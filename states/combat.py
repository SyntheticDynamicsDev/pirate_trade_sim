from __future__ import annotations
import math
import os
import random
import pygame
from typing import Optional, Dict
from dataclasses import dataclass, field
from data.loader import EnemyDef
from settings import TIME_SCALE_1X, TIME_SCALE_2X, TIME_SCALE_4X
from enum import Enum
from typing import Optional, Dict, Callable, Tuple
from collections import deque




# -----------------------------
# Data / Definitions (v1)
# -----------------------------
class CombatStance(Enum):
    OFFENSIVE = "offensive"
    BALANCED = "balanced"
    DEFENSIVE = "defensive"

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

    # Morale
    morale: int = 100  # 0..100

    #Additional stats for abilities/statuses
    quick_repair_vuln_rounds: int = 0  # erhöht eingehenden Schaden für N Runden

@dataclass
class _FloatText:
    text: str
    x: float
    y: float
    vy: float
    ttl: float
    color: tuple[int, int, int]
    crit: bool = False
    scale: float = 1.0

@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    ttl: float
    size: int
    color: tuple[int, int, int]

@dataclass
class AbilitySpec:
    id: str
    name: str
    cooldown_rounds: int = 0

    # morale handling
    morale_cost: int = 0          # subtract on use
    morale_delta: int = 0         # add (or subtract) on use

    # conditions + execution
    # can_use returns (ok, reason)
    can_use: Optional[Callable[["CombatEngine", str], Tuple[bool, str]]] = None

    # execute returns a result dict; ctx can be used for params like {"mult": 0.35}
    execute: Optional[Callable[["CombatEngine", str, dict], dict]] = None


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

        self.log = deque(maxlen=10)
        self.finished: bool = False
        self.outcome: Optional[str] = None  # "win" | "lose" | "flee"

        #Reward
        self.rewards = {"gold": 0, "xp": 0, "cargo": []}  # cargo: list[tuple[good_id, tons]]

        # --- AI state ---
        self._events = deque()


        # Runden-Tracking (future-proof)
        self.round_index: int = 0
        self.turn_owner: str = "player"   # "player" | "enemy"
        self._turn_queue: list[str] = []
        self.last_initiative: dict = {"player": 0.0, "enemy": 0.0}

        # --- Combat Stance ---
        self.stance: CombatStance = CombatStance.BALANCED
        self._stance_changed_this_round: bool = False
        # track morale tier changes (for feedback)
        self._last_morale_tier = {
            "player": self._morale_tier(self.p.morale),
            "enemy": self._morale_tier(self.e.morale),
        }

        # --- Abilities / cooldowns (C1) ---
        self._abilities: dict[str, AbilitySpec] = {}
        self._cd: dict[str, dict[str, int]] = {"player": {}, "enemy": {}}

        self._register_base_abilities()



    def pop_event(self) -> Optional[dict]:
        if not self._events:
            return None
        return self._events.popleft()

    def add_event(self, ev: dict) -> None:
        if not hasattr(self, "_events") or self._events is None:
            self._events = deque()
        self._events.append(ev)


    def _register_base_abilities(self) -> None:
        self.register_ability(AbilitySpec(
            id="fire",
            name="Fire",
            cooldown_rounds=0,
            can_use=None,
            execute=lambda eng, side, ctx: eng._ability_fire(side, ctx),
        ))

        self.register_ability(AbilitySpec(
            id="repair",
            name="Repair",
            cooldown_rounds=1,
            can_use=lambda eng, side: (eng.p.hp < eng.p.hp_max, "full_hp"),
            execute=lambda eng, side, ctx: eng._ability_repair(side, ctx),
        ))

        self.register_ability(AbilitySpec(
            id="flee",
            name="Flee",
            cooldown_rounds=2,
            can_use=None,
            execute=lambda eng, side, ctx: eng._ability_flee(side, ctx),
        ))

        self.register_ability(AbilitySpec(
            id="quick_repair",
            name="Quick Repair",
            cooldown_rounds=3,
            can_use=None,
            execute=lambda eng, side, ctx: eng._ability_quick_repair(side, ctx),
        ))


    def register_ability(self, spec: AbilitySpec) -> None:
        self._abilities[spec.id] = spec
        for s in ("player", "enemy"):
            self._cd[s].setdefault(spec.id, 0)

    def can_use_ability(self, ability_id: str, side: str) -> tuple[bool, str]:
        if self.finished:
            return False, "finished"
        if side not in ("player", "enemy"):
            return False, "bad_side"
        if ability_id not in self._abilities:
            return False, "unknown"
        if self.turn_owner != side:
            return False, "not_your_turn"

        spec = self._abilities[ability_id]

        if self._cd[side].get(ability_id, 0) > 0:
            return False, "cooldown"

        actor = self.p if side == "player" else self.e
        if spec.morale_cost > 0 and actor.morale < spec.morale_cost:
            return False, "low_morale"

        if spec.can_use:
            ok, reason = spec.can_use(self, side)
            if not ok:
                return False, reason

        return True, ""

    def use_ability(self, ability_id: str, side: str, ctx: Optional[dict] = None) -> Optional[dict]:
        ok, reason = self.can_use_ability(ability_id, side)
        if not ok:
            if side == "player":
                self.add_log(f"{ability_id.upper()} not available ({reason}).")
            return None

        spec = self._abilities.get(ability_id)
        if not spec:
            return None

        if ctx is None:
            ctx = {}

        actor = self.p if side == "player" else self.e

        # morale cost/effect
        if spec.morale_cost:
            actor.morale = max(0, actor.morale - int(spec.morale_cost))
        if spec.morale_delta:
            actor.morale = max(0, min(100, actor.morale + int(spec.morale_delta)))

        # 🔧 SICHERER EXECUTE
        if spec.execute:
            res = spec.execute(self, side, ctx)
        else:
            res = {"result": "noop"}

        # cooldown
        if spec.cooldown_rounds > 0:
            self._cd[side][ability_id] = int(spec.cooldown_rounds)

        return res

    def _morale_tier(self, morale: int) -> str:
        if morale >= 80:
            return "bonus"
        if morale >= 40:
            return "neutral"
        if morale >= 20:
            return "malus"
        return "panic"

    def _morale_modifiers(self, morale: int) -> dict:
        tier = self._morale_tier(morale)

        if tier == "bonus":
            return {
                "hit": 1.10,
                "repair": 1.15,
                "flee": 0.85,
                "panic_fail": 0.0,
            }

        if tier == "malus":
            return {
                "hit": 0.85,
                "repair": 0.75,
                "flee": 1.15,
                "panic_fail": 0.0,
            }

        if tier == "panic":
            return {
                "hit": 0.65,
                "repair": 0.50,
                "flee": 1.35,
                "panic_fail": 0.25,  # 25% Aktion scheitert
            }

        # neutral
        return {
            "hit": 1.0,
            "repair": 1.0,
            "flee": 1.0,
            "panic_fail": 0.0,
        }

    def get_live_combat_multipliers(self, unit):
        """
        SINGLE SOURCE OF TRUTH.
        All combat systems must use this.
        """

        # --- STANCE ---
        stance_damage = 1.0
        stance_repair = 1.0
        stance_hit = 1.0
        stance_flee = 1.0

        if self.stance.name == "OFFENSIVE":
            stance_damage = 1.20
            stance_hit = 1.10
            stance_repair = 0.85
            stance_flee = 0.85

        elif self.stance.name == "DEFENSIVE":
            stance_damage = 0.90
            stance_hit = 0.90
            stance_repair = 1.20
            stance_flee = 1.25

        # --- MORALE ---
        morale = unit.morale / 100.0

        morale_damage = 0.75 + morale * 0.5
        morale_hit = 0.5 + morale * 0.75
        morale_repair = 0.7 + morale * 0.6
        morale_flee = 1.3 - morale * 0.6
        # --- PANIC FAIL (used by player_repair) ---
        panic_fail = 0.0
        if unit.morale < 20:
            # 20 morale -> 0%, 0 morale -> 50%
            panic_fail = (20 - unit.morale) / 20.0 * 0.50

        return {
            "damage": stance_damage * morale_damage,
            "hit": stance_hit * morale_hit,
            "repair": stance_repair * morale_repair,
            "flee": stance_flee * morale_flee,
            "panic_fail": panic_fail,
        }

    def _compute_enemy_pressure(self) -> float:
        """
        0.00 .. 0.35 typical.
        Higher = harder to flee.
        """
        hp_frac = 0.0
        if self.e.hp_max > 0:
            hp_frac = max(0.0, min(1.0, self.e.hp / self.e.hp_max))

        morale_frac = max(0.0, min(1.0, self.e.morale / 100.0))

        # weighted pressure
        return 0.20 * hp_frac + 0.15 * morale_frac

    def _compute_flee_chance(self) -> float:
        base = 0.20  # not a panic exit

        # morale contribution: -0.10 .. +0.20
        m = max(0.0, min(1.0, self.p.morale / 100.0))
        morale_term = -0.10 + 0.30 * m

        # stance contribution
        if self.stance.name == "DEFENSIVE":
            stance_term = +0.10
        elif self.stance.name == "OFFENSIVE":
            stance_term = -0.08
        else:
            stance_term = 0.0

        pressure = self._compute_enemy_pressure()

        chance = base + morale_term + stance_term - pressure
        return max(0.05, min(0.85, chance))

    def _apply_low_morale_flee_penalty(self) -> dict:
        """
        Returns penalty dict (for UI/log). Does not assume economy model.
        """
        if self.p.morale >= 20:
            return {"penalty": None}

        # chance grows as morale drops: 20 -> 0.25, 0 -> 0.60
        t = (20 - self.p.morale) / 20.0
        chance = 0.25 + 0.35 * t

        if random.random() >= chance:
            return {"penalty": None}

        # penalty is abstract (hook)
        return {"penalty": "crew_scatter", "chance": chance}

    def player_fire(self) -> bool:
        res = self.use_ability("fire", "player")
        if not res:
            return False

        # if combat ended inside executor, don't advance turn
        if not self.finished:
            self._advance_turn()
        return True

    def player_attack(self) -> bool:
        # Backward compatibility: route to player_fire()
        return self.player_fire()

    def player_repair(self) -> bool:
        res = self.use_ability("repair", "player")
        if not res:
            return False

        # action consumed unless combat ended (repair doesn't end combat)
        if not self.finished:
            self._advance_turn()
        return True

    def player_flee(self) -> bool:
        res = self.use_ability("flee", "player")
        if not res:
            return False

        # If flee succeeded, combat already ended inside executor.
        if res.get("result") != "success" and not self.finished:
            self._advance_turn()

        return True
    
    def player_quick_repair(self) -> bool:
        res = self.use_ability("quick_repair", "player")
        if not res:
            return False

        if not self.finished:
            self._advance_turn()
        return True

    def _ability_fire(self, side: str, ctx: dict) -> dict:
        if self.finished:
            return {"result": "finished"}

        if side not in ("player", "enemy"):
            return {"result": "bad_side"}

        # turn ownership check: only enforce for player; enemy auto-actions can bypass if you want
        if side == "player" and self.turn_owner != "player":
            return {"result": "no_turn"}

        attacker = self.p if side == "player" else self.e
        defender = self.e if side == "player" else self.p

        mult = float(ctx.get("mult", 1.0))
        res = self._fire(attacker=attacker, defender=defender, mult=mult)

        # emit event for both sides
        self.add_event({
            "type": "fire",
            "side": side,
            "result": res.get("result"),
            "hull": int(res.get("hull", 0)),
            "applied": list(res.get("applied", [])),
        })

        if side == "player":
            self.add_log(f"You fire: -{int(res.get('hull', 0))} hull.")
        else:
            self.add_log(f"Enemy fires: -{int(res.get('hull', 0))} hull.")

        if self._check_finish():
            self._stop_turns()
            return {"result": "finished", **res}

        return {"result": "ok", **res}

    def _ability_repair(self, side: str, ctx: dict) -> dict:
        if side != "player":
            return {"result": "blocked"}

        if self.finished or self.turn_owner != "player":
            return {"result": "no_turn"}

        mods = self.get_live_combat_multipliers(self.p)

        # panic check
        panic = float(mods.get("panic_fail", 0.0))
        if panic > 0.0 and random.random() < panic:
            self.add_log("Repair failed due to panic!")
            self.p.morale = max(0, self.p.morale - 4)
            return {"result": "panic_fail", "heal": 0}

        # success roll
        success_chance = self._compute_repair_success(self.p)
        roll = random.random()
        success = roll < success_chance

        base_heal = int(round(self.p.hp_max * 0.10))
        base_heal = max(3, base_heal)

        heal = int(round(base_heal * float(mods.get("repair", 1.0))))

        stress_loss = 5
        if self.stance.name == "OFFENSIVE":
            stress_loss += 3
        elif self.stance.name == "DEFENSIVE":
            stress_loss -= 1
        stress_loss = max(2, stress_loss)

        applied_heal = 0
        if success:
            old_hp = self.p.hp
            self.p.hp = min(self.p.hp_max, self.p.hp + heal)
            applied_heal = self.p.hp - old_hp
            self.add_log(f"Repair succeeded (+{applied_heal} HP) (p={success_chance:.2f}, r={roll:.2f})")
            self.p.morale = min(100, self.p.morale + 1)
        else:
            self.add_log(f"Repair failed (p={success_chance:.2f}, r={roll:.2f})")
            self.p.morale = max(0, self.p.morale - 4)

        self.p.morale = max(0, self.p.morale - stress_loss)

        # chip shot
        chip_res = self.use_ability("fire", "enemy", {"mult": 0.35})

        self.add_event({
            "type": "repair",
            "side": "player",
            "amount": applied_heal,
        })

        return {
            "result": "success" if success else "fail",
            "heal": applied_heal,
            "p": success_chance,
            "r": roll,
            "chip": {
                "result": chip_res.get("result") if chip_res else None,
                "hull": int(chip_res.get("hull", 0)) if chip_res else 0
            }

        }

    def _ability_flee(self, side: str, ctx: dict) -> dict:
        if side != "player":
            return {"result": "blocked"}

        if self.finished or self.turn_owner != "player":
            return {"result": "no_turn"}

        chance = self._compute_flee_chance()
        roll = random.random()
        success = roll < chance

        if success:
            penalty = self._apply_low_morale_flee_penalty()

            self.add_event({
                "type": "flee",
                "side": "player",
                "success": True
            })

            if penalty.get("penalty"):
                self.add_log(f"Flee succeeded, but chaos ensued ({penalty['penalty']})!")
                self.add_event({"type": "flee_penalty", **penalty})
            else:
                self.add_log("Flee succeeded!")

            self.add_log(f"(p={chance:.2f}, r={roll:.2f})")

            self.finished = True
            self.outcome = "flee"
            self._stop_turns()

            return {"result": "success", "p": chance, "r": roll, "penalty": penalty}

        # failure
        self.add_log(f"Flee failed! (p={chance:.2f}, r={roll:.2f})")
        self.p.morale = max(0, self.p.morale - 8)

        chip_res = self.use_ability("fire", "enemy", {"mult": 0.60})
        self.add_event({
            "type": "flee",
            "side": "player",
            "success": False
        })

        return {
            "result": "fail",
            "p": chance,
            "r": roll,
            "chip": {
                "result": chip_res.get("result") if chip_res else None,
                "hull": int(chip_res.get("hull", 0)) if chip_res else 0
            }
        }

    def _ability_quick_repair(self, side: str, ctx: dict) -> dict:
        if side != "player":
            return {"result": "blocked"}

        if self.finished or self.turn_owner != "player":
            return {"result": "no_turn"}

        mods = self.get_live_combat_multipliers(self.p)

        # großer Heal: 30% max HP (mit repair-mult)
        base_heal = int(round(self.p.hp_max * 0.30))
        base_heal = max(8, base_heal)
        heal = int(round(base_heal * float(mods.get("repair", 1.0))))

        old_hp = self.p.hp
        self.p.hp = min(self.p.hp_max, self.p.hp + heal)
        applied = self.p.hp - old_hp

        # starker Moralverlust
        morale_loss = 18
        self.p.morale = max(0, self.p.morale - morale_loss)

        # Verwundbarkeit nächste Runde
        self.p.quick_repair_vuln_rounds = max(self.p.quick_repair_vuln_rounds, 1)

        self.add_event({
            "type": "quick_repair",
            "side": "player",
            "heal": int(applied),
        })

        self.add_log(f"Quick Repair! +{applied} HP, -{morale_loss} morale. Vulnerable next round.")

        return {"result": "ok", "heal": int(applied)}

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
        
    def set_stance(self, stance: CombatStance) -> bool:
        """
        Returns True if stance was changed.
        Can be called only once per round.
        """
        if self.finished:
            return False

        if self._stance_changed_this_round:
            return False

        if stance == self.stance:
            return False

        self.stance = stance
        self._stance_changed_this_round = True
        self.add_log(f"Stance set to {stance.name.title()}")

        return True

    def _stance_modifiers(self) -> dict:
        """
        Central stance balance table.
        """
        if self.stance == CombatStance.OFFENSIVE:
            return {
                "damage": 1.20,
                "morale": -1.0,
                "flee": 0.75,
            }
        if self.stance == CombatStance.DEFENSIVE:
            return {
                "damage": 0.85,
                "morale": +1.0,
                "flee": 1.25,
            }
        # BALANCED
        return {
            "damage": 1.0,
            "morale": 0.0,
            "flee": 1.0,
        }

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


    def _compute_hit_chance(self, attacker):
        base = 0.75
        mods = self.get_live_combat_multipliers(attacker)

        chance = base * mods["hit"]
        return max(0.05, min(0.95, chance))

    def _compute_repair_success(self, unit: CombatantRuntime) -> float:
        """
        Repair success chance based on morale.
        0..100 morale -> 0.35..0.90
        """
        m = max(0, min(100, int(unit.morale))) / 100.0
        chance = 0.35 + 0.55 * m
        return max(0.10, min(0.95, chance))

    def get_debug_combat_modifiers(self, unit):
        """
        Returns live combat multipliers affected by stance & morale.
        """
        mods = {}

        # --- BASE ---
        cannon = 1.0
        reload = 1.0
        boarding = 1.0
        repair = 1.0
        evade = 1.0
        flee = 1.0

        # --- STANCE ---
        if self.stance.name == "OFFENSIVE":
            cannon *= 1.20
            boarding *= 1.15
            repair *= 0.85
            evade *= 0.90
            flee *= 0.85

        elif self.stance.name == "DEFENSIVE":
            cannon *= 0.90
            boarding *= 0.85
            repair *= 1.20
            evade *= 1.15
            flee *= 1.25

        # BALANCED = no change

        # --- MORALE ---
        morale = unit.morale / 100.0

        cannon *= 0.75 + morale * 0.5
        reload *= 1.25 - morale * 0.5
        boarding *= 0.8 + morale * 0.4
        repair *= 0.7 + morale * 0.6
        evade *= 0.8 + morale * 0.4
        flee *= 1.3 - morale * 0.6

        mods["Cannon Damage"] = cannon
        mods["Reload Speed"] = reload
        mods["Boarding Damage"] = boarding
        mods["Repair Power"] = repair
        mods["Evade"] = evade
        mods["Flee"] = flee

        return mods


    # ---- Player actions ----

    def _roll_initiative(self, base: float) -> float:
        # kleine, faire Varianz pro Runde (±8%)
        jitter = random.uniform(-0.08, 0.08)
        return max(0.05, base * (1.0 + jitter))

    def _start_new_round(self) -> None:
        self.round_index += 1
        # decay one-round vulnerability flags
        if getattr(self.p, "quick_repair_vuln_rounds", 0) > 0:
            self.p.quick_repair_vuln_rounds -= 1
        if getattr(self.e, "quick_repair_vuln_rounds", 0) > 0:
            self.e.quick_repair_vuln_rounds -= 1

        # reset stance-change lock per round
        self._stance_changed_this_round = False

        ip = self._roll_initiative(self.p.initiative_base)
        ie = self._roll_initiative(self.e.initiative_base)
        self.last_initiative = {"player": ip, "enemy": ie}

        if ip >= ie:
            self._turn_queue = ["player", "enemy"]
        else:
            self._turn_queue = ["enemy", "player"]

        self.turn_owner = self._turn_queue[0]
        self.add_log(f"Round {self.round_index}: init P={ip:.2f} vs E={ie:.2f} → {self.turn_owner} first")

        # --- tick ability cooldowns (C1.1) ---
        for side in ("player", "enemy"):
            for aid, cd in list(self._cd[side].items()):
                if cd > 0:
                    self._cd[side][aid] = cd - 1

    def _fire(self, attacker: CombatantRuntime, defender: CombatantRuntime, mult: float) -> dict:
        mods = self.get_live_combat_multipliers(attacker)

        # --- HIT CHECK ---
        hit_chance = self._compute_hit_chance(attacker)
        hit_roll = random.random()
        hit = hit_roll < hit_chance

        if not hit:
            # morale loss on miss
            morale_loss = 6

            # offensive stance -> more morale punishment
            if self.stance.name == "OFFENSIVE":
                morale_loss += 4

            attacker.morale = max(0, attacker.morale - morale_loss)

            self.add_log(
                f"{attacker.name} missed! "
                f"(hit {hit_chance:.2f}, roll {hit_roll:.2f})"
            )

            return {
                "result": "miss",
                "hull": 0,
                "applied": [],
                "hit_chance": hit_chance,
                "roll": hit_roll,
            }



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
        cc *= mods["hit"]
        cc = max(0.0, min(1.0, cc))
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
        dmg_mult_from_armor = max(0.1, 1.0 - (effective_armor / 100.0))

        # final damage (mult bleibt als hook, aber keine Sonderfälle)
        dmg = int(round(base * float(mult) * dmg_mult_from_armor * mods["damage"]))
        # quick repair vulnerability: incoming damage increased for 1 round
        if getattr(defender, "quick_repair_vuln_rounds", 0) > 0:
            dmg = int(round(dmg * 1.35))

        if dmg < 1:
            dmg = 1

        defender.hp = max(0, int(defender.hp) - dmg)
        # morale impact
        if is_crit:
            defender.morale -= 8
            attacker.morale += 4
        else:
            defender.morale -= 4
            attacker.morale += 2


        defender.morale = max(0, min(100, defender.morale))
        attacker.morale = max(0, min(100, attacker.morale))


        # morale tier change feedback
        for key, unit in (("player", attacker), ("enemy", defender)):
            old = self._last_morale_tier.get(key)
            new = self._morale_tier(unit.morale)
            if old != new:
                self._last_morale_tier[key] = new
                self.add_event({
                    "type": "morale_shift",
                    "side": key,
                    "tier": new,
                })

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
# -----------------------------
# Combat UI tuning constants
# -----------------------------
UI_ABILITY_BTN_W = 180
UI_ABILITY_ICON_SIZE = 90
UI_ABILITY_SHIELD_H = 42
UI_ABILITY_OVERLAP = 26
UI_ABILITY_GAP = 12

