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
class EnemyDef:
    id: str
    name: str
    hull_hp: int
    crew_max: int
    armor: int
    cannon_slots: int
    basic_attack_dmg: int
    speed_px_s: float
    tags: List[str] = field(default_factory=list)


    # existing stuff...
    ai: object = None
    loot: object = None

    # --- NEW: Visuals ---
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


@dataclass(frozen=True)
class ShipDef:
    id: str
    name: str
    capacity_tons: float
    speed_px_s: float

    # optional / zusätzliche Tuning-Werte (aus ships.json)
    turn_rate: float = 1.0
    accel: float = 1.0
    hull_hp: int = 0
    crew_max: int = 0
    crew_required: int = 0
    upkeep_per_day: int = 0
    draft_m: float = 0.0
    shallow_water_ok: bool = False
    cargo_protection: float = 0.0
    pirate_target_mult: float = 1.0
    armor: int = 0
    cannon_slots: int = 0
    basic_attack_dmg: int = 0

    # --- NEW: Visuals (aus ships.json) ---
    sprite: Optional[str] = None
    sprite_scale: float = 1.0
    sprite_offset: Tuple[int, int] = (0, 0)
    sprite_size: Tuple[int, int] = (260, 160)



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

    shipdef_fields = {f.name for f in fields(ShipDef)}
    ships = {s["id"]: ShipDef(**{k: v for k, v in s.items() if k in shipdef_fields}) for s in ships_raw}

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
        tags = list(e.get("ai", {}).get("tags", []))
        stats = e["stats"]

        # --- FIX: visuals pro enemy innerhalb der Schleife ---
        vis = e.get("visual", {}) or {}

        enemies[e["id"]] = EnemyDef(
            id=e["id"],
            name=e.get("name", e["id"]),
            hull_hp=int(stats["hull_hp"]),
            crew_max=int(stats["crew_max"]),
            armor=int(stats["armor"]),
            cannon_slots=int(stats["cannon_slots"]),
            basic_attack_dmg=int(stats["basic_attack_dmg"]),
            speed_px_s=float(stats["speed_px_s"]),
            loot=loot,
            tags=tags,

            # --- Visuals ---
            sprite=vis.get("sprite"),
            sprite_scale=float(vis.get("scale", 1.0)),
            sprite_offset=tuple(vis.get("offset", [0, 0])),
            sprite_size=tuple(vis.get("size", [220, 140])),
            sprite_flip_x=bool(vis.get("flip_x", True)),
        )


    return Content(goods=goods, ships=ships, city_types=city_types, cities=cities, enemies=enemies)
