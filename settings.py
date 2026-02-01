import os

SCREEN_W, SCREEN_H = 1280, 720
FPS = 60

# Zeitsteuerung
TIME_SCALE_PAUSE  = 0.0
TIME_SCALE_1X     = 1.0  # oder dein bisheriger TIME_SCALE_NORMAL
TIME_SCALE_2X     = 2.0
TIME_SCALE_4X     = 4.0  # oder dein bisheriger TIME_SCALE_FAST

MASTER_LIFE_ICON = os.path.join("assets", "ui", "master_life.png")
GOLD_ICON = os.path.join("assets", "ui", "gold.png")  # Dateiname ggf. anpassen
# --- UI Font (ersetze "arial" überall) ---
UI_FONT_PATH = os.path.join("assets", "fonts", "BrownieStencil-8O8MJ.ttf")  # <- hier deine neue Schrift eintragen
UI_FONT_FALLBACK = "arial"

# Hafen-Dock Radius Anpassungen
DOCK_RADIUS_MULT = 1.35   # 35% größer
DOCK_RADIUS_BONUS = 18    # +18 px extra Puffer

# Siegbedingung
WIN_GOLD_TARGET = 21000
