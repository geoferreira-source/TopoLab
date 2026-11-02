"""Região de interesse (polígonos com furos) para recortar volumes."""
import numpy as np
from .geom import signed_area


def _clean_ring(coords):
    """Anel como array (n, 2) em sentido anti-horário, sem ponto de fechamento repetido."""
    r = np.asarray(coords, dtype=float).reshape(-1, 2)
    if len(r) > 1 and np.allclose(r[0], r[-1]):
        r = r[:-1]
    if len(r) < 3:
        return None
    x, y = r[:, 0], r[:, 1]
    area2 = signed_area(x, y)
    if abs(area2) == 0:
        return None
    return r if area2 > 0 else r[::-1].copy()


class Region:
    """Conjunto de polígonos, cada um com anel externo e furos opcionais.

    polygons: lista de (anel_externo, [furos]); cada anel é uma sequência de (x, y).
    """

    def __init__(self, polygons):
        self.rings = []  # (array (n,2) CCW, sinal: +1 externo, -1 furo)
        for outer, holes in polygons:
            o = _clean_ring(outer)
            if o is None:
                continue
            self.rings.append((o, 1))
            for h in holes:
                hr = _clean_ring(h)
                if hr is not None:
                    self.rings.append((hr, -1))
        if not self.rings:
            raise ValueError("O polígono de recorte é inválido ou está vazio.")
        allp = np.vstack([r for r, _ in self.rings])
        self.bbox = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
        self.ring_lists = [([tuple(p) for p in r], s) for r, s in self.rings]

    def translated(self, offset):
        off = np.asarray(offset, dtype=float)
        polys, cur = [], None
        for r, s in self.rings:
            if s == 1:
                cur = ([r - off], [])
                polys.append(cur)
            else:
                cur[1].append(r - off)
        return Region([(p[0][0], p[1]) for p in polys])

    def contains(self, pts):
        """Regra par-ímpar vetorizada: dentro de um polígono e fora de seus furos."""
        pts = np.asarray(pts, dtype=float).reshape(-1, 2)
        x, y = pts[:, 0], pts[:, 1]
        inside = np.zeros(len(pts), dtype=bool)
        for ring, _ in self.rings:
            nx, ny = np.roll(ring[:, 0], -1), np.roll(ring[:, 1], -1)
            for ax, ay, bx, by in zip(ring[:, 0], ring[:, 1], nx, ny):
                idx = np.nonzero((ay > y) != (by > y))[0]
                if len(idx) == 0:
                    continue
                xi = ax + (y[idx] - ay) * (bx - ax) / (by - ay)
                inside[idx[x[idx] < xi]] ^= True
        return inside

    def touches(self, tx0, tx1, ty0, ty1):
        """True para triângulos (por bbox) cujo bbox encosta no bbox de alguma aresta."""
        mask = np.zeros(len(tx0), dtype=bool)
        for ring, _ in self.rings:
            nx, ny = np.roll(ring[:, 0], -1), np.roll(ring[:, 1], -1)
            ex0, ex1 = np.minimum(ring[:, 0], nx), np.maximum(ring[:, 0], nx)
            ey0, ey1 = np.minimum(ring[:, 1], ny), np.maximum(ring[:, 1], ny)
            for a, b, c, d in zip(ex0, ex1, ey0, ey1):
                mask |= (tx1 >= a) & (tx0 <= b) & (ty1 >= c) & (ty0 <= d)
        return mask
