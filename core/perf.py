from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Dict, Iterator, Optional

import pygame


class PerfMonitor:
    def __init__(self) -> None:
        self.enabled = False
        self._font: Optional[pygame.font.Font] = None
        self._frame_start = 0.0
        self._real_dt = 0.0
        self._state_name = ""
        self._last_ms: Dict[str, float] = {}
        self._avg_ms: Dict[str, float] = {}
        self._alpha = 0.12

    def toggle(self) -> None:
        self.enabled = not self.enabled

    def begin_frame(self, real_dt: float) -> None:
        self._frame_start = perf_counter()
        self._real_dt = max(0.000001, float(real_dt))
        if not self.enabled:
            return
        self._last_ms = {}

    def finish_frame(self, state_name: str, notes: Optional[Dict[str, str]] = None) -> None:
        if not self.enabled:
            return
        self._state_name = state_name
        self._notes = notes or {}
        self.record("frame.total", (perf_counter() - self._frame_start) * 1000.0)

    def record(self, name: str, ms: float) -> None:
        if not self.enabled:
            return
        ms = float(ms)
        self._last_ms[name] = self._last_ms.get(name, 0.0) + ms
        old = self._avg_ms.get(name)
        if old is None:
            self._avg_ms[name] = ms
        else:
            self._avg_ms[name] = old + (ms - old) * self._alpha

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        start = perf_counter()
        try:
            yield
        finally:
            self.record(name, (perf_counter() - start) * 1000.0)

    def draw(self, screen: pygame.Surface) -> None:
        if not self.enabled:
            return
        if self._font is None:
            self._font = pygame.font.Font(None, 20)

        fps = 1.0 / self._real_dt
        lines = [
            "PERF DEBUG (F3)",
            f"FPS: {fps:5.1f}",
            f"State: {self._state_name}",
        ]

        for name in sorted(getattr(self, "_notes", {})):
            lines.append(f"{name}: {self._notes[name]}")

        for name in sorted(self._avg_ms):
            avg = self._avg_ms.get(name, 0.0)
            last = self._last_ms.get(name, 0.0)
            lines.append(f"{name}: {last:6.2f} ms  avg {avg:6.2f}")

        pad = 8
        rendered = [self._font.render(line, True, (235, 245, 255)) for line in lines]
        width = max(s.get_width() for s in rendered) + pad * 2
        height = sum(s.get_height() for s in rendered) + pad * 2 + (len(rendered) - 1) * 2

        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 175))
        pygame.draw.rect(panel, (120, 190, 255, 180), panel.get_rect(), 1)

        y = pad
        for surf in rendered:
            panel.blit(surf, (pad, y))
            y += surf.get_height() + 2

        screen.blit(panel, (10, 10))
