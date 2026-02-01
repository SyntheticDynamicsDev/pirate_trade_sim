from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import fields

@dataclass(frozen=True)
class LootCargoEntry:
    good_id: str
    min_tons: float
    max_tons: float
    chance: float


@dataclass(frozen=True)
class LootTable:
    gold_base: int = 0
    gold_mult: float = 0.0
    xp_base: int = 0
    xp_mult: float = 0.0
    cargo: List[LootCargoEntry] = field(default_factory=list)


@dataclass(frozen=True)
class CombatStats:
    # Defensive
    hp_max: int
    armor_physical: float  # percent
    armor_abyssal: float   # percent

    # Offensive
    damage_min: int
    damage_max: int
    damage_type: str       # "physical" | "abyssal"
    penetration: float     # percent, can be >100
    crit_chance: float     # 0..1
    crit_multiplier: float # e.g. 1.5 / 2.0

    # Tempo
    initiative_base: float

    # Meta
    difficulty_tier: int
    threat_level: int


@dataclass(frozen=True)
class EnemyDef:
    id: str
    name: str
    combat: CombatStats
    tags: List[str] = field(default_factory=list)  # optional, falls du später tags brauchst
    loot: LootTable = field(default_factory=LootTable)

    # --- Visuals ---
    sprite: Optional[str] = None
    sprite_scale: float = 1.0
    sprite_offset: Tuple[int, int] = (0, 0)
    sprite_size: Tuple[int, int] = (220, 140)
    sprite_flip_x: bool = True



@dataclass(frozen=True)
class GoodDef:
    id: str
    name: str
    category: str
    base_price: float
    spoil_rate_per_day: float
    target_stock: float

from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class VisualDef:
    sprite: str
    size: Tuple[int, int] = (260, 160)
    scale: float = 1.0
    offset: Tuple[int, int] = (0, 0)
    flip_x: bool = False

from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ShipDef:
    id: str
    name: str

    # world/economy
    capacity_tons: float
    speed_px_s: float
    crew_max: int
    crew_required: int
    upkeep_per_day: int
    turn_rate: float
    accel: float
    draft_m: float
    shallow_water_ok: bool
    cargo_protection: float
    pirate_target_mult: float
    cannon_slots: int

    # NEW: combat + visual (wie enemies)
    combat: CombatStats
    visual: VisualDef


@dataclass(frozen=True)
class CityTypeDef:
    id: str
    name: str
    market_size: str
    lot_size_tons: float
    needs: dict
    initial_stock_multiplier: float
    top_needs_goods: List[str]


@dataclass(frozen=True)
class CityDef:
    id: str
    name: str
    city_type_id: str
    pos: Tuple[float, float]
    harbor_radius: float
    map_id: str = "world_01"


@dataclass
class Content:
    goods: Dict[str, GoodDef]
    ships: Dict[str, ShipDef]
    city_types: Dict[str, CityTypeDef]
    cities: Dict[str, CityDef]
    enemies: Dict[str, EnemyDef]


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
    

def _parse_loot(ld: dict) -> LootTable:
    cargo_entries = []
    for ce in ld.get("cargo", []):
        cargo_entries.append(LootCargoEntry(
            good_id=str(ce["good_id"]),
            min_tons=float(ce["min_tons"]),
            max_tons=float(ce["max_tons"]),
            chance=float(ce["chance"]),
        ))
    return LootTable(
        gold_base=int(ld.get("gold", {}).get("base", 0)),
        gold_mult=float(ld.get("gold", {}).get("mult", 0.0)),
        xp_base=int(ld.get("xp", {}).get("base", 0)),
        xp_mult=float(ld.get("xp", {}).get("mult", 0.0)),
        cargo=cargo_entries,
    )


