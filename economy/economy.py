from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

@dataclass
class EconomyEngine:
     
    """
    MVP-Preisformel:
    - Referenzpreis = base_price * f(stock vs target)
    - Bid/Ask = Referenzpreis * Faktoren nach Need-Stufe (Category-basiert)
    """
    # Need-Stufe -> Multiplikatoren
    BID_BY_NEED = {
        "critical": 0.95,
        "high": 0.85,
        "normal": 0.75,
        "low": 0.35,
        "irrelevant": 0.10,
    }

    ASK_BY_NEED = {
        "critical": 1.20,
        "high": 1.15,
        "normal": 1.10,
        "low": 1.50,
        "irrelevant": 3.50,
    }
    
    NEED_TARGET_MULT = {
        "critical": 1.8,
        "high": 1.3,
        "normal": 1.0,
        "low": 0.4,
        "irrelevant": 0.1,
    }

    def compute_reference_price(self, base_price: float, stock: float, target: float) -> float:
        # Verhältnis (target/stock) -> Preis hoch bei Knappheit, niedrig bei Überfluss
        s = max(stock, 1.0)
        t = max(target, 1.0)
        ratio = t / s

        # steiler als sqrt, aber noch stabil
        mult = ratio ** 0.85

        # etwas mehr Spielraum, damit Engpässe auch "wehtun"
        mult = clamp(mult, 0.40, 3.50)

        return base_price * mult


    def compute_bid_ask(self, base_price: float, stock: float, target: float, need: str) -> Tuple[float, float]:
        ref = self.compute_reference_price(base_price, stock, target)

        bid = ref * self.BID_BY_NEED.get(need, 0.75)
        ask = ref * self.ASK_BY_NEED.get(need, 1.10)

        # Bid darf nie höher als Ask sein
        if bid > ask:
            bid = ask * 0.95

        return bid, ask
