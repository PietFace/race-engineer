"""Knoppen (toetsenbord + stuur) en spraakherkenning voor vragen."""
import os
import threading
import time

ACTIONS = ["race_update", "strategy", "gaps", "ask_question", "repeat", "setup_advice"]
ACTION_LABELS = {
    "race_update": "Race-update",
    "strategy": "Strategie",
    "gaps": "Gaps",
    "ask_question": "Vraag stellen",
    "repeat": "Herhaal laatste",
    "setup_advice": "Setup-advies",
}


class Hotkeys:
    """Globale sneltoetsen (werken ook als iRacing focus heeft)."""

    def __init__(self, log):
        self.log = log
        self.ok = True
        try:
            import keyboard
            self.kb = keyboard
        except Exception as e:
            self.ok = False
            self.log(f"Sneltoetsen niet beschikbaar ({e}).")

    def apply(self, keymap, on_action):
        if not self.ok:
            return
        try:
            self.kb.unhook_all_hotkeys()
        except Exception:
            pass
        for act in ACTIONS:
            k = (keymap or {}).get(act)
            if k:
                try:
                    self.kb.add_hotkey(k, lambda a=act: on_action(a))
                except Exception as e:
                    self.log(f"Sneltoets '{k}' werkt niet: {e}")


class JoystickWatcher:
    """Eén achtergrondthread die alle stuur/knoppenbox-knoppen leest.
    - normaal: stuurt toegewezen knoppen door als actie
    - capture: de eerstvolgende knopdruk wordt teruggegeven (voor toewijzen in het venster)"""

    def __init__(self, log):
        self.log = log
        self.mapping = {}          # knopnummer -> actie
        self.name_filter = ""
        self.on_action = None
        self._capture_cb = None
        self.devices = []
        self.ok = False
        threading.Thread(target=self._loop, daemon=True).start()

    def configure(self, wheel_cfg, on_action):
        wheel_cfg = wheel_cfg or {}
        self.mapping = {int(wheel_cfg[a]): a for a in ACTIONS
                        if isinstance(wheel_cfg.get(a), int) and wheel_cfg.get(a) >= 0}
        self.name_filter = (wheel_cfg.get("device_name_contains") or "").lower()
        self.on_action = on_action

    def capture_next(self, cb):
        self._capture_cb = cb

    def _loop(self):
        try:
            os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            import pygame
            pygame.init()
            pygame.joystick.init()
            self.ok = True
        except Exception as e:
            self.log(f"Stuurknoppen niet beschikbaar ({e}).")
            return
        joys = {}
        while True:
            try:
                for ev in pygame.event.get():
                    if ev.type == pygame.JOYDEVICEADDED:
                        j = pygame.joystick.Joystick(ev.device_index)
                        j.init()
                        joys[j.get_instance_id()] = j
                        self.devices = [x.get_name() for x in joys.values()]
                    elif ev.type == pygame.JOYDEVICEREMOVED:
                        joys.pop(ev.instance_id, None)
                        self.devices = [x.get_name() for x in joys.values()]
                    elif ev.type == pygame.JOYBUTTONDOWN:
                        j = joys.get(ev.instance_id)
                        name = j.get_name() if j else "?"
                        if self._capture_cb:
                            cb, self._capture_cb = self._capture_cb, None
                            cb(ev.button, name)
                            continue
                        if self.name_filter and self.name_filter not in name.lower():
                            continue
                        act = self.mapping.get(ev.button)
                        if act and self.on_action:
                            self.on_action(act)
            except Exception:
                pass
            time.sleep(0.02)


class Listener:
    """Luistert na een knopdruk naar een gesproken vraag (Google spraakherkenning, nl-NL)."""

    def __init__(self, cfg, log):
        self.cfg = cfg["speech_input"]
        self.log = log
        self.ok = False
        if not self.cfg.get("enabled"):
            return
        try:
            import speech_recognition as sr
            self.sr = sr
            self.rec = sr.Recognizer()
            self.mic = sr.Microphone()
            with self.mic as source:
                self.rec.adjust_for_ambient_noise(source, duration=0.5)
            self.ok = True
        except Exception as e:
            self.log(f"Microfoon/spraakherkenning niet beschikbaar ({e}).")

    def listen(self, callback):
        if not self.ok:
            callback(None)
            return

        def worker():
            try:
                with self.mic as source:
                    audio = self.rec.listen(source, timeout=3, phrase_time_limit=self.cfg.get("listen_seconds", 6))
                text = self.rec.recognize_google(audio, language=self.cfg.get("language", "nl-NL"))
                callback(text)
            except Exception:
                callback(None)
        threading.Thread(target=worker, daemon=True).start()
