"""Extra race-functies: pitstop klaarzetten, andere klassen, vlaggen en safety car,
tegenstander-info, iRating-voorspelling en baan/weer."""
import math

from race_state import say_sec

# iRacing SessionFlags
F_CHECKERED, F_WHITE, F_GREEN, F_YELLOW = 0x0001, 0x0002, 0x0004, 0x0008
F_BLUE, F_DEBRIS, F_YELLOW_WAVING = 0x0020, 0x0040, 0x0100
F_ONE_TO_GREEN, F_CAUTION, F_CAUTION_WAVING = 0x0200, 0x4000, 0x8000
F_BLACK, F_REPAIR = 0x010000, 0x100000

# pyirsdk PitCommandMode
PIT_FUEL, PIT_LF, PIT_RF, PIT_LR, PIT_RR, PIT_CLEAR_TIRES, PIT_FR = 2, 3, 4, 5, 6, 7, 8

WETNESS = {1: "droog", 2: "grotendeels droog", 3: "heel licht nat", 4: "licht nat",
           5: "matig nat", 6: "erg nat", 7: "extreem nat"}

PRIO_URGENT, PRIO_RACE, PRIO_INFO = 1, 2, 4


def irating_change(ratings, my_index, my_pos):
    """Schatting volgens de bekende iRacing-formule (zelfde als de community-calculators).
    ratings: iRatings van alle starters in je klasse, my_pos: 1-based positie."""
    n = len(ratings)
    if n < 2:
        return None
    br = 1600 / math.log(2)

    def p(a, b):
        ea, eb = math.exp(-a / br), math.exp(-b / br)
        x = (1 - ea) * eb
        y = (1 - eb) * ea
        return x / (x + y) if x + y else 0.5

    r = ratings[my_index]
    chance = sum(p(r, rj) for rj in ratings)          # inclusief jezelf (0,5)
    expected = n - chance - 0.5
    fudge = (n / 2 - my_pos) / 100
    return (n - my_pos - expected - fudge) * 200 / n


