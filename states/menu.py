from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Any, Dict, List, Tuple

import pygame

from ui.video_background import VideoBackground


@dataclass
class MainMenuState:
    game: Any = None
    ctx: Any = None
    font: Optional[pygame.font.Font] = None

    def on_enter(self) -> None:
        # Reihenfolge wie gewünscht
        self.items: List[str] = ["Spiel starten", "Spiel laden", "Optionen", "Spiel beenden"]
        self.selected_index: int = 0
        self.item_hitboxes: List[Tuple[int, pygame.Rect]] = []

        if self.font is None:
            self.font = pygame.font.SysFont("arial", 40)

        # --- Video Background (Frame Sequenz) ---
        self.bg = getattr(self.ctx, "menu_bg", None)
        if self.bg is None:
            self.bg = VideoBackground(
                frames_dir=os.path.join("assets", "ui", "menu_bg_frames"),
                fps=30,
                loop=True,
                cover=True,      # cover => füllt Bildschirm, croppt ggf.
                cache_size=24
            )
            self.ctx.menu_bg = self.bg


        # --- Bild-Assets (Schilder + Seil) ---
        self._use_image_buttons: bool = True
        self._scaled_cache_key: Optional[Tuple[int, int]] = None
        self._scaled_signs: Dict[str, pygame.Surface] = {}
        self._button_rects: Dict[str, pygame.Rect] = {}


        # Passe diese Pfade an, falls deine Assets anders heißen/liegen
        self.sign_paths: Dict[str, str] = {
            "Spiel starten": os.path.join("assets", "ui", "sign_start.png"),
            "Spiel laden": os.path.join("assets", "ui", "sign_load.png"),
            "Optionen": os.path.join("assets", "ui", "sign_options.png"),
            "Spiel beenden": os.path.join("assets", "ui", "sign_quit.png"),
        }
        self.title_sign = pygame.image.load(
            os.path.join("assets", "ui", "pirate.png")
        ).convert_alpha()

        try:
            self._raw_signs = {}
            for label, path in self.sign_paths.items():
                s = pygame.image.load(path).convert_alpha()
                s = self._crop_to_alpha(s, min_alpha=10)  # <- WICHTIG
                self._raw_signs[label] = s

        except Exception:
            # Falls Assets fehlen => Text-Fallback
            self._use_image_buttons = False
            self._raw_signs = {}

        # Musik
        tracks = [
            os.path.join("assets", "music", "menu_01.mp3"),
            os.path.join("assets", "music", "menu_02.ogg"),
        ]
        audio = getattr(self.ctx, "audio", None)
        if audio is not None:
            # Musik soll zwischen Menu <-> CharacterSelect NICHT unterbrochen werden.
            # Daher nur starten, wenn aktuell keine Musik läuft.
            try:
                # Falls dein Audio-Manager so eine Methode hat
                playing = audio.is_music_playing()
            except Exception:
                # Fallback: pygame mixer status (falls dein Audio darauf basiert)
                try:
                    playing = pygame.mixer.music.get_busy()
                except Exception:
                    playing = False

            if not playing:
                audio.play_playlist(tracks, shuffle=True, fade_ms=800)

        self._load_preview_img = None
        self._load_preview_meta = None
        self._load_preview_mtime = None

    def _refresh_load_preview_cache(self) -> None:
        from core.save_system import DEFAULT_SAVE_PATH, PREVIEW_PATH, load_save_metadata
        import os, pygame

        # cache invalidation via mtime
        mtime_json = os.path.getmtime(DEFAULT_SAVE_PATH) if os.path.exists(DEFAULT_SAVE_PATH) else None
        mtime_png = os.path.getmtime(PREVIEW_PATH) if os.path.exists(PREVIEW_PATH) else None
        mtime = (mtime_json, mtime_png)

        if self._load_preview_mtime == mtime:
            return

        self._load_preview_mtime = mtime
        self._load_preview_meta = load_save_metadata(DEFAULT_SAVE_PATH)

        if os.path.exists(PREVIEW_PATH):
            try:
                img = pygame.image.load(PREVIEW_PATH).convert_alpha()
                self._load_preview_img = img
            except Exception:
                self._load_preview_img = None
        else:
            self._load_preview_img = None


    def _draw_load_preview(self, screen: pygame.Surface, anchor_rect: pygame.Rect) -> None:
        import pygame
        self._refresh_load_preview_cache()

        meta = self._load_preview_meta
        img = self._load_preview_img

        # Wenn kein Save existiert -> nichts anzeigen
        if meta is None and img is None:
            return

        sw, sh = screen.get_size()

        # Panel rechts neben dem Button (falls kein Platz: links)
        panel_w = int(min(520, max(360, sw * 0.30)))
        panel_h = int(min(340, max(260, sh * 0.30)))

        x = anchor_rect.right + 18
        if x + panel_w > sw - 10:
            x = anchor_rect.left - panel_w - 18
        y = max(10, min(sh - panel_h - 10, anchor_rect.centery - panel_h // 2))

        panel = pygame.Rect(x, y, panel_w, panel_h)

        # Background
        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 170))
        screen.blit(bg, panel.topleft)

        # Border (dezent)
        pygame.draw.rect(screen, (255, 255, 255), panel, width=1, border_radius=10)

        pad = 12
        cur_y = y + pad

        # Screenshot
        if img is not None:
            max_w = panel_w - 2 * pad
            target_h = int(max_w * (img.get_height() / img.get_width()))
            target_h = min(target_h, int(panel_h * 0.60))
            shot = pygame.transform.smoothscale(img, (max_w, target_h))
            screen.blit(shot, (x + pad, cur_y))
            cur_y += target_h + 10

        # Text
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

    def on_exit(self) -> None:
        pass



    def _crop_to_alpha(self, surf: pygame.Surface, min_alpha: int = 10) -> pygame.Surface:
        """
        Schneidet transparenten Rand weg, basierend auf Alpha.
        Ergebnis ist ein neues Surface, das nur noch den sichtbaren Schildbereich enthält.
        """
        rect = surf.get_bounding_rect(min_alpha=min_alpha)
        if rect.width <= 0 or rect.height <= 0:
            return surf
        return surf.subsurface(rect).copy().convert_alpha()

        # -------------------------
    # Layout
    # -------------------------
    def _rebuild_image_layout(self, screen_w: int, screen_h: int) -> None:
        

        # --- WICHTIG: kleiner als vorher ---
        # vorher: max(420..760, 40% Breite)
        target_sign_w = int(max(220, min(440, screen_w * 0.20)))

        vertical_spacing = int(max(6, min(14, screen_h * 0.013)))

        # --- Titel-Schild (größer, keine Interaktion) ---
        title_target_w = int(target_sign_w * 1.55)  # ca. 25 % größer als Menüschilder
        tw, th = self.title_sign.get_size()
        t_scale = title_target_w / float(tw)
        title_target_h = int(th * t_scale)

        self._scaled_title_sign = pygame.transform.smoothscale(
            self.title_sign, (title_target_w, title_target_h)
        ).convert_alpha()

        """
        Skaliert Schilder & Seil auf die aktuelle Fenstergröße
        und berechnet die Button-Rects + Hitboxen.
        """
        if not self._use_image_buttons:
            return

        key = (screen_w, screen_h)
        if self._scaled_cache_key == key:
            return
        self._scaled_cache_key = key

        self._scaled_signs.clear()
        self._button_rects.clear()


        # Referenz für Height-Scaling
        ref = self._raw_signs.get(self.items[0])
        if ref is None:
            self._use_image_buttons = False
            return

        rw, rh = ref.get_size()
        scale = target_sign_w / float(max(1, rw))
        target_sign_h = int(rh * scale)

        # Schilder skalieren (alle gleich groß)
        for label in self.items:
            surf = self._raw_signs.get(label)
            if surf is None:
                continue
            self._scaled_signs[label] = pygame.transform.smoothscale(
                surf, (target_sign_w, target_sign_h)
            ).convert_alpha()

        # Layout: Buttons vertikal zentriert
        total_h = len(self.items) * target_sign_h + (len(self.items) - 1) * vertical_spacing
        start_y = screen_h // 2 - total_h // 2

        # Titel-Position (zentriert, oberhalb der Buttons)
        self._title_rect = self._scaled_title_sign.get_rect()
        self._title_rect.centerx = screen_w // 2
        self._title_rect.bottom = start_y - int(screen_h * 0.04)


        self.item_hitboxes = []
        for i, label in enumerate(self.items):
            sign = self._scaled_signs.get(label)
            if sign is None:
                continue
            x = screen_w // 2 - sign.get_width() // 2
            y = start_y + i * (target_sign_h + vertical_spacing)
            rect = pygame.Rect(x, y, sign.get_width(), sign.get_height())
            self._button_rects[label] = rect

            # Hitbox auf nicht-transparente Fläche zuschneiden
            # bounding rect ist relativ zum Surface -> auf Screen-Koordinaten verschieben
            tight = sign.get_bounding_rect(min_alpha=10)  # 0..255; 10 filtert Anti-Aliasing-Noise
            hit = pygame.Rect(rect.left + tight.left, rect.top + tight.top, tight.width, tight.height)

            # optional: noch leicht "einrücken", damit nicht bis zur Kante klickbar ist
            pad = max(4, int(hit.width * 0.03))
            hit.inflate_ip(-2 * pad, -2 * pad)

            self.item_hitboxes.append((i, hit))

    def _rebuild_hitboxes_attach_text(self, screen_w: int, screen_h: int) -> None:
        spacing = 60
        total_height = len(self.items) * spacing
        start_y = screen_h // 2 - total_height // 2

        self.item_hitboxes = []
        for i, item in enumerate(self.items):
            txt = self.font.render(item, True, (240, 240, 240))
            tx = screen_w // 2 - txt.get_width() // 2
            ty = start_y + i * spacing
            rect = pygame.Rect(tx - 20, ty - 8, txt.get_width() + 40, txt.get_height() + 16)
            self.item_hitboxes.append((i, rect))

    # -------------------------
    # Actions
    # -------------------------
    def activate_selected(self) -> None:
        selected = self.items[self.selected_index]

        if selected == "Spiel starten":
            from states.character_select import CharacterSelectState
            self.game.replace(CharacterSelectState())
            return

        if selected == "Spiel beenden":
            raise SystemExit
        
        from core.save_system import save_exists
        if not save_exists():
            self._toast = ("Kein Savegame gefunden.", pygame.time.get_ticks())
            return

        if selected == "Spiel laden":
            from core.save_system import load_game
            ok = load_game(self.ctx)
            if ok:
                from states.world import WorldMapState
                self.game.replace(WorldMapState())
            else:
                self._toast = ("Kein Savegame gefunden.", pygame.time.get_ticks())
            return

        # "Spiel laden" / "Optionen" später – aktuell bewusst keine Aktion
        return

    # -------------------------
    # Loop
    # -------------------------
    def handle_event(self, event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self.selected_index = (self.selected_index - 1) % len(self.items)
            elif event.key == pygame.K_DOWN:
                self.selected_index = (self.selected_index + 1) % len(self.items)
            elif event.key == pygame.K_RETURN:
                audio = getattr(self.ctx, "audio", None)
                if audio is not None:
                    audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                self.activate_selected()
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            surf = pygame.display.get_surface()
            if surf is None:
                return
            w, h = surf.get_size()

            if self._use_image_buttons:
                self._rebuild_image_layout(w, h)
            else:
                self._rebuild_hitboxes_attach_text(w, h)

            for idx, rect in self.item_hitboxes:
                if rect.collidepoint(mx, my):
                    self.selected_index = idx
                    audio = getattr(self.ctx, "audio", None)
                    if audio is not None:
                        audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                    self.activate_selected()
                    return

    def update(self, dt):
        if self.bg:
            self.bg.update(dt)


    def render(self, screen) -> None:
        if self.bg:
            self.bg.draw(screen)

        # --- Video Background ---
        if hasattr(self, "bg") and self.bg is not None and self.bg.has_frames():
            self.bg.draw(screen)

            # leichte Abdunklung => bessere Lesbarkeit
            overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 70))
            screen.blit(overlay, (0, 0))
        else:
            screen.fill((12, 14, 18))

        if self.font is None:
            self.font = pygame.font.SysFont("arial", 40)

        w, h = screen.get_size()
        mx, my = pygame.mouse.get_pos()

        if self._use_image_buttons:
            self._rebuild_image_layout(w, h)

            # Hover -> selection (via Hitboxen)
            for i, hit in self.item_hitboxes:
                if hit.collidepoint(mx, my):
                    self.selected_index = i

            # Titel-Schild (ohne Interaktion)
            if hasattr(self, "_scaled_title_sign"):
                screen.blit(self._scaled_title_sign, self._title_rect.topleft)

            # -------------------------
            # Schilder (über den Seilen)
            # -------------------------
            from core.save_system import save_exists
            load_available = save_exists()  # <-- DIES muss außerhalb der Schleife stehen! (siehe Schritt 1)

            for i, label in enumerate(self.items):
                rect = self._button_rects.get(label)
                sign = self._scaled_signs.get(label)
                if rect is None or sign is None:
                    continue

                is_load_btn = (label == "Spiel laden")
                disabled = is_load_btn and (not load_available)

                hover = (not disabled) and rect.collidepoint(mx, my)
                selected = (i == self.selected_index)

                # Schild zeichnen
                if disabled:
                    sign2 = sign.copy()
                    sign2.set_alpha(140)
                    screen.blit(sign2, rect.topleft)
                else:
                    screen.blit(sign, rect.topleft)

                # Glow nur wenn nicht disabled
                if (hover or selected) and (not disabled):
                    tint = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                    tint.fill((255, 255, 255, 18))
                    screen.blit(tint, rect.topleft)

                # Tooltip
                if disabled and rect.collidepoint(mx, my):
                    tip_font = pygame.font.SysFont("arial", 20)
                    tip = tip_font.render("Kein Savegame gefunden", True, (240, 240, 240))
                    tip_bg = pygame.Surface((tip.get_width() + 16, tip.get_height() + 10), pygame.SRCALPHA)
                    tip_bg.fill((0, 0, 0, 170))
                    tx = rect.centerx - tip_bg.get_width() // 2
                    ty = rect.bottom + 10
                    screen.blit(tip_bg, (tx, ty))
                    screen.blit(tip, (tx + 8, ty + 5))



                if label == "Spiel laden" and hover:
                    self._draw_load_preview(screen, rect)
                    is_load_btn = (label == "Spiel laden")
                    disabled = is_load_btn and not load_available
                    hover = rect.collidepoint(mx, my)
                    selected = (i == self.selected_index)
                    hover = (not disabled) and rect.collidepoint(mx, my)



        else:
            # Fallback: Textbuttons (falls Bilder fehlen)
            self._rebuild_hitboxes_attach_text(w, h)

            for i, rect in self.item_hitboxes:
                item = self.items[i]
                hover = rect.collidepoint(mx, my)
                if hover:
                    self.selected_index = i

                is_selected = (i == self.selected_index)
                if hover or is_selected:
                    pygame.draw.rect(screen, (45, 60, 85), rect, border_radius=8)

                txt = self.font.render(item, True, (240, 240, 240))
                tx = rect.centerx - txt.get_width() // 2
                ty = rect.centery - txt.get_height() // 2
                screen.blit(txt, (tx, ty))
