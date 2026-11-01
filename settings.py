"""Instellingen en mappen. Alles wordt bewaard in %APPDATA%\\RaceEngineer."""
import copy
import os
import sys

import yaml

APP_NAME = "RaceEngineer"

DEFAULTS = {
    "driver": {"name": ""},
    "voice": {"engine": "edge", "edge_voice": "nl-NL-MaartenNeural", "rate": "+12%", "volume": 1.0},
    "ai": {"enabled": True, "api_key": "", "model": "claude-haiku-5-5",
           "auto_update_every_laps": 5, "debrief_after_race": True},
    "engineer": {"class_only": True, "name_style": "achternaam", "lap_report": True,
                 "gap_report": "smart", "battle_alert_gap": 0.6, "fuel_reports": True,
                 "fuel_margin_laps": 0.6, "pit_loss_seconds": 26, "fuel_fill_rate": 2.4},
    "coach": {"enabled": True, "mode": "auto", "min_loss_practice": 0.08, "min_loss_race": 0.20,
              "max_tips_per_lap_race": 1, "quiet_when_battling": True, "lap_summary": True,
              "save_reference_laps": True, "track_guide": "auto", "track_guide_laps": 5},
    "balance": {"enabled": True, "speak": True, "advice": True, "understeer_ratio": 1.25},
    "buttons": {
        "keyboard": {"race_update": "f9", "strategy": "f10", "gaps": "f11", "ask_question": "f12", "repeat": "f8",
                     "setup_advice": "f7", "rival_compare": "f6",
                     "technique_debrief": "f5"},
        "wheel": {"device_name_contains": "", "race_update": -1, "strategy": -1, "gaps": -1,
                  "ask_question": -1, "repeat": -1, "setup_advice": -1,
                  "rival_compare": -1, "technique_debrief": -1},
    },
    "speech_input": {"enabled": True, "language": "nl-NL", "listen_seconds": 6},
    "race_extras": {"pit_auto": True, "pit_tyres": "auto", "tyre_min_laps": 8, "fast_repair": True,
                    "multiclass": True, "multiclass_warn_s": 3.0, "flags": True, "opponent_info": True,
                    "opponent_inc_warn": 8, "irating": True, "weather": True, "track_temp_step": 3.0},
    "reference": {"enabled": True},
    "technique": {"enabled": True},
    "lesson": {"enabled": True, "start_after_laps": 3, "max_laps": 10},
    "spotter": {"enabled": True, "still_there": True, "still_after": 4.0, "clear_delay": 0.45},
    "rival": {"enabled": True, "every_laps": 3, "min_zone_delta": 0.06},
    "setup": {"enabled": True, "announce": True, "eval_laps": 3},
    "incidents": {"enabled": True, "traffic_warnings": True, "limit_warnings": True},
    "app": {"autostart": True, "second_screen": True, "second_screen_port": 8770},
}


def resource(name):
    """Pad naar een meegeleverd bestand (werkt ook in de .exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def data_dir():
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(root, APP_NAME)
    else:
        d = os.path.join(os.path.expanduser("~"), ".race_engineer")
    os.makedirs(d, exist_ok=True)
    return d


def logs_dir():
    d = os.path.join(data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def ref_dir():
    return os.path.join(data_dir(), "referentie_ronden")


def ref_lib_dir():
    return os.path.join(data_dir(), "referentie_bibliotheek")


def progress_dir():
    return os.path.join(data_dir(), "voortgang")


def config_path():
    return os.path.join(data_dir(), "instellingen.yaml")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    path = path or config_path()
    user = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
        except Exception:
            user = {}
    return _merge(DEFAULTS, user)


def save(cfg, path=None):
    path = path or config_path()
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
