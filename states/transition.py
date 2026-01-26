from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import os
import math
import pygame

from settings import SCREEN_W, SCREEN_H


def _ease_in_out(t: float) -> float:
    # smoothstep
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass
class TransitionState:
    game = None
    ctx = None

    kind: str = "to_combat"  # "to_combat" | "to_world" (world kommt als nächstes)
    snapshot: Optional[pygame.Surface] = None
    focus: Optional[Tuple[float, float]] = None  # screen space focus (ship pos)
    enemy_id: Optional[str] = None

    # tuning
    duration: float = 2.20
    zoom_to: float = 2.50
    blackout_in_start: float = 0.72  # ab hier beginnt die Verdunkelung
    blackout_full_at: float = 0.88   # ab hier ist es (nahezu) schwarz

    # wave overlay (optional asset)
    wave_path: str = os.path.join("assets", "ui", "wave_edge.png")

    def on_enter(self) -> None:
        self._t = 0.0

        # focus default = screen center
        if self.focus is None:
            self.focus = (SCREEN_W * 0.5, SCREEN_H * 0.5)

        # If no snapshot passed, make a safe empty one
        if self.snapshot is None:
            self.snapshot = pygame.Surface((SCREEN_W, SCREEN_H))
            self.snapshot.fill((10, 12, 18))

        # load wave texture (optional)
        self._wave = None
        try:
            # Debug: absolute existence check
            if os.path.exists(self.wave_path):
                img = pygame.image.load(self.wave_path).convert_alpha()

                # Normalize thickness (so intrude math is deterministic)
                # Target thickness in pixels (edge "depth")
                self._wave_thickness = 160

                # scale so height == thickness (top/bottom usage)
                w = img.get_width()
                h = img.get_height()
                if h != self._wave_thickness:
                    new_w = max(1, int(w * (self._wave_thickness / float(h))))
                    img = pygame.transform.smoothscale(img, (new_w, self._wave_thickness))

                self._wave = img
            else:
                self._wave_thickness = 160
                self._wave = None
        except Exception:
            self._wave_thickness = 160
            self._wave = None

        # Time-Scale sichern und während Transition einfrieren
        self._prev_time_scale = getattr(self.ctx.clock, "time_scale", None)
        try:
            self.ctx.clock.time_scale = 0.0
        except Exception:
            pass

                # Sicherheitsmaßnahme: Encounter-Wellenloop im Übergang ausblenden
        try:
            self.ctx.audio.stop_loop_sfx("enc_waves_level", fade_ms=250)
        except Exception:
            pass

    def on_exit(self) -> None:
        try:
            # Clip sicher zurücksetzen, damit der nächste State normal rendert
            if hasattr(self.ctx, "screen") and self.ctx.screen:
                self.ctx.screen.set_clip(None)
        except Exception:
            pass

        try:
            prev = getattr(self, "_prev_time_scale", None)
            if prev is not None:
                self.ctx.clock.time_scale = prev
        except Exception:
            pass


    def handle_event(self, event: pygame.event.Event) -> None:
        # block input during transition
        pass


    def update(self, dt: float) -> None:
        self._t += dt
        if self._t >= self.duration:
            self._finish()


    def _finish(self) -> None:
        self.ctx.transition_reveal = {
            "t": 0.0,
            "duration": 0.85,
            "wave_path": self.wave_path,
        }

        if self.kind == "to_combat":
            from states.combat import CombatState
            self.game.replace(CombatState(enemy_id=self.enemy_id))

        elif self.kind == "to_lose":
            from states.lose import LoseState
            self.game.replace(LoseState(snapshot=self.snapshot))

        else:
            from states.world import WorldMapState
            self.game.replace(WorldMapState())



    def render(self, screen: pygame.Surface) -> None:
        W, H = screen.get_size()
        snap = self.snapshot
        # Wichtig: Clip darf nie "leaken", sonst bleiben Render-Reste stehen
        screen.set_clip(None)

        # progress 0..1
        p = max(0.0, min(1.0, self._t / max(0.001, self.duration)))
        pe = _ease_in_out(p)

        # zoom factor
        z = 1.0 + (self.zoom_to - 1.0) * pe

        # draw zoomed snapshot around focus
        fx, fy = self.focus
        # scale snapshot
        sw = max(1, int(W * z))
        sh = max(1, int(H * z))
        scaled = pygame.transform.smoothscale(snap, (sw, sh))

        # center focus point: keep (fx,fy) in place
        # compute offset: place scaled such that focus remains stable
        # focus maps proportionally: (fx/W, fy/H) inside image
        u = fx / float(W)
        v = fy / float(H)
        ox = int(fx - u * sw)
        oy = int(fy - v * sh)

        screen.blit(scaled, (ox, oy))

        # wave edges moving inward
        self._draw_wave_edges(screen, pe)

        # darken to black
        black_alpha = 0
        if p >= self.blackout_in_start:
            # 0..1 between start and full
            t2 = (p - self.blackout_in_start) / max(0.001, (self.blackout_full_at - self.blackout_in_start))
            t2 = max(0.0, min(1.0, t2))
            black_alpha = int(255 * _ease_in_out(t2))

        if black_alpha > 0:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((0, 0, 0, black_alpha))
            screen.blit(veil, (0, 0))

        # Debug hint (remove later)
        if getattr(self, "_wave", None) is None:
            txt = pygame.font.SysFont("arial", 18).render("wave_edge.png NOT loaded", True, (255, 120, 120))
            screen.blit(txt, (12, 12))

    def _draw_wave_edges(self, screen: pygame.Surface, pe: float) -> None:
        W, H = screen.get_size()
        t_global = float(getattr(self, "_t", 0.0))

        def ease(t: float) -> float:
            t = max(0.0, min(1.0, t))
            return t * t * (3.0 - 2.0 * t)

        # Mehr "Wellen": 6 Layer statt 4 (mehr Volumen/Tiefe)
        # (start, end, scale, alpha_mult, depth_mult)
        layers = [
            (0.00, 0.55, 1.40, 0.25, 0.40),

            (0.10, 0.74, 1.62, 0.50, 0.72),

            (0.18, 0.93, 1.9, 0.82, 1.12),
            # Ultimative Flut-Welle

            (0.22, 1.00, 2.25, 1.00, 1.55),
        ]

        # Flood-Dicke: große Eindringtiefe, aber gecappt damit Mitte minimal frei bleibt
        base_thickness = int(getattr(self, "_wave_thickness", 160) * 3.4)
        cap = int(W * 0.73)  # fast bis zur Mitte

        # Fallback (falls Textur fehlt): linke/rechte Rect-Layer
        if getattr(self, "_wave", None) is None:
            for (t0, t1, _sc, a_mul, d_mul) in layers:
                if pe <= t0:
                    continue

                lt_base = ease((pe - t0) / max(0.001, (t1 - t0)))
                lt_left = max(0.0, min(1.0, lt_base + 0.10))
                lt_right = max(0.0, min(1.0, lt_base - 0.02))


                intrude_l = min(int(base_thickness * d_mul * lt_left), cap)
                intrude_r = min(int(base_thickness * d_mul * lt_right), cap)
                if intrude_l <= 0 and intrude_r <= 0:
                    continue

                alpha_l = max(0, min(255, int(220 * a_mul * lt_left)))
                alpha_r = max(0, min(255, int(220 * a_mul * lt_right)))

                s = pygame.Surface((W, H), pygame.SRCALPHA)
                if intrude_l > 0:
                    pygame.draw.rect(s, (0, 0, 0, alpha_l), pygame.Rect(0, 0, intrude_l, H))
                if intrude_r > 0:
                    pygame.draw.rect(s, (0, 0, 0, alpha_r), pygame.Rect(W - intrude_r, 0, intrude_r, H))
                screen.blit(s, (0, 0))
            return

        wave_src = self._wave

        for (t0, t1, sc, a_mul, d_mul) in layers:
            # --- immer initialisieren ---
            intrude_l = 0
            intrude_r = 0

            if pe <= t0:
                continue

            lt_base = ease((pe - t0) / max(0.001, (t1 - t0)))

            # Asymmetrie
            lt_left = max(0.0, min(1.0, lt_base + 0.10))
            lt_right = max(0.0, min(1.0, lt_base - 0.04))

            intrude_l = min(int(base_thickness * d_mul * lt_left), cap)
            intrude_r = min(int(base_thickness * d_mul * lt_right), cap)

            if intrude_l <= 0 and intrude_r <= 0:
                continue

            alpha_l = int(255 * a_mul * lt_left)
            alpha_r = int(255 * a_mul * lt_right)

            # Shake / Drift
            shake_x_l = int(math.sin(t_global * 18.0 + sc * 2.3) * 6)
            shake_x_r = int(math.sin(t_global * 16.0 + sc * 1.7) * 6)
            drift_y = int(math.sin(t_global * 5.0 + sc * 1.1) * 10)

            # Skalierung (groß!)
            src_w, src_h = wave_src.get_size()
            lw = int(src_w * sc)
            lh = max(220, int(src_h * sc))   # Mindesthöhe!

            base = pygame.transform.smoothscale(wave_src, (lw, lh))

            wave_l = base.copy()
            wave_l.set_alpha(alpha_l)

            wave_r = pygame.transform.flip(base, True, False)
            wave_r.set_alpha(alpha_r)

            # =========================
            # LEFT (Clip, wenige Tiles)
            # =========================
            if intrude_l > 0:
                clip = pygame.Rect(0, 0, intrude_l, H)
                prev_clip = screen.get_clip()
                screen.set_clip(clip)
                try:
                    tiles = 3
                    gap = int(lh * 0.9)
                    y0 = -int((t_global * 120) % gap) + drift_y

                    x = intrude_l - lw + shake_x_l
                    for i in range(tiles):
                        screen.blit(wave_l, (x, y0 + i * gap))
                finally:
                    screen.set_clip(prev_clip)


            # ==========================
            # RIGHT (Clip, wenige Tiles)
            # ==========================
            if intrude_r > 0:
                clip = pygame.Rect(W - intrude_r, 0, intrude_r, H)
                prev_clip = screen.get_clip()
                screen.set_clip(clip)
                try:
                    tiles = 3
                    gap = int(lh * 0.9)
                    y0 = -int((t_global * 120) % gap) + drift_y

                    x = (W - intrude_r) - shake_x_r
                    for i in range(tiles):
                        screen.blit(wave_r, (x, y0 + i * gap))
                finally:
                    screen.set_clip(prev_clip)
