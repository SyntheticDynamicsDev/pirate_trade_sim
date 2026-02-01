from __future__ import annotations
import math
import os
import random
import pygame
from typing import Optional, Dict
from dataclasses import dataclass, field
from data.loader import EnemyDef
from settings import TIME_SCALE_1X, TIME_SCALE_2X, TIME_SCALE_4X


# -----------------------------
# Data / Definitions (v1)
# -----------------------------

@dataclass
class PlayerStats:
    cannon_damage_mult: float = 1.0
    reload_mult: float = 1.0
    boarding_damage_mult: float = 1.0
    repair_mult: float = 1.0
    evade_mult: float = 1.0
    flee_mult: float = 1.0


@dataclass
class CombatantRuntime:
    name: str

    # Defensive
    hp: int
    hp_max: int
    armor_physical: float  # percent
    armor_abyssal: float   # percent

    # Offensive
    damage_min: int
    damage_max: int
    damage_type: str       # "physical" | "abyssal"
    penetration: float     # percent, can exceed 100
    crit_chance: float     # 0..1
    crit_multiplier: float # e.g. 1.5, 2.0

    # Tempo
    initiative_base: float

    # Meta
    difficulty_tier: int
    threat_level: int

    # Status effects
    status: dict = field(default_factory=dict)

@dataclass
class _FloatText:
    text: str
    x: float
    y: float
    vy: float
    ttl: float
    color: tuple[int, int, int]


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    ttl: float
    size: int
    color: tuple[int, int, int]

