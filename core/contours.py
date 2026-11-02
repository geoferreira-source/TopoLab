"""Curvas de nível exatas sobre um TIN (triângulos marchantes)."""
import math

import numpy as np

from .surface import Tin


def make_levels(zmin, zmax, interval, base=0.0):
    """Cotas múltiplas de `interval` (a partir de `base`) dentro de [zmin, zmax]."""
    if interval <= 0:
        raise ValueError("A equidistância deve ser maior que zero.")
    k0 = math.ceil((zmin - base) / interval - 1e-12)
    k1 = math.floor((zmax - base) / interval + 1e-12)
    return [base + k * interval for k in range(k0, k1 + 1)]


def is_master(level, interval, master_every, base=0.0):
    """True se a cota é uma curva mestra (a cada `master_every` intervalos)."""
    if master_every <= 0:
        return False
    r = (level - base) / (interval * master_every)
    return abs(r - round(r)) < 1e-9


def contour_lines(tin: Tin, level):
    """Retorna lista de polilinhas [(x, y), ...] para a cota `level`.

    Linhas fechadas repetem o primeiro ponto no fim. A interpolação é linear
    em cada triângulo, então o resultado é exato para o TIN. Vértices com
    cota igual à do nível são tratados como "acima" (sem degeneração).
    """
    pts, tri = tin.points, tin.triangles
    n = len(pts)
    z = pts[tri, 2]
    above = z >= level
    cnt = above.sum(axis=1)
    cross = (cnt == 1) | (cnt == 2)
    if not cross.any():
        return []

    tri, above = tri[cross], above[cross]
    ea, eb = np.array([0, 1, 2]), np.array([1, 2, 0])
    va, vb = tri[:, ea], tri[:, eb]
    rows, cols = np.nonzero(above[:, ea] != above[:, eb])
    cols = cols.reshape(-1, 2)          # exatamente 2 arestas por triângulo
    r = np.arange(len(tri))[:, None]
    a, b = va[r, cols], vb[r, cols]     # (k, 2)

    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo.astype(np.int64) * n + hi
    ukeys, inv = np.unique(key.ravel(), return_inverse=True)
    lo_u, hi_u = ukeys // n, ukeys % n
    t = (level - pts[lo_u, 2]) / (pts[hi_u, 2] - pts[lo_u, 2])
    xy = pts[lo_u, :2] + t[:, None] * (pts[hi_u, :2] - pts[lo_u, :2])

    segments = inv.reshape(-1, 2)
    return [[tuple(xy[i]) for i in path] for path in _chain(segments, len(xy))]


def _chain(segments, n_nodes):
    """Encadeia segmentos (pares de nós) em caminhos contínuos."""
    adj = [[] for _ in range(n_nodes)]
    for u, v in segments:
        adj[u].append(v)
        adj[v].append(u)

    visited = set()

    def has_free_edge(node):
        return any((min(node, w), max(node, w)) not in visited for w in adj[node])

    def walk(start):
        path, cur = [start], start
        while True:
            nxt = None
            for w in adj[cur]:
                e = (min(cur, w), max(cur, w))
                if e not in visited:
                    visited.add(e)
                    nxt = w
                    break
            if nxt is None:
                return path
            path.append(nxt)
            cur = nxt

    paths = []
    for node in range(n_nodes):            # linhas abertas (extremidades)
        if len(adj[node]) == 1 and has_free_edge(node):
            paths.append(walk(node))
    for node in range(n_nodes):            # anéis fechados
        if has_free_edge(node):
            paths.append(walk(node))
    return paths
