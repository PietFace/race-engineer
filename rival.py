"""Vergelijkt jou met de auto voor of achter je, per stuk baan.

Elke auto wordt op 100 punten per ronde getimed (race_state). Daarmee weten we per bocht
hoe lang iedereen erover doet, ook zonder telemetrie van de tegenstander."""
from coach import BIN_M
from race_state import N_CP, say_sec


class RivalAnalyser:
    def __init__(self, cfg, state, coach):
        self.cfg = cfg.get("rival", {}) or {}
        self.s = state
        self.coach = coach
        self.last_said = {}        # car idx -> ronde waarop gemeld
        self.latest = {}           # car idx -> resultaat (voor scherm en AI)

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    # ------------------------------------------------------------
    def zones(self):
        """[(van_cp, tot_cp, label, bocht_nr)] — één zone per bocht: het stuk ervoor + de bocht zelf."""
        corners = self.coach.corners if self.coach and self.coach.corners else []
        L = self.s.track_len_m or 4000
        if not corners:
            return [(0, 33, "sector 1", None), (33, 66, "sector 2", None), (66, N_CP, "sector 3", None)]
        out, start = [], 0
        for c in corners:
            end = min(N_CP, max(start + 1, int(round(c.exit_bin * BIN_M / L * N_CP))))
            if end <= start:
                continue
            out.append((start, end, f"bocht {c.nr}", c.nr))
            start = end
        if start < N_CP:
            out.append((start, N_CP, "het laatste rechte stuk", None))
        return out

    def _zone_times(self, car, lap):
        """Tijd per zone voor ronde `lap` (0-based, zoals de meetpunten)."""
        base = lap * N_CP
        res = []
        for a, b, _, _ in self.zones():
            t0, t1 = car.time_at(base + a), car.time_at(base + b)
            if t0 is None or t1 is None or t1 <= t0:
                return None
            res.append(t1 - t0)
        return res

    def _clean_laps(self, car, n=3):
        laps = [w - 1 for w, _, ok in car.lap_times if ok][-n:]
        out = []
        for L in laps:
            zt = self._zone_times(car, L)
            if zt:
                out.append(zt)
        return out

    def compare(self, other):
        me = self.s.player()
        if not me or not other:
            return None
        mine, theirs = self._clean_laps(me), self._clean_laps(other)
        if not mine or not theirs:
            return None
        zs = self.zones()
        n = len(zs)
        avg = lambda rows, i: sum(r[i] for r in rows) / len(rows)
        deltas = [avg(mine, i) - avg(theirs, i) for i in range(n)]   # + = hij is daar sneller
        res = {"naam": other.name, "zones": [{"stuk": zs[i][2], "bocht": zs[i][3], "verschil_s": round(deltas[i], 3)}
                                              for i in range(n)],
               "totaal_s": round(sum(deltas), 3), "ronden_vergeleken": (len(mine), len(theirs))}
        self.latest[other.idx] = res
        return res

    # ------------------------------------------------------------
    @staticmethod
    def _names(items):
        if len(items) > 1 and all(z["bocht"] for z in items):
            nrs = sorted(z["bocht"] for z in items)
            return "bocht " + ", ".join(str(n) for n in nrs[:-1]) + f" en {nrs[-1]}"
        names = [z["stuk"] for z in items]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " en " + names[-1]

    def _next_corner(self, nr):
        corners = self.coach.corners if self.coach else []
        if not corners or nr is None:
            return None
        nrs = [c.nr for c in corners]
        i = nrs.index(nr) if nr in nrs else -1
        return nrs[(i + 1) % len(nrs)] if i >= 0 else None

    def advice(self, res, ahead):
        thr = float(self.cfg.get("min_zone_delta", 0.06))
        zones = res["zones"]
        he = sorted([z for z in zones if z["verschil_s"] > thr], key=lambda z: -z["verschil_s"])[:2]
        me = sorted([z for z in zones if z["verschil_s"] < -thr], key=lambda z: z["verschil_s"])[:2]
        if not he and not me:
            return f"{res['naam']} en jij zijn overal even snel."
        parts = []
        if he:
            parts.append(f"{res['naam']} is sneller in {self._names(he)}, {say_sec(sum(z['verschil_s'] for z in he), 2)} per ronde")
        if me:
            parts.append(f"jij bent sneller in {self._names(me)}")
        txt = ". ".join(p[0].upper() + p[1:] for p in parts) + "."
        if ahead and me:
            best = me[0]
            nxt = self._next_corner(best["bocht"])
            if best["bocht"] and nxt:
                txt += f" Je beste kans: blijf dicht achter hem uit bocht {best['bocht']} en val aan in bocht {nxt}."
            else:
                txt += f" Je beste kans ligt in {best['stuk']}."
        elif not ahead and he:
            worst = he[0]
            if worst["bocht"]:
                txt += f" Verdedig de binnenkant in bocht {worst['bocht']}."
            else:
                txt += f" Pas op in {worst['stuk']}."
        return txt

    def on_lap(self, lap_nr):
        """Na elke ronde: tegenstander dichtbij? Dan af en toe vertellen waar het verschil zit."""
        if not self.enabled or not self.s.is_race():
            return []
        ahead, behind = self.s.neighbours()
        every = int(self.cfg.get("every_laps", 3))
        out = []
        for car, is_ahead, limit in ((ahead, True, 2.5), (behind, False, 2.0)):
            if car is None or car.on_pit:
                continue
            g = self.s.gap_to(car)
            if g is None or abs(g) > limit:
                continue
            last = self.last_said.get(car.idx)
            if last is not None and lap_nr - last < every:
                continue
            res = self.compare(car)
            if not res:
                continue
            self.last_said[car.idx] = lap_nr
            out.append((2, self.advice(res, is_ahead)))
            break   # één tegelijk, de auto voor gaat voor
        return out

    def summary_now(self):
        ahead, behind = self.s.neighbours()
        out = {}
        for key, car in (("voor", ahead), ("achter", behind)):
            if car:
                r = self.compare(car)
                if r:
                    out[key] = r
        return out

    def short(self, car):
        """Kort label voor het scherm: 'sneller in B5–B6'."""
        r = self.latest.get(car.idx) if car else None
        if not r:
            return None
        he = [z for z in r["zones"] if z["verschil_s"] > 0.06 and z["bocht"]]
        me = [z for z in r["zones"] if z["verschil_s"] < -0.06 and z["bocht"]]
        bits = []
        if he:
            bits.append("hij sneller in " + ", ".join(f"B{z['bocht']}" for z in sorted(he, key=lambda z: -z["verschil_s"])[:2]))
        if me:
            bits.append("jij in " + ", ".join(f"B{z['bocht']}" for z in sorted(me, key=lambda z: z["verschil_s"])[:2]))
        return " · ".join(bits) or None
