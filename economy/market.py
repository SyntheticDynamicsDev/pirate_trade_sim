from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random

@dataclass
class CityMarketState:
    city_id: str
    stock: Dict[str, float] = field(default_factory=dict)       # physischer Bestand
    price_stock: Dict[str, float] = field(default_factory=dict) # träge Preisgrundlage (Mechanik 2)
    pending: Dict[str, float] = field(default_factory=dict)     # optional später (nicht zwingend)
    top_needs: List[str] = field(default_factory=list)          # für Weltkarte (Symbols)

# (dein CityMarketState bleibt wie er ist)

def _city_type(ctx, city_id: str):
    cdef = ctx.content.cities.get(city_id)
    if cdef is None:
        return None
    return ctx.content.city_types.get(cdef.city_type_id)

def _target_for(ctx, city_id: str, good) -> float:
    ctype = _city_type(ctx, city_id)
    if ctype is None:
        return float(getattr(good, "target_stock", 0.0))
    need = (ctype.needs.get(good.category, "normal") or "normal").strip().lower()
    mult = float(ctx.economy.NEED_TARGET_MULT.get(need, 1.0))
    return float(good.target_stock) * mult

def generate_city_market(
    ctx,
    city_id: str,
    rng: random.Random,
    *,
    juicy_frac: float = 0.10,
    missing_frac_min: float = 0.10,
    missing_frac_max: float = 0.30,
) -> "CityMarketState":
    """
    Erzeugt Market-Stock so, dass:
    - ~10% goods sind "juicy" (starkes Over-/Undersupply)
    - 10..30% goods fehlen komplett
    - Rest liegt nahe target (handelsneutral)
    """
    goods = list(ctx.content.goods.values())
    n = len(goods)
    if n == 0:
        return CityMarketState(city_id=city_id)

    missing_n = int(round(n * rng.uniform(missing_frac_min, missing_frac_max)))
    juicy_n   = int(round(n * juicy_frac))

    missing_n = max(0, min(n, missing_n))
    juicy_n   = max(0, min(n - missing_n, juicy_n))

    ids = [g.id for g in goods]
    rng.shuffle(ids)

    missing_set = set(ids[:missing_n])
    remaining = ids[missing_n:]
    juicy_set = set(remaining[:juicy_n])
    # rest = remaining[juicy_n:]

    m = CityMarketState(city_id=city_id)

    for g in goods:
        gid = g.id
        tgt = max(1.0, float(_target_for(ctx, city_id, g)))

        if gid in missing_set:
            stock = 0.0
            ps = 0.0

        elif gid in juicy_set:
            # Hälfte "Surplus", Hälfte "Shortage"
            if rng.random() < 0.5:
                # Surplus: sehr billig -> gute BUY-Quelle
                stock = tgt * rng.uniform(1.6, 2.6)
            else:
                # Shortage: sehr teuer -> gute SELL-Destination
                stock = tgt * rng.uniform(0.08, 0.35)

            # price_stock initial leicht träge/realistisch
            ps = stock * rng.uniform(0.85, 1.15)

        else:
            # Normal: um Target herum, wenig Handelsvorteil
            stock = tgt * rng.uniform(0.75, 1.25)
            ps = stock * rng.uniform(0.92, 1.08)

        m.stock[gid] = round(float(stock), 3)
        m.price_stock[gid] = round(max(0.0, float(ps)), 3)

    return m

def generate_all_markets(ctx, *, seed: Optional[int] = None) -> Dict[str, "CityMarketState"]:
    """
    Baut ctx.markets komplett neu (New Game oder Hard Reset).
    """
    if seed is None:
        # stabil pro Spielstand: wenn du ctx.seed hast, nimm den
        seed = int(getattr(ctx, "seed", 1337))
    rng = random.Random(seed)

    out: Dict[str, CityMarketState] = {}
    for city in ctx.world.cities:
        out[city.id] = generate_city_market(ctx, city.id, rng)
    return out