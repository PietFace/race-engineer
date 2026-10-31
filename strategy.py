"""Brandstof- en pitstrategie."""
import math


class Strategy:
    def __init__(self, state, cfg):
        self.s = state
        self.cfg = cfg

    def fuel_per_lap(self):
        clean = [u for _, u, ok in self.s.fuel_laps if ok][-5:]
        if not clean:
            allu = [u for _, u, _ in self.s.fuel_laps][-3:]
            return max(allu) if allu else None
        # iets voorzichtig: gemiddelde + kwart van de spreiding
        avg = sum(clean) / len(clean)
        return avg + 0.25 * (max(clean) - min(clean))

    def my_laps_remaining(self):
        """Hoeveel ronden moet ik zelf nog rijden (inclusief de huidige, gedeeltelijk)."""
        s, me = self.s, self.s.player()
        if not me:
            return None
        leader = s.overall_leader() or me   # de algemene leider bepaalt wanneer de vlag valt
        frac_left = 1.0 - (me.last_pct or 0)
        if s.total_laps:
            # leider bepaalt wanneer de vlag valt
            leader_left = max(0.0, s.total_laps - leader.progress)
            # als de leider finisht sta jij ongeveer op me.progress + leader_left; daarna maak je je ronde af
            my_end = math.ceil(me.progress + leader_left - 1e-6)
            return max(0.0, my_end - me.progress)
        if s.time_remaining:
            lap = me.avg_lap(3) or me.last_lap
            if lap:
                # tijdrace: na afloop tijd nog de ronde afmaken
                return frac_left + math.ceil((s.time_remaining - frac_left * lap) / lap) + 0.0
        if s.laps_remaining is not None:
            return s.laps_remaining + frac_left
        return None

    def plan(self):
        """Volledige brandstof/pit-situatie als dict."""
        s, me = self.s, self.s.player()
        fpl = self.fuel_per_lap()
        left = self.my_laps_remaining()
        out = {"verbruik_per_ronde": None, "ronden_in_tank": None, "ronden_te_gaan": None,
               "brandstof": round(s.fuel, 1) if s.fuel is not None else None}
        if fpl is None or s.fuel is None:
            return out
        margin = self.cfg["engineer"]["fuel_margin_laps"]
        tank = s.fuel_max or 100.0
        laps_in_tank = s.fuel / fpl
        out.update(verbruik_per_ronde=round(fpl, 2), ronden_in_tank=round(laps_in_tank, 1))
        if left is None:
            return out
        out["ronden_te_gaan"] = round(left, 1)
        need = (left + margin) * fpl
        short = need - s.fuel
        out["tekort_liter"] = round(short, 1)
        if short <= 0:
            out["stops_nodig"] = 0
            out["overschot_liter"] = round(-short, 1)
            return out
        stops = math.ceil(short / max(1.0, tank - fpl * 0.5))
        out["stops_nodig"] = stops
        cur_lap = (me.wraps or 0) + 1
        # pitvenster (1 stop): openen zodra de rest van de race in een volle tank past
        laps_full_tank = tank / fpl - margin
        open_lap = cur_lap + max(0, math.ceil(left - laps_full_tank))
        close_lap = cur_lap + max(0, int(math.floor(laps_in_tank - margin)) - 1)
        out["pitvenster_open_ronde"] = open_lap
        out["pitvenster_sluit_ronde"] = close_lap
        out["bijtanken_als_je_nu_stopt"] = round(min(tank, need) - s.fuel + fpl, 1)
        # zuinig rijden i.p.v. stoppen?
        target = s.fuel / (left + margin * 0.5)
        save_pct = (1 - target / fpl) * 100
        out["doel_verbruik_zonder_stop"] = round(target, 2)
        out["besparing_nodig_pct"] = round(save_pct, 1)
        return out

    def pit_rejoin(self, fuel_to_add=None):
        """Waar kom je terug als je deze ronde stopt?"""
        s, me = self.s, self.s.player()
        if not me:
            return None
        fill = self.cfg["engineer"]["fuel_fill_rate"]
        loss = s.pit_loss
        if fuel_to_add:
            # pit_loss is gemeten/ingesteld incl. een gemiddelde tankbeurt; corrigeer grof
            loss = s.pit_loss - 25 / fill + fuel_to_add / fill if fuel_to_add < 60 else s.pit_loss
        behind = []
        for c in s.field():
            if c.idx == me.idx:
                continue
            g = s.gap_to(c)
            if g is None or g > 0:
                continue
            behind.append((c, -g))
        passed = [(c, g) for c, g in behind if g < loss]
        new_pos = me.position + len(passed)
        res = {"tijdverlies_s": round(loss, 1), "nieuwe_positie": new_pos, "verliest_aan": [c.name for c, _ in passed]}
        if passed:
            last_c, last_g = passed[-1]
            res["terug_achter"] = last_c.name
            res["achterstand_s"] = round(loss - last_g, 1)
        nxt = [(c, g) for c, g in behind if g >= loss]
        if nxt:
            res["terug_voor"] = nxt[0][0].name
            res["voorsprong_s"] = round(nxt[0][1] - loss, 1)
        return res
