"""Telemetrie-bron: echte iRacing (via pyirsdk) of een testsimulator.

Beide bronnen gedragen zich hetzelfde: src[naam] geeft een waarde terug,
src.freeze()/src.unfreeze() zorgen voor een consistente momentopname.
"""
import math
import random


class IRacingSource:
    def __init__(self):
        import irsdk  # pip install pyirsdk
        self.ir = irsdk.IRSDK()
        self._started = False

    def check_connection(self):
        if self._started and not (self.ir.is_initialized and self.ir.is_connected):
            self.ir.shutdown()
            self._started = False
        if not self._started:
            self._started = bool(self.ir.startup())
        return self._started and self.ir.is_initialized and self.ir.is_connected

    def freeze(self):
        self.ir.freeze_var_buffer_latest()

    def unfreeze(self):
        self.ir.unfreeze_var_buffer_latest()

    def __getitem__(self, key):
        try:
            return self.ir[key]
        except Exception:
            return None

    @property
    def session_info_update(self):
        try:
            return self.ir.session_info_update
        except Exception:
            return 0

    def advance(self, dt):
        pass  # echte tijd

    def pit_command(self, mode, var=0):
        """Pitcommando naar iRacing (brandstof, banden, fast repair)."""
        try:
            self.ir.pit_command(mode, int(var))
            return True
        except Exception:
            return False


# ----------------------------------------------------------------------
#  Testsimulator: multiclass-race (12x GT3 + 3x GTP) met brandstof, pitstops,
#  spins, een safety car, regen, onder/overstuur en gevechten.
# ----------------------------------------------------------------------
TRACK_LEN = 4100.0
VMAX = 74.0  # m/s (~266 km/u)
# (apex in m, minimumsnelheid m/s, remzone m, accelereer-zone m, richting +1 links / -1 rechts)
CORNERS = [
    (420, 22.0, 150, 260, 1),
    (980, 38.0, 110, 220, -1),
    (1500, 30.0, 130, 240, 1),
    (2150, 47.0, 90, 200, 1),
    (2650, 19.0, 170, 280, -1),
    (3300, 33.0, 120, 230, -1),
    (3820, 41.0, 100, 210, 1),
]
NAMES = ["Max de Boer", "Lars Jansen", "Tom Visser", "Sven Bakker", "Jeroen Smit",
         "Kevin Mulder", "Niels de Vries", "Ruben Meijer", "Daan Bos", "Bas Kok",
         "Jij Zelf", "Pim van Dijk", "Anna Brouwer", "Joost Dekker", "Eva Hendriks"]
IRATINGS = [3450, 3200, 2950, 2800, 2650, 2500, 2400, 2300, 2150, 2050, 2200, 1900, 4100, 3600, 3300]
PLAYER = 10
GTP = (12, 13, 14)
WHEELBASE_RATIO = 15.0 * 2.7   # stuurverhouding x wielbasis


def _profile(d, var=None):
    """Snelheid, rem, gas, bochtfactor (0..1), bocht-index en fase op afstand d."""
    v, brake, thr, w, ci, phase = VMAX, 0.0, 1.0, 0.0, None, None
    for i, (apex, vmin, blen, alen, _dir) in enumerate(CORNERS):
        vv = var[i] if var else (0.0, 0.0, 0.0)
        boff, voff, aoff = vv[0], vv[1], vv[2]
        early = vv[3] if len(vv) > 3 else 0.0      # rem zoveel meter te vroeg los (geen trail braking)
        vm = vmin + voff - early * 0.02
        bl = blen - boff  # positieve boff = later remmen
        al = alen + aoff
        for a in (apex - TRACK_LEN, apex, apex + TRACK_LEN):
            x = d - a
            if -bl < x <= 0:
                f = -x / bl
                vc = vm + (VMAX - vm) * f ** 0.8
                if vc < v:
                    v, brake, thr = vc, (0.0 if early and x > -early else 0.25 + 0.7 * f), 0.0
                    w, ci, phase = max(0.0, 1 - f * 1.6), i, "in"
            elif 0 < x < al:
                f = x / al
                vc = vm + (VMAX - vm) * f ** 1.1
                if vc < v:
                    v, brake, thr = vc, 0.0, min(1.0, 0.25 + f * 1.2)
                    w, ci, phase = max(0.0, 1 - f * 1.5), i, "out"
    return v, brake, thr, w, ci, phase