class CombatEngine:
    """
    MVP-Engine:
    - distance in [0..1], 0 = Boarding-Reichweite, 1 = weit weg
    - Aktionen via trigger_* Methoden
    - update(sim_dt) tickt cooldowns und simple enemy AI
    """

    def __init__(self, player: CombatantRuntime, enemy: CombatantRuntime, pstats: PlayerStats):
        self.p = player
        self.e = enemy
        self.pstats = pstats

        self.log: list[str] = []
        self.finished: bool = False
        self.outcome: Optional[str] = None  # "win" | "lose" | "flee"

        #Reward
        self.rewards = {"gold": 0, "xp": 0, "cargo": []}  # cargo: list[tuple[good_id, tons]]

        # --- AI state ---
        self.turn = 1
        self._events: list[dict] = []

        # Runden-Tracking (future-proof)
        self.round_index: int = 0
        self.turn_owner: str = "player"   # "player" | "enemy"
        self._turn_queue: list[str] = []
        self.last_initiative: dict = {"player": 0.0, "enemy": 0.0}

    def pop_event(self) -> Optional[dict]:
        if not self._events:
            return None
        return self._events.pop(0)

    def add_event(self, ev: dict) -> None:
        # kompatibel zu pop_event()
        if not hasattr(self, "_events") or self._events is None:
            self._events = []
        self._events.append(ev)

    def player_fire(self) -> bool:
        # Unified turn-based API (keine Legacy await/turn mehr)
        if self.finished or self.turn_owner != "player":
            return False

        res = self._fire(attacker=self.p, defender=self.e, mult=1.0)
        self.add_event({"type": "fire", "side": "player", "result": res.get("result"), "hull": int(res.get("hull", 0)), "applied": list(res.get("applied", []))})
        self.add_log(f"You fire: -{int(res.get('hull', 0))} hull.")

        if self._check_finish():
            self._stop_turns()
            return True

        self._advance_turn()
        return True


    def player_attack(self) -> bool:
        # Backward compatibility: route to player_fire()
        return self.player_fire()


    def player_repair(self) -> bool:
        if self.finished or self.turn_owner != "player":
            return False

        # nur wenn nicht full hp
        if self.p.hp >= self.p.hp_max:
            return False

        # kleine feste Heilung (Phase 2), später scaling
        amount = max(1, int(round(self.p.hp_max * 0.12)))
        self.p.hp = min(self.p.hp_max, self.p.hp + amount)
        self.add_event({"type": "repair", "side": "player", "amount": amount})

        self._advance_turn()
        return True

    def player_flee(self) -> bool:
        if self.finished or self.turn_owner != "player":
            return False
        # Phase 2: 50/50 oder konstant 35% je nach tier
        chance = 0.45
        ok = (random.random() < chance)
        self.add_event({"type": "flee", "side": "player", "ok": ok})
        if ok:
            self.finished = True
            self.outcome = "flee"
            self.rewards = {}
            return True

        # miss flee kostet turn
        self._advance_turn()
        return False

    def _compute_rewards(self) -> dict:
        # sauber am neuen Modell orientiert
        dmg_avg = (self.e.damage_min + self.e.damage_max) * 0.5
        armor_avg = (self.e.armor_physical + self.e.armor_abyssal) * 0.5

        danger = (
            self.e.hp_max * 0.35 +
            dmg_avg * 6.0 +
            armor_avg * 1.2 +
            self.e.threat_level * 35.0 +
            self.e.difficulty_tier * 25.0
        )
        gold = int(8 + danger * 0.12)
        xp = int(4 + danger * 0.09)

        # cargo-drops machen wir später datengetrieben (EnemyDef.loot.cargo)
        return {"gold": gold, "xp": xp, "cargo": []}
    
    def add_log(self, msg: str) -> None:
        self.log.append(msg)
        if len(self.log) > 10:
            self.log = self.log[-10:]

    def update(self, dt: float) -> None:
        if self.finished:
            return

        # check for death after DOT
        if self._check_finish():
            self._stop_turns()
            return

        # Turn-based round init
        if self.round_index == 0 or not self._turn_queue:
            self._start_new_round()

        # enemy auto-turn (max 1 action per frame)
        if self.turn_owner == "enemy":
            self._enemy_take_turn()
            return

    def _stop_turns(self) -> None:
        self._turn_queue = []
        self.turn_owner = "none"

    def _apply_status(self, target: CombatantRuntime, key: str, payload: dict) -> bool:
        """
        Returns True if status was newly applied, False if refreshed/updated.
        """
        if key not in target.status:
            target.status[key] = dict(payload)
            return True

        # refresh duration (keep strongest values if needed)
        target.status[key]["dur"] = max(target.status[key].get("dur", 0.0), payload.get("dur", 0.0))
        # merge known numeric fields (simple: max)
        for k, v in payload.items():
            if k == "dur":
                continue
            try:
                target.status[key][k] = max(float(target.status[key].get(k, 0.0)), float(v))
            except Exception:
                target.status[key][k] = v
        return False


    def _remove_status(self, target: CombatantRuntime, key: str) -> None:
        if key in target.status:
            del target.status[key]

    def _tick_statuses(self, target: CombatantRuntime, sim_dt: float) -> None:
        if not target.status:
            return

        to_remove = []

        # Leak: hull DOT
        leak = target.status.get("leak")
        if leak:
            dps = float(leak.get("dps", self.LEAK_DPS))
            dmg = max(0, int(dps * sim_dt))
            # ensure DOT does something even on small dt
            if dmg == 0 and sim_dt > 0:
                # probabilistic 1 hp tick
                if random.random() < (dps * sim_dt):
                    dmg = 1
            if dmg > 0 and target.hp > 0:
                target.hp = max(0, target.hp - dmg)


            leak["dur"] = float(leak.get("dur", 0.0)) - sim_dt
            if leak["dur"] <= 0.0:
                to_remove.append("leak")

        # Shaken: just duration (effect applied via reload multiplier)
        shaken = target.status.get("shaken")
        if shaken:
            shaken["dur"] = float(shaken.get("dur", 0.0)) - sim_dt
            if shaken["dur"] <= 0.0:
                to_remove.append("shaken")

        for k in to_remove:
            self._remove_status(target, k)


    # ---- Player actions ----


    def _roll_initiative(self, base: float) -> float:
        # kleine, faire Varianz pro Runde (±8%)
        jitter = random.uniform(-0.08, 0.08)
        return max(0.05, base * (1.0 + jitter))

    def _start_new_round(self) -> None:
        self.round_index += 1

        ip = self._roll_initiative(self.p.initiative_base)
        ie = self._roll_initiative(self.e.initiative_base)
        self.last_initiative = {"player": ip, "enemy": ie}

        if ip >= ie:
            self._turn_queue = ["player", "enemy"]
        else:
            self._turn_queue = ["enemy", "player"]

        self.turn_owner = self._turn_queue[0]
        self.add_log(f"Round {self.round_index}: init P={ip:.2f} vs E={ie:.2f} → {self.turn_owner} first")


    def _fire(self, attacker: CombatantRuntime, defender: CombatantRuntime, mult: float) -> dict:
        """
        Feste Damage-Auflösung (verbindliche Reihenfolge, keine Sonderfälle):
        1) Damage-Roll [min..max]
        2) Crit-Check -> damage *= crit_multiplier
        3) Damage-Typ bestimmen
        4) Ziel-Armor bestimmen
        5) Penetration abziehen (Armor kann negativ werden)
        6) Final Damage = HP-Verlust
        """
        # 1) Damage roll
        dmin = int(attacker.damage_min)
        dmax = int(attacker.damage_max)
        if dmax < dmin:
            dmax = dmin
        base = random.randint(dmin, dmax)

        # 2) Crit check
        cc = float(attacker.crit_chance)
        cm = float(attacker.crit_multiplier)
        is_crit = (random.random() < max(0.0, min(1.0, cc)))
        if is_crit:
            base = int(round(base * max(1.0, cm)))

        # 3) Damage type
        dtype = str(attacker.damage_type)

        # 4) Target armor by type
        armor = float(defender.armor_physical) if dtype == "physical" else float(defender.armor_abyssal)

        # 5) Penetration subtract (armor may become negative)
        pen = float(attacker.penetration)
        effective_armor = armor - pen

        # 6) Convert armor% into multiplier (positive reduces, negative amplifies)
        # Beispiel: 30 armor -> 0.70 dmg, -20 armor -> 1.20 dmg
        dmg_mult_from_armor = 1.0 - (effective_armor / 100.0)

        # final damage (mult bleibt als hook, aber keine Sonderfälle)
        dmg = int(round(base * float(mult) * dmg_mult_from_armor))
        if dmg < 1:
            dmg = 1

        defender.hp = max(0, int(defender.hp) - dmg)

        return {
            "result": "crit" if is_crit else "hit",
            "hull": dmg,  # UI-Key beibehalten
            "applied": [],
            "damage_type": dtype,
            "armor": armor,
            "penetration": pen,
            "effective_armor": effective_armor,
        }


    def _repair(self, target: CombatantRuntime, amount_base: int) -> None:
        if target.hp <= 0:
            return
        target.hp = min(target.hp_max, target.hp + max(1, amount_base))

    def _enemy_take_turn(self) -> None:
        if self.finished:
            return

        res = self._fire(attacker=self.e, defender=self.p, mult=1.0)
        self.add_event({
            "type": "fire",
            "side": "enemy",
            "result": res.get("result"),
            "hull": int(res.get("hull", 0)),
            "applied": list(res.get("applied", [])),
        })


        if self._check_finish():
            self._stop_turns()
            return

        self._advance_turn()

    def _advance_turn(self) -> None:
        if not self._turn_queue:
            self._start_new_round()
            return

        # entferne aktuellen Spieler aus Queue
        cur = self._turn_queue.pop(0) if self._turn_queue else None

        if not self._turn_queue:
            # Runde vorbei → neue Runde
            self._start_new_round()
        else:
            self.turn_owner = self._turn_queue[0]

    def _check_finish(self) -> bool:
        if self.e.hp <= 0:
            self.finished = True
            self.outcome = "win"
            self.rewards = self._compute_rewards()
            self.add_log("Enemy defeated!")
            self._stop_turns()
            return True

        if self.p.hp <= 0:
            self.finished = True
            self.outcome = "lose"
            self.rewards = {}
            self.add_log("You were defeated!")
            self._stop_turns()
            return True

        return False

# -----------------------------
# State
# -----------------------------

