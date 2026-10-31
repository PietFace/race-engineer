"""Rijcoaching per bocht: vergelijkt je huidige ronde met je beste (referentie)ronde."""
import json
import os
import re

BIN_M = 5.0


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "onbekend").lower()).strip("_")


class Lap:
    def __init__(self, nbins):
        self.n = nbins
        self.t = [None] * nbins       # tijd-in-ronde bij binnenkomst bin
        self.v = [None] * nbins       # km/u
        self.brake = [None] * nbins
        self.thr = [None] * nbins
        self.gear = [None] * nbins

    def fill_gaps(self):
        for arr in (self.t, self.v, self.brake, self.thr, self.gear):
            last = None
            for i in range(self.n):
                if arr[i] is None:
                    arr[i] = last
                else:
                    last = arr[i]
            # begin van de ronde
            first = next((x for x in arr if x is not None), 0.0)
            for i in range(self.n):
                if arr[i] is None:
                    arr[i] = first
                else:
                    break

    def coverage(self):
        return sum(1 for x in self.t if x is not None) / self.n

    def to_dict(self):
        return {"t": self.t, "v": self.v, "brake": self.brake, "thr": self.thr, "gear": self.gear}

    @classmethod
    def from_dict(cls, d):
        lap = cls(len(d["t"]))
        lap.t, lap.v, lap.brake, lap.thr = d["t"], d["v"], d["brake"], d["thr"]
        lap.gear = d.get("gear") or [None] * lap.n
        return lap

    def copy(self):
        return Lap.from_dict({k: list(v) for k, v in self.to_dict().items()})


class Corner:
    def __init__(self, nr, brake_bin, apex_bin, exit_bin, throttle_bin):
        self.nr = nr
        self.brake_bin = brake_bin
        self.apex_bin = apex_bin
        self.exit_bin = exit_bin
        self.throttle_bin = throttle_bin


