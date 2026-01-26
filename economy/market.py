from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class CityMarketState:
    city_id: str
    stock: Dict[str, float] = field(default_factory=dict)       # physischer Bestand
    price_stock: Dict[str, float] = field(default_factory=dict) # träge Preisgrundlage (Mechanik 2)
    pending: Dict[str, float] = field(default_factory=dict)     # optional später (nicht zwingend)
    top_needs: List[str] = field(default_factory=list)          # für Weltkarte (Symbols)
