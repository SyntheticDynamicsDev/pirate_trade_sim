from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import os
import pygame

@dataclass
class LoseState:
    game = None
    ctx = None

    snapshot: Optional[pygame.Surface] = None

    # Timings
    fade_to_black: float = 0.90     # Dauer bis komplett schwarz
    sign_fade_in: float = 1.20      # Dauer Schild einblenden

    def on_enter(self) -> None:
        self._t = 0.0

        # Fallback snapshot (ctx hat kein screen-Attribut)
        if self.snapshot is None:
            # sichere Defaultgröße; wird in render() auf echte Screengröße gescaled
            w, h = 1280, 720
            self.snapshot = pygame.Surface((w, h))
            self.snapshot.fill((10, 12, 18))


        # Sign laden
        self._sign = None
        self._sign_path = os.path.join("assets", "ui", "sign_lose.png")
        if os.path.exists(self._sign_path):
            try:
                self._sign = pygame.image.load(self._sign_path).convert_alpha()
            except Exception:
                self._sign = None
        # Menü-Schild laden
        self._menu_sign = None
        self._menu_sign_path = os.path.join("assets", "ui", "sign_menu.png")
        if os.path.exists(self._menu_sign_path):
            try:
                self._menu_sign = pygame.image.load(self._menu_sign_path).convert_alpha()
            except Exception:
                self._menu_sign = None

        # --- Lose Musik (robust) ---
        lose_candidates = [
            os.path.join("assets", "audio", "lose.mp3"),
            os.path.join("assets", "music", "lose.mp3"),
        ]

        lose_path = None
        for p in lose_candidates:
            if os.path.exists(p):
                lose_path = p
                break

        if lose_path is None:
            print("[LoseState] lose.mp3 nicht gefunden. Erwartet in assets/audio/ oder assets/music/")
        else:
            try:
                # Force: aktuelle Musik sofort stoppen, dann lose track starten
                self.ctx.audio.stop_music(fade_ms=0)
                self.ctx.audio.play_playlist([lose_path], shuffle=False, fade_ms=0)
            except Exception as e:
                print(f"[LoseState] Musik konnte nicht gestartet werden: {e}")

        # Menü-Schild Timing
        self._menu_delay = 5.0      # Sekunden bis es überhaupt erscheint
        self._menu_fade = 0.35      # schnelle Fade-In Dauer
        self._menu_rect = None
        self._menu_clickable = False

        # Font für evtl. Text
        self._font = pygame.font.SysFont("arial", 22)

    def on_exit(self) -> None:
        # Optional: wenn du beim Rückweg ins Menü wieder Menü-Musik willst,
        # übernimmt das Menü-State meist selbst. Ansonsten könntest du hier pop_music() machen.
        pass

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if getattr(self, "_menu_clickable", False) and self._menu_rect and self._menu_rect.collidepoint(event.pos):
                self._go_to_menu()
            return


        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
            self._go_to_menu()


    def _go_to_menu(self) -> None:
        from states.menu import MainMenuState
        self.game.replace(MainMenuState())

    def update(self, dt: float) -> None:
        self._t += float(dt)

    def render(self, screen: pygame.Surface) -> None:
        W, H = screen.get_size()

        # Snapshot als Basis
        snap = self.snapshot
        if snap.get_width() != W or snap.get_height() != H:
            snap = pygame.transform.smoothscale(snap, (W, H))
        screen.blit(snap, (0, 0))

        # Phase 1: Fade to black (0..1)
        t_black = min(1.0, self._t / max(0.001, self.fade_to_black))
        black_alpha = int(255 * t_black)

        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, black_alpha))
        screen.blit(veil, (0, 0))

        # Phase 2: Sign fade-in, beginnt erst wenn schwarz fast voll ist
        if self._sign is not None:
            start = self.fade_to_black * 0.85
            if self._t >= start:
                tt = (self._t - start) / max(0.001, self.sign_fade_in)
                tt = max(0.0, min(1.0, tt))
                a = int(255 * tt)

                # Schild skalieren: ~40% der Screenbreite (anpassbar)
                target_w = int(W * 0.46)
                scale = target_w / float(self._sign.get_width())
                target_h = max(1, int(self._sign.get_height() * scale))

                sign = pygame.transform.smoothscale(self._sign, (target_w, target_h))
                sign.set_alpha(a)

                rect = sign.get_rect(center=(W // 2, int(H * 0.42)))
                screen.blit(sign, rect.topleft)

        # --- Menü-Schild: erst nach Delay sichtbar + klickbar ---
        self._menu_rect = None
        self._menu_clickable = False

        if self._menu_sign is not None:
            # Startzeit: erst nach 5 Sekunden
            start = float(getattr(self, "_menu_delay", 5.0))
            fade = float(getattr(self, "_menu_fade", 0.35))

            if self._t >= start:
                tt = (self._t - start) / max(0.001, fade)
                tt = max(0.0, min(1.0, tt))
                a = int(255 * tt)

                target_w = int(W * 0.30)
                scale = target_w / float(self._menu_sign.get_width())
                target_h = max(1, int(self._menu_sign.get_height() * scale))

                sign = pygame.transform.smoothscale(self._menu_sign, (target_w, target_h))
                sign.set_alpha(a)

                rect = sign.get_rect(center=(W // 2, int(H * 0.65)))
                screen.blit(sign, rect.topleft)

                # erst ab sichtbar klickbar (du kannst hier tt>0.2 setzen, wenn du willst)
                self._menu_rect = rect
                self._menu_clickable = True

