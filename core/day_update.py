from __future__ import annotations
import math
import random
from economy.npc_trade import on_new_day as npc_trade_on_new_day


def _need_weight(need: str) -> float:
    return {
        "critical": 1.75,
        "high": 1.35,
        "normal": 1.00,
        "low": 0.65,
        "irrelevant": 0.25,
    }.get(need, 1.0)

def _get_city_type(ctx, city):
    # Präziser Workflow: CityType kommt ausschließlich aus Content (cities.json)
    cdef = ctx.content.cities.get(city.id)
    if cdef is None:
        return None
    return ctx.content.city_types.get(cdef.city_type_id)

def _target_for(ctx, city, good) -> float:
    ctype = _get_city_type(ctx, city)
    if ctype is None:
        return float(good.target_stock)
    need = (ctype.needs.get(good.category, "normal") or "normal").strip().lower()
    mult = ctx.economy.NEED_TARGET_MULT.get(need, 1.0)
    return float(good.target_stock) * float(mult)

def _market_size_params(market_size: str) -> tuple[float, float, float]:
    """
    returns: (capacity_mult, prod_base, cons_base)
    """
    if market_size == "small":
        return (1.25, 0.08, 0.09)
    if market_size == "large":
        return (1.60, 0.12, 0.11)
    return (1.40, 0.10, 0.10)  # medium

def _production_bias(city_type_id: str, category: str) -> float:
    """
    Stadt-Spezialisierung. >1 produziert mehr, <1 produziert weniger.
    """
    if city_type_id == "farm_city":
        return {"food": 1.60, "raw": 1.05, "craft": 0.70, "sea": 0.55, "luxury": 0.70}.get(category, 1.0)
    if city_type_id == "mining_city":
        return {"raw": 1.70, "craft": 0.85, "food": 0.65, "sea": 0.55, "luxury": 0.55}.get(category, 1.0)
    if city_type_id == "harbor_city":
        return {"sea": 1.55, "craft": 1.25, "food": 0.95, "raw": 0.95, "luxury": 1.05}.get(category, 1.0)
    return 1.0

