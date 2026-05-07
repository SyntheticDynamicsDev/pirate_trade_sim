from __future__ import annotations
import pygame
from dataclasses import dataclass
from typing import Optional
import os
from settings import SCREEN_W, SCREEN_H
import math
from settings import TIME_SCALE_PAUSE, TIME_SCALE_1X, TIME_SCALE_2X, TIME_SCALE_4X
from core.water_fx import WakeSystem   
from core.progression import xp_to_level
import settings

@dataclass
class WorldMapState:
    game = None
    ctx = None
    font: Optional[pygame.font.Font] = None
    
    MAPS = {
        "world_01": {
            "visual": os.path.join("assets", "maps", "world_01.png"),
            "nav":    os.path.join("assets", "maps", "world_nav_01.png"),
            "trg":    os.path.join("assets", "maps", "world_trg_01.png"),
            "enc":    os.path.join("assets", "maps", "world_enc_01.png"),

            # Übergänge: trigger_color -> (target_map, spawn_pos_in_target)
            "transitions": {
                (255, 0, 255): ("world_02", (530, 60)),  # Magenta -> world_02 spawn
            },
        },
        "world_02": {
            "visual": os.path.join("assets", "maps", "world_02.png"),
            "nav":    os.path.join("assets", "maps", "world_nav_02.png"),
            "trg":    os.path.join("assets", "maps", "world_trg_02.png"),
            "enc":    os.path.join("assets", "maps", "world_enc_02.png"),

            "transitions": {
                (255, 0, 255): ("world_01", (550, 700)),  # Magenta -> zurück world_01 spawn
            },
        },
    }

    def on_enter(self) -> None:
        # Masterlife icon (immer initialisieren)
        self._ml_icon = None
        try:
            from settings import MASTER_LIFE_ICON
            import os, pygame
            if os.path.exists(MASTER_LIFE_ICON):
                self._ml_icon = pygame.image.load(MASTER_LIFE_ICON).convert_alpha()
                self._ml_icon_scaled_cache = {}

        except Exception:
            self._ml_icon = None

        # --- Gold UI ---
        self._gold_icon = None
        self._gold_icon_scaled = None
        try:
            from settings import GOLD_ICON
            if os.path.exists(GOLD_ICON):
                self._gold_icon = pygame.image.load(GOLD_ICON).convert_alpha()
                # Standardgröße (kannst du später easy ändern)
                gold_size = 78
                self._gold_icon_scaled = pygame.transform.smoothscale(self._gold_icon, (gold_size, gold_size))
        except Exception:
            self._gold_icon = None
            self._gold_icon_scaled = None

        # --- Player Stats Button / Menu ---
        self._stats_open = False
        self._stats_prev_paused = False
        self._stats_btn = None
        self._stats_btn_rect = pygame.Rect(0, 0, 1, 1)
        self._stats_btn_hover = False
        # --- Stats menu scrolling ---
        self._stats_scroll = 0
        self._stats_content_h = 0
        self._stats_view_h = 0
        self._stats_scroll_step = 28

        # ensure player_stats exists (created in combat otherwise)
        if not hasattr(self.ctx, "player_stats") or self.ctx.player_stats is None:
            try:
                from states.combat import PlayerStats  # local import avoids global dependency
                self.ctx.player_stats = PlayerStats()
            except Exception:
                # hard fallback: simple object with expected attrs
                class _PS:  # noqa
                    cannon_damage_mult = 1.0
                    reload_mult = 1.0
                    boarding_damage_mult = 1.0
                    repair_mult = 1.0
                    evade_mult = 1.0
                    flee_mult = 1.0
                self.ctx.player_stats = _PS()

        # --- Stats button icons ---
        self._stats_btn = None
        self._stats_btn_hover_img = None

        try:
            surf = pygame.image.load(os.path.join("assets", "ui", "stats.png")).convert_alpha()
            self._stats_btn = pygame.transform.smoothscale(surf, (120, 180))
        except Exception:
            self._stats_btn = None

        try:
            surf_h = pygame.image.load(os.path.join("assets", "ui", "stats_klick.png")).convert_alpha()
            self._stats_btn_hover_img = pygame.transform.smoothscale(surf_h, (120, 180))
        except Exception:
            self._stats_btn_hover_img = None
        # --- Stats menu background image (assets/ui/bg_stats.png) ---
        self._bg_stats = None
        try:
            self._bg_stats = pygame.image.load(os.path.join("assets", "ui", "bg_stats.png")).convert_alpha()
        except Exception:
            self._bg_stats = None

        # aktuelle Map (default)
        if not hasattr(self.ctx, "current_map_id") or not self.ctx.current_map_id:
            self.ctx.current_map_id = "world_01"

        from core.ui_text import FontBank, TextStyle, render_text
        from settings import UI_FONT_PATH, UI_FONT_FALLBACK

        self._fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)
        self.font = self._fonts.get(22)
        self.small = self._fonts.get(14)

        # --- City-Schilder Cache ---
        self._city_sign_cache = {}   # name -> Surface|None
        self._city_sign_scale = 1.0  # optional, später tweakbar
        self._city_sign_target_h = 130   # z.B. 28–36; 32 ist ein guter Start

        self.ctx.clock.time_scale = TIME_SCALE_1X
        tracks = [
            os.path.join("assets", "music", "world_01.mp3"),
            os.path.join("assets", "music", "world_1.mp3"),
        ]
        self.ctx.audio.play_playlist(tracks, shuffle=True, fade_ms=800)

        self._ship_sprite_cache = {}
        self._ship_sprite_size = (42, 42)

        # in on_enter()
        self._ship_time = 0.0

        self._ship_accel = 520.0          # px/s², Steuer-Acceleration
        self._ship_linear_drag = 2.2      # stärker als vorher -> weniger "gleiten"
        self._ship_quad_drag = 0.004      # bremst stark bei hoher Speed
        self._ship_stop_epsilon = 10.0    # px/s

        self._wind = pygame.Vector2(22.0, 6.0)  # px/s² (wie gehabt)

        # --- Sky Clouds (ui/air/cloud1-3) ---
        self._cloud_imgs_raw = []
        self._cloud_instances = []
        self._cloud_cache = {}  # (img_index, w, h) -> scaled surface

        sw, sh = SCREEN_W, SCREEN_H
        self._cloud_count = 12 if sw <= 1600 else 16  # oder 10/14
        # config (tweakbar)
        self._cloud_count = 18
        self._cloud_alpha_min = int(255 * 0.05)  # 5%
        self._cloud_alpha_max = int(255 * 0.20)  # 20%
        self._cloud_scale_min = 0.80
        self._cloud_scale_max = 1.20
        self._cloud_wrap_pad = 220  # extra padding for wrap

        try:
            base_dir = os.path.join("assets", "ui", "air")
            # accept both with/without .png
            names = ["cloud1.png", "cloud2.png", "cloud3.png"]
            for n in names:
                p = os.path.join(base_dir, n)
                if os.path.exists(p):
                    self._cloud_imgs_raw.append(pygame.image.load(p).convert_alpha())
        except Exception:
            self._cloud_imgs_raw = []
            self._cloud_instances = []
            self._cloud_cache = {}

        # --- Map Transition Arrows (2x2 spritesheet, use TOP row only) ---
        self._arrow_frames = []
        self._arrow_frame_i = 0
        self._arrow_anim_t = 0.0
        self._arrow_fps = 3.0  # Speed der Animation

        try:
            sheet_path = os.path.join("assets", "ui", "arrows.png")
            if os.path.exists(sheet_path):
                sheet = pygame.image.load(sheet_path).convert_alpha()
                sw, sh = sheet.get_size()
                fw, fh = sw // 2, sh // 2

                # top row only: (0,0) and (1,0)
                f0 = sheet.subsurface(pygame.Rect(0 * fw, 0 * fh, fw, fh)).copy()
                f1 = sheet.subsurface(pygame.Rect(1 * fw, 0 * fh, fw, fh)).copy()
                self._arrow_frames = [f0, f1]
        except Exception:
            self._arrow_frames = []

        self._load_current_map_assets()
        self._respawn_clouds()
        self._spawn_ship_safely()
        self._ensure_ship_on_water()
        self._wake = WakeSystem()

        self._ship_loop_key = "ship_ambience"
        self._ship_loop_path = os.path.join("assets", "sfx", "ship_waves_loop.wav")  # dein Pfad
        self._ship_loop_started = False
        self._ship_loop_vol = 0.0

        # --- Encounter/Barometer SFX (waves_level loop + wave_crash) ---
        self._enc_sfx_loop_key = "enc_waves_level"
        self._enc_sfx_loop_started = False
        self._enc_waves_path = self._resolve_sfx_path("waves_level")
        self._enc_crash_path = self._resolve_sfx_path("wave_crash")

        self._ui_t = 0.0
        self._baro_marker_cache = {}  # (w,h,alpha_bucket) -> Surface

        # --- XP Panel (unten links, kompakt) ---
        self._xp_panel_raw = None
        self._xp_panel = None
        self._xp_panel_rect = pygame.Rect(0, 0, 0, 0)

        xp_path = os.path.join("assets", "ui", "xp.png")
        try:
            if os.path.exists(xp_path):
                self._xp_panel_raw = pygame.image.load(xp_path).convert_alpha()

                # KOMPAKTER: weniger breit, etwas höher
                panel_w = 220
                panel_h = 84
                self._xp_panel = pygame.transform.smoothscale(
                    self._xp_panel_raw, (panel_w, panel_h)
                )
                # XP Fill (passt exakt auf xp.png)
                self._xp_fill_raw = None
                self._xp_fill = None

                fill_path = os.path.join("assets", "ui", "xp_fill.png")
                if os.path.exists(fill_path):
                    self._xp_fill_raw = pygame.image.load(fill_path).convert_alpha()
                    self._xp_fill = pygame.transform.smoothscale(self._xp_fill_raw, (panel_w, panel_h))

                # Platzierung: unten links (screen-size nicht aus ctx nehmen)
                margin = 18
                self._xp_panel_rect = self._xp_panel.get_rect(topleft=(margin, margin))  # temp

        except Exception:
            self._xp_panel_raw = None
            self._xp_panel = None
        # --- XP UI: keep panel & fill in identical coordinate space ---
        stretch_y = 1.45  # 1.15..1.55 je nach Geschmack

        if getattr(self, "_xp_panel", None) is not None and getattr(self, "_xp_fill", None) is not None:
            w, h = self._xp_panel.get_size()
            new_h = int(h * stretch_y)

            self._xp_panel = pygame.transform.smoothscale(self._xp_panel, (w, new_h))
            self._xp_fill  = pygame.transform.smoothscale(self._xp_fill,  (w, new_h))

        # --- Encounter Config: map_id -> color -> pool + chance ---
        # v1: simple, aber sauber strukturiert
        self._encounter_cfg = {
            "world_01": {
                (255, 0, 0): {"pool": ["pirate_sloop", "pirate_brig"], "meter_per_sec": 0.32},
                (0, 255, 0): {"pool": ["sea_wolf", "eel"], "meter_per_sec": 0.08},
            },
            "world_02": {
                (255, 0, 0): {"pool": ["pirate_brig", "pirate_frigate"], "meter_per_sec": 0.14},
                (0, 255, 0): {"pool": ["abyss_fish", "krakenling"], "meter_per_sec": 0.09},
            },
        }

        self._encounter_cooldown = 0.0
        # --- Encounter / Barometer state ---
        if not hasattr(self, "_enc_meter"):
            self._enc_meter = 0.0

        # Persist: Barometer aus ctx übernehmen (Save/Load)
        if not hasattr(self.ctx, "enc_meter"):
            self.ctx.enc_meter = float(getattr(self, "_enc_meter", 0.0))
        self._enc_meter = float(self.ctx.enc_meter)
        self._enc_meter = max(0.0, min(1.0, self._enc_meter))

        if not hasattr(self, "_enc_decay_per_sec"):
            self._enc_decay_per_sec = 0.12  # Default: fällt spürbar, aber nicht hart

        # --- New Barometer UI (Frame + Skull Marker) ---
        BARO_SCALE_FRAME = 0.22   # kleineres Gehäuse
        BARO_SCALE_MARKER = 0.12  # Marker deutlich kleiner (wird zusätzlich auf Säulenbreite gefittet)

        self._barometer_frame_raw = pygame.image.load(
            os.path.join("assets", "ui", "barometer.png")
        ).convert_alpha()

        self._barometer_marker_raw = pygame.image.load(
            os.path.join("assets", "ui", "level.png")
        ).convert_alpha()

        # Frame scale
        fw, fh = self._barometer_frame_raw.get_size()
        self._barometer_frame = pygame.transform.smoothscale(
            self._barometer_frame_raw,
            (max(1, int(fw * BARO_SCALE_FRAME)), max(1, int(fh * BARO_SCALE_FRAME)))
        )

        # Marker pre-scale (grob)
        mw, mh = self._barometer_marker_raw.get_size()
        marker_base = pygame.transform.smoothscale(
            self._barometer_marker_raw,
            (max(1, int(mw * BARO_SCALE_MARKER)), max(1, int(mh * BARO_SCALE_MARKER)))
        )

        # Final marker fit: exakt auf Säulenbreite anpassen
        self._baro_w, self._baro_h = self._barometer_frame.get_size()
        self._baro_pillar_w = int(self._baro_w * 0.36)  # Säule ~36% der Frame-Breite (kannst du später feinjustieren)

        mbw, mbh = marker_base.get_size()
        if mbw > 0:
            fit_scale = self._baro_pillar_w / float(mbw)
            self._barometer_marker = pygame.transform.smoothscale(
                marker_base,
                (max(1, int(mbw * fit_scale)), max(1, int(mbh * fit_scale)))
            )
        else:
            self._barometer_marker = marker_base

        self._marker_w, self._marker_h = self._barometer_marker.get_size()

        # --- Intro / Goal Tooltip (modal) ---
        # nur einmal pro Run anzeigen
        if not getattr(self.ctx, "_intro_seen", False):
            self._intro_open = True
            self.ctx._intro_seen = True
        else:
            self._intro_open = False

        self._goal_gold = int(getattr(settings, "WIN_GOLD_TARGET", 15000))

        # Storytext
        gold_str = f"{self._goal_gold:,}".replace(",", ".")
        self._intro_title = self.ctx.i18n.t("intro.title")
        self._intro_paragraphs = [
            self.ctx.i18n.t("intro.p1"),
            self.ctx.i18n.t("intro.p2"),
            self.ctx.i18n.t("intro.goal", gold=gold_str),
            self.ctx.i18n.t("intro.tip"),
        ]

        # --- Controls Hint (WASD) ---
        self._controls_hint_t = 0.0
        self._controls_hint_duration = 12.0  # Sekunden sichtbar

    def _resolve_sfx_path(self, base_name: str) -> str | None:
        """
        Sucht eine SFX-Datei anhand des Basenamens in typischen asset-Ordnern
        und mit typischen Extensions.
        """
        exts = [".wav", ".ogg", ".mp3"]
        dirs = [
            os.path.join("assets", "sfx"),
            os.path.join("assets", "sounds"),
            os.path.join("assets", "audio"),
            os.path.join("assets"),
        ]
        for d in dirs:
            for ext in exts:
                p = os.path.join(d, base_name + ext)
                if os.path.exists(p):
                    return p
        return None

    def _get_enc_color_at_ship(self):
        ship = self.ctx.player.ship
        x, y = int(ship.pos[0]), int(ship.pos[1])

        if x < 0 or y < 0 or x >= self._map_enc.get_width() or y >= self._map_enc.get_height():
            return None

        r, g, b, *_ = self._map_enc.get_at((x, y))
        color = (r, g, b)

        # "keine encounter zone" Farben (anpassen, je nachdem wie du enc-map malst)
        if color == (0, 0, 0) or color == (255, 255, 255):
            return None
        return color

    def on_exit(self) -> None:
        self.ctx.audio.stop_loop_sfx(self._ship_loop_key, fade_ms=800)

    def handle_event(self, event) -> None:
        # --- Intro modal blocks input ---
        if getattr(self, "_intro_open", False):
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                    self._intro_open = False
                    if getattr(self.ctx, "audio", None) is not None:
                        self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                    return
                return  # alles andere blocken

            if event.type == pygame.MOUSEBUTTONDOWN:
                # linker klick oder irgendein klick schließt
                self._intro_open = False
                if getattr(self.ctx, "audio", None) is not None:
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                return

            # sonstige events ignorieren
            return
        
        # --- Stats menu input has priority ---
        if event.type == pygame.KEYDOWN:
            if self._stats_open and event.key == pygame.K_ESCAPE:
                self._toggle_stats_menu(False)
                if getattr(self.ctx, "audio", None) is not None:
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            # click on stats button
            if getattr(self, "_stats_btn", None) is not None and self._stats_btn_rect.collidepoint(mx, my):
                self._toggle_stats_menu(not self._stats_open)
                if getattr(self.ctx, "audio", None) is not None:
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                return

            # optional: click outside panel closes when open
            if self._stats_open:
                if not self._get_stats_panel_rect().collidepoint(mx, my):
                    self._toggle_stats_menu(False)
                    if getattr(self.ctx, "audio", None) is not None:
                        self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
                return

        # --- Stats menu scrolling (mouse wheel) ---
        if self._stats_open:
            if event.type == pygame.MOUSEWHEEL:
                # pygame: y>0 = up, y<0 = down
                self._stats_scroll -= int(event.y) * self._stats_scroll_step
                self._clamp_stats_scroll()
                return

            # older pygame compatibility (optional)
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 4:  # wheel up
                    self._stats_scroll -= self._stats_scroll_step
                    self._clamp_stats_scroll()
                    return
                if event.button == 5:  # wheel down
                    self._stats_scroll += self._stats_scroll_step
                    self._clamp_stats_scroll()
                    return

        # when stats menu open, block the rest of world interactions
        if self._stats_open:
            return
        
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                # Pause toggle
                self.ctx.clock.paused = not self.ctx.clock.paused
                self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))
            elif event.key == pygame.K_TAB:
                self._cycle_time_speed()
                self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))


            elif event.key == pygame.K_e:
                # Attempt docking/enter city
                world = self.ctx.world
                player = self.ctx.player
                city = self._find_city_by_harbor_range(player.ship.pos)
                if city:
                    player.docked_city_id = city.id

                    from states.city import CityState  # <- LOCAL IMPORT
                    st = CityState(city_id=city.id)
                    st.game = self.game
                    st.ctx = self.ctx
                            # Merken, wo wir angedockt haben
                    self.ctx.last_city_id = city.id
                    self.ctx.last_world_ship_pos = self.ctx.player.ship.pos
                    self.game.replace(st)
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))

            elif event.key == pygame.K_ESCAPE:
                # In-Game Menü nur in der Weltansicht
                from states.pause_menu import PauseMenuState
                st = PauseMenuState()
                st.game = self.game
                st.ctx = self.ctx
                self.game.push(st)

                if getattr(self.ctx, "audio", None) is not None:
                    self.ctx.audio.play_sfx(os.path.join("assets", "sfx", "ui_click.mp3"))

    def _clamp_stats_scroll(self) -> None:
        max_scroll = max(0, int(self._stats_content_h) - int(self._stats_view_h))
        if self._stats_scroll < 0:
            self._stats_scroll = 0
        elif self._stats_scroll > max_scroll:
            self._stats_scroll = max_scroll

    def _toggle_stats_menu(self, open_: bool) -> None:
        if open_ == self._stats_open:
            return

        self._stats_open = open_

        if open_:
            self._stats_scroll = 0
            self._stats_content_h = 0
            self._stats_view_h = 0

        else:
            # restore previous pause state
            self.ctx.clock.paused = bool(getattr(self, "_stats_prev_paused", False))

    def _get_stats_panel_rect(self) -> pygame.Rect:
        # centered panel
        w = int(self.screen_w * 0.44) if hasattr(self, "screen_w") else 520
        h = int(self.screen_h * 0.55) if hasattr(self, "screen_h") else 420
        sw = self._last_screen_w if hasattr(self, "_last_screen_w") else 1280
        sh = self._last_screen_h if hasattr(self, "_last_screen_h") else 720
        x = (sw - w) // 2
        y = (sh - h) // 2
        return pygame.Rect(x, y, w, h)


    def update(self, dt: float) -> None:
        # --- Pause world while intro modal is open ---
        if getattr(self, "_intro_open", False):
            return
        # --- Sim-Time (Pause / Speed) ---
        if self.ctx.clock.paused:
            sim_dt = 0.0
        else:
            sim_dt = dt * float(getattr(self.ctx.clock, "time_scale", 1.0))

        self._ship_time += sim_dt

        if not hasattr(self, "_enc_meter"):
            self._enc_meter = 0.0

        self._ui_t = float(getattr(self, "_ui_t", 0.0)) + float(dt)
        # controls hint timer (läuft mit real dt, nicht sim_dt)
        self._controls_hint_t = float(getattr(self, "_controls_hint_t", 0.0)) + float(dt)

        ship = self.ctx.player.ship
        keys = pygame.key.get_pressed()

        # --- Input: WASD -> gewünschte Richtung (8-direction) ---
        ix = float(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - float(keys[pygame.K_a] or keys[pygame.K_LEFT])
        iy = float(keys[pygame.K_s] or keys[pygame.K_DOWN]) - float(keys[pygame.K_w] or keys[pygame.K_UP])

        desired = pygame.Vector2(ix, iy)
        has_input = desired.length_squared() > 0.0001
        if has_input:
            desired = desired.normalize()

        # --- Zustand laden ---
        pos = pygame.Vector2(ship.pos[0], ship.pos[1])
        vel = pygame.Vector2(ship.vel[0], ship.vel[1])

        max_speed = max(40.0, float(ship.speed))  # ship.speed = max speed px/s
        accel_mult = max(0.2, float(getattr(ship, "accel", 1.0)))
        accel_strength = self._ship_accel * accel_mult

        # --- Beschleunigung in Wunschrichtung ---
        acc = pygame.Vector2(0.0, 0.0)
        if has_input:
            acc += desired * accel_strength

        # --- Winddrift (konstante Störkraft) ---
        acc += self._wind

        # --- Drag (linear + quadratisch) ---
        speed = vel.length()
        if speed > 0.0001:
            acc -= vel * self._ship_linear_drag
            acc -= vel * speed * self._ship_quad_drag

        # --- Integration ---
        vel += acc * sim_dt
        
        if has_input and vel.length_squared() > 1.0:
            # begrenzt, wie stark man die aktuelle Bewegungsrichtung pro Sekunde drehen kann
            max_turn_per_sec = 6.0  # höher = direkter, niedriger = "bootiger"
            cur = vel.normalize()
            target = desired
            # blend towards target direction
            blended = (cur.lerp(target, min(1.0, max_turn_per_sec * sim_dt))).normalize()
            vel = blended * vel.length()

        # Clamp speed
        new_speed = vel.length()
        if new_speed > max_speed:
            vel.scale_to_length(max_speed)

        # "echtes" Stoppen, wenn kein Input
        if not has_input and vel.length() < self._ship_stop_epsilon:
            vel.update(0.0, 0.0)

        # --- Move + Collision/Slide über Navmap ---
        nx = pos.x + vel.x * sim_dt
        ny = pos.y + vel.y * sim_dt

        if self._is_sailable(nx, ny):
            pos.update(nx, ny)
        else:
            if self._is_sailable(nx, pos.y):
                pos.x = nx
                vel.y *= 0.35
            elif self._is_sailable(pos.x, ny):
                pos.y = ny
                vel.x *= 0.35
            else:
                vel *= 0.0

        # Persist back
        ship.pos = (pos.x, pos.y)
        ship.vel = (vel.x, vel.y)
        self._wake.update(sim_dt, ship.pos, ship.vel)
        # Optional: Heading für Sprite-Rotation aus Velocity ableiten
        if vel.length_squared() > 1.0:
            # Wir wollen: Down = 0°, Right = -90°, Left = +90°, Up = 180°
            # vel.x, vel.y sind in Screen-Koordinaten (y nach unten positiv).
            heading_deg = -math.degrees(math.atan2(vel.x, vel.y))
            ship.heading = math.radians(heading_deg)
            
        # --- Clouds drift (same direction as ship drift) ---
        if sim_dt > 0.0 and getattr(self, "_cloud_instances", None):
            sw, sh = SCREEN_W, SCREEN_H

            # direction = ship vel, fallback = wind
            ship = self.ctx.player.ship
            v = pygame.Vector2(float(ship.vel[0]), float(ship.vel[1]))
            if v.length_squared() < 25.0:  # ~5 px/s threshold
                v = pygame.Vector2(getattr(self, "_wind", pygame.Vector2(10.0, 0.0)))

            # normalize direction, choose a pleasant base speed
            if v.length_squared() > 0.0001:
                dir_ = v.normalize()
            else:
                dir_ = pygame.Vector2(1.0, 0.0)

            # base cloud speed in px/s
            base_speed = max(14.0, min(90.0, v.length() * 0.25))

            # move + wrap
            pad = int(getattr(self, "_cloud_wrap_pad", 200))

            for c in self._cloud_instances:
                spd = base_speed * float(c["drift_mult"])
                c["x"] += dir_.x * spd * sim_dt
                c["y"] += dir_.y * spd * sim_dt * 0.25  # much less vertical drift

                # wrap with padding
                if c["x"] < -pad:
                    c["x"] = sw + pad
                elif c["x"] > sw + pad:
                    c["x"] = -pad

                if c["y"] < -pad:
                    c["y"] = sh + pad
                elif c["y"] > sh + pad:
                    c["y"] = -pad

        self._check_map_transition()

        # --- Encounter meter update (global, no reset on color change) ---
        if sim_dt > 0.0:
            enc_color = self._get_enc_color_at_ship()
            self._enc_last_color = enc_color  # nur UI/Debug

            cfg_map = self._encounter_cfg.get(self.ctx.current_map_id, {})
            entry = cfg_map.get(enc_color) if enc_color is not None else None

            if entry is None:
                # Kein Treffer (außerhalb ODER Farbe nicht konfiguriert): immer decayn
                self._enc_meter = max(0.0, self._enc_meter - self._enc_decay_per_sec * sim_dt)
            else:
                # Treffer: gainen
                rate = float(entry.get("meter_per_sec", 0.10))
                self._enc_meter = min(1.0, self._enc_meter + rate * sim_dt)

                if self._enc_meter >= 1.0:
                    # Guaranteed encounter
                    if self._enc_meter >= 1.0:
                        # Crash-SFX einmal abspielen, wenn 100% erreicht
                        if self._enc_crash_path:
                            self.ctx.audio.play_sfx(self._enc_crash_path)

                        # Loop kurz ausblenden (wir gehen gleich in Transition/Combat)
                        self.ctx.audio.stop_loop_sfx(self._enc_sfx_loop_key, fade_ms=250)
                        self._enc_sfx_loop_started = False

                        self._enc_meter = 0.0
                        self.ctx.enc_meter = 0.0
                        self._trigger_encounter_from_color(enc_color, entry)
                        return



        # --- Barometer -> waves_level Loop Volume (0..100 -> 0.40..0.80) ---
        meter = float(getattr(self, "_enc_meter", 0.0))
        meter = max(0.0, min(1.0, meter))
        # Persist back to ctx (wichtig für Save)
        self.ctx.enc_meter = float(getattr(self, "_enc_meter", 0.0))

        if self._enc_waves_path and meter > 0.001:
            # linear mapping 0..1 -> 0.40..0.80
            vol = 0.40 + (0.80 - 0.40) * meter

            # start loop once, then update volume
            self.ctx.audio.play_loop_sfx(self._enc_sfx_loop_key, self._enc_waves_path, volume=vol)
            self._enc_sfx_loop_started = True
        else:
            # if meter is basically 0: fade out loop
            if self._enc_sfx_loop_started:
                self.ctx.audio.stop_loop_sfx(self._enc_sfx_loop_key, fade_ms=300)
                self._enc_sfx_loop_started = False


        vx, vy = ship.vel
        speed = math.hypot(vx, vy)

        # Ziel: erst ab kleiner Bewegung hörbar, dann bis max aufziehen
        min_speed = 18.0
        max_speed = 260.0

        # Test-Logik: Sobald Input aktiv ist, soll man es hören (unabhängig von min_speed)
        if has_input:
            target = 0.990  # fix zum Test
        else:
            # wenn kein Input: nach Speed ausblenden
            if speed <= min_speed:
                target = 0.0
            else:
                t = (speed - min_speed) / max(1.0, (max_speed - min_speed))
                t = max(0.0, min(1.0, t))
                target = 0.30 * t


        # weiches Fade
        fade_in = 1.2
        fade_out = 0.9
        if target > self._ship_loop_vol:
            self._ship_loop_vol = min(target, self._ship_loop_vol + sim_dt / max(0.001, fade_in))
        else:
            self._ship_loop_vol = max(target, self._ship_loop_vol - sim_dt / max(0.001, fade_out))

        # Loop einmal starten (mit 0 Volume), danach nur noch set_loop_volume
        if not self._ship_loop_started:
            self.ctx.audio.play_loop_sfx(self._ship_loop_key, self._ship_loop_path, volume=0.0)
            self._ship_loop_started = True

        self.ctx.audio.set_loop_volume(self._ship_loop_key, self._ship_loop_vol)

        # --- Transition arrows animate with REAL dt (even if paused) ---
        if getattr(self, "_arrow_frames", None):
            self._arrow_anim_t += float(dt)
            step = 1.0 / max(1e-6, float(getattr(self, "_arrow_fps", 7.0)))
            while self._arrow_anim_t >= step:
                self._arrow_anim_t -= step
                self._arrow_frame_i = (int(getattr(self, "_arrow_frame_i", 0)) + 1) % len(self._arrow_frames)

    def _trigger_encounter_from_color(self, enc_color, entry: dict) -> None:
        import random
        pool = entry.get("pool", [])
        if not pool:
            return

        enemy_id = random.choice(pool)
        from states.combat import CombatState
        from states.transition import TransitionState

        # Snapshot der aktuellen World-Ansicht erstellen
        snap = pygame.Surface((SCREEN_W, SCREEN_H))
        self.render(snap)

        # Fokus = Schiff-Position (ist bei dir screen space, weil du so renderst)
        fx, fy = self.ctx.player.ship.pos

        self.game.replace(TransitionState(
            kind="to_combat",
            snapshot=snap,
            focus=(fx, fy),
            enemy_id=enemy_id
        ))


        # Meter-Reset ist oben; hier nur Spam-Schutz:
        self._encounter_cooldown = 6.0

    def _build_transition_markers_for_map(self, map_id: str) -> list[dict]:
        """
        Finds transition zones in self._map_trg for all transition colors and returns marker list:
        [{"pos": (x,y), "dir": "N/E/S/W"}, ...]
        """
        cfg = self.MAPS.get(map_id, {})
        transitions = cfg.get("transitions", {})
        if not transitions:
            return []

        # If map trg not loaded yet, nothing to do
        trg = getattr(self, "_map_trg", None)
        if trg is None:
            return []

        target_colors = list(transitions.keys())
        if not target_colors:
            return []

        # bounds per color: (minx, miny, maxx, maxy)
        bounds = {c: [10**9, 10**9, -1, -1] for c in target_colors}

        # Use PixelArray for speed (compared to get_at)
        px = pygame.PixelArray(trg)
        mapped = {trg.map_rgb(c): c for c in target_colors}

        w = trg.get_width()
        h = trg.get_height()

        for y in range(h):
            for x in range(w):
                v = px[x, y]
                c = mapped.get(v)
                if c is None:
                    continue
                b = bounds[c]
                if x < b[0]: b[0] = x
                if y < b[1]: b[1] = y
                if x > b[2]: b[2] = x
                if y > b[3]: b[3] = y

        del px  # unlock surface

        markers = []
        for c, (minx, miny, maxx, maxy) in bounds.items():
            if maxx < 0 or maxy < 0:
                continue  # color not found on trg map

            cx = (minx + maxx) // 2
            cy = (miny + maxy) // 2

            # Determine direction by which edge it's closest to
            left = cx
            right = (SCREEN_W - 1) - cx
            top = cy
            bottom = (SCREEN_H - 1) - cy

            m = min(left, right, top, bottom)
            edge_inset = 26  # px vom Rand weg

            if m == left:
                d = "W"
                cx += edge_inset
            elif m == right:
                d = "E"
                cx -= edge_inset
            elif m == top:
                d = "N"
                cy += edge_inset
            else:
                d = "S"
                cy -= edge_inset

            markers.append({"pos": (int(cx), int(cy)), "dir": d})

        return markers

    def _check_map_transition(self) -> None:
        ship = self.ctx.player.ship
        x, y = int(ship.pos[0]), int(ship.pos[1])
        if x < 0 or y < 0 or x >= SCREEN_W or y >= SCREEN_H:
            return

        r, g, b, *_ = self._map_trg.get_at((x, y))
        color = (r, g, b)

        map_id = self.ctx.current_map_id
        transitions = self.MAPS[map_id]["transitions"]

        if color in transitions:
            target_map, target_spawn = transitions[color]

            # 1) Map wechseln
            self.ctx.current_map_id = target_map

            # 2) Zielspawn setzen
            ship.pos = target_spawn

            # 3) Map-Assets/Cache laden, aber ohne Respawn-Logik
            self._load_current_map_assets()
            self._respawn_clouds()

            # 4) Nur sicherstellen, dass Spawn auf Wasser landet
            self._ensure_ship_on_water()

    def _load_current_map_assets(self) -> None:
        map_id = self.ctx.current_map_id

        cache = getattr(self.ctx, "map_cache", None)
        if cache is None:
            self.ctx.map_cache = {}
            cache = self.ctx.map_cache

        if map_id in cache:
            cached = cache[map_id]
            self._map_visual = cached["visual"]
            self._map_nav = cached["nav"]
            self._nav_grid = cached["nav_grid"]
            self._city_harbors = cached["city_harbors"]
            self._map_trg = cached["trg"]
            self._map_enc = cached["enc"]

            self._transition_markers = cached.get("transition_markers", [])

            # Save/Load-Fix: falls alte Saves/Cache keine Marker enthalten
            if not self._transition_markers:
                self._transition_markers = self._build_transition_markers_for_map(map_id)
                cached["transition_markers"] = self._transition_markers

            return

        cfg = self.MAPS[map_id]
        self._map_visual = self._load_and_scale_visual(cfg["visual"])
        self._map_nav = self._load_and_scale_nav(cfg["nav"])
        self._map_trg = self._load_and_scale_nav(cfg["trg"])
        self._map_enc = self._load_and_scale_nav(cfg["enc"])

        self._transition_markers = self._build_transition_markers_for_map(map_id)

        self._nav_grid = [[False for _ in range(SCREEN_H)] for _ in range(SCREEN_W)]
        for x in range(SCREEN_W):
            for y in range(SCREEN_H):
                r, g, b, *_ = self._map_nav.get_at((x, y))
                is_blue_water = (b >= 200 and r <= 60 and g <= 60)
                is_white = (r >= 230 and g >= 230 and b >= 230)
                self._nav_grid[x][y] = (is_blue_water or is_white)

        self._city_harbors = {}
        self._build_city_harbors()

        cache[map_id] = {
            "visual": self._map_visual,
            "nav": self._map_nav,
            "nav_grid": self._nav_grid,
            "city_harbors": self._city_harbors,
            "trg": self._map_trg,
            "enc": self._map_enc,
            "transition_markers": self._transition_markers,

        }
        
    def _get_cloud_surface(self, img_i: int, scale: float, alpha: int) -> pygame.Surface:
        """
        Returns a cached surface for (image, scale, alpha).
        No per-frame copies in render.
        """
        if not getattr(self, "_cloud_imgs_raw", None):
            raise RuntimeError("Cloud images not loaded")

        base = self._cloud_imgs_raw[img_i]
        w = max(1, int(base.get_width() * scale))
        h = max(1, int(base.get_height() * scale))

        # quantize for better cache hit rate
        a = int(alpha)
        s_key = int(round(scale * 100))  # 0.80 -> 80, 1.20 -> 120
        key = (img_i, w, h, a, s_key)

        cache = getattr(self, "_cloud_cache", None)
        if cache is None:
            self._cloud_cache = {}
            cache = self._cloud_cache

        surf = cache.get(key)
        if surf is not None:
            return surf

        scaled = pygame.transform.smoothscale(base, (w, h))
        scaled.set_alpha(a)  # set ONCE
        cache[key] = scaled

        # keep cache bounded
        if len(cache) > 200:
            cache.clear()

        return scaled

    def _respawn_clouds(self) -> None:
        """Randomize cloud placement/variants every time we enter a map."""
        self._cloud_instances = []
        self._cloud_cache = {}

        if not getattr(self, "_cloud_imgs_raw", None):
            return

        import random
        # non-deterministic seed -> different each entry
        rng = random.Random()

        count = int(getattr(self, "_cloud_count", 18))

        # 1–2 featured clouds with higher opacity (~50%)
        featured = rng.randint(1, 2) if count >= 2 else 1
        featured_slots = set(rng.sample(range(count), featured))

        sw, sh = SCREEN_W, SCREEN_H
        pad = int(getattr(self, "_cloud_wrap_pad", 220))

        for i in range(count):
            img_i = rng.randrange(0, len(self._cloud_imgs_raw))

            # IMPORTANT: check slot index i, not img_i
            if i in featured_slots:
                alpha = int(255 * rng.uniform(0.45, 0.55))  # ~50% (45–55)
            else:
                alpha = rng.randint(int(self._cloud_alpha_min), int(self._cloud_alpha_max))

            scale = rng.uniform(
                float(getattr(self, "_cloud_scale_min", 0.80)),
                float(getattr(self, "_cloud_scale_max", 1.20)),
            )

            drift_mult = rng.uniform(0.10, 0.30)
            bob_amp = rng.uniform(1.0, 6.0)
            bob_spd = rng.uniform(0.4, 1.1)
            bob_phase = rng.uniform(0.0, 6.28318)

            x = rng.uniform(-pad, sw + pad)
            y = rng.uniform(-60, sh * 0.55)

            surf = self._get_cloud_surface(img_i, scale, alpha)

            self._cloud_instances.append({
                "img_i": int(img_i),
                "x": float(x),
                "y": float(y),
                "alpha": int(alpha),
                "scale": float(scale),
                "drift_mult": float(drift_mult),
                "bob_amp": float(bob_amp),
                "bob_spd": float(bob_spd),
                "bob_phase": float(bob_phase),
                "surf": surf,
            })

    def _draw_tooltip(self, screen, pos, lines, font=None):
        """Kleines Tooltip-Panel an Mausposition, clamped im Screen."""
        if not lines:
            return

        if font is None:
            font = self._fonts.get(16)

        sw, sh = screen.get_size()
        mx, my = pos

        pad = 10
        line_surfs = [font.render(str(t), True, (235, 235, 235)) for t in lines]
        w = max(s.get_width() for s in line_surfs) + pad * 2
        h = sum(s.get_height() for s in line_surfs) + pad * 2 + (len(line_surfs) - 1) * 4

        # Position leicht versetzt
        x = mx + 16
        y = my + 16

        # Clamp (damit nichts aus dem Screen läuft)
        if x + w > sw - 8:
            x = sw - w - 8
        if y + h > sh - 8:
            y = sh - h - 8
        x = max(8, x)
        y = max(8, y)

        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 190), panel.get_rect(), border_radius=10)
        pygame.draw.rect(panel, (220, 210, 180, 60), panel.get_rect(), 1, border_radius=10)
        screen.blit(panel, (x, y))

        yy = y + pad
        for s in line_surfs:
            screen.blit(s, (x + pad, yy))
            yy += s.get_height() + 4

    def _wrap_text(self, text: str, font: pygame.font.Font, max_w: int) -> list[str]:
        """Word-wrap für pygame fonts (keine Zeile breiter als max_w)."""
        words = text.split()
        if not words:
            return [""]

        lines = []
        cur = words[0]
        for w in words[1:]:
            test = cur + " " + w
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    def render(self, screen) -> None:
        world = self.ctx.world
        player = self.ctx.player
        # Map background (fixed)
        screen.blit(self._map_visual, (0, 0))

        # --- Sky clouds (fast path: precomputed surfaces) ---
        if getattr(self, "_cloud_instances", None):
            t = float(getattr(self, "_ship_time", 0.0))
            for c in self._cloud_instances:
                surf = c.get("surf")
                if not surf:
                    continue

                y = float(c["y"]) + math.sin(t * float(c["bob_spd"]) + float(c["bob_phase"])) * float(c["bob_amp"])
                screen.blit(surf, (int(c["x"]), int(y)))

        # --- Transition arrows (show where the world continues) ---
        if getattr(self, "_arrow_frames", None) and getattr(self, "_transition_markers", None):
            base = self._arrow_frames[int(getattr(self, "_arrow_frame_i", 0))]
            for m in self._transition_markers:
                (cx, cy) = m["pos"]
                d = m["dir"]

                img = base
                # assume base arrow points RIGHT
                if d == "E":
                    rot = 0
                elif d == "S":
                    rot = -90
                elif d == "W":
                    rot = 180
                elif d == "N":
                    rot = 90
                else:
                    rot = 0

                if rot != 0:
                    img = pygame.transform.rotate(img, rot)

                # scale a bit (optional)
                scale = 1.35
                if scale != 1.0:
                    w = max(1, int(img.get_width() * scale))
                    h = max(1, int(img.get_height() * scale))
                    img = pygame.transform.smoothscale(img, (w, h))

                r = img.get_rect(center=(int(cx), int(cy)))
                screen.blit(img, r.topleft)

        p = self.ctx.player
        ml = int(getattr(p, "master_lives", 0))
        ml_max = int(getattr(p, "master_lives_max", 3))

        # Bildschirmgröße merken für UI-Layout
        self._last_screen_w = screen.get_width()
        self._last_screen_h = screen.get_height()

        # -----------------------------
        # Master-Lives Anzeige (über Barometer)
        # -----------------------------
        p = self.ctx.player
        ml = int(getattr(p, "master_lives", 0))
        ml_max = int(getattr(p, "master_lives_max", 3))

        size = 48
        gap = 10
        sw, sh = screen.get_size()
        baro = getattr(self, "_baro_rect", None)

        # --------------- Dockable Cities + Signs + Prompts -----------------
        dockable_any = False
        ship_pos = self.ctx.player.ship.pos

        # Fallback, falls barometer rect nicht gesetzt
        if baro is not None:
            # --- Hover Rect für Barometer ---
            # --- Hover Rect für Barometer (robust: Surface oder Rect) ---
            if isinstance(baro, pygame.Rect):
                self._baro_rect = baro.copy()
            else:
                self._baro_rect = baro.get_rect(topleft=(20, 160))

            total_h = ml_max * size + (ml_max - 1) * gap
            start_y = baro.centery - total_h // 2

            # negative Werte = Herzen rücken näher an die sichtbare Barometer-Kante (überlappen in den Baro-Rect)
            pad = -60  # <- bei Bedarf -10 / -24 feinjustieren
            start_x = max(8, baro.left - size - pad)

            sh = screen.get_height()
            start_y = max(8, min(sh - total_h - 8, start_y))
        else:
            self._baro_rect = None
            start_x = 24
            start_y = 24

        # --- Hover Rect für Masterleben ---
        total_h = ml_max * size + (ml_max - 1) * gap
        self._ml_rect = pygame.Rect(start_x, start_y, size, total_h)

        if self._ml_icon is not None:
            icon = getattr(self, "_ml_icon_scaled_cache", {}).get(size)
            if icon is None:
                if not hasattr(self, "_ml_icon_scaled_cache"):
                    self._ml_icon_scaled_cache = {}
                icon = pygame.transform.smoothscale(self._ml_icon, (size, size))
                self._ml_icon_scaled_cache[size] = icon

            for i in range(ml_max):
                ic = icon.copy()
                if i >= ml:
                    ic.set_alpha(70)
                screen.blit(ic, (start_x, start_y + i * (size + gap)))

        else:
            # Fallback ohne Icon
            for i in range(ml_max):
                col = (230, 230, 230) if i < ml else (120, 120, 120)
                pygame.draw.circle(
                    screen,
                    col,
                    (start_x + i * (size + gap) + size // 2,
                    start_y + size // 2),
                    size // 2 - 4,
                )

        from settings import DOCK_RADIUS_MULT, DOCK_RADIUS_BONUS  # <-- EINMAL oben bei den Imports platzieren

        # Draw cities
        for c in world.cities:
            # ✅ WICHTIG: zuerst Map filtern, dann erst dock/hover/glow!
            if getattr(c, "map_id", "world_01") != self.ctx.current_map_id:
                continue

            # --- Dock-Check: ist diese Stadt aktuell in Reichweite? ---
            ship_pos = self.ctx.player.ship.pos
            hx, hy = self._city_harbors.get(c.id, c.pos)
            dx = hx - ship_pos[0]
            dy = hy - ship_pos[1]

            dist = (dx*dx + dy*dy) ** 0.5
            dock_r = c.harbor_radius * DOCK_RADIUS_MULT + DOCK_RADIUS_BONUS
            dockable = dist <= dock_r

            if dockable and not dockable_any:
                dockable_any = True
                dock_city = c

            # --- Glow (nur auf aktueller Map) ---
            if dockable:
                self._draw_city_glow(screen, c.pos, base_r=28)

            # --- Schild ---
            sign = self._get_city_sign(c.name)
            if sign is not None:
                sx = c.pos[0] - (sign.get_width() // 2)
                sy = c.pos[1] - (sign.get_height() // 2)
                screen.blit(sign, (sx, sy))

        # --- Dock-Prompt beim Schiff ---
        if dockable_any:
            ship_x, ship_y = ship_pos

            prompt_text = self.ctx.i18n.t("ui.dock_prompt", key="E")

            # größere & dickere Schrift
            prompt_font = self._fonts.get(24, bold=True)

            # Position leicht rechts oberhalb vom Schiff
            px = ship_x + 18
            py = ship_y - 28

            self._draw_prompt_box(
                screen,
                prompt_text,
                (px, py),
                prompt_font,
                padding=6,
                bg_alpha=150
            )

        # HUD
        day = self.ctx.clock.day
        paused = self.ctx.i18n.t("hud.paused") if self.ctx.clock.paused else ""
        hud_text = self.ctx.i18n.t("hud.day_timescale", day=day, scale=float(self.ctx.clock.time_scale), paused=paused)
        hud = self.font.render(hud_text, True, (200, 200, 200))
        screen.blit(hud, (20, 20))

        # --- UI background box for XP + Gold (bottom-left) ---
        sw, sh = screen.get_size()

        box_x = -4          # etwas vom Rand weg
        box_w = 220        # Breite der UI-Spalte
        box_h = 180        # Höhe für XP + Gold
        box_y = sh - box_h - 4

        ui_bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(
            ui_bg,
            (0, 0, 0, 130),   # Schwarz, transparent
            ui_bg.get_rect(),
            border_radius=16
        )

        screen.blit(ui_bg, (box_x, box_y))

        # --- Gold Anzeige (Icon + Text, ohne Hintergrundbox) ---
        money = int(getattr(self.ctx.player, "money", 0))
        money_txt = f"{money:,}".replace(",", ".")

        gx, gy = 10, 540  # feste Position

        icon = getattr(self, "_gold_icon_scaled", None)
        txt_surf = self.font.render(money_txt, True, (235, 235, 200))
        txt_w, txt_h = txt_surf.get_size()

        gap = 10  # Abstand Icon → Text

        if icon is not None:
            iw, ih = icon.get_size()

            # Text vertikal mittig zum Icon ausrichten
            ty = gy + (ih - txt_h) // 2
            tx = gx + iw + gap

            screen.blit(icon, (gx, gy))
            screen.blit(txt_surf, (tx, ty))
        else:
            # Fallback ohne Icon
            screen.blit(txt_surf, (gx, gy))




        # Draw wake (Particles)
        self._wake.render(screen)

        # Draw ship (Sprite)
        ship_name = self.ctx.content.ships[player.ship.id].name  # "Schaluppe"
        sprite = self._get_ship_sprite(ship_name)


        if sprite is not None:
            x, y = player.ship.pos

            # Idle-Bobbing nur visuell
            vel = pygame.Vector2(player.ship.vel[0], player.ship.vel[1])
            spd = vel.length()

            bob = 0.0
            roll_deg = 0.0
            if spd < 10.0:
                bob = math.sin(self._ship_time * 2.0) * 2.0
                roll_deg = math.sin(self._ship_time * 1.4) * 3.0


            # Heading -> Grad (pygame rotozoom nutzt Grad)
            # Achtung: Sprite-Ausrichtung: falls dein PNG "nach oben" zeigt, musst du -90° offset geben.
            heading_deg = -player.ship.heading * 57.29577951308232  # rad->deg

            rotated = pygame.transform.rotozoom(sprite, heading_deg + roll_deg, 1.0)
            rect = rotated.get_rect(center=(int(x), int(y + bob)))
            screen.blit(rotated, rect)
            

        else:
            pygame.draw.circle(screen, (240, 240, 120), player.ship.pos, 6)

        ship = self.ctx.player.ship
        x, y = int(ship.pos[0]), int(ship.pos[1])

        self._render_barometer(screen)

        # --- Hover Tooltips (nur eins zur Zeit) ---
        if not getattr(self, "_intro_open", False) and not getattr(self, "_stats_open", False):
            mx, my = pygame.mouse.get_pos()
            mouse = (mx, my)

            # --- Tooltip candidates (priority) ---
            candidates = []

            mx, my = pygame.mouse.get_pos()
            mouse = (mx, my)

            # STATS button tooltip (example if you have it in this block)
            r = getattr(self, "_stats_btn_rect", None)
            if r is not None and r.collidepoint(mx, my):
                candidates.append(("STATS", [self.ctx.i18n.t("stats.title")]))

            # XP panel tooltip
            r = getattr(self, "_xp_panel_rect", None)
            if r is not None and r.collidepoint(mx, my):
                xp = int(getattr(self.ctx.player, "xp", 0))
                lvl, cur, need = xp_to_level(xp)

                if lvl >= 10 or need <= 0:
                    lines = [
                        self.ctx.i18n.t("tip.xp.level_max", lvl=lvl),
                        self.ctx.i18n.t("tip.xp.total", xp=xp),
                    ]
                else:
                    remaining = max(0, int(need - cur))
                    lines = [
                        self.ctx.i18n.t("tip.xp.level", lvl=lvl),
                        self.ctx.i18n.t("tip.xp.total", xp=xp),
                        self.ctx.i18n.t("tip.xp.progress", cur=int(cur), need=int(need)),
                        self.ctx.i18n.t("tip.xp.to_next", next_lvl=lvl + 1, remaining=remaining),
                    ]
                candidates.append(("XP", lines))  # <- BUGFIX: lines exist

            # Master lives tooltip
            r = getattr(self, "_ml_rect", None)
            if r is not None and r.collidepoint(mx, my):
                p = self.ctx.player
                ml = int(getattr(p, "master_lives", 0))
                ml_max = int(getattr(p, "master_lives_max", 3))
                candidates.append(("ML", [
                    self.ctx.i18n.t("tip.ml.title"),
                    self.ctx.i18n.t("tip.ml.value", cur=ml, max=ml_max),
                    self.ctx.i18n.t("tip.ml.l1"),
                    self.ctx.i18n.t("tip.ml.l2"),
                    self.ctx.i18n.t("tip.ml.l3"),
                ]))

            # Danger meter tooltip
            r = getattr(self, "_baro_rect", None)
            if r is not None and r.collidepoint(mx, my):
                candidates.append(("BARO", [
                    self.ctx.i18n.t("tip.baro.title"),
                    self.ctx.i18n.t("tip.baro.l1"),
                    self.ctx.i18n.t("tip.baro.l2"),
                    self.ctx.i18n.t("tip.baro.l3"),
                ]))

            # Draw only first hit
            if candidates:
                _tag, lines = candidates[0]
                self._draw_tooltip(screen, mouse, lines, font=self._fonts.get(16))

        self._draw_xp_bar(screen)
                
        self._render_stats_button(screen)
        if self._stats_open:
            self._render_stats_menu(screen)

        # --- Goal Tracker (Hauptquest) ---
        money = int(getattr(self.ctx.player, "money", 0))
        goal = int(getattr(self, "_goal_gold", int(getattr(settings, "WIN_GOLD_TARGET", 15000))))
        goal_font = self._fonts.get(18, bold=True)
        sub_font  = self._fonts.get(16)

        title_txt = self.ctx.i18n.t("goal.title")
        line_txt  = self.ctx.i18n.t("goal.line", goal=f"{goal:,}".replace(",", "."), money=f"{money:,}".replace(",", "."))
        title = goal_font.render(title_txt, True, (245, 235, 210))
        line  = sub_font.render(line_txt,  True, (230, 230, 230))

        pad = 12
        w = max(title.get_width(), line.get_width()) + pad * 2
        h = title.get_height() + line.get_height() + pad * 2 + 6

        sw, sh = screen.get_size()
        x = sw - w - 16
        y = 16

        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (0, 0, 0, 140), panel.get_rect(), border_radius=14)
        screen.blit(panel, (x, y))
        screen.blit(title, (x + pad, y + pad))
        screen.blit(line,  (x + pad, y + pad + title.get_height() + 6))

        # --- Controls Hint (WASD) ---
        if not getattr(self.ctx, "_loaded_from_save", False):
            t = float(getattr(self, "_controls_hint_t", 0.0))
            dur = float(getattr(self, "_controls_hint_duration", 0.0))
            if dur <= 0.0 or t <= dur:
                # leichtes Fade-out gegen Ende
                alpha = 220
                if dur > 0.0 and t > dur - 2.0:
                    k = max(0.0, min(1.0, (dur - t) / 2.0))  # 2s fade
                    alpha = int(220 * k)

                hint_font = self._fonts.get(16)
                l1 = hint_font.render(self.ctx.i18n.t("controls.title"), True, (245, 235, 210))
                l2 = hint_font.render(self.ctx.i18n.t("controls.l2"), True, (230, 230, 230))
                l3 = hint_font.render(self.ctx.i18n.t("controls.l3"), True, (200, 200, 200))

                pad = 12
                w = max(l1.get_width(), l2.get_width(), l3.get_width()) + pad * 2
                h = l1.get_height() + l2.get_height() + l3.get_height() + pad * 2 + 10

                sw, sh = screen.get_size()
                x = sw - w - 16
                y = 16 + 74  # unter dem Hauptziel-Panel; ggf. feinjustieren

                panel = pygame.Surface((w, h), pygame.SRCALPHA)
                pygame.draw.rect(panel, (0, 0, 0, max(0, min(255, int(alpha * 0.65)))), panel.get_rect(), border_radius=14)
                screen.blit(panel, (x, y))

                # Text leicht mit eigenem Alpha
                def blit_alpha(surf, pos):
                    tmp = surf.copy()
                    tmp.set_alpha(alpha)
                    screen.blit(tmp, pos)

                blit_alpha(l1, (x + pad, y + pad))
                blit_alpha(l2, (x + pad, y + pad + l1.get_height() + 4))
                blit_alpha(l3, (x + pad, y + pad + l1.get_height() + l2.get_height() + 8))

    def _render_barometer(self, screen: pygame.Surface) -> None:
        # --- Intro Overlay Render (modal) ---
        if getattr(self, "_intro_open", False):
            sw, sh = screen.get_size()

            # dim background
            dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 170))
            screen.blit(dim, (0, 0))

            title_font = self._fonts.get(38, bold=True)
            body_font  = self._fonts.get(22)
            hint_font  = self._fonts.get(16)

            # Panel sizing
            max_text_w = int(sw * 0.62) - 48
            paragraphs = getattr(self, "_intro_paragraphs", [])
            wrapped = []
            for p in paragraphs:
                wrapped.extend(self._wrap_text(p, body_font, max_text_w))
                wrapped.append("")  # Absatzabstand
            if wrapped and wrapped[-1] == "":
                wrapped.pop()

            line_h = body_font.get_linesize()
            content_h = len(wrapped) * line_h

            pw = int(sw * 0.62)
            ph = min(int(sh * 0.78), content_h + 140)  # 140 = Title+Padding+Hint
            px = (sw - pw) // 2
            py = (sh - ph) // 2
            panel = pygame.Rect(px, py, pw, ph)

            # panel draw
            panel_surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
            pygame.draw.rect(panel_surf, (0, 0, 0, 210), panel_surf.get_rect(), border_radius=18)
            screen.blit(panel_surf, panel.topleft)

            # title
            title = title_font.render(getattr(self, "_intro_title", "ZIEL"), True, (245, 235, 210))
            screen.blit(title, (panel.x + 24, panel.y + 20))

            # body
            y = panel.y + 78
            max_y = panel.bottom - 60  # Platz für Hint
            for line in wrapped:
                if y + line_h > max_y:
                    break  # Safety: niemals über den Rand
                if line == "":
                    y += int(line_h * 0.6)
                    continue
                surf = body_font.render(line, True, (230, 230, 230))
                screen.blit(surf, (panel.x + 24, y))
                y += line_h

            # hint
            hint = hint_font.render(self.ctx.i18n.t("intro.hint"), True, (200, 200, 200))
            screen.blit(hint, (panel.x + 24, panel.bottom - 34))


        """
        Renders the barometer frame and moves the skull marker
        vertically based on _enc_meter (0..1).
        """
        meter = max(0.0, min(1.0, float(getattr(self, "_enc_meter", 0.0))))

        # Position: rechts, leicht eingerückt
        # Position: unten rechts
        margin_x = -65
        margin_y = -50
        x = screen.get_width() - self._baro_w - margin_x
        y = screen.get_height() - self._baro_h - margin_y
        self._baro_rect = pygame.Rect(x, y, self._baro_w, self._baro_h)

        # --- Frame ---
        screen.blit(self._barometer_frame, (x, y))

        # --- Marker movement ---
        # Marker bewegt sich innerhalb des Frames (oben/unten etwas Padding)
        padding_top = int(self._baro_h * 0.08)
        padding_bottom = int(self._baro_h * 0.25)

        track_top = y + padding_top
        track_bottom = y + self._baro_h - padding_bottom - self._marker_h
        track_height = track_bottom - track_top

        # 0.0 = unten (SAFE), 1.0 = oben (DANGER)
        marker_y = track_bottom - int(track_height * meter)
        marker_x = track_top + (track_height - self._marker_w) // 2


        t = float(getattr(self, "_ui_t", 0.0))

        # --- Float (immer aktiv) ---
        float_px = int(math.sin(t * 2.2) * 2)
        marker_y += float_px

        # --- Shake nur bei hoher Gefahr ---
        if meter > 0.80:
            strength = (meter - 0.80) / 0.20  # 0..1
            shake = int(math.sin(t * 28.0) * (1 + 2 * strength))
            marker_x += shake



        # Marker in der Säule zentrieren (nicht über das gesamte Gehäuse)
        pillar_left = x + (self._baro_w - self._baro_pillar_w) // 2
        marker_x = pillar_left + (self._baro_pillar_w - self._marker_w) // 2


        marker_surf = self._get_animated_marker_surface(meter, t)
        mx = marker_x + (self._marker_w - marker_surf.get_width()) // 2
        my = marker_y + (self._marker_h - marker_surf.get_height()) // 2
        screen.blit(marker_surf, (mx, my))

    def _render_stats_button(self, screen: pygame.Surface) -> None:
        if getattr(self, "_stats_btn", None) is None:
            return
        if not hasattr(self, "_baro_rect"):
            return

        base = self._stats_btn
        hover_img = getattr(self, "_stats_btn_hover_img", None)

        bw, bh = base.get_width(), base.get_height()
        x = self._baro_rect.centerx - bw // 2
        y = self._baro_rect.top - bh - 10
        self._stats_btn_rect = pygame.Rect(x, y, bw, bh)

        mx, my = pygame.mouse.get_pos()
        hover = self._stats_btn_rect.collidepoint(mx, my)

        # Use hover flame image if available, else fall back to base
        if hover and hover_img is not None:
            screen.blit(hover_img, (x, y))
        else:
            screen.blit(base, (x, y))

        # Rect ist bereits korrekt gesetzt:
        # self._stats_btn_rect = pygame.Rect(x, y, bw, bh)

    def _render_stats_menu(self, screen: pygame.Surface) -> None:
        # dim background
        dim = pygame.Surface((screen.get_width(), screen.get_height()), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        screen.blit(dim, (0, 0))

        panel = self._get_stats_panel_rect()

        # --- background for stats menu (overscan to hide transparent edges) ---
        bg = getattr(self, "_bg_stats", None)
        if bg is not None:
            overscan = 1.4  # 8% größer als Panel (fein justierbar)

            bw = int(panel.w * overscan)
            bh = int(panel.h * overscan)

            bg_scaled = pygame.transform.smoothscale(bg, (bw, bh))

            # center the oversized bg onto the panel
            bx = panel.x - (bw - panel.w) // 2
            by = panel.y - (bh - panel.h) // 2

            screen.blit(bg_scaled, (bx, by))
            # --- text readability overlay (subtle dark layer) ---
            overlay = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 80))  # Schwarz mit leichter Transparenz (0–255)
            screen.blit(overlay, (panel.x, panel.y))

        else:
            fallback = pygame.Surface((panel.w, panel.h), pygame.SRCALPHA)
            fallback.fill((20, 20, 24, 235))
            screen.blit(fallback, (panel.x, panel.y))


        # fonts
        title_font = self._fonts.get(28) if hasattr(self, "_fonts") else self.font
        body_font = self._fonts.get(18) if hasattr(self, "_fonts") else self.font
        small_font = self._fonts.get(14) if hasattr(self, "_fonts") else self.small

        def draw_text(font, text, x, y, color=(240, 240, 240)):
            surf = font.render(text, True, color)
            screen.blit(surf, (x, y))
            return surf.get_height()

        # layout regions
        padding = 16
        title_h = 52      # reserved for title area
        footer_h = 34     # reserved for hint
        # leave room on right for scrollbar
        content_rect = pygame.Rect(
            panel.x + padding,
            panel.y + title_h,
            panel.w - padding * 2 - 14,
            panel.h - title_h - footer_h
        )
        self._stats_view_h = content_rect.h

        # title (not clipped)
        x0 = panel.x + 18
        y_title = panel.y + 14
        draw_text(title_font, self.ctx.i18n.t("stats.menu.title"), x0, y_title)

        # gather data
        player = getattr(self.ctx, "player", None)
        ship = getattr(player, "ship", None) if player else None
        ps = getattr(self.ctx, "player_stats", None)

        shipdef = None
        ship_combat = None
        if ship is not None and getattr(self.ctx, "content", None) is not None:
            shipdef = self.ctx.content.ships.get(getattr(ship, "id", ""))
            ship_combat = getattr(shipdef, "combat", None) if shipdef else None

        def fmt_pct(p: float) -> str:
            try:
                p = float(p)
            except Exception:
                p = 0.0
            return f"{p * 100:.0f}%"

        def fmt_mult(v: float) -> str:
            try:
                v = float(v)
            except Exception:
                v = 1.0
            pct = (v - 1.0) * 100.0
            sign = "+" if pct >= 0 else ""
            return f"x{v:.2f} ({sign}{pct:.0f}%)"

        def add_section(lines: list[tuple[str, str]], heading: str, rows: list[tuple[str, str]]) -> None:
            lines.append(("_H", heading))
            for k, v in rows:
                lines.append((k, v))

        lines: list[tuple[str, str]] = []

        # --- Ship combat section ---
        if shipdef and ship_combat:
            base_min = int(getattr(ship_combat, "damage_min", 0))
            base_max = int(getattr(ship_combat, "damage_max", 0))
            dtype = str(getattr(ship_combat, "damage_type", "physical"))
            pen = float(getattr(ship_combat, "penetration", 0.0))
            aphys = float(getattr(ship_combat, "armor_physical", 0.0))
            aaby = float(getattr(ship_combat, "armor_abyssal", 0.0))
            cc = float(getattr(ship_combat, "crit_chance", 0.0))
            cm = float(getattr(ship_combat, "crit_multiplier", 1.5))
            ini = float(getattr(ship_combat, "initiative_base", 1.0))

            dmg_mult = float(getattr(ps, "cannon_damage_mult", 1.0)) if ps else 1.0
            eff_min = int(round(base_min * dmg_mult))
            eff_max = int(round(base_max * dmg_mult))

            hp_cur = int(getattr(ship, "hp", 0))
            hp_max = int(getattr(ship, "hp_max", int(getattr(ship_combat, "hp_max", 0))))

            add_section(
                lines,
                self.ctx.i18n.t("stats.section.ship_combat"),
                [
                    (self.ctx.i18n.t("stats.label.ship"), str(getattr(shipdef, "name", getattr(shipdef, "id", "unknown")))),
                    (self.ctx.i18n.t("stats.label.hp"), f"{hp_cur}/{hp_max}"),
                    (self.ctx.i18n.t("stats.label.armor_phys"), f"{aphys:.1f}"),
                    (self.ctx.i18n.t("stats.label.armor_abyss"), f"{aaby:.1f}"),
                    (self.ctx.i18n.t("stats.label.atk_base"), f"{base_min}-{base_max} ({dtype})"),
                    (self.ctx.i18n.t("stats.label.atk_eff"), f"{eff_min}-{eff_max}  [x{dmg_mult:.2f}]"),
                    (self.ctx.i18n.t("stats.label.pen"), f"{pen:.1f}"),
                    (self.ctx.i18n.t("stats.label.crit"), f"{fmt_pct(cc)}  x{cm:.2f}"),
                    (self.ctx.i18n.t("stats.label.initiative"), f"{ini:.2f}"),
                ],
            )
        else:
            add_section(
                lines,
                self.ctx.i18n.t("stats.section.ship_combat"),
                [(self.ctx.i18n.t("stats.label.info"), self.ctx.i18n.t("stats.msg.no_ship_data"))],
            )

        # --- Player modifiers section ---
        add_section(
            lines,
            self.ctx.i18n.t("stats.section.player_mods"),
            [
                (self.ctx.i18n.t("stats.mod.cannon_damage"), fmt_mult(getattr(ps, "cannon_damage_mult", 1.0) if ps else 1.0)),
                (self.ctx.i18n.t("stats.mod.reload_speed"), fmt_mult(getattr(ps, "reload_mult", 1.0) if ps else 1.0)),
                (self.ctx.i18n.t("stats.mod.boarding_damage"), fmt_mult(getattr(ps, "boarding_damage_mult", 1.0) if ps else 1.0)),
                (self.ctx.i18n.t("stats.mod.repair_power"), fmt_mult(getattr(ps, "repair_mult", 1.0) if ps else 1.0)),
                (self.ctx.i18n.t("stats.mod.evade"), fmt_mult(getattr(ps, "evade_mult", 1.0) if ps else 1.0)),
                (self.ctx.i18n.t("stats.mod.flee"), fmt_mult(getattr(ps, "flee_mult", 1.0) if ps else 1.0)),
            ],
        )

        # --- Progression section ---
        if player is not None:
            add_section(
                lines,
                self.ctx.i18n.t("stats.section.progression"),
                [
                    (self.ctx.i18n.t("stats.progress.gold"), str(getattr(player, "money", 0))),
                    (self.ctx.i18n.t("stats.progress.xp"), str(getattr(player, "xp", 0))),
                    (self.ctx.i18n.t("stats.progress.master_lives"), f"{getattr(player, 'master_lives', 0)}/{getattr(player, 'master_lives_max', 0)}"),
                ],
            )

        # render content (clipped)
        prev_clip = screen.get_clip()
        screen.set_clip(content_rect)

        y = content_rect.y - int(getattr(self, "_stats_scroll", 0))

        line_h = 26
        gap_h = 12
        heading_h = 20

        for key, val in lines:
            if key == "_H":
                # heading
                draw_text(small_font, val, x0, y, (180, 180, 190))
                y += heading_h
                continue

            draw_text(body_font, f"{key}:", x0, y, (220, 220, 230))
            draw_text(body_font, str(val), x0 + 220, y, (240, 240, 240))
            y += line_h

            # section spacing heuristic: after certain labels, add a gap
            gap_after = {
                self.ctx.i18n.t("stats.label.initiative"),
                self.ctx.i18n.t("stats.mod.flee"),
                self.ctx.i18n.t("stats.progress.master_lives"),
                self.ctx.i18n.t("stats.label.info"),
            }
            if key in gap_after:
                y += gap_h

        # compute content height for scrolling
        self._stats_content_h = max(0, (y + int(getattr(self, "_stats_scroll", 0))) - content_rect.y)

        # reset clip
        screen.set_clip(prev_clip)

        # clamp scroll after knowing content height (important if content shrank)
        self._clamp_stats_scroll()

        # scrollbar
        max_scroll = max(0, int(self._stats_content_h) - int(self._stats_view_h))
        if max_scroll > 0:
            track = pygame.Rect(content_rect.right + 6, content_rect.y, 6, content_rect.h)
            pygame.draw.rect(screen, (60, 60, 70), track, border_radius=3)

            knob_h = max(24, int(track.h * (self._stats_view_h / max(1, self._stats_content_h))))
            t = float(getattr(self, "_stats_scroll", 0)) / max_scroll
            knob_y = int(track.y + t * (track.h - knob_h))
            knob = pygame.Rect(track.x, knob_y, track.w, knob_h)
            pygame.draw.rect(screen, (170, 170, 185), knob, border_radius=3)

        # hint (not clipped)
        hint = self.ctx.i18n.t("stats.hint")
        draw_text(small_font, hint, x0, panel.bottom - 24, (180, 180, 190))

    def _get_animated_marker_surface(self, meter: float, t: float) -> pygame.Surface:
        """
        Marker Surface: nur leichte Scale-Animation (kein Alpha), damit volle Farbe erhalten bleibt.
        """
        base = self._barometer_marker

        danger = max(0.0, min(1.0, (meter - 0.40) / 0.60))  # ab ~40% stärker
        pulse = (math.sin(t * 6.0) * 0.5 + 0.5)  # 0..1
        scale = 1.0 + (0.01 + 0.04 * danger) * pulse  # subtil: 1%..5%

        bw = max(1, int(base.get_width() * scale))
        bh = max(1, int(base.get_height() * scale))

        key = ("marker", bw, bh)
        cache = getattr(self, "_baro_marker_cache", None)
        if cache is None:
            self._baro_marker_cache = {}
            cache = self._baro_marker_cache

        surf = cache.get(key)
        if surf is None:
            surf = pygame.transform.smoothscale(base, (bw, bh)).convert_alpha()
            cache[key] = surf
            if len(cache) > 96:
                cache.clear()

        return surf

    def _draw_xp_bar(self, screen) -> None:
        xp = int(getattr(self.ctx.player, "xp", 0))
        lvl, cur, need = xp_to_level(xp)
        frac = 0.0 if need <= 0 else max(0.0, min(1.0, cur / need))

        # MAX-Level immer voll anzeigen
        if lvl >= 10:
            frac = 1.0

        # Panel-Variante (wenn xp.png vorhanden)
        if getattr(self, "_xp_panel", None) is not None:
            sw, sh = screen.get_size()
            margin = -10

            r = self._xp_panel.get_rect(bottomleft=(margin, sh - margin))
            self._xp_panel_rect = r

            # 1) Panel zuerst (Frame/Background)
            screen.blit(self._xp_panel, r.topleft)

            # 2) Fill (sichtbarer Anteil) – vertikal gestreckt
            if getattr(self, "_xp_fill", None) is not None:
                fill_pad_left = 22
                fill_pad_right = 22
                fill_y = 26
                fill_h = 64  # <- DAS ist deine neue sichtbare Höhe (hier einstellen)

                fill_rect = pygame.Rect(
                    r.x + fill_pad_left,
                    r.y + fill_y,
                    r.width - fill_pad_left - fill_pad_right,
                    fill_h
                )

                visible = 0.10 + 0.90 * frac
                vis_w = max(1, min(fill_rect.width, int(fill_rect.width * visible)))

                # Source slice: gleiche Koordinaten wie Panel, aber IMMER innerhalb des Fill-Bilds
                src_x = fill_pad_left
                src_y = fill_y
                src_area = pygame.Rect(src_x, src_y, vis_w, fill_h)
                screen.blit(self._xp_fill, fill_rect.topleft, src_area)

    def _get_ship_sprite(self, ship_type: str) -> pygame.Surface | None:
        # Robust: falls on_enter() nicht gelaufen ist
        if not hasattr(self, "_ship_sprite_cache"):
            self._ship_sprite_cache = {}
        if not hasattr(self, "_ship_sprite_size"):
            self._ship_sprite_size = (42, 42)

        key = (ship_type, self._ship_sprite_size)
        if key in self._ship_sprite_cache:
            return self._ship_sprite_cache[key]

        p = os.path.join("assets", "ships", f"{ship_type}.png")
        if not os.path.exists(p):
            self._ship_sprite_cache[key] = None
            return None

        img = pygame.image.load(p).convert_alpha()
        img = pygame.transform.scale(img, self._ship_sprite_size)
        self._ship_sprite_cache[key] = img
        return img

    def _get_city_sign(self, city_name: str) -> pygame.Surface | None:
        """
        Lädt ein City-Schild aus assets/ui/cities/<city_name>.png und cached es.
        Fallback: None, wenn Datei fehlt oder Fehler.
        """
        cache = getattr(self, "_city_sign_cache", None)
        if cache is None:
            self._city_sign_cache = {}
            cache = self._city_sign_cache

        if city_name in cache:
            return cache[city_name]

        safe = city_name.strip().lower()
        path = os.path.join("assets", "ui", "cities", f"{city_name}.png")
        if not os.path.exists(path):
            safe = city_name.strip().lower()
            path = os.path.join("assets", "ui", "cities", f"{safe}.png")
            return None

        try:
            img = pygame.image.load(path).convert_alpha()

            # --- Auto-Scale auf feste Höhe ---
            target_h = int(getattr(self, "_city_sign_target_h", 32))
            if target_h > 0 and img.get_height() != target_h:
                scale = target_h / img.get_height()
                new_w = max(1, int(img.get_width() * scale))
                img = pygame.transform.smoothscale(img, (new_w, target_h))

            cache[city_name] = img
            return img
        except Exception:
            cache[city_name] = None
            return None


    def _load_and_scale_visual(self, path: str) -> pygame.Surface:
        img = pygame.image.load(path).convert_alpha()
        if img.get_size() != (SCREEN_W, SCREEN_H):
            img = pygame.transform.smoothscale(img, (SCREEN_W, SCREEN_H))
        return img

    def _load_and_scale_nav(self, path: str) -> pygame.Surface:
        # WICHTIG: Nav-Maske ohne smoothscale, damit Farben exakt bleiben
        img = pygame.image.load(path).convert()  # keine Alpha nötig
        if img.get_size() != (SCREEN_W, SCREEN_H):
            img = pygame.transform.scale(img, (SCREEN_W, SCREEN_H))  # nearest neighbor
        return img


    def _is_sailable(self, x: float, y: float) -> bool:
        ix = int(x)
        iy = int(y)
        if ix < 0 or iy < 0 or ix >= SCREEN_W or iy >= SCREEN_H:
            return False

        r, g, b, *_ = self._map_nav.get_at((ix, iy))

        # Wasser: Blau (deine Navmap) – tolerant
        is_blue_water = (b >= 200 and r <= 60 and g <= 60)

        # Optional: Weiß als "Küstenwasser" / befahrbar – tolerant
        is_white = (r >= 230 and g >= 230 and b >= 230)

        return is_blue_water or is_white



    def _ensure_ship_on_water(self) -> None:
        # Wenn das Schiff auf Land startet, suche in kleinem Radius die nächste Wasserzelle
        ship = self.ctx.player.ship
        x0, y0 = ship.pos
        if self._is_sailable(x0, y0):
            return

        # Spiralsuche / Radius-Suche (klein, einmalig)
        for radius in range(1, 80):
            for dx in range(-radius, radius + 1):
                for dy in (-radius, radius):
                    x = x0 + dx
                    y = y0 + dy
                    if self._is_sailable(x, y):
                        ship.pos = (x, y)
                        return
            for dy in range(-radius + 1, radius):
                for dx in (-radius, radius):
                    x = x0 + dx
                    y = y0 + dy
                    if self._is_sailable(x, y):
                        ship.pos = (x, y)
                        return

    def _build_city_harbors(self) -> None:
        """
        Ermittelt für jede Stadt eine Hafenposition (Wasserpixel) nahe der Stadtposition (Land).
        Speichert Ergebnis in self._city_harbors[city.id] = (hx, hy)
        """
        world = self.ctx.world
        for c in world.cities:
            if c.map_id != self.ctx.current_map_id:
                continue
            if getattr(c, "map_id", "world_01") != self.ctx.current_map_id:
                continue
            cx, cy = c.pos
            hx, hy = self._find_nearest_sailable(cx, cy, max_radius=220)
            self._city_harbors[c.id] = (hx, hy)

            # optional: falls du lieber direkt am City-Objekt speichern willst
            try:
                setattr(c, "harbor_pos", (hx, hy))
            except Exception:
                pass

    def _find_nearest_sailable(self, x: float, y: float, max_radius: int = 220) -> tuple[float, float]:
        """
        Sucht im wachsenden Radius um (x,y) das nächste befahrbare Pixel.
        Nutzt self._nav_grid (NumPy-frei).
        """
        x0 = int(x)
        y0 = int(y)

        # falls City-Pos schon auf Wasser liegt (sollte nicht, aber robust)
        if self._is_sailable(x0, y0):
            return float(x0), float(y0)

        for r in range(1, max_radius + 1):
            # Top & Bottom
            y_top = y0 - r
            y_bot = y0 + r
            for xx in range(x0 - r, x0 + r + 1):
                if 0 <= xx < SCREEN_W:
                    if 0 <= y_top < SCREEN_H and self._nav_grid[xx][y_top]:
                        return float(xx), float(y_top)
                    if 0 <= y_bot < SCREEN_H and self._nav_grid[xx][y_bot]:
                        return float(xx), float(y_bot)

            # Left & Right (ohne Ecken doppelt)
            x_left = x0 - r
            x_right = x0 + r
            for yy in range(y0 - r + 1, y0 + r):
                if 0 <= yy < SCREEN_H:
                    if 0 <= x_left < SCREEN_W and self._nav_grid[x_left][yy]:
                        return float(x_left), float(yy)
                    if 0 <= x_right < SCREEN_W and self._nav_grid[x_right][yy]:
                        return float(x_right), float(yy)

        # Fallback: wenn keine Wasserzelle gefunden wurde (Maske/City-Pos kaputt)
        return float(x0), float(y0)

    def _spawn_ship_at_start_harbor(self) -> None:
        """
        Setzt das Schiff an den Hafen der Startstadt.
        Primärquelle: ctx.start_city_id (aus SetupState).
        Fallback: erste Stadt in world.cities.
        """
        player = self.ctx.player
        world = self.ctx.world

        start_city = None  # <-- WICHTIG: Initialisierung, damit kein UnboundLocalError entsteht

        # 1) Startstadt aus ctx (Setup)
        start_city_id = getattr(self.ctx, "start_city_id", None)

        # 2) Optionaler Fallback, falls du später Player-Felder einführst
        if not start_city_id:
            start_city_id = getattr(player, "start_city_id", None) or getattr(player, "home_city_id", None)

        # 3) City anhand ID finden
        if start_city_id:
            for c in world.cities:
                if c.id == start_city_id:
                    start_city = c
                    break

        # 4) Fallback: erste Stadt
        if start_city is None and world.cities:
            start_city = world.cities[0]

        if start_city is None:
            return  # keine Städte definiert

        harbor_pos = self._city_harbors.get(start_city.id, start_city.pos)

        # Spawn direkt auf Hafenwasser
        player.ship.pos = harbor_pos

    def _draw_city_glow(self, screen: pygame.Surface, pos: tuple[float, float], base_r: int = 26) -> None:
        """
        Pulsierender Glow für dockbare Städte.
        Zeichnet ein weiches, mehrlagiges Leuchten (Alpha-Circles) auf ein kleines Overlay.
        """
        x, y = int(pos[0]), int(pos[1])

        # Puls (0..1)
        t = pygame.time.get_ticks() / 1000.0
        pulse = 0.5 + 0.5 * math.sin(t * 3.0)  # Frequenz: 3.0 -> angenehmes Pulsieren

        r = int(base_r + pulse * 8)  # Radius pulsiert leicht
        pad = 6
        size = (r * 2 + pad * 2, r * 2 + pad * 2)

        glow = pygame.Surface(size, pygame.SRCALPHA)
        cx, cy = r + pad, r + pad

        # Farbe: leicht blau/cyan (passt zu Dock/Interaktion)
        col = (90, 170, 255)

        # Mehrere Lagen = "weicher" Glow
        # außen -> innen: groß mit wenig Alpha, innen -> stärker
        layers = [
            (r + 10, int(25 + pulse * 10)),
            (r + 6,  int(45 + pulse * 15)),
            (r + 2,  int(70 + pulse * 25)),
            (r,      int(90 + pulse * 35)),
        ]
        for rr, a in layers:
            pygame.draw.circle(glow, (*col, max(0, min(255, a))), (cx, cy), rr)

        screen.blit(glow, (x - cx, y - cy))
    def _draw_prompt_box(
        self,
        screen: pygame.Surface,
        text: str,
        pos: tuple[float, float],
        font: pygame.font.Font,
        padding: int = 6,
        bg_alpha: int = 160
    ):
        """
        Zeichnet Text mit schwarzem, halbtransparentem Hintergrund.
        pos = (x, y) ist die linke obere Ecke der Box.
        """
        # Text
        txt = font.render(text, True, (245, 245, 245))
        shadow = font.render(text, True, (0, 0, 0))

        w, h = txt.get_size()
        box = pygame.Surface((w + padding * 2, h + padding * 2), pygame.SRCALPHA)
        box.fill((0, 0, 0, bg_alpha))

        x, y = int(pos[0]), int(pos[1])

        # Box
        screen.blit(box, (x, y))
        # Shadow + Text
        screen.blit(shadow, (x + padding + 2, y + padding + 2))
        screen.blit(txt, (x + padding, y + padding))

    def _find_city_by_harbor_range(self, pos: tuple[float, float]):
        x, y = pos
        world = self.ctx.world
        cur_map = self.ctx.current_map_id
        from settings import DOCK_RADIUS_MULT, DOCK_RADIUS_BONUS

        best_city = None
        best_dist = None
        for c in world.cities:
            # WICHTIG: nur Cities der aktuellen Map berücksichtigen
            if getattr(c, "map_id", "world_01") != cur_map:
                continue

            hx, hy = self._city_harbors.get(c.id, c.pos)
            cx, cy = c.pos

            harbor_dist = ((hx - x) * (hx - x) + (hy - y) * (hy - y)) ** 0.5
            city_dist = ((cx - x) * (cx - x) + (cy - y) * (cy - y)) ** 0.5
            dist = min(harbor_dist, city_dist)
            dock_r = c.harbor_radius * DOCK_RADIUS_MULT + DOCK_RADIUS_BONUS

            if dist <= dock_r and (best_dist is None or dist < best_dist):
                best_city = c
                best_dist = dist

        return best_city


    def _spawn_ship_safely(self) -> None:
        """
        Spawnt das Schiff nur dann neu, wenn es keine valide Position hat.
        Wenn wir aus einer City kommen (ctx.last_city_id), setzen wir es an deren Hafen.
        """
        ship = self.ctx.player.ship

        # 1) Wenn wir eine valide Position haben und sie befahrbar ist -> nichts ändern
        x, y = ship.pos
        if (x, y) != (0, 0) and self._is_sailable(x, y):
            return

        # 2) Wenn wir zuletzt in einer City waren -> am Hafen dieser City spawnen
        last_city_id = getattr(self.ctx, "last_city_id", None)
        if last_city_id and last_city_id in self._city_harbors:
            ship.pos = self._city_harbors[last_city_id]
            return

        # 3) Fallback: Startstadt (falls gesetzt), sonst erste City
        self._spawn_ship_at_start_harbor()

    def _cycle_time_speed(self) -> None:
        # Reihenfolge: Pause -> 1x -> 2x -> 4x
        # Wir verwenden paused als echten Pause-Schalter, time_scale bleibt 1/2/4.
        if self.ctx.clock.paused:
            self.ctx.clock.paused = False
            self.ctx.clock.time_scale = TIME_SCALE_1X
            return

        ts = float(getattr(self.ctx.clock, "time_scale", TIME_SCALE_1X))
        if ts < 1.5:
            self.ctx.clock.time_scale = TIME_SCALE_2X
        elif ts < 3.0:
            self.ctx.clock.time_scale = TIME_SCALE_4X
        else:
            self.ctx.clock.paused = True
