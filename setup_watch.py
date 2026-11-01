"""Leest je auto-setup uit iRacing (sessie-info 'CarSetup'), meldt wijzigingen,
en koppelt terug of een wijziging het onder-/overstuur heeft verbeterd."""
import re

# Woorden in iRacing-setupnamen -> Nederlands. Volgorde telt (eerste match wint).
NAMES = [
    (r"brakepressurebias|brakebias", "rembalans"),
    (r"tractioncontrol|tcsetting|^tc", "tractiecontrole"),
    (r"abssetting|^abs", "ABS"),
    (r"arb|antiroll", "stabilisator"),
    (r"diffpreload|preload", "differentieel-voorspanning"),
    (r"diffcoast|coast", "differentieel bij gas los"),
    (r"diffpower|ramp", "differentieel bij gas"),
    (r"wing|flap", "vleugel"),
    (r"springrate|spring", "veer"),
    (r"bumpstiff|lsbump|hsbump|compression", "demper (in)"),
    (r"reboundstiff|lsrebound|hsrebound|rebound", "demper (uit)"),
    (r"camber", "camber"),
    (r"toein|toe", "toe"),
    (r"pushrod|rideheight|perchoffset|spacer", "rijhoogte"),
    (r"coldpressure|startingpressure", "bandenspanning"),
    (r"enginebrak|engbrake", "motorrem"),
    (r"fuellevel|fuel", "brandstof"),
    (r"brakepads|pad", "remblokken"),
    (r"throttleshape|throttlemap", "gaskaart"),
]
SIDE = [(r"leftfront|^lf", "linksvoor"), (r"rightfront|^rf", "rechtsvoor"), (r"leftrear|^lr", "linksachter"),
        (r"rightrear|^rr", "rechtsachter"), (r"front", "voor"), (r"rear", "achter")]
# metingen en dingen die je niet instelt -> niet als "wijziging" melden
SKIP = re.compile(r"last|tread|temp|cornerweight|wear|updatecount|measured|calc|rideheight$|shockdefl|springdefl|"
                  r"torsionbardefl|fuellevel|^dash|display|nightled|pitlight", re.I)


def _flatten(d, path=()):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, path + (str(k),)))
    elif isinstance(d, list):
        pass
    else:
        out[path] = str(d).strip()
    return out


def nice(path):
    """('Chassis','Front','ArbBlades') -> 'stabilisator voor'"""
    key = path[-1].lower()
    full = " ".join(p.lower() for p in path)
    name = next((nl for pat, nl in NAMES if re.search(pat, key)), None)
    if name is None:
        name = re.sub(r"([a-z])([A-Z])", r"\1 \2", path[-1]).lower()
    if name in ("rembalans", "tractiecontrole", "ABS", "brandstof", "motorrem", "gaskaart") or name.startswith("differentieel"):
        return name
    side = next((nl for pat, nl in SIDE if any(re.search(pat, p.lower()) for p in path[:-1]) or re.search(pat, key)), "")
    if side and side not in name:
        name = f"{name} {side}"
    if "brandstof" in name or "rembalans" in name or "tractiecontrole" in name or "ABS" in name:
        return name
    return name


def num(v):
    m = re.search(r"-?\d+(?:[.,]\d+)?", v or "")
    return float(m.group(0).replace(",", ".")) if m else None


def say_val(v):
    v = re.sub(r"\s*\([^)]*\)", "", v or "").strip()
    return v.replace("%", " procent").replace(".", ",").replace("  ", " ")