def on_new_day(ctx) -> None:
    """
    Neuer Markt-Tick:
    - Verderb
    - Produktion/Konsum (stochastisch, city-type abhängig)
    - Seltene Schocks -> echte Engpässe
    - price_stock folgt träge
    - top_needs aus echter Knappheit
    """

    if not getattr(ctx, "world", None) or not getattr(ctx, "markets", None):
        return

    day = getattr(ctx.clock, "day", 1)

    # Globale Event-Intensität (kannst du später an Schwierigkeitsgrad koppeln)
    global_shock_chance = 0.06   # 6% / Tag / Stadt
    global_shock_strength = (0.25, 0.55)  # 25–55% Verlust in betroffenen Kategorien

    price_stock_smooth = 0.18  # wie schnell price_stock dem stock folgt (träge, aber nicht zu träge)

    day = getattr(ctx.clock, "day", 1)
    for city in ctx.world.cities:
        market = ctx.markets.get(city.id)
        if market is None:
            continue

        ctype = _get_city_type(ctx, city)
        if ctype is None:
            continue

        ms = getattr(ctype, "market_size", "medium")
        cap_mult, prod_base, cons_base = _market_size_params(ms)

        # deterministischer RNG pro Stadt/Tag (damit Debug reproduzierbar ist)
        seed = (hash(city.id) ^ (day * 1000003)) & 0xFFFFFFFF
        rng = random.Random(seed)

        # --- NEU: persistenter Supply-Index pro Stadt+Kategorie (Random Walk) ---
        if not hasattr(ctx, "city_supply_idx"):
            ctx.city_supply_idx = {}  # (city_id, category) -> float

        def _supply_idx(city_id: str, cat: str) -> float:
            key = (city_id, cat)
            v = float(ctx.city_supply_idx.get(key, 1.0))
            # Random walk: kleine tägliche Drift, gelegentlich stärkere Sprünge
            v += rng.uniform(-0.06, 0.06)
            if rng.random() < 0.08:
                v += rng.uniform(-0.18, 0.18)
            v = max(0.55, min(1.55, v))
            ctx.city_supply_idx[key] = v
            return v
        city_type_id = getattr(ctype, "id", None) or getattr(city, "city_type", "unknown")

        # 1) Seltene, aber heftige Schocks (Ernteausfall, Blockade, Sturm)
        shock = (rng.random() < global_shock_chance)
        shock_cat = None
        shock_factor = 1.0
        if shock:
            # Food etwas wahrscheinlicher (Ernteausfall, Verderb, Blockade)
            shock_cat = rng.choices(
                ["food", "raw", "craft", "sea", "luxury"],
                weights=[2.2, 1.0, 1.0, 1.0, 0.8],
                k=1
            )[0]
            shock_factor = 1.0 - rng.uniform(*global_shock_strength)


        for g in ctx.content.goods.values():
            gid = g.id
            cat = g.category

            stock = float(market.stock.get(gid, 0.0))
            ps = float(market.price_stock.get(gid, stock))

            # 1) Verderb (bei dir per Good definiert)
            spoil = float(getattr(g, "spoil_rate_per_day", 0.0))
            if spoil > 0.0 and stock > 0.0:
                stock = max(0.0, stock * (1.0 - spoil))

            # 2) Kapazität (verhindert “alles immer riesig”)
            target = _target_for(ctx, city, g)
            capacity = max(2.0, target * cap_mult)

            # 3) Produktion (nimmt ab, wenn Lager voll)
            prod_bias = _production_bias(city_type_id, cat)
            prod_noise = rng.uniform(0.75, 1.25)

            # --- NEU: Food stärker von Supply-Schwankungen betroffen ---
            supply = _supply_idx(city.id, cat)
            if cat == "food":
                supply = (supply ** 1.35)  # verstärkt die Schwankung leicht

            prod = prod_base * prod_bias * prod_noise * supply * capacity * (1.0 - (stock / capacity))

            prod = max(0.0, prod)

            # 4) Konsum (stärker bei hoher Need-Stufe)
            need = (ctype.needs.get(cat, "normal") or "normal").strip().lower()
            need_w = _need_weight(need)

            cons_noise = rng.uniform(0.80, 1.30)
            # Konsum hängt auch davon ab, wie viel überhaupt da ist (keine negative Stocks)
            cons = cons_base * need_w * cons_noise * capacity
            cons = min(cons, stock + prod)  # kann nicht mehr verbrauchen als verfügbar (+ heutige Produktion)

            # 5) Apply shock (Engpässe)
            if shock and shock_cat == cat:
                # Schock wirkt auf vorhandenen Bestand nach Prod/Cons
                after = max(0.0, (stock + prod - cons))
                after *= shock_factor
                stock = after
            else:
                stock = max(0.0, stock + prod - cons)

            # 6) Hard clamp an capacity (Lagerlimit)
            stock = min(stock, capacity)

            # 7) price_stock träge nachziehen
            ps = ps + price_stock_smooth * (stock - ps)

            market.stock[gid] = round(stock, 3)
            market.price_stock[gid] = round(max(ps, 0.0), 3)
            
        _apply_external_flows(ctx, rng, city, market, ctype, city_type_id)    

    npc_trade_on_new_day(ctx)
    _update_top_needs(ctx)

def _update_top_needs(ctx) -> None:
    """
    Top-Needs aus echter Knappheit:
    Score = scarcity(target/price_stock) * Need-Gewichtung
    """
    for city in ctx.world.cities:
        market = ctx.markets.get(city.id)
        if market is None:
            continue

        ctype = _get_city_type(ctx, city)
        if ctype is None:
            market.top_needs = []
            continue

        scored = []
        for g in ctx.content.goods.values():
            need = (ctype.needs.get(g.category, "normal") or "normal").strip().lower()
            w = _need_weight(need)
            if w <= 0.0:
                continue

            target = _target_for(ctx, city, g)
            ps = float(market.price_stock.get(g.id, market.stock.get(g.id, 0.0)))
            ps = max(ps, 1.0)

            scarcity = target / ps  # >1 => knapp
            score = scarcity * w
            scored.append((score, g.id))

        scored.sort(reverse=True, key=lambda x: x[0])
        market.top_needs = [gid for _, gid in scored[:3]]

