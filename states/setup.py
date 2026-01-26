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
        self.font = pygame.font.SysFont("arial", 28)
        self.ctx.clock.time_scale = TIME_SCALE_1X

        # Dynamisches Startgeld aus Difficulty
        base_money = 5000
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

        ship = Ship(
            type_id=ship_def.id,
            name=ship_def.name,
            pos=(0, 0),

            # max speed
            speed=float(ship_def.speed_px_s),

            capacity_tons=float(ship_def.capacity_tons),

            # aus ships.json (jetzt im ShipDef vorhanden)
            turn_rate=float(getattr(ship_def, "turn_rate", 1.0)),
            accel=float(getattr(ship_def, "accel", 1.0)),

            hull_hp=int(getattr(ship_def, "hull_hp", 0)),
            crew_max=int(getattr(ship_def, "crew_max", 0)),
            crew_required=int(getattr(ship_def, "crew_required", 0)),
            upkeep_per_day=int(getattr(ship_def, "upkeep_per_day", 0)),
            draft_m=float(getattr(ship_def, "draft_m", 0.0)),
            shallow_water_ok=bool(getattr(ship_def, "shallow_water_ok", False)),
            cargo_protection=float(getattr(ship_def, "cargo_protection", 0.0)),
            pirate_target_mult=float(getattr(ship_def, "pirate_target_mult", 1.0)),
            armor=int(getattr(ship_def, "armor", 0)),
            cannon_slots=int(getattr(ship_def, "cannon_slots", 0)),
            basic_attack_dmg=int(getattr(ship_def, "basic_attack_dmg", 0)),
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
