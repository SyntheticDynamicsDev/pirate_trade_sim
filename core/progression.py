# core/progression.py
from __future__ import annotations

MAX_LEVEL = 10

def xp_need_for_level(level: int) -> int:
    """
    XP needed to go from `level` -> `level+1`.
    level starts at 1.
    """
    level = max(1, int(level))
    # Increasing curve (noticeably more per level)
    # L1->2: 100, L2->3: 200, ... L9->10: 2300
    k = (level - 1)
    return int(100 + k * 75 + (k * k) * 25)

def total_xp_cap() -> int:
    # total XP required to reach MAX_LEVEL
    total = 0
    for lvl in range(1, MAX_LEVEL):
        total += xp_need_for_level(lvl)
    return total

def cap_xp(total_xp: int) -> int:
    return max(0, min(int(total_xp), total_xp_cap()))

def xp_to_level(total_xp: int) -> tuple[int, int, int]:
    """
    Returns (level, cur_xp_in_level, need_xp_for_next)
    If level == MAX_LEVEL -> cur==need and bar is full.
    """
    xp = cap_xp(total_xp)

    level = 1
    while level < MAX_LEVEL:
        need = xp_need_for_level(level)
        if xp < need:
            return level, xp, need
        xp -= need
        level += 1

    # MAX level
    need = xp_need_for_level(MAX_LEVEL - 1)  # only for display consistency
    return MAX_LEVEL, need, need

def add_xp(player, amount: int) -> None:
    """
    Mutates player.xp with cap.
    """
    cur = int(getattr(player, "xp", 0))
    setattr(player, "xp", cap_xp(cur + int(amount)))
