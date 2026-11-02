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
        self.steer = [None] * nbins   # graden

    def fill_gaps(self):
        for arr in (self.t, self.v, self.brake, self.thr, self.gear, self.steer):
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
        return {"t": self.t, "v": self.v, "brake": self.brake, "thr": self.thr, "gear": self.gear, "steer": self.steer}

    @classmethod
    def from_dict(cls, d):
        lap = cls(len(d["t"]))
        lap.t, lap.v, lap.brake, lap.thr = d["t"], d["v"], d["brake"], d["thr"]
        lap.gear = d.get("gear") or [None] * lap.n
        lap.steer = d.get("steer") or [None] * lap.n
        return lap

    def copy(self):
        return Lap.from_dict({k: list(v) for k, v in self.to_dict().items()})


class Corner:
    def __init__(self, nr, brake_bin, apex_bin, exit_bin, throttle_bin, flat=False, start_bin=None):
        self.nr = nr
        self.brake_bin = brake_bin
        self.apex_bin = apex_bin
        self.exit_bin = exit_bin
        self.throttle_bin = throttle_bin
        self.flat = flat                      # gaat zonder remmen
        self.start_bin = brake_bin if start_bin is None else start_bin   # waar de bocht begint


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
        self.ext = None             # referentie van een snellere rijder (reference.RefLap)
        self.corners_from_ext = False
        self.new_track = False
        self.guide_laps = 0
        self.guided = set()
        self.map = None             # trackmap.TrackMap (gezet door de motor)
        self.map_version = 0
        self.map_announce = None

    # ------------------------------------------------------------
    def _setup(self):
        self.nbins = max(50, int(self.s.track_len_m / BIN_M))
        self.key = f"{_slug(self.s.track_name)}__{_slug(self.s.car_name)}"
        if self.map is not None:
            self.map.setup(self.s.track_name, self.nbins)
        self._load_ref()
        if self.map is not None and self.map.ready and not self.corners and self.ext is not None:
            self._corners_from_ext()

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

    def set_ext(self, lap):
        """Referentieronde van een snellere rijder (uit de bibliotheek)."""
        if lap is not None and self.nbins is not None and lap.n != self.nbins:
            return
        self.ext = lap
        if lap is not None and not self.corners:
            self._corners_from_ext()

    def use_ext(self):
        return self.ext is not None and (self.ref_time is None or self.ext.lap_time < self.ref_time - 0.05)

    # ------------------------------------------------------------
    #  Bochten uit de bochtenkaart (alle echte bochten, ook vol gas)
    # ------------------------------------------------------------
    def _corners_from_map(self, r, has_pedals):
        n = self.nbins
        out = []
        for mc in self.map.corners:
            a, top, e = mc["start"], mc["top"], mc["eind"]
            vs = [(r.v[i] if r.v[i] is not None else 999, i) for i in range(a, e + 1)]
            apex = min(vs)[1] if vs else top
            lo = max(0, a - int(300 / BIN_M))
            brake_bin, flat = a, True
            if has_pedals:
                braked = [i for i in range(lo, apex + 1) if (r.brake[i] or 0) > 0.15]
                if braked and braked[-1] >= a - int(40 / BIN_M):
                    j = braked[-1]
                    while j - 1 >= lo and (r.brake[j - 1] or 0) > 0.05:
                        j -= 1
                    brake_bin, flat = j, False
                thr = next((i for i in range(apex, min(n - 1, e + int(60 / BIN_M)) + 1) if (r.thr[i] or 0) >= 0.5), apex)
            else:
                pk = max(range(lo, apex + 1), key=lambda i: r.v[i] or 0)
                if (r.v[pk] or 0) - (r.v[apex] or 0) >= 10:
                    vpk = r.v[pk]
                    j = pk
                    while j + 1 < apex and (r.v[j + 1] or 0) >= vpk - 2:
                        j += 1
                    brake_bin, flat = j, False
                vmin = r.v[apex] or 0
                thr = next((i for i in range(apex, min(n - 1, e + int(60 / BIN_M)) + 1) if (r.v[i] or 0) > vmin + 3), apex)
            exit_bin = min(n - 1, max(e, thr) + int(40 / BIN_M))
            out.append(Corner(mc["nr"], brake_bin, apex, exit_bin, thr, flat=flat, start_bin=a))
        self.corners = out

    def map_ready(self):
        return self.map is not None and self.map.ready and self.nbins is not None

    def on_map_ready(self):
        """De bochtenkaart is net gemaakt: bochten opnieuw indelen."""
        if self.ref is not None:
            self._find_corners()
        elif self.ext is not None:
            self._corners_from_ext()
        self.map_version += 1
        n_flat = sum(1 for c in self.corners if c.flat)
        extra = f", waarvan {n_flat} zonder remmen" if n_flat else ""
        return [(4, f"Ik heb de baan in kaart: {len(self.map.corners)} bochten{extra}. Vanaf nu gebruik ik die nummers.")]

    def _corners_from_ext(self):
        from reference import corner_metrics, corners_from_speed
        e = self.ext
        if self.map_ready():
            self._corners_from_map(e, has_pedals=False)
            self.corners_from_ext = True
            return
        out = []
        for k, apex in enumerate(corners_from_speed(e.v)):
            m = corner_metrics(e.v, e.gear, apex, max(0, apex - int(250 / BIN_M)), min(e.n - 1, apex + int(200 / BIN_M)))
            if not m:
                continue
            exit_bin = min(e.n - 1, m["accel"] + int(80 / BIN_M))
            out.append(Corner(k + 1, m["brake"], m["apex"], exit_bin, m["accel"]))
        self.corners = out
        self.corners_from_ext = True

    def mode(self):
        m = self.cfg.get("mode", "auto")
        if m == "auto":
            return "race" if self.s.is_race() else "practice"
        return m

    # ------------------------------------------------------------
    def _find_corners(self):
        r = self.ref
        n = r.n
        if self.map_ready():
            self._corners_from_map(r, has_pedals=True)
            self.corners_from_ext = False
            return
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
        self.corners_from_ext = False

    # ------------------------------------------------------------
    def update(self, src, lap_time_now):
        """Elke tick. Geeft lijst (prioriteit, tekst) van tips terug."""
        if not self.cfg.get("enabled") or self.mode() == "off":
            return []
        intro = []
        if self.nbins is None or self.key != f"{_slug(self.s.track_name)}__{_slug(self.s.car_name)}":
            self._setup()
            if self.new_track and self.cfg.get("track_guide", "auto") != "uit":
                if self.ext is not None:
                    intro = [(4, "Nieuwe baan met deze auto, maar ik heb een snelle ronde van "
                                 f"{self.ext.meta.get('rijder', 'een andere rijder')}. Ik zeg per bocht wat hij doet.")]
                else:
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
        prev = getattr(self, "_prev_pos", None)
        if prev and prev[2] == lap_nr and dist > prev[0] and b > prev[1]:
            # tijden van tussenliggende meetpunten precies interpoleren (niet afronden op 1/60 s)
            d0, b0, _, t0 = prev
            for k in range(b0 + 1, b + 1):
                if self.cur.t[k] is None:
                    f = (k * BIN_M - d0) / (dist - d0)
                    self.cur.t[k] = t0 + max(0.0, min(1.0, f)) * (t_in - t0)
        self._prev_pos = (dist, b, lap_nr, t_in)
        self.last_bin, self.last_t_in = b, t_in
        if self.cur.t[b] is None:
            self.cur.t[b] = t_in
        self.cur.v[b] = (src["Speed"] or 0) * 3.6 if self.cur.v[b] is None else min(self.cur.v[b], (src["Speed"] or 0) * 3.6)
        self.cur.brake[b] = max(self.cur.brake[b] or 0, src["Brake"] or 0)
        self.cur.thr[b] = src["Throttle"] or 0
        sw = src["SteeringWheelAngle"]
        if sw is not None:
            self.cur.steer[b] = round(sw * 57.2958, 1)
        g = src["Gear"]
        if g is not None and g > 0:
            self.cur.gear[b] = g if self.cur.gear[b] is None else min(self.cur.gear[b], g)
        if self.map is not None:
            self.map.record(lap_nr, dist, src["Speed"], src["YawRate"], not me.on_pit)
        out = intro + self._guide(dist, src["Speed"] or 0)
        if me.lap_dirty:
            return out
        return out + self._check_corners(b)

    # ------------------------------------------------------------
    #  Nieuwe baan: per bocht vooraf zeggen wat er komt
    # ------------------------------------------------------------
    def guide_active(self):
        g = self.cfg.get("track_guide", "auto")
        if g == "uit" or not self.corners or (not self.ref and self.ext is None):
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
            bd = (c.start_bin if c.flat else c.brake_bin) * BIN_M
            to_go = (bd - dist) % (self.nbins * BIN_M)
            if lead - 40 <= to_go <= lead:
                self.guided.add(c.nr)
                return [(2, self._corner_brief(c))]
        return []

    def _corner_brief(self, c):
        r = self.ref if self.ref is not None and not self.use_ext() else self.ext
        if c.flat:
            lift = r is self.ref and min((r.thr[i] or 0) for i in range(c.start_bin, c.apex_bin + 1)) < 0.85
            vmin = r.v[c.apex_bin]
            txt = f"Bocht {c.nr}, " + ("even van het gas" if lift else "vol gas")
            return txt + (f", {round(vmin / 5) * 5} in de top." if vmin else ".")
        if r is self.ext:
            drop = (r.v[c.brake_bin] or 0) - (r.v[c.apex_bin] or 0)
            rem = "hard remmen" if drop > 80 else ("remmen" if drop > 30 else "licht remmen")
        else:
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
        if not self.corners or (not self.ref and self.ext is None):
            return []
        tips = []
        for c in self.corners:
            if c.nr in self.reported or b < c.exit_bin or b > c.exit_bin + 20:
                continue
            self.reported.add(c.nr)
            tip = self._analyse(c)
            focus = getattr(self, "focus_corner", None)
            if focus and c.nr != focus and tip and abs(self.corner_deltas.get(c.nr, 0)) < 0.2:
                tip = None   # lesplan: andere bochten alleen als er echt veel tijd ligt
            if tip and not self.guide_active():   # tijdens de baan-uitleg niet ook nog tips
                tips.append(tip)
        return tips

    def _analyse(self, c):
        if self.use_ext():
            return self._analyse_ext(c)
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
        if loss >= thresh and c.flat:
            lift_cur = min((cur.thr[i] or 0) for i in range(c.start_bin, c.apex_bin + 1))
            lift_ref = min((ref.thr[i] or 0) for i in range(c.start_bin, c.apex_bin + 1))
            if cb is not None and (ref.brake[cb] or 0) < 0.05:
                txt = f"{name} kan zonder remmen. Je remde, {sec} verloren."
            elif lift_cur < lift_ref - 0.25:
                txt = f"{name}: je ging meer van het gas dan in je beste ronde, {sec} verloren."
            elif dv <= -3:
                txt = f"{name}: {abs(dv):.0f} kilometer per uur langzamer door de bocht, {sec} verloren."
            else:
                txt = f"{name}: {sec} verloren op je beste ronde."
        elif loss >= thresh:
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

    def _analyse_ext(self, c):
        """Vergelijk deze bocht met de ronde van een snellere rijder (alleen snelheid/versnelling bekend)."""
        from reference import corner_metrics
        cur, ext = self.cur, self.ext
        start = max(0, c.brake_bin - int(60 / BIN_M))
        end = c.exit_bin
        if any(cur.t[i] is None for i in (start, c.apex_bin, end)) or ext.t[start] is None or ext.t[end] is None:
            return None
        loss = (cur.t[end] - cur.t[start]) - (ext.t[end] - ext.t[start])
        self.corner_deltas[c.nr] = loss
        lo = c.start_bin if c.flat else max(0, c.brake_bin - int(150 / BIN_M))
        hi = min(cur.n - 1, end)
        from reference import speed_profile
        mine = corner_metrics(speed_profile(cur.t), cur.gear, c.apex_bin, lo, hi)
        theirs = corner_metrics(ext.v, ext.gear, c.apex_bin, lo, hi)
        if not mine or not theirs:
            return None
        mode = self.mode()
        thresh = self.cfg["min_loss_race"] if mode == "race" else self.cfg["min_loss_practice"]
        if mode == "race" and self.tips_this_lap >= self.cfg["max_tips_per_lap_race"]:
            return None
        if self.cfg.get("quiet_when_battling") and self.s.is_race() and self._battling():
            return None
        names = {1: "eerste", 2: "tweede", 3: "derde", 4: "vierde", 5: "vijfde", 6: "zesde", 7: "zevende"}
        parts = []
        bd = (mine["brake"] - theirs["brake"]) * BIN_M          # negatief = jij remt eerder
        dv = mine["vmin"] - theirs["vmin"]
        ad = (mine["accel"] - theirs["accel"]) * BIN_M          # positief = jij later op snelheid
        if c.flat:
            bd = 0   # vol-gas-bocht: geen rempunt om te vergelijken
        if bd <= -10:
            parts.append(f"de snelste remt {int(abs(bd))} meter later")
        elif bd >= 10 and dv < -2:
            parts.append(f"jij remt {int(bd)} meter later maar komt er langzamer door")
        if dv <= -3:
            parts.append(f"hij gaat {abs(dv):.0f} kilometer per uur sneller door de top")
        if theirs["gear"] and mine["gear"] and theirs["gear"] != mine["gear"]:
            parts.append(f"hij neemt hem in de {names.get(theirs['gear'], theirs['gear'])}")
        if ad >= 10:
            parts.append(f"hij is {int(ad)} meter eerder weer op snelheid")
        sec = f"{abs(loss):.2f}".replace(".", ",")
        txt = None
        if loss >= thresh:
            if parts:
                txt = f"Bocht {c.nr}: " + ", ".join(parts[:2]) + f". {sec} verloren."
            else:
                txt = f"Bocht {c.nr}: {sec} verloren op de referentie."
        elif loss <= -max(0.1, thresh) and mode == "practice":
            txt = f"Bocht {c.nr}: sneller dan de referentie!"
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
        if (self.ref is not None or self.ext is not None) and self.cur is not None:
            self.guide_laps += 1
        if self.map is not None and self.map.lap_done(clean and self.cur is not None and self.cur.coverage() > 0.9):
            msgs += self.on_map_ready()
        if self.cur is not None and self.cur.coverage() > 0.9:
            snap = self.cur.copy()
            snap.fill_gaps()
            self.laps.append({"nr": (self.cur_lap_nr or 0) + 1, "tijd": lap_time, "schoon": clean, "lap": snap})
            self.laps = self.laps[-15:]
        lap = self.cur
        if lap is None or self.nbins is None:
            return msgs
        race_quiet = self.mode() == "race" and (self.s.player() and (self.s.player().wraps or 0) % 3 != 0)
        if self.cfg.get("lap_summary") and self.corner_deltas and self.use_ext() and not race_quiet and clean:
            gap = lap_time - self.ext.lap_time
            worst = [k for k, v in sorted(self.corner_deltas.items(), key=lambda kv: -kv[1]) if v > 0.08][:2]
            if gap > 0:
                txt = (f"Op de referentie van {self.ext.meta.get('rijder', '?')} verlies je " + f"{gap:.2f}".replace(".", ",") + ".")
                if worst:
                    txt += " Het meest in bocht " + " en ".join(str(k) for k in worst) + "."
                msgs.append((4, txt))
            else:
                msgs.append((4, "Je was sneller dan de referentie! Die ronde wordt je nieuwe maatstaf."))
        elif self.cfg.get("lap_summary") and self.corner_deltas and self.ref and not race_quiet and clean:
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
                "snelle_referentie": ({"rijder": self.ext.meta.get("rijder"), "tijd": self.ext.lap_time,
                                       "datum": self.ext.meta.get("datum")} if self.ext else None),
                "vergelijkt_met": "snelle referentie" if self.use_ext() else "eigen beste ronde",
                "laatste_ronde_per_bocht_verschil_s": {k: round(v, 2) for k, v in self.corner_deltas.items()}}
