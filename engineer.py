"""De race engineer: zet gebeurtenissen om in korte gesproken berichten
en bouwt volledige race-updates (regel-gebaseerd of via AI)."""
from race_state import say_lap, say_sec, fmt_lap

# prioriteit: 1 = urgent, 2 = race-info, 3 = coaching, 4 = extra
P_URGENT, P_RACE, P_COACH, P_INFO = 1, 2, 3, 4


class Engineer:
    def __init__(self, cfg, state, strategy, coach):
        self.cfg = cfg
        self.ecfg = cfg["engineer"]
        self.s = state
        self.strat = strategy
        self.coach = coach
        self.gap_hist = {}            # car idx -> [(lap, gap)]
        self.last_battle_warn = -999
        self.last_ahead_idx = None
        self.last_behind_idx = None
        self.fuel_warned = set()
        self.window_announced = False
        self.best_lap = None
        self.laps_done_reported = set()
        self.started = False
        self.finished = False
        self.checkered = False
        self.announced_pos = None
        self.pending_pos = None
        self.pending_since = 0
        self.last_lap_said = False
        self.quiet = False          # True tijdens een spin/uitstapje (dan praat de incident-module)
        self.incidents = None       # IncidentWatcher, gezet door de motor
        self.extras = None          # RaceExtras, gezet door de motor
        self.balance = None         # BalanceAnalyser, gezet door de motor
        self.rival = None
        self.setup = None

    # ------------------------------------------------------------
    def handle_events(self, events):
        out = []
        for ev in events:
            kind = ev[0]
            if kind == "player_lap":
                out += self._on_lap(ev[1], ev[2], ev[3])
            elif kind == "position_change":
                if self.announced_pos is None:
                    self.announced_pos = ev[1]
                self.pending_pos, self.pending_since = ev[2], self.s.t
            elif kind == "player_pit_in":
                out.append((P_RACE, "Pitstraat. Let op je snelheidsbegrenzer."))
            elif kind == "player_pit_out":
                out += self._on_pit_out()
            elif kind == "car_pit_in":
                out += self._on_car_pit(ev[1])
            elif kind == "incident":
                pass
            elif kind == "session_state":
                out += self._on_session_state(ev[1])
            elif kind == "pit_loss_learned":
                pass
        return out

    def tick(self):
        """Doorlopende checks (battle-waarschuwing, brandstof-alarm)."""
        out = []
        s = self.s
        if not s.is_race() or s.session_state != 4:
            return out
        me = s.player()
        if not me or self.finished:
            return out
        if self.announced_pos is None and me.position and me.progress > 0.05:
            self.announced_pos = me.position
        if self.quiet:
            # tijdens een incident geen losse positie-/battle-meldingen; samenvatting volgt
            self.pending_pos = None
            self.announced_pos = me.position
            return out
        if self.pending_pos is not None and s.t - self.pending_since >= 2.0:
            if me.position == self.pending_pos and self.pending_pos != self.announced_pos:
                out += self._on_position(self.announced_pos, self.pending_pos)
                self.announced_pos = self.pending_pos
            self.pending_pos = None
        if me.on_pit or (me.wraps or 0) < 1:
            return out
        ahead, behind = s.neighbours()
        if behind is not None and not behind.on_pit:
            g = s.gap_to(behind)
            if g is not None and -self.ecfg["battle_alert_gap"] < g < 0 and s.t - self.last_battle_warn > 45:
                self.last_battle_warn = s.t
                close = "direct achter je" if g > -0.15 else f"achter je, {say_sec(g)}"
                out.append((P_URGENT, f"{behind.name} zit {close}. Verdedig."))
        return out

    # ------------------------------------------------------------
    def _on_session_state(self, st):
        s = self.s
        if st == 4 and s.is_race() and not self.started:
            self.started = True
            me = s.player()
            msg = "Groen, groen, groen. Succes!"
            if me and me.position:
                msg = f"Groene vlag. Je start op P{me.position}. Rustig door bocht 1."
            return [(P_URGENT, msg)]
        if st == 5 and s.is_race() and not self.checkered:
            self.checkered = True
            return [(P_URGENT, "Geblokte vlag is gevallen. Dit is je laatste ronde, breng hem thuis.")]
        return []

    def _on_lap(self, lap_nr, lap_time, clean):
        s = self.s
        out = []
        me = s.player()
        # coaching-samenvatting + referentie
        if self.finished:
            return []
        if self.checkered and s.is_race():
            self.finished = True
            pos = me.official_pos or me.position
            txt = f"Finish! P{pos}."
            if s.start_position:
                d = s.start_position - pos
                if d > 0:
                    txt += f" {d} {'plek' if d == 1 else 'plekken'} gewonnen."
            return [(P_URGENT, txt + " Goed gereden, rustig terug naar de pits.")]
        out += self.coach.lap_completed(lap_time, clean)
        if s.is_race() and s.session_state not in (4, 5):
            return out
        parts = []
        pb = False
        if clean and (self.best_lap is None or lap_time < self.best_lap):
            pb = self.best_lap is not None
            self.best_lap = lap_time
        if self.ecfg["lap_report"]:
            if s.is_race():
                parts.append(f"P{me.position}.")
            parts.append(f"{say_lap(lap_time)}.")
            if pb:
                parts.append("Persoonlijk beste ronde!")
            elif self.best_lap and clean:
                d = lap_time - self.best_lap
                if d > 0.05:
                    parts.append(f"{say_sec(d)} boven je beste.")
        if s.is_race():
            left = self.strat.my_laps_remaining()
            if left is not None:
                l = round(left)
                if l == 1 and not self.last_lap_said:
                    self.last_lap_said = True
                    parts.append("Laatste ronde!")
                elif l in (2, 3, 5, 10) and l not in self.laps_done_reported:
                    self.laps_done_reported.add(l)
                    parts.append(f"Nog {l} ronden.")
        if parts:
            out.append((P_RACE, " ".join(parts)))
        if s.is_race():
            out += self._gap_report(lap_nr)
        if self.ecfg["fuel_reports"]:
            out += self._fuel_report(lap_nr)
        return out

    def _clean_for_trend(self, car):
        s = self.s
        me = s.player()
        if s.caution:
            return False
        for c in (car, me):
            if c is None:
                continue
            if c.on_pit or (c.last_pit_lap is not None and (c.wraps or 0) - c.last_pit_lap <= 1):
                return False
        if me and me.lap_times and not me.lap_times[-1][2]:
            return False
        return True

    def _trend(self, car):
        h = self.gap_hist.get(car.idx, [])
        if h and len(h) >= 2 and (h[-1][1] > 0) != (h[-2][1] > 0):
            return None  # net van plek gewisseld
        if len(h) < 2:
            return None
        recent = h[-3:]
        laps = recent[-1][0] - recent[0][0]
        if laps <= 0:
            return None
        return (recent[-1][1] - recent[0][1]) / laps   # verandering in gap per ronde

    def _gap_report(self, lap_nr):
        s = self.s
        mode = self.ecfg["gap_report"]
        if mode == "off":
            return []
        ahead, behind = s.neighbours()
        out = []
        for car in (ahead, behind):
            if car is None:
                continue
            g = s.gap_to(car)
            if g is None:
                continue
            h = self.gap_hist.setdefault(car.idx, [])
            if not self._clean_for_trend(car):
                h.clear()   # pitstop / safety car / spin: trend opnieuw opbouwen
                continue
            if h and (h[-1][1] > 0) != (g > 0):
                h.clear()  # voor/achter gewisseld: trend opnieuw opbouwen
            if not h or h[-1][0] != lap_nr:
                h.append((lap_nr, g))
        speak_every = (mode == "every_lap") or (lap_nr % 3 == 0)
        new_ahead = ahead is not None and ahead.idx != self.last_ahead_idx
        new_behind = behind is not None and behind.idx != self.last_behind_idx
        self.last_ahead_idx = ahead.idx if ahead else None
        self.last_behind_idx = behind.idx if behind else None

        bits = []
        if ahead is not None and not ahead.on_pit:
            g = s.gap_to(ahead)
            tr = self._trend(ahead)
            if g is not None:
                if s.laps_between(ahead) >= 1 and g > 60:
                    pass
                else:
                    interesting = g < 2.5 or new_ahead or (tr is not None and abs(tr) > 0.25)
                    if speak_every or interesting:
                        txt = f"{ahead.name} vlak voor je" if g < 0.15 else f"Voor je {ahead.name}, {say_sec(g)}"
                        if tr is not None and tr < -0.1:
                            catch = g / -tr
                            txt += f", je pakt {say_sec(-tr)} per ronde"
                            left = self.strat.my_laps_remaining()
                            if catch < 25 and (left is None or catch < left):
                                n = max(1, round(catch))
                                txt += ", volgende ronde zit je erop" if n == 1 else f", over {n} ronden zit je erop"
                        elif tr is not None and tr > 0.1:
                            txt += f", hij loopt {say_sec(tr)} per ronde weg"
                        bits.append(txt + ".")
        if behind is not None and not behind.on_pit:
            g = s.gap_to(behind)
            tr = self._trend(behind)
            if g is not None and not (s.laps_between(behind) >= 1 and g < -60):
                gb = -g
                # trend voor achter: gap wordt negatiever = verder weg
                interesting = gb < 2.0 or new_behind or (tr is not None and abs(tr) > 0.25)
                if speak_every or interesting:
                    txt = f"{behind.name} direct achter je" if gb < 0.15 else f"Achter je {behind.name}, {say_sec(gb)}"
                    if tr is not None and tr > 0.1:
                        txt += f", komt {say_sec(tr)} per ronde dichterbij"
                    elif tr is not None and tr < -0.1:
                        txt += f", je loopt {say_sec(-tr)} per ronde weg"
                    bits.append(txt + ".")
        if bits:
            out.append((P_RACE, " ".join(bits)))
        return out

    def _fuel_report(self, lap_nr):
        s = self.s
        plan = self.strat.plan()
        fpl = plan.get("verbruik_per_ronde")
        if fpl is None:
            return []
        out = []
        tank_laps = plan.get("ronden_in_tank")
        stops = plan.get("stops_nodig")
        # waarschuwingen
        if tank_laps is not None and s.is_race() and stops:
            if tank_laps < 1.3 and "box" not in self.fuel_warned:
                self.fuel_warned.add("box")
                add = plan.get("bijtanken_als_je_nu_stopt")
                out.append((P_URGENT, f"Box, box deze ronde! Brandstof voor nog {say_sec(tank_laps)} ronde. Tank {add:.0f} liter."))
            elif tank_laps < 3.2 and "3" not in self.fuel_warned:
                self.fuel_warned.add("3")
                out.append((P_RACE, f"Brandstof voor nog ongeveer {round(tank_laps)} ronden."))
        if self.started and s.is_race() and stops and not self.window_announced:
            op = plan.get("pitvenster_open_ronde")
            cl = plan.get("pitvenster_sluit_ronde")
            me = s.player()
            if op and cl and me and (me.wraps or 0) + 1 >= max(op, cl - 3):
                self.window_announced = True
                out.append((P_RACE, f"Pitvenster is open. Uiterlijk ronde {cl} naar binnen."))
        # periodiek overzicht (ronde 2 en daarna elke 5 ronden)
        if lap_nr == 2 or (lap_nr > 2 and lap_nr % 5 == 0):
            txt = f"Brandstof: {say_sec(fpl, 2)} liter per ronde, {say_sec(tank_laps)} ronden in de tank."
            if s.is_race() and plan.get("ronden_te_gaan") is not None:
                if stops == 0:
                    txt += f" Je haalt de finish, {say_sec(plan.get('overschot_liter', 0))} liter over."
                elif stops:
                    save = plan.get("besparing_nodig_pct", 99)
                    if 0 < save <= 7:
                        txt += f" Met {say_sec(save)} procent zuiniger rijden haal je het zonder stop: doel {say_sec(plan['doel_verbruik_zonder_stop'], 2)} liter per ronde."
                    else:
                        txt += f" Je moet {stops} keer stoppen. Pitvenster ronde {plan['pitvenster_open_ronde']} tot {plan['pitvenster_sluit_ronde']}."
            out.append((P_INFO, txt))
        return out

    def _on_position(self, old, new):
        s = self.s
        if s.player() and s.player().on_pit:
            return []
        f = s.field()
        me = s.player()
        if new < old:
            passed = f[new] if new < len(f) else None   # degene direct achter mij
            who = f" op {passed.name}" if passed and passed.idx != me.idx else ""
            if passed and passed.on_pit:
                return [(P_RACE, f"P{new}, {passed.name} is de pits in.")]
            return [(P_RACE, f"Mooi, P{new}. Positie gewonnen{who}.")]
        else:
            by = f[new - 2] if new - 2 >= 0 else None
            who = f" aan {by.name}" if by and by.idx != me.idx else ""
            return [(P_RACE, f"P{new}. Positie verloren{who}.")]

    def _on_car_pit(self, idx):
        s = self.s
        ahead, behind = s.neighbours()
        car = s.cars.get(idx)
        if car is None:
            return []
        if (ahead and idx == ahead.idx) or (behind and idx == behind.idx):
            where = "voor" if ahead and idx == ahead.idx else "achter"
            return [(P_RACE, f"{car.name}, de auto {where} je, gaat de pits in.")]
        return []

    def _on_pit_out(self):
        me = self.s.player()
        self.fuel_warned.clear()
        self.window_announced = True
        if not me:
            return []
        return [(P_RACE, f"Uit de pits op P{me.position}. Banden zijn koud, pas op in de eerste bochten.")]

    # ------------------------------------------------------------
    #  Op verzoek (knoppen)
    # ------------------------------------------------------------
    def gaps_now(self, with_pos=True):
        s = self.s
        me = s.player()
        if not me:
            return "Nog geen data."
        ahead, behind = s.neighbours()
        parts = [f"P{me.position}."] if with_pos else []
        if ahead:
            g = s.gap_to(ahead)
            if g is not None:
                parts.append(f"{ahead.name} vlak voor je." if g < 0.15 else f"Voor je {ahead.name} op {say_sec(g)}.")
        if behind:
            g = s.gap_to(behind)
            if g is not None:
                parts.append(f"{behind.name} direct achter je." if -g < 0.15 else f"Achter je {behind.name} op {say_sec(-g)}.")
        leader = s.field()[0] if s.field() else None
        if leader and leader.idx != me.idx:
            g = s.gap_to(leader)
            if g is not None:
                parts.append(f"Leider {leader.name} op {say_sec(g)}." if s.laps_between(leader) < 1 else f"Leider {leader.name} ligt een ronde voor.")
        return " ".join(parts)

    def strategy_now(self):
        plan = self.strat.plan()
        if plan.get("verbruik_per_ronde") is None:
            return "Ik heb nog minstens één volle ronde nodig om het verbruik te meten."
        txt = f"{say_sec(plan['brandstof'])} liter aan boord, {say_sec(plan['verbruik_per_ronde'], 2)} per ronde, goed voor {say_sec(plan['ronden_in_tank'])} ronden."
        stops = plan.get("stops_nodig")
        if stops == 0:
            txt += f" Je haalt de finish met {say_sec(plan.get('overschot_liter', 0))} liter over."
        elif stops:
            txt += f" Nog {stops} stop nodig, venster ronde {plan['pitvenster_open_ronde']} tot {plan['pitvenster_sluit_ronde']}."
            save = plan.get("besparing_nodig_pct")
            if save is not None and 0 < save <= 10:
                txt += f" Of {say_sec(save)} procent zuiniger rijden en doorrijden."
            rj = self.strat.pit_rejoin(plan.get("bijtanken_als_je_nu_stopt"))
            if rj:
                txt += f" Stop je nu, dan kom je terug op P{rj['nieuwe_positie']}"
                if rj.get("terug_achter"):
                    txt += f", achter {rj['terug_achter']}"
                txt += "."
        return txt

    def full_update_rules(self):
        """Volledige update zonder AI."""
        s = self.s
        me = s.player()
        if not me:
            return "Nog geen data."
        parts = []
        left = self.strat.my_laps_remaining()
        if s.is_race():
            parts.append(f"Race-update. P{me.position} van {len(s.field())}" +
                         (f", nog {round(left)} ronden." if left is not None else "."))
            if s.start_position:
                d = s.start_position - me.position
                if d > 0:
                    parts.append(f"Je hebt {d} {'plek' if d == 1 else 'plekken'} gewonnen sinds de start.")
                elif d < 0:
                    parts.append(f"{-d} plekken verloren sinds de start.")
        avg = me.avg_lap(3)
        if avg:
            parts.append(f"Je gemiddelde over drie ronden is {say_lap(avg)}, beste {say_lap(me.best_lap())}.")
        if s.is_race():
            parts.append(self.gaps_now(with_pos=False))
            ahead, behind = s.neighbours()
            if ahead and ahead.avg_lap(3) and avg:
                d = ahead.avg_lap(3) - avg
                parts.append(f"Je bent {say_sec(abs(d))} per ronde {'sneller' if d > 0 else 'langzamer'} dan {ahead.name}.")
        parts.append(self.strategy_now())
        return " ".join(parts)

    def snapshot(self):
        """Alle data voor de AI."""
        s = self.s
        me = s.player()
        if not me:
            return {}
        ahead, behind = s.neighbours()

        def car_info(c):
            if not c:
                return None
            return {"naam": c.name, "positie": c.position, "irating": c.irating or None,
                    "licentie": c.license or None, "incidenten_rijder": c.inc_count, "gap_s": round(s.gap_to(c), 2) if s.gap_to(c) is not None else None,
                    "trend_gap_per_ronde": round(self._trend(c), 2) if self._trend(c) is not None else None,
                    "laatste_ronde": fmt_lap(c.last_lap), "gem_3": fmt_lap(c.avg_lap(3)),
                    "beste": fmt_lap(c.best_lap()), "pitstops": c.pit_stops, "in_pit": c.on_pit}
        return {
            "sessie": s.session_type, "baan": s.track_name, "auto": s.car_name,
            "status": {4: "racing", 5: "geblokte vlag"}.get(s.session_state, s.session_state),
            "ronde": (me.wraps or 0) + 1, "ronden_te_gaan": round(self.strat.my_laps_remaining() or 0, 1),
            "totaal_ronden": s.total_laps,
            "jij": {"positie": me.position, "startpositie": s.start_position,
                     "laatste_rondes": [fmt_lap(t) for _, t, _ in me.lap_times[-6:]],
                     "beste": fmt_lap(me.best_lap()), "gem_3": fmt_lap(me.avg_lap(3)),
                     "pitstops": me.pit_stops, "incidenten": s.incidents},
            "auto_voor": car_info(ahead), "auto_achter": car_info(behind),
            "klassement": s.race_order_summary(15),
            "brandstof_en_strategie": self.strat.plan(),
            "pitstop_nu": self.strat.pit_rejoin(self.strat.plan().get("bijtanken_als_je_nu_stopt")),
            "pitstop_tijdverlies_s": s.pit_loss,
            "coaching": self.coach.summary(),
            "incidenten": self.incidents.summary() if self.incidents else None,
            "race_extra": self.extras.summary() if self.extras else None,
            "auto_balans": self.balance.summary() if self.balance else None,
            "tegenstander_per_bocht": self.rival.summary_now() if self.rival else None,
            "setup": self.setup.summary() if self.setup else None,
            "safety_car_of_geel": s.caution,
        }