@dataclass
class CombatState:
    enemy_id: str
    game = None
    ctx = None
    font: Optional[pygame.font.Font] = None
    

    def on_enter(self) -> None:
        from core.ui_text import FontBank, TextStyle, render_text
        from settings import UI_FONT_PATH, UI_FONT_FALLBACK

        self._fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)
        self.font = self._fonts.get(18)
        self.small = self._fonts.get(14)
        
        self.engine = None

        self._pending_rewards = {"gold": 0, "xp": 0, "cargo": []}

        # Ensure player stats exist (future-proof anchor for your Skilltree)
        if not hasattr(self.ctx, "player_stats") or self.ctx.player_stats is None:
            self.ctx.player_stats = PlayerStats()

        # Sprite cache
        if not hasattr(self, "_sprite_cache"):
            self._sprite_cache = {}

        # --- Build player combatant from NEW ShipDef.combat ---
        ship = self.ctx.player.ship
        shipdef = self.ctx.content.ships.get(ship.id)
        if shipdef is None:
            raise KeyError(f"ShipDef not found for type_id='{ship.id}'")

        # NEW: shipdef.combat ist verpflichtend
        c = getattr(shipdef, "combat", None)
        if c is None:
            raise ValueError(f"ShipDef '{shipdef.id}' missing required .combat stats (ships.json/loader mismatch).")

        # HP: current HP comes from runtime ship, max from definition
        # (Falls du dein Ship-Runtime Feld schon umbenannt hast, ist 'hp' korrekt;
        #  wir lassen hull_hp als Fallback, damit du nicht sofort abstürzt, falls irgendwo noch Altstände sind.)
        hp_cur = int(getattr(ship, "hp", getattr(ship, "hull_hp", 0)) or 0)
        hp_max = int(getattr(c, "hp_max", 1) or 1)
        if hp_cur <= 0:
            hp_cur = hp_max
        hp_max = max(hp_max, hp_cur)

        self._player = CombatantRuntime(
            name="You",

            hp=hp_cur,
            hp_max=hp_max,

            armor_physical=float(getattr(c, "armor_physical", 0.0)),
            armor_abyssal=float(getattr(c, "armor_abyssal", 0.0)),

            damage_min=int(getattr(c, "damage_min", 1)),
            damage_max=int(getattr(c, "damage_max", 1)),
            damage_type=str(getattr(c, "damage_type", "physical")),
            penetration=float(getattr(c, "penetration", 0.0)),
            crit_chance=float(getattr(c, "crit_chance", 0.0)),
            crit_multiplier=float(getattr(c, "crit_multiplier", 1.5)),

            initiative_base=float(getattr(c, "initiative_base", 1.0)),

            difficulty_tier=int(getattr(c, "difficulty_tier", 1)),
            threat_level=int(getattr(c, "threat_level", 1)),
        )

        ed = self.ctx.content.enemies.get(self.enemy_id)
        # kein fallback mehr: enemy_id muss existieren
        self._enemy = CombatantRuntime(
            name=ed.name,

            hp=int(ed.combat.hp_max),
            hp_max=int(ed.combat.hp_max),
            armor_physical=float(ed.combat.armor_physical),
            armor_abyssal=float(ed.combat.armor_abyssal),

            damage_min=int(ed.combat.damage_min),
            damage_max=int(ed.combat.damage_max),
            damage_type=str(ed.combat.damage_type),
            penetration=float(ed.combat.penetration),
            crit_chance=float(ed.combat.crit_chance),
            crit_multiplier=float(ed.combat.crit_multiplier),

            initiative_base=float(ed.combat.initiative_base),

            difficulty_tier=int(ed.combat.difficulty_tier),
            threat_level=int(ed.combat.threat_level),
        )


        self.engine = CombatEngine(self._player, self._enemy, self.ctx.player_stats)

        # UI rects
        self.btn_fire  = pygame.Rect(60, 520, 140, 44)
        self.btn_repair= pygame.Rect(220, 520, 140, 44)
        self.btn_flee  = pygame.Rect(540, 520, 140, 44)

        # --- Result overlay state ---
        self._result_showing = False
        self._result_timer = 0.0
        self._result_applied = False

        # --- Icon cache (goods) ---
        self._good_icon_cache = {}
        self._icon_size = 32  # passt gut zu deiner Zeilenhöhe


        # --- UI metrics (fixes _line_height crash + consistent spacing) ---
        self._line_height = 26

        # --- Scene / VFX ---
        self._float_texts: list[_FloatText] = []
        self._particles: list[_Particle] = []
        self._shake_t = 0.0
        self._shake_amp = 0.0

        self._t = 0.0  # local anim time

        # background selection (by enemy tags if available)
        self._bg = self._load_combat_background()

        # --- Visuals: NEW schema via ship_def.visual ---
        ship_def = self.ctx.content.ships[self.ctx.player.ship.id]
        enemy_def = self.ctx.content.enemies[self.enemy_id]

        v = getattr(ship_def, "visual", None)
        if v is None:
            raise ValueError(f"ShipDef '{ship_def.id}' missing required .visual (ships.json/loader mismatch).")

        self._player_vis = {
            "sprite": str(getattr(v, "sprite")),
            "size": tuple(getattr(v, "size", (260, 160))),
            "scale": float(getattr(v, "scale", 1.0)),
            "offset": tuple(getattr(v, "offset", (0, 0))),
            "flip_x": bool(getattr(v, "flip_x", False)),
        }

        # --- Music: override world playlist with fight track ---
        fight_track = os.path.join("assets", "music", "fight.mp3")
        self.ctx.audio.push_music([fight_track], shuffle=False, fade_ms=800)

        self._enemy_vis = {
            "sprite": enemy_def.sprite,  # kommt aus enemies.json -> visual.sprite
            "size": tuple(getattr(enemy_def, "sprite_size", (260, 160))),
            "scale": float(getattr(enemy_def, "sprite_scale", 1.0)),
            "offset": tuple(getattr(enemy_def, "sprite_offset", (0, 0))),
            "flip_x": bool(getattr(enemy_def, "sprite_flip_x", True)),
        }

        self._spr_player = self._load_sprite_spec(self._player_vis)
        self._spr_enemy  = self._load_sprite_spec(self._enemy_vis)

        self._reveal = getattr(self.ctx, "transition_reveal", None)
        if self._reveal:
            # consume it so it doesn't apply repeatedly
            self.ctx.transition_reveal = None

            # --- sanitize reveal so it cannot lock the screen black ---
            try:
                self._reveal["t"] = 0.0  # reset time
                dur = float(self._reveal.get("duration", 0.85))
                # clamp duration to sane range (prevents "permanent black")
                dur = max(0.25, min(0.95, dur))
                self._reveal["duration"] = dur
            except Exception:
                self._reveal = None



        from settings import MASTER_LIFE_ICON
        self._ml_icon = None
        try:
            if os.path.exists(MASTER_LIFE_ICON):
                self._ml_icon = pygame.image.load(MASTER_LIFE_ICON).convert_alpha()
        except Exception:
            self._ml_icon = None


    def _resolve_player_visual(self) -> dict:
        ship = self.ctx.player.ship
        shipdef = self.ctx.content.ships.get(ship.id)

        # wir versuchen mehrere mögliche Feldnamen (damit es zu deinem bestehenden Content passt)
        cand = [
            getattr(ship, "sprite", None),
            getattr(ship, "sprite_path", None),
            getattr(ship, "image", None),
            getattr(shipdef, "sprite", None) if shipdef else None,
            getattr(shipdef, "sprite_path", None) if shipdef else None,
            getattr(shipdef, "image", None) if shipdef else None,
            getattr(shipdef, "icon", None) if shipdef else None,
        ]
        sprite = next((c for c in cand if c), None)

        # Defaults (kannst du später feinjustieren)
        size = getattr(shipdef, "sprite_size", None) if shipdef else None
        if not size:
            size = (260, 160)

        scale = float(getattr(shipdef, "sprite_scale", 1.0) if shipdef else 1.0)
        offset = getattr(shipdef, "sprite_offset", (0, 0)) if shipdef else (0, 0)

        return {
            "sprite": sprite,
            "size": tuple(size),
            "scale": scale,
            "offset": tuple(offset),
            "flip_x": False,   # player schaut nach rechts
        }

    def _resolve_enemy_visual(self, ed) -> dict:
        # ed kommt aus ctx.content.enemies -> EnemyDef
        sprite = getattr(ed, "sprite", None)
        size = tuple(getattr(ed, "sprite_size", (260, 160)))
        scale = float(getattr(ed, "sprite_scale", 1.0))
        offset = tuple(getattr(ed, "sprite_offset", (0, 0)))
        flip_x = bool(getattr(ed, "sprite_flip_x", True))

        return {
            "sprite": sprite,
            "size": size,
            "scale": scale,
            "offset": offset,
            "flip_x": flip_x,
        }

    def _load_sprite_spec(self, spec: dict):
        # spec schema:
        # { "sprite": str|None, "size": (w,h), "scale": float, "offset": (x,y), "flip_x": bool }
        path = spec.get("sprite")
        if not path:
            return None

        # defaults first (so w/h always defined)
        w, h = spec.get("size", (260, 160))
        scale = float(spec.get("scale", 1.0))
        w = max(1, int(w * scale))
        h = max(1, int(h * scale))

        # init cache if missing
        if not hasattr(self, "_sprite_cache"):
            self._sprite_cache = {}

        key = (path, w, h)
        cached = self._sprite_cache.get(key)
        if cached is not None:
            return cached

        try:
            img = pygame.image.load(path).convert_alpha()
        except Exception:
            # cache negative result to avoid repeated disk hits
            self._sprite_cache[key] = None
            return None

        surf = pygame.transform.smoothscale(img, (w, h))
        self._sprite_cache[key] = surf
        return surf



    def _try_load_sprite(self, path: str, size: tuple[int, int]) -> Optional[pygame.Surface]:
        try:
            if os.path.exists(path):
                img = pygame.image.load(path).convert_alpha()
                return pygame.transform.smoothscale(img, size)
        except Exception:
            pass
        return None


    def _load_combat_background(self) -> Optional[pygame.Surface]:
        """
        Loads combat background based on current world map (ctx.current_map_id).

        Expected assets (examples):
          assets/maps/world_comabat_01.png   (your current naming)
          assets/maps/world_combat_01.png    (fallback if you rename later)

        For current_map_id == "world_01" -> suffix "01"
        """
        try:
            map_id = getattr(self.ctx, "current_map_id", "world_01") or "world_01"
            suffix = map_id.split("_")[-1] if "_" in map_id else map_id

            candidates = [
                os.path.join("assets", "maps", f"world_comabat_{suffix}.png"),  # your file name
                os.path.join("assets", "maps", f"world_combat_{suffix}.png"),   # fallback spelling
                os.path.join("assets", "maps", f"{map_id}_combat.png"),         # optional convention
            ]

            p = next((c for c in candidates if os.path.exists(c)), None)
            if not p:
                return None

            img = pygame.image.load(p).convert()

            # scale to current screen once
            surf = pygame.display.get_surface()
            if surf:
                w, h = surf.get_size()
            else:
                w, h = 960, 720

            return pygame.transform.smoothscale(img, (w, h))
        except Exception:
            return None


    def _get_good_icon(self, good_id: str):
        import os
        if not good_id:
            return None

        if good_id in self._good_icon_cache:
            return self._good_icon_cache[good_id]

        # Standard: assets/icons/<good_id>.png
        base = os.path.join("assets", "icons")
        candidates = [
            os.path.join(base, f"{good_id}.png"),
            os.path.join(base, good_id, "icon.png"),  # optionaler Fallback
        ]

        surf = None
        for path in candidates:
            if os.path.exists(path):
                try:
                    img = pygame.image.load(path).convert_alpha()
                    surf = pygame.transform.smoothscale(img, (self._icon_size, self._icon_size))
                    break
                except Exception:
                    surf = None

        self._good_icon_cache[good_id] = surf
        return surf

    def _get_ship_hp(self) -> int:
        ship = self.ctx.player.ship
        return int(getattr(ship, "hp", getattr(ship, "hull_hp", 0)) or 0)

    def _set_ship_hp(self, value: int) -> None:
        ship = self.ctx.player.ship
        if hasattr(ship, "hp"):
            ship.hp = int(value)
        else:
            # Fallback nur falls irgendwo noch Alt-Model im Umlauf ist
            ship.hp = int(value)

    def on_exit(self) -> None:
        # --- Music: restore previous (world) playlist ---
        try:
            self.ctx.audio.pop_music(fade_ms=800)
        except Exception:
            pass
        # Persist back to world model
        self._set_ship_hp(int(self._player.hp))

    def _apply_outcome(self) -> None:
        # Persist HPs (redundant zu on_exit ist ok)
        self._set_ship_hp(int(self._player.hp))

        if self.engine.outcome == "lose":
            # 1) Masterleben abziehen
            p = self.ctx.player
            p.master_lives = int(getattr(p, "master_lives", 3)) - 1
            p.master_lives = max(0, p.master_lives)

            # 2) Wenn keine Masterleben mehr -> Game Over Transition
            if p.master_lives <= 0:
                # Hull bleibt 0, Game endet
                try:
                    self._set_ship_hp(0)
                except Exception:
                    pass
                return

            # 3) Sonst: Hull wiederherstellen und zurück zur Welt (kein Game Over)
            # Wir nutzen das maximale Hull aus CombatRuntime
            try:
                self._set_ship_hp(int(getattr(self._player, "hp_max", 1)))

            except Exception:
                self._set_ship_hp(int(getattr(self._player, "hp_max", 1)))

            # optional: kleines “respawn” Verhalten kann später ergänzt werden
            return


        if self.engine.outcome != "win":
            return

        rewards = getattr(self, "_pending_rewards", {"gold": 0, "xp": 0, "cargo": []})
        gold = int(rewards.get("gold", 0))
        xp = int(rewards.get("xp", 0))
        cargo_drops = rewards.get("cargo", [])

        # Apply money + XP
        self.ctx.player.money += gold
        from core.progression import add_xp
        add_xp(self.ctx.player, xp)


        # Apply cargo (respect capacity)
        cap = float(getattr(self.ctx.player.ship, "capacity_tons", 0.0))
        used = float(self.ctx.player.cargo.total_tons())
        free = max(0.0, cap - used)

        for gid, tons in cargo_drops:
            if free <= 0.0:
                break
            add = min(free, float(tons))
            if add > 0:
                self.ctx.player.cargo.add_lot(gid, add)
                free -= add

    def _leave_combat(self) -> None:
        # rewards nur 1x anwenden
        if not getattr(self, "_result_applied", False):
            try:
                self._apply_outcome()
            except Exception:
                # fail-safe: lieber rausgehen als soft-lock
                pass
            self._result_applied = True

        # Snapshot für Transition (ohne UI reicht)
        try:
            w, h = self.ctx.screen.get_size()
            snap = pygame.Surface((w, h))
            self._render_scene(snap)
        except Exception:
            snap = None

        # Wenn der Spieler verloren hat und Masterleben = 0 -> Losing Transition
        from states.transition import TransitionState
        # snapshot wird bereits gebaut -> snap

        p = self.ctx.player
        ml = int(getattr(p, "master_lives", 0))

        if getattr(self.engine, "outcome", None) == "lose" and ml <= 0:
            from states.lose import LoseState
            self.game.replace(LoseState(snapshot=snap))
            return


        self.game.replace(TransitionState(kind="to_world", snapshot=snap, focus=None))
    # combat.py | class CombatState

    def _build_rewards_from_enemydef(self, ed) -> dict:
        loot = getattr(ed, "loot", None)
        if loot is None:
            return {"gold": 0, "xp": 0, "cargo": []}

        # einfache Skalierung über threat/difficulty
        tl = int(getattr(ed.combat, "threat_level", 1))
        dt = int(getattr(ed.combat, "difficulty_tier", 1))
        mult_factor = 1.0 + 0.15 * (tl - 1) + 0.10 * (dt - 1)

        gold = int(round(int(getattr(loot, "gold_base", 0)) + int(getattr(loot, "gold_base", 0)) * float(getattr(loot, "gold_mult", 0.0)) * mult_factor))
        xp   = int(round(int(getattr(loot, "xp_base", 0))   + int(getattr(loot, "xp_base", 0))   * float(getattr(loot, "xp_mult", 0.0))   * mult_factor))

        cargo = self._roll_enemy_cargo_loot(ed)
        return {"gold": max(0, gold), "xp": max(0, xp), "cargo": cargo}


    def _roll_enemy_cargo_loot(self, ed) -> list:
        import random
        if ed is None:
            return []
        loot = getattr(ed, "loot", None)
        if loot is None:
            return []

        drops = []
        for entry in loot.cargo:
            if random.random() <= float(entry.chance):
                tons = random.uniform(float(entry.min_tons), float(entry.max_tons))
                # safety: only allow existing goods
                if entry.good_id in self.ctx.content.goods:
                    drops.append((entry.good_id, round(float(tons), 2)))
        return drops


    def handle_event(self, event) -> None:

        # Wenn Ergebnis-Overlay aktiv, nur Exit-Input erlauben
        if getattr(self, "_result_showing", False):
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                self._leave_combat()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._leave_combat()
            return

        # Block input wenn nicht Player-Turn
        if getattr(self, "engine", None) and getattr(self.engine, "turn_owner", None) != "player":
            # optional: trotzdem Pause erlauben
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                self.ctx.clock.paused = not self.ctx.clock.paused
            return


        #Buttons
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.ctx.clock.paused = not self.ctx.clock.paused

        #Mouse
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            # Action control
            if self.btn_fire.collidepoint(mx, my):
                self.engine.player_fire()
            elif self.btn_repair.collidepoint(mx, my):
                self.engine.player_repair()
            elif self.btn_flee.collidepoint(mx, my):
                self.engine.player_flee()

    def _cycle_time_speed(self) -> None:
        if self.ctx.clock.paused:
            self.ctx.clock.paused = False
            self.ctx.clock.time_scale = TIME_SCALE_1X
            return

        ts = float(getattr(self.ctx.clock, "time_scale", TIME_SCALE_1X))
        if ts < 1.5:
            self.ctx.clock.time_scale = TIME_SCALE_2X
        elif ts < 3.0:
            self.ctx.clock.time_scale = TIME_SCALE_4X
        else:
            self.ctx.clock.paused = True

    def update(self, dt: float) -> None:
        # 1) Engine tick (Turn-Logik + Events)
        if getattr(self, "engine", None) is None:
            return

        #bobbing
        self._t = float(getattr(self, "_t", 0.0)) + float(dt)

        # Wenn Ergebnis schon angezeigt wird, keine weiteren Turns/Enemy-Aktionen ausführen
        if getattr(self, "_result_showing", False):
            # Reveal weiter ticken lassen, damit es nicht schwarz bleibt
            if getattr(self, "_reveal", None):
                self._reveal["t"] = float(self._reveal.get("t", 0.0)) + float(dt)
                dur = float(self._reveal.get("duration", 0.85))
                if self._reveal["t"] >= dur:
                    self._reveal = None
            return

        self.engine.update(dt)

        # VFX events konsumieren (damit Treffer/Repair etc. sichtbar werden)
        while True:
            ev = self.engine.pop_event()
            if not ev:
                break
            self._handle_vfx_event(ev)

        if self.engine.finished and not getattr(self, "_result_showing", False):
            # Payload/Rewards nur einmal bauen
            if getattr(self.engine, "outcome", None) == "win":
                ed = self.ctx.content.enemies[self.enemy_id]
                self._pending_rewards = self._build_rewards_from_enemydef(ed)

                lines = []
                gold = int(self._pending_rewards.get("gold", 0))
                xp = int(self._pending_rewards.get("xp", 0))
                cargo = self._pending_rewards.get("cargo", []) or []

                if gold:
                    lines.append(("gold", f"+{gold} Gold"))
                if xp:
                    lines.append(("xp", f"+{xp} XP"))
                for gid, tons in cargo:
                    lines.append(("cargo", f"+{tons:.2f} t {gid}", gid))

                self._result_payload = {"title": "VICTORY", "lines": lines}

            elif getattr(self.engine, "outcome", None) == "lose":
                self._result_payload = {"title": "DEFEAT", "lines": [("cargo", "You lost the battle.")]}
            else:
                self._result_payload = {"title": "ESCAPED", "lines": [("cargo", "You fled successfully.")]}  # fallback

            self._result_showing = True
            self._result_timer = 0.0
            self._result_applied = False

        # 2) Reveal-Overlay Timer (sonst bleibt der Screen schwarz)
        if getattr(self, "_reveal", None):
            self._reveal["t"] = float(self._reveal.get("t", 0.0)) + float(dt)
            dur = float(self._reveal.get("duration", 0.85))
            if self._reveal["t"] >= dur:
                self._reveal = None

    def _handle_vfx_event(self, ev: dict) -> None:
        et = ev.get("type")
        side = ev.get("side")  # "player" | "enemy"

        # anchor positions in scene space (not UI space)
        # We keep it simple: left ship center, right ship center
        W, H = 960, 720
        try:
            W = self.ctx.screen.get_width()
            H = self.ctx.screen.get_height()
        except Exception:
            pass

        # distance affects spacing
        mid_y = int(H * 0.45)
        left_x  = int(W * 0.28)
        right_x = int(W * 0.72)


        src = (left_x, mid_y) if side == "player" else (right_x, mid_y)
        dst = (right_x, mid_y) if side == "player" else (left_x, mid_y)

        def add_float(text, x, y, color):
            self._float_texts.append(_FloatText(text=text, x=float(x), y=float(y), vy=-22.0, ttl=1.05, color=color))

        def add_burst(x, y, base_color):
            for _ in range(14):
                vx = random.uniform(-90, 90)
                vy = random.uniform(-120, 60)
                self._particles.append(_Particle(x=float(x), y=float(y), vx=vx, vy=vy, ttl=random.uniform(0.25, 0.55), size=random.randint(1, 3), color=base_color))

        if et == "fire":
            res = ev.get("result", "hit")

            # Muzzle flash (small burst at src)
            add_burst(src[0], src[1], (240, 220, 140))

            # Impact burst at dst for hits/grazes/crits
            hull = int(ev.get("hull", 0))

            if res != "miss":
                # more intense on crit
                if res == "crit":
                    add_burst(dst[0], dst[1], (255, 190, 110))
                    self._start_shake(0.18, 6.0 if side == "enemy" else 4.5)
                elif res == "graze":
                    add_burst(dst[0], dst[1], (210, 210, 210))
                    self._start_shake(0.10, 3.5)
                else:
                    add_burst(dst[0], dst[1], (255, 150, 90))
                    self._start_shake(0.12, 4.0)
            else:
                # a miss still gets a small splash near dst
                add_burst(dst[0] + random.randint(-20, 20), dst[1] + random.randint(10, 30), (140, 160, 180))

            # Damage numbers
            if hull > 0:
                add_float(f"-{hull}", dst[0] + random.randint(-10, 10), dst[1] - 40, (240, 120, 110))

        elif et == "board":
            hull = int(ev.get("hull", 0))
            # boarding: close-range impact feel
            add_burst(dst[0], dst[1] - 10, (220, 220, 220))
            self._start_shake(0.12, 4.5)
            if hull > 0:
                add_float(f"-{hull}", dst[0], dst[1] - 48, (255, 150, 110))

        elif et == "repair":
            amt = int(ev.get("amount", 0))
            add_burst(src[0], src[1] - 10, (120, 220, 150))
            add_float(f"+{amt}", src[0], src[1] - 40, (140, 240, 170))

        elif et == "flee":
            ok = bool(ev.get("success", ev.get("ok", False)))
            add_float("ESCAPE!" if ok else "FAILED!", src[0], src[1] - 40, (200, 200, 240) if ok else (240, 140, 140))


    def _start_shake(self, dur: float, amp: float) -> None:
        self._shake_t = max(self._shake_t, float(dur))
        self._shake_amp = max(self._shake_amp, float(amp))


    def render(self, screen: pygame.Surface) -> None:
        # --- Screen shake offset ---
        ox, oy = 0, 0
        if getattr(self, "_shake_t", 0.0) > 0.0 and getattr(self, "_shake_amp", 0.0) > 0.0:
            ox = int(random.uniform(-self._shake_amp, self._shake_amp))
            oy = int(random.uniform(-self._shake_amp, self._shake_amp))

        # Scene direkt rendern (robust, kein "black overlay")
        self._render_scene(screen)


        p = self.ctx.player
        ml = int(getattr(p, "master_lives", 0))
        ml_max = int(getattr(p, "master_lives_max", 3))

        size = 56
        gap = 8

        # Beispiel: über linker UI / Barometer
        start_x = 24
        start_y = 24  # falls Combat kein Barometer hat → leicht nach unten

        if self._ml_icon is not None:
            icon = pygame.transform.smoothscale(self._ml_icon, (size, size))
            for i in range(ml_max):
                ic = icon.copy()
                if i >= ml:
                    ic.set_alpha(70)
                screen.blit(ic, (start_x + i * (size + gap), start_y))
        else:
            for i in range(ml_max):
                col = (220, 220, 220) if i < ml else (120, 120, 120)
                pygame.draw.circle(
                    screen,
                    col,
                    (start_x + i * (size + gap) + size // 2, start_y + size // 2),
                    size // 2 - 4,
                )
        # Header
        ts = float(getattr(self.ctx.clock, "time_scale", 1.0))
        speed_label = "PAUSE" if self.ctx.clock.paused else f"{ts:.0f}x"
        title = self.font.render(f"COMBAT vs {self._enemy.name}   Speed: {speed_label}", True, (220, 220, 220))
        screen.blit(title, (40, 30))

        # Bars
        self._draw_bar(screen, 60, 90,  620, 18, self._player.hp, self._player.hp_max, "Your HP")

        self._draw_status_line(screen, 60, 140, self._player, "You")
        self._draw_status_line(screen, 60, 220, self._enemy, "Enemy")


        self._draw_bar(screen, 60, 170, 620, 18, self._enemy.hp, self._enemy.hp_max, "Enemy HP")

        # Buttons
        is_player_turn = (getattr(self.engine, "turn_owner", None) == "player")

        self._draw_button(
            screen, self.btn_fire, "Fire (1)",
            is_player_turn
        )

        self._draw_button(
            screen, self.btn_repair, "Repair (2)",
            is_player_turn and (self._player.hp < self._player.hp_max)
        )

        self._draw_button(
            screen, self.btn_flee, "Flee (4)",
            is_player_turn
        )

        # Log
        y = 290
        screen.blit(self.font.render("Combat Log:", True, (220, 220, 220)), (60, y))
        y += 24
        for line in self.engine.log[-8:]:
            screen.blit(self.font.render(f"- {line}", True, (190, 190, 190)), (60, y))
            y += 20

        if getattr(self, "_result_showing", False):
            self._draw_result_overlay(screen)
            t = self.font.render("ENTER / Click to continue", True, (170, 170, 170))

        self._draw_reveal_overlay(screen)

    def _draw_reveal_overlay(self, screen: pygame.Surface) -> None:
        if not getattr(self, "_reveal", None):
            return

        W, H = screen.get_size()
        t = float(self._reveal.get("t", 0.0))
        dur = float(self._reveal.get("duration", 0.85))
        p = max(0.0, min(1.0, t / max(0.001, dur)))

        # reverse: start fully black -> fade out
        black_alpha = int(255 * (1.0 - (p * p * (3.0 - 2.0 * p))))  # smoothstep

        # waves reverse: start intruded -> retract
        intrude = int(140 * (1.0 - p))

        # draw wave edges (same asset path if available)
        wave_path = self._reveal.get("wave_path")
        wave = None
        try:
            if wave_path and os.path.exists(wave_path):
                wave = pygame.image.load(wave_path).convert_alpha()
        except Exception:
            wave = None

        if intrude > 0:
            if wave is None:
                s = pygame.Surface((W, H), pygame.SRCALPHA)
                a = int(120 * (1.0 - p))
                pygame.draw.rect(s, (0, 0, 0, a), pygame.Rect(0, 0, W, intrude))
                pygame.draw.rect(s, (0, 0, 0, a), pygame.Rect(0, H - intrude, W, intrude))
                pygame.draw.rect(s, (0, 0, 0, a), pygame.Rect(0, 0, intrude, H))
                pygame.draw.rect(s, (0, 0, 0, a), pygame.Rect(W - intrude, 0, intrude, H))
                screen.blit(s, (0, 0))
            else:
                alpha = int(220 * (1.0 - p))
                wave2 = wave.copy()
                wave2.set_alpha(alpha)

                # left
                wave_l = pygame.transform.rotate(wave2, 90)
                x_left = -wave_l.get_width() + intrude
                y = 0
                while y < H:
                    screen.blit(wave_l, (x_left, y))
                    y += wave_l.get_height()

                # right
                wave_r = pygame.transform.rotate(wave2, -90)
                x_right = W - intrude
                y = 0
                while y < H:
                    screen.blit(wave_r, (x_right, y))
                    y += wave_r.get_height()

        if black_alpha > 0:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((0, 0, 0, black_alpha))
            screen.blit(veil, (0, 0))

    def _render_scene(self, screen: pygame.Surface) -> None:
        W, H = screen.get_size()

        # Background: world-map based combat background
        if getattr(self, "_bg", None):
            screen.blit(self._bg, (0, 0))
        else:
            # fallback if missing (should not happen once assets exist)
            screen.fill((18, 24, 36))

        mid_y = int(H * 0.45)
        left_x  = int(W * 0.28)
        right_x = int(W * 0.72)



        pv = self._player_vis
        ev = self._enemy_vis

        pv = self._player_vis
        ev = self._enemy_vis

        # Player
        self._draw_unit(
            screen,
            left_x + int(pv["offset"][0]),
            mid_y + int(pv["offset"][1]),
            self._spr_player,
            flip=bool(pv.get("flip_x", False)),
            scale=1.0,  # wichtig: wir haben beim Laden schon skaliert
            fallback_color=(0, 0, 0),  # wird nicht genutzt, wenn Sprites vorhanden
            label=self.ctx.player.ship.name if hasattr(self.ctx.player.ship, "name") else "YOU"
        )

        # Enemy
        self._draw_unit(
            screen,
            right_x + int(ev["offset"][0]),
            mid_y + int(ev["offset"][1]),
            self._spr_enemy,
            flip=bool(ev.get("flip_x", True)),
            scale=1.0,
            fallback_color=(0, 0, 0),
            label=self._enemy.name.upper()
        )


        # Particles + floating texts
        self._tick_and_draw_particles(screen)
        self._tick_and_draw_float_texts(screen)

    def _draw_unit(
        self,
        screen,
        x: int,
        y: int,
        spr,
        flip: bool,
        scale: float,
        fallback_color,
        label: str
    ) -> None:
        # leichte "Bobbing"-Animation
        t = float(getattr(self, "_t", 0.0))
        bob = int(math.sin(t * 2.2 + (0.0 if not flip else 1.1)) * 3.0)

        if spr:
            img = spr
            if flip:
                img = pygame.transform.flip(img, True, False)

            if abs(scale - 1.0) > 0.01:
                w = max(1, int(img.get_width() * scale))
                h = max(1, int(img.get_height() * scale))
                img = pygame.transform.smoothscale(img, (w, h))

            r = img.get_rect(center=(x, y + bob))
            screen.blit(img, r)
        else:
            # Fallback-Silhouette
            pygame.draw.ellipse(screen, fallback_color, pygame.Rect(x - 90, y - 30 + bob, 180, 60))
            pygame.draw.rect(screen, (30, 30, 35), pygame.Rect(x - 90, y - 30 + bob, 180, 60), 2)

        # Label-Plate
        plate = pygame.Rect(x - 80, y + 72, 160, 22)
        pygame.draw.rect(screen, (18, 20, 28), plate, border_radius=6)
        pygame.draw.rect(screen, (8, 9, 12), plate, 2, border_radius=6)

        txt = self.font.render(label, True, (230, 230, 230))
        screen.blit(txt, (plate.x + 8, plate.y + 3))

    def _tick_and_draw_particles(self, screen) -> None:
        if not getattr(self, "_particles", None):
            return

        dt = 1 / 60  # reicht als Render-Tick
        alive = []
        for p in self._particles:
            p.ttl -= dt
            if p.ttl <= 0:
                continue

            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy += 180 * dt  # "Gravity"

            alive.append(p)
            pygame.draw.rect(screen, p.color, pygame.Rect(int(p.x), int(p.y), p.size, p.size))

        self._particles = alive

    def _tick_and_draw_float_texts(self, screen) -> None:
        if not getattr(self, "_float_texts", None):
            return

        dt = 1 / 60
        alive = []
        for ft in self._float_texts:
            ft.ttl -= dt
            if ft.ttl <= 0:
                continue

            ft.y += ft.vy * dt
            alive.append(ft)

            s = self.font.render(ft.text, True, ft.color)
            screen.blit(s, (int(ft.x), int(ft.y)))

        self._float_texts = alive

    def _draw_status_line(self, screen, x, y, who, label: str) -> None:
        parts = []
        st = getattr(who, "status", {})
        if "leak" in st:
            parts.append(f"LEAK {st['leak']['dur']:.1f}s")
        if "shaken" in st:
            parts.append(f"SHAKEN {st['shaken']['dur']:.1f}s")

        text = f"{label} Status: " + (", ".join(parts) if parts else "None")
        surf = self.font.render(text, True, (200, 200, 200))
        screen.blit(surf, (x, y))


    def _draw_result_overlay(self, screen: pygame.Surface) -> None:
        payload = getattr(self, "_result_payload", None)
        if not payload:
            payload = {"title": "RESULT", "lines": []}

        title = payload.get("title", "RESULT")
        lines = payload.get("lines", [])
        if lines is None:
            lines = []

        # Semi-transparent dark overlay
        overlay = pygame.Surface((screen.get_width(), screen.get_height()), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))

        # Box (dynamic height)
        line_count = len(lines)
        box_w = 520
        box_h = 160 + line_count * 26
        box_h = max(220, min(560, box_h))

        x = (screen.get_width() - box_w) // 2
        y = (screen.get_height() - box_h) // 2

        pygame.draw.rect(screen, (20, 22, 30), (x, y, box_w, box_h), border_radius=16)
        pygame.draw.rect(screen, (8, 9, 12), (x, y, box_w, box_h), 2, border_radius=16)

        # Title
        title_surf = self.font.render(title, True, (240, 240, 240))
        screen.blit(title_surf, (x + 28, y + 28))

        yy = y + 80

        for item in lines:
            if len(item) == 2:
                kind, text = item
                good_id = None
            else:
                kind, text, good_id = item

            # Icon
            if kind == "cargo" and good_id:
                icon = self._get_good_icon(good_id)
                if icon:
                    screen.blit(icon, (x + 28, yy + 2))
                else:
                    self._draw_loot_icon_fallback(screen, x + 28, yy + 2, kind)
            else:
                self._draw_loot_icon_fallback(screen, x + 28, yy + 2, kind)

            # Text
            surf = self.font.render(text, True, (220, 220, 220))
            screen.blit(surf, (x + 28 + 34, yy))
            yy += 26



        # Small hint
        t = self.font.render("Returning...", True, (170, 170, 170))
        screen.blit(t, (x + 28, y + box_h - 40))

    def _draw_loot_icon_fallback(self, screen, x: int, y: int, kind: str) -> None:
        if kind == "gold":
            pygame.draw.circle(screen, (210, 190, 90), (x + 7, y + 7), 7)
            pygame.draw.circle(screen, (120, 105, 45), (x + 7, y + 7), 7, 2)
            pygame.draw.circle(screen, (240, 230, 150), (x + 5, y + 5), 2)
        elif kind == "xp":
            pts = [(x + 7, y), (x + 14, y + 7), (x + 7, y + 14), (x, y + 7)]
            pygame.draw.polygon(screen, (120, 170, 240), pts)
            pygame.draw.polygon(screen, (60, 90, 130), pts, 2)
        else:
            pygame.draw.rect(screen, (150, 110, 70), (x, y, 14, 14), border_radius=2)
            pygame.draw.rect(screen, (75, 55, 35), (x, y, 14, 14), 2, border_radius=2)
            pygame.draw.line(screen, (75, 55, 35), (x + 2, y + 4), (x + 12, y + 4), 1)
            pygame.draw.line(screen, (75, 55, 35), (x + 2, y + 9), (x + 12, y + 9), 1)

    def _draw_loot_icon(self, screen, x: int, y: int, kind: str) -> None:
        # tiny pixel-ish icons via simple shapes (no assets required)
        if kind == "gold":
            # coin: circle + highlight
            pygame.draw.circle(screen, (210, 190, 90), (x + 7, y + 7), 7)
            pygame.draw.circle(screen, (120, 105, 45), (x + 7, y + 7), 7, 2)
            pygame.draw.circle(screen, (240, 230, 150), (x + 5, y + 5), 2)
        elif kind == "xp":
            # badge/star-ish: diamond
            pts = [(x + 7, y), (x + 14, y + 7), (x + 7, y + 14), (x, y + 7)]
            pygame.draw.polygon(screen, (120, 170, 240), pts)
            pygame.draw.polygon(screen, (60, 90, 130), pts, 2)
        else:
            # cargo: crate
            pygame.draw.rect(screen, (150, 110, 70), (x, y, 14, 14), border_radius=2)
            pygame.draw.rect(screen, (75, 55, 35), (x, y, 14, 14), 2, border_radius=2)
            pygame.draw.line(screen, (75, 55, 35), (x + 2, y + 4), (x + 12, y + 4), 1)
            pygame.draw.line(screen, (75, 55, 35), (x + 2, y + 9), (x + 12, y + 9), 1)


    def _draw_bar(self, screen, x, y, w, h, val, vmax, label):
        vmax = max(1, int(vmax))
        val = max(0, min(int(val), vmax))
        frac = val / vmax

        pygame.draw.rect(screen, (50, 55, 70), pygame.Rect(x, y, w, h), border_radius=4)
        pygame.draw.rect(screen, (80, 180, 120), pygame.Rect(x, y, int(w * frac), h), border_radius=4)
        pygame.draw.rect(screen, (25, 28, 38), pygame.Rect(x, y, w, h), 2, border_radius=4)

        txt = self.font.render(f"{label}: {val}/{vmax}", True, (230, 230, 230))
        screen.blit(txt, (x, y - 20))

    def _draw_button(self, screen, rect: pygame.Rect, text: str, enabled: bool, subtext: str = ""):

        mx, my = pygame.mouse.get_pos()
        hover = rect.collidepoint(mx, my)

        # base colors
        bg = (70, 75, 95) if enabled else (45, 48, 60)
        if hover and enabled:
            bg = (82, 88, 112)

        # shadow
        shadow = rect.move(0, 3)
        pygame.draw.rect(screen, (0, 0, 0), shadow, border_radius=10)

        pygame.draw.rect(screen, bg, rect, border_radius=10)
        pygame.draw.rect(screen, (20, 22, 30), rect, 2, border_radius=10)

        # title
        t = self.font.render(text, True, (240, 240, 240) if enabled else (170, 170, 170))
        screen.blit(t, (rect.x + 12, rect.y + 10))

        # subtext
        if subtext:
            st = self.font.render(subtext, True, (210, 210, 210) if enabled else (160, 160, 160))
            screen.blit(st, (rect.x + 12, rect.y + 28))