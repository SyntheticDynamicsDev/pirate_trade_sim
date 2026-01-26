import pygame
from settings import SCREEN_W, SCREEN_H, FPS
from core.game import Game
from states.menu import MainMenuState
from core.audio import AudioManager

def main():
    pygame.init()
    pygame.mixer.init()

    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Pirate Trade Sim (Prototype)")
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