def load_content(content_dir: str = "content") -> Content:
    base = Path(content_dir)

    goods_raw = _read_json(base / "goods.json")["goods"]
    ships_raw = _read_json(base / "ships.json")["ships"]
    cities_bundle = _read_json(base / "cities.json")
    city_types_raw = cities_bundle.get("city_types", [])
    cities_raw = cities_bundle.get("cities", [])
    enemies_raw = _read_json(base / "enemies.json")["enemies"]

    goods = {g["id"]: GoodDef(**g) for g in goods_raw}

    ships: Dict[str, ShipDef] = {}
    for s in ships_raw:
        if "combat" not in s or s["combat"] is None:
            raise ValueError(f"Ship '{s.get('id','?')}' missing required 'combat' block.")
        if "visual" not in s or s["visual"] is None:
            raise ValueError(f"Ship '{s.get('id','?')}' missing required 'visual' block.")

        c = s["combat"]
        v = s["visual"]

        combat = CombatStats(
            hp_max=int(c["hp_max"]),
            armor_physical=float(c.get("armor_physical", 0.0)),
            armor_abyssal=float(c.get("armor_abyssal", 0.0)),

            damage_min=int(c["damage_min"]),
            damage_max=int(c["damage_max"]),
            damage_type=str(c.get("damage_type", "physical")),
            penetration=float(c.get("penetration", 0.0)),

            crit_chance=float(c.get("crit_chance", 0.0)),
            crit_multiplier=float(c.get("crit_multiplier", 1.5)),

            initiative_base=float(c.get("initiative_base", 1.0)),

            difficulty_tier=int(c.get("difficulty_tier", 1)),
            threat_level=int(c.get("threat_level", 1)),
        )

        visual = VisualDef(
            sprite=str(v["sprite"]),
            size=tuple(v.get("size", (260, 160))),
            scale=float(v.get("scale", 1.0)),
            offset=tuple(v.get("offset", (0, 0))),
            flip_x=bool(v.get("flip_x", False)),
        )

        sd = ShipDef(
            id=str(s["id"]),
            name=str(s.get("name", s["id"])),

            capacity_tons=float(s["capacity_tons"]),
            speed_px_s=float(s["speed_px_s"]),
            crew_max=int(s["crew_max"]),
            crew_required=int(s["crew_required"]),
            upkeep_per_day=int(s["upkeep_per_day"]),
            turn_rate=float(s["turn_rate"]),
            accel=float(s["accel"]),
            draft_m=float(s["draft_m"]),
            shallow_water_ok=bool(s["shallow_water_ok"]),
            cargo_protection=float(s["cargo_protection"]),
            pirate_target_mult=float(s["pirate_target_mult"]),
            cannon_slots=int(s["cannon_slots"]),

            combat=combat,
            visual=visual,
        )

        ships[sd.id] = sd


    city_types = {ct["id"]: CityTypeDef(**ct) for ct in city_types_raw}

    cities = {
        c["id"]: CityDef(
            id=c["id"],
            name=c["name"],
            city_type_id=c["city_type_id"],
            pos=(float(c["pos"][0]), float(c["pos"][1])),
            harbor_radius=float(c["harbor_radius"]),
            map_id=str(c.get("map_id", "world_01")),
        )
        for c in cities_raw
    }

    enemies: Dict[str, EnemyDef] = {}
    for e in enemies_raw:
        loot = _parse_loot(e.get("loot", {}))
        tags = list(e.get("tags", []))  # optional: falls du tags später im JSON direkt pflegen willst

        # Neues Stat-Modell
        c = e["combat"]
        combat = CombatStats(
            hp_max=int(c["hp_max"]),
            armor_physical=float(c.get("armor_physical", 0.0)),
            armor_abyssal=float(c.get("armor_abyssal", 0.0)),

            damage_min=int(c["damage_min"]),
            damage_max=int(c["damage_max"]),
            damage_type=str(c.get("damage_type", "physical")),
            penetration=float(c.get("penetration", 0.0)),
            crit_chance=float(c.get("crit_chance", 0.0)),
            crit_multiplier=float(c.get("crit_multiplier", 1.5)),

            initiative_base=float(c.get("initiative_base", 1.0)),

            difficulty_tier=int(c.get("difficulty_tier", 1)),
            threat_level=int(c.get("threat_level", 1)),
        )

        # Visuals
        vis = e.get("visual", {}) or {}

        enemies[e["id"]] = EnemyDef(
            id=e["id"],
            name=e.get("name", e["id"]),
            combat=combat,
            loot=loot,
            tags=tags,

            sprite=vis.get("sprite"),
            sprite_scale=float(vis.get("scale", 1.0)),
            sprite_offset=tuple(vis.get("offset", [0, 0])),
            sprite_size=tuple(vis.get("size", [220, 140])),
            sprite_flip_x=bool(vis.get("flip_x", True)),
        )



    return Content(goods=goods, ships=ships, city_types=city_types, cities=cities, enemies=enemies)