class Coach:
    def __init__(self, cfg, state, data_dir="referentie_ronden"):
        self.cfg = cfg["coach"]
        self.s = state
        self.data_dir = data_dir
        self.nbins = None
        self.ref = None
        self.ref_time = None
        self.corners = []
        self.cur = None
        self.cur_lap_nr = None
        self.lap_start_t = None
        self.reported = set()
        self.tips_this_lap = 0
        self.corner_deltas = {}
        self.last_lap_deltas = {}
        self.key = None
        self.laps = []              # laatste ronden voor de grafieken
        self.new_track = False
        self.guide_laps = 0
        self.guided = set()

    # ------------------------------------------------------------
    def _setup(self):
        self.nbins = max(50, int(self.s.track_len_m / BIN_M))
        self.key = f"{_slug(self.s.track_name)}__{_slug(self.s.car_name)}"
        self._load_ref()

    def _ref_path(self):
        return os.path.join(self.data_dir, self.key + ".json")

    def _load_ref(self):
        if not self.cfg.get("save_reference_laps"):
            return
        try:
            with open(self._ref_path()) as f:
                d = json.load(f)
            lap = Lap.from_dict(d["lap"])
            if lap.n == self.nbins:
                self.ref, self.ref_time = lap, d["time"]
                self._find_corners()
        except Exception:
            self.new_track = True

    def _save_ref(self):
        if not self.cfg.get("save_reference_laps"):
            return
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self._ref_path(), "w") as f:
                json.dump({"time": self.ref_time, "lap": self.ref.to_dict()}, f)
        except Exception:
            pass

    def mode(self):
        m = self.cfg.get("mode", "auto")
        if m == "auto":
            return "race" if self.s.is_race() else "practice"
        return m

    # ------------------------------------------------------------
    def _find_corners(self):
        r = self.ref
        n = r.n
        zones = []
        i = 0
        while i < n:
            if (r.brake[i] or 0) > 0.15:
                j = i
                while j < n and ((r.brake[j] or 0) > 0.05 or (j + 1 < n and (r.brake[j + 1] or 0) > 0.15)):
                    j += 1
                zones.append([i, j])
                i = j + 1
            else:
                i += 1
        # zones dicht bij elkaar samenvoegen (< 30 m)
        merged = []
        for z in zones:
            if merged and z[0] - merged[-1][1] < 30 / BIN_M:
                merged[-1][1] = z[1]
            else:
                merged.append(z)
        corners = []
        for k, (b0, b1) in enumerate(merged):
            search_end = min(n - 1, b1 + int(150 / BIN_M))
            apex = min(range(b0, search_end + 1), key=lambda x: r.v[x] or 999)
            thr = apex
            while thr < n - 1 and (r.thr[thr] or 0) < 0.5:
                thr += 1
            exit_bin = min(n - 1, thr + int(80 / BIN_M))
            corners.append(Corner(k + 1, b0, apex, exit_bin, thr))
        self.corners = corners

    # ------------------------------------------------------------
    def update(self, src, lap_time_now):
        """Elke tick. Geeft lijst (prioriteit, tekst) van tips terug."""
        if not self.cfg.get("enabled") or self.mode() == "off":
            return []
        intro = []
        if self.nbins is None or self.key != f"{_slug(self.s.track_name)}__{_slug(self.s.car_name)}":
            self._setup()
            if self.new_track and self.cfg.get("track_guide", "auto") != "uit":
                intro = [(4, "Nieuwe baan met deze auto. Rij eerst een rustige, schone ronde, "
                             "daarna zeg ik voor elke bocht hoe hard je remt en in welke versnelling.")]
        me = self.s.player()
        if not me or me.wraps is None:
            return []
        lap_nr = me.wraps
        dist = src["LapDist"]
        if dist is None or dist < 0:
            return []
        b = min(self.nbins - 1, int(dist / BIN_M))
        if self.cur is None or lap_nr != self.cur_lap_nr:
            self.cur = Lap(self.nbins)
            self.cur_lap_nr = lap_nr
            self.lap_start_t = self.s.t
            self.reported = set()
            self.tips_this_lap = 0
            self.corner_deltas = {}
            self.guided = set()
        t_in = self.s.t - self.lap_start_t
        self.last_bin, self.last_t_in = b, t_in
        if self.cur.t[b] is None:
            self.cur.t[b] = t_in
        self.cur.v[b] = (src["Speed"] or 0) * 3.6 if self.cur.v[b] is None else min(self.cur.v[b], (src["Speed"] or 0) * 3.6)
        self.cur.brake[b] = max(self.cur.brake[b] or 0, src["Brake"] or 0)
        self.cur.thr[b] = src["Throttle"] or 0
        g = src["Gear"]
        if g is not None and g > 0:
            self.cur.gear[b] = g if self.cur.gear[b] is None else min(self.cur.gear[b], g)
        out = intro + self._guide(dist, src["Speed"] or 0)
        if me.lap_dirty:
            return out
        return out + self._check_corners(b)

    # ------------------------------------------------------------
    #  Nieuwe baan: per bocht vooraf zeggen wat er komt
    # ------------------------------------------------------------
    def guide_active(self):
        g = self.cfg.get("track_guide", "auto")
        if g == "uit" or not self.ref or not self.corners:
            return False
        if g == "altijd":
            return True
        return self.new_track and self.guide_laps < int(self.cfg.get("track_guide_laps", 5))

    def _guide(self, dist, speed):
        if not self.guide_active() or (self.s.is_race() and self._battling()):
            return []
        lead = max(80.0, speed * 2.8)
        for c in self.corners:
            if c.nr in self.guided:
                continue
            bd = c.brake_bin * BIN_M
            to_go = (bd - dist) % (self.nbins * BIN_M)
            if lead - 40 <= to_go <= lead:
                self.guided.add(c.nr)
                return [(2, self._corner_brief(c))]
        return []

    def _corner_brief(self, c):
        r = self.ref
        peak = max((r.brake[i] or 0) for i in range(c.brake_bin, c.apex_bin + 1))
        rem = "hard remmen" if peak > 0.7 else ("remmen" if peak > 0.35 else "licht remmen")
        gears = [r.gear[i] for i in range(c.brake_bin, c.exit_bin + 1) if r.gear and r.gear[i]]
        names = {1: "eerste", 2: "tweede", 3: "derde", 4: "vierde", 5: "vijfde", 6: "zesde", 7: "zevende"}
        g = names.get(min(gears)) + " versnelling" if gears else None
        vmin = r.v[c.apex_bin]
        parts = [f"Bocht {c.nr}", rem]
        if g:
            parts.append(g)
        if vmin:
            parts.append(f"{round(vmin / 5) * 5} in de top")
        return ", ".join(parts) + "."


    def _check_corners(self, b):
        if not self.ref or not self.corners:
            return []
        tips = []
        for c in self.corners:
            if c.nr in self.reported or b < c.exit_bin or b > c.exit_bin + 20:
                continue
            self.reported.add(c.nr)
            tip = self._analyse(c)
            if tip and not self.guide_active():   # tijdens de baan-uitleg niet ook nog tips
                tips.append(tip)
        return tips

    def _analyse(self, c):
        cur, ref = self.cur, self.ref
        start = max(0, c.brake_bin - int(60 / BIN_M))
        need = [start, c.brake_bin, c.apex_bin, c.exit_bin]
        if any(cur.t[i] is None for i in need):
            return None
        # segmenttijd vergelijken
        seg_cur = cur.t[c.exit_bin] - cur.t[start]
        seg_ref = ref.t[c.exit_bin] - ref.t[start]
        loss = seg_cur - seg_ref
        self.corner_deltas[c.nr] = loss
        # remmoment
        cb = next((i for i in range(start, c.apex_bin + 1) if (cur.brake[i] or 0) > 0.15), None)
        brake_diff_m = (cb - c.brake_bin) * BIN_M if cb is not None else None  # negatief = eerder geremd
        vmin_cur = min(v for v in cur.v[c.brake_bin:c.exit_bin + 1] if v is not None)
        vmin_ref = ref.v[c.apex_bin]
        dv = vmin_cur - vmin_ref
        ct = next((i for i in range(c.apex_bin - 10 if c.apex_bin > 10 else 0, c.exit_bin + 1)
                   if i >= c.apex_bin and (cur.thr[i] or 0) >= 0.5), None)
        thr_diff_m = (ct - c.throttle_bin) * BIN_M if ct is not None else None

        mode = self.mode()
        thresh = self.cfg["min_loss_race"] if mode == "race" else self.cfg["min_loss_practice"]
        if mode == "race" and self.tips_this_lap >= self.cfg["max_tips_per_lap_race"]:
            return None
        if self.cfg.get("quiet_when_battling") and self.s.is_race() and self._battling():
            return None
        sec = f"{abs(loss):.2f}".replace(".", ",")
        name = f"Bocht {c.nr}"
        txt = None
        if loss >= thresh:
            if brake_diff_m is not None and brake_diff_m <= -10:
                txt = f"{name}: {abs(int(brake_diff_m))} meter te vroeg geremd, {sec} verloren. Rem later."
            elif brake_diff_m is not None and brake_diff_m >= 10 and dv < -2:
                txt = f"{name}: te laat op de rem, minimumsnelheid {abs(dv):.0f} kilometer lager. {sec} verloren."
            elif dv <= -3:
                txt = f"{name}: {abs(dv):.0f} kilometer per uur minder bochtsnelheid, {sec} verloren. Meer snelheid meenemen."
            elif thr_diff_m is not None and thr_diff_m >= 10:
                txt = f"{name}: {int(thr_diff_m)} meter later op het gas, {sec} verloren."
            else:
                txt = f"{name}: {sec} verloren op je beste ronde."
        elif loss <= -max(0.1, thresh) and mode == "practice":
            txt = f"{name}: goed, {sec} sneller dan je beste."
        if txt:
            self.tips_this_lap += 1
            return (3, txt)
        return None

    def _battling(self):
        ahead, behind = self.s.neighbours()
        for c in (ahead, behind):
            if c is None:
                continue
            g = self.s.gap_to(c)
            if g is not None and abs(g) < 1.0:
                return True
        return False

    # ------------------------------------------------------------
    def lap_completed(self, lap_time, clean):
        """Aan het eind van een ronde: referentie bijwerken en samenvatting."""
        msgs = []
        if self.corner_deltas:
            self.last_lap_deltas = dict(self.corner_deltas)
        if self.ref is not None and self.cur is not None:
            self.guide_laps += 1
        if self.cur is not None and self.cur.coverage() > 0.9:
            snap = self.cur.copy()
            snap.fill_gaps()
            self.laps.append({"nr": (self.cur_lap_nr or 0) + 1, "tijd": lap_time, "schoon": clean, "lap": snap})
            self.laps = self.laps[-15:]
        lap = self.cur
        if lap is None or self.nbins is None:
            return msgs
        race_quiet = self.mode() == "race" and (self.s.player() and (self.s.player().wraps or 0) % 3 != 0)
        if self.cfg.get("lap_summary") and self.corner_deltas and self.ref and not race_quiet and clean:
            worst = max(self.corner_deltas.items(), key=lambda kv: kv[1])
            best = min(self.corner_deltas.items(), key=lambda kv: kv[1])
            if worst[1] > 0.1 and (self.mode() == "practice" or worst[1] > 0.25):
                msgs.append((4, f"Meeste tijd verloren in bocht {worst[0]}, " + f"{worst[1]:.2f}".replace(".", ",") + " seconde."))
            if self.mode() == "practice" and best[1] < -0.1:
                msgs.append((4, f"Meeste tijd gewonnen in bocht {best[0]}."))
        if clean and lap.coverage() > 0.9 and (self.ref_time is None or lap_time < self.ref_time):
            first = self.ref_time is None
            lap.fill_gaps()
            self.ref, self.ref_time = lap, lap_time
            self._find_corners()
            self._save_ref()
            if first:
                txt = f"Referentieronde opgeslagen. Ik heb {len(self.corners)} bochten gevonden, vanaf nu coach ik per bocht."
                if self.guide_active():
                    txt += " Omdat deze baan nieuw is, zeg ik de komende ronden voor elke bocht wat er komt."
                msgs.append((4, txt))
        return msgs

    def corner_at(self, dist_m):
        """Welke bocht is dit (op basis van de referentieronde)?"""
        if not self.corners or dist_m is None:
            return None
        b = int(dist_m / BIN_M)
        for c in self.corners:
            if c.brake_bin - int(40 / BIN_M) <= b <= c.exit_bin + int(40 / BIN_M):
                return c.nr
        return None

    def delta_now(self):
        """(ronde, seconden achter op je referentieronde op dit punt)"""
        if not self.ref or self.cur is None or getattr(self, "last_bin", None) is None:
            return None
        rt = self.ref.t[self.last_bin]
        if rt is None:
            return None
        return (self.cur_lap_nr, self.last_t_in - rt)

    def summary(self):
        return {"referentie_ronde": self.ref_time, "bochten": len(self.corners),
                "laatste_ronde_per_bocht_verschil_s": {k: round(v, 2) for k, v in self.corner_deltas.items()}}