UI_STANCE_ICON_SIZE = 72
UI_STANCE_GAP = 10
UI_STANCE_PAD = 12

class CombatState:
    def __init__(self, enemy_id: str = "") -> None:
        self.enemy_id = enemy_id
        self.game = None
        self.ctx = None
        self.font = None


    

    def on_enter(self) -> None:
        from core.ui_text import FontBank, TextStyle, render_text
        from settings import UI_FONT_PATH, UI_FONT_FALLBACK

        self._fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)
        self.font = self._fonts.get(18)
        self.small = self._fonts.get(16)
        
        # --- Damage number fonts (big & bold) ---
        self._dmg_font = self._fonts.get(32)
        self._dmg_font.set_bold(True)

        # optional: noch stärker für Crits (später)
        self._dmg_font_big = self._fonts.get(40)
        self._dmg_font_big.set_bold(True)

        self.engine = None

        self._pending_rewards = {"gold": 0, "xp": 0, "cargo": []}

        # UI state
        self._floating_texts = []  # [(text, x, y, timer)]

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
        # Morale initialisieren (kann später durch Aktionen beeinflusst werden)
        self._player.morale = random.randint(65, 80)

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

        #morale initialisieren (kann später durch Aktionen beeinflusst werden)
        self._enemy.morale = random.randint(55, 75)

        self.engine = CombatEngine(self._player, self._enemy, self.ctx.player_stats)


        # UI rects (werden per _layout_ui() dynamisch gesetzt)
        self.btn_fire = pygame.Rect(0, 0, 1, 1)
        self.btn_repair = pygame.Rect(0, 0, 1, 1)
        self.btn_flee = pygame.Rect(0, 0, 1, 1)
        self.btn_quick_repair = pygame.Rect(0, 0, 1, 1)
        self._log_panel_rect = pygame.Rect(0, 0, 1, 1)


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

        # --- UI: empty sign for unit names ---
        try:
            sign_path = os.path.join("assets", "ui", "sign_empty.png")
            self._sign_empty = pygame.image.load(sign_path).convert_alpha()
        except Exception:
            self._sign_empty = None
        # use same sign as ability button shield
        self._name_shield = self._sign_empty

        # --- Visuals: NEW schema via ship_def.visual ---
        ship_def = self.ctx.content.ships[self.ctx.player.ship.id]
        enemy_def = self.ctx.content.enemies[self.enemy_id]

        v = getattr(ship_def, "visual", None)
        if v is None:
            raise ValueError(f"ShipDef '{ship_def.id}' missing required .visual (ships.json/loader mismatch).")

        self._player_vis = {
            "sprite": str(getattr(v, "sprite")),
            "size": tuple(getattr(v, "size", (380, 240))),
            "scale": float(getattr(v, "scale", 1.0)),
            "offset": tuple(getattr(v, "offset", (0, 0))),
            "flip_x": bool(getattr(v, "flip_x", False)),
        }

        #--- Ability icons (optional, loaded by convention from ui/abilities/{ability_id}.png) ---
        abilities_dir = os.path.join("assets", "ui", "abilities")
        self._ability_icons = {}

        for ability_id in ("fire", "repair", "flee", "quick_repair"):
            path = os.path.join(abilities_dir, f"{ability_id}.png")
            if os.path.exists(path):
                img = pygame.image.load(path).convert_alpha()
                self._ability_icons[ability_id] = img



        # --- Music: override world playlist with fight track ---
        fight_track = os.path.join("assets", "music", "fight.mp3")
        self.ctx.audio.push_music([fight_track], shuffle=False, fade_ms=800)

        self._enemy_vis = {
            "sprite": enemy_def.sprite,  # kommt aus enemies.json -> visual.sprite
            "size": tuple(getattr(enemy_def, "sprite_size", (380,240))),
            "scale": float(getattr(enemy_def, "sprite_scale", 1.0)),
            "offset": tuple(getattr(enemy_def, "sprite_offset", (0, 0))),
            "flip_x": bool(getattr(enemy_def, "sprite_flip_x", True)),
        }

        self._player_vis["scale"] = 1.18
        self._enemy_vis["scale"] = 1.22
        self._spr_player = self._load_sprite_spec(self._player_vis)
        self._spr_enemy = self._load_sprite_spec(self._enemy_vis)

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

        # --- Name sign (empty wooden sign) ---
        try:
            ui_dir = os.path.join("assets", "ui")  # falls du ui_dir bereits irgendwo setzt: diesen try-Block behalten
            sign_path = os.path.join(ui_dir, "sign_empty.png")
            self._sign_empty = pygame.image.load(sign_path).convert_alpha()
        except Exception:
            self._sign_empty = None


        from settings import MASTER_LIFE_ICON
        self._ml_icon = None
        try:
            if os.path.exists(MASTER_LIFE_ICON):
                self._ml_icon = pygame.image.load(MASTER_LIFE_ICON).convert_alpha()
        except Exception:
            self._ml_icon = None

        # --- Turn delay (visual spacing between actions) ---
        self._turn_delay = 0.0  # seconds remaining
        self._pending_action = None  # e.g. ("fire",) / ("repair",) / ("flee",)
        # --- Unit rect cache for precise VFX placement ---
        self._unit_rects = {"player": None, "enemy": None}

        # --- Stance UI ---
        self._stance_icons = {}
        self._stance_rects = {}

        base = os.path.join("assets", "ui", "stance")
        for key in ("offensive", "balanced", "defensive"):
            path = os.path.join(base, f"{key}.png")
            try:
                self._stance_icons[key] = pygame.image.load(path).convert_alpha()
            except Exception:
                self._stance_icons[key] = None

        # --- Morale UI assets (3-layer) ---
        try:
            base = os.path.join("assets", "ui", "moral")
            self._morale_frame = pygame.image.load(os.path.join(base, "moral.png")).convert_alpha()
            self._morale_fill = pygame.image.load(os.path.join(base, "moral_fill.png")).convert_alpha()
            self._morale_bg = pygame.image.load(os.path.join(base, "moral_bg.png")).convert_alpha()
        except Exception:
            self._morale_frame = None
            self._morale_fill = None
            self._morale_bg = None
        # --- Morale bar sizing (UI scale) ---
        self._morale_scale = 0.18   # 60% der Originalgröße

        # --- HP UI assets (4-layer) ---
        try:
            base = os.path.join("assets", "ui", "hp")
            self._hp_bg = pygame.image.load(os.path.join(base, "hp_bg.png")).convert_alpha()
            self._hp_fill = pygame.image.load(os.path.join(base, "hp_fill.png")).convert_alpha()
            self._hp_frame = pygame.image.load(os.path.join(base, "hp_frame.png")).convert_alpha()
            self._hp_glow = pygame.image.load(os.path.join(base, "hp_glow.png")).convert_alpha()
            self._hp_cache = {}  # cache scaled layers by width
        except Exception:
            self._hp_bg = None
            self._hp_fill = None
            self._hp_frame = None
            self._hp_glow = None
            self._hp_cache = {}

        # --- HP glow animation ---
        self._hp_glow_t = 0.0
        self._hp_glow_alpha_cache = {}  # (w, alpha) -> glow_surface


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
        """
        spec schema:
        { "sprite": str|None, "size": (w,h), "scale": float, "offset": (x,y), "flip_x": bool }
        Loads and scales with aspect ratio to fit into size, then applies optional scale multiplier.
        Uses a small cache to avoid repeated disk hits.
        """
        path = spec.get("sprite")
        if not path:
            return None

        # Target box
        w, h = spec.get("size", (260, 160))
        w = max(1, int(w))
        h = max(1, int(h))

        # Extra multiplier applied after fitting
        scale = float(spec.get("scale", 1.0))
        scale = max(0.01, scale)

        # init cache if missing
        if not hasattr(self, "_sprite_cache"):
            self._sprite_cache = {}

        # We cache by the resulting output size, not by (w,h) to avoid collisions
        # after aspect-fit calculations.
        base_key = (path, w, h, scale)
        if base_key in self._sprite_cache:
            return self._sprite_cache[base_key]

        try:
            img = pygame.image.load(path).convert_alpha()
        except Exception:
            self._sprite_cache[base_key] = None
            return None

        iw, ih = img.get_size()
        if iw <= 0 or ih <= 0:
            self._sprite_cache[base_key] = None
            return None

        # Fit into (w,h) keeping aspect, then apply scale multiplier
        fit = min(w / float(iw), h / float(ih))
        s = fit * scale

        out_w = max(1, int(round(iw * s)))
        out_h = max(1, int(round(ih * s)))

        key = (path, out_w, out_h)
        cached = self._sprite_cache.get(key)
        if cached is not None:
            self._sprite_cache[base_key] = cached
            return cached

        surf = pygame.transform.smoothscale(img, (out_w, out_h))
        self._sprite_cache[key] = surf
        self._sprite_cache[base_key] = surf
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

    def _layout_ui(self, screen: pygame.Surface) -> None:
        """Responsive UI layout for combat: left stacked buttons + bottom-right combat log."""
        W, H = screen.get_size()

        # --- Compact Ability Layout (final clean version) ---
        btn_w = UI_ABILITY_BTN_W
        icon_size = UI_ABILITY_ICON_SIZE         # kleiner als vorher
        shield_h = UI_ABILITY_SHIELD_H
        overlap = UI_ABILITY_OVERLAP            # Schild überlappt Icon
        gap_between_blocks = UI_ABILITY_GAP # dichter zusammen

        margin_l = 40
        margin_b = 34

        block_h = icon_size - overlap + shield_h
        total_h = block_h * 4 + gap_between_blocks * 3


        top_y = H - margin_b - total_h

        def make_block(i):
            y = top_y + i * (block_h + gap_between_blocks)
            return pygame.Rect(margin_l, y, btn_w, block_h)

        self.btn_fire   = make_block(0)
        self.btn_repair = make_block(1)
        self.btn_flee   = make_block(2)
        self.btn_quick_repair = make_block(3)



        # --- Combat log: bottom-right panel ---
        panel_w = 420
        # Header + spacing + up to 8 lines
        line_h = 20
        header_h = 26
        pad = 12
        lines = 8
        panel_h = pad + header_h + 6 + lines * line_h + pad

        margin_r = 32
        panel_x = W - margin_r - panel_w
        panel_y = H - margin_b - panel_h

        self._log_panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
        self._log_lines_max = lines
        self._log_line_h = line_h
        self._log_pad = pad
        self._log_header_h = header_h

        # --- Stance buttons (stacked above ability buttons, WITH panel) ---
        # --- Stance buttons (stacked, large, flush left) ---
        icon_size = 72
        gap = 10
        pad = 12

        order = ["offensive", "balanced", "defensive"]
        self._stance_rects = {}

        # 1️⃣ bündig links
        x = 0

        # 2️⃣ 25px höher als vorher
        y_start = self.btn_fire.y - (icon_size * 3 + gap * 2) - 40  # vorher -16 → jetzt -40

        # Klick-Rects (Icons)
        for i, key in enumerate(order):
            self._stance_rects[key] = pygame.Rect(
                x + pad,
                y_start + pad + i * (icon_size + gap),
                icon_size,
                icon_size,
            )

        # Panel-Rect
        panel_w = icon_size + pad * 2
        panel_h = (icon_size * 3) + (gap * 2) + pad * 2

        self._stance_panel_rect = pygame.Rect(
            x,
            y_start,
            panel_w,
            panel_h
        )

    def _draw_combat_log_panel(self, screen: pygame.Surface) -> None:
        """Draws combat log inside a bottom-right panel."""
        r = getattr(self, "_log_panel_rect", None)
        if r is None:
            return

        # Panel background (rounded, semi-transparent, no border)
        panel = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        pygame.draw.rect(
            panel,
            (0, 0, 0, 180),          # transparent black
            pygame.Rect(0, 0, r.w, r.h),
            border_radius=14
        )
        screen.blit(panel, (r.x, r.y))


        x = r.x + self._log_pad
        y = r.y + self._log_pad

        # Header
        screen.blit(self.font.render("Combat Log", True, (230, 230, 230)), (x, y))
        y += self._log_header_h

        # Lines
        lines = list(getattr(self.engine, "log", []))[-self._log_lines_max:]
        for line in lines:
            screen.blit(self.font.render(f"- {line}", True, (200, 200, 200)), (x, y))
            y += self._log_line_h

    def handle_event(self, event) -> None:
        # --- Stance click ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            for key, rect in self._stance_rects.items():
                if rect.collidepoint(mx, my):

                    mapping = {
                        "offensive": CombatStance.OFFENSIVE,
                        "balanced": CombatStance.BALANCED,
                        "defensive": CombatStance.DEFENSIVE,
                    }

                    self.engine.set_stance(mapping[key])
                    return

        
        # keep UI layout in sync (important for click rects)
        try:
            self._layout_ui(self.ctx.screen)
        except Exception:
            pass

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

        # Block combat actions while turn-delay is running (pause still allowed)
        if float(getattr(self, "_turn_delay", 0.0)) > 0.0:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                self.ctx.clock.paused = not self.ctx.clock.paused
            return


        #Buttons
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.ctx.clock.paused = not self.ctx.clock.paused

        # --- Player actions are queued and executed after a 1s pre-delay ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            # only during player turn
            if getattr(self.engine, "turn_owner", "player") != "player":
                return

            # if a delay is running or something is already queued, ignore
            if float(getattr(self, "_turn_delay", 0.0)) > 0.0 or getattr(self, "_pending_action", None) is not None:
                return

            # Decide which action to queue
            if self.btn_fire.collidepoint(mx, my):
                self._pending_action = ("fire",)
            elif self.btn_repair.collidepoint(mx, my):
                # Avoid "wait 1s -> nothing happens" by validating locally
                if getattr(self._player, "hp", 0) >= getattr(self._player, "hp_max", 0):
                    return
                self._pending_action = ("repair",)
            elif self.btn_flee.collidepoint(mx, my):
                self._pending_action = ("flee",)
            elif self.btn_quick_repair.collidepoint(mx, my):
                if getattr(self._player, "hp", 0) >= getattr(self._player, "hp_max", 0):
                    return
                self._pending_action = ("quick_repair",)

            else:
                return

            # Start PRE-delay so you see who acts first before anything happens
            ts = float(getattr(self.ctx.clock, "time_scale", 1.0)) or 1.0
            self._turn_delay = 0.2
            return



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
        # HP glow timer (resets on HP change, animates glow alpha)
        if hasattr(self, "_hp_glow_t"):
            self._hp_glow_t += float(dt)

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

        # --- Turn delay gate: wait before allowing next action/turn to execute ---
        if float(getattr(self, "_turn_delay", 0.0)) > 0.0:
            self._turn_delay = max(0.0, float(self._turn_delay) - float(dt))

            # Reveal weiter ticken lassen (sonst kann es wieder "kleben")
            if getattr(self, "_reveal", None):
                self._reveal["t"] = float(self._reveal.get("t", 0.0)) + float(dt)
                dur = float(self._reveal.get("duration", 0.85))
                if self._reveal["t"] >= dur:
                    self._reveal = None
            return

        # --- Execute queued player action AFTER the pre-delay ---
        if float(getattr(self, "_turn_delay", 0.0)) <= 0.0 and getattr(self, "_pending_action", None) is not None:
            action = self._pending_action
            self._pending_action = None

            # Execute exactly one player intent
            acted = False
            if action[0] == "fire":
                acted = bool(self.engine.player_fire())
            elif action[0] == "repair":
                acted = bool(self.engine.player_repair())
            elif action[0] == "flee":
                acted = bool(self.engine.player_flee())
            elif action[0] == "quick_repair":
                acted = bool(self.engine.player_quick_repair())

            # Drain events immediately so VFX/log shows right away
            any_action_event = False
            while True:
                ev = self.engine.pop_event()
                if not ev:
                    break
                self._handle_vfx_event(ev)
                if ev.get("type") in ("fire", "repair", "board", "flee"):
                    any_action_event = True

            # Start POST-delay after the executed action (spacing before the next one)
            if acted or any_action_event:
                ts = float(getattr(self.ctx.clock, "time_scale", 1.0)) or 1.0
                self._turn_delay = 0.5 / max(0.25, ts)

            return


        self.engine.update(dt)

        acted = False
        while True:
            ev = self.engine.pop_event()
            if not ev:
                break
            self._handle_vfx_event(ev)

            # Any of these events represent an action we want to space out
            if ev.get("type") in ("fire", "repair", "board", "flee"):
                acted = True

        # After an action (usually enemy auto-turn), start delay before next turn
        if acted and not getattr(self.engine, "finished", False):
            ts = float(getattr(self.ctx.clock, "time_scale", 1.0)) or 1.0
            self._turn_delay = 0.5 / max(0.25, ts)

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

        def add_float(text, x, y, color, crit: bool = False, scale: float = 1.0):
            self._float_texts.append(
                _FloatText(text=text, x=float(x), y=float(y), vy=-22.0, ttl=1.05, color=color, crit=crit, scale=float(scale))
            )

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
                add_burst(dst[0] + random.randint(-20, 20), dst[1] + random.randint(10, 30), (140, 160, 180))

                # MISS text on defender ship
                defender_key = "enemy" if side == "player" else "player"
                rdef = self._unit_rects.get(defender_key)

                if rdef:
                    x = rdef.centerx
                    y = rdef.centery - int(rdef.height * 0.2)
                else:
                    x = dst[0]
                    y = dst[1] - 40

                add_float("MISS", x, y, (200, 200, 200), crit=False, scale=1.0)


            # Damage numbers (placed ON the defender ship)
            if hull > 0:
                # side == attacker ("player" or "enemy")
                defender_key = "enemy" if side == "player" else "player"

                # --- compute defender rect directly (do not rely on cached rects) ---
                pv = self._player_vis
                evv = self._enemy_vis

                p_cx = int(W * 0.28) + int(pv["offset"][0])
                p_cy = mid_y + int(pv["offset"][1])

                e_cx = int(W * 0.72) + int(evv["offset"][0])
                e_cy = mid_y + int(evv["offset"][1])

                p_spr = getattr(self, "_spr_player", None)
                e_spr = getattr(self, "_spr_enemy", None)

                p_w = p_spr.get_width() if p_spr else 180
                p_h = p_spr.get_height() if p_spr else 90
                e_w = e_spr.get_width() if e_spr else 180
                e_h = e_spr.get_height() if e_spr else 90

                if defender_key == "enemy":
                    rdef = pygame.Rect(e_cx - e_w // 2, e_cy - e_h // 2, e_w, e_h)
                else:
                    rdef = pygame.Rect(p_cx - p_w // 2, p_cy - p_h // 2, p_w, p_h)

                # --- crit styling ---
                is_crit = (res == "crit")
                col = (255, 210, 120) if is_crit else (240, 120, 110)
                scale = 1.25 if is_crit else 1.0

                # --- position ON the ship body (tweakable) ---
                # slightly above center
                y = rdef.centery - int(rdef.height * 0.18) + random.randint(-4, 4)

                # nudge toward "inside" so it doesn't drift off the hull
                if defender_key == "enemy":
                    x = rdef.centerx - int(rdef.width * 0.06) + 170
                else:
                    x = rdef.centerx + int(rdef.width * 0.06) + random.randint(-4, 4)

                add_float(f"-{hull}", x, y, col, crit=is_crit, scale=scale)

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

        elif et == "morale_shift":
            tier = ev.get("tier")
            side = ev.get("side")

            if tier == "panic":
                self.engine.add_log(f"{side.upper()} is panicking!")
                self._start_shake(0.15, 3.5)
            elif tier == "malus":
                self.engine.add_log(f"{side.upper()} morale is faltering.")

    def _start_shake(self, dur: float, amp: float) -> None:
        self._shake_t = max(self._shake_t, float(dur))
        self._shake_amp = max(self._shake_amp, float(amp))

    def _apply_red_tint(self, surf: pygame.Surface, strength: float) -> pygame.Surface:
        """
        strength:
            0.0 = original color
            1.0 = fully red-tinted
        """
        strength = max(0.0, min(1.0, strength))
        if strength <= 0.0:
            return surf

        # Red tint overlay (NO alpha fading)
        overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)

        # Red increases, green/blue decrease with strength
        r = 255
        g = int(255 * (strength))
        b = int(255 * (strength))

        overlay.fill((r, g, b, 255))

        out = surf.copy()
        out.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        return out

    def render(self, screen: pygame.Surface) -> None:
        HP_TEXT_GAP = -70
        MORALE_TEXT_GAP = 2
        HP_TO_MORALE_GAP = -85   # <- “nur wenige Pixel” zwischen HP-Bar und Morale-Text)

        # responsive layout each frame
        self._layout_ui(screen)

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
        W, H = screen.get_size()

        total_w = ml_max * size + (ml_max - 1) * gap
        margin = 24

        start_x = W - total_w - margin
        start_y = margin


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
        # Bars (centered above player/enemy units, half length)
        W, H = screen.get_size()
        mid_y = int(H * 0.45)

        pv = self._player_vis
        ev = self._enemy_vis

        p_cx = int(W * 0.28) + int(pv["offset"][0])
        p_cy = mid_y + int(pv["offset"][1])

        e_cx = int(W * 0.72) + int(ev["offset"][0])
        e_cy = mid_y + int(ev["offset"][1])

        # Use sprite heights for correct vertical placement (fallback if missing)
        p_h = self._spr_player.get_height() if getattr(self, "_spr_player", None) else 60
        e_h = self._spr_enemy.get_height() if getattr(self, "_spr_enemy", None) else 60

        bar_w = 310  # half of 620
        bar_h = self._hp_height_for_width(bar_w) if getattr(self, "_hp_bg", None) else 18
        lift = 60  # distance above the sprite

        p_bar_x = p_cx - bar_w // 2
        p_bar_y = max(10, int(p_cy - (p_h * 0.5) - lift)-150)

        e_bar_x = e_cx - bar_w // 2
        e_bar_y = max(10, int(e_cy - (e_h * 0.5) - lift)-150)

        # --- HP + Status: shared panel (covers text + bar + status), status below HP ---
        panel_pad = 8
        panel_alpha = 140
        gap_status = 8

        font_h = self.font.get_height()
        label_h = font_h          # "YOUR HP: 117/180" etc.
        status_h = font_h         # "YOU STATUS: ..." line

        p_status_y = p_bar_y + bar_h + gap_status
        e_status_y = e_bar_y + bar_h + gap_status

        def _hp_panel(x_left: int, hp_bar_y: int, morale_bar_y: int) -> None:
            font_h = self.font.get_height()

            top = (hp_bar_y - font_h - HP_TEXT_GAP) - panel_pad
            bottom = (morale_bar_y + morale_h) + panel_pad

            w = bar_w + panel_pad * 2
            h = max(1, bottom - top)

            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(surf, (0, 0, 0, panel_alpha), surf.get_rect(), border_radius=14)
            screen.blit(surf, (x_left - panel_pad, top))



        # --- Compact stacking: Morale text sits just a few pixels under HP bar ---
        font_h = self.font.get_height()

        # morale bar height (needed for panel sizing)
        if self._morale_frame:
            morale_h = int(self._morale_frame.get_height() * float(self._morale_scale))
        else:
            morale_h = 18

        # Place the morale BAR so that its LABEL is only HP_TO_MORALE_GAP pixels below the HP bar.
        # Label is drawn at (y - font_h - MORALE_TEXT_GAP) inside _draw_morale_bar.
        morale_bar_y = p_bar_y + bar_h + HP_TO_MORALE_GAP + font_h + MORALE_TEXT_GAP
        enemy_morale_bar_y = e_bar_y + bar_h + HP_TO_MORALE_GAP + font_h + MORALE_TEXT_GAP

        _hp_panel(p_bar_x, p_bar_y, morale_bar_y)
        _hp_panel(e_bar_x, e_bar_y, enemy_morale_bar_y)

        # HP bars (label is typically drawn by _draw_bar)
        self._draw_bar(screen, p_bar_x, p_bar_y, bar_w, bar_h,
                    self._player.hp, self._player.hp_max, "Your HP", text_gap=HP_TEXT_GAP)
        self._draw_bar(screen, e_bar_x, e_bar_y, bar_w, bar_h,
                    self._enemy.hp, self._enemy.hp_max, "Enemy HP", text_gap=HP_TEXT_GAP)

        self._draw_morale_bar(screen, p_bar_x, morale_bar_y, self._player.morale, "YOUR", text_gap=MORALE_TEXT_GAP)
        self._draw_morale_bar(screen, e_bar_x, enemy_morale_bar_y, self._enemy.morale, "ENEMY", text_gap=MORALE_TEXT_GAP)

        # Buttons
        is_player_turn = (getattr(self.engine, "turn_owner", None) == "player")

        self._draw_button(
            screen, self.btn_fire, "Fire",
            is_player_turn
        )

        self._draw_button(
            screen, self.btn_repair, "Repair",
            is_player_turn and (self._player.hp < self._player.hp_max)
        )

        self._draw_button(
            screen, self.btn_flee, "Flee",
            is_player_turn
        )
        self._draw_button(
            screen, self.btn_quick_repair, "Quick Repair",
            is_player_turn and (self._player.hp < self._player.hp_max)
        )

        # --- Stance UI (big, vertical, with transparent panel) ---
        active = self.engine.stance.value
        locked = self.engine._stance_changed_this_round

        panel_rect = getattr(self, "_stance_panel_rect", None)
        if panel_rect:
            panel = pygame.Surface((panel_rect.w, panel_rect.h), pygame.SRCALPHA)
            pygame.draw.rect(panel, (0, 0, 0, 170), panel.get_rect(), border_radius=12)
            pygame.draw.rect(panel, (20, 22, 30, 180), panel.get_rect(), 2, border_radius=12)
            screen.blit(panel, (panel_rect.x, panel_rect.y))

        for key, rect in self._stance_rects.items():
            icon = self._stance_icons.get(key)
            if not icon:
                continue

            img = pygame.transform.smoothscale(icon, (rect.w, rect.h))
            is_active = (key == active)

            if locked and not is_active:
                img.set_alpha(90)
            elif not is_active:
                img.set_alpha(170)

            screen.blit(img, rect.topleft)

            # Highlight
            if is_active:
                pygame.draw.rect(screen, (240, 220, 140), rect, 3, border_radius=10)
            else:
                pygame.draw.rect(screen, (10, 10, 10), rect, 2, border_radius=10)

        # Combat log bottom-right
        self._draw_combat_log_panel(screen)

        if getattr(self, "_result_showing", False):
            self._draw_result_overlay(screen)
            t = self.font.render("ENTER / Click to continue", True, (170, 170, 170))

        self._draw_reveal_overlay(screen)

        # --- DEBUG COMBAT STATS ---
        # --- Combat debug panel (left of combat log) ---
        log_rect = self._log_panel_rect

        dbg_w = 320
        dbg_h = log_rect.height
        dbg_x = log_rect.left - dbg_w - 12
        dbg_y = log_rect.top

        self._draw_debug_panel(screen, dbg_x, dbg_y, dbg_w, dbg_h)
        self._draw_combat_debug(screen, dbg_x, dbg_y)

    def _draw_debug_panel(self, screen, x, y, w, h):
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 160))
        pygame.draw.rect(panel, (40, 40, 40), panel.get_rect(), 2, border_radius=6)
        screen.blit(panel, (x, y))

    def _draw_combat_debug(self, screen, x, y):

        panel_width = 320
        panel_padding = 10
        line_height = 20
        cur_y = y + panel_padding
        panel_rect = pygame.Rect(x, y, panel_width, 260)

        panel_surf = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
        panel_surf.fill((0, 0, 0, 170))  # transparent black
        screen.blit(panel_surf, panel_rect.topleft)

        def draw_line(text):
            nonlocal cur_y

            words = text.split(" ")
            line = ""

            for word in words:
                test_line = line + word + " "
                text_width = self.font.size(test_line)[0]

                if text_width > panel_width - panel_padding * 2:
                    surf = self.font.render(line, True, (220, 220, 220))
                    screen.blit(surf, (x + panel_padding, cur_y))
                    cur_y += line_height
                    line = word + " "
                else:
                    line = test_line

            if line:
                surf = self.font.render(line, True, (220, 220, 220))
                screen.blit(surf, (x + panel_padding, cur_y))
                cur_y += line_height

        cur_y = y + 8
        line_h = 18

        mods = self.engine.get_live_combat_multipliers(self.engine.p)
        #mods = self.engine.get_debug_combat_modifiers(self.engine.e)  TITEL ÄNDERN
        hit_chance = self.engine._compute_hit_chance(self.engine.p)
        rep_p = self.engine._compute_repair_success(self.engine.p)

        line_h = 18
        cur_y = y + 10
        #flee chance + pressure (pressure is the main driver of flee chance, so good to see them together)
        fc = self.engine._compute_flee_chance()
        pr = self.engine._compute_enemy_pressure()
        surf = self.font.render(f"Flee Chance: {fc*100:5.1f}%  (pressure {pr:.2f})", True, (230, 230, 230))
        screen.blit(surf, (x + 10, cur_y))
        cur_y += 18


        title = self.font.render("PLAYER MODIFIERS", True, (230, 230, 230))
        base_hit = 0.75
        hit_mult = float(mods.get("hit", 1.0))
        hc_txt = f"Hit Chance: {hit_chance*100:5.1f}%   (base {base_hit*100:.0f}% × x{hit_mult:.2f})"

        surf = self.font.render(hc_txt, True, (240, 220, 180))
        screen.blit(surf, (x + 10, cur_y))
        cur_y += 20

        screen.blit(title, (x + 10, cur_y))
        cur_y += 22

        draw_line("PLAYER MODIFIERS")

        for name in ("damage", "hit", "repair", "flee", "panic_fail"):
            value = float(mods.get(name, 0.0))

            if name == "panic_fail":
                txt = f"{name:<12}: {value*100:5.1f}%"
            else:
                pct = int((value - 1.0) * 100)
                txt = f"{name:<12}: x{value:.2f} ({pct:+d}%)"

            draw_line(txt)



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
            label=self.ctx.player.ship.name if hasattr(self.ctx.player.ship, "name") else "YOU",
            key="player",
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
            label=self._enemy.name.upper(),
            key="enemy",
        )


        # Particles + floating texts
        self._tick_and_draw_particles(screen)
        self._tick_and_draw_float_texts(screen)

    def _draw_unit(self, screen, x, y, spr, flip: bool, scale: float, fallback_color, label: str, key: str) -> None:

        # --- Soft shadow under unit (depth) ---
        def _draw_shadow(cx: int, cy: int, w: int, h: int, alpha: int = 90) -> None:
            # small surface for the shadow
            sw = max(1, int(w * 0.75))
            sh = max(1, int(h * 0.22))
            surf = pygame.Surface((sw, sh), pygame.SRCALPHA)

            # multi-pass ellipse = fake blur
            for i in range(3):
                a = max(0, alpha - i * 25)
                inset = i * 2
                pygame.draw.ellipse(
                    surf,
                    (0, 0, 0, a),
                    pygame.Rect(inset, inset, sw - inset * 2, sh - inset * 2),
                )

            screen.blit(surf, (cx - sw // 2, cy - sh // 2))

        # leichte "Bobbing"-Animation
        t = float(getattr(self, "_t", 0.0))
        bob = int(math.sin(t * 2.2 + (0.0 if not flip else 1.1)) * 3.0)

        if spr:
            sprite = spr
            if flip:
                sprite = pygame.transform.flip(sprite, True, False)

            # apply scale uniformly
            if abs(scale - 1.0) > 0.001:
                sprite = pygame.transform.smoothscale(
                    sprite,
                    (max(1, int(sprite.get_width() * scale)), max(1, int(sprite.get_height() * scale)))
                )
            r = sprite.get_rect(center=(int(x), int(y + bob)))
            # shadow sits slightly below the ship center
            _draw_shadow(r.centerx, r.centery + int(r.height * 0.33), r.width, r.height, alpha=95)

            # draw sprite
            screen.blit(sprite, r)

            # cache rect for VFX placement
            if hasattr(self, "_unit_rects"):
                self._unit_rects[key] = r.copy()

            screen.blit(sprite, r)
        else:
            rr = pygame.Rect(x - 90, y - 30 + bob, 180, 60)
            pygame.draw.ellipse(screen, fallback_color, rr)
            pygame.draw.rect(screen, (30, 30, 35), rr, 2)

            if hasattr(self, "_unit_rects"):
                self._unit_rects[key] = rr.copy()


        # --- Name sign (wood sign) ---
        # Determine bottom of unit sprite to place sign below it
        if spr:
            unit_bottom = r.bottom
        else:
            # fallback ellipse: height 60 centered on (x, y+bob)
            unit_bottom = (y + bob) + 30

        if getattr(self, "_sign_empty", None) is not None:
            sign_w, sign_h = 210, 56
            sign = pygame.transform.smoothscale(self._sign_empty, (sign_w, sign_h))
            sign_rect = sign.get_rect(midtop=(x, unit_bottom + 12))
            screen.blit(sign, sign_rect)

            # Render name centered on sign
            name = str(label)

            # Text color: dark ink on wood
            txt = self.font.render(name, True, (20, 20, 20))

            # Fit if too wide (simple scale-down)
            max_w = sign_w - 24
            if txt.get_width() > max_w and txt.get_width() > 0:
                scale = max(0.55, max_w / float(txt.get_width()))
                txt = pygame.transform.smoothscale(
                    txt, (int(txt.get_width() * scale), int(txt.get_height() * scale))
                )

            tx = sign_rect.centerx - txt.get_width() // 2
            ty = sign_rect.centery - txt.get_height() // 2
            screen.blit(txt, (tx, ty))

        else:
            # Fallback: old dark plate if sign missing
            plate = pygame.Rect(x - 80, unit_bottom + 12, 160, 22)
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

            # choose font (crits bigger)
            font = self._dmg_font_big if getattr(ft, "crit", False) else self._dmg_font

            # render main + outline for readability
            main = font.render(ft.text, True, ft.color)

            # optional scaling (crit punch)
            scale = float(getattr(ft, "scale", 1.0))
            if abs(scale - 1.0) > 0.01:
                main = pygame.transform.smoothscale(main, (int(main.get_width() * scale), int(main.get_height() * scale)))

            outline = font.render(ft.text, True, (0, 0, 0))
            if abs(scale - 1.0) > 0.01:
                outline = pygame.transform.smoothscale(outline, (int(outline.get_width() * scale), int(outline.get_height() * scale)))

            x = int(ft.x)
            y = int(ft.y)

            # 4-way outline (stronger than a single shadow)
            screen.blit(outline, (x - 2, y))
            screen.blit(outline, (x + 2, y))
            screen.blit(outline, (x, y - 2))
            screen.blit(outline, (x, y + 2))

            screen.blit(main, (x, y))

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

    def _add_floating_text(self, text, x, y):
        self._floating_texts.append({
            "text": text,
            "x": x,
            "y": y,
            "timer": 0.8  # Sekunden sichtbar
        })

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

    def _hp_scaled_layers(self, target_w: int):
        """Return (bg, fill, frame, glow, h) scaled to target_w, cached."""
        if not self._hp_bg or not self._hp_fill or not self._hp_frame or not self._hp_glow:
            return None

        target_w = max(1, int(target_w))
        cached = self._hp_cache.get(target_w)
        if cached:
            return cached

        # scale by width, keep aspect ratio based on bg
        bw, bh = self._hp_bg.get_size()
        s = target_w / float(bw)
        target_h = max(1, int(round(bh * s)))

        bg = pygame.transform.smoothscale(self._hp_bg, (target_w, target_h))
        fill = pygame.transform.smoothscale(self._hp_fill, (target_w, target_h))
        frame = pygame.transform.smoothscale(self._hp_frame, (target_w, target_h))
        glow = pygame.transform.smoothscale(self._hp_glow, (target_w, target_h))

        self._hp_cache[target_w] = (bg, fill, frame, glow, target_h)
        return self._hp_cache[target_w]

    def _hp_height_for_width(self, target_w: int) -> int:
        layers = self._hp_scaled_layers(target_w)
        if not layers:
            return 18
        return int(layers[4])

    def _draw_bar(self, screen, x, y, w, h, val, vmax, label, text_gap: int = 2):

        vmax = max(1, int(vmax))
        val = max(0, min(int(val), vmax))
        frac = val / vmax

        # --- New 4-layer HP bar if assets exist ---
        layers = self._hp_scaled_layers(w) if getattr(self, "_hp_bg", None) else None
        if layers:
            bg, fill, frame, glow, hh = layers

            # draw BG
            screen.blit(bg, (x, y))

            # draw FILL (clipped)
            fill_w = max(0, int(round(w * frac)))
            if fill_w > 0:
                # clip area from left
                area = pygame.Rect(0, 0, fill_w, hh)
                screen.blit(fill, (x, y), area)

            # draw FRAME
            screen.blit(frame, (x, y))
            
            # draw GLOW (top layer) with pulsing alpha
            import math
            t = getattr(self, "_hp_glow_t", 0.0)

            # pulse settings (tuning)
            speed = 2.2          # puls frequency
            base_a = 110         # min alpha
            amp_a = 110          # amplitude
            pulse = 0.5 + 0.5 * math.sin(t * speed)
            alpha = int(base_a + amp_a * pulse)

            # quantize alpha to reduce cache size (perf)
            alpha_q = int(round(alpha / 8.0) * 8)
            alpha_q = max(0, min(255, alpha_q))

            key = (w, alpha_q)
            cached = self._hp_glow_alpha_cache.get(key)
            if cached is None:
                g = glow.copy()
                g.set_alpha(alpha_q)
                self._hp_glow_alpha_cache[key] = g
                cached = g

            screen.blit(cached, (x, y))


            # label above bar (slightly tighter than before)
            txt = self.font.render(f"{label}: {val}/{vmax}", True, (230, 230, 230))
            screen.blit(txt, (x, y - self.font.get_height() - int(text_gap)))
            return

        # --- Fallback: old rect bar ---
        pygame.draw.rect(screen, (50, 55, 70), pygame.Rect(x, y, w, h), border_radius=4)
        pygame.draw.rect(screen, (80, 180, 120), pygame.Rect(x, y, int(w * frac), h), border_radius=4)
        pygame.draw.rect(screen, (25, 28, 38), pygame.Rect(x, y, w, h), 2, border_radius=4)

        txt = self.font.render(f"{label}: {val}/{vmax}", True, (230, 230, 230))
        screen.blit(txt, (x, y - self.font.get_height() - int(text_gap)))

    def _draw_morale_bar(self, screen, x, y, morale: int, label: str, text_gap: int = 2):
        if not self._morale_frame or not self._morale_fill or not self._morale_bg:
            return

        morale = max(0, min(100, int(morale)))
        frac = morale / 100.0
        scale = float(self._morale_scale)

        # --- scale all layers once ---
        bg_src = self._morale_bg
        fill_src = self._morale_fill
        frame_src = self._morale_frame

        w0, h0 = frame_src.get_size()
        w = int(w0 * scale)
        h = int(h0 * scale)

        bg = pygame.transform.smoothscale(bg_src, (w, h))
        fill = pygame.transform.smoothscale(fill_src, (w, h))
        frame = pygame.transform.smoothscale(frame_src, (w, h))

        # --- draw BACKGROUND (always full) ---
        screen.blit(bg, (x, y))

        # --- draw FILL (clipped) ---
        fill_w = max(1, int(w * frac))
        fill_rect = pygame.Rect(0, 0, fill_w, h)
        fill_surf = fill.subsurface(fill_rect)

        # CORRECT grayscale fade:
        # 50% morale -> 0% grayscale
        # 0% morale  -> 100% grayscale
        # desaturate below 75%
        if morale < 75:
            strength = morale/75
            fill_surf = self._apply_red_tint(fill_surf, strength)


        screen.blit(fill_surf, (x, y))

        # --- draw FRAME (always on top) ---
        screen.blit(frame, (x, y))

        # --- morale text ---
        txt = self.font.render(f"{label} MORALE: {morale}", True, (230, 230, 230))
        screen.blit(txt, (x, y - self.font.get_height() - int(text_gap)))



    def _draw_button(self, screen, rect: pygame.Rect, text: str, enabled: bool, subtext: str = ""):

        mx, my = pygame.mouse.get_pos()
        hover = rect.collidepoint(mx, my)

        # base colors
        bg = (70, 75, 95) if enabled else (45, 48, 60)
        if hover and enabled:
            bg = (82, 88, 112)

        # --- ability id aus text ableiten ---
        first = text.split(" ")[0].lower()
        ability_id = "quick_repair" if first == "quick" else first


        icon_size = rect.height - 46 - 8  # block height minus shield + gap
        shield_h = 46
        shield_w = rect.width

        icon_size = 90
        shield_h = 42
        overlap = 26

        icon_x = rect.x + rect.width // 2 - icon_size // 2
        icon_y = rect.y

        # ICON
        if ability_id in self._ability_icons:
            icon = self._ability_icons[ability_id]
            icon_scaled = pygame.transform.smoothscale(icon, (icon_size, icon_size))
            screen.blit(icon_scaled, (icon_x, icon_y))

        # SHIELD (liegt auf unterem Icon-Bereich)
        shield_y = rect.y + icon_size - overlap

        if self._name_shield:
            shield_scaled = pygame.transform.smoothscale(self._name_shield, (rect.width, shield_h))
            screen.blit(shield_scaled, (rect.x, shield_y))

        # TEXT
        label = text
        text_color = (30, 20, 10) if enabled else (90, 90, 90)
        text_surf = self.font.render(label, True, text_color)
        text_rect = text_surf.get_rect(center=(rect.x + rect.width // 2, shield_y + shield_h // 2))
        screen.blit(text_surf, text_rect)

