"""AI Race Engineer - programmavenster."""
import datetime
import os
import queue
import sys
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

import settings
from engine import Engine
from inputs import ACTION_LABELS, ACTIONS, Hotkeys, JoystickWatcher
from race_state import fmt_lap

from version import VERSION

C = {
    "bg": "#0F1216", "side": "#0B0D10", "card": "#171B21", "card2": "#1E232B", "line": "#262C35",
    "text": "#E8EAED", "muted": "#8A94A6", "accent": "#FF8A00", "accent2": "#FFB054",
    "good": "#3DDC84", "bad": "#FF5A5F", "info": "#5AB0FF",
}

QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', sans-serif; color: {C['text']}; }}
QMainWindow, #page {{ background: {C['bg']}; }}
#side {{ background: {C['side']}; border-right: 1px solid {C['line']}; }}
#brand {{ font-size: 17px; font-weight: 700; }}
#brandsub {{ color: {C['muted']}; font-size: 11px; }}
QPushButton#nav {{ text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
    font-size: 14px; color: {C['muted']}; background: transparent; }}
QPushButton#nav:hover {{ background: {C['card']}; color: {C['text']}; }}
QPushButton#nav:checked {{ background: {C['card2']}; color: {C['text']}; border-left: 3px solid {C['accent']}; }}
#card {{ background: {C['card']}; border: 1px solid {C['line']}; border-radius: 12px; }}
#cap {{ color: {C['muted']}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
#big {{ font-size: 34px; font-weight: 700; }}
#mid {{ font-size: 20px; font-weight: 600; }}
#sub {{ color: {C['muted']}; font-size: 12px; }}
#h1 {{ font-size: 22px; font-weight: 700; }}
QPushButton {{ background: {C['card2']}; border: 1px solid {C['line']}; border-radius: 8px;
    padding: 8px 14px; font-size: 13px; }}
