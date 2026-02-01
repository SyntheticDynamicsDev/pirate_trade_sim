from __future__ import annotations
import pygame
from dataclasses import dataclass
from typing import Optional, Any
import os
from settings import TIME_SCALE_1X
from states.world import WorldMapState
from world.model import World, City, Ship, Player
from data.loader import load_content


@dataclass
class NewGameSetupState:
    game: Any = None
    ctx: Any = None
    font: Optional[pygame.font.Font] = None

    def on_enter(self) -> None:
        from core.ui_text import FontBank, TextStyle, render_text
        from settings import UI_FONT_PATH, UI_FONT_FALLBACK

        self._fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)
        self.font = self._fonts.get(28)
        self.small = self._fonts.get(14)

        self.ctx.clock.time_scale = TIME_SCALE_1X

        # Dynamisches Startgeld aus Difficulty
        base_money = 19990
        rc = getattr(self.ctx, "run_config", None)

        if rc is not None:
            start_money = int(round(base_money * float(rc.start_money_mult)))
        else:
            start_money = base_money

        # Direkt starten (kein Setup-Fenster mehr)
        self.ctx.content = load_content("content")

        # --- Cities laden + ggf. auf Screen (1280x720) skalieren ---
        cities = []

        from settings import SCREEN_W, SCREEN_H
        MAP_SRC_W, MAP_SRC_H = 1536, 1024  # deine Map-Originalgröße

        def scale_pos(pos):
            x, y = pos
            # Wenn Content-Pos noch im 1536x1024 Raum sind -> auf Screen skalieren
            if x > SCREEN_W or y > SCREEN_H:
                x = x * (SCREEN_W / MAP_SRC_W)
                y = y * (SCREEN_H / MAP_SRC_H)
            return (x, y)

        for c in self.ctx.content.cities.values():
            cities.append(
                City(
                    id=c.id,
                    name=c.name,
                    pos=scale_pos(c.pos),
                    harbor_radius=c.harbor_radius,
                    city_type_id=c.city_type_id,
                    map_id=getattr(c, "map_id", "world_01"),
                )
            )



        # nach ship = Ship(...)
        rc = self.ctx.run_config
        ship_id = getattr(rc, "start_ship_id", "ship_01")

        ship_id_map = {
            "ship_01": "Schaluppe",
            "ship_02": "Holk",
            "ship_03": "Karake",
            "ship_04": "Fleute",
            "ship_05": "Linienschiff",
        }

        ship_type = ship_id_map.get(ship_id, "Schaluppe")



        rc = self.ctx.run_config
        ship_type_id = getattr(rc, "start_ship_type_id", "sloop")

        ship_def = self.ctx.content.ships[ship_type_id]

        # setup.py (in on_enter nach: ship_def = self.ctx.content.ships[ship_type_id])

        sd = ship_def
        c = sd.combat

        ship = Ship(
            id=sd.id,
            name=sd.name,

            # World
            speed=sd.speed_px_s,
            turn_rate=sd.turn_rate,
            accel=sd.accel,
            draft_m=sd.draft_m,
            shallow_water_ok=sd.shallow_water_ok,
            capacity_tons=sd.capacity_tons,
            cargo_protection=sd.cargo_protection,
            pirate_target_mult=sd.pirate_target_mult,
            upkeep_per_day=sd.upkeep_per_day,
            crew_max=sd.crew_max,
            crew_required=sd.crew_required,
            cannon_slots=sd.cannon_slots,

            # Combat runtime
            hp=c.hp_max,
            hp_max=c.hp_max,
        )

        # Robust: Attribut nachträglich setzen
        try:
            ship.ship_type = ship_type
        except Exception:
            # Falls Ship __slots__ nutzt und keine neuen Attribute erlaubt
            # dann nutzen wir stattdessen ein Feld im Player/ctx
            self.ctx.selected_ship_type = ship_type

        player = Player(money=start_money, houses=set(), ship=ship)
        self.ctx.world = World(cities=cities)
        self.ctx.current_map_id = "world_01"
        self.ctx.start_city_id = cities[0].id if cities else None

        self.ctx.player = player
        self.ctx._win_triggered = False


        from economy.market import CityMarketState
        from economy.economy import EconomyEngine

        self.ctx.economy = EconomyEngine()
        self.ctx.markets = {}

        for city in self.ctx.world.cities:
            cdef = self.ctx.content.cities[city.id]
            ctype = self.ctx.content.city_types[cdef.city_type_id]

            market = CityMarketState(city_id=city.id)

            for g in self.ctx.content.goods.values():
                need = ctype.needs.get(g.category, "normal")
                need_target_mult = self.ctx.economy.NEED_TARGET_MULT.get(need, 1.0)

                target = g.target_stock * need_target_mult


                target = g.target_stock * need_target_mult
                stock = target * ctype.initial_stock_multiplier

                tweak = (hash(city.id + g.id) % 21 - 10) / 100.0
                stock *= (1.0 + tweak)

                market.stock[g.id] = max(0.0, round(stock, 1))
                market.pending[g.id] = 0.0
                market.price_stock[g.id] = market.stock[g.id]

            self.ctx.markets[city.id] = market

        from core.day_update import _update_top_needs
        _update_top_needs(self.ctx)

        self.game.replace(WorldMapState())

        

    def on_exit(self) -> None:
        ...

    def handle_event(self, event) -> None:
        # Wird i. d. R. nicht erreicht, weil on_enter sofort weiterleitet
        pass

    def update(self, dt: float) -> None:
        ...

    def render(self, screen) -> None:
        # Kein Setup Screen mehr
        pass