class RaceExtras:
    def __init__(self, cfg, state, strat, src, engineer):
        self.cfg = cfg.get("race_extras", {}) or {}
        self.s = state
        self.strat = strat
        self.src = src
        self.eng = engineer
        # pitstop
        self.pit_fuel_sent = None
        self.pit_tyres_sent = None
        self.pit_announced = False
        # klassen
        self.class_warned = {}
        self._v = {}
        # vlaggen
        self.prev_flags = 0
        self.in_caution = False
        self.caution_advice = None
        self.prev_pits_open = True
        self.flag_last = {}
        # tegenstanders
        self.opp_last = {}
        self.prev_ahead = self.prev_behind = None
        # iRating
        self.ir_est = None
        self.ir_said_finish = False
        # weer
        self.temp_ref = None
        self.prev_wet = None
        self.rain_said = False
        self.declared_said = False
        self.weather_last = -999
        self.weather = {}

    def on(self, key, default=True):
        return self.cfg.get(key, default)

    # ------------------------------------------------------------
    def update(self, src, events):
        s = self.s
        out = []
        me = s.player()
        if not me or me.wraps is None:
            return out
        self._speeds()
        racing = s.is_race() and s.session_state == 4
        if self.on("weather"):
            out += self._weather(src)
        if self.on("multiclass") and not self.eng.quiet:
            out += self._traffic()
        if not s.is_race():
            return out
        if self.on("flags"):
            out += self._flags(src, racing)
        if not racing:
            if s.session_state >= 5 and self.on("irating") and not self.ir_said_finish and self.eng.finished:
                self.ir_said_finish = True
                est = self._irating()
                if est is not None:
                    out.append((PRIO_INFO, f"Schatting iRating: {'plus' if est >= 0 else 'min'} {abs(round(est))}."))
            return out
        for ev in events:
            if ev[0] == "player_lap":
                out += self._on_lap(ev[1])
            elif ev[0] == "incident" and ev[1] >= 4 and self.on("fast_repair"):
                if src.pit_command(PIT_FR, 0):
                    out.append((PRIO_RACE, "Zwaar contact. Fast repair staat klaar voor je volgende stop."))
            elif ev[0] == "player_pit_out":
                self.pit_fuel_sent = None
                self.pit_tyres_sent = None
                self.pit_announced = False
        if self.on("pit_auto"):
            out += self._pit_prep(src)
        if self.on("opponent_info") and not self.eng.quiet:
            out += self._opponents()
        return out

    def _speeds(self):
        """Snelheid van alle auto's op de baan (m/s), uit hun positie-verloop."""
        s = self.s
        L = s.track_len_m
        for idx, c in s.cars.items():
            if c.last_pct is None:
                continue
            prev = self._v.get(idx)
            if prev and s.t > prev[1] + 0.2:
                dp = (c.last_pct - prev[0]) % 1.0
                if dp > 0.5:
                    dp -= 1.0
                v = dp * L / (s.t - prev[1])
                v = 0.6 * prev[2] + 0.4 * v if prev[2] else v
                self._v[idx] = (c.last_pct, s.t, v)
            elif not prev:
                self._v[idx] = (c.last_pct, s.t, 0.0)

    # ------------------------------------------------------------
    #  Pitstop automatisch klaarzetten
    # ------------------------------------------------------------
    def _pit_prep(self, src):
        s = self.s
        me = s.player()
        if me.on_pit:
            return []
        plan = self.strat.plan()
        stops = plan.get("stops_nodig")
        if not stops:
            return []
        cur = (me.wraps or 0) + 1
        op = plan.get("pitvenster_open_ronde") or cur
        if cur < op - 1:
            return []
        fpl = plan.get("verbruik_per_ronde") or 0
        add = plan.get("bijtanken_als_je_nu_stopt")
        if add is None or add <= 0:
            return []
        fuel = int(math.ceil(add + 0.5 * fpl))
        cap = s.fuel_max or 999
        fuel = max(1, min(int(cap), fuel))
        out = []
        changed = False
        if self.pit_fuel_sent is None or abs(fuel - self.pit_fuel_sent) >= 1:
            if src.pit_command(PIT_FUEL, fuel):
                self.pit_fuel_sent = fuel
                changed = True
        mode = self.cfg.get("pit_tyres", "auto")
        left = (plan.get("ronden_te_gaan") or 0)
        tyres = mode == "altijd" or (mode == "auto" and left >= self.cfg.get("tyre_min_laps", 8))
        if self.pit_tyres_sent != tyres:
            ok = True
            if tyres:
                for m in (PIT_LF, PIT_RF, PIT_LR, PIT_RR):
                    ok = src.pit_command(m, 0) and ok
            else:
                ok = src.pit_command(PIT_CLEAR_TIRES, 0)
            if ok:
                self.pit_tyres_sent = tyres
                changed = True
        if not self.pit_announced and self.pit_fuel_sent and cur >= op:
            self.pit_announced = True
            band = "vier nieuwe banden" if self.pit_tyres_sent else "geen banden"
            out.append((PRIO_INFO, f"Pitstop staat klaar: {self.pit_fuel_sent} liter, {band}."))
        return out

    # ------------------------------------------------------------
    #  Andere klassen
    # ------------------------------------------------------------
    def _traffic(self):
        """Sneller verkeer van achteren, in elke sessie: een snellere klasse, iemand die je op ronde zet,
        of (in training/kwalificatie) een auto op een snelle ronde. Gemeten op hoe snel hij echt inloopt."""
        s = self.s
        me = s.player()
        L = s.track_len_m
        if not L or me.on_pit or me.last_pct is None:
            return []
        race = s.is_race()
        if race and getattr(self.eng, "finished", False):
            return []   # na de finish: uitrijden
        if race and (me.wraps or 0) < 1:
            return []   # startronde: iedereen zit op elkaar
        v_me = self._v.get(me.idx, (0, 0, 0))[2] or 0
        warn_s = float(self.cfg.get("multiclass_warn_s", 3.0))
        my_est = me.class_est_lap or me.avg_lap(3)
        coming = []
        for idx, c in s.cars.items():
            if idx == me.idx or c.on_pit or c.last_pct is None:
                continue
            behind_m = ((me.last_pct - c.last_pct) % 1.0) * L
            if behind_m < 5 or behind_m > 600:
                continue
            v = self._v.get(idx, (0, 0, 0))[2] or 0
            if v < 15:
                continue
            other_class = c.class_id != me.class_id and c.class_est_lap and my_est and c.class_est_lap < my_est * 0.97
            lapping = race and c.class_id == me.class_id and (c.wraps or 0) > (me.wraps or 0) \
                and not (c.wraps == (me.wraps or 0) + 1 and c.last_pct < me.last_pct)
            closing = v - v_me
            if closing < (2.0 if (other_class or lapping) else 5.0):
                continue   # loopt niet (duidelijk) in: gewone gevechten doen de gaps en de spotter
            gap = behind_m / v                     # over zoveel seconden is hij waar jij nu bent
            if 0.3 < gap <= warn_s:
                kind = "klasse" if other_class else ("ronde" if lapping else "snel")
                coming.append((gap, c, kind))
        if not coming:
            return []
        coming.sort(key=lambda x: x[0])
        gap, first, kind = coming[0]
        if s.t - self.class_warned.get(first.idx, -999) < 45:
            return []
        for _, c, _k in coming:
            self.class_warned[c.idx] = s.t
        sec = f"{max(1, round(gap))} seconde"
        if kind == "klasse":
            cls = first.class_name or "Snellere klasse"
            n = sum(1 for x in coming if x[2] == "klasse")
            if n > 1:
                return [(PRIO_RACE, f"{n} auto's uit de {cls} komen eraan, de eerste op {sec}. Laat ruimte.")]
            return [(PRIO_RACE, f"{cls} komt eraan, {sec}. Laat ruimte.")]
        if kind == "ronde":
            return [(PRIO_RACE, f"{first.name or 'Een auto'} zet je op een ronde, {sec} achter je. Laat hem netjes gaan.")]
        if race:
            return [(PRIO_RACE, f"{first.name or 'Een auto'} komt snel dichterbij, {sec} achter je.")]
        return [(PRIO_RACE, f"Snelle auto achter je, {sec}. Blijf op je lijn of laat hem gaan.")]

    # ------------------------------------------------------------
    #  Vlaggen en safety car
    # ------------------------------------------------------------
    def _flag_once(self, key, text, prio, every=20):
        if self.s.t - self.flag_last.get(key, -999) < every:
            return []
        self.flag_last[key] = self.s.t
        return [(prio, text)]

    def _flags(self, src, racing):
        s = self.s
        f = s.flags
        new = f & ~self.prev_flags
        out = []
        caution = bool(f & (F_CAUTION | F_CAUTION_WAVING))
        if caution and not self.in_caution and s.session_state == 4:
            self.in_caution = True
            self.prev_pits_open = s.pits_open
            out.append((PRIO_URGENT, "Safety car! Gele vlag over de hele baan, niet inhalen."))
            out += self._caution_advice()
        elif not caution and self.in_caution:
            self.in_caution = False
            self.caution_advice = None
            if s.session_state == 4:
                out.append((PRIO_URGENT, "Groen, groen, groen! Herstart."))
        if self.in_caution:
            if s.pits_open and not self.prev_pits_open:
                txt = "Pits zijn open."
                if self.caution_advice == "box":
                    txt += " Box, box deze ronde."
                out.append((PRIO_URGENT, txt))
            elif not s.pits_open and self.prev_pits_open:
                out.append((PRIO_RACE, "Pits zijn dicht."))
            self.prev_pits_open = s.pits_open
            if new & F_ONE_TO_GREEN:
                out.append((PRIO_RACE, "Nog één ronde tot de herstart. Houd je banden en remmen warm."))
        else:
            if new & (F_YELLOW | F_YELLOW_WAVING):
                out += self._flag_once("yellow", "Gele vlag. Voorzichtig, niet inhalen.", PRIO_URGENT)
            if new & F_DEBRIS:
                out += self._flag_once("debris", "Brokstukken op de baan.", PRIO_RACE)
        if new & F_BLUE:
            out += self._flag_once("blue", "Blauwe vlag. Laat de snellere auto erlangs.", PRIO_RACE, 30)
        if new & F_BLACK:
            out += self._flag_once("black", "Zwarte vlag! Je moet de pits in.", PRIO_URGENT, 30)
        if new & F_REPAIR:
            out += self._flag_once("repair", "Reparatievlag: naar de pits voor reparatie.", PRIO_URGENT, 30)
        self.prev_flags = f
        return out

    def _caution_advice(self):
        s = self.s
        plan = self.strat.plan()
        stops = plan.get("stops_nodig")
        me = s.player()
        cur = (me.wraps or 0) + 1
        closed = "" if s.pits_open else " De pits zijn nog dicht."
        if stops is None:
            self.caution_advice = None
            return [(PRIO_RACE, "Ik heb nog te weinig brandstofdata voor een advies." + closed)]
        if stops == 0:
            self.caution_advice = "stay"
            return [(PRIO_RACE, "Je hebt genoeg brandstof tot de finish. Advies: buiten blijven." + closed)]
        op = plan.get("pitvenster_open_ronde") or cur
        if cur >= op:
            self.caution_advice = "box"
            return [(PRIO_RACE, "Advies: stoppen zodra de pits open zijn. Onder de safety car kost een stop veel minder tijd, "
                                "en daarna haal je de finish." + closed)]
        self.caution_advice = "maybe"
        return [(PRIO_RACE, f"Je moet nog {stops} keer stoppen, maar nu haal je met een volle tank de finish nog niet. "
                            "Stoppen bespaart tijd, maar dan moet je later nog een keer naar binnen. Jouw keus." + closed)]

    # ------------------------------------------------------------
    #  Tegenstanders
    # ------------------------------------------------------------
    def _opponents(self):
        s = self.s
        ahead, behind = s.neighbours()
        out = []
        for car, side, prev in ((ahead, "voor", self.prev_ahead), (behind, "achter", self.prev_behind)):
            if car is None or car.idx == prev:
                continue
            g = s.gap_to(car)
            if g is None or abs(g) > 4 or s.t - self.opp_last.get(car.idx, -999) < 300:
                continue
            self.opp_last[car.idx] = s.t
            bits = []
            if car.irating:
                bits.append(f"{car.irating} iRating")
            if car.license:
                bits.append(f"{car.license[0]}-licentie")
            txt = f"{car.name} {side} je" + (": " + ", ".join(bits) if bits else "")
            if car.inc_count >= int(self.cfg.get("opponent_inc_warn", 8)):
                txt += f". Hij heeft al {car.inc_count} incidenten, geef hem ruimte"
            out.append((PRIO_INFO, txt + "."))
        self.prev_ahead = ahead.idx if ahead else None
        self.prev_behind = behind.idx if behind else None
        return out

    # ------------------------------------------------------------
    #  iRating
    # ------------------------------------------------------------
    def _irating(self):
        s = self.s
        me = s.player()
        f = [c for c in s.field() if c.irating > 0]
        if not me or me.irating <= 0 or me not in f or len(f) < 2:
            return None
        ratings = [c.irating for c in f]
        pos = f.index(me) + 1
        self.ir_est = irating_change(ratings, f.index(me), pos)
        return self.ir_est

    def _on_lap(self, lap_nr):
        out = []
        est = self._irating() if self.on("irating") else None
        if est is not None and lap_nr >= 3 and lap_nr % 5 == 3:
            out.append((PRIO_INFO, f"Als je zo finisht: {'plus' if est >= 0 else 'min'} {abs(round(est))} iRating."))
        return out

    # ------------------------------------------------------------
    #  Baan en weer
    # ------------------------------------------------------------
    def _weather(self, src):
        s = self.s
        out = []
        temp = src["TrackTempCrew"]
        if temp is None:
            temp = src["TrackTemp"]
        precip = src["Precipitation"]
        wet = src["TrackWetness"]
        declared = src["WeatherDeclaredWet"]
        self.weather = {"baantemp": round(temp, 1) if temp is not None else None,
                        "luchttemp": round(src["AirTemp"], 1) if src["AirTemp"] is not None else None,
                        "regen": round(precip, 2) if precip is not None else None,
                        "baan": WETNESS.get(wet) if wet else None, "nat_verklaard": bool(declared)}
        if s.session_state < 3 or s.t < 10:
            return out
        quiet = s.t - self.weather_last < 45
        if temp is not None:
            if self.temp_ref is None:
                self.temp_ref = temp
            d = temp - self.temp_ref
            if abs(d) >= float(self.cfg.get("track_temp_step", 3.0)) and not quiet:
                self.temp_ref = temp
                self.weather_last = s.t
                if d < 0:
                    out.append((PRIO_INFO, f"Baantemperatuur {abs(round(d))} graden gedaald, nu {round(temp)}. Meer grip, je kunt later remmen."))
                else:
                    out.append((PRIO_INFO, f"Baantemperatuur {round(d)} graden gestegen, nu {round(temp)}. Minder grip, let op je achterbanden."))
        if precip is not None and precip > 0.05 and not self.rain_said:
            self.rain_said = True
            self.weather_last = s.t
            out.append((PRIO_RACE, "Het begint te regenen. Let op je grip."))
        if wet and self.prev_wet and wet != self.prev_wet and wet >= 1:
            if wet > self.prev_wet and wet >= 3:
                out.append((PRIO_RACE, f"De baan wordt natter: nu {WETNESS.get(wet, 'nat')}."))
                self.weather_last = s.t
            elif wet < self.prev_wet and self.prev_wet >= 3:
                out.append((PRIO_RACE, f"De baan droogt op: nu {WETNESS.get(wet, 'droger')}."))
                self.weather_last = s.t
        if wet:
            self.prev_wet = wet
        if declared and not self.declared_said:
            self.declared_said = True
            out.append((PRIO_RACE, "De baan is nat verklaard. Regenbanden zijn nu toegestaan."))
        return out

    # ------------------------------------------------------------
    def summary(self):
        return {"irating_schatting": round(self.ir_est) if self.ir_est is not None else None,
                "safety_car": self.in_caution, "pits_open": self.s.pits_open,
                "pitstop_klaar": {"liter": self.pit_fuel_sent, "banden": self.pit_tyres_sent},
                "weer": self.weather}
