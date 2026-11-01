"""Referentie-bibliotheek: meet tijdens elke sessie ALLE auto's per 5 meter en bewaart per
auto-model + baan de snelste geldige ronde op schijf. Zo bouw je vanzelf een verzameling
snelle ronden op, ook van auto's die je die dag niet zelf reed.

Van andere auto's geeft iRacing live: positie op de baan, versnelling, toerental en stuurhoek.
Snelheid berekenen we uit de positie. Gas en rem van anderen zijn niet beschikbaar."""
import datetime
import json
import os
import re

from coach import BIN_M

N_TRACK_OK = 3   # CarIdxTrackSurface: 3 = op de baan


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "onbekend").lower()).strip("_")


def smooth(vals, w=2):
    out = []
    n = len(vals)
    for i in range(n):
        win = [vals[j] for j in range(max(0, i - w), min(n, i + w + 1)) if vals[j] is not None]
        out.append(sum(win) / len(win) if win else None)
    return out


def speed_profile(ts, lap_time=None):
    """Snelheid (km/u) per bin uit de passeertijden. Zelfde methode voor jou en de referentie,
    zodat de vergelijking eerlijk is."""
    n = len(ts)
    v = [None] * n
    for i in range(n):
        a = ts[i]
        b = ts[i + 1] if i + 1 < n else lap_time
        if a is not None and b is not None and b > a:
            v[i] = BIN_M / (b - a) * 3.6
    return smooth(v, 2)


class RefLap:
    """Eén ronde in bins van 5 m: tijd, snelheid (km/u), versnelling, stuurhoek."""

    def __init__(self, n):
        self.n = n
        self.t = [None] * n
        self.v = [None] * n
        self.gear = [None] * n
        self.steer = [None] * n
        self.brake = [None] * n   # alleen bij eigen ronden bekend
        self.thr = [None] * n
        self.meta = {}

    @property
    def lap_time(self):
        return self.meta.get("tijd")

    def to_dict(self):
        return {"meta": self.meta, "t": self.t, "v": self.v, "gear": self.gear, "steer": self.steer}

    @classmethod
    def from_dict(cls, d):
        lap = cls(len(d["t"]))
        lap.t, lap.v, lap.gear, lap.steer = d["t"], d["v"], d["gear"], d.get("steer") or [None] * len(d["t"])
        lap.meta = d.get("meta", {})
        return lap


class _Rec:
    """Opname van de lopende ronde van één auto."""

    def __init__(self, n, t0):
        self.n = n
        self.t0 = t0
        self.t = [None] * n
        self.gear = [None] * n
        self.steer = [None] * n
        self.dirty = False
        self.prev = None   # (pct, t)


