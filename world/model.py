from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from dataclasses import dataclass, field
from typing import List
from math import pi


Vec2 = Tuple[float, float]

@dataclass
class City:
    id: str
    name: str
    pos: Vec2
    harbor_radius: float
    city_type_id: str
    map_id: str = "world_01"

@dataclass
class Ship:
    # Pflichtfelder (ohne Default) müssen zuerst kommen
    type_id: str
    name: str
    pos: Vec2
    speed: float                 # max speed in px/s
    capacity_tons: float

    # --- Physikzustand (Defaults) ---
    vel: Vec2 = (0.0, 0.0)        # px/s
    heading: float = 0.0          # rad
    ang_vel: float = 0.0          # rad/s
    throttle: float = 0.0         # -1..+1

    # --- Stats / Rest (Defaults) ---
    hull_hp: int = 0
    crew_max: int = 0
    crew_required: int = 0
    upkeep_per_day: int = 0
    turn_rate: float = 1.0
    accel: float = 1.0
    draft_m: float = 0.0
    shallow_water_ok: bool = False
    cargo_protection: float = 0.0
    pirate_target_mult: float = 1.0
    armor: int = 0
    cannon_slots: int = 0
    basic_attack_dmg: int = 0
        
@dataclass
class CargoLot:
    good_id: str
    qty_tons: float
    age_days: int = 0

@dataclass
class CargoHold:
    lots: List[CargoLot] = field(default_factory=list)

    def total_tons(self) -> float:
        return sum(l.qty_tons for l in self.lots)

    def add_lot(self, good_id: str, qty_tons: float) -> None:
        if qty_tons <= 0:
            return
        self.lots.append(CargoLot(good_id=good_id, qty_tons=qty_tons, age_days=0))

    def remove_fifo(self, good_id: str, qty_tons: float) -> float:
        """
        Removes qty_tons from oldest lots first (FIFO).
        Returns actual removed amount (may be less if not enough stock).
        """
        if qty_tons <= 0:
            return 0.0

        removed = 0.0
        # Oldest first: lots are already chronological by insertion
        for lot in list(self.lots):
            if lot.good_id != good_id:
                continue
            if removed >= qty_tons:
                break
            take = min(lot.qty_tons, qty_tons - removed)
            lot.qty_tons -= take
            removed += take
            if lot.qty_tons <= 0.0001:
                self.lots.remove(lot)

        return removed

    def tons_by_good(self) -> dict:
        out = {}
        for lot in self.lots:
            out[lot.good_id] = out.get(lot.good_id, 0.0) + lot.qty_tons
        return out

@dataclass
class Player:
    money: int
    houses: Set[str]
    ship: Ship
    docked_city_id: Optional[str] = None
    cargo: CargoHold = field(default_factory=CargoHold)

    # NEW: persistent progression stats
    xp: int = 0

    #Lives for Mastery Mode
    master_lives: int = 1
    master_lives_max: int = 1

    def __post_init__(self):
        # Master lives init clamp
        if self.master_lives_max <= 0:
            self.master_lives_max = 3
        if self.master_lives <= 0:
            self.master_lives = self.master_lives_max
        self.master_lives = max(0, min(self.master_lives, self.master_lives_max))


@dataclass
class World:
    cities: List[City]

    def find_city_in_range(self, pos: Vec2) -> Optional[City]:
        x, y = pos
        for c in self.cities:
            cx, cy = c.pos
            dx = cx - x
            dy = cy - y
            if (dx*dx + dy*dy) ** 0.5 <= c.harbor_radius:
                return c
        return None
