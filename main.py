"""Console-versie (voor testen/foutzoeken). Het gewone programma is app.py / RaceEngineer.exe.

  python main.py            wacht op iRacing
  python main.py --mock     gesimuleerde race
"""
import argparse
import datetime
import os
import time

import settings
from engine import Engine
from inputs import Hotkeys, JoystickWatcher


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--laps", type=int, default=22)
    ap.add_argument("--practice", action="store_true", help="mock: training i.p.v. race")
    ap.add_argument("--text", action="store_true", help="alleen tekst, geen stem")
    ap.add_argument("--no-input", action="store_true", help="geen sneltoetsen/stuurknoppen")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = settings.load(args.config)
    if args.text:
        cfg["voice"]["engine"] = "print"
    logf = open(os.path.join(settings.logs_dir(),
                             f"sessie_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"), "a", encoding="utf-8")
    eng = None

    def log(msg, kind="info"):
        t = eng.state.t if eng and getattr(eng, "state", None) else 0
        prefix = {"radio": "🎧 ", "question": "🎤 ", "debrief": "📋 "}.get(kind, "")
        line = f"{datetime.datetime.now():%H:%M:%S} [{int(t // 60):02d}:{int(t % 60):02d}]  {prefix}{msg}"
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode(), flush=True)
        logf.write(line + "\n")
        logf.flush()

    eng = Engine(cfg, log)
    if not args.no_input:
        Hotkeys(log).apply(cfg["buttons"]["keyboard"], eng.action)
        JoystickWatcher(log).configure(cfg["buttons"]["wheel"], eng.action)
    eng.start(mock=args.mock, speed=args.speed, laps=args.laps, session="Practice" if args.practice else "Race")
    try:
        while eng.running:
            time.sleep(0.2)
    except KeyboardInterrupt:
        eng.stop()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
