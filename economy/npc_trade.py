# npc_trade.py
from __future__ import annotations
from dataclasses import dataclass
import random
from typing import Dict, List, Optional, Tuple

@dataclass
class Shipment:
    src_city_id: str
    dst_city_id: str
    good_id: str
    qty: float
    eta_days: int
    # optional für Debug/Stats
    created_day: int = 0

def _city_type(ctx, city):
    # Präziser Workflow: CityType kommt ausschließlich aus Content (cities.json)
    cdef = ctx.content.cities.get(city.id)
    if cdef is None:
        return None
    return ctx.content.city_types.get(cdef.city_type_id)


def _need_weight(need: str) -> float:
    return {
        "critical": 1.75,
        "high": 1.35,
        "normal": 1.00,
        "low": 0.65,
        "irrelevant": 0.25,
    }.get((need or "normal").strip().lower(), 1.0)


def _target_for(ctx, city, good) -> float:
    ctype = _city_type(ctx, city)
    if ctype is None:
        return float(good.target_stock)
    need = (ctype.needs.get(good.category, "normal") or "normal").strip().lower()
    mult = ctx.economy.NEED_TARGET_MULT.get(need, 1.0)
    return float(good.target_stock) * float(mult)


def _travel_time_days(city_a, city_b) -> int:
    """
    MVP: 1..6 Tage. Wenn du Koordinaten hast: Distanz->Tage.
    """
    ax, ay = getattr(city_a, "x", None), getattr(city_a, "y", None)
    bx, by = getattr(city_b, "x", None), getattr(city_b, "y", None)
    if ax is None or ay is None or bx is None or by is None:
        return 2
    # Manhattan als robustes MVP
    d = abs(ax - bx) + abs(ay - by)
    return max(1, min(6, int(round(d / 8))))


def _ensure_ctx_state(ctx) -> None:
    if not hasattr(ctx, "npc_shipments") or ctx.npc_shipments is None:
        ctx.npc_shipments = []  # List[Shipment]


def _apply_shipments_arrival(ctx, rng: random.Random) -> None:
    """
    Reduziert ETA, liefert an Ziel aus, kann unterwegs verloren gehen.
    """
    _ensure_ctx_state(ctx)

    # globale Risiko-Parameter (später an Welt/Region koppeln)
    base_loss_chance = 0.06  # 6% Shipment-Verlust/Tag (Piraten, Sturm)
    partial_loss_range = (0.15, 0.55)  # 15..55% Mengenverlust

    remaining: List[Shipment] = []
    for s in ctx.npc_shipments:
        s.eta_days -= 1
        if s.eta_days > 0:
            remaining.append(s)
            continue

        # angekommen: Verlustwurf
        qty = float(s.qty)
        if qty <= 0:
            continue

        if rng.random() < base_loss_chance:
            # Teilverlust oder Totalausfall (MVP)
            if rng.random() < 0.25:
                qty = 0.0
            else:
                qty *= (1.0 - rng.uniform(*partial_loss_range))

        if qty <= 0:
            continue

        dst_market = ctx.markets.get(s.dst_city_id)
        if dst_market is None:
            continue
        dst_market.stock[s.good_id] = round(float(dst_market.stock.get(s.good_id, 0.0)) + qty, 3)

        # price_stock NICHT sofort springen lassen; der Tages-Tick zieht es träge nach.
        # Optional: minimaler Pull, damit Lieferung “gefühlt” reinhaut:
        ps = float(dst_market.price_stock.get(s.good_id, dst_market.stock[s.good_id]))
        dst_market.price_stock[s.good_id] = round(max(ps, 0.0), 3)

    ctx.npc_shipments = remaining


