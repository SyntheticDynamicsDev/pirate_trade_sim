from __future__ import annotations
import os
import random
import pygame

class AudioManager:
    def __init__(self, music_volume: float = 0.6, sfx_volume: float = 0.8):
        self.music_volume = float(music_volume)
        self.sfx_volume = float(sfx_volume)

        self._playlist: list[str] = []
        self._current: str | None = None
        self._shuffle: bool = True

        self._sfx_cache: dict[str, pygame.mixer.Sound] = {}

        self._music_stack: list[dict] = []

        # Eigener Event für "music ended"
        self.MUSIC_END = pygame.USEREVENT + 1
        pygame.mixer.music.set_endevent(self.MUSIC_END)

        pygame.mixer.music.set_volume(self.music_volume)

        # Loop-SFX (z.B. Meeresrauschen/Schiff)
        self._loop_channels: dict[str, pygame.mixer.Channel] = {}
        self._loop_sounds: dict[str, pygame.mixer.Sound] = {}

        self._reserved_loop_channel = pygame.mixer.Channel(0)
        self._loop_key_to_path: dict[str, str] = {}


    def set_music_volume(self, v: float) -> None:
        self.music_volume = float(max(0.0, min(1.0, v)))
        pygame.mixer.music.set_volume(self.music_volume)

    def set_sfx_volume(self, v: float) -> None:
        self.sfx_volume = float(max(0.0, min(1.0, v)))

    def play_playlist(self, tracks: list[str], *, shuffle: bool = True, fade_ms: int = 600) -> None:
        # Normalisieren + nur existierende Dateien
        norm = []
        for t in tracks:
            if t and os.path.exists(t):
                norm.append(t)

        if not norm:
            return

        self._shuffle = shuffle
        self._playlist = norm[:]

        # Wenn bereits dieselbe Playlist läuft, nicht neu starten
        if self._current in self._playlist and pygame.mixer.music.get_busy():
            return

        self._start_next(fade_ms=fade_ms, force=True)

    def push_music(self, tracks: list[str], *, shuffle: bool = False, fade_ms: int = 800) -> None:
        """
        Merkt sich den aktuellen Musikzustand (Playlist, current, shuffle) und startet eine neue Playlist.
        Perfekt für Combat/Minigames/States, die Musik temporär überschreiben.
        """
        # aktuellen Zustand sichern
        self._music_stack.append({
            "playlist": self._playlist[:],
            "current": self._current,
            "shuffle": self._shuffle,
        })
        self.play_playlist(tracks, shuffle=shuffle, fade_ms=fade_ms)

    def pop_music(self, *, fade_ms: int = 800) -> None:
        """
        Stellt den vorherigen Musikzustand wieder her (sofern vorhanden).
        """
        if not self._music_stack:
            return

        prev = self._music_stack.pop()
        playlist = prev.get("playlist") or []
        shuffle = bool(prev.get("shuffle", True))
        current = prev.get("current")

        # Wenn keine alte Playlist existierte: Musik stoppen
        if not playlist:
            self.stop_music(fade_ms=fade_ms)
            return

        # wiederherstellen
        self._shuffle = shuffle
        self._playlist = playlist[:]
        self._current = current

        # Wenn current existiert und Datei existiert: exakt diesen Track starten
        if self._current and os.path.exists(self._current):
            pygame.mixer.music.load(self._current)
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(fade_ms=int(fade_ms))
        else:
            # sonst normal "next"
            self._start_next(fade_ms=fade_ms, force=True)


    def stop_music(self, fade_ms: int = 600) -> None:
        try:
            pygame.mixer.music.fadeout(int(fade_ms))
        except Exception:
            pygame.mixer.music.stop()
        self._current = None

    def _start_next(self, fade_ms: int = 600, force: bool = False) -> None:
        if not self._playlist:
            return

        choices = [t for t in self._playlist if t != self._current]
        if not choices:
            choices = self._playlist[:]

        track = random.choice(choices) if self._shuffle else choices[0]

        if (not force) and track == self._current and pygame.mixer.music.get_busy():
            return

        self._current = track
        pygame.mixer.music.load(track)
        pygame.mixer.music.set_volume(self.music_volume)
        pygame.mixer.music.play(fade_ms=int(fade_ms))

    def handle_event(self, event) -> None:
        # muss aus Game Loop aufgerufen werden
        if event.type == self.MUSIC_END:
            self._start_next(fade_ms=0)

    def play_sfx(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return

        s = self._sfx_cache.get(path)
        if s is None:
            s = pygame.mixer.Sound(path)
            self._sfx_cache[path] = s

        s.set_volume(self.sfx_volume)
        s.play()

    def play_loop_sfx(self, key: str, path: str, *, volume: float = 1.0) -> None:
        """
        Startet einen loopenden SFX-Track. Wenn er bereits läuft, wird nur die Lautstärke angepasst.
        """
        if not key:
            return
        if not path or not os.path.exists(path):
            print(f"[Audio] loop sfx missing: {path}")
            return

        # Wenn der Loop für diesen Key bereits läuft: nur Volume setzen (KEIN restart)
        ch = self._loop_channels.get(key)
        if ch is not None and ch.get_busy():
            self.set_loop_volume(key, volume)
            return

        # Sound laden/cachen
        snd = self._loop_sounds.get(path)
        if snd is None:
            try:
                snd = pygame.mixer.Sound(path)
            except Exception as e:
                print(f"[Audio] failed to load loop sfx {path}: {e}")
                return
            self._loop_sounds[path] = snd

        # Channel holen (falls du einen reservierten Channel nutzt, nimm den; sonst find_channel)
        ch = getattr(self, "_reserved_loop_channel", None)
        if ch is None:
            ch = pygame.mixer.find_channel()
            if ch is None:
                print("[Audio] no free mixer channel for loop sfx (increase num channels)")
                return

        # Starten (genau einmal)
        v = max(0.0, min(1.0, self.sfx_volume * float(volume)))
        ch.set_volume(v)
        ch.play(snd, loops=-1)

        self._loop_channels[key] = ch

    def set_loop_volume(self, key: str, volume: float) -> None:
        ch = self._loop_channels.get(key)
        if ch is None:
            return
        v = max(0.0, min(1.0, self.sfx_volume * float(volume)))
        ch.set_volume(v)


    def stop_loop_sfx(self, key: str, fade_ms: int = 0) -> None:
        ch = self._loop_channels.get(key)
        if ch is None:
            return
        try:
            if fade_ms and fade_ms > 0:
                ch.fadeout(int(fade_ms))
            else:
                ch.stop()
        finally:
            self._loop_channels.pop(key, None)
            self._loop_key_to_path.pop(key, None)
