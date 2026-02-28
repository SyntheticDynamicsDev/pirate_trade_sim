import os
import pygame
from core.run_config import DIFFICULTY_PRESETS, DEFAULT_DIFFICULTY_ID
import json
from ui.video_background import VideoBackground


class CharacterSelectState:
    def on_enter(self):
        from core.ui_text import FontBank, TextStyle, render_text
        from settings import UI_FONT_PATH, UI_FONT_FALLBACK
        i18n = self.ctx.i18n

        self._fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)
        self.font = self._fonts.get(22)
        self.small = self._fonts.get(16)
        # Nur die ersten zwei Charaktere sind auswählbar
        self._enabled_char_count = 2

        # Fragezeichen-Font (für disabled Portraits)
        self.qmark_font = self._fonts.get(92)   # ggf. 80–110 anpassen
        # Charakterdefinition (später in JSON auslagern)
        self.chars = [
            {
                "id": "char_01",
                "name": "Seemann",
                "portrait": "Ruben.png",
                "start_ship_type_id": "sloop",
                "start_gold_bonus_mult": 0.90,   # +15% Startgold
                "start_gold_bonus_add":  -200,      # optional
                "trade_buy_mult": 0.95,   # -5% Einkaufspreis
                "trade_sell_mult": 1.00,  # +5% Verkaufspreis
                "attack_bonus_flat": 2,
                "armor_physical_bonus": 5.0,
                "armor_abyssal_bonus": 2.0,
            },
            {
                "id": "char_02",
                "name": "Händlerin",
                "portrait": "Lucy.png",
                "start_ship_type_id": "holk",
                "start_gold_bonus_mult": 1.15,   # -5% Startgold
                "start_gold_bonus_add":  200,    # dafür +150 fix (Beispiel)
                "trade_buy_mult": 0.90,   # -5% Einkaufspreis
                "trade_sell_mult": 1.15,  # +5% Verkaufspreis
                "attack_bonus_flat": -2,
                "armor_physical_bonus": -2.0,
                "armor_abyssal_bonus": 1.0,
            },
            {
                "id": "char_03",
                "name": "???",
                "portrait": "Carlo.png",
                "start_ship_type_id": "sloop",
                "start_gold_bonus_mult": 1.0,   # 0% Startgold
                "start_gold_bonus_add":  100,    # +100 Startgold flat
                "trade_buy_mult": 1.0,   # neutral
                "trade_sell_mult": 1.0,  # neutral
            },

            # --- Neue Charaktere ---
            {
                "id": "char_04",
                "name": "???",
                "portrait": "Miroso.png",
                "start_ship_type_id": "holk", 
                "start_gold_bonus_mult": 1.0,   # 0% Startgold
                "start_gold_bonus_add":  100,    # +100 Startgold flat
                "trade_buy_mult": 1.0,   # neutral
                "trade_sell_mult": 1.0,  # neutral
            },
            {
                "id": "char_05",
                "name": "???",
                "portrait": "Leyla.png",
                "start_ship_type_id": "sloop",
                "start_gold_bonus_mult": 1.0,   # 0% Startgold
                "start_gold_bonus_add":  100,    # +100 Startgold flat
                "trade_buy_mult": 1.0,   # neutral
                "trade_sell_mult": 1.0,  # neutral
            },
            {
                "id": "char_06",
                "name": "???",
                "portrait": "Gerhaldt.png",
                "buy_discount": 0.05,
                "start_ship_type_id": "sloop",
                "start_gold_bonus_mult": 1.0,   # 0% Startgold
                "start_gold_bonus_add":  100,    # +100 Startgold flat
                "trade_buy_mult": 1.0,   # neutral
                "trade_sell_mult": 1.0,  # neutral
            },
        ]

        # Nur die ersten zwei Charaktere sind auswählbar
        self._enabled_char_count = 2
        # Safety: falls selected später irgendwo rausläuft
        self.selected = 0
        # Safety clamp
        self.selected = max(0, min(self.selected, self._enabled_char_count - 1))

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
            enabled = getattr(self, "_enabled_char_count", len(self.chars))
            max_sel = max(0, enabled - 1)

            if event.key == pygame.K_LEFT:
                self.selected = max(0, self.selected - 1)
            elif event.key == pygame.K_RIGHT:
                self.selected = min(max_sel, self.selected + 1)
            elif event.key == pygame.K_UP:
                self.selected_diff = max(0, self.selected_diff - 1)
            elif event.key == pygame.K_DOWN:
                self.selected_diff = min(len(self.diffs) - 1, self.selected_diff + 1)
            elif event.key == pygame.K_RETURN:
                self._apply_and_start()
                return


        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            enabled = getattr(self, "_enabled_char_count", len(self.chars))

            for i, r in self.hitboxes:
                if not r.collidepoint(mx, my):
                    continue

                # nur wenn wirklich auf Slot geklickt wurde, dann prüfen ob disabled
                if i >= enabled:
                    return  # disabled Slot: nicht anwählbar

                self.selected = i
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

        # Difficulty anwenden (erst holen!)
        diff_id, price_spread_mult, event_freq_mult, start_money_mult, start_gold_base = self.diffs[self.selected_diff]
        rc.difficulty_id = diff_id
        rc.price_spread_mult = float(price_spread_mult)
        rc.event_freq_mult = float(event_freq_mult)
        rc.start_money_mult = float(start_money_mult)
        rc.start_gold_base = int(start_gold_base)

        # Charakter-Boni
        rc.start_gold_bonus_mult = float(c.get("start_gold_bonus_mult", 1.0))
        rc.start_gold_bonus_add  = int(c.get("start_gold_bonus_add", 0))
        rc.trade_buy_mult = float(c.get("trade_buy_mult", 1.0))
        rc.trade_sell_mult = float(c.get("trade_sell_mult", 1.0))

        #Schiff
        rc.start_ship_type_id = c.get("start_ship_type_id", "sloop")

        if getattr(self.ctx, "audio", None) is not None:
            self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.wav"))

        # Jetzt in dein bestehendes Setup / Spielstart
        from states.setup import NewGameSetupState
        st = NewGameSetupState()
        st.game = self.game
        st.ctx = self.ctx
        self.game.replace(st)

    def _draw_tooltip(self, screen, pos, lines, font=None):
        if not lines:
            return
        if font is None:
            font = self._fonts.get(16)

        sw, sh = screen.get_size()
        mx, my = pos
        pad = 10

        surfs = [font.render(str(t), True, (235, 235, 235)) for t in lines]
        w = max(s.get_width() for s in surfs) + pad * 2
        h = sum(s.get_height() for s in surfs) + pad * 2 + (len(surfs) - 1) * 4

        # oben-rechts relativ zur Maus
        x = mx + 16
        y = my - h - 16

        # Clamp im Screen
        if x + w > sw - 8:
            x = sw - w - 8
        if y < 8:
            # falls oben kein Platz: unter die Maus ausweichen
            y = my + 16
        if y + h > sh - 8:
            y = sh - h - 8

        x = max(8, x)
        y = max(8, y)

        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 190), panel.get_rect(), border_radius=10)
        pygame.draw.rect(panel, (220, 210, 180, 60), panel.get_rect(), 1, border_radius=10)
        screen.blit(panel, (x, y))

        yy = y + pad
        for s in surfs:
            screen.blit(s, (x + pad, yy))
            yy += s.get_height() + 4

    def _char_perks_tooltip_lines(self, char: dict) -> list[str]:
        # Difficulty-basierte Startgold-Berechnung (muss identisch zu Setup sein)
        diff_id, _, _, start_money_mult, start_gold_base = self.diffs[self.selected_diff]

        # Startgold-Char-Bonus
        gold_mult = float(char.get("start_gold_bonus_mult", 1.0))
        gold_add  = int(char.get("start_gold_bonus_add", 0))

        # Handel
        buy_mult  = float(char.get("trade_buy_mult", 1.0))
        sell_mult = float(char.get("trade_sell_mult", 1.0))

        # Kampf (deine neuen Felder, defaults safe)
        atk_flat = int(char.get("attack_bonus_flat", 0))
        armor_p  = float(char.get("armor_physical_bonus", 0.0))
        armor_a  = float(char.get("armor_abyssal_bonus", 0.0))

        # Final Startgold (Preview)
        start_money = int(round(int(start_gold_base) * float(start_money_mult) * gold_mult)) + gold_add
        start_money = max(0, start_money)

        def fmt_int(n: int) -> str:
            return f"{int(n):,}".replace(",", ".")

        def pct_from_mult(m: float, inverse: bool = False) -> int:
            # inverse=True => buy_mult <1 ist gut (zeigt als "+% günstiger")
            if m <= 0:
                return 0
            if inverse:
                # 0.95 => +5% günstiger
                return int(round((1.0 / m - 1.0) * 100))
            return int(round((m - 1.0) * 100))

        buy_pct  = pct_from_mult(buy_mult, inverse=True)
        sell_pct = pct_from_mult(sell_mult, inverse=False)

        i18n = self.ctx.i18n

        # name i18n: use selected index mapping if possible
        try:
            idx = self.chars.index(char)
            display_name = i18n.t(f"char.name.{idx}")
        except Exception:
            display_name = str(char.get("name", "CHARACTER"))

        lines = [
            i18n.t("char.perks.title", name=display_name),
            "",
            i18n.t("char.perks.gold", money=fmt_int(start_money)),
        ]

        # Gold-Details nur wenn tatsächlich vorhanden
        if abs(gold_mult - 1.0) > 1e-6 or gold_add != 0:
            gm = int(round((gold_mult - 1.0) * 100))
            parts = []
            if gm != 0:
                parts.append(f"{gm:+d}%")
            if gold_add != 0:
                parts.append(f"{gold_add:+d}")
            bonus_parts = " ".join(parts).replace("+", "+")
            lines.append("   " + i18n.t("char.perks.bonus", parts=bonus_parts))

        # Handel
        if buy_pct != 0 or sell_pct != 0:
            buy_s  = f"{buy_pct:+d}"
            sell_s = f"{sell_pct:+d}"
            lines.append(i18n.t("char.perks.trade", buy=buy_s, sell=sell_s))
        else:
            lines.append(i18n.t("char.perks.trade.none"))

        # Angriff / Verteidigung
        if atk_flat != 0 or armor_p != 0.0 or armor_a != 0.0:
            if atk_flat != 0:
                lines.append(i18n.t("char.perks.attack", value=f"{atk_flat:+d}"))
            else:
                lines.append(i18n.t("char.perks.attack.none"))

            v_parts = []
            if armor_p != 0.0:
                v_parts.append(f"Phys {armor_p:+.0f}")
            if armor_a != 0.0:
                v_parts.append(f"Abyss {armor_a:+.0f}")

            if v_parts:
                lines.append(i18n.t("char.perks.defense", value=" | ".join(v_parts)))
            else:
                lines.append(i18n.t("char.perks.defense.none"))
        else:
            lines.append(i18n.t("char.perks.attack.none"))
            lines.append(i18n.t("char.perks.defense.none"))

        return lines

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

        # --- Character block horizontal centering ---
        sw, sh = screen.get_size()

        portrait_w = 140
        gap = 24
        count = len(self.chars)

        block_w = count * portrait_w + (count - 1) * gap

        # --- Zentrales Schiff-Preview (abhängig vom ausgewählten Charakter) ---
        selected_char = self.chars[self.selected]
        ship_type_id = selected_char.get("start_ship_type_id", "sloop")
        ship_img = self.ship_previews.get(ship_type_id)

        pad = 24
        sw, sh = screen.get_size()

        # Panel größer, weil Stats jetzt rechts neben dem Schiff stehen
        panel_w = 470
        panel_h = 260

        # neben dem Difficulty-Block platzieren (dessen dx/dy sind 60/460)
        dx = 60
        dy = 460
        dw = 220  # difficulty width

        px = dx + dw + 190   # weiter rechts, damit Startgeld-Preview nicht reinragt
        py = dy - 20        # leicht nach oben, wirkt mittiger

        panel_rect = pygame.Rect(px, py, panel_w, panel_h)
        # --- Panel background with rounded corners (no white outline) ---
        panel_bg = pygame.Surface((panel_rect.w, panel_rect.h), pygame.SRCALPHA)

        # transparenter Hintergrund der Surface, dann abgerundetes Rect zeichnen
        panel_bg.fill((0, 0, 0, 0))
        pygame.draw.rect(
            panel_bg,
            (0, 0, 0, 170),   # schwarz + alpha
            panel_bg.get_rect(),
            border_radius=16  # runde Ecken
        )

        screen.blit(panel_bg, panel_rect.topleft)


        #--- Schiff-Name + Stats im Panel ---
        ship_label = self.ship_type_to_name.get(ship_type_id, ship_type_id)
        i18n = self.ctx.i18n
        ship_title = self.small.render(i18n.t("char.ship_panel.title"), True, (220, 220, 220))
        ship_name = self.small.render(ship_label, True, (240, 240, 240))

        # --- Layout im Panel: links Schiff, rechts Stats ---
        inner_pad = 12
        left_w = 190
        left_rect = pygame.Rect(panel_rect.x + inner_pad, panel_rect.y + inner_pad, left_w, panel_rect.h - 2 * inner_pad)
        right_rect = pygame.Rect(left_rect.right + 12, panel_rect.y + inner_pad,
                                panel_rect.right - (left_rect.right + 12) - inner_pad,
                                panel_rect.h - 2 * inner_pad)
        

        # Titel/Name links oben
        screen.blit(ship_title, ship_title.get_rect(midtop=(left_rect.centerx, left_rect.top + 0)))
        screen.blit(ship_name,  ship_name.get_rect(midtop=(left_rect.centerx, left_rect.top + 22)))

        # Schiffbild links (mittig im linken Bereich)
        if ship_img is not None:
            img_rect = ship_img.get_rect(center=(left_rect.centerx, left_rect.centery + 12))
            screen.blit(ship_img, img_rect)

        ship_def = self.ship_defs.get(ship_type_id, {})

        # --- base stats ---
        cap = ship_def.get("capacity_tons")
        spd = ship_def.get("speed_px_s")
        crew_max = ship_def.get("crew_max")
        crew_req = ship_def.get("crew_required")
        cannons = ship_def.get("cannon_slots")

        # --- combat stats ---
        combat = ship_def.get("combat", {})

        hp_max = combat.get("hp_max")
        armor_phys = combat.get("armor_physical")
        armor_abyss = combat.get("armor_abyssal")

        dmg_min = combat.get("damage_min")
        dmg_max = combat.get("damage_max")

        initiative = combat.get("initiative_base")
        threat = combat.get("threat_level")


        cap_txt = f"{cap:.0f} t" if isinstance(cap, (int, float)) else "-"
        spd_txt = f"{spd:.0f} m/s" if isinstance(spd, (int, float)) else "-"
        hp_txt  = f"{hp_max:.0f}" if isinstance(hp_max, (int, float)) else "-"
        dmg_txt = f"{dmg_min}–{dmg_max}" if isinstance(dmg_min, int) and isinstance(dmg_max, int) else "-"
        armor_txt = f"{armor_phys:.0f}" if isinstance(armor_phys, (int, float)) else "-"
        cannon_txt = f"{cannons}" if isinstance(cannons, int) else "-"

        i18n = self.ctx.i18n
        lines = [
            i18n.t("char.ship.stat.capacity", value=cap_txt),
            i18n.t("char.ship.stat.speed", value=spd_txt),
            i18n.t("char.ship.stat.hp", value=hp_txt),
            i18n.t("char.ship.stat.armor", value=armor_txt),
            i18n.t("char.ship.stat.cannons", value=cannon_txt),
            i18n.t("char.ship.stat.damage", value=dmg_txt),
        ]


        # rechts vertikal zentrieren (wirkt sauber)
        line_h = 24
        total_h = len(lines) * line_h
        start_y = right_rect.centery - total_h // 2

        for idx, text in enumerate(lines):
            surf = self.small.render(text, True, (220, 220, 220))
            screen.blit(surf, (right_rect.x, start_y + idx * line_h))

        # --- Difficulty UI ---
        self.diff_hitboxes = []
        # --- Difficulty block layout ---
        dx = 140          # weiter nach rechts (vorher 60)
        dy = 460

        dw, dh = 110, 46  # halb so breit
        dgap = 12


        i18n = self.ctx.i18n
        diff_title = self.small.render(i18n.t("char.difficulty"), True, (220, 220, 220))
        screen.blit(diff_title, (dx, dy - 28))

        for i, d in enumerate(self.diffs):
            diff_id = d[0]
            r = pygame.Rect(dx, dy + i * (dh + dgap), dw, dh)
            self.diff_hitboxes.append((i, r))

            is_sel = (i == self.selected_diff)

            btn_bg = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            btn_bg.fill((0, 0, 0, 0))

            # etwas dunkler wenn selected
            alpha = 170 if is_sel else 120

            pygame.draw.rect(
                btn_bg,
                (0, 0, 0, alpha),
                btn_bg.get_rect(),
                border_radius=10
            )

            screen.blit(btn_bg, r.topleft)


            label = diff_id
            txt = self.small.render(label, True, (240, 240, 240))
            screen.blit(txt, txt.get_rect(center=r.center))


        # Startgold Preview (dynamisch)
        c = self.chars[self.selected]
        _, _, _, start_money_mult, start_gold_base = self.diffs[self.selected_diff]
        char_mult = float(c.get("start_gold_bonus_mult", 1.0))
        char_add  = int(c.get("start_gold_bonus_add", 0))

        start_money = int(round(int(start_gold_base) * float(start_money_mult) * char_mult)) + char_add
        start_money = max(0, start_money)

        i18n = self.ctx.i18n
        money_str = f"{start_money:,}".replace(",", ".")
        preview = self.small.render(
            i18n.t("char.start_money", money=money_str),
            True,
            (200, 200, 200)
        )
        screen.blit(preview, (dx + dw + 30, dy + 8))

        # --- Start-Button unten rechts (Hover Highlight) ---
        if self.start_img is not None:
            sw, sh = screen.get_size()
            pad = 24
            self.start_rect = self.start_img.get_rect(bottomright=(sw - pad, sh - pad))

            hover = self.start_rect.collidepoint(mx, my)

            # Button immer zeichnen (auch ohne Hover)
            screen.blit(self.start_img, self.start_rect)
        else:
            self.start_rect = None


        # --- Back-Button unten mittig ---
        sw, sh = screen.get_size()
        mx, my = pygame.mouse.get_pos()
        pad = 24

        if self.back_img is not None:
            # Back direkt über Start platzieren (orientiert an start_rect)
            if self.start_rect is not None:
                # gleiche rechte Kante wie Start, aber darüber
                self.back_rect = self.back_img.get_rect(midbottom=(self.start_rect.centerx, self.start_rect.top - 10))
            else:
                # Fallback: bisheriges Verhalten
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
            label = self.small.render(self.ctx.i18n.t("char.btn.back_fallback"), True, (240, 240, 240))
            bw = label.get_width() + 48
            bh = label.get_height() + 24
            self.back_rect = pygame.Rect(0, 0, bw, bh)
            self.back_rect.midbottom = (sw // 2, sh - pad)

            hover = self.back_rect.collidepoint(mx, my)
            pygame.draw.rect(screen, (45, 60, 85) if hover else (26, 32, 40), self.back_rect, border_radius=12)
            screen.blit(label, label.get_rect(center=self.back_rect.center))


        # exakt horizontal zentrieren
        x0 = (sw - block_w) // 2

        # optional: bewusster Feinschub nach rechts (Design-Offset)
        x0 += 0   # <- kannst du jederzeit anpassen / auch 0 setzen

        y0 = 220

        enabled = getattr(self, "_enabled_char_count", len(self.chars))

        hovered_char = None
        for i, c in enumerate(self.chars):
            x = x0 + i * (140 + gap)
            y = y0
            r = pygame.Rect(x, y, 140, 140)
            self.hitboxes.append((i, r))

            enabled = getattr(self, "_enabled_char_count", len(self.chars))
            is_disabled = (i >= enabled)

            hover = (not is_disabled) and r.collidepoint(mx, my)
            if hover and not is_disabled:
                hovered_char = i
            # Highlight nur für aktive Slots
            if i == self.selected or hover:
                highlight_rect = pygame.Rect(x - 8, y - 8, 156, 200)
                hl = pygame.Surface((highlight_rect.w, highlight_rect.h), pygame.SRCALPHA)
                hl.fill((0, 0, 0, 0))
                pygame.draw.rect(hl, (0, 0, 0, 150), hl.get_rect(), border_radius=14)
                screen.blit(hl, highlight_rect.topleft)
            

            # Portrait/Placeholder zeichnen
            if not is_disabled:
                screen.blit(self.portraits[i], (x, y))
            else:
                # optional: original portrait NICHT zeichnen -> komplett schwarz
                # screen.blit(self.portraits[i], (x, y))

                # schwarzes Overlay (leicht transparent, wirkt "locked")
                ov = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                ov.fill((0, 0, 0, 230))  # Alpha anpassen (200–255)
                screen.blit(ov, r.topleft)

                # Fragezeichen zentriert
                q = self.qmark_font.render("?", True, (235, 235, 235))
                q_rect = q.get_rect(center=r.center)
                screen.blit(q, q_rect)

            # Name (i18n; disabled gedimmt)
            i18n = self.ctx.i18n
            name_col = (240, 240, 240) if not is_disabled else (150, 150, 150)

            # use stable slot index for name mapping
            name_key = f"char.name.{i}"
            display_name = i18n.t(name_key)

            name = self.small.render(display_name, True, name_col)
            name_rect = name.get_rect(midtop=(r.centerx, y + 150))
            screen.blit(name, name_rect)

            # --- Hover Tooltip: Character Perks ---
            if hovered_char is not None:
                mx, my = pygame.mouse.get_pos()
                c = self.chars[hovered_char]
                tip = self._char_perks_tooltip_lines(c)
                self._draw_tooltip(screen, (mx, my), tip, font=self._fonts.get(16))