# Pirate Trade

Pirate Trade ist ein Python/Pygame-Spiel.

## Setup Für Spieler

Für Spieler ist das Ziel eine klassische Setup-Datei:

```text
PirateTradeSetup-0.1.0.exe
```

Die Setup-Datei installiert das Spiel, legt Startmenü-Verknüpfungen an und kann optional ein Desktop-Icon erstellen. Danach ist kein Python und kein manuelles Startskript nötig.

## Setup-Datei Bauen

Voraussetzungen auf dem Build-PC:

- Python 3.11 oder neuer
- Inno Setup 6

Build starten:

```powershell
.\build_windows_setup.ps1
```

Das erzeugt:

```text
installer_output\PirateTradeSetup-0.1.0.exe
```

Diese `.exe` ist die Datei, die du an Tester oder Spieler weitergibst.

## Entwicklerstart Unter Windows

Das ist nur für Entwicklung oder schnelle Tests aus dem Projektordner.

1. Lade das Projekt herunter oder entpacke den Projektordner.
2. Starte `install_windows.bat`.
3. Starte danach `run_game.bat`.

## Manuell Starten

```powershell
py -3 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

## Standalone-Ordner Ohne Installer Bauen

Wenn du nur den spielbereiten Ordner ohne Setup brauchst:

```powershell
.\build_windows_exe.ps1
```

Die fertige Version liegt danach unter:

```text
dist\Pirate Trade\Pirate Trade.exe
```

Den kompletten Ordner `dist\Pirate Trade` weitergeben, nicht nur die `.exe`.

## Projektstruktur

- `assets/`: Bilder, Musik, Sounds und UI-Grafiken
- `content/`: JSON-Daten für Waren, Städte, Gegner, Schiffe und Übersetzungen
- `core/`, `states/`, `world/`, `economy/`, `data/`, `ui/`: Spielcode
- `saves/`: lokale Spielstände und Einstellungen
