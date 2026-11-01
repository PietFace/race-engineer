"""Balans van de auto per bocht: onderstuur / overstuur, bij het insturen en bij het uitkomen.

Methode: 'stuurhoek per bochtkromming' = |stuurhoek| x snelheid / |yaw rate|.
Voor een neutrale auto is dat ongeveer constant (stuurverhouding x wielbasis).
Moet je voor dezelfde bocht meer sturen dan normaal -> onderstuur.
Draait de auto meer dan je stuurt, of stuur je tegen -> overstuur.
De auto wordt met zichzelf vergeleken (mediaan over de hele ronde), dus het werkt voor elke auto."""
import statistics

from coach import BIN_M

PHASE_NL = {"in": "bij het insturen van", "uit": "bij het uitkomen van"}

ADVICE = {
    ("onderstuur", "in"): "Probeer de rembalans een klik naar achter, of de voorste stabilisator zachter. Rijtechniek: houd bij het insturen nog wat rem vast zodat de voorwielen grip houden, en stuur rustig in.",
    ("onderstuur", "uit"): "Probeer de voorste stabilisator zachter of de achterste stijver. Rijtechniek: wacht met vol gas tot je stuur bijna recht staat.",
    ("overstuur", "in"): "Probeer de rembalans een klik naar voren, of minder motorrem. Rijtechniek: rem rechter uit en laat de rem geleidelijker los.",
    ("overstuur", "uit"): "Probeer de tractiecontrole een stap hoger, of de achterste stabilisator zachter. Rijtechniek: rustiger op het gas tot de auto recht staat.",
}


class BalanceAnalyser:
    def __init__(self, cfg, state, coach):
        self.cfg = cfg.get("balance", {}) or {}
        self.s = state
        self.coach = coach
        self.samples = []          # (bin, steer_per_curv, countersteer) van de huidige ronde
        self.cur_lap = None
        self.done_samples, self.done_lap = [], None
        self.history = {}          # (bocht, fase) -> [label per ronde]
        self.reported = {}         # (bocht, fase, label) -> ronde waarin gemeld
        self.baselines = []
        self.latest = {}           # (bocht, fase) -> {label, ratio, tegensturen}
        self.clean_laps_since_reset = 0
        self.setup = None          # SetupWatcher (voor concrete waarden)

    def update(self, src):
        me = self.s.player()
        if not me or me.wraps is None or not self.cfg.get("enabled", True):
            return
        if self.cur_lap != me.wraps:
            self.done_samples, self.done_lap = self.samples, self.cur_lap   # voor lap_completed
            self.samples = []
            self.cur_lap = me.wraps
        steer, yaw, lat, v = src["SteeringWheelAngle"], src["YawRate"], src["LatAccel"], src["Speed"]
        dist = src["LapDist"]
        if None in (steer, yaw, lat, v, dist) or v < 12 or abs(lat) < 4 or abs(yaw) < 0.05:
            return
        counter = (steer * yaw < 0) and abs(steer) > 0.03 and abs(yaw) > 0.15
        spc = abs(steer) * v / abs(yaw)
        self.samples.append((int(dist / BIN_M), spc, counter, abs(lat)))

    def lap_completed(self, clean):
        """Na een ronde: per bocht en fase het label bepalen. Geeft berichten terug."""
        samples, self.done_samples = self.done_samples, []
        if not clean or not self.coach.corners or len(samples) < 40:
            return []
        mod = [x[1] for x in samples if 4 <= x[3] <= 10 and not x[2]]
        if len(mod) < 20:
            return []
        self.baselines = (self.baselines + [statistics.median(mod)])[-4:]
        self.clean_laps_since_reset += 1
        base = statistics.median(self.baselines)
        lap_nr = (self.done_lap or 0) + 1
        found = {}
        for c in self.coach.corners:
            for phase, (a, b) in (("in", (c.brake_bin, c.apex_bin)), ("uit", (c.apex_bin, c.exit_bin))):
                pts = [x for x in samples if a <= x[0] <= b]
                if len(pts) < 6:
                    continue
                cs = sum(1 for x in pts if x[2]) / len(pts)
                ratio = statistics.median(x[1] for x in pts if not x[2]) / base if any(not x[2] for x in pts) else 0
                label = "neutraal"
                if cs > 0.2 or (ratio and ratio < 0.75):
                    label = "overstuur"
                elif ratio > float(self.cfg.get("understeer_ratio", 1.25)):
                    label = "onderstuur"
                key = (c.nr, phase)
                self.latest[key] = {"label": label, "ratio": round(ratio, 2), "tegensturen": round(cs, 2)}
                h = self.history.setdefault(key, [])
                h.append(label)
                del h[:-3]
                if label != "neutraal" and h.count(label) >= 2:
                    found[key] = label
        out = []
        if not self.cfg.get("speak", True):
            return out
        mode = self.coach.mode()
        for (nr, phase), label in sorted(found.items(), key=lambda kv: kv[0]):
            last = self.reported.get((nr, phase, label))
            if last is not None and lap_nr - last < 10:
                continue
            if mode == "race" and self.s.is_race():
                continue  # in de race niet afleiden; staat wel in de nabespreking/analyse
            self.reported[(nr, phase, label)] = lap_nr
            txt = f"Balans: {label} {PHASE_NL[phase]} bocht {nr}."
            if self.cfg.get("advice", True):
                txt += " " + self.advice_text(label, phase)
            out.append((4, txt))
            break  # max één balansmelding per ronde
        return out

    def advice_text(self, label, phase):
        generic = ADVICE[(label, phase)]
        tips = self.setup.concrete(label, phase) if self.setup else []
        if not tips:
            return generic
        technique = generic.split("Rijtechniek:")[-1].strip() if "Rijtechniek:" in generic else ""
        txt = "Probeer: " + ", of ".join(tips) + "."
        if technique:
            txt += " Rijtechniek: " + technique
        return txt

    def issue_map(self):
        """Huidige duidelijke problemen: {(bocht, fase): label}"""
        out = {}
        for key, h in self.history.items():
            for label in ("onderstuur", "overstuur"):
                if h.count(label) >= 2:
                    out[key] = label
        return out

    def reset_history(self):
        self.history = {}
        self.reported = {}
        self.latest = {}
        self.baselines = []
        self.clean_laps_since_reset = 0

    def summary(self):
        issues = []
        for (nr, phase), h in sorted(self.history.items()):
            for label in ("onderstuur", "overstuur"):
                if h.count(label) >= 2:
                    issues.append({"bocht": nr, "fase": "insturen" if phase == "in" else "uitkomen",
                                   "balans": label, "tip": self.advice_text(label, phase)})
        return {"balans_problemen": issues}