GEAR_EDGES = [0, 20, 30, 40, 52, 63, 80]


def _rpm(v, g):
    g = max(1, min(6, g or 1))
    lo, hi = GEAR_EDGES[g - 1], GEAR_EDGES[g]
    return 3500 + 4000 * max(0.0, min(1.0, (v - lo) / (hi - lo)))


def _gear(v):
    return 1 if v < 20 else 2 if v < 30 else 3 if v < 40 else 4 if v < 52 else 5 if v < 63 else 6


class _Car:
    def __init__(self, idx, pace, start_dist):
        self.idx = idx
        self.pace = pace
        self.dist = start_dist  # totale afstand (meters, kan negatief zijn op de grid)
        self.fuel = 52.0
        self.fpl = 2.95 + random.uniform(-0.1, 0.1)
        self.pit_timer = 0.0
        self.pit_lap = random.choice([10, 11, 12, 13])
        self.pitted = False
        self.last_lap = -1.0
        self.best_lap = -1.0
        self.lap_start = 0.0
        self.var = None
        self.on_pit = False
        self.done = False
        self.cls = 2 if idx in GTP else 1

    @property
    def lap(self):
        return int(math.floor(self.dist / TRACK_LEN))

    @property
    def pct(self):
        return (self.dist % TRACK_LEN) / TRACK_LEN


