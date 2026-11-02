"""Roteiro perimétrico e leitura de memorial descritivo (sem dependência do QGIS)."""
import math
import re
from dataclasses import dataclass, field

import numpy as np

from .angles import format_dms, parse_angle
from .report_html import fmt
from .geom import signed_area


def azimuth_distance(p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    return math.degrees(math.atan2(dx, dy)) % 360.0, math.hypot(dx, dy)


def route_from_coords(x, y, closed=True):
    """Azimute (a partir do Norte, horário) e distância de cada lado, a partir das coordenadas."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    pairs = [(i, (i + 1) % n) for i in range(n)] if closed else [(i, i + 1) for i in range(n - 1)]
    az, dist = [], []
    for a, b in pairs:
        d_az, d = azimuth_distance((x[a], y[a]), (x[b], y[b]))
        az.append(d_az)
        dist.append(d)
    return np.array(az), np.array(dist)


def polygon_area(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    return abs(signed_area(x, y))


def memorial_from_coords(names, x, y, closed=True, title="Memorial descritivo", crs_text="",
                         decimals=2):
    """Texto-base do memorial, com azimutes e distâncias derivados das coordenadas."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    az, dist = route_from_coords(x, y, closed)
    n = len(x)

    def coord(i):
        return f"E = {fmt(x[i], decimals)} m e N = {fmt(y[i], decimals)} m"

    lines = [title.upper(), ""]
    if closed:
        lines.append(f"Área: {fmt(polygon_area(x, y), 2)} m² ({fmt(polygon_area(x, y) / 10000, 4)} ha).")
    lines.append(f"{'Perímetro' if closed else 'Comprimento'}: {fmt(dist.sum(), 2)} m.")
    if crs_text:
        lines.append(f"Coordenadas no sistema {crs_text}.")
    lines += ["", "DESCRIÇÃO:", ""]
    text = f"Inicia-se a descrição no vértice {names[0]}, de coordenadas {coord(0)}"
    for i in range(len(az)):
        j = (i + 1) % n if closed else i + 1
        text += (f"; deste, segue com azimute de {format_dms(az[i], 0)} e distância de "
                 f"{fmt(dist[i], decimals)} m até o vértice {names[j]}, de coordenadas {coord(j)}")
        if closed and i == len(az) - 1:
            text += ", ponto inicial da descrição, fechando o perímetro"
    lines.append(text + ".")
    lines += ["", "Azimutes referidos ao Norte da quadrícula do sistema de coordenadas informado."]
    return "\n".join(lines)


@dataclass
class MemorialGeometry:
    names: list
    x: np.ndarray
    y: np.ndarray
    closed: bool
    azimuth: np.ndarray
    dist: np.ndarray
    misclosure: float = 0.0                 # fechamento (se fechado) ou desvio máx. das coordenadas citadas
    stated: list = field(default_factory=list)  # coordenadas citadas no texto (E, N) ou None


def _pt_number(s):
    s = s.strip()
    s = s.replace(".", "").replace(",", ".") if "," in s else s
    return float(s)


_NUM = r"\d[\d\.]*(?:,\d+)?"
_COORD = re.compile(rf"E\s*=\s*({_NUM})\s*m\s*e\s*N\s*=\s*({_NUM})\s*m", re.I)
_AZ = re.compile(r"azimute\s+(?:de\s+)?([0-9°'\"′″:\s.,\-]+?)\s*,?\s*e\s+dist[âa]ncia\s+(?:de\s+)?"
                 rf"({_NUM})\s*m", re.I)
_VERT = re.compile(r"v[ée]rtice\s+([^\s,;]+)", re.I)


def parse_memorial(text, start=None):
    """Lê um memorial no padrão "... azimute de X e distância de Y m até o vértice V ..." e
    restitui as coordenadas.

    start: (E, N) do primeiro vértice, usado se o texto não trouxer coordenadas.
    Aceita o texto gerado pelo TopoLab e redações parecidas (vírgula decimal, ponto de milhar).
    """
    t = (text.replace("’", "'").replace("′", "'").replace("”", '"').replace("″", '"')
         .replace("“", '"').replace("º", "°"))
    if "DESCRIÇÃO" in t.upper():
        t = t[t.upper().index("DESCRIÇÃO") + len("DESCRIÇÃO"):].lstrip(": \n")
    clauses = [c.strip() for c in re.split(r";", " ".join(t.split())) if c.strip()]
    if len(clauses) < 2:
        raise ValueError("Não encontrei os trechos do memorial (separados por ';').")

    first = _VERT.search(clauses[0])
    if not first:
        raise ValueError("Não encontrei o vértice inicial (\"no vértice P1...\").")
    names, stated = [first.group(1).rstrip(".,"), ], []
    c0 = _COORD.search(clauses[0])
    stated.append((_pt_number(c0.group(1)), _pt_number(c0.group(2))) if c0 else None)
    if c0:
        start = stated[0]
    if start is None:
        raise ValueError("O texto não traz as coordenadas do vértice inicial; informe E e N.")

    az, dist = [], []
    for c in clauses[1:]:
        m = _AZ.search(c)
        if not m:
            raise ValueError(f"Trecho sem azimute e distância: {c[:60]!r}")
        az.append(parse_angle(m.group(1).strip(" ,"), "dms") % 360.0)
        dist.append(_pt_number(m.group(2)))
        v = _VERT.search(c[m.end():])
        names.append(v.group(1).rstrip(".,") if v else f"V{len(names) + 1}")
        cc = _COORD.search(c[m.end():])
        stated.append((_pt_number(cc.group(1)), _pt_number(cc.group(2))) if cc else None)

    az, dist = np.array(az), np.array(dist)
    x = np.concatenate([[start[0]], start[0] + np.cumsum(dist * np.sin(np.radians(az)))])
    y = np.concatenate([[start[1]], start[1] + np.cumsum(dist * np.cos(np.radians(az)))])
    closed = bool(re.search(r"fechando|ponto inicial", t, re.I)) or names[-1] == names[0]
    mis = 0.0
    if closed:
        mis = math.hypot(x[-1] - x[0], y[-1] - y[0])
        x, y, names, stated = x[:-1], y[:-1], names[:-1], stated[:-1]
    dev = [math.hypot(x[i] - s[0], y[i] - s[1]) for i, s in enumerate(stated) if s is not None]
    if not closed and dev:
        mis = max(dev)
    return MemorialGeometry(names, x, y, closed, az, dist, mis, stated)
