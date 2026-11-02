"""Overlays: doorzichtige vensters boven iRacing (iRacing in 'venster zonder rand' / borderless).

Elke overlay tekent in zijn eigen basismaat en wordt als geheel geschaald (sleep de hoek om te vergroten).
'Verplaatsen' zet ze in bewerk-stand: dan kun je ze slepen en vergroten. Daarna klik je erdoorheen.
Posities en grootte worden bewaard in de instellingen (cfg["overlays"]).
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

BG = QColor(12, 14, 18)
ROW = QColor(255, 255, 255, 14)
TXT = QColor("#E8EAED")
MUTED = QColor("#8A94A6")
ACCENT = QColor("#FF8A00")
GOOD = QColor("#3DDC84")
BAD = QColor("#FF5A5F")
PURPLE = QColor("#B58CFF")
INFO = QColor("#5AB0FF")
ME_BG = QColor(255, 138, 0, 60)


def fmt_t(t, dec=3):
    if t is None or t <= 0:
        return "–"
    m = int(t // 60)
    s = t - 60 * m
    w = 3 + dec
    return (f"{m}:{s:0{w}.{dec}f}" if m else f"{s:.{dec}f}").replace(".", ",")


def fmt_gap(g, dec=1):
    if g is None:
        return "–"
    if isinstance(g, str):
        return g
    return (("+" if g > 0 else "−" if g < 0 else "") + f"{abs(g):.{dec}f}").replace(".", ",")


def font(px, bold=False, mono=False):
    f = QFont("Consolas" if mono else "Segoe UI")
    if mono:
        f.setStyleHint(QFont.Monospace)
    f.setPixelSize(int(px))
    f.setBold(bold)
    return f


# ======================================================================
#  Basis
# ======================================================================
class Overlay(QWidget):
    NAME = "basis"
    TITLE = "Overlay"
    BASE = (300, 200)          # tekenmaat (breedte, hoogte)
    DEFAULT_POS = (40, 40)

    def __init__(self, mgr):
        super().__init__(None)
        self.mgr = mgr
        self.edit = False
        self._drag = None
        self._resize = None
        self.setWindowTitle(f"Race Engineer · {self.TITLE}")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._apply_flags()
        geo = (mgr.cfg.get("vensters") or {}).get(self.NAME)
        x, y = self.default_pos()
        scale = 1.0
        if geo:
            x, y, scale = geo[0], geo[1], max(0.5, min(3.0, geo[2]))
        self.scale = scale
        self.move(int(x), int(y))
        self._fit()

    def default_pos(self):
        """DEFAULT_POS als fractie van het scherm (0..1); de overlay wordt daar binnen het scherm gezet."""
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        g = scr.availableGeometry() if scr else None
        sw, sh = (g.width(), g.height()) if g else (1920, 1080)
        ox, oy = (g.x(), g.y()) if g else (0, 0)
        fx, fy = self.DEFAULT_POS
        x = ox + max(0, fx * (sw - self.BASE[0]))
        y = oy + max(0, fy * (sh - self.BASE[1]))
        return int(x), int(y)

    def _fit(self):
        self.setFixedSize(int(self.BASE[0] * self.scale), int(self.BASE[1] * self.scale))

    def _apply_flags(self):
        f = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if not self.edit:
            f |= Qt.WindowTransparentForInput
        vis = self.isVisible()
        self.setWindowFlags(f)
        if vis:
            self.show()

    def set_edit(self, on):
        if on == self.edit:
            return
        self.edit = on
        self._apply_flags()
        self.update()

    # ---------- slepen en vergroten ----------
    def mousePressEvent(self, e):
        if not self.edit:
            return
        p = e.position()
        if p.x() > self.width() - 18 and p.y() > self.height() - 18:
            self._resize = (e.globalPosition(), self.scale)
        else:
            self._drag = e.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            np = e.globalPosition() - self._drag
            self.move(int(np.x()), int(np.y()))
        elif self._resize is not None:
            start, sc = self._resize
            dx = e.globalPosition().x() - start.x()
            self.scale = max(0.5, min(3.0, sc + dx / self.BASE[0]))
            self._fit()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None or self._resize is not None:
            self._drag = self._resize = None
            self.mgr.remember(self)

    # ---------- tekenen ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.scale, self.scale)
        W, H = self.BASE
        bg = QColor(BG)
        bg.setAlpha(int(255 * self.mgr.opacity))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 8, 8)
        p.fillPath(path, bg)
        data = self.mgr.data_for(self)
        try:
            if data is None:
                p.setPen(MUTED)
                p.setFont(font(12))
                p.drawText(QRectF(0, 0, W, H), Qt.AlignCenter, f"{self.TITLE}\nwacht op iRacing")
            else:
                self.draw(p, W, H, data)
        except Exception as ex:   # nooit het programma laten vallen op een tekenfout
            p.setPen(BAD)
            p.setFont(font(10))
            p.drawText(QRectF(6, 6, W - 12, H - 12), Qt.AlignLeft | Qt.TextWordWrap, f"{self.TITLE}: {ex}")
        if self.edit:
            p.setPen(QPen(ACCENT, 1.5, Qt.DashLine))
            p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 8, 8)
            p.setFont(font(10, True))
            p.fillRect(QRectF(8, H - 20, p.fontMetrics().horizontalAdvance(self.TITLE) + 10, 16), ACCENT)
            p.setPen(QColor("#111"))
            p.drawText(QRectF(13, H - 20, 300, 16), Qt.AlignVCenter, self.TITLE)
            p.setPen(QPen(ACCENT, 2))
            for k in (5, 10):
                p.drawLine(QPointF(W - 3, H - 3 - k), QPointF(W - 3 - k, H - 3))
        p.end()

    def draw(self, p, W, H, d):
        pass

    # hulpjes
    @staticmethod
    def text(p, x, y, w, h, s, color=TXT, f=None, align=Qt.AlignLeft | Qt.AlignVCenter):
        if f is not None:
            p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(x, y, w, h), align, s)

    @staticmethod
    def header(p, W, title, right=""):
        p.setFont(font(11, True))
        p.setPen(ACCENT)
        p.drawText(QRectF(10, 4, W - 20, 18), Qt.AlignLeft | Qt.AlignVCenter, title.upper())
        if right:
            p.setPen(MUTED)
            p.setFont(font(11))
            p.drawText(QRectF(10, 4, W - 20, 18), Qt.AlignRight | Qt.AlignVCenter, right)


# ======================================================================
#  1. Relative
# ======================================================================
class RelativeOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "relative", "Relative", (380, 238), (0.01, 0.75)

    def draw(self, p, W, H, d):
        rows = d.get("relative") or []
        self.header(p, W, "Relative", f"ronde {d.get('ronde')}" + (f"/{d['totaal']}" if d.get("totaal") else ""))
        y, rh = 26, 22
        for r in rows[:9]:
            if r["jij"]:
                p.fillRect(QRectF(4, y, W - 8, rh), ME_BG)
            elif rows.index(r) % 2:
                p.fillRect(QRectF(4, y, W - 8, rh), ROW)
            col = TXT
            if r["ronde"] == 1:
                col = BAD       # ligt een ronde voor: laat gaan
            elif r["ronde"] == -1:
                col = INFO      # ronde achter
            if r["pit"]:
                col = MUTED
            p.fillRect(QRectF(6, y + 3, 4, rh - 6), QColor(r["kleur"]))
            self.text(p, 14, y, 30, rh, f"P{r['pos']}" if r["pos"] else "", col, font(12, True))
            self.text(p, 46, y, 40, rh, f"#{r['nr']}", MUTED, font(12))
            name = r["naam"] if len(r["naam"]) < 22 else r["kort"]
            self.text(p, 86, y, 170, rh, name + ("  PIT" if r["pit"] else ""), col, font(12, r["jij"]))
            if r["ir"]:
                lic = (r["lic"] or " ")[0]
                self.text(p, 238, y, 70, rh, f"{lic} {r['ir'] / 1000:.1f}k".replace(".", ","), MUTED, font(11),
                          Qt.AlignRight | Qt.AlignVCenter)
            self.text(p, 310, y, 62, rh, "" if r["jij"] else fmt_gap(r["gap"]), col, font(12, True, True),
                      Qt.AlignRight | Qt.AlignVCenter)
            y += rh


# ======================================================================
#  2. Stand (verticaal)
# ======================================================================
class StandingsOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "stand", "Stand", (420, 430), (0.01, 0.08)

    def _pick(self, rows, n):
        """Top 3 + rond jou, zoals je gewend bent."""
        me = next((i for i, r in enumerate(rows) if r["jij"]), None)
        if me is None or len(rows) <= n:
            return rows[:n]
        keep = set(range(3))
        a = max(3, min(me - (n - 3) // 2, len(rows) - (n - 3)))
        keep |= set(range(a, a + n - 3))
        return [rows[i] for i in sorted(keep) if i < len(rows)]

    def draw(self, p, W, H, d):
        groups = d.get("stand") or []
        tl = d.get("tijd_over")
        right = (f"{int(tl // 3600)}:{int(tl % 3600 // 60):02d}:{int(tl % 60):02d}" if tl else "")
        self.header(p, W, d.get("sessie") or "Stand", right)
        y, rh = 26, 20
        space = int((H - 30) / rh)
        own = next((g for g in groups if g["eigen"]), None)
        others = [g for g in groups if not g["eigen"]]
        n_own = max(5, space - (len(others) * 4))
        for g in ([own] if own else []) + others:
            n = n_own if g["eigen"] else 3
            if y + rh * 2 > H:
                break
            p.fillRect(QRectF(4, y, W - 8, rh - 2), QColor(g["kleur"]).darker(260))
            self.text(p, 10, y, 200, rh - 2, g["klasse"], QColor(g["kleur"]), font(11, True))
            self.text(p, 230, y, 80, rh - 2, "beste", MUTED, font(10), Qt.AlignRight | Qt.AlignVCenter)
            self.text(p, 320, y, 90, rh - 2, "gap", MUTED, font(10), Qt.AlignRight | Qt.AlignVCenter)
            y += rh
            prev = None
            for r in self._pick(g["auto"], n):
                if y + rh > H - 4:
                    break
                if prev is not None and r["pos"] and prev["pos"] and r["pos"] - prev["pos"] > 1:
                    p.setPen(QPen(MUTED, 1, Qt.DotLine))
                    p.drawLine(QPointF(14, y), QPointF(W - 14, y))
                if r["jij"]:
                    p.fillRect(QRectF(4, y, W - 8, rh), ME_BG)
                col = MUTED if r["pit"] else TXT
                self.text(p, 10, y, 28, rh, str(r["pos"] or ""), col, font(12, True), Qt.AlignRight | Qt.AlignVCenter)
                self.text(p, 44, y, 40, rh, f"#{r['nr']}", MUTED, font(11))
                self.text(p, 84, y, 150, rh, (r["naam"] if len(r["naam"]) < 20 else r["kort"]) +
                          (" PIT" if r["pit"] else ""), col, font(12, r["jij"]))
                self.text(p, 230, y, 80, rh, fmt_t(r["beste"]), MUTED, font(11, False, True), Qt.AlignRight | Qt.AlignVCenter)
                gap = r["gap"]
                gtxt = "leider" if gap == 0 else fmt_gap(gap, 1 if d.get("race") else 3)
                self.text(p, 320, y, 90, rh, gtxt, col, font(12, False, True), Qt.AlignRight | Qt.AlignVCenter)
                y += rh
                prev = r
            y += 4


# ======================================================================
#  3. Stand (horizontaal)
# ======================================================================
class TickerOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "ticker", "Stand horizontaal", (1100, 44), (0.5, 0.0)

    def draw(self, p, W, H, d):
        own = next((g for g in d.get("stand") or [] if g["eigen"]), None)
        if not own:
            return
        rows = own["auto"]
        me = next((i for i, r in enumerate(rows) if r["jij"]), 0)
        n = 7
        a = max(0, min(me - n // 2, len(rows) - n))
        sel = rows[a:a + n]
        cw = (W - 70) / max(1, len(sel))
        p.fillRect(QRectF(4, 6, 56, H - 12), QColor(own["kleur"]).darker(240))
        self.text(p, 4, 6, 56, H - 12, own["klasse"], QColor(own["kleur"]), font(12, True), Qt.AlignCenter)
        x = 66
        for r in sel:
            if r["jij"]:
                p.fillRect(QRectF(x, 6, cw - 4, H - 12), ME_BG)
            else:
                p.fillRect(QRectF(x, 6, cw - 4, H - 12), ROW)
            self.text(p, x + 5, 6, 30, H - 12, f"P{r['pos']}", ACCENT if r["jij"] else TXT, font(13, True))
            g = r["gap"]
            gtxt = "" if r["jij"] else ("" if g == 0 else fmt_gap(g))
            gw = 44 if gtxt else 0
            nm = p.fontMetrics()
            p.setFont(font(12, r["jij"]))
            name = p.fontMetrics().elidedText(r["kort"], Qt.ElideRight, int(cw - 40 - gw - 8))
            self.text(p, x + 36, 6, cw - 40 - gw, H - 12, name, TXT)
            if gtxt:
                self.text(p, x + cw - gw - 8, 6, gw, H - 12, gtxt, MUTED, font(11, False, True), Qt.AlignRight | Qt.AlignVCenter)
            x += cw


# ======================================================================
#  4. Sectoren tegen voor en achter
# ======================================================================
class SectorsOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "sectoren", "Sectoren", (380, 136), (0.99, 0.08)

    def draw(self, p, W, H, d):
        s = d.get("sectoren") or {}
        n = s.get("aantal") or 3
        self.header(p, W, "Sectoren", "vorige ronde")
        mine = (s.get("jij") or {}).get("vorige") or [None] * n
        best = (s.get("jij") or {}).get("beste") or [None] * n
        x0, cw = 110, (W - 120) / n
        y = 26
        for k in range(n):
            self.text(p, x0 + k * cw, y, cw, 16, f"S{k + 1}", MUTED, font(10, True), Qt.AlignCenter)
        y += 18
        # jij: eigen tijd, paars = je beste sector
        self.text(p, 10, y, 100, 22, "Jij", ACCENT, font(12, True))
        for k in range(n):
            t = mine[k] if k < len(mine) else None
            col = PURPLE if (t and best[k] and abs(t - best[k]) < 0.0005) else TXT
            self.text(p, x0 + k * cw, y, cw, 22, fmt_t(t), col, font(12, False, True), Qt.AlignCenter)
        y += 24
        for key, label in (("voor", "Voor"), ("achter", "Achter")):
            o = s.get(key)
            if not o:
                self.text(p, 10, y, 100, 22, f"{label}: –", MUTED, font(12))
                y += 24
                continue
            gap = s.get("gap_" + key)
            p.setFont(font(12))
            self.text(p, 10, y, 62, 22, p.fontMetrics().elidedText(o["naam"], Qt.ElideRight, 60), TXT)
            if gap is not None:
                self.text(p, 66, y, 42, 22, fmt_gap(gap), MUTED, font(10, False, True), Qt.AlignRight | Qt.AlignVCenter)
            theirs = o.get("vorige") or [None] * n
            for k in range(n):
                a = mine[k] if k < len(mine) else None
                b = theirs[k] if k < len(theirs) else None
                if a is None or b is None:
                    self.text(p, x0 + k * cw, y, cw, 22, "–", MUTED, font(12), Qt.AlignCenter)
                    continue
                diff = a - b       # + = jij langzamer
                col = BAD if diff > 0.02 else (GOOD if diff < -0.02 else MUTED)
                self.text(p, x0 + k * cw, y, cw, 22, fmt_gap(diff, 2), col, font(12, True, True), Qt.AlignCenter)
            y += 24


# ======================================================================
#  5. Invoer (gas, rem, stuur)
# ======================================================================
class InputsOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "invoer", "Invoer", (420, 110), (0.5, 0.97)

    def draw(self, p, W, H, d):
        hist = list(self.mgr.input_hist())
        live = self.mgr.live() or {}
        gx, gy, gw, gh = 8, 8, W - 130, H - 16
        p.fillRect(QRectF(gx, gy, gw, gh), QColor(255, 255, 255, 8))
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(gx, gy + gh * f), QPointF(gx + gw, gy + gh * f))
        if len(hist) > 2:
            n = len(hist)
            smax = live.get("stuur_max") or 4.7
            series = ((lambda h: 0.5 + 0.5 * max(-1, min(1, h[3] / smax)), QColor(255, 255, 255, 140), 1.2),
                      (lambda h: h[1], BAD, 2.0), (lambda h: h[0], GOOD, 2.0))
            for fn, col, wpen in series:
                path = QPainterPath()
                for i, h in enumerate(hist):
                    x = gx + gw * i / max(1, n - 1)
                    y = gy + gh * (1 - fn(h))
                    (path.moveTo if i == 0 else path.lineTo)(x, y)
                p.setPen(QPen(col, wpen))
                p.drawPath(path)
        # balken
        bx = W - 116
        clutch = live.get("koppeling")
        bars = [(1 - clutch if clutch is not None else 0, INFO), (live.get("rem") or 0, BAD), (live.get("gas") or 0, GOOD)]
        for i, (v, col) in enumerate(bars):
            x = bx + i * 14
            p.fillRect(QRectF(x, gy, 10, gh), QColor(255, 255, 255, 18))
            c = QColor(col)
            if i == 1 and live.get("abs"):
                c = QColor("#FFD400")
            p.fillRect(QRectF(x, gy + gh * (1 - v), 10, gh * v), c)
        # versnelling en snelheid
        g = live.get("versnelling")
        gtxt = "R" if g == -1 else ("N" if not g else str(g))
        self.text(p, W - 72, gy, 64, 46, gtxt, TXT, font(38, True), Qt.AlignCenter)
        self.text(p, W - 72, gy + 48, 64, 22, f"{live.get('snelheid') or 0:.0f}", TXT, font(16, True, True), Qt.AlignCenter)
        self.text(p, W - 72, gy + 68, 64, 14, "km/u", MUTED, font(10), Qt.AlignCenter)


# ======================================================================
#  6. Delta tegen je beste ronde
# ======================================================================
class DeltaOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "delta", "Delta", (360, 84), (0.5, 0.07)

    def draw(self, p, W, H, d):
        dl = d.get("delta") or {}
        delta = dl.get("delta")
        # balk: ±1 s, midden = gelijk
        bx, by, bw, bh = 10, 8, W - 20, 14
        p.fillRect(QRectF(bx, by, bw, bh), QColor(255, 255, 255, 18))
        mid = bx + bw / 2
        if delta is not None:
            f = max(-1.0, min(1.0, delta / 1.0))
            col = BAD if delta > 0 else GOOD
            if f > 0:
                p.fillRect(QRectF(mid, by, bw / 2 * f, bh), col)
            else:
                p.fillRect(QRectF(mid + bw / 2 * f, by, -bw / 2 * f, bh), col)
        p.fillRect(QRectF(mid - 1, by - 2, 2, bh + 4), TXT)
        col = TXT if delta is None else (BAD if delta > 0 else GOOD)
        self.text(p, 10, 26, 130, 34, fmt_gap(delta, 2) if delta is not None else "–", col, font(26, True, True))
        self.text(p, 150, 26, 200, 16, "voorspeld  " + fmt_t(dl.get("voorspelling")), TXT, font(12, False, True),
                  Qt.AlignRight | Qt.AlignVCenter)
        self.text(p, 150, 44, 200, 16, "beste  " + fmt_t(dl.get("beste")), PURPLE, font(12, False, True),
                  Qt.AlignRight | Qt.AlignVCenter)
        self.text(p, 150, 62, 200, 16, "laatste  " + fmt_t(dl.get("laatste")), MUTED, font(12, False, True),
                  Qt.AlignRight | Qt.AlignVCenter)
        self.text(p, 10, 62, 140, 16, "t.o.v. je beste ronde", MUTED, font(10))


# ======================================================================
#  7. Brandstof en strategie
# ======================================================================
class FuelOverlay(Overlay):
    NAME, TITLE, BASE, DEFAULT_POS = "brandstof", "Brandstof", (300, 186), (0.99, 0.35)

    def draw(self, p, W, H, d):
        f = d.get("brandstof") or {}
        self.header(p, W, "Brandstof", f"ronde {f.get('ronde', '')}")
        liter, tank = f.get("liter"), f.get("tank")
        # tankbalk
        p.fillRect(QRectF(10, 26, W - 20, 8), QColor(255, 255, 255, 18))
        if liter is not None and tank:
            fr = max(0.0, min(1.0, liter / tank))
            p.fillRect(QRectF(10, 26, (W - 20) * fr, 8), ACCENT if fr > 0.15 else BAD)

        def num(x, dec=1, unit=""):
            return "–" if x is None else (f"{x:.{dec}f}".replace(".", ",") + unit)

        rows = [
            ("In de tank", num(liter, 1, " L")),
            ("Per ronde (gem.)", num(f.get("per_ronde"), 2, " L")),
            ("Vorige ronde", num(f.get("laatste_ronde"), 2, " L")),
            ("Ronden in tank", num(f.get("ronden_in_tank"), 1)),
            ("Ronden te gaan", num(f.get("ronden_te_gaan"), 1)),
        ]
        stops = f.get("stops")
        if stops == 0 and f.get("overschot") is not None:
            rows.append(("Tot de finish", "haalt het, " + num(f.get("overschot"), 1, " L over")))
        elif stops:
            v = f.get("venster") or (None, None)
            rows.append(("Stops nodig", f"{stops}  ·  venster R{v[0]}–R{v[1]}" if v[0] else str(stops)))
            rows.append(("Bijtanken bij stop", num(f.get("bijtanken"), 1, " L")))
            if f.get("besparen_pct") is not None and 0 < f["besparen_pct"] < 15:
                rows.append(("Zonder stop", f"{num(f.get('doel_zonder_stop'), 2)} L/ronde (−{num(f['besparen_pct'], 0)}%)"))
        y = 40
        for k, v in rows[:7]:
            self.text(p, 10, y, 140, 18, k, MUTED, font(12))
            warn = k == "Ronden in tank" and f.get("ronden_in_tank") is not None and f.get("ronden_te_gaan") is not None \
                and f["ronden_in_tank"] < f["ronden_te_gaan"]
            self.text(p, 140, y, W - 150, 18, v, BAD if warn else TXT, font(12, True), Qt.AlignRight | Qt.AlignVCenter)
            y += 18


ALL = [RelativeOverlay, StandingsOverlay, TickerOverlay, SectorsOverlay, InputsOverlay, DeltaOverlay, FuelOverlay]


# ======================================================================
#  Voorbeeldgegevens (om te verplaatsen zonder iRacing)
# ======================================================================
def sample_data():
    names = ["Max de Boer", "Lars Jansen", "Tom Visser", "Jij", "Sven Bakker", "Bas Kok", "Pim van Dijk"]
    gt3 = [{"idx": i, "pos": i + 1, "nr": str(10 + i), "naam": n, "kort": n.split()[-1], "klasse": "GT3",
            "kleur": "#33CEFF", "ir": 2100 + 50 * i, "lic": "A 3.1", "pit": i == 5, "jij": n == "Jij",
            "laatste": 92.4 + i * 0.1, "beste": 91.9 + i * 0.12, "stops": 0, "gap": round(i * 1.7, 1)} for i, n in enumerate(names)]
    gtp = [{"idx": 20 + i, "pos": i + 1, "nr": str(1 + i), "naam": n, "kort": n.split()[-1], "klasse": "GTP",
            "kleur": "#FFDA59", "ir": 3000, "lic": "A 4.0", "pit": False, "jij": False, "laatste": 84.1,
            "beste": 83.6 + i * 0.2, "stops": 0, "gap": round(i * 2.3, 1)} for i, n in enumerate(["Anna Brouwer", "Kees Dekker", "Rik Hendriks"])]
    rel = []
    for k, r in enumerate([gtp[0], gt3[1], gt3[2], gt3[3], gt3[4], gtp[1], gt3[6]]):
        x = dict(r)
        x["gap"] = [4.2, 2.6, 0.9, 0.0, -1.1, -2.4, -4.0][k]
        x["ronde"] = 1 if x["klasse"] == "GTP" else 0
        rel.append(x)
    return {
        "relative": rel, "sessie": "Race", "race": True, "ronde": 12, "totaal": 30, "tijd_over": 1830,
        "stand": [{"klasse": "GT3", "kleur": "#33CEFF", "eigen": True, "auto": gt3},
                  {"klasse": "GTP", "kleur": "#FFDA59", "eigen": False, "auto": gtp}],
        "sectoren": {"aantal": 3, "jij": {"naam": "Jij", "vorige": [31.204, 33.870, 27.115], "beste": [31.204, 33.6, 27.0]},
                     "voor": {"naam": "Visser", "vorige": [31.05, 34.02, 27.10]},
                     "achter": {"naam": "Bakker", "vorige": [31.40, 33.75, 27.35]},
                     "gap_voor": 0.9, "gap_achter": -1.1},
        "delta": {"delta": -0.184, "voorspelling": 91.716, "beste": 91.9, "laatste": 92.31},
        "brandstof": {"liter": 41.2, "tank": 100, "per_ronde": 3.12, "laatste_ronde": 3.08, "ronden_in_tank": 13.2,
                      "ronden_te_gaan": 18.0, "stops": 1, "venster": (16, 24), "bijtanken": 18.4,
                      "besparen_pct": 26.0, "ronde": 12},
    }


def sample_inputs():
    import collections
    h = collections.deque(maxlen=480)
    for i in range(480):
        t = i / 60
        ph = (t % 4) / 4
        thr = 1.0 if ph < 0.55 else (0.0 if ph < 0.75 else min(1, (ph - 0.75) * 4))
        brk = max(0.0, 1 - (ph - 0.55) * 6) if 0.55 <= ph < 0.72 else 0.0
        h.append((thr, brk, 1.0, 1.6 * math.sin(math.pi * max(0, ph - 0.58) / 0.42) if ph > 0.58 else 0.0))
    return h


# ======================================================================
#  Beheer
# ======================================================================
class OverlayManager:
    def __init__(self, win):
        self.win = win
        self.windows = {}
        self.editing = False
        self._sample, self._sample_in = sample_data(), sample_inputs()
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.apply()

    @property
    def cfg(self):
        return self.win.cfg.setdefault("overlays", {})

    @property
    def opacity(self):
        return float(self.cfg.get("doorzichtig", 0.82))

    def enabled(self, name):
        return bool((self.cfg.get("aan") or {}).get(name, False))

    def apply(self):
        """Vensters maken of weghalen volgens de instellingen."""
        for cls in ALL:
            want = self.cfg.get("ingeschakeld", False) and self.enabled(cls.NAME)
            w = self.windows.get(cls.NAME)
            if want and w is None:
                w = cls(self)
                w.set_edit(self.editing)
                self.windows[cls.NAME] = w
            elif not want and w is not None:
                w.close()
                w.deleteLater()
                del self.windows[cls.NAME]

    def set_edit(self, on):
        self.editing = on
        for w in self.windows.values():
            w.set_edit(on)

    def remember(self, w):
        self.cfg.setdefault("vensters", {})[w.NAME] = [w.x(), w.y(), round(w.scale, 3)]
        self.win.save_cfg(self.win.cfg)

    def reset_positions(self):
        self.cfg["vensters"] = {}
        for name in list(self.windows):
            self.windows[name].close()
            self.windows[name].deleteLater()
        self.windows = {}
        self.apply()
        self.win.save_cfg(self.win.cfg)

    # gegevens
    def _live_ok(self):
        eng = self.win.engine
        return eng.running and eng.overlay is not None

    def data_for(self, _w):
        if self._live_ok():
            return self.win.engine.overlay
        return self._sample if self.editing else None

    def live(self):
        return self.win.engine.live if self._live_ok() else ({"gas": 0.8, "rem": 0, "koppeling": 1.0, "versnelling": 4,
                                                              "snelheid": 187} if self.editing else {})

    def input_hist(self):
        return self.win.engine.input_hist if self._live_ok() else (self._sample_in if self.editing else [])

    def tick(self):
        eng = self.win.engine
        in_car = (eng.live or {}).get("in_auto", True) if self._live_ok() else False
        only_car = self.cfg.get("alleen_in_auto", True)
        show = self.editing or (self._live_ok() and (in_car or not only_car))
        for w in self.windows.values():
            if show and not w.isVisible():
                w.show()
            elif not show and w.isVisible():
                w.hide()
            if show:
                w.update()

    def close_all(self):
        self.timer.stop()
        for w in self.windows.values():
            w.close()


# ======================================================================
#  Pagina in het programma
# ======================================================================
class OverlayPage(QWidget):
    LABELS = {
        "relative": ("Relative", "Auto's direct voor en achter je op de baan, met gap, klasse en iRating."),
        "stand": ("Stand", "Stand per klasse: top 3 en de auto's rond jou, met beste ronde en gap."),
        "ticker": ("Stand horizontaal", "Een balk met jouw klasse rond jouw positie, bovenin beeld."),
        "sectoren": ("Sectoren", "Jouw sectortijden tegen de auto voor en achter je (groen = jij sneller)."),
        "invoer": ("Invoer", "Gas, rem, koppeling en stuur als lopende lijn, met versnelling en snelheid."),
        "delta": ("Delta", "Live sneller of langzamer dan je beste ronde, met voorspelde rondetijd."),
        "brandstof": ("Brandstof", "Verbruik, ronden in de tank, stops, pitvenster en hoeveel je moet tanken."),
    }

    def __init__(self, win, lab, card):
        super().__init__()
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(lab("Overlays", "h1"))
        root.addWidget(lab("Informatie bovenop iRacing. Zet iRacing in de grafische instellingen op "
                           "'Windowed' zonder rand (borderless), anders verdwijnen de overlays achter het spel.",
                           "sub", wrap=True))
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(16, 14, 16, 14)
        g.setVerticalSpacing(8)
        self.master = QCheckBox("Overlays gebruiken")
        g.addWidget(self.master, 0, 0, 1, 2)
        self.checks = {}
        for i, (name, (title, desc)) in enumerate(self.LABELS.items(), start=1):
            cb = QCheckBox(title)
            self.checks[name] = cb
            g.addWidget(cb, i, 0)
            g.addWidget(lab(desc, "sub", wrap=True), i, 1)
            cb.toggled.connect(self._changed)
        self.master.toggled.connect(self._changed)
        g.setColumnStretch(1, 1)
        root.addWidget(c)

        c2 = card()
        v = QVBoxLayout(c2)
        v.setContentsMargins(16, 14, 16, 14)
        row = QHBoxLayout()
        self.edit_btn = QPushButton("Overlays verplaatsen")
        self.edit_btn.setObjectName("primary")
        self.edit_btn.setCheckable(True)
        self.edit_btn.toggled.connect(self._edit)
        reset = QPushButton("Standaardplekken")
        reset.clicked.connect(lambda: self.win.overlays.reset_positions())
        row.addWidget(self.edit_btn)
        row.addWidget(reset)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(lab("Klik op 'Overlays verplaatsen', sleep ze waar je wilt en trek aan de hoek rechtsonder om ze "
                        "groter of kleiner te maken. Klik daarna nog een keer om ze vast te zetten. Tijdens het rijden "
                        "klik je er gewoon doorheen.", "sub", wrap=True))
        h = QHBoxLayout()
        h.addWidget(lab("Achtergrond", "sub"))
        self.op = QSlider(Qt.Horizontal)
        self.op.setRange(20, 100)
        self.op.valueChanged.connect(self._changed)
        h.addWidget(self.op, 1)
        v.addLayout(h)
        self.only_car = QCheckBox("Alleen laten zien als ik in de auto zit")
        self.only_car.toggled.connect(self._changed)
        v.addWidget(self.only_car)
        root.addWidget(c2)
        root.addStretch(1)
        self._loading = False

    def load(self, cfg):
        self._loading = True
        o = cfg.setdefault("overlays", {})
        self.master.setChecked(bool(o.get("ingeschakeld", False)))
        aan = o.get("aan") or {}
        for name, cb in self.checks.items():
            cb.setChecked(bool(aan.get(name, False)))
        self.op.setValue(int(100 * float(o.get("doorzichtig", 0.82))))
        self.only_car.setChecked(bool(o.get("alleen_in_auto", True)))
        self._loading = False

    def _changed(self, *_):
        if self._loading:
            return
        o = self.win.cfg.setdefault("overlays", {})
        o["ingeschakeld"] = self.master.isChecked()
        o["aan"] = {n: cb.isChecked() for n, cb in self.checks.items()}
        o["doorzichtig"] = self.op.value() / 100
        o["alleen_in_auto"] = self.only_car.isChecked()
        self.win.save_cfg(self.win.cfg)
        self.win.overlays.apply()

    def _edit(self, on):
        self.edit_btn.setText("Klaar met verplaatsen" if on else "Overlays verplaatsen")
        self.win.overlays.set_edit(on)