class ReferenceLibrary:
    def __init__(self, cfg, state, data_dir):
        self.cfg = cfg.get("reference", {}) or {}
        self.s = state
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.recs = {}
        self.models = {}       # car idx -> automodel
        self.est = {}          # automodel -> geschatte rondetijd (iRacing)
        self._upd = None
        self.session_best = {}  # automodel -> RefLap (beste in deze sessie)
        self.saved = []         # (automodel, tijd, rijder) opgeslagen deze sessie
        self.changed = False    # True als de referentie voor jouw auto net is verbeterd
        self._cache = {}
        self.drivers = {}
        self.announced = False

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    def n_bins(self):
        return max(50, int((self.s.track_len_m or 4000) / BIN_M))

    def path(self, model, track=None):
        return os.path.join(self.dir, f"{slug(track or self.s.track_name)}__{slug(model)}.json")

    # ------------------------------------------------------------
    def _read_drivers(self, src):
        di = src["DriverInfo"] or {}
        self.drivers = {}
        for d in di.get("Drivers", []) or []:
            if d.get("CarIsPaceCar") or d.get("IsSpectator"):
                continue
            idx = d["CarIdx"]
            model = d.get("CarScreenNameShort") or d.get("CarScreenName") or d.get("CarPath") or "auto"
            self.models[idx] = model
            name = re.sub(r"\d+$", "", str(d.get("UserName", ""))).strip()
            self.drivers[idx] = {"naam": name, "irating": d.get("IRating") or 0}
            try:
                est = float(d.get("CarClassEstLapTime") or 0)
                if est > 0:
                    self.est[model] = est
            except (TypeError, ValueError):
                pass

    def update(self, src):
        if not self.enabled or not self.s.track_name:
            return []
        if src.session_info_update != self._upd:
            self._upd = src.session_info_update
            self._read_drivers(src)
        pcts = src["CarIdxLapDistPct"] or []
        gears = src["CarIdxGear"] or []
        steers = src["CarIdxSteer"] or []
        surf = src["CarIdxTrackSurface"] or []
        pits = src["CarIdxOnPitRoad"] or []
        t = self.s.t
        n = self.n_bins()
        caution = self.s.caution
        out = []
        for idx in self.models:
            if idx >= len(pcts):
                continue
            p = pcts[idx]
            if p is None or p < 0:
                self.recs.pop(idx, None)
                continue
            rec = self.recs.get(idx)
            if rec is None or rec.n != n:
                rec = self.recs[idx] = _Rec(n, None)
            sf = surf[idx] if idx < len(surf) else N_TRACK_OK
            if sf != N_TRACK_OK or (idx < len(pits) and pits[idx]) or caution:
                rec.dirty = True
            g = gears[idx] if idx < len(gears) else None
            st = steers[idx] if idx < len(steers) else None
            if rec.prev is not None:
                p0, t0 = rec.prev
                if p0 > 0.9 and p < 0.1:
                    # over de finishlijn: tijdstip interpoleren
                    span = (1.0 - p0) + p
                    tc = t0 + (t - t0) * ((1.0 - p0) / span if span > 0 else 0)
                    self._fill(rec, p0, t0, 1.0, tc, g, st)
                    res = self._finish(idx, rec, tc)
                    if res:
                        out += res
                    rec = self.recs[idx] = _Rec(n, tc)
                    rec.prev = (0.0, tc)
                    self._fill(rec, 0.0, tc, p, t, g, st)
                elif p > p0 and p - p0 < 0.2:
                    self._fill(rec, p0, t0, p, t, g, st)
                elif p < p0 - 0.02 or p - p0 >= 0.2:
                    rec.dirty = True   # achteruit of sprong (tow/reset)
            rec.prev = (p, t)
        return out

    @staticmethod
    def _fill(rec, p0, t0, p1, t1, g, st):
        if rec.t0 is None:
            return
        n = rec.n
        b0 = int(p0 * n) + 1
        b1 = min(n - 1, int(p1 * n))
        for b in range(b0, b1 + 1):
            if rec.t[b] is None:
                f = (b / n - p0) / (p1 - p0) if p1 > p0 else 0
                rec.t[b] = (t0 + f * (t1 - t0)) - rec.t0
                rec.gear[b] = g if g and g > 0 else rec.gear[b]
                rec.steer[b] = st
        if p0 == 0.0 and rec.t[0] is None:
            rec.t[0] = 0.0

    def _finish(self, idx, rec, t_cross):
        if rec.t0 is None or rec.dirty:
            return []
        lt = t_cross - rec.t0
        model = self.models.get(idx)
        filled = sum(1 for x in rec.t if x is not None) / rec.n
        if filled < 0.95 or lt <= 10:
            return []
        est = self.est.get(model)
        if est and not (0.85 * est < lt < 1.25 * est):
            return []
        # gaten opvullen en snelheid uit de tijden berekenen
        ts = rec.t[:]
        last = 0.0
        for i in range(len(ts)):
            if ts[i] is None:
                ts[i] = last
            last = ts[i]
        v = [None] * rec.n
        for i in range(rec.n):
            j = min(rec.n - 1, i + 1)
            dt = (ts[j] - ts[i]) if j > i else (lt - ts[i])
            v[i] = (BIN_M / dt * 3.6) if dt and dt > 0 else None
        v = smooth(v, 2)
        lap = RefLap(rec.n)
        lap.t, lap.v, lap.gear, lap.steer = [round(x, 3) for x in ts], [round(x, 1) if x else x for x in v], rec.gear, rec.steer
        drv = self.drivers.get(idx, {})
        lap.meta = {"tijd": round(lt, 3), "rijder": drv.get("naam", "?"), "irating": drv.get("irating", 0),
                    "auto": model, "baan": self.s.track_name, "sessie": self.s.session_type,
                    "datum": datetime.date.today().isoformat(), "eigen": idx == self.s.player_idx,
                    "baantemp": getattr(self.s, "track_temp", None)}
        best = self.session_best.get(model)
        if best is None or lt < best.lap_time:
            self.session_best[model] = lap
        return self._maybe_save(model, lap)

    def _maybe_save(self, model, lap):
        stored = self.get(model)
        if stored is not None and stored.lap_time <= lap.lap_time:
            return []
        try:
            with open(self.path(model), "w", encoding="utf-8") as f:
                json.dump(lap.to_dict(), f)
        except Exception:
            return []
        self._cache[(slug(self.s.track_name), slug(model))] = lap
        self.saved.append((model, lap.lap_time, lap.meta["rijder"]))
        me_model = self.models.get(self.s.player_idx)
        if model == me_model and not lap.meta.get("eigen"):
            self.changed = True
            if self.announced:
                return []
            self.announced = True
            from race_state import say_lap
            return [(4, f"Nieuwe referentie voor deze auto: {lap.meta['rijder']}, {say_lap(lap.lap_time)}. "
                        "Vanaf nu vergelijk ik je met die ronde.")]
        return []

    # ------------------------------------------------------------
    def get(self, model, track=None):
        key = (slug(track or self.s.track_name), slug(model))
        if key in self._cache:
            return self._cache[key]
        try:
            with open(self.path(model, track), encoding="utf-8") as f:
                lap = RefLap.from_dict(json.load(f))
        except Exception:
            lap = None
        self._cache[key] = lap
        return lap

    def for_player(self):
        model = self.models.get(self.s.player_idx) or self.s.car_name
        lap = self.get(model) if model else None
        if lap is not None and lap.n != self.n_bins():
            return None
        return lap

    def list_all(self):
        out = []
        try:
            files = sorted(os.listdir(self.dir))
        except Exception:
            files = []
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, fn), encoding="utf-8") as f:
                    meta = json.load(f).get("meta", {})
                out.append(meta)
            except Exception:
                pass
        return out


