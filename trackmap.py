"""Bochtenkaart van een baan: alle echte bochten, ook de bochten die vol gas gaan.

Gemeten uit je eigen ronde: hoe sterk de auto draait (gierhoeksnelheid / snelheid = kromming van de lijn).
Een bocht is een stuk waar de baan duidelijk krom is. Een chicane wordt twee bochten (links en rechts).
De kaart hoort bij de baan, niet bij de auto, dus de nummers blijven hetzelfde in elke auto.
Bewaard als bochten_<baan>.json, zodat je hem met de hand kunt nalezen.
"""
import json
import os
import re

BIN_M = 5.0
VERSION = 1

K_IN = 1 / 330.0      # vanaf deze bochtstraal (m) telt het als bocht
K_OUT = 1 / 600.0     # tot hier loopt de bocht door
MIN_LEN_M = 25
MERGE_M = 30          # zelfde richting en zo dicht bij elkaar: één bocht


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "onbekend").lower()).strip("_")


def _smooth(vals, w):
    n = len(vals)
    out = [None] * n
    for i in range(n):
        xs = [vals[j % n] for j in range(i - w, i + w + 1) if vals[j % n] is not None]
        out[i] = sum(xs) / len(xs) if xs else None
    return out


def corners_from_curvature(k):
    """k = kromming per meetpunt (1/m, + = links). Geeft [(start, top, eind, 'L'|'R')]."""
    n = len(k)
    ks = _smooth(k, 3)
    segs = []
    i = 0
    while i < n:
        x = ks[i]
        if x is not None and abs(x) >= K_IN:
            sign = 1 if x > 0 else -1
            a = i
            while a > 0 and ks[a - 1] is not None and ks[a - 1] * sign >= K_OUT:
                a -= 1
            b = i
            while b + 1 < n and ks[b + 1] is not None and ks[b + 1] * sign >= K_OUT:
                b += 1
            segs.append([a, b, sign])
            i = b + 1
        else:
            i += 1
    # zelfde richting dicht bij elkaar samenvoegen
    merged = []
    for s in segs:
        if merged and s[2] == merged[-1][2] and (s[0] - merged[-1][1]) * BIN_M <= MERGE_M:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    out = []
    for a, b, sign in merged:
        if (b - a + 1) * BIN_M < MIN_LEN_M:
            continue
        top = max(range(a, b + 1), key=lambda j: abs(ks[j] or 0))
        out.append((a, top, b, "L" if sign > 0 else "R"))
    return out


class TrackMap:
    def __init__(self, data_dir):
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.track = None
        self.nbins = None
        self.corners = []        # [{"nr", "start", "top", "eind", "richting"}] in meetpunten
        self.version = 0         # telt op als de kaart verandert
        self._k = None
        self._lap = None

    def path(self, track):
        return os.path.join(self.dir, f"bochten_{_slug(track)}.json")

    def setup(self, track, nbins):
        if track == self.track and nbins == self.nbins:
            return
        self.track, self.nbins = track, nbins
        self.corners = []
        self._k, self._lap = None, None
        try:
            with open(self.path(track), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("meetpunten") == nbins and d.get("versie") == VERSION:
                self.corners = d["bochten"]
                self.version += 1
        except Exception:
            pass

    @property
    def ready(self):
        return bool(self.corners)

    def record(self, lap_nr, dist, speed, yaw, on_track=True):
        """Elke tick tijdens je eigen ronde."""
        if self.ready or self.nbins is None or dist is None or dist < 0 or not on_track:
            return
        if lap_nr != self._lap:
            self._lap = lap_nr
            self._k = [None] * self.nbins
        if speed is None or speed < 12 or yaw is None:
            return
        b = min(self.nbins - 1, int(dist / BIN_M))
        k = yaw / speed
        prev = self._k[b]
        self._k[b] = k if prev is None else 0.5 * (prev + k)

    def lap_done(self, clean):
        """Na een schone ronde met (bijna) alle meetpunten: kaart maken en bewaren. True als hij nieuw is."""
        if self.ready or not clean or self._k is None:
            self._k = None
            return False
        k = self._k
        self._k = None
        if sum(1 for x in k if x is not None) < 0.95 * self.nbins:
            return False
        segs = corners_from_curvature(k)
        if len(segs) < 3:
            return False
        self.corners = [{"nr": i + 1, "start": a, "top": t, "eind": b, "richting": d}
                        for i, (a, t, b, d) in enumerate(segs)]
        self.version += 1
        try:
            with open(self.path(self.track), "w", encoding="utf-8") as f:
                json.dump({"baan": self.track, "versie": VERSION, "meetpunten": self.nbins,
                           "bochten": self.corners}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        return True
