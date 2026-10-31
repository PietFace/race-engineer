"""Spins, van de baan, incidentpunten en verkeer na een spin."""
import math

from race_state import say_sec

# iRacing TrkLoc: -1 niet in de wereld, 0 van de baan, 1 pitbox, 2 pitstraat-aanloop, 3 op de baan
OFF_TRACK, ON_TRACK = 0, 3


class Incident:
    def __init__(self, kind, t, lap, corner, pos, behind_names, behind_idx, coach_delta):
        self.kind = kind                # 'spin' of 'off'
        self.t0 = t
        self.lap = lap
        self.corner = corner
        self.pos0 = pos
        self.behind_idx = set(behind_idx)
        self.behind_names = behind_names
        self.coach_delta0 = coach_delta
        self.points = 0
        self.announced = False
        self.traffic = "none"           # none | wait | clear
        self.last_traffic_msg = -99
        self.recover_since = None
        self.slow_since = None


class IncidentWatcher:
    def __init__(self, cfg, state, coach):
        self.cfg = cfg.get("incidents", {}) or {}
        self.s = state
        self.coach = coach
        self.active = None
        self.cond_since = None
        self.off_since = None
        self.log = []                   # alle incidenten van de sessie
        self.pending_points = None      # (tijd, punten) wachten of er een spin bij hoort
        self.limit = None
        self.limit_warned = set()
        self._car_v = {}                # idx -> (pct, t, snelheid m/s)

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    # ------------------------------------------------------------
    def _read_limit(self, src):
        wi = src["WeekendInfo"] or {}
        lim = str((wi.get("WeekendOptions") or {}).get("IncidentLimit", "")).strip()
        self.limit = int(lim) if lim.isdigit() and int(lim) > 0 else None

    def _corner(self):
        me = self.s.player()
        if not me or me.last_pct is None:
            return None
        return self.coach.corner_at(me.last_pct * self.s.track_len_m)

    def _where(self, corner):
        return f" in bocht {corner}" if corner else ""

    def _track_speeds(self, src):
        pcts = src["CarIdxLapDistPct"] or []
        t = self.s.t
        L = self.s.track_len_m
        for idx in self.s.cars:
            if idx >= len(pcts) or pcts[idx] is None or pcts[idx] < 0:
                continue
            p = pcts[idx]
            prev = self._car_v.get(idx)
            if prev and t > prev[1]:
                dp = (p - prev[0]) % 1.0
                if dp > 0.5:
                    dp -= 1.0
                v = dp * L / (t - prev[1])
                v = 0.7 * prev[2] + 0.3 * v if prev[2] else v
                self._car_v[idx] = (p, t, v)
            elif not prev:
                self._car_v[idx] = (p, t, 0.0)

    # ------------------------------------------------------------
    def update(self, src, events):
        if not self.enabled:
            return []
        out = []
        s = self.s
        me = s.player()
        if getattr(self, "_info_upd", None) != src.session_info_update:
            self._info_upd = src.session_info_update
            self._read_limit(src)
        self._track_speeds(src)
        if not me or me.wraps is None or (me.wraps < 0 and (me.last_pct or 0) > 0.5):
            return out

        for ev in events:
            if ev[0] == "incident":
                if self.active and s.t - self.active.t0 < 8:
                    self.active.points += ev[1]
                else:
                    self.pending_points = (s.t, ev[1], self._corner())

        speed = src["Speed"] or 0.0
        yaw = src["YawRate"] or 0.0
        vx = src["VelocityX"]
        vy = src["VelocityY"]
        surf = src["PlayerTrackSurface"]
        on_pit = me.on_pit or surf in (1, 2) or surf == -1

        if on_pit:
            self.active = None
            self.cond_since = self.off_since = None
            return out

        slip = 0.0
        if vx is not None and vy is not None and speed > 3:
            slip = math.degrees(math.atan2(abs(vy), vx))   # >90 = achteruit

        # ---- detectie ----
        spin_cond = speed > 6 and (abs(yaw) > 1.5 or slip > 55)
        if spin_cond:
            self.cond_since = self.cond_since if self.cond_since is not None else s.t
        else:
            self.cond_since = None
        off_cond = surf == OFF_TRACK and speed > 3
        if off_cond:
            self.off_since = self.off_since if self.off_since is not None else s.t
        else:
            self.off_since = None

        if self.active is None:
            if self.cond_since is not None and s.t - self.cond_since > 0.25:
                self._start("spin")
                out.append((1, "Spin. Rem vast, ik kijk naar het verkeer."))
                self.active.announced = True
            elif self.off_since is not None and s.t - self.off_since > 1.2:
                self._start("off")
        elif self.active.kind == "off" and self.cond_since is not None and s.t - self.cond_since > 0.25:
            self.active.kind = "spin"   # eraf en daarna gespind
            out.append((1, "Spin. Rem vast, ik kijk naar het verkeer."))
            self.active.announced = True

        # ---- losse incidentpunten zonder spin ----
        if self.pending_points and s.t - self.pending_points[0] > 1.0:
            t0, pts, corner = self.pending_points
            self.pending_points = None
            if self.active:
                self.active.points += pts
            else:
                what = {1: "vier wielen eraf", 2: "verlies van controle", 4: "contact"}.get(pts, "incident")
                out.append((2, f"{pts}x, {what}{self._where(corner)}. Totaal {s.incidents}x."))
                self.log.append({"ronde": (me.wraps or 0) + 1, "bocht": corner, "soort": what, "punten": pts})
                out += self._limit_check()

        if self.active:
            out += self._follow(src, speed, surf, slip)
        return out

    def _start(self, kind):
        s = self.s
        me = s.player()
        f = s.field()
        behind = [c for c in f if c.position > me.position]
        self.active = Incident(kind, s.t, (me.wraps or 0) + 1, self._corner(), me.position,
                               [c.name for c in behind], [c.idx for c in behind], self.coach.delta_now())

    def _follow(self, src, speed, surf, slip):
        """Tijdens het incident: verkeer melden, en herstel herkennen."""
        out = []
        s, inc = self.s, self.active
        me = s.player()
        if s.t - inc.t0 > 90:   # weggesleept of iets vreemds
            self.active = None
            return out

        if inc.kind == "off" and not inc.announced and speed < 12:
            inc.announced = True
            out.append((1, "Van de baan. Rustig terugkomen, ik kijk naar het verkeer."))

        # verkeer: alleen als je langzaam bent
        if speed < 20 and inc.announced and self.cfg.get("traffic_warnings", True):
            traffic = [x for x in self._traffic(src) if x[0] < 4.5]
            if traffic:
                eta, name = traffic[0]
                if inc.traffic != "wait" and s.t - inc.last_traffic_msg > 1.2:
                    inc.traffic = "wait"
                    inc.last_traffic_msg = s.t
                    more = ""
                    if len(traffic) == 2:
                        more = f", {traffic[1][1]} erachter"
                    elif len(traffic) > 2:
                        more = f", en nog {len(traffic) - 1} auto's erachter"
                    if eta < 1.5:
                        out.append((1, f"Wacht! {name} komt nu langs{more}."))
                    else:
                        out.append((1, f"Wacht, {name} komt eraan, {max(1, round(eta))} seconde{more}."))
            else:
                if speed < 2:
                    inc.slow_since = inc.slow_since if inc.slow_since is not None else s.t
                else:
                    inc.slow_since = None
                stopped = inc.slow_since is not None and s.t - inc.slow_since > 1.0
                if inc.traffic in ("none", "wait") and s.t - inc.last_traffic_msg > 1.2:
                    if inc.traffic == "wait" or stopped:
                        inc.traffic = "clear"
                        inc.last_traffic_msg = s.t
                        out.append((1, "Vrij. Je kunt gaan."))

        # herstel: weer op de baan op snelheid
        if surf == ON_TRACK and speed > 25 and slip < 20:
            inc.recover_since = inc.recover_since if inc.recover_since is not None else s.t
            if s.t - inc.recover_since > 2.0:
                out += self._finish()
        else:
            inc.recover_since = None
        return out

    def _traffic(self, src):
        """Naderende auto's achter je op de baan: [(seconden, naam)], dichtstbijzijnde eerst."""
        s = self.s
        me = s.player()
        surf = src["CarIdxTrackSurface"] or []
        L = s.track_len_m
        found = []
        for idx, c in s.cars.items():
            if idx == me.idx or c.on_pit or c.last_pct is None:
                continue
            if idx < len(surf) and surf[idx] != ON_TRACK:
                continue
            behind_m = ((me.last_pct - c.last_pct) % 1.0) * L
            if behind_m > 450 or behind_m < 2:
                continue
            v = self._car_v.get(idx, (0, 0, 0))[2]
            if v < 8:
                continue
            found.append((behind_m / v, c.name))
        return sorted(found)

    def _finish(self):
        s, inc = self.s, self.active
        me = s.player()
        self.active = None
        out = []
        parts = ["Weer onderweg."]
        lost_pos = 0
        if s.is_race():
            passed = [c.name for c in s.field() if c.idx in inc.behind_idx and c.position < me.position]
            lost_pos = max(0, me.position - inc.pos0)
            if passed:
                names = " en ".join(passed[:3]) if len(passed) <= 3 else f"{len(passed)} auto's"
                parts.append(f"{len(passed)} {'plek' if len(passed) == 1 else 'plekken'} kwijt aan {names}, je ligt P{me.position}.")
            else:
                parts.append(f"Geen plekken verloren, nog steeds P{me.position}.")
        lost_t = self._time_lost(inc.coach_delta0, self.coach.delta_now())
        if lost_t and lost_t > 0.5:
            parts.append(f"Ongeveer {say_sec(lost_t, 0)} seconde verloren.")
        if inc.points:
            parts.append(f"{inc.points}x, totaal {s.incidents}x.")
        same = [x for x in self.log if x.get("bocht") and x.get("bocht") == inc.corner and x["soort"] in ("spin", "van de baan")]
        if inc.corner and same:
            parts.append(f"Dat is de {'tweede' if len(same) == 1 else 'derde' if len(same) == 2 else 'zoveelste'} keer in bocht {inc.corner}. Neem daar wat meer marge.")
        minor = inc.kind == "off" and not inc.announced and lost_pos == 0 and not (lost_t and lost_t > 1.5)
        if not minor:
            out.append((1, " ".join(parts)))
        if minor:
            self.just_finished = True
            return out
        self.log.append({"ronde": inc.lap, "bocht": inc.corner, "soort": "spin" if inc.kind == "spin" else "van de baan",
                         "punten": inc.points, "tijd_verloren_s": round(lost_t, 1) if lost_t else None,
                         "plekken_verloren": lost_pos})
        out += self._limit_check()
        self.just_finished = True
        return out

    def _time_lost(self, d0, d1):
        """d0/d1 = (rondenummer, achterstand op referentie). Werkt ook over de finishlijn heen."""
        if not d0 or not d1:
            return None
        (l0, x0), (l1, x1) = d0, d1
        if l0 == l1:
            return x1 - x0
        me = self.s.player()
        if l1 == l0 + 1 and self.coach.ref_time and me and me.lap_times:
            return (me.lap_times[-1][1] - self.coach.ref_time - x0) + x1
        return None

    def _limit_check(self):
        s = self.s
        if not self.limit or not self.cfg.get("limit_warnings", True):
            return []
        left = self.limit - s.incidents
        for th in (2, 5):
            if left <= th and th not in self.limit_warned:
                self.limit_warned.update(t for t in (2, 5) if t >= th)
                return [(1, f"Let op: {s.incidents}x, de limiet is {self.limit}. Nog {left} over, rij voorzichtig.")]
        return []

    def summary(self):
        return {"incidenten": self.log, "limiet": self.limit, "totaal": self.s.incidents}
