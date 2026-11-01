"""Spraakuitvoer met prioriteiten. Urgente berichten gaan voor, oude coachingtips vervallen."""
import asyncio
import heapq
import itertools
import os
import tempfile
import threading
import time

MAX_AGE = {0: 2.0, 1: 10.0, 2: 12.0, 3: 4.0, 4: 20.0}   # seconden voordat een bericht vervalt


class Voice:
    def __init__(self, cfg, log):
        self.cfg = cfg["voice"]
        self.log = log
        self.engine = self.cfg.get("engine", "edge")
        self.q = []
        self.counter = itertools.count()
        self.cv = threading.Condition()
        self.last_text = ""
        self.speaking = False
        self._sapi = None
        self._stop = False
        self.hold_until = 0.0       # spotter actief: gewone berichten even wachten
        self._clips = {}            # tekst -> bestand (vooraf gemaakt, voor de spotter)
        self._sounds = {}
        self._init_engine()
        threading.Thread(target=self._worker, daemon=True).start()

    def _init_engine(self):
        if self.engine == "edge":
            try:
                import edge_tts  # noqa
                os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                self._pygame = pygame
                self._tmpdir = tempfile.mkdtemp(prefix="engineer_")
            except Exception as e:
                self.log(f"Edge-stem niet beschikbaar ({e}), val terug op Windows-stem.")
                self.engine = "sapi"
        if self.engine == "sapi":
            try:
                import pyttsx3  # noqa  (wordt in de spraak-thread gestart, i.v.m. Windows COM)
            except Exception as e:
                self.log(f"Windows-stem niet beschikbaar ({e}), alleen tekst.")
                self.engine = "print"

    def _sapi_engine(self):
        if self._sapi is None:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
            import pyttsx3
            self._sapi = pyttsx3.init()
            for v in self._sapi.getProperty("voices"):
                if "dutch" in v.name.lower() or "nederlands" in v.name.lower() or "nl" in str(getattr(v, "languages", "")).lower():
                    self._sapi.setProperty("voice", v.id)
                    break
            self._sapi.setProperty("rate", 190)
        return self._sapi

    def stop(self):
        self._stop = True
        with self.cv:
            self.q.clear()
            self.q.append((0, 0, 0, None))
            self.cv.notify()

    # ------------------------------------------------------------
    #  Spotter: korte vaste zinnen, vooraf ingesproken, direct afspelen
    # ------------------------------------------------------------
    def prewarm(self, phrases):
        if self.engine != "edge":
            return

        def work():
            import edge_tts
            for ph in phrases:
                if self._stop:
                    return
                path = os.path.join(self._tmpdir, f"clip_{abs(hash(ph))}.mp3")
                try:
                    comm = edge_tts.Communicate(ph, self.cfg.get("edge_voice", "nl-NL-MaartenNeural"),
                                                rate=self.cfg.get("spotter_rate", "+25%"))
                    asyncio.run(comm.save(path))
                    self._clips[ph] = path
                except Exception:
                    pass
        threading.Thread(target=work, daemon=True).start()

    def instant(self, text):
        """Spotter-melding: zonder wachtrij, over de rest heen."""
        path = self._clips.get(text)
        if path and self.engine == "edge":
            try:
                snd = self._sounds.get(text)
                if snd is None:
                    snd = self._pygame.mixer.Sound(path)
                    self._sounds[text] = snd
                snd.set_volume(float(self.cfg.get("volume", 1.0)))
                ch = self._pygame.mixer.Channel(7)
                ch.stop()
                ch.play(snd)
                self.log(text, "spotter")
                return
            except Exception:
                pass
        self.say(text, 0)

    def hold(self, seconds):
        self.hold_until = max(self.hold_until, time.time() + seconds)

    def say(self, text, priority=2):
        if not text:
            return
        with self.cv:
            heapq.heappush(self.q, (priority, next(self.counter), time.time(), text))
            self.cv.notify()

    def repeat(self):
        if self.last_text:
            self.say(self.last_text, 1)

    def busy(self):
        return self.speaking or bool(self.q)

    def _worker(self):
        while True:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                prio, _, ts, text = heapq.heappop(self.q)
                if text is not None and prio >= 2 and time.time() < self.hold_until:
                    heapq.heappush(self.q, (prio, next(self.counter), ts, text))
                    self.cv.wait(0.2)
                    continue
            if self._stop or text is None:
                return
            if time.time() - ts > MAX_AGE.get(prio, 10):
                continue
            self.speaking = True
            self.log(text, "spotter" if prio == 0 else "radio")
            if prio <= 2:
                self.last_text = text
            try:
                self._speak(text)
            except Exception as e:
                self.log(f"Spraakfout: {e}")
            self.speaking = False

    def _speak(self, text):
        if self.engine == "edge":
            import edge_tts
            path = os.path.join(self._tmpdir, f"m{next(self.counter)}.mp3")
            comm = edge_tts.Communicate(text, self.cfg.get("edge_voice", "nl-NL-MaartenNeural"),
                                        rate=self.cfg.get("rate", "+0%"))
            asyncio.run(comm.save(path))
            m = self._pygame.mixer.music
            m.load(path)
            m.set_volume(float(self.cfg.get("volume", 1.0)))
            m.play()
            while m.get_busy():
                time.sleep(0.05)
            try:
                m.unload()
                os.remove(path)
            except Exception:
                pass
        elif self.engine == "sapi":
            eng = self._sapi_engine()
            eng.say(text)
            eng.runAndWait()
        else:
            time.sleep(min(4.0, 0.06 * len(text)) if self.cfg.get("simulate_duration") else 0)
