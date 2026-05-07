from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import pygame


@dataclass
class OptionsState:
    game: Any = None
    ctx: Any = None
    fonts: Any = None

    # background mode
    # - "menu": uses ctx.menu_bg (VideoBackground) live
    # - "snapshot": uses a frozen surface
    bg_mode: str = "menu"
    bg_snapshot: Optional[pygame.Surface] = None

    # ui
    selected_row: int = 0  # 0 = volume, 1 = language, 2 = fullscreen, 3 = controls
    volume_pct: int = 55   # 0..100
    dragging: bool = False
    fullscreen: bool = False

    def on_enter(self) -> None:
        from core.ui_text import FontBank
        from settings import UI_FONT_PATH, UI_FONT_FALLBACK

        if self.fonts is None:
            self.fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)

        self.title_font = self.fonts.get(44)
        self.body_font = self.fonts.get(22)
        self.small_font = self.fonts.get(16)

        # init from audio if possible
        self.volume_pct = self._read_volume_pct()
        self.fullscreen = bool(getattr(self.ctx, "fullscreen", False))

        # click sound path (optional)
        self._click_sfx = os.path.join("assets", "sfx", "ui_click.mp3")

        # --- use same background as Stats menu (assets/ui/bg_stats.png) ---
        self._bg_stats = None
        try:
            self._bg_stats = pygame.image.load(os.path.join("assets", "ui", "bg_stats.png")).convert_alpha()
        except Exception:
            self._bg_stats = None

        # --- back button wood sign ---
        self._back_img = None
        try:
            self._back_img = pygame.image.load(
                os.path.join("assets", "ui", "back.png")
            ).convert_alpha()
        except Exception:
            self._back_img = None

        self._dirty_settings = False

    def on_exit(self) -> None:
        pass

    # ----------------------------
    # Input
    # ----------------------------
    def handle_event(self, event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE,):
                self._save_settings_if_dirty()
                self.game.pop()
                return
            if event.key in (pygame.K_UP, pygame.K_w):
                self.selected_row = max(0, self.selected_row - 1)
                return

            if event.key in (pygame.K_DOWN, pygame.K_s):
                self.selected_row = min(3, self.selected_row + 1)
                return

            if event.key in (pygame.K_LEFT, pygame.K_a):
                if self.selected_row == 0:
                    self._set_volume(self.volume_pct - 5)
                    return
                if self.selected_row == 1:
                    self._toggle_language()
                    return
                if self.selected_row == 2:
                    self._toggle_fullscreen()
                    return

            if event.key in (pygame.K_RIGHT, pygame.K_d):
                if self.selected_row == 0:
                    self._set_volume(self.volume_pct + 5)
                    return
                if self.selected_row == 1:
                    self._toggle_language()
                    return
                if self.selected_row == 2:
                    self._toggle_fullscreen()
                    return

            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                if self.selected_row == 1:
                    self._play_click()
                    self._toggle_language()
                    return
                if self.selected_row == 2:
                    self._play_click()
                    self._toggle_fullscreen()
                    return
                self._play_click()
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            vol_track, vol_knob = self._volume_rects(self.game.screen.get_size())
            back_rect = self._back_button_rect(self.game.screen.get_size())

            if back_rect.collidepoint(mx, my):
                self._play_click()
                self._save_settings_if_dirty()
                self.game.pop()
                return

            # click on volume row -> start dragging
            if vol_track.collidepoint(mx, my) or vol_knob.collidepoint(mx, my):
                self.selected_row = 0
                self.dragging = True
                self._apply_volume_from_mouse(mx, vol_track)
                return

            # click on language header selects row
            lang_rect = self._language_header_rect(self.game.screen.get_size())
            if lang_rect.collidepoint(mx, my):
                self.selected_row = 1
                self._play_click()
                self._toggle_language()
                return

            fullscreen_rect = self._fullscreen_header_rect(self.game.screen.get_size())
            if fullscreen_rect.collidepoint(mx, my):
                self.selected_row = 2
                self._play_click()
                self._toggle_fullscreen()
                return
            
            # click on controls header selects row
            controls_rect = self._controls_header_rect(self.game.screen.get_size())
            if controls_rect.collidepoint(mx, my):
                self.selected_row = 3
                self._play_click()
                return

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False

        if event.type == pygame.MOUSEMOTION and self.dragging:
            mx, _my = event.pos
            vol_track, _vol_knob = self._volume_rects(self.game.screen.get_size())
            self._apply_volume_from_mouse(mx, vol_track)

    # ----------------------------
    # Update / Render
    # ----------------------------
    def update(self, dt: float) -> None:
        # only menu background is “live”
        if self.bg_mode == "menu":
            bg = getattr(self.ctx, "menu_bg", None)
            if bg is not None:
                try:
                    bg.update(dt)
                except Exception:
                    pass

    def render(self, screen: pygame.Surface) -> None:
        sw, sh = screen.get_size()

        # --- background ---
        if self.bg_mode == "menu":
            bg = getattr(self.ctx, "menu_bg", None)
            if bg is not None:
                try:
                    bg.draw(screen)
                except Exception:
                    screen.fill((12, 14, 18))
            else:
                screen.fill((12, 14, 18))
        else:
            if self.bg_snapshot is not None:
                screen.blit(self.bg_snapshot, (0, 0))
            else:
                screen.fill((12, 14, 18))

        # readability overlay
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        screen.blit(dim, (0, 0))

        # panel
        panel_w = int(min(860, sw * 0.72))
        panel_h = int(min(620, sh * 0.82))
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (sw // 2, sh // 2)

        # --- stats background as panel background (overscan like stats menu) ---
        bg = getattr(self, "_bg_stats", None)
        if bg is not None:
            # --- scale stats background exactly to panel (with optional zoom) ---
            bg_w, bg_h = bg.get_size()

            # scale factors per axis
            sx = panel.w / bg_w
            sy = panel.h / bg_h

            # fill strategy: take larger factor so panel is fully covered
            scale_w = sx
            scale_h = sy

            # optional subtle zoom (feel free to tweak: 1.0–1.08)
            scale_w *= 1.05
            scale_h *= 1.35

            scaled_w = int(bg_w * scale_w)
            scaled_h = int(bg_h * scale_h)

            bg_scaled = pygame.transform.smoothscale(bg, (scaled_w, scaled_h))

            # center crop into panel
            bx = panel.x - (scaled_w - panel.w) // 2
            by = panel.y - (scaled_h - panel.h) // 2

            screen.blit(bg_scaled, (bx, by))


            # readability overlay inside panel area (subtle dark layer)
            overlay = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 80))
            screen.blit(overlay, (panel.x, panel.y))
        else:
            # fallback
            fallback = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
            fallback.fill((20, 20, 24, 235))
            screen.blit(fallback, (panel.x, panel.y))

        # title
        title = self.title_font.render(self.ctx.i18n.t("options.title"), True, (240, 240, 240))
        screen.blit(title, (panel.x + 22, panel.y + 16))

        # --- Volume row ---
        y0 = panel.y + 90
        self._draw_row_header(
            screen,
            rect=pygame.Rect(panel.x + 22, y0, panel.w - 44, 48),
            text=self.ctx.i18n.t("options.row.volume"),
            selected=(self.selected_row == 0),
        )

        vol_track, vol_knob = self._volume_rects((sw, sh), panel=panel, top=y0 + 56)
        pygame.draw.rect(screen, (70, 70, 80), vol_track, border_radius=10)
        pygame.draw.rect(screen, (220, 220, 230), vol_knob, border_radius=10)

        vol_txt = self.body_font.render(f"{self.volume_pct}%", True, (240, 240, 240))
        screen.blit(vol_txt, vol_txt.get_rect(midleft=(vol_track.right + 16, vol_track.centery)))

        hint = self.small_font.render(self.ctx.i18n.t("options.hint.volume"), True, (190, 190, 200))
        screen.blit(hint, (vol_track.x, vol_track.bottom + 10))

        # --- Language row ---
        y_lang = vol_track.bottom + 42
        lang_header = pygame.Rect(panel.x + 22, y_lang, panel.w - 44, 48)
        self._draw_row_header(
            screen,
            rect=lang_header,
            text=self.ctx.i18n.t("options.row.language"),
            selected=(self.selected_row == 1),
        )

        cur_lang = getattr(self.ctx, "lang", "de")
        lang_value_key = "options.language.de" if cur_lang == "de" else "options.language.en"
        lang_value = self.body_font.render(self.ctx.i18n.t(lang_value_key), True, (240, 240, 240))
        screen.blit(lang_value, lang_value.get_rect(midright=(lang_header.right - 16, lang_header.centery)))

        # --- Fullscreen row ---
        y_fullscreen = y_lang + 48 + 18
        fullscreen_header = pygame.Rect(panel.x + 22, y_fullscreen, panel.w - 44, 48)
        self._draw_row_header(
            screen,
            rect=fullscreen_header,
            text=self.ctx.i18n.t("options.row.fullscreen"),
            selected=(self.selected_row == 2),
        )

        fullscreen_value_key = "options.value.on" if self.fullscreen else "options.value.off"
        fullscreen_value = self.body_font.render(self.ctx.i18n.t(fullscreen_value_key), True, (240, 240, 240))
        screen.blit(fullscreen_value, fullscreen_value.get_rect(midright=(fullscreen_header.right - 16, fullscreen_header.centery)))

        # --- Controls row ---
        y1 = y_fullscreen + 48 + 18
        controls_header = pygame.Rect(panel.x + 22, y1, panel.w - 44, 48)
        self._draw_row_header(
            screen,
            rect=controls_header,
            text=self.ctx.i18n.t("options.row.controls"),
            selected=(self.selected_row == 3),
        )

        # controls text block
        lines = [
            (self.ctx.i18n.t("options.controls.k1"), self.ctx.i18n.t("options.controls.v1")),
            (self.ctx.i18n.t("options.controls.k2"), self.ctx.i18n.t("options.controls.v2")),
            (self.ctx.i18n.t("options.controls.k3"), self.ctx.i18n.t("options.controls.v3")),
            (self.ctx.i18n.t("options.controls.k4"), self.ctx.i18n.t("options.controls.v4")),
            (self.ctx.i18n.t("options.controls.k5"), self.ctx.i18n.t("options.controls.v5")),
            (self.ctx.i18n.t("options.controls.k6"), self.ctx.i18n.t("options.controls.v6")),
            (self.ctx.i18n.t("options.controls.k7"), self.ctx.i18n.t("options.controls.v7")),
        ]

        tx = panel.x + 34
        ty = controls_header.bottom + 12
        for k, v in lines:
            ks = self.body_font.render(f"{k}:", True, (220, 220, 230))
            vs = self.body_font.render(v, True, (240, 240, 240))
            screen.blit(ks, (tx, ty))
            screen.blit(vs, (tx + 220, ty))
            ty += 25

        # back button
        back_rect = self._back_button_rect((sw, sh), panel=panel)
        self._draw_button(screen, back_rect, self.ctx.i18n.t("ui.back"))

    # ----------------------------
    # Layout helpers
    # ----------------------------

    def _language_header_rect(self, size: Tuple[int, int]) -> pygame.Rect:
        sw, sh = size
        panel_w = int(min(860, sw * 0.72))
        panel_h = int(min(620, sh * 0.82))
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (sw // 2, sh // 2)

        y0 = panel.y + 90
        vol_track, _ = self._volume_rects((sw, sh), panel=panel, top=y0 + 56)
        y_lang = vol_track.bottom + 42
        return pygame.Rect(panel.x + 22, y_lang, panel.w - 44, 48)

    def _fullscreen_header_rect(self, size: Tuple[int, int]) -> pygame.Rect:
        lang_rect = self._language_header_rect(size)
        return pygame.Rect(lang_rect.x, lang_rect.bottom + 18, lang_rect.w, lang_rect.h)

    def _toggle_language(self) -> None:
        cur = getattr(self.ctx, "lang", "de")
        new = "en" if cur == "de" else "de"
        self._set_language(new)

    def _set_language(self, lang: str) -> None:
        if lang not in ("de", "en"):
            return
        self.ctx.lang = lang
        i18n = getattr(self.ctx, "i18n", None)
        if i18n is not None:
            try:
                i18n.set_lang(lang)
            except Exception:
                # fallback: reload
                try:
                    i18n.lang = lang
                    i18n.load()
                except Exception:
                    pass
    
        self._dirty_settings = True
        from settings import save_user_settings
        save_user_settings({
            "lang": getattr(self.ctx, "lang", "de"),
            "volume_pct": int(getattr(self, "volume_pct", getattr(self.ctx, "volume_pct", 55))),
            "fullscreen": bool(getattr(self.ctx, "fullscreen", False)),
        })
        self._dirty_settings = False  # language already persisted

    def _toggle_fullscreen(self) -> None:
        self._set_fullscreen(not bool(getattr(self, "fullscreen", False)))

    def _set_fullscreen(self, enabled: bool) -> None:
        from settings import SCREEN_W, SCREEN_H, save_user_settings

        self.fullscreen = bool(enabled)
        self.ctx.fullscreen = self.fullscreen

        flags = pygame.SCALED
        if self.fullscreen:
            flags |= pygame.FULLSCREEN

        try:
            self.game.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
            try:
                icon = pygame.image.load(os.path.join("assets", "ui", "level.png"))
                pygame.display.set_icon(icon)
            except Exception:
                pass
            try:
                cursor = pygame.image.load(os.path.join("assets", "mouse.png")).convert_alpha()
                cursor = pygame.transform.smoothscale(cursor, (32, 38))
                pygame.mouse.set_cursor((0, 0), cursor)
            except Exception:
                pass
        except Exception:
            self.fullscreen = not self.fullscreen
            self.ctx.fullscreen = self.fullscreen
            return

        save_user_settings({
            "lang": getattr(self.ctx, "lang", "de"),
            "volume_pct": int(getattr(self, "volume_pct", getattr(self.ctx, "volume_pct", 55))),
            "fullscreen": self.fullscreen,
        })
        self._dirty_settings = False

    def _volume_rects(self, size: Tuple[int, int], panel: Optional[pygame.Rect] = None, top: Optional[int] = None):
        sw, sh = size
        if panel is None:
            panel_w = int(min(860, sw * 0.72))
            panel_h = int(min(620, sh * 0.82))
            panel = pygame.Rect(0, 0, panel_w, panel_h)
            panel.center = (sw // 2, sh // 2)

        y = top if top is not None else (panel.y + 150)
        track = pygame.Rect(panel.x + 34, y, int(panel.w * 0.58), 18)

        t = self.volume_pct / 100.0
        knob_w = 18
        knob_x = int(track.x + t * (track.w - knob_w))
        knob = pygame.Rect(knob_x, track.y - 6, knob_w, track.h + 12)
        return track, knob

    def _controls_header_rect(self, size: Tuple[int, int]) -> pygame.Rect:
        sw, sh = size
        panel_w = int(min(860, sw * 0.72))
        panel_h = int(min(620, sh * 0.82))
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (sw // 2, sh // 2)

        fullscreen_rect = self._fullscreen_header_rect(size)
        return pygame.Rect(panel.x + 22, fullscreen_rect.bottom + 18, panel.w - 44, 48)

    def _back_button_rect(self, size: Tuple[int, int], panel: Optional[pygame.Rect] = None) -> pygame.Rect:
        sw, sh = size
        if panel is None:
            panel_w = int(min(860, sw * 0.72))
            panel_h = int(min(620, sh * 0.82))
            panel = pygame.Rect(0, 0, panel_w, panel_h)
            panel.center = (sw // 2, sh // 2)

        r = pygame.Rect(0, 0, 220, 72)  # etwas größer für Schild
        r.bottomright = (panel.right - 28, panel.bottom - 60)
        return r


    def _draw_row_header(self, screen: pygame.Surface, rect: pygame.Rect, text: str, selected: bool) -> None:
        if selected:
            bg = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            bg.fill((255, 255, 255, 18))
            screen.blit(bg, rect.topleft)

        surf = self.body_font.render(text, True, (240, 240, 240))
        screen.blit(surf, (rect.x + 10, rect.y + (rect.h - surf.get_height()) // 2))

    def _draw_button(self, screen: pygame.Surface, rect: pygame.Rect, text: str) -> None:
        mx, my = pygame.mouse.get_pos()
        hover = rect.collidepoint(mx, my)

        if self._back_img is not None:
            img = pygame.transform.smoothscale(
                self._back_img, (rect.w, rect.h)
            )
            screen.blit(img, rect.topleft)

            # leichter Hover-Glow
            if hover:
                glow = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
                glow.fill((255, 255, 255, 35))
                screen.blit(glow, rect.topleft)

        else:
            # Fallback (falls PNG fehlt)
            bg = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            bg.fill((40, 40, 48, 220))
            screen.blit(bg, rect.topleft)
            pygame.draw.rect(screen, (255, 255, 255), rect, 1, border_radius=12)

    # ----------------------------
    # Volume logic
    # ----------------------------
    def _apply_volume_from_mouse(self, mx: int, track: pygame.Rect) -> None:
        t = (mx - track.x) / float(max(1, track.w))
        pct = int(round(max(0.0, min(1.0, t)) * 100))
        self._set_volume(pct)

    def _set_volume(self, pct: int) -> None:
        pct = int(max(0, min(100, pct)))
        if pct == self.volume_pct:
            return
        self.volume_pct = pct
        self._apply_volume_to_audio()
        self._dirty_settings = True

    def _read_volume_pct(self) -> int:
        audio = getattr(self.ctx, "audio", None)
        if audio is None:
            return 55

        # Try common patterns
        for attr in ("master_volume", "volume", "music_volume"):
            try:
                v = float(getattr(audio, attr))
                return int(round(max(0.0, min(1.0, v)) * 100))
            except Exception:
                pass

        # fallback to pygame music volume if mixer is active
        try:
            v = float(pygame.mixer.music.get_volume())
            return int(round(max(0.0, min(1.0, v)) * 100))
        except Exception:
            return 55

    def _apply_volume_to_audio(self) -> None:
        audio = getattr(self.ctx, "audio", None)
        v = max(0.0, min(1.0, self.volume_pct / 100.0))

        # Prefer explicit setters if they exist
        if audio is not None:
            for fn_name in ("set_master_volume", "set_volume"):
                fn = getattr(audio, fn_name, None)
                if callable(fn):
                    try:
                        fn(v)
                        return
                    except Exception:
                        pass

            # else: set both music + sfx if available
            for fn_name in ("set_music_volume", "set_sfx_volume"):
                fn = getattr(audio, fn_name, None)
                if callable(fn):
                    try:
                        fn(v)
                    except Exception:
                        pass

            # also store attributes if present
            for attr in ("master_volume", "volume", "music_volume", "sfx_volume"):
                if hasattr(audio, attr):
                    try:
                        setattr(audio, attr, v)
                    except Exception:
                        pass

        # always apply at least to pygame music volume
        try:
            pygame.mixer.music.set_volume(v)
        except Exception:
            pass

    def _save_settings_if_dirty(self) -> None:
        if not getattr(self, "_dirty_settings", False):
            return
        from settings import save_user_settings
        save_user_settings({
            "lang": getattr(self.ctx, "lang", "de"),
            "volume_pct": int(getattr(self, "volume_pct", getattr(self.ctx, "volume_pct", 55))),
            "fullscreen": bool(getattr(self.ctx, "fullscreen", getattr(self, "fullscreen", False))),
        })
        self._dirty_settings = False

    def _play_click(self) -> None:
        audio = getattr(self.ctx, "audio", None)
        if audio is None:
            return
        try:
            audio.play_sfx(self._click_sfx)
        except Exception:
            pass