def _choose_arbitrage(ctx, rng: random.Random) -> Optional[Tuple[str, str, str, float, int]]:
    """
    Findet (src, dst, good, qty, eta) für NPC-Arbitrage.
    Minimalheuristik: max( dst_bid - src_ask ) * qty, nur wenn src genug hat und dst knapp ist.
    """
    cities = list(ctx.world.cities)
    if len(cities) < 2:
        return None

    # Stichprobe, damit es performant bleibt
    city_samples = rng.sample(cities, k=min(6, len(cities)))
    goods = list(ctx.content.goods.values())
    good_samples = rng.sample(goods, k=min(10, len(goods)))

    best = None
    best_score = 0.0

    for g in good_samples:
        for src in city_samples:
            for dst in city_samples:
                if src.id == dst.id:
                    continue

                src_market = ctx.markets.get(src.id)
                dst_market = ctx.markets.get(dst.id)
                if src_market is None or dst_market is None:
                    continue

                src_stock = float(src_market.stock.get(g.id, 0.0))
                if src_stock < 3.0:
                    continue

                # Need-Bewertungen pro Zielstadt steuern Zahlungsbereitschaft
                dst_ctype = _city_type(ctx, dst)
                if dst_ctype is None:
                    continue
                need = (dst_ctype.needs.get(g.category, "normal") or "normal").strip().lower()

                dst_target = _target_for(ctx, dst, g)
                dst_ps = float(dst_market.price_stock.get(g.id, dst_market.stock.get(g.id, 0.0)))
                dst_bid, _ = ctx.economy.compute_bid_ask(g.base_price, dst_ps, dst_target, need)

                # Ask in src hängt von src-Need ab (oder neutral)
                src_ctype = _city_type(ctx, src)
                if src_ctype is None:
                    continue
                src_need = (src_ctype.needs.get(g.category, "normal") or "normal").strip().lower()
                src_target = _target_for(ctx, src, g)
                src_ps = float(src_market.price_stock.get(g.id, src_market.stock.get(g.id, 0.0)))
                _, src_ask = ctx.economy.compute_bid_ask(g.base_price, src_ps, src_target, src_need)

                margin = dst_bid - src_ask
                if margin <= 0.0:
                    continue

                # dst sollte knapp sein (sonst kein Sinn)
                if dst_market.stock.get(g.id, 0.0) >= 0.9 * dst_target:
                    continue

                # qty begrenzen (nicht alles wegsaugen)
                qty = min(src_stock * rng.uniform(0.08, 0.22), max(4.0, dst_target * rng.uniform(0.05, 0.12)))
                qty = max(0.0, qty)

                eta = _travel_time_days(src, dst)

                score = margin * qty
                if score > best_score:
                    best_score = score
                    best = (src.id, dst.id, g.id, qty, eta)

    return best


def on_new_day(ctx) -> None:
    """
    NPC-Trade Tick pro Tag:
    1) Ankommende Shipments verarbeiten (ETA, Piraten/Sturm)
    2) Neue Arbitrage-Shipments erzeugen
    """
    if not getattr(ctx, "world", None) or not getattr(ctx, "markets", None):
        return

    day = int(getattr(ctx.clock, "day", 1))
    seed = (day * 2654435761) & 0xFFFFFFFF
    rng = random.Random(seed)

    _apply_shipments_arrival(ctx, rng)

    # Wie viele NPC-Deals pro Tag? skaliere mit Stadtanzahl.
    cities_n = len(ctx.world.cities)
    deals = max(1, min(8, int(round(cities_n * 0.65))))

    _ensure_ctx_state(ctx)

    for _ in range(deals):
        choice = _choose_arbitrage(ctx, rng)
        if not choice:
            continue
        src_id, dst_id, gid, qty, eta = choice

        src_market = ctx.markets.get(src_id)
        if src_market is None:
            continue

        have = float(src_market.stock.get(gid, 0.0))
        qty = min(qty, have)
        if qty < 1.0:
            continue

        # Ware im Ursprung “reservieren” (physisch raus aus dem Markt)
        src_market.stock[gid] = round(have - qty, 3)

        ctx.npc_shipments.append(Shipment(
            src_city_id=src_id,
            dst_city_id=dst_id,
            good_id=gid,
            qty=qty,
            eta_days=int(max(1, eta)),
            created_day=day,
        ))
