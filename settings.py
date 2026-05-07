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
WIN_GOLD_TARGET = 3000


# ----------------------------
# Persisted user settings (lang, volume, etc.)
# ----------------------------
import os
import json

USER_SETTINGS_DEFAULTS = {
    "lang": "de",        # "de" or "en"
    "volume_pct": 70,    # 0..100
    "fullscreen": False,
}

def _user_settings_path() -> str:
    base = "saves"
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "user_settings.json")

def load_user_settings() -> dict:
    path = _user_settings_path()
    if not os.path.exists(path):
        return dict(USER_SETTINGS_DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}

    out = dict(USER_SETTINGS_DEFAULTS)
    out.update(data)

    if out.get("lang") not in ("de", "en"):
        out["lang"] = USER_SETTINGS_DEFAULTS["lang"]

    try:
        out["volume_pct"] = int(out.get("volume_pct", USER_SETTINGS_DEFAULTS["volume_pct"]))
    except Exception:
        out["volume_pct"] = USER_SETTINGS_DEFAULTS["volume_pct"]
    out["volume_pct"] = max(0, min(100, out["volume_pct"]))
    out["fullscreen"] = bool(out.get("fullscreen", USER_SETTINGS_DEFAULTS["fullscreen"]))

    return out

def save_user_settings(data: dict) -> None:
    path = _user_settings_path()
    merged = load_user_settings()
    merged.update(data or {})

    if merged.get("lang") not in ("de", "en"):
        merged["lang"] = USER_SETTINGS_DEFAULTS["lang"]

    try:
        merged["volume_pct"] = int(merged.get("volume_pct", USER_SETTINGS_DEFAULTS["volume_pct"]))
    except Exception:
        merged["volume_pct"] = USER_SETTINGS_DEFAULTS["volume_pct"]
    merged["volume_pct"] = max(0, min(100, merged["volume_pct"]))
    merged["fullscreen"] = bool(merged.get("fullscreen", USER_SETTINGS_DEFAULTS["fullscreen"]))

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def apply_user_settings(ctx, data: dict | None = None) -> None:
    if data is None:
        data = load_user_settings()

    # Language
    lang = data.get("lang", "de")
    ctx.lang = lang
    if getattr(ctx, "i18n", None) is not None:
        try:
            ctx.i18n.set_lang(lang)
        except Exception:
            try:
                ctx.i18n.lang = lang
                ctx.i18n.load()
            except Exception:
                pass

    # Volume
    vol = int(data.get("volume_pct", 70))
    ctx.volume_pct = vol
    ctx.fullscreen = bool(data.get("fullscreen", False))
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(vol / 100.0)
    except Exception:
        pass
