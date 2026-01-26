from __future__ import annotations
import pygame
from dataclasses import dataclass
from typing import List, Optional
from core.audio import AudioManager 
from core.clock import GameClock
from core.state import State
from core.run_config import RunConfig
from dataclasses import dataclass, field


@dataclass
class GameContext:
    clock: GameClock
    content = None
    world = None
    player = None
    markets = None
    economy = None
    run_config: RunConfig = field(default_factory=RunConfig)


class Game:
    def __init__(self, screen: pygame.Surface, initial_state: State):
        self.screen = screen
        self.ctx = GameContext(clock=GameClock())
        self.state_stack: List[State] = [initial_state]
        pygame.mouse.set_visible(True)
        self.ctx.run_config = RunConfig()

        # Inject references + enter initial state
        self._inject(self.state_stack[-1])

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        
        pygame.mixer.set_num_channels(32)
        pygame.mixer.set_reserved(1)  # Channel 0 wird exklusiv reserviert

        # AudioManager am Context
        self.ctx.audio = AudioManager(music_volume=0.55, sfx_volume=0.8)

        self.state_stack[-1].on_enter()

    def _inject(self, state: State) -> None:
        # States are dataclasses with attributes game/ctx in this prototype
        state.game = self
        state.ctx = self.ctx

    def push(self, new_state) -> None:
        new_state.game = self
        new_state.ctx = self.ctx
        self.state_stack.append(new_state)
        if hasattr(new_state, "on_enter"):
            new_state.on_enter()

    def pop(self) -> None:
        if not self.state_stack:
            return
        old = self.state_stack.pop()
        if hasattr(old, "on_exit"):
            old.on_exit()


    def replace(self, new_state) -> None:
        # Exit old
        if self.state_stack:
            old = self.state_stack[-1]
            if hasattr(old, "on_exit"):
                old.on_exit()

        # Prepare new state
        new_state.game = self
        new_state.ctx = self.ctx

        # Replace
        if self.state_stack:
            self.state_stack[-1] = new_state
        else:
            self.state_stack = [new_state]

        # Enter new
        if hasattr(new_state, "on_enter"):
            new_state.on_enter()



    @property
    def state(self) -> State:
        return self.state_stack[-1]

    def run_frame(self, real_dt: float) -> None:
        # Event handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise SystemExit

            # Audio zuerst (damit Trackwechsel zuverlässig passiert)
            if getattr(self.ctx, "audio", None) is not None:
                self.ctx.audio.handle_event(event)

            # Dann State
            self.state.handle_event(event)

        # Update clock (state can adjust time_scale)
        days = self.ctx.clock.update(real_dt)
        if days:
            from core.day_update import on_new_day
            for _ in range(int(days)):
                on_new_day(self.ctx)


        # State update
        self.state.update(real_dt)

        # Render
        self.screen.fill((12, 14, 18))
        self.state.render(self.screen)


