from __future__ import annotations
import pygame
import os
from dataclasses import dataclass
from typing import Optional

from settings import TIME_SCALE_PAUSE, TIME_SCALE_1X, TIME_SCALE_2X, TIME_SCALE_4X

@dataclass
class CityState:
    city_id: str
    game = None
    ctx = None
    font: Optional[pygame.font.Font] = None
    selected_idx: int = 0
    trade_qty_tons: float = 5.0
    message: str = ""

    # UI-Cache (wird in render() gesetzt, in handle_event() benutzt)
    row_trade_btns: dict = None  # gid -> {"buy": Rect, "sell": Rect}
    row_fav_btns: dict = None  # gid -> Rect
    btn_buy: pygame.Rect = None
    btn_sell: pygame.Rect = None
    btn_minus: pygame.Rect = None
    btn_plus: pygame.Rect = None
    btn_lot: pygame.Rect = None
    btn_max: pygame.Rect = None

    # UI
    row_hitboxes: list = None
    scroll_offset: int = 0
    _hold_trade: dict = None  # {"gid": str, "side": "buy"/"sell", "t0": int, "next": int}


    # Kategorie-Filter (on/off)
    enabled_categories: set = None
    cat_buttons: dict = None  # category -> Rect



    # Icons cache
    icons: dict = None  # good_id -> Surface


    def on_enter(self) -> None:
        # Zeit in Stadtansicht verlangsamt
        self.ctx.clock.time_scale = TIME_SCALE_PAUSE

        # kompaktere Schrift
        self.font = pygame.font.SysFont("arial", 18)
        self.font_small = pygame.font.SysFont("arial", 16)
        self.font_title = pygame.font.SysFont("arial", 34)

        # --- Session-Persistenz für Trade-UI ---
        if not hasattr(self.ctx, "trade_ui_state") or self.ctx.trade_ui_state is None:
            self.ctx.trade_ui_state = {}

        # Keys sicherstellen (auch wenn trade_ui_state schon existiert)
        self.ctx.trade_ui_state.setdefault("favorite_goods", set())
        self.ctx.trade_ui_state.setdefault("enabled_categories", None)
        self.ctx.trade_ui_state.setdefault("avg_cost", {})  # Einstandspreis (WAC)
        self.ctx.trade_ui_state.setdefault("selected_lot_tons", 1)
        self.trade_qty_tons = float(self.ctx.trade_ui_state["selected_lot_tons"])

        # Favoriten-Set als zentrale Quelle
        self.ctx.favorite_goods = self.ctx.trade_ui_state["favorite_goods"]

        # Kategorien übernehmen (oder default setzen)
        if self.ctx.trade_ui_state["enabled_categories"] is None:
            cats = sorted({g.category for g in self.ctx.content.goods.values()})
            self.enabled_categories = set(["__fav__"] + cats)  # falls FAV default aktiv sein soll
        else:
            self.enabled_categories = set(self.ctx.trade_ui_state["enabled_categories"])

        # Favoriten (Session-weit, kein Save/Load)
        if not hasattr(self.ctx, "favorite_goods") or self.ctx.favorite_goods is None:
            self.ctx.favorite_goods = set()  # set[str] good_id

        # Kategorien initial: alle an
        if self.enabled_categories is None:
            self.enabled_categories = {g.category for g in self.ctx.content.goods.values()}

        # Icons laden
        self.icons = {}
        icons_dir = os.path.join("assets", "icons")
        for gid in self.ctx.content.goods.keys():
            path = os.path.join(icons_dir, f"{gid}.png")
            if os.path.exists(path):
                img = pygame.image.load(path).convert_alpha()
                ICON_SIZE = 32  # oder 36, wenn du noch größer willst
                img = pygame.transform.scale(img, (ICON_SIZE, ICON_SIZE))  # scharf (nearest)

                self.icons[gid] = img

        # UI Button-Sprites laden + Ausschnitten
        ui_dir = os.path.join("assets", "ui")

        btn_raw = pygame.image.load(os.path.join(ui_dir, "button.png")).convert_alpha()
        btn_hi_raw = pygame.image.load(os.path.join(ui_dir, "button_high.png")).convert_alpha()
        # neu:
        btn_not_raw = pygame.image.load(os.path.join(ui_dir, "button_not.png")).convert_alpha()
        cross_raw   = pygame.image.load(os.path.join(ui_dir, "crossed.png")).convert_alpha()

        #Handelsmenühintergrund
        self.trade_bg = pygame.image.load(
            os.path.join(ui_dir, "trade_menu.png")
        ).convert_alpha()

        # (dein fester Zuschnitt bleibt wie gehabt)
        bw, bh = 900, 220
        x0 = (btn_raw.get_width() - bw) // 2
        y0 = (btn_raw.get_height() - bh) // 2
        btn_rect = pygame.Rect(x0, y0, bw, bh)

        self.ui_btn      = btn_raw.subsurface(btn_rect).copy()
        self.ui_btn_hi   = btn_hi_raw.subsurface(btn_rect).copy()
        self.ui_btn_not  = btn_not_raw.subsurface(btn_rect).copy()

        # crossed ggf. nicht gleich groß -> wir croppen NICHT, wir skalieren später auf Button-Größe
        self.ui_cross = cross_raw

        # caches
        self._ui_btn_cache = {}       # (w,h,variant) -> Surface
        self._ui_cross_cache = {}     # (w,h) -> Surface

        self.star_empty = pygame.image.load(os.path.join(ui_dir, "star_empty.png")).convert_alpha()
        self.star_filled = pygame.image.load(os.path.join(ui_dir, "star_filled.png")).convert_alpha()

        STAR_SIZE = 48  # optional 18, je nach Look
        self.star_empty = pygame.transform.scale(self.star_empty, (STAR_SIZE, STAR_SIZE))
        self.star_filled = pygame.transform.scale(self.star_filled, (STAR_SIZE, STAR_SIZE))
        self._star_size = STAR_SIZE

        # Pressed-State + Cache
        self._pressed_trade_btn = None
        self._ui_btn_cache = {}


    def on_exit(self) -> None:
        ...

    def handle_event(self, event) -> None:

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.ctx.player.docked_city_id = None
                from states.world import WorldMapState  # local import
                st = WorldMapState()
                self.game.replace(st)
                self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))

            elif event.key == pygame.K_SPACE:
                self.ctx.clock.paused = not self.ctx.clock.paused

            elif event.key == pygame.K_TAB:
                if self.ctx.clock.time_scale != TIME_SCALE_1X:
                    self.ctx.clock.time_scale = TIME_SCALE_1X
                else:
                    self.ctx.clock.time_scale = TIME_SCALE_PAUSE

        # --- Maus: Klicks für Auswahl + Kaufen/Verkaufen + Menge ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._pressed_trade_btn = None

            # Lot-Buttons (1t/5t/10t)
            if hasattr(self, "lot_buttons") and self.lot_buttons:
                for val, r in self.lot_buttons.items():
                    if r.collidepoint(mx, my):
                        self.trade_qty_tons = float(val)
                        self.ctx.trade_ui_state["selected_lot_tons"] = int(val)
                        self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                        return

            # 0) Favoriten togglen (prioritär vor Buy/Sell)
            if getattr(self, "row_fav_btns", None):
                for gid, r in self.row_fav_btns.items():
                    if r.collidepoint(mx, my):
                        fav = self.ctx.favorite_goods
                        if gid in fav:
                            fav.remove(gid)
                        else:
                            fav.add(gid)
                        self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                        self.ctx.trade_ui_state["favorite_goods"] = self.ctx.favorite_goods
                        return
                    
            # Pressed-State für Buttons setzen (nur optisch)
            self._pressed_trade_btn = None
            if getattr(self, "row_trade_btns", None):
                for gid, btns in self.row_trade_btns.items():
                    if btns["buy"].collidepoint(mx, my):
                        self._pressed_trade_btn = (gid, "buy")
                        break
                    if btns["sell"].collidepoint(mx, my):
                        self._pressed_trade_btn = (gid, "sell")
                        break

            # A0) One-click Buy/Sell pro Zeile: NUR _trade_once + Hold starten (kein Inline-Trade)
            if getattr(self, "row_trade_btns", None):
                for gid, btns in self.row_trade_btns.items():
                    side = None
                    if btns["buy"].collidepoint(mx, my):
                        side = "buy"
                    elif btns["sell"].collidepoint(mx, my):
                        side = "sell"

                    if side is None:
                        continue

                    now = pygame.time.get_ticks()
                    self._hold_trade = {"gid": gid, "side": side, "t0": now, "next": now + 350}
                    self._pressed_trade_btn = (gid, side)

                    self._trade_once(gid, side)
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                    return


            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._hold_trade = None
                self._pressed_trade_btn = None
                            
            # A) ZUERST Kategorie-Buttons togglen (sonst "verschluckt" die Tabelle den Klick)
            if self.cat_buttons:
                for cat, rect in self.cat_buttons.items():
                    if rect.collidepoint(mx, my):
                        if cat in self.enabled_categories:
                            self.enabled_categories.remove(cat)
                            self.ctx.trade_ui_state["enabled_categories"] = set(self.enabled_categories)
                            self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                        else:
                            self.enabled_categories.add(cat)
                            self.ctx.trade_ui_state["enabled_categories"] = set(self.enabled_categories)
                            self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                        self.scroll_offset = 0
                        return

            # B) DANN Tabellenzeile auswählen
            if self.row_hitboxes:
                for idx, r in self.row_hitboxes:
                    if r.collidepoint(mx, my):
                        self.selected_idx = idx
                        return

            # C) Next Day Button (ganz rechts oben)
            if hasattr(self, "btn_next_day") and self.btn_next_day and self.btn_next_day.collidepoint(mx, my):
                # Tag vorspulen
                if hasattr(self.ctx.clock, "force_next_day"):
                    self.ctx.clock.force_next_day(start_hour=8)

                # Märkte/Needs sofort aktualisieren
                from core.day_update import on_new_day
                on_new_day(self.ctx)

                self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                self.message = "Neuer Tag begonnen."
                return


        if event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()

            # Wenn Maus über Tabelle -> scroll Liste
            if hasattr(self, "table_panel") and self.table_panel and self.table_panel.collidepoint(mx, my):
                self.scroll_offset = max(0, self.scroll_offset - event.y)  # wheel up -> -1 => scroll up
                return

            # Sonst Menge ändern
            self.trade_qty_tons = max(1.0, min(999.0, self.trade_qty_tons + event.y))


    def _get_goods_sorted(self):
        FAV_CAT = "__fav__"

        goods_all = sorted(self.ctx.content.goods.values(), key=lambda gg: (gg.category, gg.base_price))
        if not self.enabled_categories:
            return []

        fav_on = (FAV_CAT in self.enabled_categories)
        fav_set = getattr(self.ctx, "favorite_goods", set())

        out = []
        for g in goods_all:
            # Favoriten immer rein, wenn FAV aktiviert ist
            if fav_on and g.id in fav_set:
                out.append(g)
                continue
            # Normale Kategorien
            if g.category in self.enabled_categories:
                out.append(g)

        # Optional: Favoriten nach oben sortieren, wenn FAV aktiviert ist
        if fav_on and fav_set:
            out.sort(key=lambda gg: (0 if gg.id in fav_set else 1, gg.category, gg.base_price))

        return out


    def _get_city_type(self):
        cdef = self.ctx.content.cities[self.city_id]
        return self.ctx.content.city_types[cdef.city_type_id]

    def _get_city_lot_size(self) -> float:
        ctype = self._get_city_type()
        return float(getattr(ctype, "lot_size_tons", 5.0))
    
    def _wac_add(self, gid: str, qty: float, price_per_ton: float) -> None:
        """Weighted Average Cost: add qty at price_per_ton."""
        if qty <= 0:
            return
        avg_map = self.ctx.trade_ui_state.setdefault("avg_cost", {})
        old_avg = float(avg_map.get(gid, 0.0))
        old_qty = float(self.ctx.player.cargo.tons_by_good().get(gid, 0.0)) - float(qty)  # qty ist schon hinzugefügt
        if old_qty < 0:
            old_qty = 0.0
        new_qty = old_qty + qty
        if new_qty <= 0:
            return
        new_avg = (old_avg * old_qty + float(price_per_ton) * qty) / new_qty
        avg_map[gid] = new_avg

    def _wac_remove(self, gid: str) -> None:
        """Wenn Ware auf 0 fällt, Einstandspreis löschen."""
        avg_map = self.ctx.trade_ui_state.setdefault("avg_cost", {})
        if float(self.ctx.player.cargo.tons_by_good().get(gid, 0.0)) <= 0.001:
            avg_map.pop(gid, None)

    def _compute_max_trade_qty(self) -> float:
        goods_sorted = self._get_goods_sorted()
        if not goods_sorted:
            return 1.0
        self.selected_idx = max(0, min(self.selected_idx, len(goods_sorted) - 1))
        g = goods_sorted[self.selected_idx]

        market = self.ctx.markets[self.city_id]
        player = self.ctx.player
        free = max(0.0, player.ship.capacity_tons - player.cargo.total_tons())
        available_market = max(0.0, market.stock.get(g.id, 0.0))
        owned = max(0.0, player.cargo.tons_by_good().get(g.id, 0.0))

        # Heuristik: wenn Marktbestand vorhanden und genug Geld, dann "buy max" = min(free, available_market)
        # (Geldlimit lassen wir erstmal weg; MAX soll nur eine sinnvolle Obergrenze setzen)
        return max(1.0, min(free, available_market, 999.0)) if free > 0 else max(1.0, min(owned, 999.0))

    def _execute_trade(self, mode: str) -> None:
        goods_sorted = self._get_goods_sorted()
        if not goods_sorted:
            return

        self.selected_idx = max(0, min(self.selected_idx, len(goods_sorted) - 1))
        g = goods_sorted[self.selected_idx]

        market = self.ctx.markets[self.city_id]
        ctype = self._get_city_type()
        need = ctype.needs.get(g.category, "normal")

        target = g.target_stock * self.ctx.economy.NEED_TARGET_MULT.get(need, 1.0)

        lot_size = float(ctype.lot_size_tons)
        qty = float(self.trade_qty_tons)

        # Sofortreaktion (Mechanik 2)
        immediate_pct = {"small": 0.60, "medium": 0.40, "large": 0.25}.get(ctype.market_size, 0.40)

        def apply_immediate_price_stock(gid: str) -> None:
            stock = market.stock.get(gid, 0.0)
            ps = market.price_stock.get(gid, stock)
            ps = ps + immediate_pct * (stock - ps)
            market.price_stock[gid] = max(0.0, round(ps, 3))

        if mode == "buy":
            self._buy_good(g, market, need, target, lot_size, qty, apply_immediate_price_stock)
        else:
            self._sell_good(g, market, need, target, lot_size, qty, apply_immediate_price_stock)

        from core.day_update import _update_top_needs
        _update_top_needs(self.ctx)

    def update(self, dt: float) -> None:
        ...

    def render(self, screen) -> None:
        # --- Safety: Fonts anlegen, falls on_enter sie nicht gesetzt hat ---
        if not hasattr(self, "font") or self.font is None:
            self.font = pygame.font.SysFont("arial", 18)
        if not hasattr(self, "font_small") or self.font_small is None:
            self.font_small = pygame.font.SysFont("arial", 16)
        if not hasattr(self, "font_title") or self.font_title is None:
            self.font_title = pygame.font.SysFont("arial", 34)

        # --- Hintergrund ---
        screen.fill((12, 14, 18))

        # --- Layout Konstanten (zentral!) ---
        CAT_W   = 140
        GAP     = 16

        TABLE_W = 410
        TABLE_H = 540

        CARGO_W = 220
        CARGO_H = 540

        # --- City holen ---
        world = self.ctx.world
        player = self.ctx.player
        city = next(c for c in world.cities if c.id == self.city_id)

        # --- Spalten kompakt (keine leeren Bereiche) ---
        X_MARKET = 34
        X_SELL   = 90
        X_ICON   = 165
        X_BUY    = 220
        X_OWN    = 300

        BUY_W  = 60
        SELL_W = 60

        ICON_SIZE = 32   # quadratisch, sauber

        # --- Layout constants (kompakt) ---
        x0 = 30
        title_y = 18
        hud_y = 60
        bar_y = 90
        cat_y = 140
        table_y = 175

        # --- Title ---
        title = self.font_title.render(f"{city.name} – Stadtansicht", True, (240, 240, 240))
        screen.blit(title, (x0, title_y))

        # --- HUD (GANZE ZAHLEN) ---
        cargo_used = player.cargo.total_tons()
        cargo_cap = player.ship.capacity_tons

        cargo_used_i = int(round(cargo_used))
        cargo_cap_i = int(round(cargo_cap))
        qty_i = int(round(self.trade_qty_tons))

        day = getattr(self.ctx.clock, "day", 1)

        hud = self.font.render(
            f"Tag: {day} | Geld: {player.money}",
            True,
            (220, 220, 220)
        )


        screen.blit(hud, (x0, hud_y))

        # Message
        if getattr(self, "message", ""):
            screen.blit(self.font.render(self.message, True, (240, 210, 140)), (x0, hud_y + 22))

        # --- Control Bar (Buttons) ---
        total_w = CAT_W + GAP + TABLE_W + GAP + CARGO_W
        bar = pygame.Rect(x0, bar_y, total_w, 42)

        # Menge-Label (GANZE ZAHL)
        qty_label = self.font_small.render(f"{qty_i} t", True, (230, 230, 230))
        screen.blit(qty_label, (bar.left + 315, bar.top + 11))

        # --- Kategorie-Toggles (On/Off) ---
        if self.enabled_categories is None:
            self.enabled_categories = {g.category for g in self.ctx.content.goods.values()}

        FAV_CAT = "__fav__"
        cats = sorted({g.category for g in self.ctx.content.goods.values()})
        cats = [FAV_CAT] + cats  # Favoriten ganz oben

        self.cat_buttons = {}

        # Buttons im gleichen Look wie Trade-Buttons (parchment)
        bx = x0 + 10
        by = table_y + 12
        btn_h = 28
        btn_w = CAT_W - 20
        step = 34

        for cat in cats:
            label = "FAV" if cat == FAV_CAT else cat.upper()
            r = pygame.Rect(bx, by, btn_w, btn_h)
            self.cat_buttons[cat] = r

            enabled = (cat in self.enabled_categories)

            # aktiv: normal button
            # deaktiviert: button_not + crossed overlay
            if enabled:
                self._draw_ui_button(screen, r, label, variant="normal")
            else:
                self._draw_ui_button(screen, r, label, variant="not")

                # crossed overlay skalieren/cachen
                ck = (r.w, r.h)
                if ck in self._ui_cross_cache:
                    cross_surf = self._ui_cross_cache[ck]
                else:
                    cross_surf = pygame.transform.smoothscale(self.ui_cross, (r.w, r.h))
                    self._ui_cross_cache[ck] = cross_surf

                screen.blit(cross_surf, r.topleft)

            by += step
            if by + btn_h > table_y + TABLE_H - 10:
                break

        # --- Lot Buttons: 1t / 5t / 10t (unter Kategorien) ---
        lot_y = by + 12
        lot_h = 26
        gap_x = 6
        lot_w = (btn_w - 2 * gap_x) // 3  # 3 Buttons

        self.lot_buttons = {}  # val -> Rect

        lots = [(1, "1t"), (5, "5t"), (10, "10t")]
        x = bx
        for val, label in lots:
            r = pygame.Rect(x, lot_y, lot_w, lot_h)
            self.lot_buttons[val] = r

            selected = int(round(self.trade_qty_tons))

            is_active = (val == selected)

            if is_active:
                # aktiver Lot: normal (oder hi, wenn du es lieber „gedrückt“ willst)
                self._draw_ui_button(screen, r, label, variant="normal")
            else:
                # inaktiv: disabled look + durchgestrichen
                self._draw_ui_button(screen, r, label, variant="not")

                # crossed overlay (wie bei Kategorien)
                ck = (r.w, r.h)
                if ck in self._ui_cross_cache:
                    cross_surf = self._ui_cross_cache[ck]
                else:
                    cross_surf = pygame.transform.smoothscale(self.ui_cross, (r.w, r.h))
                    self._ui_cross_cache[ck] = cross_surf

                screen.blit(cross_surf, r.topleft)


            x += lot_w + gap_x

                
        # A2) One-click Buy/Sell pro Zeile
        if getattr(self, "row_trade_btns", None):
            goods_by_id = self.ctx.content.goods
            market = self.ctx.markets[self.city_id]
            ctype = self._get_city_type()

        # --- Markt Tabelle (kompakt + Icons + Scroll) ---
        market = self.ctx.markets[self.city_id]
        cdef = self.ctx.content.cities[self.city_id]
        ctype = self.ctx.content.city_types[cdef.city_type_id]

        #Cago-Panel zeichnen

        cargo_x = x0 + CAT_W + GAP + TABLE_W + GAP + 20
        cargo_panel = pygame.Rect(
            cargo_x,
            table_y,
            CARGO_W,
            CARGO_H
        )
        table_x = x0 + CAT_W + GAP
        self.table_panel = pygame.Rect(table_x, table_y, TABLE_W, TABLE_H)

        # Handelsmenü Hintergrundbild
        panel = self.table_panel
        # --- Content zentriert im Trade-Panel (Holzplanken) ---
        # Breite der "Tabellen-Inhalte" (inkl. Sternspalte links)
        STAR_W = 22          # Breite der Stern-/Favoritenspalte
        LEFT_PAD = 8
        RIGHT_PAD = 8

        # Buttons/Icons Breiten müssen zu deinen aktuellen Werten passen:
        SELL_W = 60
        BUY_W  = 60
        ICON_SIZE = 32

        # Spaltenabstände (in Content-Koordinaten)
        X_STAR   = 0
        X_MARKET = X_STAR + STAR_W + 10
        X_SELL   = X_MARKET + 52
        X_ICON   = X_SELL + SELL_W + 18
        X_BUY    = X_ICON + ICON_SIZE + 18
        X_OWN    = X_BUY + BUY_W + 18

        CONTENT_W = X_OWN + 90  # genug Platz für "Du" + (Ø) etc.

        content_x0 = panel.left + (panel.width - (CONTENT_W + LEFT_PAD + RIGHT_PAD)) // 2 + LEFT_PAD
        # trade_menu: leicht reinzoomen und am unteren Rand ausrichten
        SCALE = 1.22  # 1.05..1.20 je nach Geschmack
        sw = int(panel.width * SCALE)
        sh = int(panel.height * SCALE)

        bg = pygame.transform.smoothscale(self.trade_bg, (sw, sh))

        # X zentriert, Y am unteren Rand "geankert"
        bx = panel.centerx - sw // 2
        by = panel.bottom - sh + 50   # dadurch sieht man unten mehr

        old_clip = screen.get_clip()
        screen.set_clip(panel)
        screen.blit(bg, (bx, by))
        screen.set_clip(old_clip)


        # Header
        hdr = self.font_small
        screen.blit(hdr.render(" ", True, (220, 220, 220)), (panel.left + 12, panel.top + 10))
        screen.blit(hdr.render("Markt", True, (220, 220, 220)), (content_x0 + X_MARKET, panel.top + 10))
        screen.blit(hdr.render("Verkaufen", True, (220, 220, 220)), (content_x0 + X_SELL, panel.top + 10))
        screen.blit(hdr.render("Kaufen", True, (220, 220, 220)), (content_x0 + X_BUY, panel.top + 10))
        screen.blit(hdr.render("Du", True, (220, 220, 220)), (content_x0 + X_OWN, panel.top + 10))


        # --- Lesbarkeits-Layer: sehr transparentes Rechteck hinter Liste ---
        # Bereich: von kurz unter dem Holz-Header bis unten
        overlay_rect = pygame.Rect(
            content_x0 - 6,
            panel.top + 36,
            CONTENT_W + 12,
            panel.height - 48
        )

        overlay = pygame.Surface((overlay_rect.w, overlay_rect.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))  # sehr transparent (60/255). Wenn du mehr willst: 80..110
        screen.blit(overlay, overlay_rect.topleft)


        # Daten: sort + Filter
        goods_filtered = self._get_goods_sorted()

        # Selection clamp
        if goods_filtered:
            self.selected_idx = max(0, min(self.selected_idx, len(goods_filtered) - 1))
        else:
            self.selected_idx = 0

        # Scroll setup
        row_h = 30
        header_h = 38
        usable_h = panel.height - (header_h + 12)
        visible_rows = max(1, int(usable_h / row_h))

        if not hasattr(self, "scroll_offset") or self.scroll_offset is None:
            self.scroll_offset = 0

        max_scroll = max(0, len(goods_filtered) - visible_rows)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        # Hitboxes
        self.row_hitboxes = []
        mx, my = pygame.mouse.get_pos()

        y = panel.top + header_h
        start = self.scroll_offset
        end = min(len(goods_filtered), start + visible_rows)
        self.row_trade_btns = {}
        self.row_fav_btns = {}

        #Tooltips 
        hover_tooltip_text = None
        hover_tooltip_pos = None

        for i in range(start, end):
            g = goods_filtered[i]
            row_idx = i  # Index innerhalb goods_filtered

            row_rect = pygame.Rect(panel.left + 10, y - 2, panel.width - 20, row_h)
            cy = row_rect.centery
            self.row_hitboxes.append((row_idx, row_rect))

            # Hover/Selected Highlight
            hover = row_rect.collidepoint(mx, my)


            stock = market.stock.get(g.id, 0.0)
            ps = market.price_stock.get(g.id, stock)

            need = ctype.needs.get(g.category, "normal")
            target = g.target_stock * self.ctx.economy.NEED_TARGET_MULT.get(need, 1.0)
            bid, ask = self.ctx.economy.compute_bid_ask(g.base_price, ps, target, need)

            # --- Favorit-Stern (links in der Zeile) ---
            STAR_SIZE = 18  # falls du es woanders schon als Konstante hast, nicht doppelt definieren
            fav_rect = pygame.Rect(0, 0, STAR_SIZE, STAR_SIZE)
            fav_rect.centery = cy
            fav_rect.centerx = content_x0 + X_STAR + (STAR_W // 2)

            self.row_fav_btns[g.id] = fav_rect

            is_fav = (g.id in getattr(self.ctx, "favorite_goods", set()))
            star_img = self.star_filled if is_fav else self.star_empty

            sx = fav_rect.centerx - self._star_size // 2
            sy = fav_rect.centery - self._star_size // 2
            screen.blit(star_img, (sx, sy))

            # GANZE ZAHLEN für Anzeige
            stock_i = int(round(stock))
            bid_i = int(round(bid))
            ask_i = int(round(ask))



            # --- Buttons & Icon pro Ware (One-click Trade) ---
            BTN_H = 20
            sell_rect = pygame.Rect(content_x0 + X_SELL, cy - BTN_H // 2, SELL_W, BTN_H)
            buy_rect  = pygame.Rect(content_x0 + X_BUY,  cy - BTN_H // 2, BUY_W,  BTN_H)
            icon_rect = pygame.Rect(0, 0, ICON_SIZE, ICON_SIZE)
            icon_rect.centery = cy
            icon_rect.centerx = (sell_rect.right + buy_rect.left) // 2



            self.row_trade_btns[g.id] = {"buy": buy_rect, "sell": sell_rect}

            # Buttons: nur Preis (ohne K/V)
            ask_txt = f"{ask_i}"
            bid_txt = f"{bid_i}"

            pressed = (self._pressed_trade_btn == (g.id, "buy"))
            self._draw_ui_button(screen, buy_rect, ask_txt, variant=("hi" if pressed else "normal"))

            pressed = (self._pressed_trade_btn == (g.id, "sell"))
            self._draw_ui_button(screen, sell_rect, bid_txt, variant=("hi" if pressed else "normal"))

            # Icon
            icon = None
            if getattr(self, "icons", None):
                icon = self.icons.get(g.id)

            # Icon in der Mitte (doppelt so groß)
            if icon:
                # Pixel-scharf skalieren (kein smoothscale!)
                screen.blit(icon, (icon_rect.centerx - ICON_SIZE // 2, icon_rect.centery - ICON_SIZE // 2))


            else:
                letter = self.font_small.render(g.name[0].upper(), True, (230, 230, 230))
                screen.blit(letter, (icon_rect.centerx - letter.get_width() // 2,
                                    icon_rect.centery - letter.get_height() // 2))

            # Tooltip: Warenname nur bei Hover über Icon
            mx, my = pygame.mouse.get_pos()
            if icon_rect.collidepoint(mx, my):
                hover_tooltip_text = g.name
                hover_tooltip_pos = (mx, my)


            # --- Markt links neben Kaufen, Du direkt neben Verkaufen ---
            m_surf = self.font_small.render(f"{stock_i:>5d}", True, (200, 200, 200))
            screen.blit(m_surf, (content_x0 + X_MARKET, cy - m_surf.get_height() // 2))

            owned = int(round(player.cargo.tons_by_good().get(g.id, 0.0)))

            avg_map = self.ctx.trade_ui_state.get("avg_cost", {})
            avg = avg_map.get(g.id, None)

            if owned > 0 and avg is not None:
                owned_text = f"{owned} ({int(round(avg))})"
            else:
                owned_text = f"{owned}"

            owned_surf = self.font_small.render(owned_text, True, (200, 200, 200))
            screen.blit(owned_surf, (content_x0 + X_OWN, cy - owned_surf.get_height() // 2))

            y += row_h

        # Cargo Header (mit Frei)
        used = float(player.cargo.total_tons())
        cap = float(player.ship.capacity_tons)
        free = max(0.0, cap - used)

        screen.blit(self.font_small.render("Laderaum", True, (220, 220, 220)), (cargo_panel.left + 10, cargo_panel.top + 10))
        screen.blit(self.font_small.render(f"{int(round(used))}/{int(round(cap))} t", True, (220, 220, 220)), (cargo_panel.left + 10, cargo_panel.top + 30))
        screen.blit(self.font_small.render(f"Frei: {int(round(free))} t", True, (220, 220, 220)), (cargo_panel.left + 10, cargo_panel.top + 50))


        tons_by = player.cargo.tons_by_good()
        y2 = cargo_panel.top + 70
        for gid, tons in sorted(tons_by.items(), key=lambda x: -x[1]):
            name = self.ctx.content.goods[gid].name
            avg_map = self.ctx.trade_ui_state.get("avg_cost", {})
            avg = avg_map.get(gid, None)

            tons_i = int(round(tons))
            if tons_i > 0 and avg is not None:
                line = f"{name[:14]:<14} {tons_i:>4d}t ({int(round(avg))})"
            else:
                line = f"{name[:14]:<14} {tons_i:>6d}t"

            y2 += 22
            screen.blit(self.font_small.render(line, True, (220, 220, 220)), (cargo_panel.left + 10, y2))
            if y2 > cargo_panel.bottom - 20:
                break

        # Tooltip IMMER ganz vorne zeichnen
        if hover_tooltip_text and hover_tooltip_pos:
            mx, my = hover_tooltip_pos
            name_surf = self.font_small.render(hover_tooltip_text, True, (255, 255, 255))
            pad = 6

            tip_rect = name_surf.get_rect()
            tip_rect.topleft = (mx + 12, my + 12)

            bg_rect = pygame.Rect(
                tip_rect.left - pad,
                tip_rect.top - pad,
                tip_rect.width + pad * 2,
                tip_rect.height + pad * 2,
            )

            pygame.draw.rect(screen, (20, 20, 20), bg_rect, border_radius=6)
            pygame.draw.rect(screen, (90, 90, 90), bg_rect, 1, border_radius=6)
            screen.blit(name_surf, tip_rect)

        # Auto-Repeat Trades (Click-and-hold)
        self._tick_hold_trade()


    def _draw_ui_button(self, screen: pygame.Surface, rect: pygame.Rect, text: str, variant: str = "normal") -> None:
        """
        variant: "normal" | "hi" | "not"
        """
        key = (rect.w, rect.h, variant)
        if key in self._ui_btn_cache:
            surf = self._ui_btn_cache[key]
        else:
            if variant == "hi":
                base = self.ui_btn_hi
            elif variant == "not":
                base = self.ui_btn_not
            else:
                base = self.ui_btn

            surf = pygame.transform.smoothscale(base, (rect.w, rect.h))
            self._ui_btn_cache[key] = surf

        screen.blit(surf, rect.topleft)

        # Text (bei not ggf. etwas heller/dunkler – du wolltest keine Extra-Spielereien)
        color = (0, 0, 0) if variant != "not" else (80, 80, 80)
        t = self.font_small.render(text, True, color)

        screen.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))



    def _trade_qty_with_modifiers(self) -> float:
        """Berechnet die Handelsmenge unter Berücksichtigung von Shift/Ctrl."""
        mods = pygame.key.get_mods()
        mult = 1

        if mods & pygame.KMOD_SHIFT:
            mult *= 10
        if mods & pygame.KMOD_CTRL:
            mult *= 50

        return float(self.trade_qty_tons) * float(mult)


    def _trade_once(self, gid: str, side: str) -> None:
        """Führt genau einen Buy/Sell-Vorgang für die Ware aus (trade_qty_tons)."""
        goods_by_id = self.ctx.content.goods
        market = self.ctx.markets[self.city_id]
        ctype = self._get_city_type()

        g = goods_by_id[gid]

        need = (ctype.needs.get(g.category, "normal") or "normal").strip().lower()
        target = float(g.target_stock) * float(self.ctx.economy.NEED_TARGET_MULT.get(need, 1.0))
        lot_size = float(getattr(ctype, "lot_size_tons", 5.0))
        qty = self._trade_qty_with_modifiers()

        immediate_pct = {"small": 0.60, "medium": 0.40, "large": 0.25}.get(
            getattr(ctype, "market_size", "medium"), 0.40
        )

        def apply_immediate_price_stock(xgid: str) -> None:
            stock = float(market.stock.get(xgid, 0.0))
            ps = float(market.price_stock.get(xgid, stock))
            ps = ps + immediate_pct * (stock - ps)
            market.price_stock[xgid] = max(0.0, round(ps, 3))

        if side == "buy":
            self._buy_good(g, market, need, target, lot_size, qty, apply_immediate_price_stock)
        else:
            self._sell_good(g, market, need, target, lot_size, qty, apply_immediate_price_stock)

        from core.day_update import _update_top_needs
        _update_top_needs(self.ctx)

    def _tick_hold_trade(self) -> None:
        """Auto-Repeat: wenn Maus gedrückt gehalten wird, wiederholt Trade mit Ramp-up."""
        if not self._hold_trade:
            return

        # Maus muss weiterhin gedrückt sein (links)
        if not pygame.mouse.get_pressed(num_buttons=3)[0]:
            self._hold_trade = None
            self._pressed_trade_btn = None
            return

        now = pygame.time.get_ticks()
        gid = self._hold_trade["gid"]
        side = self._hold_trade["side"]
        t0 = self._hold_trade["t0"]

        # Optional: nur repeat, wenn Cursor noch auf dem selben Button ist
        mx, my = pygame.mouse.get_pos()
        btns = getattr(self, "row_trade_btns", {}).get(gid)
        if not btns:
            return

        rect = btns["buy"] if side == "buy" else btns["sell"]
        if not rect.collidepoint(mx, my):
            # Cursor weggezogen -> Repeat pausiert (oder stoppen)
            return

        # Timing: erst kurze Verzögerung, dann langsam, dann schnell
        elapsed = (now - t0) / 1000.0  # Sekunden

        if elapsed < 0.35:
            interval = None  # noch keine Wiederholung
        elif elapsed < 1.20:
            interval = 250   # ms
        else:
            interval = 60    # ms (sehr schnell)

        if interval is None:
            return

        if now < self._hold_trade["next"]:
            return

        # Nächster Trigger
        self._hold_trade["next"] = now + interval

        # Pressed-State für das Rendering
        self._pressed_trade_btn = (gid, side)

        # Einen Trade ausführen
        self._trade_once(gid, side)

    def _buy_good(self, g, market, need, target, lot_size, qty, apply_immediate_price_stock) -> None:
        player = self.ctx.player

        # Kapazität prüfen
        free = player.ship.capacity_tons - player.cargo.total_tons()
        if free <= 0.001:
            self.message = "Kein Laderaum frei."
            return

        qty = min(qty, free)

        # Marktbestand prüfen
        available = market.stock.get(g.id, 0.0)
        if available <= 0.001:
            self.message = "Markt ist leer."
            return

        qty = min(qty, available)

        bought = 0.0
        cost_total = 0.0

        while bought < qty - 1e-6:
            chunk = min(lot_size, qty - bought)

            # Preis berechnen über price_stock (träge), nicht stock
            ps = market.price_stock.get(g.id, market.stock.get(g.id, 0.0))
            bid, ask = self.ctx.economy.compute_bid_ask(g.base_price, ps, target, need)
            
            rc = self.ctx.run_config
            cat = g.category

            # buy_discount nur wenn Kategorie matcht
            if getattr(rc, "buy_discount_category", None) and getattr(rc, "buy_discount", 0.0) > 0:
                if cat.lower() == rc.buy_discount_category.lower():
                    ask = ask * (1.0 - rc.buy_discount)

            # Kaufkosten
            cost = int(round(ask * chunk))
            if player.money < cost:
                # ggf. nur Teilmenge kaufen
                max_chunk = player.money / max(ask, 0.0001)
                if max_chunk <= 0.1:
                    break
                chunk = min(chunk, max_chunk)
                max_chunk = player.money / max(ask, 0.0001)


            # Transfer
            player.money -= cost
            market.stock[g.id] -= chunk
            player.cargo.add_lot(g.id, chunk)
            # Einstandspreis-Durchschnitt aktualisieren (pro Chunk, effektiver ask)
            self._wac_add(g.id, chunk, ask)

            self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "coin.mp3"))


            bought += chunk
            cost_total += cost

            apply_immediate_price_stock(g.id)
            self._wac_remove(g.id)  # falls doch 0 (Edgecases)

        if bought <= 0.001:
            self.message = "Zu wenig Geld für Kauf."
        else:
            self.message = f"Gekauft: {bought:.1f} t {g.name} für {cost_total:.0f}"

    def _sell_good(self, g, market, need, target, lot_size, qty, apply_immediate_price_stock) -> None:
        player = self.ctx.player

        owned = player.cargo.tons_by_good().get(g.id, 0.0)
        if owned <= 0.001:
            self.message = "Keine Ware im Laderaum."
            return

        qty = min(qty, owned)

        sold = 0.0
        revenue_total = 0.0

        while sold < qty - 1e-6:
            chunk = min(lot_size, qty - sold)

            # Preis über price_stock (träge)
            ps = market.price_stock.get(g.id, market.stock.get(g.id, 0.0))
            bid, ask = self.ctx.economy.compute_bid_ask(g.base_price, ps, target, need)

            # Ware FIFO entnehmen
            removed = player.cargo.remove_fifo(g.id, chunk)
            if removed <= 0.001:
                break

            # Bestand erhöhen
            market.stock[g.id] = market.stock.get(g.id, 0.0) + removed

            # Erlös
            revenue = int(round(bid * removed))
            player.money += revenue

            sold += removed
            revenue_total += revenue
            self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "coin.mp3"))

            apply_immediate_price_stock(g.id)

        if sold <= 0.001:
            self.message = "Verkauf nicht möglich."
        else:
            self.message = f"Verkauft: {sold:.1f} t {g.name} für {revenue_total:.0f}"
        # Wenn Bestand 0, Einstandspreis löschen
        self._wac_remove(g.id)
