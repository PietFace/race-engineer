"""Lesplan: oefen één ding tegelijk, met een korte aanwijzing vóór de bocht en steeds minder
feedback naarmate het lukt. Geslaagd = 3 van de laatste 4 doorgangen goed. Voortgang wordt
per auto en baan bewaard, en na de sessie komt er een nabespreking met huiswerk."""
import datetime
import json
import os

from coach import BIN_M
from reference import slug


class LessonPlan:
    def __init__(self, cfg, state, coach, technique, data_dir):
        self.cfg = cfg.get("lesson", {}) or {}
        self.s = state
        self.coach = coach
        self.tech = technique
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.focus = None          # bevinding (dict) waar we nu aan werken
        self.results = []          # True/False per doorgang van de focusbocht
        self.laps_on_focus = 0
        self.done = []             # geslaagde lessen deze sessie
        self.skipped = set()
        self.reminded_lap = None
        self.pause_until_lap = -1  # na een spin even rust
        self.progress = None
        self._key = None
        self._added = None   # wat deze sessie al in de voortgang heeft gezet (wordt vervangen, niet verdubbeld)

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    def active(self):
        return self.enabled and self.coach.mode() == "practice" and self.focus is not None

    # ------------------------------------------------------------
    def _path(self):
        return os.path.join(self.dir, f"{slug(self.s.track_name)}__{slug(self.s.car_name)}.json")

    def _load(self):
        key = (self.s.track_name, self.s.car_name)
        if key == self._key:
            return
        self._key = key
        try:
            with open(self._path(), encoding="utf-8") as f:
                self.progress = json.load(f)
        except Exception:
            self.progress = {"lessen_geslaagd": [], "sessies": [], "huiswerk": []}

    def save(self):
        if not self.progress:
            return
        try:
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump(self.progress, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ------------------------------------------------------------
    def calm_down(self):
        """Na een spin of grote fout: even geen techniektips."""
        me = self.s.player()
        self.pause_until_lap = (me.wraps or 0) + 2 if me else -1

    def _paused(self):
        me = self.s.player()
        return me is not None and (me.wraps or 0) < self.pause_until_lap

    def _choose(self):
        cands = [f for f in self.tech.diagnose(getattr(self.coach, "_balance", None))
                 if f.get("bocht") and f.get("doel") and (f["bocht"], f["code"]) not in self.skipped
                 and (f["bocht"], f["code"]) not in {(d["bocht"], d["code"]) for d in self.done}]
        if not cands:
            return None
        hw = [(h.get("bocht"), h.get("code")) for h in (self.progress or {}).get("huiswerk", [])[-3:]]
        # huiswerk van vorige keer krijgt voorrang
        for f in cands:
            if (f["bocht"], f["code"]) in hw:
                return f
        return cands[0]

    def update(self, dist, speed):
        """Elke tick: korte herinnering vlak vóór de focusbocht."""
        if not self.active() or self._paused():
            return []
        me = self.s.player()
        if self.reminded_lap == me.wraps:
            return []
        c = next((c for c in self.coach.corners if c.nr == self.focus["bocht"]), None)
        if not c:
            return []
        # afbouwen: na 2 goede op rij alleen nog om de ronde herinneren
        streak = 0
        for r in reversed(self.results):
            if not r:
                break
            streak += 1
        if streak >= 2 and (me.wraps or 0) % 2 == 1:
            return []
        lead = max(120.0, speed * 3.2)
        to_go = (c.brake_bin * BIN_M - dist) % ((self.coach.nbins or 1) * BIN_M)
        if lead - 50 <= to_go <= lead:
            self.reminded_lap = me.wraps
            return [(2, self.focus["cue"])]
        return []

    def on_lap(self, lap_metrics, clean):
        """Na een ronde: focus beoordelen, feedback geven, volgende les kiezen."""
        out = []
        if not self.enabled or self.coach.mode() != "practice":
            return out
        self._load()
        if self._paused():
            return out
        if self.focus is None:
            n_clean = max((len(h) for h in self.tech.history.values()), default=0)
            if n_clean >= int(self.cfg.get("start_after_laps", 3)):
                f = self._choose()
                if f:
                    self.focus, self.results, self.laps_on_focus = f, [], 0
                    out.append((2, "Lesplan. We werken nu aan één ding: " + f["uitleg"] +
                                " Ik herinner je eraan vlak voor de bocht."))
            return out
        if not clean:
            return out
        m = lap_metrics.get(self.focus["bocht"])
        ok = self.tech.evaluate(m, self.focus["doel"])
        if ok is None:
            return out
        self.results.append(ok)
        self.laps_on_focus += 1
        last4 = self.results[-4:]
        if sum(last4) >= 3 and len(last4) >= 3:
            self.done.append(self.focus)
            self.progress.setdefault("lessen_geslaagd", []).append(
                {"datum": datetime.date.today().isoformat(), "bocht": self.focus["bocht"], "code": self.focus["code"]})
            self.save()
            out.append((2, f"Bocht {self.focus['bocht']} zit erin! Dat doe je nu goed."))
            self.focus = None
            nxt = self._choose()
            if nxt:
                self.focus, self.results, self.laps_on_focus = nxt, [], 0
                out.append((2, "Volgende oefening: " + nxt["uitleg"]))
            return out
        if self.laps_on_focus >= int(self.cfg.get("max_laps", 10)):
            self.skipped.add((self.focus["bocht"], self.focus["code"]))
            out.append((2, f"We laten bocht {self.focus['bocht']} even rusten en komen er later op terug."))
            self.focus = None
            return out
        # feedback: bij een goede doorgang kort prijzen (in het begin), bij een fout de cue
        if ok:
            if len(self.results) <= 3 or self.results[-2:] == [False, True]:
                out.append((3, f"Goed, bocht {self.focus['bocht']} precies zo."))
        else:
            out.append((3, f"Bocht {self.focus['bocht']}: nog niet. " + self.focus["cue"].split(": ", 1)[-1]))
        return out

    # ------------------------------------------------------------
    def session_debrief_rules(self):
        """Nabespreking zonder AI: wat ging goed, wat is het huiswerk."""
        self._load()
        f = self.tech.diagnose(getattr(self.coach, "_balance", None))
        if self._added:
            for key, items in self._added.items():
                lst = self.progress.get(key, [])
                for it in items:
                    if any(x is it for x in lst):
                        lst.remove(it)
        self._added = {"huiswerk": [], "sessies": []}
        lines = []
        if self.done:
            lines.append("Geslaagd vandaag: " + ", ".join(f"bocht {d['bocht']} ({d['code'].replace('_', ' ')})" for d in self.done) + ".")
        for nr, txt in list(self.tech.self_compare.items())[:2]:
            lines.append(txt)
        cons = self.tech.consistency()
        if cons and cons[0][1] > 0.25:
            lines.append(f"Minst constant: bocht {cons[0][0]} (verschil {cons[0][1]:.2f} seconde tussen je snelste en langzaamste doorgang).".replace(".", ",", 1))
        hw = [x for x in f if x.get("bocht")][:2]
        if hw:
            lines.append("Huiswerk voor de volgende keer: " + " ".join(x["uitleg"] for x in hw))
            new_hw = [{"datum": datetime.date.today().isoformat(), "bocht": x["bocht"], "code": x["code"]} for x in hw]
            self.progress.setdefault("huiswerk", []).extend(new_hw)
            self._added["huiswerk"] = new_hw
        sess = {"datum": datetime.date.today().isoformat(), "bevindingen": [x["code"] for x in f[:6]],
                "geslaagd": [d["code"] for d in self.done]}
        self.progress.setdefault("sessies", []).append(sess)
        self._added["sessies"] = [sess]
        self.progress["sessies"] = self.progress["sessies"][-30:]
        self.save()
        return " ".join(lines) if lines else "Nog te weinig schone ronden voor een nabespreking."

    def summary(self):
        return {"focus": ({"bocht": self.focus["bocht"], "oefening": self.focus["code"],
                           "goed": sum(self.results), "pogingen": len(self.results)} if self.focus else None),
                "geslaagd_vandaag": [{"bocht": d["bocht"], "oefening": d["code"]} for d in self.done],
                "eerdere_sessies": (self.progress or {}).get("sessies", [])[-5:],
                "huiswerk_vorige_keer": (self.progress or {}).get("huiswerk", [])[-3:]}
