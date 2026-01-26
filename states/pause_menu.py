from __future__ import annotations
import os
import pygame

import os
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any

import pygame


@dataclass
class PauseMenuState:
    game: Any = None
    ctx: Any = None
    font: Optional[pygame.font.Font] = None
    small: Optional[pygame.font.Font] = None

    _prev_paused: bool = False
    _buttons: List[Tuple[str, pygame.Rect]] = None
    selected_index: int = 0

    def on_enter(self) -> None:
        if self.font is None:
            self.font = pygame.font.SysFont("arial", 44)
        if self.small is None:
            self.small = pygame.font.SysFont("arial", 30)

        # Spielzeit pausieren (merken + setzen)
        clock = getattr(self.ctx, "clock", None)
        self._prev_paused = bool(getattr(clock, "paused", False)) if clock is not None else False
        if clock is not None:
            clock.paused = True

        self.labels = [
            "back",
            "sign_load",
            "sign_save",
            "sign_options",
            "sign_menu",
            "sign_quit",
        ]

        # Bild-Schilder laden (falls vorhanden)
        self._raw_signs = {}
        ui_dir = os.path.join("assets", "ui")
        for label in self.labels:
            fn = self._slug(label) + ".png"
            path = os.path.join(ui_dir, fn)
            if os.path.exists(path):
                img = pygame.image.load(path).convert_alpha()
                img = self._crop_to_alpha(img, min_alpha=10)
                self._raw_signs[label] = img

        self._scaled_signs = {}
        self._button_rects = {}
        self.item_hitboxes = []  # [(idx, rect)]
        self.selected_index = 0

        self._load_preview_img = None
        self._load_preview_meta = None
        self._load_preview_mtime = None



    def on_exit(self) -> None:
        # Pause-Zustand wiederherstellen
        clock = getattr(self.ctx, "clock", None)
        if clock is not None:
            clock.paused = self._prev_paused

    def _build_layout(self, sw: int, sh: int) -> None:
        # Button-Schildbreite (ähnlich wie MainMenu, aber etwas kompakter)
        target_w = int(max(240, min(420, sw * 0.26)))
        vertical_spacing = int(max(8, min(16, sh * 0.014)))

        # Schilder skalieren
        self._scaled_signs = {}
        for label in self.labels:
            surf = self._raw_signs.get(label)
            if surf is None:
                continue
            iw, ih = surf.get_size()
            scale = target_w / float(iw)
            new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
            self._scaled_signs[label] = pygame.transform.smoothscale(surf, new_size).convert_alpha()

        # Höhe bestimmen (Bild falls vorhanden, sonst Text-Fallback)
        heights = []
        for label in self.labels:
            if label in self._scaled_signs:
                heights.append(self._scaled_signs[label].get_height())
            else:
                heights.append(56)  # fallback height

        total_h = sum(heights) + vertical_spacing * (len(self.labels) - 1)
        start_y = sh // 2 - total_h // 2

        self._button_rects = {}
        self.item_hitboxes = []

        y = start_y
        for i, label in enumerate(self.labels):
            if label in self._scaled_signs:
                sign = self._scaled_signs[label]
                rect = sign.get_rect()
                rect.centerx = sw // 2
                rect.top = y
            else:
                # fallback: Textbutton rect
                rect = pygame.Rect(0, 0, int(min(520, max(320, sw * 0.34))), 56)
                rect.centerx = sw // 2
                rect.top = y

            self._button_rects[label] = rect
            self.item_hitboxes.append((i, rect))
            y += rect.height + vertical_spacing


    def handle_event(self, event) -> None:
        # Sicherstellen, dass Layout existiert (wichtig, falls ein Klick kommt bevor render() lief)
        if not getattr(self, "item_hitboxes", None):
            # wir brauchen screen size -> nutze game screen, falls vorhanden
            sw, sh = self.game.screen.get_size()
            self._build_layout(sw, sh)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.game.pop()
                return

            if event.key in (pygame.K_UP, pygame.K_w):
                self.selected_index = max(0, self.selected_index - 1)
                return

            if event.key in (pygame.K_DOWN, pygame.K_s):
                self.selected_index = min(len(self.labels) - 1, self.selected_index + 1)
                return

            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._activate(self.labels[self.selected_index])
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for i, rect in self.item_hitboxes:
                if rect.collidepoint(mx, my):
                    self.selected_index = i
                    self._activate(self.labels[i])
                    return


    def _activate(self, label: str) -> None:
        # Nur Zurück ist in diesem Schritt funktional
        if label == "Zurück":
            self.game.pop()
            return

        # Platzhalter für spätere Steps:
        # Spiel laden / speichern / Optionen / Hauptmenü / Beenden

    def update(self, dt: float) -> None:
        pass

    def _refresh_load_preview_cache(self) -> None:
        import os, pygame
        from core.save_system import DEFAULT_SAVE_PATH, PREVIEW_PATH, load_save_metadata

        mtime_json = os.path.getmtime(DEFAULT_SAVE_PATH) if os.path.exists(DEFAULT_SAVE_PATH) else None
        mtime_png = os.path.getmtime(PREVIEW_PATH) if os.path.exists(PREVIEW_PATH) else None
        mtime = (mtime_json, mtime_png)

        if self._load_preview_mtime == mtime:
            return

        self._load_preview_mtime = mtime
        self._load_preview_meta = load_save_metadata(DEFAULT_SAVE_PATH)

        if os.path.exists(PREVIEW_PATH):
            try:
                self._load_preview_img = pygame.image.load(PREVIEW_PATH).convert_alpha()
            except Exception:
                self._load_preview_img = None
        else:
            self._load_preview_img = None


    def _draw_load_preview(self, screen: pygame.Surface, anchor_rect: pygame.Rect) -> None:
        import pygame
        self._refresh_load_preview_cache()

        meta = self._load_preview_meta
        img = self._load_preview_img
        if meta is None and img is None:
            return

        sw, sh = screen.get_size()

        panel_w = int(min(520, max(360, sw * 0.30)))
        panel_h = int(min(340, max(260, sh * 0.30)))

        x = anchor_rect.right + 18
        if x + panel_w > sw - 10:
            x = anchor_rect.left - panel_w - 18
        y = max(10, min(sh - panel_h - 10, anchor_rect.centery - panel_h // 2))

        panel = pygame.Rect(x, y, panel_w, panel_h)

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 170))
        screen.blit(bg, panel.topleft)
        pygame.draw.rect(screen, (255, 255, 255), panel, width=1, border_radius=10)

        pad = 12
        cur_y = y + pad

        if img is not None:
            max_w = panel_w - 2 * pad
            target_h = int(max_w * (img.get_height() / img.get_width()))
            target_h = min(target_h, int(panel_h * 0.60))
            shot = pygame.transform.smoothscale(img, (max_w, target_h))
            screen.blit(shot, (x + pad, cur_y))
            cur_y += target_h + 10

        f = pygame.font.SysFont("arial", 22)
        if meta is not None:
            enc_pct = int(max(0.0, min(1.0, meta["enc_meter"])) * 100)
            lines = [
                f"Tag {meta['day']}  |  {meta['time_str']}",
                f"Level {meta['level']}  |  XP {meta['xp']}",
                f"Gefahr {enc_pct}%",
            ]
        else:
            lines = ["Save vorhanden, aber Metadaten fehlen."]

        for line in lines:
            surf = f.render(line, True, (240, 240, 240))
            screen.blit(surf, (x + pad, cur_y))
            cur_y += surf.get_height() + 6

    def render(self, screen) -> None:
        sw, sh = screen.get_size()

        # Welt im Hintergrund rendern (eingefroren)
        if hasattr(self.game, "state_stack") and len(self.game.state_stack) >= 2:
            below = self.game.state_stack[-2]
            below.render(screen)

        # dunkles Overlay
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))

        # Layout
        self._build_layout(sw, sh)

        # Buttons zeichnen
        mx, my = pygame.mouse.get_pos()
        for i, label in enumerate(self.labels):
            rect = self._button_rects[label]
            hover = rect.collidepoint(mx, my)
            selected = (i == self.selected_index)
            
            if label == "sign_load" and hover:
                self._draw_load_preview(screen, rect)

            # Bildschild?
            sign = self._scaled_signs.get(label)
            if sign is not None:
                screen.blit(sign, rect.topleft)

                # sehr dezenter Hover-Tint (kein Rahmen!)
                if hover or selected:
                    tint = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                    tint.fill((255, 255, 255, 18))
                    screen.blit(tint, rect.topleft)
            else:
                # Fallback: Textbutton
                bg = (38, 48, 62) if (hover or selected) else (26, 32, 40)
                pygame.draw.rect(screen, bg, rect, border_radius=12)
                txt = self.small.render(label, True, (240, 240, 240))
                screen.blit(txt, txt.get_rect(center=rect.center))

        if getattr(self, "_toast", None):
            msg, t0 = self._toast
            if pygame.time.get_ticks() - t0 < 1400:
                surf = self.small.render(msg, True, (240, 240, 240))
                r = surf.get_rect(center=(sw // 2, int(sh * 0.86)))
                screen.blit(surf, r)
            else:
                self._toast = None

    def _slug(self, s: str) -> str:
        s = s.strip().lower()
        # deutsche Umlaute / ß
        repl = {
            "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
            " ": "_", "-": "_"
        }
        for a, b in repl.items():
            s = s.replace(a, b)
        # nur a-z, 0-9, _
        out = []
        for ch in s:
            if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_":
                out.append(ch)
        return "".join(out)

    def _crop_to_alpha(self, surf: pygame.Surface, min_alpha: int = 10) -> pygame.Surface:
        rect = surf.get_bounding_rect(min_alpha=min_alpha)
        if rect.width <= 0 or rect.height <= 0:
            return surf
        return surf.subsurface(rect).copy().convert_alpha()

    def _activate(self, label: str) -> None:
        # Click SFX
        audio = getattr(self.ctx, "audio", None)
        if audio is not None:
            audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))

        if label == "back":
            self.game.pop()
            return

        if label == "sign_save":
            # 1) sauberen Preview-Screenshot aus dem State unter dem PauseMenu rendern
            below = None
            if hasattr(self.game, "state_stack") and len(self.game.state_stack) >= 2:
                below = self.game.state_stack[-2]

            if below is not None:
                sw, sh = self.game.screen.get_size()
                tmp = pygame.Surface((sw, sh), pygame.SRCALPHA)
                below.render(tmp)

                from core.save_system import save_preview, save_game
                save_preview(tmp)     # saves/preview.png
                save_game(self.ctx)   # saves/savegame.json
            else:
                from core.save_system import save_game
                save_game(self.ctx)

            self._toast = ("Spiel gespeichert.", pygame.time.get_ticks())
            return

        if label == "sign_load":
            from core.save_system import load_game
            ok = load_game(self.ctx)
            if ok:
                self.game.pop()
                from states.world import WorldMapState
                self.game.replace(WorldMapState())
            else:
                self._toast = ("Kein Savegame gefunden.", pygame.time.get_ticks())
            return

        if label == "sign_menu":
            from states.menu import MainMenuState
            self.game.replace(MainMenuState())
            return

        if label == "sign_quit":
            raise SystemExit

        # sign_options: später

