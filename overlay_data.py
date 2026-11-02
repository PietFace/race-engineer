"""Gegevens voor de overlays: relative, stand, sectoren, delta en brandstof.

Wordt ongeveer 10 keer per seconde door de motor opgebouwd. De invoer-grafiek (gas/rem/stuur)
krijgt elke tick een nieuw punt via Engine.input_hist.
"""
from race_state import N_CP

DEFAULT_CLASS_COLORS = ["#33CEFF", "#FFDA59", "#FF5888", "#AE6BFF", "#53FF77"]


def _class_color(car, order):
    if car.class_color and car.class_color.lower() not in ("#000000", "#ffffff"):
        return car.class_color
    try:
        return DEFAULT_CLASS_COLORS[order.index(car.class_id) % len(DEFAULT_CLASS_COLORS)]
    except ValueError:
        return DEFAULT_CLASS_COLORS[0]


def sector_bounds(src):
    """Sector-grenzen als fractie van de ronde, uit iRacing (SplitTimeInfo). Anders 3 gelijke sectoren."""
    try:
        secs = (src["SplitTimeInfo"] or {}).get("Sectors") or []
        starts = sorted(float(s.get("SectorStartPct", 0)) for s in secs)
        if len(starts) >= 2 and starts[0] < 0.01:
            return starts
    except Exception:
        pass
    return [0.0, 1 / 3, 2 / 3]


def sector_times(car, lap, bounds):
    """Sectortijden van een auto in ronde `lap` (telling zoals car.wraps). None waar onbekend."""
    out = []
    edges = [int(round(b * N_CP)) for b in bounds] + [N_CP]
    base = lap * N_CP
    for k in range(len(bounds)):
        a, b = car.time_at(base + edges[k]), car.time_at(base + edges[k + 1])
        out.append(round(b - a, 3) if a is not None and b is not None and b > a else None)
    return out


