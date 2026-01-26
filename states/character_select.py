import os
import pygame
from core.run_config import DIFFICULTY_PRESETS, DEFAULT_DIFFICULTY_ID
import json
from ui.video_background import VideoBackground


class CharacterSelectState:
    def on_enter(self):
        self.font = pygame.font.SysFont("arial", 34)
        self.small = pygame.font.SysFont("arial", 20)

        # Charakterdefinition (später in JSON auslagern)
        self.chars = [
            {
                "id": "char_01",
                "name": "Händler",
                "portrait": "Ruben.png",
                "food_buy_discount": 0.10,
                "start_ship_type_id": "sloop"
            },
            {
                "id": "char_02",
                "name": "Seemann",
                "portrait": "Lucy.png",
                "weapon_buy_discount": 0.08,
                "start_ship_type_id": "sloop"
            },
            {
                "id": "char_03",
                "name": "Navigator",
                "portrait": "Carlo.png",
                "food_buy_discount": 0.05,
                "start_ship_type_id": "sloop"
            },

            # --- Neue Charaktere ---
            {
                "id": "char_04",
                "name": "Schmuggler",
                "portrait": "Miroso.png",
                "buy_discount_category": "illegal",
                "buy_discount": 0.12,
                "start_ship_type_id": "holk"
            },
            {
                "id": "char_05",
                "name": "Quartiermeister",
                "portrait": "Leyla.png",
                "food_buy_discount": 0.06,
                "weapon_buy_discount": 0.04,
                "start_ship_type_id": "sloop"
            },
            {
                "id": "char_06",
                "name": "Finanzier",
                "portrait": "Gerhaldt.png",
                "buy_discount": 0.05,
                "start_ship_type_id": "sloop"
            },
        ]


        self.selected = 0
        self.portraits = []
        for c in self.chars:
            p = os.path.join("assets", "portraits", c["portrait"])
            img = pygame.image.load(p).convert_alpha()
            img = pygame.transform.scale(img, (140, 140))
            self.portraits.append(img)

        self.hitboxes = []

        # Difficulty Presets aus run_config.py (Option A)
        # Format je Eintrag: ("normal", price_spread_mult, event_freq_mult, start_money_mult, start_gold_base)
        self.diffs = DIFFICULTY_PRESETS

        # Default auswählen
        self.selected_diff = 0
        for i, d in enumerate(self.diffs):
            if d[0] == DEFAULT_DIFFICULTY_ID:
                self.selected_diff = i
                break

        self.diff_hitboxes = []
        self.base_start_money = 5000  # gleiche Basis wie bisher im Setup-State

        self.ship_previews = {}
        ship_preview_size = (180, 180)

        # Mapping: type_id -> display_name (gleichzeitig Dateiname deiner PNGs)
        self.ship_type_to_name = {
            "sloop": "Schaluppe",
            "holk": "Holk",
            "carrack": "Karake",
            "fluyt": "Fleute",
            "line": "Linienschiff",
        }

        for type_id, display_name in self.ship_type_to_name.items():
            p = os.path.join("assets", "ships", f"{display_name}.png")
            img = pygame.image.load(p).convert_alpha()
            img = pygame.transform.smoothscale(img, ship_preview_size)
            self.ship_previews[type_id] = img

        # Ship-Stats aus ship.json laden (für Panel-Anzeige)
        self.ship_defs = {}
        here = os.path.dirname(os.path.abspath(__file__))
        ship_json_path = os.path.normpath(os.path.join(here, "..", "content", "ships.json"))

        try:
            with open(ship_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Erwartet: {"ships":[{"id":"sloop","name":"Schaluppe","capacity_tons":..,"speed_px_s":..}, ...]}
            for s in data.get("ships", []):
                if "id" in s:
                    self.ship_defs[s["id"]] = s
        except Exception:
            # Fallback: leer lassen, UI zeigt dann nur das Bild
            self.ship_defs = {}

        # Start-Button (Bild unten rechts)
        self.start_img = None
        self.start_rect = None
        start_path = os.path.join("assets", "ui", "start_game.png")  # <-- Dateiname/Ordner ggf. anpassen

        if os.path.exists(start_path):
            img = pygame.image.load(start_path).convert_alpha()

            max_w, max_h = 280, 110
            iw, ih = img.get_size()
            scale = min(1 * max_w / iw, 1 * max_h / ih)
            new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))

            self.start_img = pygame.transform.smoothscale(img, new_size)

        # --- Back-Button (unten mittig) ---
        self.back_img = None
        self.back_rect = None

        back_path = os.path.join("assets", "ui", "back.png")  # falls vorhanden
        if os.path.exists(back_path):
            img = pygame.image.load(back_path).convert_alpha()

            # etwas kleiner als Startbutton, passt unten mittig
            max_w, max_h = 220, 90
            iw, ih = img.get_size()
            scale = min(max_w / iw, max_h / ih)
            new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
            self.back_img = pygame.transform.smoothscale(img, new_size)

        # --- Titel-Schild oben mittig (keine Interaktion) ---
        self.title_img = None
        self.title_rect = None

        # Passe den Dateinamen an, falls dein Bild anders heißt
        title_path = os.path.join("assets", "ui", "charakterauswahl.png")
        if os.path.exists(title_path):
            img = pygame.image.load(title_path).convert_alpha()
            self.title_img = img


        # --- Shared Menu Video Background (identisch wie im Hauptmenü) ---
        self.bg = getattr(self.ctx, "menu_bg", None)



    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self.selected = max(0, self.selected - 1)
            elif event.key == pygame.K_RIGHT:
                self.selected = min(len(self.chars) - 1, self.selected + 1)
            elif event.key == pygame.K_UP:
                self.selected_diff = max(0, self.selected_diff - 1)
            elif event.key == pygame.K_DOWN:
                self.selected_diff = min(len(self.diffs) - 1, self.selected_diff + 1)
            elif event.key == pygame.K_RETURN:
                self._apply_and_start()
                return


        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            for i, r in self.hitboxes:
                if r.collidepoint(mx, my):
                    self.selected = i
                    # optional: Klick-Sound
                    if getattr(self.ctx, "audio", None) is not None:
                        self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.wav"))
                    return


            # Difficulty wählen
            for i, r in self.diff_hitboxes:
                if r.collidepoint(mx, my):
                    self.selected_diff = i
                    if getattr(self.ctx, "audio", None) is not None:
                        self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.wav"))
                    return
                
            # Start-Button klicken
            if self.start_rect is not None and self.start_rect.collidepoint(mx, my):
                self._apply_and_start()
                return

                        # Back-Button klicken
            if self.back_rect is not None and self.back_rect.collidepoint(mx, my):
                if getattr(self.ctx, "audio", None) is not None:
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.wav"))

                from states.menu import MainMenuState
                st = MainMenuState()
                st.game = self.game
                st.ctx = self.ctx
                self.game.replace(st)
                return




    def _apply_and_start(self):
        c = self.chars[self.selected]
        rc = self.ctx.run_config
        rc.character_id = c["id"]
        rc.food_buy_discount = float(c.get("food_buy_discount", 0.0))
        rc.weapon_buy_discount = float(c.get("weapon_buy_discount", 0.0))
        rc.buy_discount_category = c.get("buy_discount_category", "")
        rc.buy_discount = float(c.get("buy_discount", 0.0))

        # Difficulty anwenden
        diff_id, price_spread_mult, event_freq_mult, start_money_mult, start_gold_base = self.diffs[self.selected_diff]
        rc.difficulty_id = diff_id
        rc.price_spread_mult = float(price_spread_mult)
        rc.event_freq_mult = float(event_freq_mult)
        rc.start_money_mult = float(start_money_mult)

        #Schiff
        rc.start_ship_type_id = c.get("start_ship_type_id", "sloop")

        # Optional: falls du start_gold_base als Info im rc halten willst
        # (nur nötig, wenn du es später irgendwo anzeigen/loggen möchtest)
        if hasattr(rc, "start_gold_base"):
            rc.start_gold_base = int(start_gold_base)



        if getattr(self.ctx, "audio", None) is not None:
            self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.wav"))

        # Jetzt in dein bestehendes Setup / Spielstart
        from states.setup import NewGameSetupState
        st = NewGameSetupState()
        st.game = self.game
        st.ctx = self.ctx
        self.game.replace(st)



    def update(self, dt):
        if self.bg:
            self.bg.update(dt)



    def render(self, screen):
        # --- Video Background (shared) ---
        if getattr(self, "bg", None) is not None and self.bg.has_frames():
            self.bg.draw(screen)
            overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 70))  # Lesbarkeit
            screen.blit(overlay, (0, 0))
        else:
            screen.fill((12, 14, 18))

        # --- Titel-Schild oben mittig (statisch) ---
        if getattr(self, "title_img", None) is not None:
            sw, sh = screen.get_size()

            # Zielbreite: etwas größer, aber nicht zu dominant
            target_w = int(min(700, max(420, sw * 0.45)))

            iw, ih = self.title_img.get_size()
            scale = target_w / float(iw)
            new_size = (max(1, int(iw * scale)), max(1, int(ih * scale)))

            # Nur neu skalieren, wenn Größe sich geändert hat (kleiner Cache)
            if getattr(self, "_title_scaled_size", None) != new_size:
                self._title_scaled_size = new_size
                self._title_scaled = pygame.transform.smoothscale(self.title_img, new_size).convert_alpha()

            self.title_rect = self._title_scaled.get_rect(midtop=(sw // 2, -40))
            screen.blit(self._title_scaled, self.title_rect.topleft)

        self.hitboxes = []
        mx, my = pygame.mouse.get_pos()

        x0, y0 = 60, 220
        gap = 24

        for i, c in enumerate(self.chars):
            x = x0 + i * (140 + gap)
            y = y0
            r = pygame.Rect(x, y, 140, 140)
            self.hitboxes.append((i, r))

            hover = r.collidepoint(mx, my)

            # Highlight: entweder Hover oder ausgewählt
            if i == self.selected or hover:
                pygame.draw.rect(
                    screen,
                    (45, 60, 85),
                    pygame.Rect(x - 8, y - 8, 156, 200),
                    border_radius=14
                )

            # IMMER zeichnen, nicht nur wenn selected/hover
            screen.blit(self.portraits[i], (x, y))

            name = self.small.render(c["name"], True, (240, 240, 240))
            screen.blit(name, (x, y + 150))

        # --- Zentrales Schiff-Preview (abhängig vom ausgewählten Charakter) ---
        selected_char = self.chars[self.selected]
        ship_type_id = selected_char.get("start_ship_type_id", "sloop")
        ship_img = self.ship_previews.get(ship_type_id)

        pad = 24
        sw, sh = screen.get_size()

        # Panel-Breite wirklich reduzieren: 10% links + 10% rechts = 20% insgesamt
        panel_w = int(260 * 0.80)   # <- jetzt ist es garantiert schmaler
        panel_h = 360

        px = sw - panel_w - pad     # ganz rechts am Rand ausrichten
        py = y0

        panel_rect = pygame.Rect(px, py, panel_w, panel_h)
        pygame.draw.rect(screen, (26, 32, 40), panel_rect, border_radius=14)

        ship_label = self.ship_type_to_name.get(ship_type_id, ship_type_id)
        ship_title = self.small.render("Startschiff", True, (220, 220, 220))
        ship_name = self.small.render(ship_label, True, (240, 240, 240))

        # Text zentrieren
        title_rect = ship_title.get_rect(midtop=(panel_rect.centerx, panel_rect.top + 12))
        name_rect  = ship_name.get_rect(midtop=(panel_rect.centerx, panel_rect.top + 40))
        screen.blit(ship_title, title_rect)
        screen.blit(ship_name, name_rect)

        # Bild zentrieren (optional)
        if ship_img is not None:
            img_rect = ship_img.get_rect(center=(panel_rect.centerx, panel_rect.top + 170))
            screen.blit(ship_img, img_rect)

        # --- Stats anzeigen (IMMER, unabhängig vom Bild) ---
        ship_def = self.ship_defs.get(ship_type_id, {})

        cap = ship_def.get("capacity_tons", None)
        spd = ship_def.get("speed_px_s", None)
        hp  = ship_def.get("hull_hp", None)
        crew = ship_def.get("crew_max", None)
        dmg = ship_def.get("basic_attack_dmg", None)


        cap_txt = f"{cap:.0f} t" if isinstance(cap, (int, float)) else "-"
        spd_txt = f"{spd:.0f} px/s" if isinstance(spd, (int, float)) else "-"
        hp_txt = f"{hp:d}" if isinstance(hp, int) else (f"{hp:.0f}" if isinstance(hp, (int, float)) else "-")
        crew_txt = f"{crew:d}" if isinstance(crew, int) else (f"{crew:.0f}" if isinstance(crew, (int, float)) else "-")
        dmg_txt = f"{dmg:d}" if isinstance(dmg, int) else (f"{dmg:.0f}" if isinstance(dmg, (int, float)) else "-")

        lines = [
            f"Kapazität: {cap_txt}",
            f"Geschwindigkeit: {spd_txt}",
            f"Hülle: {hp_txt}",
            f"Crew max: {crew_txt}",
            f"Basisangriff: {dmg_txt}",
            ]

        # Unterer Bereich im Panel (du hast panel_h bereits erhöht)
        start_y = panel_rect.bottom - 26 * len(lines) - 14
        for idx, text in enumerate(lines):
           surf = self.small.render(text, True, (220, 220, 220))
           screen.blit(surf, surf.get_rect(midtop=(panel_rect.centerx, start_y + idx * 26)))

        # --- Difficulty UI ---
        self.diff_hitboxes = []
        dx = 60
        dy = 460

        dw, dh = 220, 46
        dgap = 12

        diff_title = self.small.render("Schwierigkeit", True, (220,220,220))
        screen.blit(diff_title, (dx, dy - 28))

        for i, d in enumerate(self.diffs):
            diff_id = d[0]
            r = pygame.Rect(dx, dy + i * (dh + dgap), dw, dh)
            self.diff_hitboxes.append((i, r))

            is_sel = (i == self.selected_diff)
            pygame.draw.rect(screen, (45, 60, 85) if is_sel else (26, 32, 40), r, border_radius=10)

            label = diff_id
            txt = self.small.render(label, True, (240,240,240))
            screen.blit(txt, (r.x + 12, r.y + 12))

        # Startgold Preview (dynamisch)
        _, _, _, start_money_mult, start_gold_base = self.diffs[self.selected_diff]
        start_money = int(round(self.base_start_money * float(start_money_mult)))

        preview = self.small.render(
            f"Startgeld: {start_money}  (Basis {self.base_start_money} × {start_money_mult})",
            True,
            (200,200,200)
        )
        screen.blit(preview, (dx + dw + 30, dy + 8))

        # --- Start-Button unten rechts (Hover Highlight) ---
        if self.start_img is not None:
            sw, sh = screen.get_size()
            pad = 24
            self.start_rect = self.start_img.get_rect(bottomright=(sw - pad, sh - pad))

            hover = self.start_rect.collidepoint(mx, my)

            if hover:
                # Vollflächiges Highlight, aber flacher (weniger Höhe)
                glow = self.start_rect.inflate(10, 0)                  # etwas breiter
                glow = pygame.Rect(glow.x, glow.y, glow.w, max(2, self.start_rect.height - 50))
                glow.centery = self.start_rect.centery

                pygame.draw.rect(
                    screen,
                    (220, 200, 80),   # gelber Ton
                    glow,
                    border_radius=12
                )

            # Button immer zeichnen (auch ohne Hover)
            screen.blit(self.start_img, self.start_rect)
        else:
            self.start_rect = None


        # --- Back-Button unten mittig ---
        sw, sh = screen.get_size()
        mx, my = pygame.mouse.get_pos()
        pad = 24

        if self.back_img is not None:
            self.back_rect = self.back_img.get_rect(midbottom=(sw // 2, sh - pad))
            hover = self.back_rect.collidepoint(mx, my)

            # dezentes Hover (ohne Rahmen/Glow-Box)
            if hover:
                tint = pygame.Surface((self.back_rect.width, self.back_rect.height), pygame.SRCALPHA)
                tint.fill((255, 255, 255, 18))
                screen.blit(tint, self.back_rect.topleft)

            screen.blit(self.back_img, self.back_rect)
        else:
            # Fallback: Textbutton, falls kein Bild existiert
            label = self.small.render("Zurück", True, (240, 240, 240))
            bw = label.get_width() + 48
            bh = label.get_height() + 24
            self.back_rect = pygame.Rect(0, 0, bw, bh)
            self.back_rect.midbottom = (sw // 2, sh - pad)

            hover = self.back_rect.collidepoint(mx, my)
            pygame.draw.rect(screen, (45, 60, 85) if hover else (26, 32, 40), self.back_rect, border_radius=12)
            screen.blit(label, label.get_rect(center=self.back_rect.center))
