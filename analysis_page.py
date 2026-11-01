"""Analysepagina: rem-, gas- en snelheidslijnen per bocht, jouw ronde tegen je beste ronde,
plus de balans (onder/overstuur) per bocht."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from coach import BIN_M
from race_state import fmt_lap

COL = {"bg": "#171B21", "grid": "#262C35", "text": "#8A94A6", "ref": "#FF8A00", "lap": "#5AB0FF",
       "good": "#3DDC84", "bad": "#FF5A5F", "fg": "#E8EAED"}


class TraceChart(QWidget):
    """Vier gestapelde grafieken over afstand: snelheid, gas, rem, tijdverschil."""
    PANELS = [("SNELHEID km/u", "v", None), ("GAS %", "thr", (0, 100)), ("REM %", "brake", (0, 100)), ("VERSCHIL s", "delta", None)]

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ref = None
        self.lap = None
        self.rng = None
        self.corners = []
        self.ref_label = "beste"
        self.lap_label = "ronde"

    def set_data(self, ref, lap, rng, corners, ref_label, lap_label):
        self.ref, self.lap, self.rng, self.corners = ref, lap, rng, corners
        self.ref_label, self.lap_label = ref_label, lap_label
        self.update()

    def _series(self, lap, key, a, b):
        if lap is None:
            return []
        if key == "delta":
            if self.ref is None:
                return []
            t0l, t0r = lap.t[a] or 0, self.ref.t[a] or 0
            return [((lap.t[i] or 0) - t0l) - ((self.ref.t[i] or 0) - t0r) for i in range(a, b)]
        arr = getattr(lap, key)
        if not arr or all(x is None for x in arr[a:b]):
            return []   # bv. gas/rem van een andere rijder: niet bekend
        mul = 100 if key in ("thr", "brake") else 1
        return [(arr[i] if arr[i] is not None else 0) * mul for i in range(a, b)]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(COL["bg"]))
        if self.ref is None and self.lap is None:
            p.setPen(QColor(COL["text"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Nog geen rondes. Rij een paar ronden (of start een testrace),\n"
                                                    "dan zie je hier je rem-, gas- en snelheidslijnen.")
            return
        base = self.ref or self.lap
        a, b = self.rng or (0, base.n)
        b = max(a + 2, min(b, base.n))
        W, H = self.width(), self.height()
        left, right, top, gap = 58, 14, 26, 10
        ph = (H - top - 26 - gap * 3) / 4
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        # legenda
        p.setPen(QColor(COL["ref"]))
        p.drawText(left, 16, f"━ {self.ref_label}")
        p.setPen(QColor(COL["lap"]))
        p.drawText(left + p.fontMetrics().horizontalAdvance(f"━ {self.ref_label}") + 24, 16, f"━ {self.lap_label}")
        for k, (title, key, fixed) in enumerate(self.PANELS):
            y0 = top + k * (ph + gap)
            rect = QRectF(left, y0, W - left - right, ph)
            p.setPen(QPen(QColor(COL["grid"]), 1))
            p.drawRect(rect)
            sr = self._series(self.ref, key, a, b) if key != "delta" else []
            sl = self._series(self.lap, key, a, b)
            vals = [x for x in sr + sl if x is not None]
            if fixed:
                lo, hi = fixed
            elif vals:
                lo, hi = min(vals), max(vals)
                if key == "delta":
                    m = max(abs(lo), abs(hi), 0.05)
                    lo, hi = -m, m
                pad = (hi - lo) * 0.08 or 1
                lo, hi = lo - pad, hi + pad
            else:
                lo, hi = 0, 1
            p.setPen(QColor(COL["text"]))
            p.drawText(QRectF(4, y0, left - 8, 14), Qt.AlignRight, title.split()[0].capitalize())
            unit = title.split()[-1]
            p.drawText(QRectF(4, y0 + 13, left - 8, 14), Qt.AlignRight,
                       f"{hi:.0f}{'' if unit in ('%',) else ''}" if key != "delta" else f"+{hi:.2f}".replace(".", ","))
            p.drawText(QRectF(4, y0 + ph - 14, left - 8, 14), Qt.AlignRight,
                       f"{lo:.0f}" if key != "delta" else f"{lo:.2f}".replace(".", ","))
            if key == "delta":
                yz = y0 + ph * (hi / (hi - lo))
                p.setPen(QPen(QColor(COL["grid"]), 1, Qt.DashLine))
                p.drawLine(QPointF(left, yz), QPointF(W - right, yz))

            def path(series):
                pp = QPainterPath()
                n = len(series)
                for i, val in enumerate(series):
                    x = left + (W - left - right) * i / max(1, n - 1)
                    y = y0 + ph - (val - lo) / (hi - lo or 1) * ph
                    if i == 0:
                        pp.moveTo(x, y)
                    else:
                        pp.lineTo(x, y)
                return pp
            if sr:
                p.setPen(QPen(QColor(COL["ref"]), 1.6))
                p.drawPath(path(sr))
            if sl:
                if key == "delta":
                    end = sl[-1]
                    p.setPen(QPen(QColor(COL["bad"] if end > 0.02 else COL["good"]), 1.8))
                else:
                    p.setPen(QPen(QColor(COL["lap"]), 1.6))
                p.drawPath(path(sl))
        # bochtmarkeringen (alleen bij hele ronde)
        if self.rng is None or (b - a) > base.n * 0.6:
            p.setPen(QColor(COL["text"]))
            for c in self.corners:
                x = left + (W - left - right) * (c.apex_bin - a) / max(1, b - a - 1)
                p.drawText(QRectF(x - 14, H - 22, 28, 16), Qt.AlignCenter, f"B{c.nr}")
        else:
            p.setPen(QColor(COL["text"]))
            p.drawText(QRectF(left, H - 22, 200, 16), Qt.AlignLeft, f"{a * BIN_M:.0f} m")
            p.drawText(QRectF(W - right - 200, H - 22, 200, 16), Qt.AlignRight, f"{b * BIN_M:.0f} m")


class AnalysisPage(QWidget):
    def __init__(self, win, lab, card):
        super().__init__()
        self.win = win
        self._lab = lab
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(lab("Analyse", "h1"), 1)
        self.lap_box = QComboBox()
        self.lap_box.setMinimumWidth(220)
        self.corner_box = QComboBox()
        self.corner_box.setMinimumWidth(150)
        self.cmp_box = QComboBox()
        self.cmp_box.addItem("Mijn beste ronde", "own")
        self.cmp_box.setMinimumWidth(230)
        refresh = QPushButton("Vernieuwen")
        refresh.clicked.connect(self.refresh)
        top.addWidget(lab("Ronde", "sub"))
        top.addWidget(self.lap_box)
        top.addWidget(lab("Vergelijk met", "sub"))
        top.addWidget(self.cmp_box)
        top.addWidget(lab("Bocht", "sub"))
        top.addWidget(self.corner_box)
        top.addWidget(refresh)
        root.addLayout(top)
        self.info = lab("Oranje = waarmee je vergelijkt, blauw = de gekozen ronde. Onderste grafiek: tijd verloren (rood) of gewonnen (groen).", "sub", wrap=True)
        root.addWidget(self.info)
        self.chart = TraceChart()
        root.addWidget(self.chart, 1)
        bal = card()
        bv = QVBoxLayout(bal)
        bv.setContentsMargins(16, 12, 16, 12)
        bv.addWidget(lab("BALANS VAN DE AUTO PER BOCHT", "cap"))
        self.bal_grid = QGridLayout()
        self.bal_grid.setHorizontalSpacing(8)
        bv.addLayout(self.bal_grid)
        self.bal_hint = lab("Na een paar schone ronden zie je hier per bocht of de auto onderstuurt of overstuurt.", "sub", wrap=True)
        bv.addWidget(self.bal_hint)
        self.setup_line = lab("", "sub", wrap=True)
        bv.addWidget(self.setup_line)
        root.addWidget(bal)
        libc = card()
        lv = QVBoxLayout(libc)
        lv.setContentsMargins(16, 12, 16, 12)
        lv.addWidget(lab("REFERENTIE-BIBLIOTHEEK · SNELSTE RONDE PER AUTO EN BAAN", "cap"))
        self.lib_text = lab("Nog leeg. Tijdens elke sessie bewaar ik vanzelf de snelste ronde van iedere auto die meerijdt.", "sub", wrap=True)
        self.lib_text.setTextFormat(Qt.RichText)
        lv.addWidget(self.lib_text)
        root.addWidget(libc)
        self.cmp_box.currentIndexChanged.connect(self.redraw)
        self.cmp_box.activated.connect(lambda _i: setattr(self, "_user_cmp", True))
        self.lap_box.currentIndexChanged.connect(self.redraw)
        self.corner_box.currentIndexChanged.connect(self.redraw)
        self._n_laps = -1
        self._coach = None

    def _src(self):
        return getattr(self.win.engine, "coach", None)

    def refresh(self):
        coach = self._src()
        laps = list(coach.laps) if coach else []
        keep_lap = self.lap_box.currentData()
        keep_c = self.corner_box.currentData()
        self.lap_box.blockSignals(True)
        self.corner_box.blockSignals(True)
        self.lap_box.clear()
        for i, l in reversed(list(enumerate(laps))):
            mark = "" if l["schoon"] else "  (incident/pit)"
            self.lap_box.addItem(f"Ronde {l['nr']}  ·  {fmt_lap(l['tijd'])}{mark}", i)
        self.corner_box.clear()
        self.corner_box.addItem("Hele ronde", None)
        for c in (coach.corners if coach else []):
            self.corner_box.addItem(f"Bocht {c.nr}", c.nr)
        if keep_lap is not None:
            i = self.lap_box.findData(keep_lap)
            if i >= 0:
                self.lap_box.setCurrentIndex(i)
        if keep_c is not None:
            i = self.corner_box.findData(keep_c)
            if i >= 0:
                self.corner_box.setCurrentIndex(i)
        self.lap_box.blockSignals(False)
        self.corner_box.blockSignals(False)
        self._n_laps = len(laps)
        self._coach = coach
        keep_cmp = self.cmp_box.currentData()
        self.cmp_box.blockSignals(True)
        self.cmp_box.clear()
        self.cmp_box.addItem("Mijn beste ronde", "own")
        if coach and coach.ext is not None:
            m = coach.ext.meta
            self.cmp_box.addItem(f"Snelste: {m.get('rijder', '?')} {fmt_lap(m.get('tijd'))}", "ext")
            if keep_cmp == "ext" or (not getattr(self, "_user_cmp", False) and coach.use_ext()):
                self.cmp_box.setCurrentIndex(1)
        self.cmp_box.blockSignals(False)
        self.redraw()
        self._balance()
        self._library()

    def tick(self):
        coach = self._src()
        if coach is not self._coach or (coach and len(coach.laps) != self._n_laps):
            self.refresh()

    def redraw(self):
        coach = self._src()
        if not coach:
            self.chart.set_data(None, None, None, [], "", "")
            return
        laps = list(coach.laps)
        idx = self.lap_box.currentData()
        lap = laps[idx]["lap"] if idx is not None and idx < len(laps) else None
        lap_label = self.lap_box.currentText().split("  ·  ")[0] if lap else ""
        ref = coach.ref
        use_ext = self.cmp_box.currentData() == "ext" and coach.ext is not None
        if use_ext:
            ref = coach.ext
        rng = None
        cn = self.corner_box.currentData()
        if cn is not None:
            c = next((c for c in coach.corners if c.nr == cn), None)
            if c:
                rng = (max(0, c.brake_bin - int(120 / BIN_M)), min(coach.nbins, c.exit_bin + int(120 / BIN_M)))
        if use_ext:
            ref_label = f"{coach.ext.meta.get('rijder', 'referentie')} {fmt_lap(coach.ext.lap_time)} (gas/rem onbekend)"
        else:
            ref_label = f"beste ronde {fmt_lap(coach.ref_time)}" if ref else ""
        self.chart.set_data(ref, lap, rng, coach.corners, ref_label, lap_label)

    def _library(self):
        lib = getattr(self.win.engine, "library", None)
        if lib is None:
            import settings
            from reference import ReferenceLibrary
            items = []
            try:
                import json, os
                d = settings.ref_lib_dir()
                for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                    if fn.endswith(".json"):
                        with open(os.path.join(d, fn), encoding="utf-8") as f:
                            items.append(json.load(f).get("meta", {}))
            except Exception:
                items = []
        else:
            items = lib.list_all()
        if not items:
            return
        rows = sorted(items, key=lambda m: (m.get("baan", ""), m.get("auto", "")))
        html = "<table cellspacing='0' cellpadding='3'>" + "<tr style='color:#8A94A6'><td>Baan</td><td>Auto</td><td>Rijder</td><td>Tijd</td><td>Datum</td></tr>"
        for m in rows[:40]:
            html += (f"<tr><td>{m.get('baan', '')}</td><td>{m.get('auto', '')}</td><td>{m.get('rijder', '')}"
                     f"{' (jij)' if m.get('eigen') else ''}</td><td>{fmt_lap(m.get('tijd'))}</td><td>{m.get('datum', '')}</td></tr>")
        html += "</table>"
        if len(rows) > 40:
            html += f"<div>… en nog {len(rows) - 40}</div>"
        self.lib_text.setText(html)

    def _balance(self):
        while self.bal_grid.count():
            w = self.bal_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        su = getattr(self.win.engine, "setup", None)
        kv = su.key_values() if su else []
        txt = ("Jouw setup: " + "  ·  ".join(f"{k} {v}" for k, v in kv)) if kv else ""
        if su and su.changes:
            ch = su.changes[-1]
            txt += ("\n" if txt else "") + "Laatste wijziging (ronde %s): " % ch["ronde"] + ", ".join(
                f"{w['wat']} {w['van']} → {w['naar']}" for w in ch["wijzigingen"][:4])
        self.setup_line.setText(txt)
        self.setup_line.setVisible(bool(txt))
        bal = getattr(self.win.engine, "balance", None)
        if not bal or not bal.latest:
            self.bal_hint.show()
            return
        self.bal_hint.hide()
        corners = sorted({k[0] for k in bal.latest})
        self.bal_grid.addWidget(self._lab("", "sub"), 0, 0)
        for j, nr in enumerate(corners):
            self.bal_grid.addWidget(self._lab(f"B{nr}", "cap"), 0, j + 1)
        for r, (phase, name) in enumerate((("in", "Insturen"), ("uit", "Uitkomen")), start=1):
            self.bal_grid.addWidget(self._lab(name, "sub"), r, 0)
            for j, nr in enumerate(corners):
                d = bal.latest.get((nr, phase))
                txt, col = "–", COL["text"]
                if d:
                    txt = {"onderstuur": "onder", "overstuur": "over", "neutraal": "ok"}[d["label"]]
                    col = {"onderstuur": COL["lap"], "overstuur": COL["bad"], "neutraal": COL["good"]}[d["label"]]
                w = self._lab(txt, "chip")
                w.setAlignment(Qt.AlignCenter)
                w.setStyleSheet(f"color: {col};")
                self.bal_grid.addWidget(w, r, j + 1)
