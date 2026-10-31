"""De motor: leest telemetrie, laat de engineer praten. Draait in een achtergrondthread
zodat het programmavenster (of de console) er los van blijft."""
import datetime
import os
import queue
import threading
import time

from ai import AI
from coach import Coach
from engineer import Engineer, P_RACE
from incidents import IncidentWatcher
from race_extras import RaceExtras
from balance import BalanceAnalyser
from inputs import Listener
from race_state import RaceState, fmt_lap
import settings
from strategy import Strategy

TICK = 1 / 60


class Engine:
    def __init__(self, cfg, log):
        """log(tekst, soort) met soort = 'info' | 'radio' | 'question'"""
        self.cfg = cfg
        self._log = log
        self.actions = queue.Queue()
        self.thread = None
        self.stop_flag = threading.Event()
        self.running = False
        self.connected = False
        self.mock = False
        self.status = {}
        self.voice = None
        self.ai = None

    def log(self, msg, kind="info"):
        try:
            self._log(msg, kind)
        except Exception:
            pass

    # ------------------------------------------------------------
    def start(self, mock=False, speed=1.0, laps=22, session="Race"):
        if self.running:
            return
        self.stop_flag.clear()
        self.mock = mock
        self.mock_session = session
        self.thread = threading.Thread(target=self._run, args=(mock, speed, laps), daemon=True)
        self.running = True
        self.thread.start()

    def stop(self):
        self.stop_flag.set()

    def action(self, name):
        if self.running:
            self.actions.put(name)

    # ------------------------------------------------------------
    def _run(self, mock, speed, laps):
        try:
            self._run_inner(mock, speed, laps)
        except Exception as e:
            import traceback
            self.log(f"Fout: {e}")
            self.log(traceback.format_exc())
        finally:
            if self.voice:
                self.voice.stop()
            self.running = False
            self.connected = False
            self.status = {}
            self.log("Engineer gestopt.")

    def _run_inner(self, mock, speed, laps):
        cfg = self.cfg
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        from voice import Voice
        self.voice = voice = Voice(cfg, self.log)
        self.ai = ai = AI(cfg, self.log)
        listener = None

        if mock:
            from telemetry import MockSource
            session = getattr(self, "mock_session", "Race")
            src = MockSource(race_laps=laps, session=session)
            self.log(f"Test gestart: {session.lower()}, {laps} ronden.")
        else:
            try:
                from telemetry import IRacingSource
                src = IRacingSource()
            except Exception as e:
                self.log(f"iRacing-koppeling kon niet laden: {e}")
                return
            self.log("Wachten op iRacing... (start een sessie en stap in de auto)")

        state = RaceState(cfg)
        strat = Strategy(state, cfg)
        import tempfile
        # testsessies gebruiken een tijdelijke map, zodat je echte referentierondes schoon blijven
        coach = Coach(cfg, state, data_dir=settings.ref_dir() if not mock else tempfile.mkdtemp(prefix="re_test_"))
        eng = Engineer(cfg, state, strat, coach)
        incw = IncidentWatcher(cfg, state, coach)
        eng.incidents = incw
        self.incw = incw
        extras = RaceExtras(cfg, state, strat, src, eng)
        eng.extras = extras
        self.extras = extras
        bal = BalanceAnalyser(cfg, state, coach)
        eng.balance = bal
        self.balance = bal
        self.state, self.eng, self.strat, self.coach = state, eng, strat, coach

        lap_log = []
        debrief_done = False
        debrief_thread = None
        auto_every = int(cfg["ai"].get("auto_update_every_laps") or 0)
        last_status = 0.0

        def speak_cb(prio):
            return lambda text: voice.say(text, prio) if text else None

        while not self.stop_flag.is_set():
            ok = src.check_connection()
            if not ok:
                if self.connected:
                    self.log("Verbinding met iRacing verbroken.")
                    self.connected = False
                    self.status = {}
                time.sleep(1)
                continue
            if not self.connected:
                self.connected = True
                self.log("Verbonden met iRacing." if not mock else "Testrace loopt.")
                voice.say("Radio check. Ik ben er klaar voor.", 1)

            src.advance(TICK)
            src.freeze()
            events = state.update(src)
            msgs = eng.handle_events(events)
            msgs += coach.update(src, None)
            msgs += incw.update(src, events)
            eng.quiet = incw.active is not None
            msgs += extras.update(src, events)
            bal.update(src)
            for ev in events:
                if ev[0] == "player_lap":
                    msgs += bal.lap_completed(ev[3])
            if getattr(incw, "just_finished", False):
                incw.just_finished = False
                eng.gap_hist.clear()   # trends opnieuw opbouwen na een spin
            msgs += eng.tick()
            src.unfreeze()

            for ev in events:
                if ev[0] == "player_lap":
                    me = state.player()
                    lap_log.append({"ronde": ev[1], "tijd": fmt_lap(ev[2]), "schoon": ev[3],
                                    "positie": me.position if me else None})
                    if auto_every and state.is_race() and state.session_state == 4 and ev[1] % auto_every == 0:
                        ai.run_async(lambda: ai.race_update(eng.snapshot()), speak_cb(P_RACE))

            if eng.finished and not debrief_done:
                debrief_done = True
                if cfg["ai"].get("debrief_after_race") and ai.available:
                    def later():
                        time.sleep(3)
                        try:
                            text = ai.debrief(eng.snapshot(), lap_log)
                        except Exception as e:
                            self.log(f"Nabespreking mislukt: {e}")
                            return
                        if not text:
                            return
                        p = os.path.join(settings.logs_dir(), f"nabespreking_{stamp}.txt")
                        with open(p, "w", encoding="utf-8") as f:
                            f.write(text)
                        self.log(text, "debrief")
                        voice.say(text, 4)
                    debrief_thread = threading.Thread(target=later, daemon=True)
                    debrief_thread.start()

            for prio, text in msgs:
                voice.say(text, prio)

            while not self.actions.empty():
                act = self.actions.get_nowait()
                if act == "repeat":
                    voice.repeat()
                elif act == "gaps":
                    voice.say(eng.gaps_now(), 1)
                elif act == "strategy":
                    voice.say(eng.strategy_now(), 1)
                elif act == "setup_advice":
                    def rules_advice():
                        issues = bal.summary()["balans_problemen"]
                        if not issues:
                            return "Ik zie nog geen duidelijk onder- of overstuur. Rij een paar schone ronden, dan kijk ik opnieuw."
                        i = issues[0]
                        return f"Grootste punt: {i['balans']} bij het {i['fase']} van bocht {i['bocht']}. {i['standaard_tip']}"
                    ai.run_async(lambda: ai.setup_advice(eng.snapshot()), speak_cb(1), fallback=rules_advice)
                elif act == "race_update":
                    ai.run_async(lambda: ai.race_update(eng.snapshot()), speak_cb(1), fallback=eng.full_update_rules)
                elif act == "ask_question":
                    if not ai.available:
                        voice.say("Vragen stellen werkt alleen met een API-sleutel.", 1)
                        continue
                    if listener is None:
                        listener = Listener(cfg, self.log)
                    voice.say("Zeg het maar.", 1)

                    def on_question(q):
                        if not q:
                            voice.say("Niet verstaan.", 1)
                            return
                        self.log(q, "question")
                        ai.run_async(lambda: ai.answer(q, eng.snapshot()), speak_cb(1))
                    listener.listen(on_question)

            if state.t - last_status > 0.4 or state.t < last_status:
                last_status = state.t
                self.status = self._build_status()

            if mock:
                if src.finished and not ai.busy and not voice.busy() and not (debrief_thread and debrief_thread.is_alive()):
                    if not hasattr(src, "_end_t"):
                        src._end_t = time.time()
                    elif time.time() - src._end_t > 3:
                        self.log("Testrace afgelopen.")
                        break
                if speed > 0:
                    time.sleep(TICK / speed)
            else:
                time.sleep(TICK)

    @staticmethod
    def _flag_name(f):
        if f & (0x4000 | 0x8000):
            return "safety car"
        if f & 0x010000:
            return "zwart"
        if f & (0x0008 | 0x0100):
            return "geel"
        if f & 0x0020:
            return "blauw"
        if f & 0x0002:
            return "wit"
        if f & 0x0001:
            return "geblokt"
        return "groen"

    # ------------------------------------------------------------
    def _build_status(self):
        s, eng, strat = self.state, self.eng, self.strat
        me = s.player()
        if not me:
            return {"verbonden": True}
        ahead, behind = s.neighbours()

        def side(c):
            if not c:
                return None
            g = s.gap_to(c)
            return {"naam": c.name, "nr": c.number, "gap": g, "trend": eng._trend(c),
                    "pit": c.on_pit, "laatste": c.last_lap}
        plan = strat.plan()
        left = strat.my_laps_remaining()
        lap_now = (me.wraps or 0) + 1
        return {
            "verbonden": True,
            "sessie": s.session_type, "baan": s.track_name, "auto": s.car_name,
            "positie": me.position, "deelnemers": len(s.field()),
            "ronde": max(1, lap_now), "totaal": s.total_laps,
            "ronden_te_gaan": left,
            "laatste": me.last_lap, "beste": me.best_lap(),
            "voor": side(ahead), "achter": side(behind),
            "brandstof": plan.get("brandstof"), "verbruik": plan.get("verbruik_per_ronde"),
            "ronden_in_tank": plan.get("ronden_in_tank"), "stops": plan.get("stops_nodig"),
            "venster": (plan.get("pitvenster_open_ronde"), plan.get("pitvenster_sluit_ronde")),
            "in_pit": me.on_pit, "incidenten": s.incidents,
            "bochten": dict(self.coach.last_lap_deltas),
            "limiet": self.incw.limit,
            "irating": self.extras.ir_est,
            "safety_car": self.extras.in_caution,
            "pits_open": s.pits_open,
            "vlag": self._flag_name(s.flags),
            "weer": self.extras.weather,
            "pitstop_klaar": self.extras.pit_fuel_sent,
            "incident_actief": self.incw.active is not None and self.incw.active.kind == "spin",
        }
