from __future__ import annotations
import pygame
from dataclasses import dataclass
from typing import Optional
import os
from settings import SCREEN_W, SCREEN_H
import math
from settings import TIME_SCALE_PAUSE, TIME_SCALE_1X, TIME_SCALE_2X, TIME_SCALE_4X
from core.water_fx import WakeSystem   

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

        # aktuelle Map (default)
        if not hasattr(self.ctx, "current_map_id") or not self.ctx.current_map_id:
            self.ctx.current_map_id = "world_01"

        self.font = pygame.font.SysFont("arial", 22)
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

        self._load_current_map_assets()
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



    def update(self, dt: float) -> None:
        # --- Sim-Time (Pause / Speed) ---
        if self.ctx.clock.paused:
            sim_dt = 0.0
        else:
            sim_dt = dt * float(getattr(self.ctx.clock, "time_scale", 1.0))

        self._ship_time += sim_dt

        if not hasattr(self, "_enc_meter"):
            self._enc_meter = 0.0

        self._ui_t = float(getattr(self, "_ui_t", 0.0)) + float(dt)
        

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

            return

        cfg = self.MAPS[map_id]
        self._map_visual = self._load_and_scale_visual(cfg["visual"])
        self._map_nav = self._load_and_scale_nav(cfg["nav"])
        self._map_trg = self._load_and_scale_nav(cfg["trg"])
        self._map_enc = self._load_and_scale_nav(cfg["enc"])


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

        }

    def render(self, screen) -> None:
        world = self.ctx.world
        player = self.ctx.player
        # Map background (fixed)
        screen.blit(self._map_visual, (0, 0))

        p = self.ctx.player
        ml = int(getattr(p, "master_lives", 0))
        ml_max = int(getattr(p, "master_lives_max", 3))

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

        # Fallback, falls barometer rect nicht gesetzt
        if baro is not None:
            total_h = ml_max * size + (ml_max - 1) * gap
            start_y = baro.centery - total_h // 2

            # negative Werte = Herzen rücken näher an die sichtbare Barometer-Kante (überlappen in den Baro-Rect)
            pad = -60  # <- bei Bedarf -10 / -24 feinjustieren
            start_x = max(8, baro.left - size - pad)


            sh = screen.get_height()
            start_y = max(8, min(sh - total_h - 8, start_y))
        else:
            start_x = 24
            start_y = 24

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



        # Draw cities
        for c in world.cities:
            if c.map_id != self.ctx.current_map_id:
                continue
            if getattr(c, "map_id", "world_01") != self.ctx.current_map_id:
                continue
            pygame.draw.circle(screen, (90, 140, 220), c.pos, 10)
            pygame.draw.circle(screen, (60, 90, 150), c.pos, int(c.harbor_radius), 1)
            label = self.font.render(c.name, True, (220,220,220))
            screen.blit(label, (c.pos[0] + 14, c.pos[1] - 10))

            # Bedarf-Icons: nur Symbole, keine Preise
            market = self.ctx.markets.get(c.id)
            needs = (market.top_needs if market and market.top_needs else [])


            ix = c.pos[0] + 14
            iy = c.pos[1] + 12
            for gid in needs:
                g = self.ctx.content.goods.get(gid)
                if not g:
                    continue
                # simples Symbol: erster Buchstabe in kleinem Kästchen
                pygame.draw.rect(screen, (50, 70, 95), pygame.Rect(ix, iy, 18, 18), border_radius=3)
                letter = pygame.font.SysFont("arial", 14).render(g.name[0].upper(), True, (230,230,230))
                screen.blit(letter, (ix + 5, iy + 1))
                ix += 22

        # HUD
        day = self.ctx.clock.day
        paused = "PAUSE" if self.ctx.clock.paused else ""
        hud = self.font.render(f"Tag {day}  ZeitScale: {self.ctx.clock.time_scale:.2f}  {paused}", True, (200,200,200))
        screen.blit(hud, (20, 20))
        hint = self.font.render("WASD: Steuern | E: Anlegen | SPACE: Pause | TAB: Zeit x4", True, (150,150,150))
        screen.blit(hint, (20, 50))

        self._wake.render(screen)

        # Draw ship (Sprite)
        ship_name = self.ctx.content.ships[player.ship.type_id].name  # "Schaluppe"
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

        er, eg, eb, *_ = self._map_enc.get_at((x, y))
        dbg = self.font.render(f"ENC@ship: ({er},{eg},{eb})", True, (255,255,255))
        screen.blit(dbg, (20, 80))

        self._render_barometer(screen)

        self._draw_xp_bar(screen)

    def _render_barometer(self, screen: pygame.Surface) -> None:
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


    def _xp_to_level(self, xp: int) -> tuple[int, int, int]:
        # v1: simple quadratic-ish curve
        level = 1
        need = 100
        remaining = xp
        while remaining >= need and level < 99:
            remaining -= need
            level += 1
            need = int(100 + (level - 1) * 35)
        return level, remaining, need

    def _draw_xp_bar(self, screen) -> None:
        xp = int(getattr(self.ctx.player, "xp", 0))
        lvl, cur, need = self._xp_to_level(xp)
        frac = 0.0 if need <= 0 else max(0.0, min(1.0, cur / need))

        w, h = 260, 14
        x, y = 18, 18 + 34  # unterhalb deines Top-HUD, ggf. anpassen

        # container
        pygame.draw.rect(screen, (20, 22, 30), (x-10, y-28, w+20, 48), border_radius=10)
        pygame.draw.rect(screen, (8, 9, 12), (x-10, y-28, w+20, 48), 2, border_radius=10)

        label = self.font.render(f"XP  Lv {lvl}", True, (230, 230, 230))
        screen.blit(label, (x, y-22))

        pygame.draw.rect(screen, (50, 55, 70), (x, y, w, h), border_radius=6)
        pygame.draw.rect(screen, (90, 170, 110), (x, y, int(w * frac), h), border_radius=6)
        pygame.draw.rect(screen, (10, 10, 12), (x, y, w, h), 2, border_radius=6)

        txt = self.font.render(f"{cur}/{need}", True, (230, 230, 230))
        screen.blit(txt, (x + w - 82, y - 2))

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


    def _find_city_by_harbor_range(self, pos: tuple[float, float]):
        x, y = pos
        world = self.ctx.world
        for c in world.cities:
            hx, hy = self._city_harbors.get(c.id, c.pos)
            dx = hx - x
            dy = hy - y
            if (dx*dx + dy*dy) ** 0.5 <= c.harbor_radius:
                return c
        return None

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
