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
    hull_hp: int
    hull_hp_max: int

    armor: int
    cannon_slots: int
    basic_attack_dmg: int
    speed_px_s: float

    # Turn-based: keine echten Cooldowns mehr nötig
    cannon_cd: float = 0.0
    repair_cd: float = 0.0

    # Status effects
    status: dict = field(default_factory=dict)  # key -> {"dur": float, ...}



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

        # Tuning
        self.CANNON_RELOAD = 3.2
        self.REPAIR_CD = 7.0

        #Reward
        self.rewards = {"gold": 0, "xp": 0, "cargo": []}  # cargo: list[tuple[good_id, tons]]

        # --- Status tuning (v1.3) ---
        self.LEAK_DPS = 2.0
        self.LEAK_DUR = 8.0
        self.LEAK_CHANCE_ON_HIT = 0.18

        self.SHAKEN_DUR = 6.0
        self.SHAKEN_RELOAD_MULT = 1.35  # 35% slower reload


        self.GRAZE_BAND = 0.10  # wie nah am hit-chance threshold -> graze
        self.CRIT_CHANCE = 0.08

        # --- Visual Event Queue (for VFX/UI feedback) ---
        self._events: list[dict] = []

        # --- AI state ---
        self.turn = 1
        self.awaiting_player = True
        self._events: list[dict] = []

    def push_event(self, ev: dict) -> None:
        self._events.append(ev)
        # keep it bounded
        if len(self._events) > 30:
            self._events = self._events[-30:]


    def pop_event(self) -> Optional[dict]:
        if not self._events:
            return None
        return self._events.pop(0)

    def player_fire(self) -> None:
        if self.finished or not self.awaiting_player:
            return

        res = self._fire(attacker=self.p, defender=self.e, mult=1.0)

        # Event für VFX
        self.push_event({
            "type": "fire",
            "side": "player",
            "result": res.get("result", "hit"),
            "hull": int(res.get("hull", 0)),
            "applied": list(res.get("applied", [])),
            "hit_chance": float(res.get("hit_chance", 0.0)),
        })

        self.add_log(f"You fire: -{int(res.get('hull', 0))} hull.")
        self._after_player_action()


    def player_repair(self) -> None:
        if self.finished or not self.awaiting_player:
            return

        amt = int(22 * float(getattr(self.pstats, "repair_mult", 1.0)))
        self._repair(self.p, amount_base=amt)

        self.push_event({"type": "repair", "side": "player", "amount": amt})
        self.add_log("You repair.")
        self._after_player_action()


    def player_flee(self) -> None:
        if self.finished or not self.awaiting_player:
            return
        # einfache flee chance, später skilltree stats einbauen
        chance = 0.35 * float(getattr(self.pstats, "flee_mult", 1.0))
        if random.random() < chance:
            self.finished = True
            self.outcome = "flee"
            self._events.append({"type": "flee", "side": "player", "result": "success"})
            return
        else:
            self._events.append({"type": "flee", "side": "player", "result": "fail"})
            self._after_player_action()


    def _compute_rewards(self) -> dict:
        danger = (self.e.hull_hp_max * 0.8 + self.e.cannon_slots * 18 + self.e.armor * 6)
        gold = int(10 + danger * 0.12)
        xp = int(5 + danger * 0.08)
        return {"gold": gold, "xp": xp, "cargo": []}



    
    def add_log(self, msg: str) -> None:
        self.log.append(msg)
        if len(self.log) > 10:
            self.log = self.log[-10:]

    def update(self, sim_dt: float) -> None:
        # Turn-based: keine dt-getriebene Simulation
        return


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
            if dmg > 0 and target.hull_hp > 0:
                target.hull_hp = max(0, target.hull_hp - dmg)

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

    def _reload_mult_for(self, who: CombatantRuntime, base_reload_mult: float) -> float:
        mult = float(base_reload_mult)
        if "shaken" in who.status:
            mult *= float(who.status["shaken"].get("reload_mult", self.SHAKEN_RELOAD_MULT))
        return max(0.2, mult)

    def _enemy_ai(self, sim_dt: float) -> None:
        return

    # ---- Player actions ----

    def _hit_chance(self, attacker: CombatantRuntime, defender: CombatantRuntime) -> float:
        # Turn-based, keine Distanz mehr: stabile Trefferchance
        base = 0.78

        # kleine Varianz durch Speed (optional, aber deterministisch genug)
        spd_att = float(getattr(attacker, "speed_px_s", 150.0))
        spd_def = float(getattr(defender, "speed_px_s", 150.0))
        diff = max(-80.0, min(80.0, spd_att - spd_def))
        base += (diff / 80.0) * 0.06  # max +/- 6%

        return max(0.15, min(0.95, base))



    def _fire(self, attacker: CombatantRuntime, defender: CombatantRuntime, mult: float) -> dict:
        applied = []

        hc = self._hit_chance(attacker, defender)
        roll = random.random()

        # Determine graze vs solid hit
        graze = (hc - roll) < self.GRAZE_BAND
        crit = (not graze) and (random.random() < self.CRIT_CHANCE)

        result_tag = "graze" if graze else ("crit" if crit else "hit")

        # --- HIT (turn-based) ---
        raw = int(getattr(attacker, "basic_attack_dmg", 10) or 10)

        # Heuristik: sehr große Werte (wie 300 in ships.json) sind vermutlich "DPS/old system"
        # -> für Turn-based stark skalieren
        if raw >= 80:
            raw = int(raw * 0.10)  # 300 -> 30
            raw = max(8, raw)

        # Kanonen sollen im Turn-System mehr Gewicht haben
        base = raw + int(attacker.cannon_slots * 8)

        # graze/crit tuning (vereinfacht)
        dmg_mult = 1.0
        if graze:
            dmg_mult *= 0.60
        elif crit:
            dmg_mult *= 1.45

        # Hull damage (kein target_mode mehr)
        dmg = int(base * mult * dmg_mult) - int(defender.armor * 0.9)
        dmg = max(1, dmg)
        defender.hull_hp = max(0, defender.hull_hp - dmg)

        leak_bonus= 1.0
        # Leak
        if random.random() < (self.LEAK_CHANCE_ON_HIT * leak_bonus):
            is_new = self._apply_status(defender, "leak", {"dur": self.LEAK_DUR, "dps": self.LEAK_DPS})
            applied.append("leak_new" if is_new else "leak_refresh")

        return {
            "result": result_tag,
            "hull": dmg,
            "hit_chance": hc,
            "applied": applied,
        }


    def _repair(self, target: CombatantRuntime, amount_base: int) -> None:
        if target.hull_hp <= 0:
            return
        target.hull_hp = min(target.hull_hp_max, target.hull_hp + max(1, amount_base))


    def _after_player_action(self) -> None:
        if self._check_finish():
            return
        self.awaiting_player = False
        self._enemy_turn()
        if self._check_finish():
            return
        self.turn += 1
        self.awaiting_player = True

    def _enemy_turn(self) -> None:
        res = self._fire(attacker=self.e, defender=self.p, mult=1.0)
        self.push_event({
            "type": "fire",
            "side": "enemy",
            "result": res.get("result", "hit"),
            "hull": int(res.get("hull", 0)),
            "applied": list(res.get("applied", [])),
        })


    def _check_finish(self) -> bool:
        if self.e.hull_hp <= 0:
            self.finished = True
            self.outcome = "win"
            self.rewards = self._compute_rewards()
            self.add_log("Enemy defeated.")
            return True
        if self.p.hull_hp <= 0:
            self.finished = True
            self.outcome = "lose"
            self.rewards = {"gold": 0, "xp": 0, "cargo": []}
            self.add_log("You have been defeated.")
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
        self.font = pygame.font.SysFont("consolas", 18)

        self._pending_rewards = {"gold": 0, "xp": 0, "cargo": []}

        # Ensure player stats exist (future-proof anchor for your Skilltree)
        if not hasattr(self.ctx, "player_stats") or self.ctx.player_stats is None:
            self.ctx.player_stats = PlayerStats()

        # Sprite cache
        if not hasattr(self, "_sprite_cache"):
            self._sprite_cache = {}

        # Build player combatant from current ship + shipdef
        ship = self.ctx.player.ship
        shipdef = self.ctx.content.ships.get(ship.type_id)

        p_hull_max = int(getattr(shipdef, "hull_hp", 120) or 120)

        # IMPORTANT:
        # In deinem Weltmodell ist ship.hull_hp aktuell ein Feld.
        # Wir behandeln es als "current hp". Wenn bei dir hull_hp eher "max" war:
        # -> dann setze ship.hull_hp beim Kauf/Spawn einmalig auf shipdef.hull_hp.
        p_hull_cur = int(ship.hull_hp) if int(ship.hull_hp) > 0 else p_hull_max
        self._player = CombatantRuntime(
            name="You",
            hull_hp=p_hull_cur, hull_hp_max=p_hull_max,
            armor=int(getattr(shipdef, "armor", 0) or 0),
            cannon_slots=int(getattr(shipdef, "cannon_slots", 0) or 0),
            basic_attack_dmg=int(getattr(shipdef, "basic_attack_dmg", 10) or 10),
            speed_px_s=float(getattr(shipdef, "speed_px_s", ship.speed) or ship.speed),
        )

        ed = self.ctx.content.enemies.get(self.enemy_id)
        if ed is None:
            # fallback, damit es nicht crasht
            ed = EnemyDef(self.enemy_id, self.enemy_id, 140, 40, 2, 4, 14, 150.0)

        if ed is None:
            ed = EnemyDef(self.enemy_id, self.enemy_id, 140, 40, 2, 4, 14, 150.0)

        self._enemy = CombatantRuntime(
            name=ed.name,
            hull_hp=ed.hull_hp, hull_hp_max=ed.hull_hp,
            armor=ed.armor,
            cannon_slots=ed.cannon_slots,
            basic_attack_dmg=ed.basic_attack_dmg,
            speed_px_s=ed.speed_px_s,
        )

        self.engine = CombatEngine(self._player, self._enemy, self.ctx.player_stats)

        # UI rects
        self.btn_fire  = pygame.Rect(60, 520, 140, 44)
        self.btn_repair= pygame.Rect(220, 520, 140, 44)
        self.btn_flee  = pygame.Rect(540, 520, 140, 44)

        # --- Result overlay state ---
        self._result_showing = False
        self._result_timer = 0.0
        self._result_text_lines = []
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

        # --- Visuals: datengetrieben ---
        ship_def = self.ctx.content.ships[self.ctx.player.ship.type_id]
        enemy_def = self.ctx.content.enemies[self.enemy_id]

        self._player_vis = {
            "sprite": ship_def.sprite,
            "size": tuple(ship_def.sprite_size),
            "scale": float(ship_def.sprite_scale),
            "offset": tuple(ship_def.sprite_offset),
            "flip_x": False,  # Player schaut nach rechts
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

        # --- Transition reveal from ctx (reverse of TransitionState) ---
        self._reveal = getattr(self.ctx, "transition_reveal", None)
        if self._reveal:
            # consume it so it doesn't apply repeatedly
            self.ctx.transition_reveal = None

        from settings import MASTER_LIFE_ICON
        self._ml_icon = None
        try:
            if os.path.exists(MASTER_LIFE_ICON):
                self._ml_icon = pygame.image.load(MASTER_LIFE_ICON).convert_alpha()
        except Exception:
            self._ml_icon = None


    def _resolve_player_visual(self) -> dict:
        ship = self.ctx.player.ship
        shipdef = self.ctx.content.ships.get(ship.type_id)

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


    def on_exit(self) -> None:
        # --- Music: restore previous (world) playlist ---
        try:
            self.ctx.audio.pop_music(fade_ms=800)
        except Exception:
            pass
        # Persist back to world model
        ship = self.ctx.player.ship
        ship.hull_hp = int(self._player.hull_hp)

    def _apply_outcome(self) -> None:
        # Persist HPs (redundant zu on_exit ist ok)
        ship = self.ctx.player.ship
        ship.hull_hp = int(self._player.hull_hp)

        if self.engine.outcome == "lose":
            # 1) Masterleben abziehen
            p = self.ctx.player
            p.master_lives = int(getattr(p, "master_lives", 3)) - 1
            p.master_lives = max(0, p.master_lives)

            # 2) Wenn keine Masterleben mehr -> Game Over Transition
            if p.master_lives <= 0:
                # Hull bleibt 0, Game endet
                try:
                    self.ctx.player.ship.hull_hp = 0
                except Exception:
                    pass
                return

            # 3) Sonst: Hull wiederherstellen und zurück zur Welt (kein Game Over)
            # Wir nutzen das maximale Hull aus CombatRuntime
            try:
                self.ctx.player.ship.hull_hp = int(getattr(self._player, "hull_hp_max", 1))
            except Exception:
                self.ctx.player.ship.hull_hp = max(1, int(getattr(self.ctx.player.ship, "hull_hp", 1)))

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

        if getattr(self, "_result_showing", False):
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                self._leave_combat()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._leave_combat()
            return


        #Buttons
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.ctx.clock.paused = not self.ctx.clock.paused
            
            #Action buttons
            elif event.key == pygame.K_TAB:
                self._cycle_time_speed()
            elif event.key == pygame.K_1:
                self.engine.player_fire()
            elif event.key == pygame.K_2:
                self.engine.player_repair()
            elif event.key == pygame.K_4:
                self.engine.player_flee()

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

    def update(self, sim_dt: float) -> None:
        # local time for bobbing etc.
        self._t = float(getattr(self, "_t", 0.0)) + float(sim_dt)

        # --- advance reveal (otherwise screen stays black) ---
        if getattr(self, "_reveal", None):
            self._reveal["t"] = float(self._reveal.get("t", 0.0)) + float(sim_dt)
            dur = float(self._reveal.get("duration", 0.85))
            if self._reveal["t"] >= dur:
                self._reveal = None

        # --- drain engine visual events into VFX ---
        try:
            while True:
                ev = self.engine.pop_event()
                if not ev:
                    break
                self._handle_vfx_event(ev)
        except Exception:
            pass

        # --- tick shake timer ---
        if getattr(self, "_shake_t", 0.0) > 0.0:
            self._shake_t = max(0.0, float(self._shake_t) - float(sim_dt))
            if self._shake_t <= 0.0:
                self._shake_amp = 0.0

        # --- tick float texts ---
        if self.engine.finished:
            # --- FINAL GAME OVER: direkt im Combat (ohne TransitionState / ohne Ergebnis-Overlay) ---
            if getattr(self.engine, "outcome", None) == "lose":
                p = self.ctx.player
                ml = int(getattr(p, "master_lives", 3))

                # Wenn dieses Combat-Lose das letzte Masterlife kosten würde -> sofort LoseState
                if (ml - 1) <= 0:
                    # Masterlife jetzt direkt abziehen (damit State konsistent ist)
                    p.master_lives = 0
                    try:
                        self.ctx.player.ship.hull_hp = 0
                    except Exception:
                        pass

                    # Snapshot vom Kampf als Hintergrund
                    try:
                        w, h = self.ctx.screen.get_size()
                        snap = pygame.Surface((w, h))
                        self._render_scene(snap)
                    except Exception:
                        snap = None

                    from states.lose import LoseState
                    self.game.replace(LoseState(snapshot=snap))
                    return


            # overlay initialisieren
            if not getattr(self, "_result_showing", False):
                self._result_showing = True
                self._result_timer = 1.4  # kurze Anzeige, dann raus
                self._result_applied = False

                outcome = getattr(self.engine, "outcome", None)
                if outcome == "win":
                    rewards = getattr(self.engine, "rewards", {"gold": 0, "xp": 0, "cargo": []})
                    gold = int(rewards.get("gold", 0))
                    xp = int(rewards.get("xp", 0))

                    ed = self.ctx.content.enemies.get(self.enemy_id)
                    cargo_drops = self._roll_enemy_cargo_loot(ed)
                    self._pending_rewards = {"gold": gold, "xp": xp, "cargo": cargo_drops}

                    lines = [("gold", f"+{gold} gold"), ("xp", f"+{xp} xp")]
                    for gid, tons in cargo_drops:
                        gdef = self.ctx.content.goods.get(gid)
                        gname = gdef.name if gdef else gid
                        lines.append(("cargo", f"+{tons:.2f}t {gname}", gid))

                    self._result_payload = {"title": "VICTORY", "lines": lines}

                    # timer runterzählen  <-- DAS FEHLT BEI DIR
                    self._result_timer = max(0.0, float(self._result_timer) - float(sim_dt))

                    # automatisch raus
                    if self._result_timer <= 0.0:
                        self._leave_combat()
                    return

                elif outcome == "lose":
                    self._result_payload = {"title": "DEFEAT", "lines": []}
                elif outcome == "flee":
                    self._result_payload = {"title": "ESCAPED", "lines": []}
                else:
                    self._result_payload = {"title": "RESULT", "lines": []}

            # automatisch raus
            if self._result_timer <= 0.0:
                self._leave_combat()
            return





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
            ok = bool(ev.get("success", False))
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



        # Render into a scene surface to apply shake cleanly
        scene = pygame.Surface(screen.get_size())
        self._render_scene(scene)
        screen.blit(scene, (ox, oy))


        # Header
        ts = float(getattr(self.ctx.clock, "time_scale", 1.0))
        speed_label = "PAUSE" if self.ctx.clock.paused else f"{ts:.0f}x"
        title = self.font.render(f"COMBAT vs {self._enemy.name}   Speed: {speed_label}", True, (220, 220, 220))
        screen.blit(title, (40, 30))

        # Bars
        self._draw_bar(screen, 60, 90,  620, 18, self._player.hull_hp, self._player.hull_hp_max, "Your Hull")

        self._draw_status_line(screen, 60, 140, self._player, "You")
        self._draw_status_line(screen, 60, 220, self._enemy, "Enemy")


        self._draw_bar(screen, 60, 170, 620, 18, self._enemy.hull_hp, self._enemy.hull_hp_max, "Enemy Hull")

        # Buttons
        self._draw_button(
            screen, self.btn_fire, "Fire (1)",
            self._player.cannon_cd <= 0.0 and self._player.cannon_slots > 0,
            subtext=f"CD: {self._player.cannon_cd:.1f}s",
            cooldown=float(self._player.cannon_cd),
            cooldown_max=float(self.engine.CANNON_RELOAD / max(0.2, self.engine._reload_mult_for(self._player, self.ctx.player_stats.reload_mult)))
        )

        self._draw_button(
            screen, self.btn_repair, "Repair (2)",
            self._player.repair_cd <= 0.0,
            subtext=f"CD: {self._player.repair_cd:.1f}s",
            cooldown=float(self._player.repair_cd),
            cooldown_max=float(self.engine.REPAIR_CD)
        )

        self._draw_button(screen, self.btn_flee, "Flee (4)", True)

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
            screen.fill((10, 12, 18))

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

    def _draw_button(self, screen, rect: pygame.Rect, text: str, enabled: bool, subtext: str = "", cooldown: float = 0.0, cooldown_max: float = 0.0):
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

        # cooldown pie (top-right)
        if cooldown_max > 0.0 and cooldown > 0.0:
            frac = max(0.0, min(1.0, cooldown / cooldown_max))
            cx = rect.right - 18
            cy = rect.y + 18
            r = 12

            # base circle
            pygame.draw.circle(screen, (25, 28, 38), (cx, cy), r)
            pygame.draw.circle(screen, (8, 9, 12), (cx, cy), r, 2)

            # draw pie as polygon fan
            steps = 20
            ang0 = -math.pi / 2
            ang1 = ang0 + (2 * math.pi * frac)
            pts = [(cx, cy)]
            for i in range(steps + 1):
                a = ang0 + (ang1 - ang0) * (i / steps)
                pts.append((cx + int(math.cos(a) * (r - 2)), cy + int(math.sin(a) * (r - 2))))
            pygame.draw.polygon(screen, (120, 120, 140), pts)
