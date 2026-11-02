"""Perfil longitudinal e seções transversais sobre um TIN (sem dependência do QGIS)."""
from dataclasses import dataclass

import numpy as np

from .surface import Tin


class Axis:
    """Eixo (polilinha) com estaqueamento contínuo a partir do primeiro vértice."""

    def __init__(self, xy):
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        keep = np.ones(len(xy), dtype=bool)
        keep[1:] = np.any(np.diff(xy, axis=0) != 0, axis=1)
        xy = xy[keep]
        if len(xy) < 2:
            raise ValueError("O eixo precisa de ao menos 2 vértices distintos.")
        d = np.diff(xy, axis=0)
        seg = np.hypot(d[:, 0], d[:, 1])
        self.xy, self.seg, self.dir = xy, seg, d / seg[:, None]
        self.chain = np.concatenate([[0.0], np.cumsum(seg)])  # distância acumulada nos vértices
        self.length = float(self.chain[-1])

    def at(self, s):
        """Pontos (k, 2) e tangentes unitárias (k, 2) nas distâncias `s` (k,)."""
        s = np.clip(np.atleast_1d(np.asarray(s, dtype=float)), 0.0, self.length)
        i = np.clip(np.searchsorted(self.chain, s, side="right") - 1, 0, len(self.seg) - 1)
        p = self.xy[i] + self.dir[i] * (s - self.chain[i])[:, None]
        return p, self.dir[i]


def make_stations(length, step, extra=()):
    """Distâncias 0, step, 2*step... até o fim do eixo (inclui o fim e `extra`)."""
    if step <= 0:
        raise ValueError("O passo deve ser maior que zero.")
    s = np.concatenate([np.arange(0.0, length, step), [length], np.asarray(extra, float)])
    return np.unique(np.round(s, 9))


def format_station(s, estaca_len=20.0):
    """Estaca no padrão brasileiro: 12+05,00 (estacas de `estaca_len` m)."""
    n = int(s // estaca_len + 1e-9)
    r = max(s - n * estaca_len, 0.0)
    if r >= estaca_len - 5e-3:  # evita 5+20,00 por arredondamento
        n, r = n + 1, 0.0
    return f"{n}+{r:05.2f}".replace(".", ",")


@dataclass
class Profile:
    station: np.ndarray
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray  # NaN fora do TIN


def profile_along(tin: Tin, axis: Axis, step: float) -> Profile:
    """Perfil longitudinal: amostra o TIN a cada `step` m e em todos os vértices do eixo."""
    st = make_stations(axis.length, step, extra=axis.chain)
    p, _ = axis.at(st)
    return Profile(station=st, x=p[:, 0], y=p[:, 1], z=tin.z_at(p))


def section_areas(offsets, z, datum):
    """(área de corte, área de aterro, completa) de uma seção contra a cota `datum`.

    Corte = terreno acima de `datum`; aterro = abaixo. Exato por trecho (trapézios
    com cruzamento de cota). Trechos com NaN são ignorados e `completa` fica False.
    """
    offsets, z = np.asarray(offsets, float), np.asarray(z, float)
    h = z - datum
    w = np.diff(offsets)
    h0, h1 = h[:-1], h[1:]
    ok = np.isfinite(h0) & np.isfinite(h1)
    w, h0, h1 = w[ok], h0[ok], h1[ok]
    cut = fill = 0.0
    both_pos, both_neg = (h0 >= 0) & (h1 >= 0), (h0 <= 0) & (h1 <= 0)
    cut += float((w * (h0 + h1) / 2)[both_pos].sum())
    fill += float((-w * (h0 + h1) / 2)[both_neg & ~both_pos].sum())
    mix = ~(both_pos | both_neg)
    hp, hn = np.maximum(h0, h1)[mix], np.minimum(h0, h1)[mix]
    d = 2 * (hp - hn)
    cut += float((w[mix] * hp ** 2 / d).sum())
    fill += float((w[mix] * hn ** 2 / d).sum())
    return cut, fill, bool(ok.all())


@dataclass
class Section:
    station: float
    cx: float
    cy: float
    offsets: np.ndarray  # positivo à direita do eixo (sentido do estaqueamento)
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray        # NaN fora do TIN
    z_axis: float
    area_cut: float = float("nan")
    area_fill: float = float("nan")
    complete: bool = True


def cross_sections(tin: Tin, axis: Axis, interval, half_width, step, datum=None):
    """Seções transversais a cada `interval` m, de -half_width a +half_width (esquerda
    negativa, direita positiva), amostradas a cada `step` m."""
    if half_width <= 0 or step <= 0:
        raise ValueError("Largura e passo da seção devem ser maiores que zero.")
    st = make_stations(axis.length, interval)
    offs = np.unique(np.round(np.concatenate([np.arange(-half_width, half_width, step),
                                              [half_width]]), 9))
    c, t = axis.at(st)
    right = np.column_stack([t[:, 1], -t[:, 0]])
    pts = c[:, None, :] + offs[None, :, None] * right[:, None, :]  # (S, K, 2)
    z = tin.z_at(pts.reshape(-1, 2)).reshape(len(st), len(offs))
    z_axis = tin.z_at(c)
    out = []
    for i, s in enumerate(st):
        sec = Section(float(s), float(c[i, 0]), float(c[i, 1]), offs, pts[i, :, 0],
                      pts[i, :, 1], z[i], float(z_axis[i]))
        if datum is not None:
            sec.area_cut, sec.area_fill, sec.complete = section_areas(offs, z[i], datum)
        else:
            sec.complete = bool(np.isfinite(z[i]).all())
        out.append(sec)
    return out


def section_volumes(sections):
    """Volumes entre seções consecutivas pelo método da média das áreas.

    Retorna lista de (estaca_ini, estaca_fim, corte, aterro, ok). `ok` é False quando
    alguma das duas seções está incompleta (fora do TIN) ou sem cota de referência.
    """
    rows = []
    for a, b in zip(sections[:-1], sections[1:]):
        d = b.station - a.station
        ok = a.complete and b.complete and np.isfinite(a.area_cut) and np.isfinite(b.area_cut)
        if ok:
            rows.append((a.station, b.station, (a.area_cut + b.area_cut) / 2 * d,
                         (a.area_fill + b.area_fill) / 2 * d, True))
        else:
            rows.append((a.station, b.station, 0.0, 0.0, False))
    return rows
