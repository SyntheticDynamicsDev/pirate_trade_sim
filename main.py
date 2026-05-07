import pygame
from settings import SCREEN_W, SCREEN_H, FPS
from core.game import Game
from states.menu import MainMenuState
from core.audio import AudioManager
from settings import load_user_settings


def set_window_icon():
    try:
        icon = pygame.image.load("assets/ui/level.png")
        pygame.display.set_icon(icon)
    except Exception:
        pass


def main():
    pygame.init()
    pygame.mixer.init()

    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    set_window_icon()
    title = "Pirate Trade"
    try:
        from core.i18n import I18N
        lang = load_user_settings().get("lang", "de")
        i18n = I18N(lang=lang, base_dir="content/i18n")
        i18n.load()
        title = i18n.t("app.title")
    except Exception:
        pass
    pygame.display.set_caption(title)
    clock = pygame.time.Clock()

    game = Game(screen=screen, initial_state=MainMenuState())
    pygame.mixer.init()
    game.ctx.audio = AudioManager(music_volume=0.8, sfx_volume=0.8)
    
    while True:
        real_dt = clock.tick(FPS) / 1000.0
        game.run_frame(real_dt)
        pygame.display.flip()

if __name__ == "__main__":
    main()