def _external_flow_params(city_type_id: str) -> tuple[float, float]:
    """
    returns (import_mult, export_mult)
    """
    # harbor: mehr Außenhandel
    if city_type_id == "harbor_city":
        return (1.25, 1.25)
    # farm/mining eher exportlastig
    if city_type_id == "farm_city":
        return (0.85, 1.20)
    if city_type_id == "mining_city":
        return (0.85, 1.25)
    return (1.00, 1.00)


def _category_external_bias(city_type_id: str, category: str) -> tuple[float, float]:
    """
    returns (import_bias, export_bias) pro Kategorie
    """
    if city_type_id == "farm_city":
        return ({
            "food": 0.45, "raw": 1.05, "craft": 1.20, "sea": 1.10, "luxury": 1.15
        }.get(category, 1.0),
        {
            "food": 1.55, "raw": 1.00, "craft": 0.70, "sea": 0.60, "luxury": 0.65
        }.get(category, 1.0))

    if city_type_id == "mining_city":
        return ({
            "food": 1.25, "raw": 0.50, "craft": 1.10, "sea": 1.10, "luxury": 1.20
        }.get(category, 1.0),
        {
            "food": 0.65, "raw": 1.70, "craft": 0.75, "sea": 0.60, "luxury": 0.60
        }.get(category, 1.0))

    if city_type_id == "harbor_city":
        return ({
            "food": 0.95, "raw": 0.95, "craft": 0.90, "sea": 0.70, "luxury": 0.85
        }.get(category, 1.0),
        {
            "food": 0.90, "raw": 0.90, "craft": 1.15, "sea": 1.35, "luxury": 1.10
        }.get(category, 1.0))

    return (1.0, 1.0)


def _apply_external_flows(ctx, rng: random.Random, city, market, ctype, city_type_id: str) -> None:
    """
    Exogene Quellen/Senken:
    - Import füllt NUR teilweise auf, ist volatil und kann “ausfallen”
    - Export zieht Überschüsse ab und verhindert “alles immer voll”
    """
    import_mult, export_mult = _external_flow_params(city_type_id)

    # Disruption: manchmal brechen Lieferungen/Exports ein (Blockade, Sturm, Krieg, Piraten)
    disruption = (rng.random() < 0.10)  # 10% / Tag / Stadt
    disruption_factor = 1.0
    if disruption:
        disruption_factor = rng.uniform(0.15, 0.55)

    for g in ctx.content.goods.values():
        gid = g.id
        cat = g.category

        target = _target_for(ctx, city, g)

        stock = float(market.stock.get(gid, 0.0))

        imp_bias, exp_bias = _category_external_bias(city_type_id, cat)

        # Import: nur wenn deutlich unter Ziel
        # Baseline-Importkapazität als Anteil vom target (klein!)
        import_cap = (0.06 * target) * import_mult * imp_bias
        # Volatilität
        import_cap *= rng.uniform(0.55, 1.55)
        # Disruption reduziert Import/Export
        import_cap *= disruption_factor

        if stock < 0.70 * target and import_cap > 0:
            # fülle nur ein Stück, keine “Magie-Volllager”
            need = (ctype.needs.get(cat, "normal") or "normal").strip().lower()
            w = _need_weight(need)
            qty = import_cap * (0.6 + 0.5 * w)  # critical bekommt etwas mehr, aber capped
            qty = min(qty, max(0.0, (0.90 * target) - stock))
            if qty > 0:
                market.stock[gid] = round(stock + qty, 3)
                stock = float(market.stock[gid])

        # Export: wenn deutlich über Ziel
        export_cap = (0.07 * target) * export_mult * exp_bias
        export_cap *= rng.uniform(0.55, 1.55)
        export_cap *= disruption_factor

        if stock > 1.10 * target and export_cap > 0:
            qty = min(export_cap, stock - 1.05 * target)
            if qty > 0:
                market.stock[gid] = round(stock - qty, 3)
                stock = float(market.stock[gid])
