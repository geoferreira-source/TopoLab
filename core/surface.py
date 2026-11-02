"""Superfície TIN (triangulação de Delaunay). Sem dependência do QGIS."""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.spatial import Delaunay


@dataclass
class Tin:
    points: np.ndarray     # (n, 3) -> x, y, z
    triangles: np.ndarray  # (m, 3) -> índices em `points`
    delaunay: Optional[Delaunay] = field(default=None, repr=False)
    center: Optional[np.ndarray] = field(default=None, repr=False)
    kept: Optional[np.ndarray] = field(default=None, repr=False)  # máscara dos simplices mantidos
    lines: Optional[list] = field(default=None, repr=False)  # linhas impostas (quebra e limite), (k, 2)

    def z_at(self, xy, use_kept=True):
        """Cota interpolada (linear, exata no TIN) em pontos (k, 2).

        Retorna NaN fora do TIN ou dentro de triângulos descartados (aresta máxima, limite).
        use_kept=False interpola também nos descartados: serve para pontos exatamente sobre a
        borda (a cota na aresta é a mesma dos dois lados), cuja validade se confere à parte.
        """
        if self.delaunay is None:
            raise RuntimeError("TIN sem estrutura de localização (criado fora de build_tin).")
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        out = np.full(len(xy), np.nan)
        q = xy - self.center
        s = self.delaunay.find_simplex(q)
        ok = s >= 0
        if self.kept is not None and use_kept:
            ok &= self.kept[np.where(s >= 0, s, 0)]
        if not ok.any():
            return out
        t = self.delaunay.transform[s[ok]]                       # (k, 3, 2)
        b = np.einsum("kij,kj->ki", t[:, :2, :], q[ok] - t[:, 2, :])
        bary = np.column_stack([b, 1.0 - b.sum(axis=1)])
        z = self.points[self.delaunay.simplices[s[ok]], 2]
        out[ok] = (bary * z).sum(axis=1)
        return out


def _dedupe(xyz):
    """Descarta não finitos e pontos com XY repetido (mantém o primeiro, na ordem original)."""
    xyz = np.asarray(xyz, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("Esperado array (n, 3) com x, y, z.")
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    _, first = np.unique(xyz[:, :2], axis=0, return_index=True)
    return xyz[np.sort(first)]


def _delaunay(xyz):
    """Delaunay centralizado (estabilidade numérica com coordenadas UTM grandes)."""
    center = xyz[:, :2].mean(axis=0)
    return Delaunay(xyz[:, :2] - center), center


def build_tin(xyz, max_edge=0.0, breaklines=None, boundary=None):
    """Constrói um TIN a partir de pontos (n, 3).

    max_edge: se > 0, descarta triângulos com qualquer aresta maior que esse valor
    (evita triângulos falsos sobre vazios e no fecho convexo).
    breaklines: lista de polilinhas (k, 3) [ou (k, 2)] que passam a ser arestas do TIN
    (cota da linha onde informada; NaN = interpolada). Ver `breaklines.conform`.
    boundary: `Region` que limita o MDT; triângulos fora dela (ou dentro de furos) saem.
    Pontos com XY duplicado são descartados (mantém o primeiro).
    """
    xyz = _dedupe(xyz)
    if len(xyz) < 3:
        raise ValueError("São necessários ao menos 3 pontos distintos.")

    if breaklines or boundary is not None:
        from .breaklines import conform
        xyz, dela, center = conform(xyz, breaklines or [], boundary)
    else:
        dela, center = _delaunay(xyz)
    tri = dela.simplices
    kept = np.ones(len(tri), dtype=bool)

    if max_edge and max_edge > 0:
        p = xyz[:, :2]
        a, b, c = p[tri[:, 0]], p[tri[:, 1]], p[tri[:, 2]]
        longest = np.maximum.reduce([
            np.hypot(*(a - b).T), np.hypot(*(b - c).T), np.hypot(*(c - a).T)
        ])
        kept &= longest <= max_edge
    if boundary is not None:
        kept &= boundary.contains(xyz[tri, :2].mean(axis=1))
    if not kept.any():
        raise ValueError("Nenhum triângulo restou (confira a aresta máxima e o limite do MDT).")

    lines = [np.asarray(l, float).reshape(len(l), -1)[:, :2] for l in (breaklines or [])]
    if boundary is not None:
        lines += [np.vstack([ring, ring[:1]]) for ring, _ in boundary.rings]
    return Tin(points=xyz, triangles=tri[kept], delaunay=dela, center=center, kept=kept,
               lines=lines or None)
