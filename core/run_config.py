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
    start_gold_base: int = 1000
    start_gold_bonus_mult: float = 1.0   # z.B. 1.15 = +15%
    start_gold_bonus_add: int = 0        # z.B. +200 Gold flat
    attack_bonus_flat: int = 0          # +2 => damage_min/max +2
    armor_physical_bonus: float = 0.0   # +5 => armor_physical +5
    armor_abyssal_bonus: float = 0.0    # +5 => armor_abyssal +5 (optional)

    trade_buy_mult: float = 1.0
    trade_sell_mult: float = 1.0

    #Startschiff
    start_ship_type_id: str = "sloop"

DIFFICULTY_PRESETS = [
    # (id, price_spread_mult, event_freq_mult, start_money_mult, start_gold_base)
    ("leicht",   0.9,  0.7,  1.0, 1200),
    ("normal",   1.0,  1.0,  1.0, 1000),
    ("schwer",   1.2,  1.3,  1.0,  850),
    ("legendär", 1.35, 1.6,  1.0,  700),
]
DEFAULT_DIFFICULTY_ID = "normal"