def build(state, src, coach, strat, eng_finished=False):
    s = state
    me = s.player()
    if not me or me.last_pct is None:
        return None
    L = s.track_len_m or 4000
    est_me = me.class_est_lap or me.best_lap() or me.avg_lap(3) or 90.0
    race = s.is_race()
    racing = race and s.session_state >= 4
    class_order = sorted({c.class_id for c in s.cars.values()})
    est_times = src["CarIdxEstTime"] or []
    cls_pos = src["CarIdxClassPosition"] or []
    surf = src["CarIdxTrackSurface"] or []

    def on_track(c):
        return c.last_pct is not None and c.wraps is not None and not (c.idx < len(surf) and surf[c.idx] == -1)

    # ---------- posities per klasse ----------
    by_class = {}
    for c in s.cars.values():
        if on_track(c) or c.lap_times:
            by_class.setdefault(c.class_id, []).append(c)
    pos_of = {}
    for cid, cars in by_class.items():
        if racing:
            if s.session_state >= 5 and all(c.official_pos for c in cars) and s.cfg["engineer"]["class_only"]:
                cars.sort(key=lambda c: c.official_pos)
            else:
                cars.sort(key=lambda c: -c.progress)
        else:
            def key(c):
                p = cls_pos[c.idx] if c.idx < len(cls_pos) else 0
                if p and p > 0:
                    return (0, p)
                b = c.best_lap()
                return (1, b if b else 1e9)
            cars.sort(key=key)
        for i, c in enumerate(cars):
            pos_of[c.idx] = i + 1

    def row(c):
        return {"idx": c.idx, "pos": pos_of.get(c.idx), "nr": c.number, "naam": c.full_name or c.name,
                "kort": c.name, "klasse": c.class_name, "kleur": _class_color(c, class_order),
                "ir": c.irating, "lic": c.license, "pit": c.on_pit, "jij": c.idx == me.idx,
                "laatste": c.last_lap, "beste": c.best_lap(), "stops": c.pit_stops}

    # ---------- relative ----------
    rel = []
    for c in s.cars.values():
        if not on_track(c):
            continue
        d = ((c.last_pct - me.last_pct + 0.5) % 1.0) - 0.5          # ronde-fractie, + = voor je op de baan
        gap = None
        if c.idx < len(est_times) and me.idx < len(est_times) and est_times[c.idx] and est_times[me.idx] is not None:
            gap = est_times[c.idx] - est_times[me.idx]
            if d > 0 and gap < 0:
                gap += est_me
            elif d < 0 and gap > 0:
                gap -= est_me
        if gap is None or abs(gap) > est_me:
            gap = d * est_me
        r = row(c)
        r["gap"] = 0.0 if c.idx == me.idx else round(gap, 1)
        lapdiff = c.progress - me.progress
        r["ronde"] = 1 if (race and lapdiff > 0.5) else (-1 if (race and lapdiff < -0.5) else 0)
        r["_d"] = d
        rel.append(r)
    rel.sort(key=lambda r: -r["_d"])
    i = next((k for k, r in enumerate(rel) if r["jij"]), 0)
    rel = rel[max(0, i - 4): i + 5]
    for r in rel:
        r.pop("_d", None)

    # ---------- stand ----------
    def gap_to_leader(c, leader):
        if c is leader:
            return 0.0
        if racing:
            laps = int(leader.progress - c.progress)
            if laps >= 1:
                return f"+{laps}R"
            g = s.gap_between(c, leader)
            return round(g, 1) if g is not None else None
        b, lb = c.best_lap(), leader.best_lap()
        return round(b - lb, 3) if b and lb else None

    standings = []
    for cid in sorted(by_class, key=lambda k: (k != me.class_id, class_order.index(k))):
        cars = by_class[cid]
        leader = cars[0]
        rows = []
        for c in cars:
            r = row(c)
            r["gap"] = gap_to_leader(c, leader)
            rows.append(r)
        standings.append({"klasse": leader.class_name or "Klasse", "kleur": _class_color(leader, class_order),
                          "eigen": cid == me.class_id, "auto": rows})

    # ---------- sectoren tegen voor en achter ----------
    bounds = sector_bounds(src)
    mine_cls = by_class.get(me.class_id, [])
    k = mine_cls.index(me) if me in mine_cls else -1
    ahead = mine_cls[k - 1] if k > 0 else None
    behind = mine_cls[k + 1] if 0 <= k < len(mine_cls) - 1 else None
    lap_done = (me.wraps or 0) - 1

    def sect(c, lap):
        return sector_times(c, lap, bounds) if c else None

    def last_lap_of(c):
        # laatste ronde die deze auto helemaal heeft gereden (zelfde telling als car.wraps)
        return (c.wraps or 0) - 1 if c else None

    cur_lap = me.wraps or 0
    sectors = {
        "aantal": len(bounds),
        "jij": {"naam": me.name, "vorige": sect(me, lap_done), "nu": sect(me, cur_lap)},
        "voor": ({"naam": ahead.name, "nr": ahead.number, "vorige": sect(ahead, last_lap_of(ahead)),
                  "nu": sect(ahead, cur_lap if ahead.wraps == cur_lap else ahead.wraps or 0)} if ahead else None),
        "achter": ({"naam": behind.name, "nr": behind.number, "vorige": sect(behind, last_lap_of(behind)),
                    "nu": sect(behind, behind.wraps or 0)} if behind else None),
        "gap_voor": s.gap_between(me, ahead) if ahead else None,
        "gap_achter": s.gap_between(me, behind) if behind else None,
    }
    # beste sectoren van jezelf
    best = [None] * len(bounds)
    for lap_nr, _t, ok in me.lap_times:
        if not ok:
            continue
        st = sector_times(me, lap_nr - 1, bounds)
        for j, x in enumerate(st):
            if x is not None and (best[j] is None or x < best[j]):
                best[j] = x
    sectors["jij"]["beste"] = best

    # ---------- delta ----------
    dn = coach.delta_now() if coach else None
    delta = None
    if dn and coach.ref_time:
        delta = {"delta": round(dn[1], 3), "referentie": coach.ref_time,
                 "voorspelling": round(coach.ref_time + dn[1], 3), "laatste": me.last_lap,
                 "beste": me.best_lap(), "ronde": (me.wraps or 0) + 1}
    elif coach:
        delta = {"delta": None, "referentie": coach.ref_time, "voorspelling": None,
                 "laatste": me.last_lap, "beste": me.best_lap(), "ronde": (me.wraps or 0) + 1}

    # ---------- brandstof ----------
    plan = strat.plan() if strat else {}
    last_used = s.fuel_laps[-1][1] if s.fuel_laps else None
    fuel = {"liter": plan.get("brandstof"), "per_ronde": plan.get("verbruik_per_ronde"),
            "laatste_ronde": round(last_used, 2) if last_used else None,
            "ronden_in_tank": plan.get("ronden_in_tank"), "ronden_te_gaan": plan.get("ronden_te_gaan"),
            "stops": plan.get("stops_nodig"), "tekort": plan.get("tekort_liter"),
            "overschot": plan.get("overschot_liter"),
            "bijtanken": plan.get("bijtanken_als_je_nu_stopt"),
            "venster": (plan.get("pitvenster_open_ronde"), plan.get("pitvenster_sluit_ronde")),
            "doel_zonder_stop": plan.get("doel_verbruik_zonder_stop"),
            "besparen_pct": plan.get("besparing_nodig_pct"), "tank": s.fuel_max,
            "ronde": (me.wraps or 0) + 1}

    return {"relative": rel, "stand": standings, "sectoren": sectors, "delta": delta, "brandstof": fuel,
            "sessie": s.session_type, "race": race, "klaar": eng_finished,
            "ronde": (me.wraps or 0) + 1, "totaal": s.total_laps,
            "tijd_over": s.time_remaining, "positie": pos_of.get(me.idx),
            "deelnemers": len(mine_cls)}
