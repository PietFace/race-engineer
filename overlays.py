"""Overlays: doorzichtige vensters boven iRacing (iRacing in 'venster zonder rand' / borderless).

Elke overlay heeft eigen opties (kolommen, aantal rijen, onderdelen) die je in het programma aan- en uitzet.
'Verplaatsen' zet ze in bewerk-stand: slepen en aan de hoek trekken om te vergroten. Daarna klik je erdoorheen.
Alles wordt bewaard in cfg["overlays"]: aan/uit, posities ('vensters') en opties ('opties').
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

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
LIC_COL = {"R": "#E0463C", "D": "#FF8A00", "C": "#F2C200", "B": "#36C26E", "A": "#3E86E6", "P": "#BBBBBB",
           "PWC": "#BBBBBB"}

L, R, C = Qt.AlignLeft | Qt.AlignVCenter, Qt.AlignRight | Qt.AlignVCenter, Qt.AlignCenter


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


def opt_bool(key, label, default, group="Weergave"):
    return {"key": key, "label": label, "type": "bool", "default": default, "group": group}


def opt_int(key, label, default, lo, hi, group="Weergave"):
    return {"key": key, "label": label, "type": "int", "default": default, "min": lo, "max": hi, "group": group}


def opt_choice(key, label, default, choices, group="Weergave"):
    return {"key": key, "label": label, "type": "choice", "default": default, "choices": choices, "group": group}


# ======================================================================
#  Kolommen voor de tabellen (relative en stand)
# ======================================================================
def _col_vs(r, o):
    """Verschil in rondetijd met jou. Groen = jij sneller, rood = jij langzamer."""
    v = r.get("vs_beste" if o("verschil_met") == "beste" else "vs_laatste")
    if r["jij"] or v is None:
        return "", MUTED
    return f"{abs(v):.{o('verschil_dec')}f}".replace(".", ","), GOOD if v > 0 else (BAD if v < 0 else MUTED)


def _col_sr(r, o):
    if not r.get("lic_klasse"):
        return "", MUTED
    sr = r.get("sr")
    return (r["lic_klasse"] + (f" {sr:.2f}".replace(".", ",") if sr is not None else "")), \
        QColor(LIC_COL.get(r["lic_klasse"], "#BBBBBB"))


def _col_ird(r, o):
    v = r.get("ir_delta")
    if v is None:
        return "", MUTED
    return (f"+{v}" if v > 0 else str(v).replace("-", "−")), GOOD if v > 0 else (BAD if v < 0 else MUTED)


def _col_plekken(r, o):
    v = r.get("plekken")
    if not v:
        return ("0" if v == 0 else ""), MUTED
    return (f"▲{v}" if v > 0 else f"▼{-v}"), GOOD if v > 0 else BAD


def _col_gap(key):
    def f(r, o):
        g = r.get(key)
        if key == "gap" and g == 0:
            return "leider", MUTED
        if r["jij"] and key != "gap":
            return "", MUTED
        dec = 1 if o("_race") else 3
        return fmt_gap(g, dec), TXT
    return f


def _col_rel_gap(r, o):
    if r["jij"]:
        return "", TXT
    return fmt_gap(r.get("gap")), TXT


COLUMNS = {
    # sleutel: (kop, breedte, uitlijning, functie(rij, optie) -> (tekst, kleur), lettertype)
    "pos": ("Pos", 32, R, lambda r, o: (str(r["pos"] or ""), TXT), "bold"),
    "nr": ("#", 40, L, lambda r, o: (f"#{r['nr']}", MUTED), ""),
    "naam": ("Naam", 150, L, lambda r, o: (r["naam"] if len(r["naam"]) <= 22 else r["kort"], TXT), "naam"),
    "auto": ("Auto", 120, L, lambda r, o: (r.get("auto") or "", MUTED), "klein"),
    "ir": ("iRating", 52, R, lambda r, o: ((str(r["ir"]) if o("ir_vol") else f"{r['ir'] / 1000:.1f}k".replace(".", ","))
                                         if r.get("ir") else "", MUTED), ""),
    "sr": ("Licentie", 62, C, _col_sr, "klein"),
    "ir_delta": ("±iR", 46, R, _col_ird, "bold"),
    "laatste": ("Laatste", 70, R, lambda r, o: (fmt_t(r.get("laatste")), MUTED), "mono"),
    "beste": ("Beste", 70, R, lambda r, o: (fmt_t(r.get("beste")), MUTED), "mono"),
    "verschil": ("Verschil", 58, R, _col_vs, "monobold"),
    "gap": ("Gap", 64, R, _col_gap("gap"), "mono"),
    "interval": ("Interval", 60, R, _col_gap("interval"), "mono"),
    "stops": ("Stops", 40, R, lambda r, o: (str(r.get("stops") or 0), MUTED), ""),
    "plekken": ("+/−", 40, R, _col_plekken, "bold"),
    "relgap": ("Gap", 60, R, _col_rel_gap, "monobold"),
}
COL_LABELS = {
    "pos": "Positie", "nr": "Startnummer", "naam": "Naam", "auto": "Auto (merk/type)", "ir": "iRating",
    "sr": "Licentie en safety rating", "ir_delta": "iRating winst/verlies bij deze uitslag",
    "laatste": "Laatste ronde", "beste": "Beste ronde", "verschil": "Verschil in rondetijd met jou (groen = jij sneller)",
    "gap": "Gap tot de leider", "interval": "Interval tot de auto voor", "stops": "Aantal pitstops",
    "plekken": "Plekken gewonnen/verloren sinds de start", "relgap": "Gap tot jou",
}


def _font_for(kind, r):
    if kind == "bold":
        return font(12, True)
    if kind == "mono":
        return font(12, False, True)
    if kind == "monobold":
        return font(12, True, True)
    if kind == "klein":
        return font(11)
    if kind == "naam":
        return font(12, r["jij"])
    return font(12)


# ======================================================================
#  Basis
# ======================================================================
class Overlay(QWidget):
    NAME = "basis"
    TITLE = "Overlay"
    DEFAULT_POS = (0.0, 0.0)
    OPTIONS = []

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
        self.scale = max(0.5, min(3.0, geo[2])) if geo else 1.0
        self._size = None
        self._fit()
        x, y = (geo[0], geo[1]) if geo else self.default_pos()
        self.move(int(x), int(y))

    # ---------- opties ----------
    def o(self, key):
        if key == "_race":
            d = self.mgr.data_for(self) or {}
            return d.get("race")
        opts = (self.mgr.cfg.get("opties") or {}).get(self.NAME) or {}
        if key in opts:
            return opts[key]
        for spec in self.OPTIONS:
            if spec["key"] == key:
                return spec["default"]
        return None

    def base(self):
        return (300, 200)

    def default_pos(self):
        """DEFAULT_POS als fractie van het scherm (0..1)."""
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        g = scr.availableGeometry() if scr else None
        sw, sh = (g.width(), g.height()) if g else (1920, 1080)
        ox, oy = (g.x(), g.y()) if g else (0, 0)
        bw, bh = self.base()
        fx, fy = self.DEFAULT_POS
        return int(ox + max(0, fx * (sw - bw))), int(oy + max(0, fy * (sh - bh)))

    def _fit(self):
        b = self.base()
        if b != self._size or self.width() != int(b[0] * self.scale):
            self._size = b
            self.setFixedSize(int(b[0] * self.scale), int(b[1] * self.scale))

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
            self.scale = max(0.5, min(3.0, sc + dx / self.base()[0]))
            self._size = None
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
        W, H = self._size or self.base()
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
            tw = p.fontMetrics().horizontalAdvance(self.TITLE) + 10
            p.fillRect(QRectF(W - tw - 22, H - 20, tw, 16), ACCENT)
            p.setPen(QColor("#111"))
            p.drawText(QRectF(W - tw - 17, H - 20, tw, 16), Qt.AlignVCenter, self.TITLE)
            p.setPen(QPen(ACCENT, 2))
            for k in (5, 10):
                p.drawLine(QPointF(W - 3, H - 3 - k), QPointF(W - 3 - k, H - 3))
        p.end()

    def draw(self, p, W, H, d):
        pass

    @staticmethod
    def text(p, x, y, w, h, s, color=TXT, f=None, align=L):
        if f is not None:
            p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(x, y, w, h), align, s)

    def header(self, p, W, title, right=""):
        p.setFont(font(11, True))
        p.setPen(ACCENT)
        p.drawText(QRectF(10, 4, W - 20, 18), L, title.upper())
        if right:
            p.setPen(MUTED)
            p.setFont(font(11))
            p.drawText(QRectF(10, 4, W - 20, 18), R, right)


class TableOverlay(Overlay):
    """Overlay met kolommen die je zelf kiest."""
    COLS = []          # [(sleutel, standaard aan)]
    RH = 21

    def cols(self):
        return [k for k, _ in self.COLS if self.o("kol_" + k)]

    def table_width(self):
        return 16 + (6 if self.o("kleurbalk") else 0) + sum(COLUMNS[k][1] + 6 for k in self.cols())

    def col_titles(self, p, x0, y, h):
        x = x0
        for k in self.cols():
            title, w, al = COLUMNS[k][0], COLUMNS[k][1], COLUMNS[k][2]
            if k not in ("naam", "nr", "pos"):
                self.text(p, x, y, w, h, title, MUTED, font(10), al)
            x += w + 6

    def draw_row(self, p, x0, y, W, r, idx, color_override=None):
        rh = self.RH
        if r["jij"]:
            p.fillRect(QRectF(4, y, W - 8, rh), ME_BG)
        elif idx % 2:
            p.fillRect(QRectF(4, y, W - 8, rh), ROW)
        x = x0
        if self.o("kleurbalk"):
            p.fillRect(QRectF(x - 2, y + 3, 4, rh - 6), QColor(r["kleur"]))
            x += 6
        for k in self.cols():
            _t, w, al, fn, kind = COLUMNS[k]
            txt, col = fn(r, self.o)
            if color_override is not None and k in ("pos", "naam", "relgap", "gap"):
                col = color_override
            if r.get("pit") and k == "naam":
                txt += "  PIT"
                col = MUTED
            f = _font_for(kind, r)
            p.setFont(f)
            txt = p.fontMetrics().elidedText(txt, Qt.ElideRight, w)
            self.text(p, x, y, w, rh, txt, col, f, al)
            x += w + 6


# ======================================================================
#  1. Relative
# ======================================================================
class RelativeOverlay(TableOverlay):
    NAME, TITLE, DEFAULT_POS = "relative", "Relative", (0.01, 0.75)
    COLS = [("pos", True), ("nr", True), ("naam", True), ("auto", False), ("ir", True), ("sr", False),
            ("ir_delta", False), ("laatste", False), ("beste", False), ("verschil", False), ("relgap", True)]
    OPTIONS = ([opt_int("voor", "Auto's voor je", 4, 1, 8), opt_int("achter", "Auto's achter je", 4, 1, 8),
                opt_bool("alleen_klasse", "Alleen mijn klasse", False),
                opt_bool("kleurbalk", "Klassekleur", True), opt_bool("kop", "Kopregel met ronde", True),
                opt_bool("ir_vol", "iRating voluit (2345 in plaats van 2,3k)", False),
                opt_choice("verschil_met", "Verschil in rondetijd met", "laatste", ["laatste", "beste"]),
                opt_int("verschil_dec", "Decimalen bij verschil", 1, 1, 3)] +
               [opt_bool("kol_" + k, COL_LABELS[k], v, "Kolommen") for k, v in COLS])

    def base(self):
        rows = int(self.o("voor")) + int(self.o("achter")) + 1
        return (max(220, self.table_width()), (26 if self.o("kop") else 6) + rows * self.RH + 6)

    def draw(self, p, W, H, d):
        rows = d.get("relative") or []
        if self.o("alleen_klasse"):
            me = next((r for r in rows if r["jij"]), None)
            rows = [r for r in rows if me and r["klasse"] == me["klasse"]]
        i = next((k for k, r in enumerate(rows) if r["jij"]), 0)
        rows = rows[max(0, i - int(self.o("voor"))): i + int(self.o("achter")) + 1]
        y = 6
        if self.o("kop"):
            self.header(p, W, "Relative", f"ronde {d.get('ronde')}" + (f"/{d['totaal']}" if d.get("totaal") else ""))
            y = 26
        for n, r in enumerate(rows):
            col = None
            if r.get("ronde") == 1:
                col = BAD
            elif r.get("ronde") == -1:
                col = INFO
            self.draw_row(p, 10, y, W, r, n, col)
            y += self.RH


# ======================================================================
#  2. Stand
# ======================================================================
class StandingsOverlay(TableOverlay):
    NAME, TITLE, DEFAULT_POS = "stand", "Stand", (0.01, 0.08)
    COLS = [("pos", True), ("nr", True), ("naam", True), ("auto", False), ("ir", True), ("sr", True),
            ("ir_delta", True), ("laatste", False), ("beste", True), ("verschil", True), ("gap", True),
            ("interval", False), ("stops", False), ("plekken", False)]
    OPTIONS = ([opt_int("top", "Altijd de top", 3, 0, 10), opt_int("rond_mij", "Auto's rond mij", 6, 2, 20),
                opt_bool("andere_klassen", "Andere klassen laten zien", True),
                opt_int("per_klasse", "Auto's per andere klasse", 3, 1, 10),
                opt_bool("kleurbalk", "Klassekleur", False), opt_bool("klok", "Resterende tijd in de kop", True),
                opt_bool("koppen", "Kolomnamen", True),
                opt_bool("ir_vol", "iRating voluit (2345 in plaats van 2,3k)", True),
                opt_choice("verschil_met", "Verschil in rondetijd met", "laatste", ["laatste", "beste"]),
                opt_int("verschil_dec", "Decimalen bij verschil", 1, 1, 3)] +
               [opt_bool("kol_" + k, COL_LABELS[k], v, "Kolommen") for k, v in COLS])

    def _n_classes(self):
        d = self.mgr.data_for(self) or {}
        return max(1, len(d.get("stand") or []))

    def base(self):
        own = int(self.o("top")) + int(self.o("rond_mij"))
        others = (self._n_classes() - 1) * (int(self.o("per_klasse")) + 1) if self.o("andere_klassen") else 0
        rows = 1 + own + others
        return (max(260, self.table_width()), 30 + rows * self.RH + (self._n_classes() * 4))

    def _pick(self, rows, top, around):
        me = next((i for i, r in enumerate(rows) if r["jij"]), None)
        if me is None or len(rows) <= top + around:
            return rows[:top + around]
        keep = set(range(min(top, len(rows))))
        a = max(top, min(me - around // 2, len(rows) - around))
        keep |= set(range(a, a + around))
        return [rows[i] for i in sorted(keep) if i < len(rows)]

    def draw(self, p, W, H, d):
        groups = d.get("stand") or []
        tl = d.get("tijd_over")
        right = (f"{int(tl // 3600)}:{int(tl % 3600 // 60):02d}:{int(tl % 60):02d}" if tl and self.o("klok") else "")
        self.header(p, W, d.get("sessie") or "Stand", right)
        y, rh = 26, self.RH
        own = next((g for g in groups if g["eigen"]), None)
        others = [g for g in groups if not g["eigen"]] if self.o("andere_klassen") else []
        for g in ([own] if own else []) + others:
            if y + rh * 2 > H:
                break
            p.fillRect(QRectF(4, y, W - 8, rh - 2), QColor(g["kleur"]).darker(260))
            self.text(p, 10, y, 200, rh - 2, g["klasse"], QColor(g["kleur"]), font(11, True))
            if self.o("koppen"):
                self.col_titles(p, 10 + (6 if self.o("kleurbalk") else 0), y, rh - 2)
            y += rh
            if g["eigen"]:
                sel = self._pick(g["auto"], int(self.o("top")), int(self.o("rond_mij")))
            else:
                sel = g["auto"][:int(self.o("per_klasse"))]
            prev = None
            for n, r in enumerate(sel):
                if y + rh > H - 2:
                    break
                if prev is not None and r["pos"] and prev["pos"] and r["pos"] - prev["pos"] > 1:
                    p.setPen(QPen(MUTED, 1, Qt.DotLine))
                    p.drawLine(QPointF(14, y), QPointF(W - 14, y))
                self.draw_row(p, 10, y, W, r, n)
                y += rh
                prev = r
            y += 4


# ======================================================================
#  3. Stand horizontaal
# ======================================================================
class TickerOverlay(Overlay):
    NAME, TITLE, DEFAULT_POS = "ticker", "Stand horizontaal", (0.5, 0.0)
    OPTIONS = [opt_int("aantal", "Aantal auto's", 7, 3, 15), opt_int("breedte", "Breedte per auto", 150, 100, 260),
               opt_bool("klasse", "Klasse vooraan", True),
               opt_choice("tweede", "Onder de naam / ernaast", "gap",
                          ["gap", "interval", "verschil", "ir", "ir_delta", "niets"])]

    def base(self):
        return (int(self.o("aantal")) * int(self.o("breedte")) + (66 if self.o("klasse") else 6), 44)

    def draw(self, p, W, H, d):
        own = next((g for g in d.get("stand") or [] if g["eigen"]), None)
        if not own:
            return
        rows = own["auto"]
        me = next((i for i, r in enumerate(rows) if r["jij"]), 0)
        n = int(self.o("aantal"))
        a = max(0, min(me - n // 2, len(rows) - n))
        sel = rows[a:a + n]
        x = 6
        if self.o("klasse"):
            p.fillRect(QRectF(4, 6, 56, H - 12), QColor(own["kleur"]).darker(240))
            self.text(p, 4, 6, 56, H - 12, own["klasse"], QColor(own["kleur"]), font(12, True), C)
            x = 66
        cw = int(self.o("breedte"))
        what = self.o("tweede")
        for r in sel:
            p.fillRect(QRectF(x, 6, cw - 4, H - 12), ME_BG if r["jij"] else ROW)
            self.text(p, x + 5, 6, 34, H - 12, f"P{r['pos']}", ACCENT if r["jij"] else TXT, font(13, True))
            if what == "niets" or r["jij"]:
                txt, col = "", MUTED
            elif what in ("gap", "interval"):
                g = r.get(what)
                txt, col = ("" if g == 0 else fmt_gap(g, 1 if d.get("race") else 3)), MUTED
            else:
                txt, col = COLUMNS[what][3](r, self.o)
            gw = 50 if txt else 0
            p.setFont(font(12, r["jij"]))
            name = p.fontMetrics().elidedText(r["kort"], Qt.ElideRight, int(cw - 42 - gw - 8))
            self.text(p, x + 40, 6, cw - 42 - gw, H - 12, name, TXT)
            if txt:
                self.text(p, x + cw - gw - 8, 6, gw, H - 12, txt, col, font(11, False, True), R)
            x += cw

    def o(self, key):
        if key in ("ir_vol",):
            return False
        if key == "verschil_met":
            return "laatste"
        if key == "verschil_dec":
            return 1
        return super().o(key)


# ======================================================================
#  4. Sectoren
# ======================================================================
class SectorsOverlay(Overlay):
    NAME, TITLE, DEFAULT_POS = "sectoren", "Sectoren", (0.99, 0.08)
    OPTIONS = [opt_bool("voor", "Auto voor je", True), opt_bool("achter", "Auto achter je", True),
               opt_bool("beste", "Rij met je beste sectoren", True),
               opt_bool("huidig", "Rij met je huidige ronde", False),
               opt_choice("anderen", "Bij de andere auto's laten zien", "verschil", ["verschil", "tijden"]),
               opt_bool("gap", "Gap naast de naam", True)]

    def base(self):
        n = 1 + sum(1 for k in ("voor", "achter", "beste", "huidig") if self.o(k))
        return (380, 46 + n * 24)

    def draw(self, p, W, H, d):
        s = d.get("sectoren") or {}
        n = s.get("aantal") or 3
        self.header(p, W, "Sectoren", "vorige ronde")
        jij = s.get("jij") or {}
        mine = jij.get("vorige") or [None] * n
        best = jij.get("beste") or [None] * n
        x0, cw = 110, (W - 120) / n
        y = 26
        for k in range(n):
            self.text(p, x0 + k * cw, y, cw, 16, f"S{k + 1}", MUTED, font(10, True), C)
        y += 18

        def times_row(label, vals, color, is_best=False):
            nonlocal y
            self.text(p, 10, y, 100, 22, label, color, font(12, True))
            for k in range(n):
                t = vals[k] if k < len(vals) else None
                col = PURPLE if (not is_best and t and k < len(best) and best[k] and abs(t - best[k]) < 0.0005) else (
                    PURPLE if is_best else TXT)
                self.text(p, x0 + k * cw, y, cw, 22, fmt_t(t), col, font(12, False, True), C)
            y += 24

        times_row("Jij", mine, ACCENT)
        if self.o("huidig"):
            times_row("Nu", jij.get("nu") or [None] * n, MUTED)
        if self.o("beste"):
            times_row("Beste", best, PURPLE, True)
        for key in ("voor", "achter"):
            if not self.o(key):
                continue
            o = s.get(key)
            if not o:
                self.text(p, 10, y, 200, 22, ("Voor" if key == "voor" else "Achter") + ": niemand", MUTED, font(12))
                y += 24
                continue
            gap = s.get("gap_" + key)
            p.setFont(font(12))
            self.text(p, 10, y, 62, 22, p.fontMetrics().elidedText(o["naam"], Qt.ElideRight, 60), TXT)
            if gap is not None and self.o("gap"):
                self.text(p, 66, y, 42, 22, fmt_gap(gap), MUTED, font(10, False, True), R)
            theirs = o.get("vorige") or [None] * n
            for k in range(n):
                a = mine[k] if k < len(mine) else None
                b = theirs[k] if k < len(theirs) else None
                if self.o("anderen") == "tijden":
                    col = MUTED if a is None or b is None else (GOOD if b > a else BAD)
                    self.text(p, x0 + k * cw, y, cw, 22, fmt_t(b), col, font(12, False, True), C)
                    continue
                if a is None or b is None:
                    self.text(p, x0 + k * cw, y, cw, 22, "–", MUTED, font(12), C)
                    continue
                diff = a - b       # + = jij langzamer
                col = BAD if diff > 0.02 else (GOOD if diff < -0.02 else MUTED)
                self.text(p, x0 + k * cw, y, cw, 22, fmt_gap(diff, 2), col, font(12, True, True), C)
            y += 24


# ======================================================================
#  5. Invoer
# ======================================================================
class InputsOverlay(Overlay):
    NAME, TITLE, DEFAULT_POS = "invoer", "Invoer", (0.5, 0.97)
    OPTIONS = [opt_int("seconden", "Seconden in de grafiek", 8, 3, 12),
               opt_bool("lijn_gas", "Gas-lijn", True), opt_bool("lijn_rem", "Rem-lijn", True),
               opt_bool("lijn_stuur", "Stuur-lijn", True), opt_bool("koppeling", "Koppeling-balk", True),
               opt_bool("balken", "Pedaalbalken", True), opt_bool("versnelling", "Versnelling en snelheid", True),
               opt_bool("abs", "Rem geel kleuren als ABS ingrijpt", True)]

    def base(self):
        right = (14 * (3 if self.o("koppeling") else 2) + 6 if self.o("balken") else 0) + (72 if self.o("versnelling") else 0)
        return (300 + right, 110)

    def draw(self, p, W, H, d):
        hist = list(self.mgr.input_hist())
        n_keep = int(self.o("seconden")) * 60
        hist = hist[-n_keep:]
        live = self.mgr.live() or {}
        right = (14 * (3 if self.o("koppeling") else 2) + 6 if self.o("balken") else 0) + (72 if self.o("versnelling") else 0)
        gx, gy, gw, gh = 8, 8, W - 16 - right, H - 16
        p.fillRect(QRectF(gx, gy, gw, gh), QColor(255, 255, 255, 8))
        p.setPen(QPen(QColor(255, 255, 255, 25), 1))
        for f in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(gx, gy + gh * f), QPointF(gx + gw, gy + gh * f))
        if len(hist) > 2:
            n = len(hist)
            smax = live.get("stuur_max") or 4.7
            series = []
            if self.o("lijn_stuur"):
                series.append((lambda h: 0.5 + 0.5 * max(-1, min(1, h[3] / smax)), QColor(255, 255, 255, 140), 1.2))
            if self.o("lijn_rem"):
                series.append((lambda h: h[1], BAD, 2.0))
            if self.o("lijn_gas"):
                series.append((lambda h: h[0], GOOD, 2.0))
            for fn, col, wpen in series:
                path = QPainterPath()
                for i, h in enumerate(hist):
                    x = gx + gw * i / max(1, n - 1)
                    y = gy + gh * (1 - fn(h))
                    (path.moveTo if i == 0 else path.lineTo)(x, y)
                p.setPen(QPen(col, wpen))
                p.drawPath(path)
        x = gx + gw + 8
        if self.o("balken"):
            clutch = live.get("koppeling")
            bars = []
            if self.o("koppeling"):
                bars.append((1 - clutch if clutch is not None else 0, INFO))
            bars += [(live.get("rem") or 0, BAD), (live.get("gas") or 0, GOOD)]
            for v, col in bars:
                p.fillRect(QRectF(x, gy, 10, gh), QColor(255, 255, 255, 18))
                c = QColor(col)
                if col is BAD and live.get("abs") and self.o("abs"):
                    c = QColor("#FFD400")
                p.fillRect(QRectF(x, gy + gh * (1 - v), 10, gh * v), c)
                x += 14
            x += 2
        if self.o("versnelling"):
            g = live.get("versnelling")
            gtxt = "R" if g == -1 else ("N" if not g else str(g))
            self.text(p, x, gy, 64, 46, gtxt, TXT, font(38, True), C)
            self.text(p, x, gy + 48, 64, 22, f"{live.get('snelheid') or 0:.0f}", TXT, font(16, True, True), C)
            self.text(p, x, gy + 68, 64, 14, "km/u", MUTED, font(10), C)


# ======================================================================
#  6. Delta
# ======================================================================
class DeltaOverlay(Overlay):
    NAME, TITLE, DEFAULT_POS = "delta", "Delta", (0.5, 0.07)
    OPTIONS = [opt_choice("bereik", "Bereik van de balk (seconden)", "1", ["0.5", "1", "2"]),
               opt_bool("balk", "Balk", True), opt_bool("voorspelling", "Voorspelde rondetijd", True),
               opt_bool("beste", "Beste ronde", True), opt_bool("laatste", "Laatste ronde", True)]

    def base(self):
        side = any(self.o(k) for k in ("voorspelling", "beste", "laatste"))
        return (360 if side else 170, 84 if self.o("balk") else 62)

    def draw(self, p, W, H, d):
        dl = d.get("delta") or {}
        delta = dl.get("delta")
        top = 6
        if self.o("balk"):
            rng = float(self.o("bereik"))
            bx, by, bw, bh = 10, 8, W - 20, 14
            p.fillRect(QRectF(bx, by, bw, bh), QColor(255, 255, 255, 18))
            mid = bx + bw / 2
            if delta is not None:
                f = max(-1.0, min(1.0, delta / rng))
                col = BAD if delta > 0 else GOOD
                if f > 0:
                    p.fillRect(QRectF(mid, by, bw / 2 * f, bh), col)
                else:
                    p.fillRect(QRectF(mid + bw / 2 * f, by, -bw / 2 * f, bh), col)
            p.fillRect(QRectF(mid - 1, by - 2, 2, bh + 4), TXT)
            top = 26
        col = TXT if delta is None else (BAD if delta > 0 else GOOD)
        self.text(p, 10, top, 150, 34, fmt_gap(delta, 2) if delta is not None else "–", col, font(26, True, True))
        self.text(p, 10, top + 36, 150, 16, "t.o.v. je beste ronde", MUTED, font(10))
        y = top
        for key, label, colr, val in (("voorspelling", "voorspeld", TXT, dl.get("voorspelling")),
                                      ("beste", "beste", PURPLE, dl.get("beste")),
                                      ("laatste", "laatste", MUTED, dl.get("laatste"))):
            if self.o(key):
                self.text(p, 150, y, W - 160, 16, f"{label}  {fmt_t(val)}", colr, font(12, False, True), R)
                y += 18


# ======================================================================
#  7. Brandstof
# ======================================================================
class FuelOverlay(Overlay):
    NAME, TITLE, DEFAULT_POS = "brandstof", "Brandstof", (0.99, 0.35)
    ROWS = [("liter", "In de tank", True), ("per_ronde", "Verbruik per ronde (gemiddeld)", True),
            ("vorige", "Verbruik vorige ronde", True), ("ronden_tank", "Ronden in de tank", True),
            ("ronden_te_gaan", "Ronden te gaan", True), ("strategie", "Stops en pitvenster / haalt het", True),
            ("bijtanken", "Bijtanken bij een stop", True), ("zuinig", "Hoe zuinig om zonder stop te finishen", True)]
    OPTIONS = [opt_bool("tankbalk", "Tankbalk", True)] + [opt_bool("rij_" + k, lbl, v, "Regels") for k, lbl, v in ROWS]

    def base(self):
        n = sum(1 for k, _l, _v in self.ROWS if self.o("rij_" + k))
        return (300, 30 + (12 if self.o("tankbalk") else 0) + n * 18 + 6)

    def draw(self, p, W, H, d):
        f = d.get("brandstof") or {}
        self.header(p, W, "Brandstof", f"ronde {f.get('ronde', '')}")
        liter, tank = f.get("liter"), f.get("tank")
        y = 26
        if self.o("tankbalk"):
            p.fillRect(QRectF(10, y, W - 20, 8), QColor(255, 255, 255, 18))
            if liter is not None and tank:
                fr = max(0.0, min(1.0, liter / tank))
                p.fillRect(QRectF(10, y, (W - 20) * fr, 8), ACCENT if fr > 0.15 else BAD)
            y += 14

        def num(x, dec=1, unit=""):
            return "–" if x is None else (f"{x:.{dec}f}".replace(".", ",") + unit)

        stops = f.get("stops")
        v = f.get("venster") or (None, None)
        if stops == 0 and f.get("overschot") is not None:
            strat = ("Tot de finish", "haalt het, " + num(f.get("overschot"), 1, " L over"))
        elif stops:
            strat = ("Stops nodig", f"{stops}  ·  venster R{v[0]}–R{v[1]}" if v[0] else str(stops))
        else:
            strat = ("Stops nodig", "–")
        zuinig = ("Zonder stop", f"{num(f.get('doel_zonder_stop'), 2)} L/ronde (−{num(f.get('besparen_pct'), 0)}%)") \
            if stops and f.get("besparen_pct") is not None and 0 < f["besparen_pct"] < 25 else ("Zonder stop", "–")
        values = {
            "liter": ("In de tank", num(liter, 1, " L")),
            "per_ronde": ("Per ronde (gem.)", num(f.get("per_ronde"), 2, " L")),
            "vorige": ("Vorige ronde", num(f.get("laatste_ronde"), 2, " L")),
            "ronden_tank": ("Ronden in tank", num(f.get("ronden_in_tank"), 1)),
            "ronden_te_gaan": ("Ronden te gaan", num(f.get("ronden_te_gaan"), 1)),
            "strategie": strat,
            "bijtanken": ("Bijtanken bij stop", num(f.get("bijtanken"), 1, " L") if stops else "–"),
            "zuinig": zuinig,
        }
        for k, _lbl, _v in self.ROWS:
            if not self.o("rij_" + k):
                continue
            label, val = values[k]
            self.text(p, 10, y, 140, 18, label, MUTED, font(12))
            warn = k == "ronden_tank" and f.get("ronden_in_tank") is not None and f.get("ronden_te_gaan") is not None \
                and f["ronden_in_tank"] < f["ronden_te_gaan"]
            self.text(p, 140, y, W - 150, 18, val, BAD if warn else TXT, font(12, True), R)
            y += 18


ALL = [RelativeOverlay, StandingsOverlay, TickerOverlay, SectorsOverlay, InputsOverlay, DeltaOverlay, FuelOverlay]
BY_NAME = {c.NAME: c for c in ALL}


# ======================================================================
#  Voorbeeldgegevens (om te verplaatsen en in te stellen zonder iRacing)
# ======================================================================
def sample_data():
    names = ["Max de Boer", "Lars Jansen", "Tom Visser", "Frank (jij)", "Sven Bakker", "Bas Kok", "Pim van Dijk",
             "Ruben Meijer", "Daan Bos", "Kees Smit"]
    lic = ["A 3.42", "A 2.10", "B 3.95", "A 2.88", "B 2.31", "C 3.12", "B 4.01", "A 1.99", "D 2.50", "B 3.00"]
    irs = [3120, 2890, 2650, 2480, 2410, 2300, 2150, 1980, 1850, 1700]
    gt3 = []
    for i, n in enumerate(names):
        jij = i == 3
        last = 92.4 + ((i * 37) % 9) / 10 - 0.3
        gt3.append({"idx": i, "pos": i + 1, "nr": str(10 + i), "naam": n, "kort": n.split()[-1] if not jij else "Frank",
                    "klasse": "GT3", "kleur": "#33CEFF", "ir": irs[i], "lic": lic[i], "lic_klasse": lic[i][0],
                    "sr": float(lic[i][2:]), "pit": i == 5, "jij": jij, "auto": ["McLaren 720S GT3 EVO", "Ferrari 296 GT3",
                    "Porsche 911 GT3 R", "McLaren 720S GT3 EVO", "BMW M4 GT3", "Audi R8 LMS EVO II"][i % 6],
                    "laatste": last, "beste": 91.9 + i * 0.12, "stops": 1 if i in (2, 5) else 0,
                    "ir_delta": [62, 41, 25, 12, 2, -8, -17, -26, -33, -40][i],
                    "vs_laatste": None if jij else round(last - 92.5, 3),
                    "vs_beste": None if jij else round((91.9 + i * 0.12) - 92.26, 3),
                    "plekken": [0, 1, -1, 2, 0, -3, 1, 0, -1, 1][i],
                    "gap": round(i * 1.7, 1), "interval": None if i == 0 else 1.7})
    gtp = [{"idx": 20 + i, "pos": i + 1, "nr": str(1 + i), "naam": n, "kort": n.split()[-1], "klasse": "GTP",
            "kleur": "#FFDA59", "ir": 3600 - 200 * i, "lic": "A 4.0", "lic_klasse": "A", "sr": 4.0, "pit": False,
            "jij": False, "auto": "Porsche 963 GTP", "laatste": 84.1, "beste": 83.6 + i * 0.2, "stops": 0,
            "ir_delta": [30, 5, -20][i], "vs_laatste": -8.3, "vs_beste": -8.6, "plekken": 0,
            "gap": round(i * 2.3, 1), "interval": None if i == 0 else 2.3}
           for i, n in enumerate(["Anna Brouwer", "Kees Dekker", "Rik Hendriks"])]
    rel = []
    for k, r in enumerate([gtp[0], gt3[0], gt3[1], gt3[2], gt3[3], gt3[4], gtp[1], gt3[5], gt3[6]]):
        x = dict(r)
        x["gap"] = [6.0, 4.2, 2.6, 0.9, 0.0, -1.1, -2.4, -4.0, -5.6][k]
        x["ronde"] = 1 if x["klasse"] == "GTP" else 0
        rel.append(x)
    return {
        "relative": rel, "sessie": "Race", "race": True, "ronde": 12, "totaal": 30, "tijd_over": 1830,
        "stand": [{"klasse": "GT3", "kleur": "#33CEFF", "eigen": True, "auto": gt3},
                  {"klasse": "GTP", "kleur": "#FFDA59", "eigen": False, "auto": gtp}],
        "sectoren": {"aantal": 3, "jij": {"naam": "Jij", "vorige": [31.204, 33.870, 27.115], "beste": [31.204, 33.6, 27.0],
                                          "nu": [31.3, 33.9, None]},
                     "voor": {"naam": "Visser", "vorige": [31.05, 34.02, 27.10]},
                     "achter": {"naam": "Bakker", "vorige": [31.40, 33.75, 27.35]},
                     "gap_voor": 0.9, "gap_achter": -1.1},
        "delta": {"delta": -0.184, "voorspelling": 91.716, "beste": 91.9, "laatste": 92.31},
        "brandstof": {"liter": 41.2, "tank": 100, "per_ronde": 3.12, "laatste_ronde": 3.08, "ronden_in_tank": 13.2,
                      "ronden_te_gaan": 18.0, "stops": 1, "venster": (16, 24), "bijtanken": 18.4,
                      "doel_zonder_stop": 2.29, "besparen_pct": 12.0, "ronde": 12},
    }


def sample_inputs():
    import collections
    h = collections.deque(maxlen=720)
    for i in range(720):
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

    def set_option(self, name, key, value):
        self.cfg.setdefault("opties", {}).setdefault(name, {})[key] = value
        self.win.save_cfg(self.win.cfg)
        w = self.windows.get(name)
        if w:
            w._fit()
            w.update()

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
            if show:
                w._fit()
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
#  Optievenster per overlay
# ======================================================================
class OptionsDialog(QDialog):
    def __init__(self, page, cls):
        super().__init__(page)
        self.page, self.cls = page, cls
        mgr = page.win.overlays
        self.setWindowTitle(f"Opties · {cls.TITLE}")
        self.setMinimumWidth(460)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("page")
        v = QVBoxLayout(inner)
        cur = (mgr.cfg.get("opties") or {}).get(cls.NAME) or {}
        groups = {}
        for spec in cls.OPTIONS:
            groups.setdefault(spec["group"], []).append(spec)
        for gname, specs in groups.items():
            lab = QLabel(gname.upper())
            lab.setObjectName("cap")
            v.addWidget(lab)
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignLeft)
            for spec in specs:
                key, val = spec["key"], cur.get(spec["key"], spec["default"])
                if spec["type"] == "bool":
                    w = QCheckBox(spec["label"])
                    w.setChecked(bool(val))
                    w.toggled.connect(lambda x, k=key: mgr.set_option(cls.NAME, k, bool(x)))
                    form.addRow(w)
                elif spec["type"] == "int":
                    w = QSpinBox()
                    w.setRange(spec["min"], spec["max"])
                    w.setValue(int(val))
                    w.valueChanged.connect(lambda x, k=key: mgr.set_option(cls.NAME, k, int(x)))
                    form.addRow(spec["label"], w)
                else:
                    w = QComboBox()
                    for ch in spec["choices"]:
                        w.addItem(CHOICE_LABELS.get(ch, ch), ch)
                    w.setCurrentIndex(max(0, spec["choices"].index(val) if val in spec["choices"] else 0))
                    w.currentIndexChanged.connect(lambda _i, k=key, ww=w: mgr.set_option(cls.NAME, k, ww.currentData()))
                    form.addRow(spec["label"], w)
            v.addLayout(form)
            v.addSpacing(8)
        v.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        hint = QLabel("Wijzigingen zie je meteen. Tip: klik op 'Overlays verplaatsen' om ze met voorbeeldgegevens te zien.")
        hint.setObjectName("sub")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Sluiten")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        outer.addLayout(row)
        self.setStyleSheet("QDialog { background: #0F1216; }")
        self.resize(520, 620)


CHOICE_LABELS = {"laatste": "laatste ronde", "beste": "beste ronde", "verschil": "verschil met jou",
                 "tijden": "hun tijden", "gap": "gap tot de leider", "interval": "interval tot de auto voor",
                 "ir": "iRating", "ir_delta": "iRating winst/verlies", "niets": "niets", "0.5": "0,5 seconde",
                 "1": "1 seconde", "2": "2 seconden"}


# ======================================================================
#  Pagina in het programma
# ======================================================================
class OverlayPage(QWidget):
    LABELS = {
        "relative": "Auto's direct voor en achter je op de baan, met gap, klasse en iRating.",
        "stand": "Stand per klasse met de kolommen die jij kiest (iRating, safety rating, verschil, iRating-winst, ...).",
        "ticker": "Een balk met jouw klasse rond jouw positie, bovenin beeld.",
        "sectoren": "Jouw sectortijden tegen de auto voor en achter je (groen = jij sneller).",
        "invoer": "Gas, rem, koppeling en stuur als lopende lijn, met versnelling en snelheid.",
        "delta": "Live sneller of langzamer dan je beste ronde, met voorspelde rondetijd.",
        "brandstof": "Verbruik, ronden in de tank, stops, pitvenster en hoeveel je moet tanken.",
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
        g.addWidget(self.master, 0, 0, 1, 3)
        self.checks = {}
        for i, (name, desc) in enumerate(self.LABELS.items(), start=1):
            cls = BY_NAME[name]
            cb = QCheckBox(cls.TITLE)
            self.checks[name] = cb
            g.addWidget(cb, i, 0)
            g.addWidget(lab(desc, "sub", wrap=True), i, 1)
            b = QPushButton("Opties")
            b.setStyleSheet("padding: 4px 12px;")
            b.clicked.connect(lambda _=False, k=cls: OptionsDialog(self, k).exec())
            g.addWidget(b, i, 2)
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
