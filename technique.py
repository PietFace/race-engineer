"""Rijtechniek: meet per bocht hoe je remt, instuurt, de rem loslaat (trail braking), stuurt,
gas geeft en schakelt — uit je eigen pedalen en stuur, zonder voorbeeld nodig.

Daarna:
- diagnose: wat gaat er niet goed (regels op basis van algemene rijtechniek + de balans van de auto)
- zelfvergelijking: wat deed je anders in je snelste doorgangen van een bocht dan in je langzaamste
- constantheid: welke bocht schommelt het meest"""
import math
import statistics

from coach import BIN_M

DEG = 180 / math.pi


class Sample:
    __slots__ = ("d", "t", "brake", "thr", "steer", "gear", "rpm", "v", "yaw", "abs", "ffb")

    def __init__(self, d, t, brake, thr, steer, gear, rpm, v, yaw, abs_, ffb):
        self.d, self.t, self.brake, self.thr, self.steer = d, t, brake, thr, steer
        self.gear, self.rpm, self.v, self.yaw, self.abs, self.ffb = gear, rpm, v, yaw, abs_, ffb


def _f(x, d=0.0):
    return d if x is None else float(x)


class Technique:
    def __init__(self, cfg, state, coach):
        self.cfg = cfg.get("technique", {}) or {}
        self.s = state
        self.coach = coach
        self.samples = []          # lopende ronde
        self.lap_nr = None
        self.history = {}          # bocht -> [metrics per schone ronde]
        self.lap_info = []         # [{ronde, schakelen, ffb_clip}]
        self.shift_rpm = None
        self._upd = None
        self.findings = []         # laatste diagnose
        self.self_compare = {}     # bocht -> tekst

    @property
    def enabled(self):
        return self.cfg.get("enabled", True)

    # ------------------------------------------------------------
    def update(self, src):
        if not self.enabled:
            return
        if src.session_info_update != self._upd:
            self._upd = src.session_info_update
            di = src["DriverInfo"] or {}
            try:
                sr = float(di.get("DriverCarSLShiftRPM") or 0)
                self.shift_rpm = sr if sr > 0 else self.shift_rpm
            except (TypeError, ValueError):
                pass
        me = self.s.player()
        if not me or me.wraps is None:
            return
        if self.lap_nr != me.wraps:
            self.samples = []
            self.lap_nr = me.wraps
        d = src["LapDist"]
        if d is None or d < 0:
            return
        abs_ = src["BrakeABSactive"]
        self.samples.append(Sample(d, self.s.t, _f(src["Brake"]), _f(src["Throttle"]), _f(src["SteeringWheelAngle"]),
                                   src["Gear"] or 0, _f(src["RPM"]), _f(src["Speed"]) * 3.6, _f(src["YawRate"]),
                                   bool(abs_) if abs_ is not None else None, src["SteeringWheelPctTorque"]))

    # ------------------------------------------------------------
    #  Metingen per bocht
    # ------------------------------------------------------------
    def _corner_metrics(self, c, ss):
        start_d = c.brake_bin * BIN_M - 60
        apex_d = c.apex_bin * BIN_M
        end_d = c.exit_bin * BIN_M + 40
        w = [s for s in ss if start_d <= s.d <= end_d]
        if len(w) < 20:
            return None
        m = {}
        braking = [s for s in w if s.brake > 0.05 and s.d <= apex_d + 30]
        steer_abs = [abs(s.steer) for s in w]
        max_steer = max(steer_abs) if steer_abs else 0
        m["stuur_max_graden"] = round(max_steer * DEG, 1)
        m["vmin"] = round(min(s.v for s in w), 1)
        if braking:
            b0 = braking[0]
            peak = max(s.brake for s in braking)
            m["rem_piek"] = round(peak, 2)
            m["rem_start_m"] = round(b0.d, 1)
            t_peak = next((s.t for s in braking if s.brake >= 0.9 * peak), b0.t)
            m["rem_opbouw_s"] = round(t_peak - b0.t, 2)
            ab = [s.abs for s in braking if s.abs is not None]
            m["abs_deel"] = round(sum(ab) / len(ab), 2) if ab else None
            rel = max((s for s in braking), key=lambda s: s.d)
            m["rem_los_m"] = round(rel.d, 1)
            m["rem_los_voor_top_m"] = round(apex_d - rel.d, 1)
            after_peak = [s for s in braking if s.t >= t_peak]
            t80 = next((s.t for s in after_peak if s.brake <= 0.8 * peak), rel.t)
            m["rem_afbouw_s"] = round(max(0.0, rel.t - t80), 2)
        else:
            m["rem_piek"] = 0.0
        # insturen: stuur groter dan 25% van het maximum in deze bocht
        ti = next((s for s in w if max_steer > 0.02 and abs(s.steer) >= 0.25 * max_steer), None)
        if ti:
            m["instuur_m"] = round(ti.d, 1)
            m["rem_bij_instuur"] = round(ti.brake, 2)
            if braking:
                m["trail_m"] = round(m["rem_los_m"] - ti.d, 1)   # hoe ver de rem de bocht in gaat
            first = [s for s in w if ti.t <= s.t <= ti.t + 0.8]
            rates = [abs(b.steer - a.steer) / (b.t - a.t) for a, b in zip(first, first[1:]) if b.t > a.t]
            m["instuur_snelheid_gps"] = round(max(rates) * DEG, 0) if rates else None
        # vol gas en stuur op dat moment
        full = next((s for s in w if s.d > apex_d - 20 and s.thr >= 0.95), None)
        if full:
            m["vol_gas_m"] = round(full.d, 1)
            m["stuur_bij_vol_gas"] = round(abs(full.steer) / max_steer, 2) if max_steer > 0 else None
        # rollen (geen gas, geen rem) tussen rem-start en vol gas, en overlap
        coast = overlap = 0.0
        lo = braking[0].d if braking else start_d
        hi = full.d if full else end_d
        for a, b in zip(w, w[1:]):
            if lo <= a.d <= hi:
                dd = max(0.0, b.d - a.d)
                if a.brake < 0.05 and a.thr < 0.05 and a.v > 15:
                    coast += dd
                if a.brake > 0.1 and a.thr > 0.1:
                    overlap += dd
        m["rollen_m"] = round(coast, 1)
        m["overlap_m"] = round(overlap, 1)
        # pompen met het gas na de top
        pumps, run_max, armed = 0, 0.0, False
        for s in w:
            if s.d < apex_d - 20:
                continue
            if s.thr >= 0.95:
                break
            if s.thr > 0.3:
                armed = True
            if armed and run_max - s.thr > 0.2:
                pumps += 1
                run_max = s.thr
            run_max = max(run_max, s.thr)
        m["gas_pompen"] = pumps
        # stuurcorrecties en tegensturen tussen insturen en vol gas
        corr = 0
        if ti:
            seg = [s for s in w if s.t >= ti.t and (not full or s.t <= full.t)]
            last_sign = 0
            for a, b in zip(seg, seg[1:]):
                if b.t <= a.t:
                    continue
                r = (b.steer - a.steer) / (b.t - a.t)
                if abs(r) < 0.35:
                    continue
                sg = 1 if r > 0 else -1
                if last_sign and sg != last_sign:
                    corr += 1
                last_sign = sg
        m["stuurcorrecties"] = max(0, corr - 1)
        cs = [s for s in w if abs(s.steer) > 0.04 and abs(s.yaw) > 0.2 and s.steer * s.yaw < 0]
        m["tegensturen_s"] = round(len(cs) / 60.0, 2)
        m["bochttype"] = "langzaam" if m["vmin"] < 120 else ("snel" if m["vmin"] > 180 else "middel")
        return m

    def _lap_extras(self, ss):
        ups, clip = [], 0
        ffb = [s.ffb for s in ss if s.ffb is not None]
        if ffb:
            clip = sum(1 for x in ffb if x >= 0.99) / len(ffb)
        for a, b in zip(ss, ss[1:]):
            if b.gear > a.gear > 0 and a.rpm > 0:
                ups.append(a.rpm)
        return {"opschakel_toeren": round(statistics.median(ups)) if ups else None,
                "ffb_clipping": round(clip, 3) if ffb else None}

    def lap_completed(self, lap_nr, lap_time, clean):
        """Na elke ronde: metingen opslaan. Geeft de metingen per bocht van deze ronde terug."""
        if not self.enabled or not self.coach.corners or not self.samples:
            return {}
        ss = self.samples
        self.samples = []
        out = {}
        if not clean or not lap_time or lap_time <= 0:
            return out
        # alleen representatieve ronden: niet de start, niet achter de safety car of in het verkeer
        self.best_time = min(lap_time, getattr(self, "best_time", None) or lap_time)
        if lap_time > self.best_time * 1.04:
            return out
        cur = self.coach.cur if self.coach.cur is not None else None
        for c in self.coach.corners:
            m = self._corner_metrics(c, ss)
            if not m:
                continue
            # bochttijd uit de coach (zelfde meetpunten voor iedere ronde)
            if cur is not None:
                st = max(0, c.brake_bin - int(60 / BIN_M))
                if cur.t[st] is not None and cur.t[c.exit_bin] is not None:
                    m["bochttijd"] = round(cur.t[c.exit_bin] - cur.t[st], 3)
            m["ronde"] = lap_nr
            m["rondetijd"] = lap_time
            out[c.nr] = m
            h = self.history.setdefault(c.nr, [])
            h.append(m)
            # ronden die achteraf veel trager blijken dan je beste ronde tellen niet mee
            h[:] = [r for r in h if r.get("rondetijd", 0) <= self.best_time * 1.04][-12:]
        ex = self._lap_extras(ss)
        ex["ronde"] = lap_nr
        self.lap_info.append(ex)
        del self.lap_info[:-12]
        return out

    # ------------------------------------------------------------
    #  Diagnose
    # ------------------------------------------------------------
    @staticmethod
    def _avg(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def spread(self, nr):
        ts = [r["bochttijd"] for r in self.history.get(nr, []) if r.get("bochttijd")]
        if len(ts) < 3:
            return None
        return max(ts) - min(ts)

    def diagnose(self, balance=None):
        """Lijst van bevindingen, belangrijkste eerst. Elke bevinding: bocht, code, uitleg, korte cue, gewicht."""
        out = []
        for nr, rows in self.history.items():
            recent = rows[-4:]
            if len(recent) < 2:
                continue
            a = lambda k: self._avg(recent, k)
            typ = recent[-1].get("bochttype")
            sp = self.spread(nr) or 0.0
            bal_in = bal_out = None
            if balance is not None:
                bal_in = (balance.issue_map() or {}).get((nr, "in"))
                bal_out = (balance.issue_map() or {}).get((nr, "uit"))

            def add(code, weight, text, cue, target):
                out.append({"bocht": nr, "code": code, "gewicht": round(weight + sp, 3), "uitleg": text,
                            "cue": cue, "doel": target})
            peak = a("rem_piek") or 0
            if peak > 0.5 and (a("rem_opbouw_s") or 0) > 0.35:
                add("rem_opbouw", 0.25, f"Bocht {nr}: je bouwt de remdruk te langzaam op "
                    f"({a('rem_opbouw_s'):.2f} seconde tot de piek). Trap in één keer stevig in.".replace(".", ",", 1),
                    f"Bocht {nr}: in één keer hard op de rem.", {"rem_opbouw_s": ("<", 0.25)})
            if (a("abs_deel") or 0) > 0.5:
                add("abs", 0.2, f"Bocht {nr}: de ABS grijpt het grootste deel van het remmen in. "
                    "Je remt harder dan de banden aankunnen; iets minder druk, vooral tijdens het insturen.",
                    f"Bocht {nr}: iets minder remdruk, ABS stil houden.", {"abs_deel": ("<", 0.35)})
            if typ in ("langzaam", "middel") and peak > 0.3:
                before = a("rem_los_voor_top_m")
                at_ti = a("rem_bij_instuur")
                if before is not None and before > 25 and (at_ti or 0) < 0.12:
                    why = " Daardoor duiken de voorwielen niet in en krijg je onderstuur bij het insturen." if bal_in == "onderstuur" else ""
                    add("trail_kort", 0.35, f"Bocht {nr}: je laat de rem {before:.0f} meter voor de top al los en "
                        f"remt bijna niet meer als je instuurt. Neem de rem geleidelijk mee de bocht in (trail braking).{why}",
                        f"Bocht {nr}: rem verder meenemen.", {"rem_los_voor_top_m": ("<", 15)})
                elif bal_in == "overstuur" and (at_ti or 0) > 0.35:
                    add("trail_te_veel", 0.3, f"Bocht {nr}: je staat nog met {at_ti * 100:.0f} procent op de rem als je "
                        "instuurt, en de achterkant komt los. Laat de rem eerder en rustiger los.",
                        f"Bocht {nr}: rem eerder lichter maken.", {"rem_bij_instuur": ("<", 0.25)})
                if peak > 0.5 and (a("rem_afbouw_s") or 1) < 0.15:
                    add("rem_los_abrupt", 0.2, f"Bocht {nr}: je laat de rem in één keer los. Laat hem afvloeien terwijl je "
                        "instuurt, dan blijft de auto rustig en grijpen de voorwielen.",
                        f"Bocht {nr}: rem rustig laten afvloeien.", {"rem_afbouw_s": (">", 0.25)})
            if (a("rollen_m") or 0) > 15:
                add("rollen", 0.25, f"Bocht {nr}: je rolt {a('rollen_m'):.0f} meter zonder gas en zonder rem. "
                    "Ga van de rem direct naar het gas.", f"Bocht {nr}: niet rollen, direct op het gas.",
                    {"rollen_m": ("<", 8)})
            if (a("overlap_m") or 0) > 5:
                add("overlap", 0.15, f"Bocht {nr}: je staat {a('overlap_m'):.0f} meter tegelijk op gas en rem.",
                    f"Bocht {nr}: eerst rem los, dan gas.", {"overlap_m": ("<", 2)})
            if (a("gas_pompen") or 0) >= 1.5:
                add("pompen", 0.2, f"Bocht {nr}: je pompt met het gas bij het uitkomen. Geef één keer rustig gas en "
                    "bouw het op terwijl je het stuur opendraait.", f"Bocht {nr}: één keer rustig gas.",
                    {"gas_pompen": ("<", 1)})
            sf = a("stuur_bij_vol_gas")
            if sf is not None and sf > 0.7:
                why = " Daardoor schuift de auto naar buiten." if bal_out == "onderstuur" else (
                    " Daardoor komt de achterkant los." if bal_out == "overstuur" else "")
                add("gas_met_stuur", 0.25, f"Bocht {nr}: je geeft vol gas met nog {sf * 100:.0f} procent stuur erin.{why} "
                    "Draai eerst het stuur open, dan vol gas.", f"Bocht {nr}: eerst stuur open, dan vol gas.",
                    {"stuur_bij_vol_gas": ("<", 0.55)})
            if (a("stuurcorrecties") or 0) >= 3:
                add("bijsturen", 0.15, f"Bocht {nr}: je stuurt gemiddeld {a('stuurcorrecties'):.0f} keer bij. Zet de auto in "
                    "één beweging neer: rustiger insturen helpt.", f"Bocht {nr}: in één beweging insturen.",
                    {"stuurcorrecties": ("<", 2)})
            if (a("tegensturen_s") or 0) > 0.3:
                add("tegensturen", 0.2, f"Bocht {nr}: je moet tegensturen, de achterkant breekt uit. "
                    "Rustiger op het gas, of kijk naar de setup-tip.", f"Bocht {nr}: rustig op het gas.",
                    {"tegensturen_s": ("<", 0.1)})
        # hele ronde: schakelen en force feedback
        li = self.lap_info[-4:]
        ups = [x["opschakel_toeren"] for x in li if x.get("opschakel_toeren")]
        if ups and self.shift_rpm and statistics.median(ups) < 0.9 * self.shift_rpm:
            out.append({"bocht": None, "code": "vroeg_schakelen", "gewicht": 0.15,
                        "uitleg": f"Je schakelt gemiddeld op {statistics.median(ups):.0f} toeren; het schakelpunt van deze auto is "
                                  f"{self.shift_rpm:.0f}. Schakel later op, dan houd je meer vermogen.",
                        "cue": "Later opschakelen.", "doel": {}})
        clips = [x["ffb_clipping"] for x in li if x.get("ffb_clipping") is not None]
        if clips and statistics.mean(clips) > 0.12:
            out.append({"bocht": None, "code": "ffb", "gewicht": 0.1,
                        "uitleg": f"Je force feedback zit {statistics.mean(clips) * 100:.0f} procent van de tijd op het maximum "
                                  "(clipping): dan voel je de banden niet meer. Zet de sterkte in iRacing lager.",
                        "cue": "", "doel": {}})
        out.sort(key=lambda f: -f["gewicht"])
        self.findings = out
        return out

    # ------------------------------------------------------------
    #  Zelfvergelijking: wat deed je anders in je snelste doorgangen?
    # ------------------------------------------------------------
    PHRASES = {
        "rem_start_m": ("later remde", "eerder remde", "meter"),
        "rem_los_voor_top_m": ("de rem verder meenam", "de rem eerder losliet", "meter", True),
        "vmin": ("meer snelheid meenam", "langzamer door de top ging", "km/u"),
        "vol_gas_m": ("eerder vol gas gaf", "later vol gas gaf", "meter", True),
        "rollen_m": ("minder rolde", "meer rolde", "meter", True),
        "instuur_m": ("later instuurde", "eerder instuurde", "meter"),
        "stuur_max_graden": ("minder stuur gaf", "meer stuur gaf", "graden", True),
        "rem_piek": ("harder remde", "zachter remde", "procent"),
    }

    def compare_self(self, nr):
        rows = [r for r in self.history.get(nr, []) if r.get("bochttijd")]
        if len(rows) < 5:
            return None
        rows = sorted(rows, key=lambda r: r["bochttijd"])
        fast, slow = rows[:3], rows[-3:]
        gain = self._avg(slow, "bochttijd") - self._avg(fast, "bochttijd")
        if gain < 0.08:
            return None
        cands = []
        for k, ph in self.PHRASES.items():
            f, s = self._avg(fast, k), self._avg(slow, k)
            if f is None or s is None:
                continue
            diff = f - s
            lower_is_better = len(ph) > 3 and ph[3]
            scale = {"meter": 8.0, "km/u": 3.0, "graden": 4.0, "procent": 0.08}[ph[2]]
            score = abs(diff) / scale
            if score < 1.0:
                continue
            better = (diff < 0) if lower_is_better else (diff > 0)
            word = ph[0] if better else ph[1]
            amount = abs(diff) * (100 if ph[2] == "procent" else 1)
            cands.append((score, f"{word} (ongeveer {amount:.0f} {ph[2]})"))
        if not cands:
            return None
        cands.sort(key=lambda x: -x[0])
        txt = f"In bocht {nr} was je {gain:.2f} sneller als je ".replace(".", ",") + " en ".join(c[1] for c in cands[:2]) + "."
        self.self_compare[nr] = txt
        return txt

    def consistency(self):
        out = []
        for nr in self.history:
            sp = self.spread(nr)
            if sp is not None:
                out.append((nr, sp))
        return sorted(out, key=lambda x: -x[1])

    def evaluate(self, metrics, target):
        """Voldoet deze doorgang aan het doel van een les? target = {sleutel: ('<'|'>', waarde)}"""
        if not metrics or not target:
            return None
        for k, (op, val) in target.items():
            x = metrics.get(k)
            if x is None:
                return None
            if op == "<" and not x < val:
                return False
            if op == ">" and not x > val:
                return False
        return True

    def summary(self):
        cons = self.consistency()[:3]
        return {"bevindingen": [{k: f[k] for k in ("bocht", "code", "uitleg")} for f in self.findings[:6]],
                "zelfvergelijking": list(self.self_compare.values())[:4],
                "minst_constante_bochten": [{"bocht": n, "spreiding_s": round(s, 2)} for n, s in cons],
                "laatste_metingen_per_bocht": {n: rows[-1] for n, rows in list(self.history.items())[:12]}}