class MockSource:
    def __init__(self, race_laps=22, seed=7, session="Race"):
        random.seed(seed)
        self.t = 0.0
        self.race_laps = race_laps
        self.session = session
        self.practice = session != "Race"
        paces = [1.012, 1.008, 1.006, 1.004, 1.0035, 1.003, 1.0015, 1.001, 0.996, 0.994, 1.0, 1.0045,
                 1.10, 1.095, 1.09]
        self.cars = []
        for i in range(len(NAMES)):
            grid = -(i * 14.0) - 5
            if i in GTP:  # GTP's starten achteraan (aparte startgroep)
                grid = -(15 + (i - 12)) * 14.0 - 5
            self.cars.append(_Car(i, paces[i], grid))
        self.cars[PLAYER].dist = -(10 * 14.0) - 5
        self.cars[PLAYER].pit_lap = 12
        self.cars[PLAYER].fuel = 40.0
        self.cars[PLAYER].fpl = 2.9
        self._new_lap_var(self.cars[PLAYER])
        # eigen rijstijl voor een paar tegenstanders (voor de vergelijking per bocht)
        z = (0.0, 0.0, 0.0)
        self.cars[8].var = [z, z, z, z, (6, 2.5, -15), (6, 2.0, -10), z]          # Bos: sterk in bocht 5 en 6
        self.cars[11].var = [z, (0, 1.5, -25), (4, 1.5, -20), z, (-6, -1.5, 15), z, z]   # Van Dijk: sterk in 2 en 3
        self.cars[9].var = [(5, 2.0, -10), z, z, z, z, z, (-5, -1.5, 10)]        # Kok: sterk in bocht 1
        self.speed = self.brake = 0.0
        self.throttle = 1.0
        self.gear = 1
        self.steer = self.lat = 0.0
        self.finished = False
        self.checkered = False
        self.finish_order = []
        self.session_info_update = 1
        self.incidents = 0
        self.scenarios = {(4, 4): "spin", (6, 2): "off", (8, 4): "spin"}
        self.done_scen = set()
        self.ev = None
        self.yaw = 0.0
        self.vx = self.vy = 0.0
        self.surface = 3
        self.flags = 0x0004
        self.pits_open = True
        self.caution = None       # fase van de safety car
        self.track_temp = 38.0
        self.precip = 0.0
        self.wetness = 1
        self.pit_fuel_req = 0.0
        self.pit_tyres = True
        self.pit_cmds = []
        self.driver_inc = {i: 0 for i in range(len(NAMES))}
        self.driver_inc[1] = 9    # Jansen is een brokkenpiloot
        self._cache_t = None
        self._cache = {}
        self.setup = {
            "UpdateCount": 1,
            "TiresAero": {"LeftFront": {"StartingPressure": "165.5 kPa", "LastHotPressure": "172.0 kPa", "TreadRemaining": "100%"},
                          "AeroBalanceCalc": {"FrontRhAtSpeed": "52.0 mm"}, "RearWing": {"WingSetting": "7"}},
            "Chassis": {"Front": {"ArbBlades": "4", "BrakePressureBias": "54.0%", "CrossWeight": "50.0%"},
                        "Rear": {"ArbBlades": "3", "RideHeight": "68.0 mm"},
                        "InCarDials": {"TractionControlSetting": "4 (TC)", "AbsSetting": "6 (ABS)"}},
        }
        self.setup_changed = False

    def _new_lap_var(self, car):
        car.var = [(random.gauss(0, 7), random.gauss(0, 1.0), random.gauss(0, 12)) for _ in CORNERS]
        if car.idx == PLAYER:
            # bocht 5: laat de rem vaak te vroeg los; dat wordt beter naarmate je meer ronden rijdt
            p_early = max(0.1, 0.9 - 0.1 * max(0, car.lap))
            if random.random() < p_early:
                b, vo, a = car.var[4]
                car.var[4] = (b, vo, a, 35.0)

    def check_connection(self):
        return True

    def freeze(self):
        pass

    def unfreeze(self):
        pass

    def pit_command(self, mode, var=0):
        """Zoals irsdk: 2 = brandstof (liter), 7 = banden wissen, 3-6 = banden, 11 = brandstof wissen."""
        self.pit_cmds.append((mode, var))
        if mode == 2:
            self.pit_fuel_req = float(var)
        elif mode == 11:
            self.pit_fuel_req = 0.0
        elif mode == 7:
            self.pit_tyres = False
        elif mode in (3, 4, 5, 6):
            self.pit_tyres = True
        return True

    # ------------------------------------------------------------
    def _leader(self):
        return max(self.cars, key=lambda c: c.dist)

    def _race_control(self, dt):
        lead = self._leader()
        if self.practice:
            self.track_temp -= 0.006 * dt
            return
        lp = lead.dist / TRACK_LEN
        # safety car van leider-ronde 9,0 tot 10,6
        if self.caution is None and lp >= 9.0 and lp < 9.1:
            self.caution = {"t": 0.0}
        if self.caution is not None and self.caution != "done":
            self.caution["t"] += dt
            ct = self.caution["t"]
            self.pits_open = ct > 45
            self.flags = 0x4000 | (0x8000 if ct < 12 else 0)
            if lp >= 10.2:
                self.flags |= 0x0200    # nog één ronde tot groen
            if lp >= 10.6:
                self.caution = "done"
                self.flags = 0x0004
                self.pits_open = True
        # weer: baan koelt af, regen vanaf leider-ronde 15
        self.track_temp -= 0.006 * dt
        if lp > 15:
            self.precip = min(0.6, self.precip + 0.004 * dt)
            self.wetness = 1 if self.precip < 0.1 else (3 if self.precip < 0.3 else 4)

    def advance(self, dt):
        self.t += dt
        if self.t < 3.0:
            return
        self._race_control(dt)
        if int(self.t * 10) % 100 == 0:
            self.session_info_update += 1   # iRacing ververst sessie-info af en toe
        slow = 0.55 if isinstance(self.caution, dict) else 1.0
        for car in self.cars:
            if car.done:
                continue
            old_lap = car.lap
            if car.pit_timer > 0:
                car.pit_timer -= dt
                car.on_pit = True
                if car.pit_timer <= 0:
                    if car.idx == PLAYER and self.pit_fuel_req > 0:
                        car.fuel = min(60.0, car.fuel + self.pit_fuel_req)
                    else:
                        car.fuel = 60.0
                    car.on_pit = False
                if car.idx == PLAYER:
                    self.speed, self.brake, self.throttle, self.gear = 0.0, 1.0, 0.0, 1
                continue
            d = car.dist % TRACK_LEN
            if car.idx == PLAYER and self._player_event(car, d, dt):
                continue
            v, b, th, w, ci, phase = _profile(d, car.var)
            v *= car.pace * slow
            if car.dist < 0:
                v = min(v, 35.0)
            car.dist += v * dt
            car.v = v
            car.fuel -= car.fpl * (v * dt) / TRACK_LEN
            if car.idx == PLAYER:
                self.speed, self.brake, self.throttle = v, b, th
                self.gear = 1 if v < 20 else 2 if v < 30 else 3 if v < 40 else 4 if v < 52 else 5 if v < 63 else 6
                self._balance(v, w, ci, phase)
            if car.lap != old_lap:
                if car.lap >= 1:
                    lt = self.t - car.lap_start
                    if old_lap >= 0:
                        car.last_lap = lt
                        if car.best_lap < 0 or lt < car.best_lap:
                            car.best_lap = lt
                car.lap_start = self.t
                if car.idx == PLAYER:
                    self._new_lap_var(car)
                if self.practice:
                    if car.idx == PLAYER and car.lap >= self.race_laps:
                        self.finished = True
                    if car.idx == PLAYER and car.lap == 5 and not self.setup_changed:
                        self.setup_changed = True
                        self.setup["Chassis"]["Front"]["ArbBlades"] = "3"
                        self.setup["Chassis"]["Front"]["BrakePressureBias"] = "53.5%"
                        self.setup["UpdateCount"] = 2
                        self.session_info_update += 1
                    continue
                if self.checkered or car.lap >= self.race_laps:
                    self.checkered = True
                    car.done = True
                    self.finish_order.append(car.idx)
                    car.dist += 30
                    if car.idx == PLAYER:
                        self.finished = True
                    continue
                if car.lap == car.pit_lap and not car.pitted:
                    car.pitted = True
                    car.pit_timer = 24.0 + random.uniform(-1, 1)

    def _balance(self, v, w, ci, phase):
        """Stuurhoek/dwarsversnelling/yaw met ingebouwd onderstuur (bocht 5 ingang)
        en overstuur (bocht 2 uitgang)."""
        if ci is None or w <= 0.02 or v < 5:
            self.steer, self.lat, self.yaw, self.vx, self.vy, self.surface = 0.0, 0.0, 0.0, v, 0.0, 3
            return
        direction = CORNERS[ci][4]
        lat = 16.0 * w
        yaw = lat / v
        steer = WHEELBASE_RATIO * yaw / v * (1 + 0.0035 * lat)   # klein beetje natuurlijk onderstuur
        if ci == 4 and phase == "in" and not self.setup_changed:
            steer *= 1.5           # onderstuur bij insturen bocht 5 (weg na setup-wijziging)
        if ci == 1 and phase == "out" and w > 0.2:
            steer = -0.25 * steer  # tegensturen: overstuur uitgang bocht 2
            yaw *= 1.2
        self.steer, self.lat, self.yaw = steer * direction, lat * direction, yaw * direction
        self.vx, self.vy, self.surface = v, 0.3 * direction, 3

    def _player_event(self, car, d, dt):
        """Speelt een spin of een uitstapje af. True = auto is deze tick afgehandeld."""
        if self.ev is None:
            for (lap, ci), kind in self.scenarios.items():
                apex = CORNERS[ci][0]
                if car.lap == lap and (lap, ci) not in self.done_scen and apex - 25 < d < apex:
                    self.done_scen.add((lap, ci))
                    self.ev = {"kind": kind, "t": 0.0, "v": self.speed, "ang": 0.0}
                    self.incidents += 2 if kind == "spin" else 1
                    break
            if self.ev is None:
                return False
        ev = self.ev
        ev["t"] += dt
        t = ev["t"]
        self.steer = self.lat = 0.0
        if ev["kind"] == "off":
            if t > 1.8:
                self.ev = None
                return False
            v = max(20.0, ev["v"] * 0.9)
            car.dist += v * dt
            self.speed, self.brake, self.throttle = v, 0.0, 0.3
            self.yaw, self.vx, self.vy, self.surface = 0.2, v, 1.0, 0
            return True
        if t < 2.0:
            ev["v"] = max(0.0, ev["v"] - 15 * dt)
            ev["ang"] += 3.0 * dt
            v = ev["v"]
            car.dist += v * dt * 0.6
            self.speed, self.brake, self.throttle = v, 1.0, 0.0
            self.yaw, self.vx, self.vy, self.surface = 3.0, v * math.cos(ev["ang"]), v * math.sin(ev["ang"]), 0
        elif t < 8.0:
            self.speed, self.brake, self.throttle = 0.0, 1.0, 0.0
            self.yaw, self.vx, self.vy, self.surface = 0.0, 0.0, 0.0, 0
        else:
            target = _profile(d)[0]
            ev["v"] = min(target, ev["v"] + 9 * dt)
            v = ev["v"]
            car.dist += v * dt
            self.speed, self.brake, self.throttle = v, 0.0, 1.0
            self.yaw, self.vx, self.vy, self.surface = 0.05, v, 0.0, 0 if t < 10.0 else 3
            if v >= target - 0.5 and t > 10.0:
                self.ev = None
        car.fuel -= car.fpl * (self.speed * dt) / TRACK_LEN
        return True

    # ---------- variabelen zoals iRacing ze geeft ----------
    def _build(self):
        p = self.cars[PLAYER]
        fin = {idx: i for i, idx in enumerate(self.finish_order)}

        def key(c):
            # meeste voltooide ronden eerst; bij gelijke ronden ligt wie nog rijdt (verder op de baan) voor
            return (-c.lap, 1, fin[c.idx]) if c.idx in fin else (-c.lap, 0, -c.dist)
        order = sorted(self.cars, key=key)
        pos = {c.idx: i + 1 for i, c in enumerate(order)}
        cpos = {}
        for cls in (1, 2):
            for i, c in enumerate([c for c in order if c.cls == cls]):
                cpos[c.idx] = i + 1
        lead = self._leader()
        left = right = 0
        if not p.on_pit and self.speed > 8:
            for c in self.cars:
                if c.idx == PLAYER or c.on_pit or c.done:
                    continue
                if abs(c.dist - p.dist) < 5.5:
                    if c.idx % 2 == 0:
                        left += 1
                    else:
                        right += 1
        if left and right:
            clr = 4
        elif left:
            clr = 5 if left > 1 else 2
        elif right:
            clr = 6 if right > 1 else 3
        else:
            clr = 1
        return {
            "CarLeftRight": clr,
            "SessionTime": self.t,
            "SessionNum": 0,
            "SessionState": 5 if self.checkered else (4 if self.t >= 3 else 3),
            "_dummy": 0,
            "SessionFlags": self.flags,
            "SessionLapsRemainEx": max(0, self.race_laps - max(0, lead.lap)),
            "SessionTimeRemain": 604800.0,
            "PlayerCarIdx": PLAYER,
            "Speed": self.speed,
            "Throttle": self.throttle,
            "BrakeABSactive": self.brake > 0.92,
            "RPM": _rpm(self.speed, self.gear),
            "SteeringWheelPctTorque": min(1.0, abs(self.steer) * 2.2),
            "Brake": self.brake,
            "Gear": self.gear,
            "SteeringWheelAngle": self.steer,
            "LatAccel": self.lat,
            "LapDist": p.dist % TRACK_LEN,
            "LapDistPct": p.pct,
            "Lap": p.lap + 1,
            "LapCompleted": p.lap,
            "LapLastLapTime": p.last_lap,
            "LapBestLapTime": p.best_lap,
            "FuelLevel": p.fuel,
            "OnPitRoad": p.on_pit,
            "PitsOpen": self.pits_open,
            "PitSvFuel": self.pit_fuel_req,
            "PitSvFlags": 0x0F if self.pit_tyres else 0,
            "IsOnTrack": True,
            "PlayerTrackSurface": self.surface,
            "YawRate": self.yaw,
            "VelocityX": self.vx,
            "VelocityY": self.vy,
            "PlayerCarMyIncidentCount": self.incidents,
            "TrackTempCrew": self.track_temp,
            "AirTemp": 21.0,
            "Precipitation": self.precip,
            "TrackWetness": self.wetness,
            "WeatherDeclaredWet": self.wetness >= 4,
            "CarIdxLapDistPct": [c.pct for c in self.cars],
            "CarIdxLap": [c.lap + 1 for c in self.cars],
            "CarIdxLapCompleted": [c.lap for c in self.cars],
            "CarIdxPosition": [pos[c.idx] for c in self.cars],
            "CarIdxClassPosition": [cpos[c.idx] for c in self.cars],
            "CarIdxOnPitRoad": [c.on_pit for c in self.cars],
            "CarIdxLastLapTime": [c.last_lap for c in self.cars],
            "CarIdxBestLapTime": [c.best_lap for c in self.cars],
            "CarIdxTrackSurface": [1 if c.on_pit else 3 for c in self.cars],
            "CarIdxClass": [c.cls for c in self.cars],
            "CarIdxGear": [_gear(getattr(c, "v", 0) or 0) for c in self.cars],
            "CarIdxSteer": [0.0 for _ in self.cars],
        }

    def __getitem__(self, key):
        if self._cache_t != self.t:
            self._cache = self._build()
            self._cache_t = self.t
        if key in self._cache:
            return self._cache[key]
        if key == "DriverInfo":
            return {
                "DriverCarIdx": PLAYER,
                "DriverCarFuelMaxLtr": 60.0,
                "DriverCarSLShiftRPM": 7300.0,
                "Drivers": [{"CarIdx": i, "UserName": n, "CarNumber": str(i * 7 + 3),
                             "CarClassID": 2 if i in GTP else 1,
                             "CarClassShortName": "GTP" if i in GTP else "GT3",
                             "CarClassEstLapTime": 66.0 if i in GTP else 73.5,
                             "CarScreenNameShort": "Porsche 963 GTP" if i in GTP else ("Ferrari 296 GT3" if i in (1, 3, 5) else "McLaren 720S GT3 EVO"),
                             "IRating": IRATINGS[i], "LicString": "A 4.12" if IRATINGS[i] > 3000 else "B 3.20",
                             "CurDriverIncidentCount": self.driver_inc[i],
                             "CarIsPaceCar": 0, "IsSpectator": 0} for i, n in enumerate(NAMES)],
            }
        if key == "CarSetup":
            return self.setup
        if key == "WeekendInfo":
            return {"TrackDisplayName": "Testbaan", "TrackLength": f"{TRACK_LEN/1000:.2f} km",
                    "WeekendOptions": {"IncidentLimit": "17"}}
        if key == "SessionInfo":
            return {"Sessions": [{"SessionNum": 0, "SessionType": self.session,
                                  "SessionLaps": str(self.race_laps), "SessionTime": "unlimited"}]}
        return None
