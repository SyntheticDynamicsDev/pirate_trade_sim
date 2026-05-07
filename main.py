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


def set_mouse_cursor():
    try:
        cursor = pygame.image.load("assets/mouse.png").convert_alpha()
        cursor = pygame.transform.smoothscale(cursor, (32, 38))
        pygame.mouse.set_cursor((0, 0), cursor)
    except Exception:
        pass


def create_display(fullscreen: bool = False):
    flags = pygame.SCALED
    if fullscreen:
        flags |= pygame.FULLSCREEN
    return pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)


def main():
    pygame.init()
    pygame.mixer.init()

    user_settings = load_user_settings()
    screen = create_display(bool(user_settings.get("fullscreen", False)))
    set_window_icon()
    set_mouse_cursor()
    title = "Pirate Trade"
    try:
        from core.i18n import I18N
        lang = user_settings.get("lang", "de")
        i18n = I18N(lang=lang, base_dir="content/i18n")
        i18n.load()
        title = i18n.t("app.title")
    except Exception:
        pass
    pygame.display.set_caption(title)
    clock = pygame.time.Clock()

    game = Game(screen=screen, initial_state=MainMenuState())
    game.ctx.fullscreen = bool(user_settings.get("fullscreen", False))
    pygame.mixer.init()
    game.ctx.audio = AudioManager(music_volume=0.8, sfx_volume=0.8)
    
    while True:
        real_dt = clock.tick(FPS) / 1000.0
        game.run_frame(real_dt)
        pygame.display.flip()

if __name__ == "__main__":
    main()
