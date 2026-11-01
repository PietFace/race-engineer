"""Spotter: meldt auto's naast je (links, rechts, drie breed) en wanneer je weer vrij bent.

iRacing geeft dit direct door in CarLeftRight:
0 uit, 1 vrij, 2 auto links, 3 auto rechts, 4 links en rechts (drie breed), 5 twee links, 6 twee rechts."""

CLEAR, LEFT, RIGHT, BOTH, TWO_LEFT, TWO_RIGHT = 1, 2, 3, 4, 5, 6

CALLS = {
    LEFT: "Links",
    RIGHT: "Rechts",
    BOTH: "Drie breed, jij in het midden",
    TWO_LEFT: "Twee links",
    TWO_RIGHT: "Twee rechts",
}
STILL = {
    LEFT: "Nog links",
    RIGHT: "Nog rechts",
    BOTH: "Nog drie breed",
    TWO_LEFT: "Nog twee links",
    TWO_RIGHT: "Nog twee rechts",
}
CLEAR_CALLS = {LEFT: "Vrij links", RIGHT: "Vrij rechts"}

PHRASES = sorted(set(CALLS.values()) | set(STILL.values()) | set(CLEAR_CALLS.values()) | {"Vrij"})


class Spotter:
    def __init__(self, cfg, state, voice):
        self.cfg = cfg.get("spotter", {}) or {}
        self.s = state
        self.voice = voice
        self.reported = CLEAR      # wat we als laatste hebben gemeld
        self.raw = None
        self.raw_since = 0.0
        self.call_t = 0.0
        self.still_said = False
        self.calls = 0
        if self.enabled:
            voice.prewarm(PHRASES)

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    @property
    def active(self):
        return self.reported not in (CLEAR, 0, None)

    def update(self, src):
        if not self.enabled:
            return
        s = self.s
        me = s.player()
        val = src["CarLeftRight"]
        speed = src["Speed"] or 0
        if val is None or not me or me.on_pit or speed < 8 or s.session_state not in (3, 4, 5):
            val = CLEAR if self.active else self.reported
        if val == 0:
            val = CLEAR
        t = s.t
        if val != self.raw:
            self.raw, self.raw_since = val, t
        stable_for = t - self.raw_since
        # nieuwe situatie pas melden als hij heel even stabiel is (tegen geflikker)
        if self.raw != self.reported:
            need = 0.12 if self.raw != CLEAR else float(self.cfg.get("clear_delay", 0.45))
            if stable_for >= need:
                self._announce(self.raw, t)
        elif self.active and self.cfg.get("still_there", True):
            if not self.still_said and t - self.call_t > float(self.cfg.get("still_after", 4.0)):
                self.still_said = True
                self.voice.instant(STILL[self.reported])
        if self.active:
            self.voice.hold(1.5)

    def _announce(self, new, t):
        old = self.reported
        self.reported = new
        self.call_t = t
        self.still_said = False
        if new == CLEAR:
            self.voice.instant(CLEAR_CALLS.get(old, "Vrij"))
            return
        # van drie breed naar één kant: zeg alleen welke kant er nog zit
        self.calls += 1
        self.voice.instant(CALLS[new])