QPushButton:hover {{ border-color: {C['accent']}; }}
QPushButton:disabled {{ color: #555c66; border-color: {C['line']}; }}
QPushButton#primary {{ background: {C['accent']}; color: #15100A; font-weight: 700; border: none; padding: 10px 22px; font-size: 14px; }}
QPushButton#primary:hover {{ background: {C['accent2']}; }}
QPushButton#danger {{ background: transparent; border: 1px solid {C['bad']}; color: {C['bad']}; font-weight: 600; padding: 10px 18px; }}
QTextEdit {{ background: {C['card']}; border: 1px solid {C['line']}; border-radius: 12px; padding: 8px; font-size: 13px; }}
QGroupBox {{ background: {C['card']}; border: 1px solid {C['line']}; border-radius: 12px; margin-top: 22px; padding: 16px 14px 12px 14px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 4px; top: 0px; color: {C['accent2']}; font-size: 13px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {C['bg']}; border: 1px solid {C['line']}; border-radius: 6px; padding: 5px 8px; min-height: 20px; }}
QComboBox QAbstractItemView {{ background: {C['card2']}; selection-background-color: {C['accent']}; selection-color: #000; }}
QCheckBox {{ spacing: 8px; }}
QProgressBar {{ background: {C['bg']}; border: none; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {C['line']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {C['accent']}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['line']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A424E; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ height: 0; background: none; }}
#chip {{ background: {C['bg']}; border: 1px solid {C['line']}; border-radius: 6px; padding: 4px 8px; font-size: 12px; }}
#banner {{ background: #2A2112; border: 1px solid #5C4313; border-radius: 10px; color: {C['accent2']}; padding: 8px 12px; }}
"""


def sec(x, d=1):
    return f"{abs(x):.{d}f}".replace(".", ",")


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def lab(text="", name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


# ======================================================================
class StatTile(QFrame):
    def __init__(self, caption):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        v.addWidget(lab(caption.upper(), "cap"))
        self.value = lab("–", "big")
        self.sub = lab("", "sub")
        v.addWidget(self.value)
        v.addWidget(self.sub)

    def set(self, value, sub="", color=None):
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color: {color};" if color else "")


class RivalCard(QFrame):
    def __init__(self, caption):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(4)
        v.addWidget(lab(caption.upper(), "cap"))
        row = QHBoxLayout()
        self.name = lab("–", "mid")
        self.gap = lab("", "big")
        row.addWidget(self.name, 1)
        row.addWidget(self.gap, 0, Qt.AlignRight)
        v.addLayout(row)
        self.trend = lab("", "sub")
        v.addWidget(self.trend)

    def set(self, d, ahead):
        if not d:
            self.name.setText("–")
            self.gap.setText("")
            self.trend.setText("Niemand" if ahead else "Niemand")
            return
        self.name.setText(d["naam"] + (f"  #{d['nr']}" if d.get("nr") else ""))
        g = d.get("gap")
        self.gap.setText(f"{sec(g)} s" if g is not None else "…")
        tr = d.get("trend")
        txt, col = "", C["muted"]
        if d.get("pit"):
            txt, col = "in de pits", C["info"]
        elif tr is not None and abs(tr) >= 0.05:
            if ahead:
                txt, col = (f"je pakt {sec(tr)} s per ronde", C["good"]) if tr < 0 else (f"loopt {sec(tr)} s per ronde weg", C["bad"])
            else:
                txt, col = (f"komt {sec(tr)} s per ronde dichterbij", C["bad"]) if tr > 0 else (f"je loopt {sec(tr)} s per ronde weg", C["good"])
        elif d.get("laatste"):
            txt = f"laatste ronde {fmt_lap(d['laatste'])}"
        self.trend.setText(txt)
        self.trend.setStyleSheet(f"color: {col};")
        close = g is not None and abs(g) < 1.0
        self.gap.setStyleSheet(f"color: {C['bad'] if close and not ahead else (C['good'] if close else C['text'])};")


# ======================================================================
class RacePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # kop
        top = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.title = lab("Klaar om te racen", "h1")
        self.subtitle = lab("Start de engineer en stap in iRacing in je auto.", "sub")
        tv.addWidget(self.title)
        tv.addWidget(self.subtitle)
        top.addLayout(tv, 1)
        self.btn_test = QPushButton("Testrace")
        self.btn_test.setToolTip("Een gesimuleerde race, zonder iRacing")
        self.btn_test_p = QPushButton("Testtraining")
        self.btn_test_p.setToolTip("Een gesimuleerde training op een nieuwe baan, zonder iRacing")
        self.btn_start = QPushButton("Start engineer")
        self.btn_start.setObjectName("primary")
        top.addWidget(self.btn_test_p)
        top.addWidget(self.btn_test)
        top.addWidget(self.btn_start)
        root.addLayout(top)

        self.banner = lab("", "banner", wrap=True)
        self.banner.hide()
        root.addWidget(self.banner)
        self.flagbar = lab("", None)
        self.flagbar.setAlignment(Qt.AlignCenter)
        self.flagbar.hide()
        root.addWidget(self.flagbar)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        # links: dashboard
        dash = QVBoxLayout()
        dash.setSpacing(12)
        tiles = QGridLayout()
        tiles.setSpacing(12)
        self.t_pos = StatTile("Positie")
        self.t_lap = StatTile("Ronde")
        self.t_last = StatTile("Laatste ronde")
        self.t_best = StatTile("Beste ronde")
        for i, t in enumerate([self.t_pos, self.t_lap, self.t_last, self.t_best]):
            tiles.addWidget(t, 0, i)
        dash.addLayout(tiles)

        rivals = QHBoxLayout()
        rivals.setSpacing(12)
        self.c_ahead = RivalCard("Voor je")
        self.c_behind = RivalCard("Achter je")
        rivals.addWidget(self.c_ahead)
        rivals.addWidget(self.c_behind)
        dash.addLayout(rivals)

        fuel = card()
        fv = QVBoxLayout(fuel)
        fv.setContentsMargins(16, 12, 16, 14)
        fv.setSpacing(6)
        fv.addWidget(lab("BRANDSTOF & STRATEGIE", "cap"))
        fr = QHBoxLayout()
        self.f_main = lab("–", "mid")
        self.f_side = lab("", "sub")
        fr.addWidget(self.f_main, 1)
        fr.addWidget(self.f_side, 0, Qt.AlignRight)
        fv.addLayout(fr)
        self.f_bar = QProgressBar()
        self.f_bar.setTextVisible(False)
        self.f_bar.setRange(0, 100)
        self.f_bar.setFixedHeight(8)
        fv.addWidget(self.f_bar)
        self.f_plan = lab("", "sub", wrap=True)
        fv.addWidget(self.f_plan)
        dash.addWidget(fuel)

        coachc = card()
        cv = QVBoxLayout(coachc)
        cv.setContentsMargins(16, 12, 16, 14)
        cv.setSpacing(8)
        cv.addWidget(lab("COACHING · LAATSTE RONDE PER BOCHT T.O.V. JE BESTE", "cap"))
        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        self.chips = []
        cv.addLayout(self.chips_row)
        self.coach_hint = lab("Na je eerste schone ronde zie je hier per bocht waar je tijd wint of verliest.", "sub", wrap=True)
        cv.addWidget(self.coach_hint)
        dash.addWidget(coachc)

        acts = QGridLayout()
        acts.setSpacing(8)
        self.act_buttons = {}
        for k, a in enumerate(ACTIONS):
            b = QPushButton(ACTION_LABELS[a])
            b.clicked.connect(lambda _=False, x=a: self.win.engine.action(x))
            acts.addWidget(b, k // 3, k % 3)
            self.act_buttons[a] = b
        dash.addLayout(acts)
        dash.addStretch(1)
        body.addLayout(dash, 3)

        # rechts: radio
        rv = QVBoxLayout()
        rv.setSpacing(6)
        rv.addWidget(lab("BOORDRADIO", "cap"))
        self.radio = QTextEdit()
        self.radio.setReadOnly(True)
        self.radio.setMinimumWidth(330)
        rv.addWidget(self.radio, 1)
        body.addLayout(rv, 2)

    def refresh_keys(self, cfg):
        keys = cfg["buttons"]["keyboard"]
        for a, b in self.act_buttons.items():
            k = keys.get(a)
            b.setText(ACTION_LABELS[a] + (f"  ({k.upper()})" if k else ""))

    def add_radio(self, text, kind):
        ts = datetime.datetime.now().strftime("%H:%M")
        if kind == "radio":
            html = f'<div style="margin:4px 0"><span style="color:{C["muted"]}">{ts}</span>&nbsp; <b style="color:{C["accent2"]}">ENGINEER</b>&nbsp; {text}</div>'
        elif kind == "question":
            html = f'<div style="margin:4px 0"><span style="color:{C["muted"]}">{ts}</span>&nbsp; <b style="color:{C["info"]}">JIJ</b>&nbsp; {text}</div>'
        elif kind == "debrief":
            body = text.replace("\n", "<br>")
            html = f'<div style="margin:8px 0; padding:8px; background:{C["card2"]}"><b style="color:{C["accent2"]}">NABESPREKING</b><br>{body}</div>'
        else:
            html = f'<div style="margin:2px 0; color:{C["muted"]}; font-size:12px">{ts}&nbsp; {text}</div>'
        self.radio.append(html)
        self.radio.moveCursor(QTextCursor.End)

    def update_status(self, st, engine):
        running = engine.running
        self.btn_start.setText("Stop" if running else "Start engineer")
        self.btn_start.setObjectName("danger" if running else "primary")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)
        self.btn_test.setEnabled(not running)
        self.btn_test_p.setEnabled(not running)
        for b in self.act_buttons.values():
            b.setEnabled(running and bool(st.get("positie")))

        if not running:
            self.title.setText("Klaar om te racen")
            self.subtitle.setText("Start de engineer en stap in iRacing in je auto.")
        elif not st:
            self.title.setText("Wachten op iRacing…")
            self.subtitle.setText("Start een sessie en stap in de auto. De engineer meldt zich vanzelf.")
        else:
            sess = st.get("sessie") or "Sessie"
            self.title.setText(f"{sess} · {st.get('baan') or ''}")
            sub = st.get("auto") or ("Testrace" if engine.mock else "")
            w = st.get("weer") or {}
            if w.get("baantemp") is not None:
                sub += f"   ·   baan {round(w['baantemp'])}°"
            if w.get("baan"):
                sub += f" · {w['baan']}"
            self.subtitle.setText(sub)
        self._flag(st.get("vlag") if running else None, st)

        if not st.get("positie"):
            for t in (self.t_pos, self.t_lap, self.t_last, self.t_best):
                t.set("–")
            self.c_ahead.set(None, True)
            self.c_behind.set(None, False)
            self.f_main.setText("–")
            self.f_side.setText("")
            self.f_plan.setText("")
            self.f_bar.setValue(0)
            self._update_chips({})
            return
        inc = st.get("incidenten") or 0
        lim = st.get("limiet")
        inc_txt = f"  ·  {inc}x" + (f" / {lim}" if lim else "")
        ir = st.get("irating")
        if ir is not None and st.get("sessie", "").lower().startswith("race"):
            inc_txt += f"  ·  {'+' if ir >= 0 else '−'}{abs(round(ir))} iR"
        self.t_pos.set(f"P{st['positie']}", f"van {st['deelnemers']}{inc_txt}")
        self.title.setText(self.title.text() + ("   ⚠ SPIN" if st.get("incident_actief") else ""))
        tot = st.get("totaal")
        left = st.get("ronden_te_gaan")
        self.t_lap.set(f"{st['ronde']}" + (f" / {tot}" if tot else ""),
                       f"nog {round(left)} ronden" if left is not None else "")
        last, best = st.get("laatste"), st.get("beste")
        if last:
            d = last - best if best else None
            col = C["good"] if d is not None and d <= 0.001 else None
            self.t_last.set(fmt_lap(last), (f"+{sec(d, 2)} t.o.v. beste" if d and d > 0.001 else "beste ronde!") if d is not None else "", col)
        self.t_best.set(fmt_lap(best) if best else "–", "")
        self.c_ahead.set(st.get("voor"), True)
        self.c_behind.set(st.get("achter"), False)

        fuel, fpl, tank = st.get("brandstof"), st.get("verbruik"), st.get("ronden_in_tank")
        if fuel is not None:
            self.f_main.setText(f"{sec(fuel)} liter" + (f"  ·  {sec(tank)} ronden" if tank is not None else ""))
            self.f_side.setText(f"{sec(fpl, 2)} L per ronde" if fpl else "verbruik meten…")
            cap = engine.state.fuel_max if getattr(engine, "state", None) and engine.state.fuel_max else 100
            self.f_bar.setValue(int(max(0, min(100, fuel / cap * 100))))
        self._update_chips(st.get("bochten") or {})
        stops = st.get("stops")
        op, cl = st.get("venster") or (None, None)
        if stops == 0:
            self.f_plan.setText("Je haalt de finish zonder stop.")
        elif stops:
            self.f_plan.setText(f"{stops} stop nodig · pitvenster ronde {op} – {cl}")
        else:
            self.f_plan.setText("")

    def _update_chips(self, deltas):
        keys = sorted(deltas)
        while len(self.chips) < len(keys):
            c = lab("", "chip")
            self.chips_row.addWidget(c)
            self.chips.append(c)
        for i, c in enumerate(self.chips):
            if i < len(keys):
                k = keys[i]
                d = deltas[k]
                col = C["good"] if d < -0.02 else (C["bad"] if d > 0.05 else C["muted"])
                c.setText(f"B{k}  {'+' if d > 0 else '−'}{sec(d, 2)}")
                c.setStyleSheet(f"color: {col};")
                c.show()
            else:
                c.hide()
        self.coach_hint.setVisible(not keys)

    def _flag(self, flag, st):
        styles = {
            "safety car": ("#FFD400", "#1A1500", "SAFETY CAR  ·  " + ("PITS OPEN" if st.get("pits_open") else "PITS DICHT")),
            "geel": ("#FFD400", "#1A1500", "GELE VLAG"),
            "blauw": ("#2F7BFF", "#FFFFFF", "BLAUWE VLAG  ·  LAAT HEM ERLANGS"),
            "zwart": ("#000000", "#FFFFFF", "ZWARTE VLAG  ·  NAAR DE PITS"),
            "wit": ("#F2F2F2", "#111111", "LAATSTE RONDE"),
        }
        if st.get("incident_actief"):
            styles_key = ("#FF5A5F", "#FFFFFF", "SPIN  ·  KIJK UIT VOOR VERKEER")
        else:
            styles_key = styles.get(flag)
        if not styles_key:
            self.flagbar.hide()
            return
        bg, fg, txt = styles_key
        self.flagbar.setText(txt)
        self.flagbar.setStyleSheet(f"background:{bg}; color:{fg}; font-weight:800; font-size:14px; letter-spacing:2px; border-radius:10px; padding:8px;")
        self.flagbar.show()

    def set_banner(self, text):
        self.banner.setText(text)
        self.banner.setVisible(bool(text))


# ======================================================================
class SettingsPage(QWidget):
    VOICES = [("nl-NL-MaartenNeural", "Maarten (man)"), ("nl-NL-FennaNeural", "Fenna (vrouw)"),
              ("nl-NL-ColetteNeural", "Colette (vrouw)"), ("nl-BE-ArnaudNeural", "Arnaud (Vlaams)")]
    ENGINES = [("edge", "Natuurlijke stem (internet nodig)"), ("sapi", "Windows-stem (offline)"), ("print", "Geen stem, alleen tekst")]
    MODELS = [("claude-haiku-5-5", "Snel – Haiku"), ("claude-sonnet-5-5", "Slimmer – Sonnet")]
    GAPS = [("smart", "Slim: als het spannend is"), ("every_lap", "Elke ronde"), ("off", "Uit")]
    COACH = [("auto", "Automatisch (training uitgebreid, race kort)"), ("practice", "Altijd uitgebreid"),
             ("race", "Alleen grote fouten"), ("off", "Uit")]
    NAMES = [("achternaam", "Achternaam"), ("volledig", "Volledige naam"), ("nummer", "Startnummer")]

    def __init__(self, win):
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.addWidget(lab("Instellingen", "h1"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("page")
        self.form = QVBoxLayout(inner)
        self.form.setSpacing(4)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # Stem
        g, f = self._group("Stem")
        self.v_engine = self._combo(self.ENGINES)
        self.v_voice = self._combo(self.VOICES)
        self.v_rate = QSlider(Qt.Horizontal)
        self.v_rate.setRange(-20, 40)
        self.v_vol = QSlider(Qt.Horizontal)
        self.v_vol.setRange(10, 100)
        test = QPushButton("Test de stem")
        test.clicked.connect(self.win.test_voice)
        f.addRow("Soort stem", self.v_engine)
        f.addRow("Stem", self.v_voice)
        f.addRow("Spreeksnelheid", self.v_rate)
        f.addRow("Volume", self.v_vol)
        f.addRow("", test)

        # AI
        g, f = self._group("AI (Claude)")
        self.a_key = QLineEdit()
        self.a_key.setEchoMode(QLineEdit.Password)
        self.a_key.setPlaceholderText("sk-ant-...")
        keyrow = QHBoxLayout()
        keyrow.addWidget(self.a_key, 1)
        mk = QPushButton("Sleutel maken")
        mk.clicked.connect(lambda: webbrowser.open("https://console.anthropic.com/settings/keys"))
        keyrow.addWidget(mk)
        kw = QWidget()
        kw.setLayout(keyrow)
        keyrow.setContentsMargins(0, 0, 0, 0)
        self.a_model = self._combo(self.MODELS)
        self.a_every = QSpinBox()
        self.a_every.setRange(0, 20)
        self.a_every.setSuffix(" ronden")
        self.a_every.setSpecialValueText("uit")
        self.a_debrief = QCheckBox("Nabespreking na de race")
        self.d_name = QLineEdit()
        self.d_name.setPlaceholderText("bv. Frank")
        f.addRow("Jouw naam", self.d_name)
        f.addRow("API-sleutel", kw)
        f.addRow("Model", self.a_model)
        f.addRow("Automatische update elke", self.a_every)
        f.addRow("", self.a_debrief)
        f.addRow("", lab("Zonder sleutel werkt alles, alleen zijn de updates dan vaste zinnen en kun je geen vragen stellen.", "sub", wrap=True))

        # Engineer
        g, f = self._group("Race engineer")
        self.e_gap = self._combo(self.GAPS)
        self.e_battle = QDoubleSpinBox()
        self.e_battle.setRange(0.0, 3.0)
        self.e_battle.setSingleStep(0.1)
        self.e_battle.setSuffix(" s")
        self.e_names = self._combo(self.NAMES)
        self.e_lap = QCheckBox("Elke ronde laptijd en positie")
        self.e_fuel = QCheckBox("Brandstof-meldingen")
        self.e_class = QCheckBox("Alleen mijn klasse (multiclass)")
        self.e_pit = QDoubleSpinBox()
        self.e_pit.setRange(5, 120)
        self.e_pit.setSuffix(" s")
        f.addRow("Gaps melden", self.e_gap)
        f.addRow("Waarschuwing auto achter binnen", self.e_battle)
        f.addRow("Namen uitspreken als", self.e_names)
        f.addRow("Tijdverlies pitstop", self.e_pit)
        f.addRow("", self.e_lap)
        f.addRow("", self.e_fuel)
        f.addRow("", self.e_class)

        # Incidenten
        g, f = self._group("Spins && incidenten")
        self.i_on = QCheckBox("Spins en van-de-baan herkennen")
        self.i_traffic = QCheckBox("Verkeer melden na een spin (wacht / vrij)")
        self.i_limit = QCheckBox("Waarschuwen als je de incidentlimiet nadert")
        f.addRow("", self.i_on)
        f.addRow("", self.i_traffic)
        f.addRow("", self.i_limit)

        # Coach
        g, f = self._group("Rijcoaching per bocht")
        self.c_on = QCheckBox("Coaching aan")
        self.c_mode = self._combo(self.COACH)
        self.c_quiet = QCheckBox("Stil als er iemand binnen 1 seconde zit")
        self.c_summary = QCheckBox("Na elke ronde: waar verloor je de meeste tijd")
        f.addRow("", self.c_on)
        f.addRow("Hoeveel coaching", self.c_mode)
        f.addRow("", self.c_quiet)
        f.addRow("", self.c_summary)

        # Race-extra's
        g, f = self._group("Race-extra's")
        self.x_pit = QCheckBox("Pitstop automatisch klaarzetten (brandstof en banden)")
        self.x_tyres = self._combo([("auto", "Banden: automatisch (niet in de laatste ronden)"), ("altijd", "Banden: altijd wisselen"), ("nooit", "Banden: nooit wisselen")])
        self.x_fr = QCheckBox("Fast repair klaarzetten na zwaar contact (4x)")
        self.x_mc = QCheckBox("Waarschuwen voor snellere klassen")
        self.x_mc_s = QDoubleSpinBox()
        self.x_mc_s.setRange(1.0, 8.0)
        self.x_mc_s.setSingleStep(0.5)
        self.x_mc_s.setSuffix(" s van tevoren")
        self.x_flags = QCheckBox("Vlaggen en safety car (met pit-advies)")
        self.x_opp = QCheckBox("Info over de auto voor en achter je (iRating, licentie, incidenten)")
        self.x_ir = QCheckBox("iRating-voorspelling")
        self.x_weather = QCheckBox("Baantemperatuur en regen")
        f.addRow("", self.x_pit)
        f.addRow("Bandenwissel", self.x_tyres)
        f.addRow("", self.x_fr)
        f.addRow("", self.x_mc)
        f.addRow("Klasse-waarschuwing", self.x_mc_s)
        f.addRow("", self.x_flags)
        f.addRow("", self.x_opp)
        f.addRow("", self.x_ir)
        f.addRow("", self.x_weather)

        # Training
        g, f = self._group("Training")
        self.t_guide = self._combo([("auto", "Op een nieuwe baan: per bocht vooraf uitleg"), ("altijd", "Altijd per bocht vooraf uitleg"), ("uit", "Uit")])
        self.t_guide_laps = QSpinBox()
        self.t_guide_laps.setRange(1, 30)
        self.t_guide_laps.setSuffix(" ronden")
        self.t_bal = QCheckBox("Onder- en overstuur per bocht herkennen")
        self.t_bal_speak = QCheckBox("Balans-meldingen uitspreken (in training)")
        self.t_bal_adv = QCheckBox("Met setup- en rijtechniek-tip")
        f.addRow("Baan leren", self.t_guide)
        f.addRow("Hoe lang", self.t_guide_laps)
        f.addRow("", self.t_bal)
        f.addRow("", self.t_bal_speak)
        f.addRow("", self.t_bal_adv)

        # Programma
        g, f = self._group("Programma")
        self.p_auto = QCheckBox("Engineer automatisch starten als het programma opent")
        f.addRow("", self.p_auto)
        openlogs = QPushButton("Open map met logs en nabesprekingen")
        openlogs.clicked.connect(lambda: _open_folder(settings.logs_dir()))
        f.addRow("", openlogs)
        self.form.addStretch(1)

        bottom = QHBoxLayout()
        self.saved = lab("", "sub")
        bottom.addWidget(self.saved, 1)
        save = QPushButton("Opslaan")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        bottom.addWidget(save)
        outer.addLayout(bottom)

    def _group(self, title):
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignLeft)
        f.setHorizontalSpacing(18)
        f.setVerticalSpacing(10)
        self.form.addWidget(g)
        return g, f

    def _combo(self, items):
        c = QComboBox()
        for key, text in items:
            c.addItem(text, key)
        return c

    @staticmethod
    def _set_combo(c, key):
        i = c.findData(key)
        c.setCurrentIndex(i if i >= 0 else 0)

    def load(self, cfg):
        v, a, e, co = cfg["voice"], cfg["ai"], cfg["engineer"], cfg["coach"]
        self._set_combo(self.v_engine, v["engine"])
        self._set_combo(self.v_voice, v["edge_voice"])
        try:
            self.v_rate.setValue(int(str(v.get("rate", "+0%")).replace("%", "")))
        except ValueError:
            self.v_rate.setValue(0)
        self.v_vol.setValue(int(float(v.get("volume", 1.0)) * 100))
        self.a_key.setText(a.get("api_key") or "")
        self.d_name.setText((cfg.get("driver", {}) or {}).get("name") or "")
        self._set_combo(self.a_model, a["model"])
        self.a_every.setValue(int(a.get("auto_update_every_laps") or 0))
        self.a_debrief.setChecked(bool(a.get("debrief_after_race")))
        self._set_combo(self.e_gap, e["gap_report"])
        self.e_battle.setValue(float(e["battle_alert_gap"]))
        self._set_combo(self.e_names, e["name_style"])
        self.e_pit.setValue(float(e["pit_loss_seconds"]))
        self.e_lap.setChecked(bool(e["lap_report"]))
        self.e_fuel.setChecked(bool(e["fuel_reports"]))
        self.e_class.setChecked(bool(e["class_only"]))
        self.c_on.setChecked(bool(co["enabled"]))
        self._set_combo(self.c_mode, co["mode"])
        self.c_quiet.setChecked(bool(co["quiet_when_battling"]))
        self.c_summary.setChecked(bool(co["lap_summary"]))
        self.p_auto.setChecked(bool(cfg.get("app", {}).get("autostart", True)))
        x = cfg.get("race_extras", {})
        self.x_pit.setChecked(bool(x.get("pit_auto", True)))
        self._set_combo(self.x_tyres, x.get("pit_tyres", "auto"))
        self.x_fr.setChecked(bool(x.get("fast_repair", True)))
        self.x_mc.setChecked(bool(x.get("multiclass", True)))
        self.x_mc_s.setValue(float(x.get("multiclass_warn_s", 3.0)))
        self.x_flags.setChecked(bool(x.get("flags", True)))
        self.x_opp.setChecked(bool(x.get("opponent_info", True)))
        self.x_ir.setChecked(bool(x.get("irating", True)))
        self.x_weather.setChecked(bool(x.get("weather", True)))
        self._set_combo(self.t_guide, co.get("track_guide", "auto"))
        self.t_guide_laps.setValue(int(co.get("track_guide_laps", 5)))
        b = cfg.get("balance", {})
        self.t_bal.setChecked(bool(b.get("enabled", True)))
        self.t_bal_speak.setChecked(bool(b.get("speak", True)))
        self.t_bal_adv.setChecked(bool(b.get("advice", True)))
        inc = cfg.get("incidents", {})
        self.i_on.setChecked(bool(inc.get("enabled", True)))
        self.i_traffic.setChecked(bool(inc.get("traffic_warnings", True)))
        self.i_limit.setChecked(bool(inc.get("limit_warnings", True)))

    def collect(self, cfg):
        v, a, e, co = cfg["voice"], cfg["ai"], cfg["engineer"], cfg["coach"]
        v["engine"] = self.v_engine.currentData()
        v["edge_voice"] = self.v_voice.currentData()
        r = self.v_rate.value()
        v["rate"] = f"{'+' if r >= 0 else ''}{r}%"
        v["volume"] = self.v_vol.value() / 100
        a["api_key"] = self.a_key.text().strip()
        cfg.setdefault("driver", {})["name"] = self.d_name.text().strip()
        a["model"] = self.a_model.currentData()
        a["auto_update_every_laps"] = self.a_every.value()
        a["debrief_after_race"] = self.a_debrief.isChecked()
        e["gap_report"] = self.e_gap.currentData()
        e["battle_alert_gap"] = round(self.e_battle.value(), 2)
        e["name_style"] = self.e_names.currentData()
        e["pit_loss_seconds"] = round(self.e_pit.value(), 1)
        e["lap_report"] = self.e_lap.isChecked()
        e["fuel_reports"] = self.e_fuel.isChecked()
        e["class_only"] = self.e_class.isChecked()
        co["enabled"] = self.c_on.isChecked()
        co["mode"] = self.c_mode.currentData()
        co["quiet_when_battling"] = self.c_quiet.isChecked()
        co["lap_summary"] = self.c_summary.isChecked()
        cfg.setdefault("app", {})["autostart"] = self.p_auto.isChecked()
        x = cfg.setdefault("race_extras", {})
        x["pit_auto"] = self.x_pit.isChecked()
        x["pit_tyres"] = self.x_tyres.currentData()
        x["fast_repair"] = self.x_fr.isChecked()
        x["multiclass"] = self.x_mc.isChecked()
        x["multiclass_warn_s"] = round(self.x_mc_s.value(), 1)
        x["flags"] = self.x_flags.isChecked()
        x["opponent_info"] = self.x_opp.isChecked()
        x["irating"] = self.x_ir.isChecked()
        x["weather"] = self.x_weather.isChecked()
        co["track_guide"] = self.t_guide.currentData()
        co["track_guide_laps"] = self.t_guide_laps.value()
        b = cfg.setdefault("balance", {})
        b["enabled"] = self.t_bal.isChecked()
        b["speak"] = self.t_bal_speak.isChecked()
        b["advice"] = self.t_bal_adv.isChecked()
        inc = cfg.setdefault("incidents", {})
        inc["enabled"] = self.i_on.isChecked()
        inc["traffic_warnings"] = self.i_traffic.isChecked()
        inc["limit_warnings"] = self.i_limit.isChecked()
        return cfg

    def save(self):
        self.win.save_cfg(self.collect(self.win.cfg))
        self.saved.setText("Opgeslagen." + ("  Wordt actief bij de volgende start van de engineer." if self.win.engine.running else ""))
        QTimer.singleShot(5000, lambda: self.saved.setText(""))


# ======================================================================
class ButtonsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(lab("Knoppen", "h1"))
        root.addWidget(lab("Koppel acties aan een toets op je toetsenbord of een knop op je stuur. "
                           "Toetsen werken ook als iRacing op de voorgrond staat.", "sub", wrap=True))
        self.devices = lab("", "sub", wrap=True)
        root.addWidget(self.devices)

        box = card()
        grid = QGridLayout(box)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for col, h in enumerate(["ACTIE", "TOETS", "STUURKNOP", ""]):
            grid.addWidget(lab(h, "cap"), 0, col)
        self.key_edits, self.wheel_labels = {}, {}
        for r, a in enumerate(ACTIONS, start=1):
            grid.addWidget(lab(ACTION_LABELS[a]), r, 0)
            ke = QLineEdit()
            ke.setPlaceholderText("bv. f9")
            ke.setFixedWidth(110)
            grid.addWidget(ke, r, 1)
            wl = lab("–")
            grid.addWidget(wl, r, 2)
            bw = QHBoxLayout()
            assign = QPushButton("Stuurknop toewijzen")
            assign.clicked.connect(lambda _=False, x=a: self.assign(x))
            clear = QPushButton("Wissen")
            clear.clicked.connect(lambda _=False, x=a: self.clear(x))
            bw.addWidget(assign)
            bw.addWidget(clear)
            w = QWidget()
            bw.setContentsMargins(0, 0, 0, 0)
            w.setLayout(bw)
            grid.addWidget(w, r, 3)
            self.key_edits[a], self.wheel_labels[a] = ke, wl
        grid.setColumnStretch(2, 1)
        root.addWidget(box)

        self.mic = QCheckBox("Microfoon gebruiken voor 'Vraag stellen'")
        root.addWidget(self.mic)
        self.hint = lab("", "sub")
        root.addWidget(self.hint)
        root.addStretch(1)
        bottom = QHBoxLayout()
        self.saved = lab("", "sub")
        bottom.addWidget(self.saved, 1)
        save = QPushButton("Opslaan")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        bottom.addWidget(save)
        root.addLayout(bottom)
        self.wheel = {}

    def load(self, cfg):
        keys, wheel = cfg["buttons"]["keyboard"], cfg["buttons"]["wheel"]
        self.wheel = dict(wheel)
        for a in ACTIONS:
            self.key_edits[a].setText(keys.get(a) or "")
            self._show_wheel(a)
        self.mic.setChecked(bool(cfg["speech_input"]["enabled"]))

    def _show_wheel(self, a):
        n = self.wheel.get(a, -1)
        self.wheel_labels[a].setText(f"knop {n}" if isinstance(n, int) and n >= 0 else "–")

    def assign(self, a):
        if not self.win.joy.ok:
            self.hint.setText("Geen stuur gevonden. Sluit je stuur aan en start het programma opnieuw.")
            return
        self.hint.setText(f"Druk nu op de knop op je stuur voor '{ACTION_LABELS[a]}'…")
        self.wheel_labels[a].setText("druk op een knop…")

        def got(button, name):
            self._pending = (a, button, name)
        self._pending = None
        self.win.joy.capture_next(got)
        self._poll_n = 0
        self._poll_capture()

    def _poll_capture(self):
        if self._pending:
            a, button, name = self._pending
            self.wheel[a] = button
            self.wheel["device_name_contains"] = name.split(" ")[0] if name else ""
            self._show_wheel(a)
            self.hint.setText(f"Gekoppeld aan knop {button} op {name}. Vergeet niet op te slaan.")
            return
        self._poll_n += 1
        if self._poll_n > 100:  # 10 s
            self.win.joy.capture_next(None)
            self.hint.setText("Geen knop gedetecteerd.")
            for a in ACTIONS:
                self._show_wheel(a)
            return
        QTimer.singleShot(100, self._poll_capture)

    def clear(self, a):
        self.wheel[a] = -1
        self._show_wheel(a)

    def save(self):
        cfg = self.win.cfg
        for a in ACTIONS:
            cfg["buttons"]["keyboard"][a] = self.key_edits[a].text().strip().lower()
            cfg["buttons"]["wheel"][a] = self.wheel.get(a, -1)
        cfg["buttons"]["wheel"]["device_name_contains"] = self.wheel.get("device_name_contains", "")
        cfg["speech_input"]["enabled"] = self.mic.isChecked()
        self.win.save_cfg(cfg)
        self.win.apply_inputs()
        self.saved.setText("Opgeslagen.")
        QTimer.singleShot(4000, lambda: self.saved.setText(""))

    def tick(self):
        devs = self.win.joy.devices
        self.devices.setText("Gevonden: " + ", ".join(devs) if devs else "Nog geen stuur of knoppenbox gevonden.")


# ======================================================================
class ScreenPage(QWidget):
    """Tweede scherm: adres + QR-code voor telefoon/iPad/andere pc."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(lab("Tweede scherm", "h1"))
        root.addWidget(lab("Zet je telefoon, iPad of een andere pc naast je stuur als live dashboard. "
                           "Het apparaat moet op hetzelfde (wifi-)netwerk zitten als deze pc.", "sub", wrap=True))
        box = card()
        h = QHBoxLayout(box)
        h.setContentsMargins(20, 20, 20, 20)
        h.setSpacing(24)
        self.qr = QLabel()
        self.qr.setFixedSize(220, 220)
        self.qr.setAlignment(Qt.AlignCenter)
        h.addWidget(self.qr)
        v = QVBoxLayout()
        v.setSpacing(8)
        v.addWidget(lab("SCAN MET JE CAMERA OF TYP DIT ADRES IN", "cap"))
        self.url = lab("", "h1")
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.url)
        self.viewers = lab("", "sub")
        v.addWidget(self.viewers)
        self.enabled = QCheckBox("Tweede scherm aan")
        self.enabled.toggled.connect(self.toggle)
        v.addWidget(self.enabled)
        pr = QHBoxLayout()
        pr.addWidget(lab("Poort", "sub"))
        self.port = QSpinBox()
        self.port.setRange(1024, 65000)
        self.port.setFixedWidth(110)
        pr.addWidget(self.port)
        apply = QPushButton("Toepassen")
        apply.clicked.connect(self.apply_port)
        pr.addWidget(apply)
        pr.addStretch(1)
        v.addLayout(pr)
        v.addStretch(1)
        h.addLayout(v, 1)
        root.addWidget(box)
        tips = lab("Tips:  op iPhone/iPad: open de pagina in Safari → Deel → 'Zet op beginscherm' voor een app-icoon zonder adresbalk.  "
                   "Vraagt Windows om toestemming voor het netwerk? Kies 'Privénetwerken' en klik Toestaan.  "
                   "Zet de automatische schermvergrendeling van je telefoon even uit tijdens het racen.", "sub", wrap=True)
        root.addWidget(tips)
        root.addStretch(1)

    def load(self, cfg):
        a = cfg.get("app", {})
        self.port.setValue(int(a.get("second_screen_port", 8770)))
        self.enabled.blockSignals(True)
        self.enabled.setChecked(bool(a.get("second_screen", True)))
        self.enabled.blockSignals(False)
        self.refresh()

    def toggle(self, on):
        self.win.cfg.setdefault("app", {})["second_screen"] = on
        self.win.save_cfg(self.win.cfg)
        self.win.apply_web()
        self.refresh()

    def apply_port(self):
        self.win.cfg.setdefault("app", {})["second_screen_port"] = self.port.value()
        self.win.save_cfg(self.win.cfg)
        self.win.apply_web(restart=True)
        self.refresh()

    def refresh(self):
        web = self.win.web
        if not web.running:
            self.url.setText("uit")
            self.qr.clear()
            self.qr.setText("—")
            return
        url = web.url
        self.url.setText(url)
        self.qr.setPixmap(_qr_pixmap(url, 220))

    def tick(self):
        web = self.win.web
        n = web.viewer_count() if web.running else 0
        self.viewers.setText("Niemand verbonden" if n == 0 else f"{n} {'scherm' if n == 1 else 'schermen'} verbonden")
        self.viewers.setStyleSheet(f"color: {C['good'] if n else C['muted']};")


def _qr_pixmap(text, size):
    from PySide6.QtGui import QPainter, QPixmap, QColor
    pm = QPixmap(size, size)
    pm.fill(QColor("white"))
    try:
        import qrcode
        q = qrcode.QRCode(border=2)
        q.add_data(text)
        q.make(fit=True)
        m = q.get_matrix()
    except Exception:
        return pm
    n = len(m)
    cell = size / n
    p = QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(m):
        for x, val in enumerate(row):
            if val:
                p.drawRect(int(x * cell), int(y * cell), int(cell + 1), int(cell + 1))
    p.end()
    return pm


def _open_folder(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            webbrowser.open("file://" + path)
    except Exception:
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Race Engineer")
        try:
            self.setWindowIcon(QIcon(settings.resource("icon.ico")))
        except Exception:
            pass
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)
        self.first_run = not os.path.exists(settings.config_path())
        self.cfg = settings.load()
        self.msgq = queue.Queue()
        from collections import deque
        self.radio_log = deque(maxlen=30)
        from webdash import WebDash
        self.web = WebDash(self._web_data, lambda m: self.log(m), port=int(self.cfg.get("app", {}).get("second_screen_port", 8770)))
        self.logf = open(os.path.join(settings.logs_dir(), f"sessie_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"),
                         "a", encoding="utf-8")
        self.engine = Engine(self._engine_cfg(), self.log)
        self.hotkeys = Hotkeys(self.log)
        self.joy = JoystickWatcher(self.log)
        self._test_voice = None

        central = QWidget()
        central.setObjectName("page")
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(210)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 20, 14, 16)
        sv.setSpacing(4)
        logo = QLabel()
        try:
            logo.setPixmap(QIcon(settings.resource("icon.ico")).pixmap(40, 40))
        except Exception:
            pass
        sv.addWidget(logo)
        sv.addWidget(lab("Race Engineer", "brand"))
        sv.addWidget(lab("AI voor iRacing", "brandsub"))
        sv.addSpacing(20)
        self.stack = QStackedWidget()
        self.race = RacePage(self)
        self.sets = SettingsPage(self)
        self.btns = ButtonsPage(self)
        from analysis_page import AnalysisPage
        self.analysis = AnalysisPage(self, lab, card)
        self.screen = ScreenPage(self)
        self.navs = []
        for i, (name, page) in enumerate([("Race", self.race), ("Analyse", self.analysis), ("Tweede scherm", self.screen),
                                         ("Instellingen", self.sets), ("Knoppen", self.btns)]):
            page.setObjectName("page")
            self.stack.addWidget(page)
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, x=i: self.go(x))
            sv.addWidget(b)
            self.navs.append(b)
        sv.addStretch(1)
        self.status_dot = lab("●")
        self.status_txt = lab("Gestopt", "sub")
        sr = QHBoxLayout()
        sr.addWidget(self.status_dot)
        sr.addWidget(self.status_txt, 1)
        sv.addLayout(sr)
        self.update_btn = QPushButton("")
        self.update_btn.setObjectName("primary")
        self.update_btn.setStyleSheet("padding: 6px 8px; font-size: 12px;")
        self.update_btn.hide()
        self.update_btn.clicked.connect(lambda: webbrowser.open(self._update_info["url"]) if self._update_info else None)
        sv.addWidget(self.update_btn)
        sv.addWidget(lab(f"versie {VERSION}", "brandsub"))
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.go(0)

        self.sets.load(self.cfg)
        self.apply_web()
        self.screen.load(self.cfg)
        self.btns.load(self.cfg)
        self.race.refresh_keys(self.cfg)
        self.apply_inputs()
        self.race.btn_start.clicked.connect(self.toggle)
        self.race.btn_test.clicked.connect(self.start_test)
        self.race.btn_test_p.clicked.connect(self.start_test_practice)
        self._update_banner()

        self._update_info = None
        import updater
        updater.check_async(lambda info: setattr(self, "_update_info", info))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        if self.first_run:
            settings.save(self.cfg)
            QTimer.singleShot(300, self._welcome)
        if self.cfg.get("app", {}).get("autostart", True):
            QTimer.singleShot(400, self.start_real)

    # -------------------------------------------------------------
    def _engine_cfg(self):
        import copy
        cfg = copy.deepcopy(self.cfg)
        if not cfg["ai"].get("api_key"):
            cfg["ai"]["api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
        return cfg

    def log(self, msg, kind="info"):
        self.msgq.put((msg, kind))
        if kind in ("radio", "question"):
            self.radio_log.append({"k": kind, "t": datetime.datetime.now().strftime("%H:%M"), "x": msg})
        try:
            prefix = {"radio": "ENGINEER: ", "question": "JIJ: ", "debrief": "NABESPREKING:\n"}.get(kind, "")
            self.logf.write(f"{datetime.datetime.now():%H:%M:%S}  {prefix}{msg}\n")
            self.logf.flush()
        except Exception:
            pass

    def _welcome(self):
        QMessageBox.information(
            self, "Welkom bij AI Race Engineer",
            "Welkom! Drie dingen om te beginnen:\n\n"
            "1. Vul bij Instellingen je naam in (zo spreekt de engineer je aan).\n"
            "2. Optioneel: een Claude API-sleutel voor slimme updates en vragen stellen.\n"
            "3. Klik op 'Testrace' om alles te proberen zonder iRacing.\n\n"
            "Daarna: start iRacing en stap in de auto. De engineer meldt zich vanzelf.")
        self.go(3)

    def _web_data(self):
        eng = self.engine
        st = eng.status if eng.running else {}
        tank = None
        if getattr(eng, "state", None) is not None:
            tank = eng.state.fuel_max
        return {"actief": eng.running, "status": st, "radio": list(self.radio_log), "tank": tank}

    def apply_web(self, restart=False):
        on = self.cfg.get("app", {}).get("second_screen", True)
        port = int(self.cfg.get("app", {}).get("second_screen_port", 8770))
        if restart or not on or port != self.web.port:
            self.web.stop()
            self.web.port = port
        if on and not self.web.running:
            self.web.start()

    def go(self, i):
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.navs):
            b.setChecked(i == j)

    def save_cfg(self, cfg):
        self.cfg = cfg
        settings.save(cfg)
        self.race.refresh_keys(cfg)
        self._update_banner()

    def apply_inputs(self):
        self.hotkeys.apply(self.cfg["buttons"]["keyboard"], self.engine.action)
        self.joy.configure(self.cfg["buttons"]["wheel"], self.engine.action)

    def _update_banner(self):
        has_key = self.cfg["ai"].get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        self.race.set_banner("" if has_key else
                             "Tip: voeg bij Instellingen een Claude API-sleutel toe voor slimme race-updates, "
                             "een nabespreking en vragen stellen via je microfoon.")

    # -------------------------------------------------------------
    def _new_engine(self):
        self.engine = Engine(self._engine_cfg(), self.log)
        self.apply_inputs()

    def toggle(self):
        if self.engine.running:
            self.engine.stop()
        else:
            self.start_real()

    def start_real(self):
        if self.engine.running:
            return
        self._new_engine()
        self.engine.start(mock=False)

    def start_test_practice(self):
        if self.engine.running:
            return
        self._new_engine()
        self.race.radio.clear()
        self.engine.start(mock=True, speed=3, laps=8, session="Practice")

    def start_test(self):
        if self.engine.running:
            return
        self._new_engine()
        self.race.radio.clear()
        self.engine.start(mock=True, speed=3, laps=12)

    def test_voice(self):
        from voice import Voice
        cfg = self.sets.collect(self._engine_cfg())
        if self._test_voice:
            self._test_voice.stop()
        self._test_voice = Voice(cfg, self.log)
        self._test_voice.say("Radio check. Hoor je me goed? Je ligt P3, 1,2 seconde achter de auto voor je.", 1)

    def tick(self):
        if self._update_info and not getattr(self, "_update_shown", False):
            self._update_shown = True
            self.update_btn.setText(f"Update beschikbaar: versie {self._update_info['versie']}")
            self.update_btn.show()
        n = 0
        while not self.msgq.empty() and n < 50:
            msg, kind = self.msgq.get_nowait()
            self.race.add_radio(msg.replace("<", "&lt;"), kind)
            n += 1
        st = self.engine.status if self.engine.running else {}
        self.race.update_status(st, self.engine)
        self.btns.tick()
        self.screen.tick()
        if self.stack.currentWidget() is self.analysis:
            self.analysis.tick()
        if not self.engine.running:
            col, txt = "#555c66", "Gestopt"
        elif self.engine.connected:
            col, txt = C["good"], "Testrace" if self.engine.mock else "Verbonden met iRacing"
        else:
            col, txt = C["accent"], "Wacht op iRacing"
        self.status_dot.setStyleSheet(f"color: {col}; font-size: 14px;")
        self.status_txt.setText(txt)

    def closeEvent(self, e):
        self.engine.stop()
        self.web.stop()
        e.accept()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("frank.raceengineer")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setFont(QFont("Segoe UI", 10))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
