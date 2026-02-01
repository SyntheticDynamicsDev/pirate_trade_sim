# core/save_system.py
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Dict, Optional, Tuple

import pygame

from data.loader import load_content
from world.model import World, City, Ship, Player, CargoHold, CargoLot
from economy.market import CityMarketState
from core.progression import xp_to_level, cap_xp



SAVE_VERSION = 1
DEFAULT_SAVE_PATH = os.path.join("saves", "savegame.json")
PREVIEW_PATH = os.path.join("saves", "preview.png")

def save_exists(path: str = DEFAULT_SAVE_PATH) -> bool:
    import os
    return os.path.exists(path)


def save_preview(surface: "pygame.Surface", path: str = PREVIEW_PATH) -> None:
    import pygame
    _ensure_save_dir(path)

    # Thumbnail-Größe (16:9)
    target_w, target_h = 420, 236

    thumb = pygame.transform.smoothscale(surface, (target_w, target_h))
    pygame.image.save(thumb, path)

def load_save_metadata(path: str = DEFAULT_SAVE_PATH) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    clock = data.get("clock", {}) or {}
    player = data.get("player", {}) or {}

    # "Spielzeit": In-Game Zeit (Tag + Uhrzeit)
    day = int(clock.get("day", 1))
    sec = float(clock.get("seconds_in_day", 0.0))
    hours = int(sec // 3600)
    minutes = int((sec % 3600) // 60)

    # XP + Level
    xp = cap_xp(int(player.get("xp", 0)))
    lvl, cur, need = xp_to_level(xp)

    return {
        "day": day,
        "time_str": f"{hours:02d}:{minutes:02d}",
        "xp": xp,
        "level": lvl,
        "xp_cur": cur,
        "xp_need": need,
        "enc_meter": float(data.get("enc_meter", 0.0)),
    }


def _ensure_save_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _tuple2(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return (float(v[0]), float(v[1]))
    return v


def save_game(ctx: Any, path: str = DEFAULT_SAVE_PATH) -> None:
    """
    Speichert den minimal nötigen Spielzustand aus ctx in JSON.
    Content wird NICHT gespeichert (wird beim Laden aus content/ wiederhergestellt).
    """
    _ensure_save_dir(path)

    clock = getattr(ctx, "clock", None)
    player = getattr(ctx, "player", None)

    if clock is None or player is None:
        raise RuntimeError("save_game: ctx.clock oder ctx.player fehlt")

    ship = player.ship

    # Markets
    markets_out: Dict[str, Dict[str, Any]] = {}
    markets = getattr(ctx, "markets", {}) or {}
    for city_id, m in markets.items():
        markets_out[city_id] = {
            "stock": dict(m.stock),
            "price_stock": dict(m.price_stock),
            "pending": dict(getattr(m, "pending", {}) or {}),
            "top_needs": list(getattr(m, "top_needs", []) or []),
        }

    # Cargo lots
    lots_out = []
    cargo = getattr(player, "cargo", None)
    if cargo is not None:
        for lot in cargo.lots:
            lots_out.append({
                "good_id": str(lot.good_id),
                "qty_tons": float(lot.qty_tons),
                "age_days": int(getattr(lot, "age_days", 0)),
            })

    # NPC shipments
    shipments_out = []
    for s in list(getattr(ctx, "npc_shipments", []) or []):
        shipments_out.append({
            "src_city_id": s.src_city_id,
            "dst_city_id": s.dst_city_id,
            "good_id": s.good_id,
            "qty": float(s.qty),
            "eta_days": int(s.eta_days),
            "created_day": int(getattr(s, "created_day", 0)),
        })

    data = {
        "version": SAVE_VERSION,

        "clock": {
            "day": int(clock.day),
            "seconds_in_day": float(clock.seconds_in_day),
            "day_length_seconds": float(clock.day_length_seconds),
            "time_scale": float(clock.time_scale),
            "paused": bool(clock.paused),
            "display_day_start_hour": int(clock.display_day_start_hour),
        },

        "world": {
            "current_map_id": str(getattr(ctx, "current_map_id", "world_01")),
            "last_city_id": getattr(ctx, "last_city_id", None),
            "last_world_ship_pos": list(getattr(ctx, "last_world_ship_pos", ship.pos)),
            "enc_meter": float(getattr(ctx, "enc_meter", 0.0)),
        },

        "player": {
            "money": int(player.money),
            "xp": cap_xp(int(getattr(player, "xp", 0))),
            "crew_hp": int(getattr(player, "crew_hp", 0)),
            "docked_city_id": getattr(player, "docked_city_id", None),
            "houses": sorted(list(getattr(player, "houses", set()) or [])),
            "cargo_lots": lots_out,
            "master_lives": int(ctx.player.master_lives),
            "master_lives_max": int(ctx.player.master_lives_max),
        },

        "ship": {
            "id": ship.id,
            "name": ship.name,
            "pos": list(ship.pos),
            "vel": list(ship.vel),
            "heading": ship.heading,
            "ang_vel": ship.ang_vel,
            "throttle": ship.throttle,

            # World stats
            "speed": ship.speed,
            "turn_rate": ship.turn_rate,
            "accel": ship.accel,
            "draft_m": ship.draft_m,
            "capacity_tons": ship.capacity_tons,
            "cargo_protection": ship.cargo_protection,
            "pirate_target_mult": ship.pirate_target_mult,
            "crew_max": ship.crew_max,
            "crew_required": ship.crew_required,
            "upkeep_per_day": ship.upkeep_per_day,
            "cannon_slots": ship.cannon_slots,

            # Combat runtime
            "hp": ship.hp,
            "hp_max": ship.hp_max,
        },


        "markets": markets_out,
        "npc_shipments": shipments_out,

        "city_supply_idx": {
            # keys: (city_id, category) -> float
            f"{k[0]}|{k[1]}": float(v)
            for k, v in (getattr(ctx, "city_supply_idx", {}) or {}).items()
        },

        "trade_ui_state": _serialize_trade_ui_state(getattr(ctx, "trade_ui_state", None)),

        "run_config": _serialize_run_config(getattr(ctx, "run_config", None)),
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_game(ctx: Any, path: str = DEFAULT_SAVE_PATH) -> bool:
    """
    Lädt Savegame in den bestehenden ctx.
    Gibt False zurück, wenn kein Save existiert.
    """
    if not os.path.exists(path):
        return False

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # --- Content neu laden (Source of Truth) ---
    ctx.content = load_content("content")

    # --- World/Cities neu aufbauen (wie Setup), aber ohne “neues” Market Init ---
    cities = []
    from settings import SCREEN_W, SCREEN_H
    MAP_SRC_W, MAP_SRC_H = 1536, 1024

    def scale_pos(pos):
        x, y = pos
        if x > SCREEN_W or y > SCREEN_H:
            x = x * (SCREEN_W / MAP_SRC_W)
            y = y * (SCREEN_H / MAP_SRC_H)
        return (x, y)

    for c in ctx.content.cities.values():
        cities.append(City(
            id=c.id,
            name=c.name,
            pos=scale_pos(c.pos),
            harbor_radius=c.harbor_radius,
            city_type_id=c.city_type_id,
            map_id=getattr(c, "map_id", "world_01"),
        ))

    ctx.world = World(cities=cities)

    # --- Clock ---
    cd = data.get("clock", {})
    clock = ctx.clock
    clock.day = int(cd.get("day", 1))
    clock.seconds_in_day = float(cd.get("seconds_in_day", 0.0))
    clock.day_length_seconds = float(cd.get("day_length_seconds", clock.day_length_seconds))
    clock.time_scale = float(cd.get("time_scale", 1.0))
    clock.paused = bool(cd.get("paused", False))
    clock.display_day_start_hour = int(cd.get("display_day_start_hour", 8))

    # --- Map meta ---
    wd = data.get("world", {})
    ctx.current_map_id = str(wd.get("current_map_id", "world_01"))
    ctx.last_city_id = wd.get("last_city_id", None)
    ctx.last_world_ship_pos = _tuple2(wd.get("last_world_ship_pos", [0.0, 0.0]))
    ctx.enc_meter = float(data.get("enc_meter", 0.0))
    ctx.enc_meter = max(0.0, min(1.0, ctx.enc_meter))


    # --- Ship ---
    sd = data.get("ship", {})
    ship = Ship(
        id=str(sd.get("id", "sloop")),
        name=str(sd.get("name", "Ship")),
        pos=_tuple2(sd.get("pos", [0.0, 0.0])),
        speed=float(sd.get("speed", 200.0)),
        capacity_tons=float(sd.get("capacity_tons", 0.0)),
    )
    ship.vel = _tuple2(sd.get("vel", [0.0, 0.0]))
    ship.heading = float(sd.get("heading", 0.0))
    ship.ang_vel = float(sd.get("ang_vel", 0.0))
    ship.throttle = float(sd.get("throttle", 0.0))

    # Stats
    ship.hull_hp = int(sd.get("hull_hp", 0))
    ship.crew_max = int(sd.get("crew_max", 0))
    ship.crew_required = int(sd.get("crew_required", 0))
    ship.upkeep_per_day = int(sd.get("upkeep_per_day", 0))
    ship.turn_rate = float(sd.get("turn_rate", 1.0))
    ship.accel = float(sd.get("accel", 1.0))
    ship.draft_m = float(sd.get("draft_m", 0.0))
    ship.shallow_water_ok = bool(sd.get("shallow_water_ok", False))
    ship.cargo_protection = float(sd.get("cargo_protection", 0.0))
    ship.pirate_target_mult = float(sd.get("pirate_target_mult", 1.0))
    ship.armor = int(sd.get("armor", 0))
    ship.cannon_slots = int(sd.get("cannon_slots", 0))
    ship.basic_attack_dmg = int(sd.get("basic_attack_dmg", 0))

    # --- Player + Cargo ---
    pd = data.get("player", {})
    cargo = CargoHold()
    for lotd in pd.get("cargo_lots", []) or []:
        cargo.lots.append(CargoLot(
            good_id=str(lotd["good_id"]),
            qty_tons=float(lotd["qty_tons"]),
            age_days=int(lotd.get("age_days", 0)),
        ))

    player = Player(
        money=int(pd.get("money", 0)),
        houses=set(pd.get("houses", []) or []),
        ship=ship,
    )
    player.xp = int(pd.get("xp", 0))
    player.xp = cap_xp(player.xp)
    player.crew_hp = int(pd.get("crew_hp", max(0, ship.crew_max)))
    player.docked_city_id = pd.get("docked_city_id", None)
    player.cargo = cargo

    ctx.player = player
    ctx.start_city_id = cities[0].id if cities else None
    player_data = data.get("player", {})  # data ist dein geladenes JSON dict

    ctx.player.master_lives = int(player_data.get("master_lives", 3))
    ctx.player.master_lives_max = int(player_data.get("master_lives_max", 3))

    ctx.player.master_lives_max = max(1, int(ctx.player.master_lives_max))
    ctx.player.master_lives = max(0, min(int(ctx.player.master_lives), int(ctx.player.master_lives_max)))


    # --- Economy + Markets ---
    from economy.economy import EconomyEngine
    ctx.economy = EconomyEngine()

    ctx.markets = {}
    for city_id, md in (data.get("markets", {}) or {}).items():
        m = CityMarketState(city_id=city_id)
        m.stock = {k: float(v) for k, v in (md.get("stock", {}) or {}).items()}
        m.price_stock = {k: float(v) for k, v in (md.get("price_stock", {}) or {}).items()}
        m.pending = {k: float(v) for k, v in (md.get("pending", {}) or {}).items()}
        m.top_needs = list(md.get("top_needs", []) or [])
        ctx.markets[city_id] = m

    # Falls Save ohne Markets (oder neue Stadt hinzugefügt): defensiv initialisieren
    for city in ctx.world.cities:
        if city.id not in ctx.markets:
            ctx.markets[city.id] = CityMarketState(city_id=city.id)

    # NPC shipments
    from economy.npc_trade import Shipment
    ctx.npc_shipments = []
    for s in (data.get("npc_shipments", []) or []):
        ctx.npc_shipments.append(Shipment(
            src_city_id=s["src_city_id"],
            dst_city_id=s["dst_city_id"],
            good_id=s["good_id"],
            qty=float(s["qty"]),
            eta_days=int(s["eta_days"]),
            created_day=int(s.get("created_day", 0)),
        ))

    # supply idx
    ctx.city_supply_idx = {}
    for k, v in (data.get("city_supply_idx", {}) or {}).items():
        # key format: "city|category"
        if "|" in k:
            city_id, cat = k.split("|", 1)
            ctx.city_supply_idx[(city_id, cat)] = float(v)

    # UI state (optional)
    ctx.trade_ui_state = _deserialize_trade_ui_state(data.get("trade_ui_state", None))

    # run_config (optional)
    _deserialize_run_config(getattr(ctx, "run_config", None), data.get("run_config", None))

    return True


def _serialize_trade_ui_state(st: Any) -> Optional[Dict[str, Any]]:
    if not st:
        return None
    out = dict(st)
    # sets -> lists
    if "favorite_goods" in out and isinstance(out["favorite_goods"], set):
        out["favorite_goods"] = sorted(list(out["favorite_goods"]))
    if "enabled_categories" in out and isinstance(out["enabled_categories"], set):
        out["enabled_categories"] = sorted(list(out["enabled_categories"]))
    return out


def _deserialize_trade_ui_state(d: Any) -> Optional[Dict[str, Any]]:
    if not d:
        return None
    out = dict(d)
    if "favorite_goods" in out and isinstance(out["favorite_goods"], list):
        out["favorite_goods"] = set(out["favorite_goods"])
    if "enabled_categories" in out and isinstance(out["enabled_categories"], list):
        out["enabled_categories"] = set(out["enabled_categories"])
    return out


def _serialize_run_config(rc: Any) -> Optional[Dict[str, Any]]:
    if rc is None:
        return None
    # run_config ist bei dir ein Dataclass-ähnliches Objekt; wir nehmen nur primitive Felder
    out = {}
    for k, v in vars(rc).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
    return out


def _deserialize_run_config(rc: Any, d: Any) -> None:
    if rc is None or not d:
        return
    for k, v in d.items():
        try:
            setattr(rc, k, v)
        except Exception:
            pass
