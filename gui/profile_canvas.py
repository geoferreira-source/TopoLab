"""Gráfico simples (perfil ou seção) desenhado com QPainter — sem matplotlib."""
import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import QWidget

from ..core.report_html import fmt


class ProfileCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(240)
        self._x = self._z = None
        self._title = self._xlabel = ""
        self._datum = None

    def set_data(self, x, z, title="", xlabel="", datum=None):
        self._x = None if x is None else np.asarray(x, float)
        self._z = None if z is None else np.asarray(z, float)
        self._title, self._xlabel, self._datum = title, xlabel, datum
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("white"))
        ml, mr, mt, mb = 62, 14, 26, 34
        p.setPen(QColor("#222"))
        p.drawText(QRectF(ml, 2, w - ml - mr, mt - 4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)

        ok = None if self._z is None else np.isfinite(self._z)
        if self._x is None or ok is None or not ok.any():
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Sem dados para exibir.")
            return
        xmin, xmax = float(self._x.min()), float(self._x.max())
        zlo, zhi = float(self._z[ok].min()), float(self._z[ok].max())
        if self._datum is not None:
            zlo, zhi = min(zlo, self._datum), max(zhi, self._datum)
        pad = (zhi - zlo) * 0.08 or 1.0
        zlo, zhi = zlo - pad, zhi + pad
        dx = (xmax - xmin) or 1.0
        pw, ph = w - ml - mr, h - mt - mb

        def sx(v):
            return ml + (v - xmin) / dx * pw

        def sy(v):
            return mt + (zhi - v) / (zhi - zlo) * ph

        grid = QPen(QColor("#dddddd"))
        for i in range(6):
            zv = zlo + (zhi - zlo) * i / 5
            xv = xmin + dx * i / 5
            p.setPen(grid)
            p.drawLine(QPointF(ml, sy(zv)), QPointF(w - mr, sy(zv)))
            p.drawLine(QPointF(sx(xv), mt), QPointF(sx(xv), h - mb))
            p.setPen(QColor("#444"))
            p.drawText(QRectF(0, sy(zv) - 9, ml - 6, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fmt(zv, 2))
            p.drawText(QRectF(sx(xv) - 40, h - mb + 2, 80, 16), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       fmt(xv, 1))
        p.drawText(QRectF(ml, h - 16, pw, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._xlabel)

        if self._datum is not None:
            pen = QPen(QColor("#c0392b"))
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(ml, sy(self._datum)), QPointF(w - mr, sy(self._datum)))

        p.setPen(QPen(QColor("#2f5d3a"), 2))
        for i in range(len(self._x) - 1):  # quebra a linha onde há NaN
            if ok[i] and ok[i + 1]:
                p.drawLine(QPointF(sx(self._x[i]), sy(self._z[i])),
                           QPointF(sx(self._x[i + 1]), sy(self._z[i + 1])))