# ----------------------------------------------------------------------
#  Bochtkenmerken uit een snelheidsprofiel (werkt voor elke ronde, ook zonder pedaaldata)
# ----------------------------------------------------------------------
def corner_metrics(v, gear, apex_hint, lo, hi):
    """Remstart (bin), top (bin), minimumsnelheid, accelereer-start (bin), laagste versnelling.
    Gebaseerd op het snelheidsverloop rond de bocht."""
    sv = smooth(v, 1)
    rng = [i for i in range(max(0, lo), min(len(sv), hi + 1)) if sv[i] is not None]
    if not rng:
        return None
    apex = min(rng, key=lambda i: sv[i])
    vmin = sv[apex]
    before = [i for i in rng if i <= apex]
    peak_i = max(before, key=lambda i: sv[i])
    peak = sv[peak_i]
    # remstart: laatste punt vóór de top waar je nog (bijna) op topsnelheid zat
    brake = max((i for i in before if i >= peak_i and sv[i] >= peak - 2.0), default=peak_i)
    # accelereren: eerste punt na de top dat duidelijk sneller is dan de minimumsnelheid
    accel = next((i for i in rng if i > apex and sv[i] >= vmin + 3.0), apex)
    gears = [gear[k] for k in range(brake, accel + 1) if gear and k < len(gear) and gear[k]]
    return {"brake": brake, "apex": apex, "vmin": vmin, "accel": accel, "gear": min(gears) if gears else None}


def corners_from_speed(v, min_drop=12.0, merge_m=60):
    """Bochten vinden in een ronde zonder remdata: lokale minima met genoeg snelheidsverlies."""
    sv = smooth(v, 2)
    n = len(sv)
    mins = []
    for i in range(1, n - 1):
        if sv[i] is None or sv[i - 1] is None or sv[i + 1] is None:
            continue
        if sv[i] <= sv[i - 1] and sv[i] <= sv[i + 1]:
            back = max((x for x in sv[max(0, i - 60):i] if x is not None), default=sv[i])
            if back - sv[i] >= min_drop:
                mins.append(i)
    merged = []
    for m in mins:
        if merged and (m - merged[-1]) * BIN_M < merge_m:
            if sv[m] < sv[merged[-1]]:
                merged[-1] = m
        else:
            merged.append(m)
    return merged
