# clock.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class GameClock:
    day: int = 1
    seconds_in_day: float = 0.0
    day_length_seconds: float = 600.0
    time_scale: float = 1.0
    paused: bool = False
    display_day_start_hour: int = 8

    def update(self, real_dt: float) -> int:
        """
        Returns number of day rollovers that happened (0..n).
        Wichtig für Skip/large dt: Markt muss pro Tag ticken.
        """
        if self.paused:
            return 0

        self.seconds_in_day += real_dt * self.time_scale

        days_advanced = 0
        while self.seconds_in_day >= self.day_length_seconds:
            self.seconds_in_day -= self.day_length_seconds
            self.day += 1
            days_advanced += 1

        return days_advanced

    def time_of_day_ratio(self) -> float:
        return max(0.0, min(1.0, self.seconds_in_day / self.day_length_seconds))

    def get_hhmm(self) -> str:
        ratio = self.time_of_day_ratio()
        total_minutes = int(round(ratio * 24 * 60))
        start_minutes = int(self.display_day_start_hour) * 60
        minutes = (start_minutes + total_minutes) % (24 * 60)
        hh = minutes // 60
        mm = minutes % 60
        return f"{hh:02d}:{mm:02d}"

    def force_next_day(self, start_hour: int | None = None) -> None:
        self.day += 1
        if start_hour is not None:
            self.display_day_start_hour = int(start_hour)
        self.seconds_in_day = 0.0
