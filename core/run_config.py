from dataclasses import dataclass

@dataclass
class RunConfig:
    difficulty_id: str = "normal"
    character_id: str = "char_01"

    # globale Multiplikatoren
    price_spread_mult: float = 1.0        # beeinflusst Bid/Ask-Spread bzw. Markt-“Härte”
    event_freq_mult: float = 1.0          # Naturereignisse häufiger/seltener
    start_money_mult: float = 1.0         # Startkapital

    # Charakter-Perks (Beispiele)
    food_buy_discount: float = 0.0        # z.B. 0.10 = 10% günstiger einkaufen (Lebensmittel)
    weapon_buy_discount: float = 0.0

    #Startschiff
    start_ship_type_id: str = "sloop"

DIFFICULTY_PRESETS = [
    # (id, price_spread_mult, event_freq_mult, start_money_mult, start_gold_base)
    ("leicht",   0.9,  0.7,  1.3, 1200),
    ("normal",   1.0,  1.0,  1.0, 1000),
    ("schwer",   1.2,  1.3,  0.8,  850),
    ("legendär", 1.35, 1.6,  0.6,  700),
]
DEFAULT_DIFFICULTY_ID = "normal"
