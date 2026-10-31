"""Houdt de hele race bij: alle auto's, rondetijden, gaps via tijdmeetpunten,
posities, brandstofverbruik en pitstops."""
import math
import re

N_CP = 100            # tijdmeetpunten per ronde (elke 1%)
KEEP_LAPS = 4         # zoveel ronden geschiedenis per auto


def fmt_lap(t):
    if t is None or t <= 0:
        return "-"
    m = int(t // 60)
    s = t - m * 60
    return f"{m}:{s:04.1f}".replace(".", ",")


def say_lap(t):
    """Rondetijd zoals je hem uitspreekt: 1 32,4"""
    if t is None or t <= 0:
        return "onbekend"
    m = int(t // 60)
    s = t - m * 60
    return f"{m} {s:.1f}".replace(".", ",")


def say_sec(x, decimals=1):
    return f"{abs(x):.{decimals}f}".replace(".", ",")


class Car:
    def __init__(self, idx):
        self.idx = idx
        self.name = f"auto {idx}"
        self.number = ""
        self.class_id = 0
        self.wraps = None        # aantal gefinishte ronden (eigen telling)
        self.last_pct = None
        self.last_g = None       # laatste globale meetpunt-index
        self.cp_times = {}       # globale index -> sessietijd
        self.lap_times = []      # (lap_nr, tijd, schoon?)
        self.lap_start_t = None
        self.lap_dirty = False
        self.lap_pit = False
        self.on_pit = False
        self.pit_stops = 0
        self.last_pit_lap = None
        self.position = 0
        self.official_pos = 0
        self.class_name = ""
        self.class_est_lap = None
        self.irating = 0
        self.license = ""
        self.inc_count = 0

    @property
    def progress(self):
        if self.wraps is None or self.last_pct is None:
            return -1e9
        return self.wraps + self.last_pct

    @property
    def last_lap(self):
        return self.lap_times[-1][1] if self.lap_times else None

    def best_lap(self):
        clean = [t for _, t, ok in self.lap_times if ok]
        return min(clean) if clean else None

    def avg_lap(self, n=3):
        clean = [t for _, t, ok in self.lap_times if ok][-n:]
        return sum(clean) / len(clean) if clean else None

    def time_at(self, g):
        return self.cp_times.get(g)


class RaceState:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cars = {}
        self.player_idx = None
        self.track_name = ""
        self.track_len_m = 4000.0
        self.car_name = ""
        self.session_type = ""
        self.session_num = None
        self.session_state = 0
        self.fuel_max = None
        self.total_laps = None
        self.t = 0.0
        self.fuel = None
        self.fuel_at_lap_start = None
        self.fuel_laps = []      # (lap, verbruik, schoon?)
        self.laps_remaining = None
        self.time_remaining = None
        self.caution = False
        self.events = []         # gebeurtenissen voor de engineer
        self.pit_loss = cfg["engineer"]["pit_loss_seconds"]
        self.pit_lap_times = []
        self.incidents = 0
        self.start_position = None
        self.position_history = []   # (lap, positie)
        self._last_info_update = -1
        self.flags = 0
        self.pits_open = True

    # ------------------------------------------------------------
    def player(self):
        return self.cars.get(self.player_idx)

    def is_race(self):
        return "race" in (self.session_type or "").lower()

    def _load_session_info(self, src):
        di = src["DriverInfo"] or {}
        self.player_idx = di.get("DriverCarIdx", self.player_idx)
        self.fuel_max = di.get("DriverCarFuelMaxLtr") or self.fuel_max
        style = self.cfg["engineer"]["name_style"]
        for d in di.get("Drivers", []) or []:
            if d.get("CarIsPaceCar") or d.get("IsSpectator"):
                continue
            idx = d["CarIdx"]
            car = self.cars.setdefault(idx, Car(idx))
            full = re.sub(r"\d+$", "", str(d.get("UserName", ""))).strip()
            car.number = str(d.get("CarNumber", ""))
            car.class_id = d.get("CarClassID", 0)
            car.class_name = str(d.get("CarClassShortName") or "")
            try:
                car.class_est_lap = float(d.get("CarClassEstLapTime") or 0) or None
            except (TypeError, ValueError):
                car.class_est_lap = None
            car.irating = int(d.get("IRating") or 0)
            car.license = str(d.get("LicString") or "")
            car.inc_count = int(d.get("CurDriverIncidentCount") or 0)
            if style == "nummer":
                car.name = f"nummer {car.number}"
            elif style == "volledig":
                car.name = full
            else:
                car.name = full.split(" ")[-1] if full else f"nummer {car.number}"
            if idx == self.player_idx:
                self.car_name = d.get("CarScreenNameShort", "")
        wi = src["WeekendInfo"] or {}
        self.track_name = wi.get("TrackDisplayName", "")
        tl = str(wi.get("TrackLength", "4 km"))
        try:
            val = float(tl.split()[0])
            self.track_len_m = val * (1609.34 if "mi" in tl else 1000.0)
        except Exception:
            pass
        si = src["SessionInfo"] or {}
        num = src["SessionNum"]
        for s in si.get("Sessions", []) or []:
            if s.get("SessionNum") == num:
                self.session_type = s.get("SessionType", "")
                laps = str(s.get("SessionLaps", ""))
                self.total_laps = int(laps) if laps.isdigit() else None

    # ------------------------------------------------------------
    def update(self, src):
        """Eén tick verwerken. Geeft lijst van gebeurtenissen terug."""
        self.events = []
        info_upd = src.session_info_update
        num = src["SessionNum"]
        if info_upd != self._last_info_update or num != self.session_num:
            if num != self.session_num and self.session_num is not None:
                self._reset_session()
            self.session_num = num
            self._load_session_info(src)
            self._last_info_update = info_upd

        self.t = src["SessionTime"] or 0.0
        st = src["SessionState"] or 0
        if st != self.session_state:
            self.events.append(("session_state", st))
            self.session_state = st
        flags = src["SessionFlags"] or 0
        self.flags = flags
        self.caution = bool(flags & (0x4000 | 0x8000))
        po = src["PitsOpen"]
        self.pits_open = True if po is None else bool(po)
        self.fuel = src["FuelLevel"]
        lr = src["SessionLapsRemainEx"]
        self.laps_remaining = lr if lr is not None and 0 <= lr < 32000 else None
        tr = src["SessionTimeRemain"]
        self.time_remaining = tr if tr is not None and 0 < tr < 600000 else None
        inc = src["PlayerCarMyIncidentCount"]
        if inc is not None and inc > self.incidents:
            self.events.append(("incident", inc - self.incidents))
            self.incidents = inc
            if self.player():
                self.player().lap_dirty = True

        pcts = src["CarIdxLapDistPct"] or []
        laps = src["CarIdxLapCompleted"] or []
        opos = src["CarIdxClassPosition"] if self.cfg["engineer"]["class_only"] else src["CarIdxPosition"]
        opos = opos or []
        pits = src["CarIdxOnPitRoad"] or []
        surf = src["CarIdxTrackSurface"] or []
        for idx, car in self.cars.items():
            if idx >= len(pcts):
                continue
            pct = pcts[idx]
            if pct is None or pct < 0 or (idx < len(surf) and surf[idx] == -1):
                continue  # niet in de wereld
            if idx < len(opos) and opos[idx]:
                car.official_pos = opos[idx]
            self._update_car(car, pct, laps[idx] if idx < len(laps) else 0,
                             bool(pits[idx]) if idx < len(pits) else False)
        self._update_positions()
        return self.events

    def _reset_session(self):
        keep = self.cfg
        self.__init__(keep)

    def _update_car(self, car, pct, lap_completed, on_pit):
        # voortgang = voltooide ronden + fractie. Op de grid: -1 + 0,98
        if lap_completed is None:
            lap_completed = 0
        if car.wraps is None:
            car.wraps = lap_completed
            car.last_pct = pct
            car.last_g = car.wraps * N_CP + int(pct * N_CP)
            car.on_pit = on_pit
            return
        crossed = False
        if car.last_pct > 0.85 and pct < 0.15:
            car.wraps += 1
            crossed = True
        elif pct > 0.85 and car.last_pct < 0.15:
            car.wraps -= 1  # achteruit over de lijn (zeldzaam)
        elif 0.1 < pct < 0.9 and lap_completed >= 0 and lap_completed != car.wraps:
            car.wraps = lap_completed  # opnieuw synchroniseren (reset/tow)
        car.last_pct = pct
        g = car.wraps * N_CP + int(pct * N_CP)
        if car.last_g is not None and g > car.last_g:
            # alle tussenliggende meetpunten (bij lage samplefrequentie) dezelfde tijd geven
            for k in range(car.last_g + 1, g + 1):
                car.cp_times[k] = self.t
            if len(car.cp_times) > N_CP * KEEP_LAPS:
                lim = g - N_CP * KEEP_LAPS
                for k in [k for k in car.cp_times if k < lim]:
                    del car.cp_times[k]
        car.last_g = g

        if on_pit and not car.on_pit:
            car.pit_stops += 1
            car.last_pit_lap = car.wraps + 1
            car.lap_dirty = True
            if car.idx == self.player_idx:
                self.events.append(("player_pit_in", car.wraps + 1))
            elif self.is_race():
                self.events.append(("car_pit_in", car.idx))
        if not on_pit and car.on_pit and car.idx == self.player_idx:
            self.events.append(("player_pit_out", car.wraps + 1))
        if on_pit:
            car.lap_dirty = True
            car.lap_pit = True
        car.on_pit = on_pit

        if crossed:
            if car.lap_start_t is not None:
                lt = self.t - car.lap_start_t
                clean = not car.lap_dirty and not self.caution
                if 20 < lt < 1200:
                    car.lap_times.append((car.wraps, lt, clean))
                    if car.idx == self.player_idx:
                        self.pit_lap_times.append(car.lap_pit)
                        self._learn_pit_loss(car)
                        self.events.append(("player_lap", car.wraps, lt, clean))
            car.lap_start_t = self.t
            car.lap_dirty = on_pit
            car.lap_pit = on_pit
            if car.idx == self.player_idx:
                self._fuel_lap(car)

    def _learn_pit_loss(self, car):
        # pit_lap_times loopt synchroon met car.lap_times: True = pit in die ronde
        flags = self.pit_lap_times
        if len(flags) < 3 or flags[-1] or not flags[-2]:
            return
        n = 0
        while n + 1 < len(flags) and flags[-2 - n]:
            n += 1
        pit_laps = [t for _, t, _ in car.lap_times[-1 - n:-1]]
        ref = car.avg_lap(5)
        if ref and pit_laps:
            loss = sum(pit_laps) - n * ref
            if 8 < loss < 120:
                self.pit_loss = round(loss, 1)
                self.events.append(("pit_loss_learned", self.pit_loss))

    def _fuel_lap(self, car):
        if self.fuel is None:
            return
        if self.fuel_at_lap_start is not None:
            used = self.fuel_at_lap_start - self.fuel
            clean = (not self.caution) and bool(car.lap_times) and car.lap_times[-1][2]
            if used > 0.05:
                self.fuel_laps.append((car.wraps, used, clean))
        self.fuel_at_lap_start = self.fuel

    def _update_positions(self):
        me = self.player()
        if not me:
            return
        cls_only = self.cfg["engineer"]["class_only"]
        field = [c for c in self.cars.values() if c.wraps is not None and
                 (not cls_only or c.class_id == me.class_id)]
        if self.session_state >= 5 and all(c.official_pos for c in field):
            field.sort(key=lambda c: c.official_pos)
        else:
            field.sort(key=lambda c: -c.progress)
        old = me.position
        for i, c in enumerate(field):
            c.position = i + 1
        if self.is_race() and self.session_state == 4 and me.progress > 0.05:
            if old and me.position != old:
                self.events.append(("position_change", old, me.position))
            if self.start_position is None:
                self.start_position = old or me.position

    # ------------------------------------------------------------
    #  Gaps
    # ------------------------------------------------------------
    def field(self):
        me = self.player()
        cls_only = self.cfg["engineer"]["class_only"]
        f = [c for c in self.cars.values() if c.wraps is not None and
             (not cls_only or not me or c.class_id == me.class_id)]
        f.sort(key=lambda c: c.position or 999)
        return f

    def overall_leader(self):
        cars = [c for c in self.cars.values() if c.wraps is not None]
        return max(cars, key=lambda c: c.progress) if cars else None

    def neighbours(self):
        """(auto voor, auto achter) in de klassering."""
        f = self.field()
        me = self.player()
        if not me or me not in f:
            return None, None
        i = f.index(me)
        ahead = f[i - 1] if i > 0 else None
        behind = f[i + 1] if i + 1 < len(f) else None
        return ahead, behind

    def gap_to(self, other):
        """Tijdsverschil in seconden. Positief = andere auto ligt voor."""
        me = self.player()
        if not me or not other or me.last_g is None or other.last_g is None:
            return None
        if other.progress >= me.progress:
            g = me.last_g
            t_me, t_o = me.time_at(g), other.time_at(g)
            if t_me is None or t_o is None:
                return None
            return t_me - t_o
        g = other.last_g
        t_me, t_o = me.time_at(g), other.time_at(g)
        if t_me is None or t_o is None:
            return None
        return -(t_o - t_me)

    def laps_between(self, other):
        me = self.player()
        return int(math.floor(abs(other.progress - me.progress)))

    def race_order_summary(self, n=None):
        out = []
        for c in self.field()[: n or 99]:
            g = self.gap_to(c) if c.idx != self.player_idx else 0.0
            out.append({
                "pos": c.position, "naam": c.name, "nr": c.number,
                "is_jij": c.idx == self.player_idx,
                "gap_tot_jou_s": round(g, 2) if g is not None else None,
                "laatste_ronde": round(c.last_lap, 2) if c.last_lap else None,
                "gem_3_ronden": round(c.avg_lap(), 2) if c.avg_lap() else None,
                "pitstops": c.pit_stops,
                "in_pit": c.on_pit,
            })
        return out