class SetupWatcher:
    def __init__(self, cfg, state, balance):
        self.cfg = cfg.get("setup", {}) or {}
        self.s = state
        self.bal = balance
        self.current = {}          # pad -> waarde (alleen instelbare dingen)
        self.raw = {}
        self._upd = None
        self.changes = []          # [{ronde, wijzigingen, balans_voor, balans_na?}]
        self.pending_eval = None   # wacht op schone ronden na een wijziging
        self.announced_first = False

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    def _read(self, src):
        cs = src["CarSetup"]
        if not isinstance(cs, dict):
            return None
        flat = _flatten(cs)
        self.raw = flat
        return {p: v for p, v in flat.items() if not any(SKIP.search(x) for x in p)}

    def update(self, src, events):
        out = []
        if not self.enabled:
            return out
        if src.session_info_update != self._upd:
            self._upd = src.session_info_update
            new = self._read(src)
            if new:
                if not self.current:
                    self.current = new
                else:
                    diff = [(p, self.current.get(p), v) for p, v in new.items() if self.current.get(p) not in (None, v)]
                    self.current = new
                    if diff:
                        out += self._on_change(diff)
        for ev in events:
            if ev[0] == "player_lap" and self.pending_eval:
                out += self._evaluate()
        return out

    def _on_change(self, diff):
        me = self.s.player()
        lap = (me.wraps or 0) + 1 if me else 0
        before = {k: v for k, v in self.bal.issue_map().items()}
        self.changes.append({"ronde": lap, "wijzigingen": [{"wat": nice(p), "van": a, "naar": b} for p, a, b in diff],
                             "balans_voor": {f"bocht {k[0]} {k[1]}": v for k, v in before.items()}})
        self.bal.reset_history()
        self.pending_eval = {"laps": 0, "before": before}
        if not self.cfg.get("announce", True):
            return []
        bits = [f"{nice(p)} van {say_val(a)} naar {say_val(b)}" for p, a, b in diff[:3]]
        more = f", en nog {len(diff) - 3} andere" if len(diff) > 3 else ""
        return [(4, "Setup aangepast: " + ", ".join(bits) + more + ". Rij een paar schone ronden, dan vertel ik of het helpt.")]

    def _evaluate(self):
        pe = self.pending_eval
        pe["laps"] = self.bal.clean_laps_since_reset
        if pe["laps"] < int(self.cfg.get("eval_laps", 3)):
            return []
        self.pending_eval = None
        now = self.bal.issue_map()
        before = pe["before"]
        gone = [k for k in before if k not in now]
        still = [k for k in before if k in now]
        new = [k for k in now if k not in before]
        fmt = lambda k, lab: f"{lab} {'bij het insturen van' if k[1] == 'in' else 'bij het uitkomen van'} bocht {k[0]}"
        parts = []
        if gone:
            parts.append("Weg: " + ", ".join(fmt(k, before[k]) for k in gone[:2]) + ".")
        if still:
            parts.append("Nog steeds: " + ", ".join(fmt(k, now[k]) for k in still[:2]) + ".")
        if new:
            parts.append("Nieuw: " + ", ".join(fmt(k, now[k]) for k in new[:2]) + ".")
        if self.changes:
            self.changes[-1]["balans_na"] = {f"bocht {k[0]} {k[1]}": v for k, v in now.items()}
        if not parts:
            return [(4, "Na je setup-wijziging is de auto overal neutraal. Goede wijziging.")]
        verdict = " Goede wijziging." if gone and not new else (" Die wijziging maakte het niet beter." if new and not gone else "")
        return [(4, "Effect van je setup-wijziging. " + " ".join(parts) + verdict)]

    # ------------------------------------------------------------
    #  Concreet advies met jouw waarden
    # ------------------------------------------------------------
    def find(self, *patterns, side=None):
        for p, v in self.current.items():
            key = p[-1].lower()
            full = " ".join(x.lower() for x in p)
            if any(re.search(pt, key) for pt in patterns):
                if side and not re.search(side, full):
                    continue
                return p, v
        return None, None

    def concrete(self, label, phase):
        """Eén of twee concrete stappen met de huidige waarde erbij."""
        tips = []

        def add(patterns, side, text):
            p, v = self.find(*patterns, side=side)
            if p is not None:
                tips.append(f"{text} (staat nu op {say_val(v)})")

        if label == "onderstuur" and phase == "in":
            p, v = self.find(r"brakepressurebias|brakebias")
            n = num(v)
            if n is not None:
                tips.append(f"rembalans naar {say_val(f'{n - 0.5:.1f}%')} (nu {say_val(v)})")
            add([r"arb|antiroll"], r"front", "voorste stabilisator een stap zachter")
        elif label == "onderstuur" and phase == "uit":
            add([r"arb|antiroll"], r"front", "voorste stabilisator een stap zachter")
            add([r"arb|antiroll"], r"rear", "of de achterste een stap stijver")
        elif label == "overstuur" and phase == "in":
            p, v = self.find(r"brakepressurebias|brakebias")
            n = num(v)
            if n is not None:
                tips.append(f"rembalans naar {say_val(f'{n + 0.5:.1f}%')} (nu {say_val(v)})")
            add([r"enginebrak|engbrake"], None, "minder motorrem")
            add([r"diffcoast|coast"], None, "of minder differentieel bij gas los")
        elif label == "overstuur" and phase == "uit":
            add([r"tractioncontrol|tcsetting|^tc"], None, "tractiecontrole een stap meer ingrijpen")
            add([r"arb|antiroll"], r"rear", "achterste stabilisator een stap zachter")
        return tips[:2]

    def key_values(self):
        """Korte lijst van de belangrijkste waarden (voor scherm en AI)."""
        out = []
        for pats, side, label in (([r"brakepressurebias|brakebias"], None, "rembalans"),
                                  ([r"arb|antiroll"], r"front", "ARB voor"),
                                  ([r"arb|antiroll"], r"rear", "ARB achter"),
                                  ([r"tractioncontrol|tcsetting|^tc"], None, "TC"),
                                  ([r"abssetting|^abs"], None, "ABS"),
                                  ([r"wing|flap"], None, "vleugel")):
            p, v = self.find(*pats, side=side)
            if p is not None:
                out.append((label, v))
        return out

    def summary(self):
        if not self.current:
            return {"setup": "niet beschikbaar"}
        lines = {" > ".join(p): v for p, v in list(self.current.items())[:90]}
        return {"belangrijkste": dict(self.key_values()), "alle_instellingen": lines,
                "wijzigingen_deze_sessie": self.changes[-5:]}
