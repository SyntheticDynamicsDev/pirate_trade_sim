# ui/video_background.py
from __future__ import annotations

import os
import glob
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

import pygame


@dataclass
class VideoBackground:
    """
    Spielt eine Frame-Sequenz (PNG/JPG/WebP) als 'Video' ab.
    - Kein echtes mp4 decoding zur Runtime
    - Sehr robust für PyGame/PyInstaller
    """
    frames_dir: str
    fps: int = 30
    loop: bool = True
    cover: bool = True                # True = cover (füllt Screen), False = contain
    cache_size: int = 24              # wie viele Frames als Surface im RAM gehalten werden

    _frame_paths: list[str] = None
    _t: float = 0.0
    _index: int = 0

    _cache: OrderedDict[int, pygame.Surface] = None
    _last_scaled_key: Optional[tuple[int, int, int]] = None
    _last_scaled_surf: Optional[pygame.Surface] = None

    def __post_init__(self) -> None:
        self._frame_paths = self._scan_frames(self.frames_dir)
        self._cache = OrderedDict()

    def _scan_frames(self, frames_dir: str) -> list[str]:
        exts = ("*.png", "*.jpg", "*.jpeg", "*.webp")
        paths: list[str] = []
        for pat in exts:
            paths.extend(glob.glob(os.path.join(frames_dir, pat)))
        paths.sort()
        return paths

    def has_frames(self) -> bool:
        return bool(self._frame_paths)

    def reset(self) -> None:
        self._t = 0.0
        self._index = 0
        self._last_scaled_key = None
        self._last_scaled_surf = None

    def update(self, dt: float) -> None:
        if not self._frame_paths:
            return

        self._t += float(dt)
        frame_time = 1.0 / max(1, int(self.fps))

        # Advance frames deterministisch (auch bei dt spikes)
        while self._t >= frame_time:
            self._t -= frame_time
            self._index += 1
            if self._index >= len(self._frame_paths):
                if self.loop:
                    self._index = 0
                else:
                    self._index = len(self._frame_paths) - 1

        # invalidate scaled cache (neuer frame)
        self._last_scaled_key = None
        self._last_scaled_surf = None

    def _load_frame(self, idx: int) -> Optional[pygame.Surface]:
        if not self._frame_paths:
            return None

        # clamp
        idx = max(0, min(idx, len(self._frame_paths) - 1))

        if idx in self._cache:
            surf = self._cache.pop(idx)
            self._cache[idx] = surf
            return surf

        path = self._frame_paths[idx]
        try:
            surf = pygame.image.load(path).convert_alpha()
        except Exception:
            return None

        self._cache[idx] = surf
        while len(self._cache) > max(1, int(self.cache_size)):
            self._cache.popitem(last=False)

        return surf

    def draw(self, screen: pygame.Surface) -> None:
        if not self._frame_paths:
            return

        src = self._load_frame(self._index)
        if src is None:
            return

        sw, sh = screen.get_size()
        iw, ih = src.get_size()

        if iw <= 0 or ih <= 0:
            return

        # scaled cache (pro frame + screen size)
        key = (self._index, sw, sh)
        if self._last_scaled_key == key and self._last_scaled_surf is not None:
            scaled = self._last_scaled_surf
        else:
            sx = sw / float(iw)
            sy = sh / float(ih)

            if self.cover:
                s = max(sx, sy)  # cover
            else:
                s = min(sx, sy)  # contain

            tw = max(1, int(iw * s))
            th = max(1, int(ih * s))
            scaled = pygame.transform.smoothscale(src, (tw, th)).convert_alpha()

            self._last_scaled_key = key
            self._last_scaled_surf = scaled

        # center blit
        x = (sw - scaled.get_width()) // 2
        y = (sh - scaled.get_height()) // 2
        screen.blit(scaled, (x, y))
