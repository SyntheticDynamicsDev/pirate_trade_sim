from __future__ import annotations
import pygame
from dataclasses import dataclass
from typing import Any

from core.ui_text import FontBank, TextStyle, render_text
from settings import UI_FONT_PATH, UI_FONT_FALLBACK


@dataclass
class VictoryState:
    game: Any = None
    ctx: Any = None

    def on_enter(self) -> None:
        # Zeit anhalten
        if getattr(self.ctx, "clock", None) is not None:
            self.ctx.clock.time_scale = 0.0

        self.fonts = FontBank(UI_FONT_PATH, UI_FONT_FALLBACK)
        self.title_font = self.fonts.get(64, bold=True)
        self.text_font = self.fonts.get(28, bold=True)
        self.small_font = self.fonts.get(20)

        self._title_style = TextStyle(
            gradient_top=(255, 240, 200),
            gradient_bottom=(190, 150, 80),
            thickness=2,
            outline_color=(0, 0, 0),
            outline_px=3,
            shadow_alpha=140,
        )
        self._text_style = TextStyle(
            color=(235, 235, 235),
            thickness=2,
            outline_color=(0, 0, 0),
            outline_px=2,
            shadow_alpha=120,
        )

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN or event.type == pygame.MOUSEBUTTONDOWN:
            from states.menu import MainMenuState
            self.game.replace(MainMenuState())

    def update(self, dt: float) -> None:
        pass

    def _t(self, key: str, **kwargs) -> str:
        i18n = getattr(self.ctx, "i18n", None)
        if i18n is None:
            return key.format(**kwargs) if kwargs else key
        return i18n.t(key, **kwargs)

    def render(self, screen: pygame.Surface) -> None:
        w, h = screen.get_size()

        # dunkler Overlay
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))

        money = int(getattr(getattr(self.ctx, "player", None), "money", 0))
        money_txt = f"{money:,}".replace(",", ".")

        title = render_text(self._t("victory.title"), self.title_font, self._title_style)
        info = render_text(self._t("victory.info", money=money_txt), self.text_font, self._text_style)
        hint = render_text(self._t("victory.hint"), self.small_font, self._text_style)

        screen.blit(title, ((w - title.get_width()) // 2, int(h * 0.28)))
        screen.blit(info, ((w - info.get_width()) // 2, int(h * 0.45)))
        screen.blit(hint, ((w - hint.get_width()) // 2, int(h * 0.60)))
