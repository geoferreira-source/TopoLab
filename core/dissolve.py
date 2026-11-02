"""Faixas (classes) sobre uma malha triangular, juntadas em polígonos por classe.

Em vez de um polígono por pedaço de triângulo (dezenas de milhares de feições, lentas para
gravar e desenhar), cada classe vira um multipolígono com furos. Os pedaços são recortados
com vértices identificados (vértice da malha, ou cruzamento de uma aresta da malha com um
limite de classe); como o cruzamento é calculado sempre no mesmo sentido da aresta, os dois
triângulos vizinhos produzem exatamente o mesmo ponto, e as arestas internas se cancelam.
"""
import math
from collections import defaultdict

import numpy as np

from .geom import signed_area


class BandMesh:
    """Recorta os triângulos de uma malha por limites de um valor linear nos vértices.

    xy: (n, 2) vértices; v: (n,) valor em cada vértice; tri: (m, 3) índices.
    """

    def __init__(self, xy, v, tri):
        self.xy = np.asarray(xy, float)
        self.v = np.asarray(v, float)
        tri = np.asarray(tri, int)
        p = self.xy[tri]
        det = ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
               - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
        tri = tri[det != 0].copy()
        cw = det[det != 0] < 0
        tri[cw] = tri[cw][:, [0, 2, 1]]           # todos anti-horários
        self.tri = tri
        self.coords = {}                         # chave do vértice -> (x, y)

    # ------------------------------------------------------------------ vértices
    def _vert(self, i):
        i = int(i)
        if i not in self.coords:
            self.coords[i] = (float(self.xy[i, 0]), float(self.xy[i, 1]))
        return i

    def _cross(self, a, b, k, thr):
        """Ponto onde a aresta (a, b) da malha atinge o limite k (mesmo resultado nos dois sentidos)."""
        a, b = (a, b) if a < b else (b, a)
        va, vb = self.v[a], self.v[b]
        t = (thr - va) / (vb - va)
        if t <= 0.0:
            return self._vert(a)
        if t >= 1.0:
            return self._vert(b)
        key = (a, b, k)
        if key not in self.coords:
            xa, ya = self.xy[a]
            xb, yb = self.xy[b]
            self.coords[key] = (float(xa + t * (xb - xa)), float(ya + t * (yb - ya)))
        return key

    @staticmethod
    def _edge_of(p, q):
        """Aresta da malha que contém o segmento p-q (None se for um trecho de curva)."""
        sp = {p} if isinstance(p, int) else {p[0], p[1]}
        sq = {q} if isinstance(q, int) else {q[0], q[1]}
        s = sp | sq
        return tuple(sorted(s)) if len(s) == 2 else None

    def _value(self, key, thr_of):
        return self.v[key] if isinstance(key, int) else thr_of[key[2]]

    def _clip(self, poly, k, thr, keep_above, thr_of):
        out, n = [], len(poly)
        for i in range(n):
            p, q = poly[i], poly[(i + 1) % n]
            vp, vq = self._value(p, thr_of), self._value(q, thr_of)
            sp = vp >= thr if keep_above else vp <= thr
            sq = vq >= thr if keep_above else vq <= thr
            if sp:
                out.append(p)
            if sp != sq:
                e = self._edge_of(p, q)
                if e is not None:
                    out.append(self._cross(e[0], e[1], k, thr))
        # tira repetidos consecutivos (cruzamento caindo sobre um vértice)
        clean = [c for i, c in enumerate(out) if c != out[i - 1]] if len(out) > 1 else out
        return clean

    # ------------------------------------------------------------------ pedaços
    def pieces(self, edges):
        """Gera (índice do triângulo, classe, [chaves dos vértices]) — anti-horários.

        Classe 0 = abaixo do 1º limite; k = [edges[k-1], edges[k]); len(edges) = acima do último.
        """
        edges = np.asarray(edges, float)
        thr_of = {k: float(t) for k, t in enumerate(edges)}
        vt = self.v[self.tri]
        bmin = np.searchsorted(edges, vt.min(axis=1), side="right")
        bmax = np.searchsorted(edges, vt.max(axis=1), side="right")
        for i, (t, b0, b1) in enumerate(zip(self.tri, bmin, bmax)):
            tri = [self._vert(t[0]), self._vert(t[1]), self._vert(t[2])]
            if b0 == b1:
                yield i, int(b0), tri
                continue
            for b in range(int(b0), int(b1) + 1):
                poly = tri
                if b > 0:
                    poly = self._clip(poly, b - 1, edges[b - 1], True, thr_of)
                if b < len(edges) and len(poly) >= 3:
                    poly = self._clip(poly, b, edges[b], False, thr_of)
                if len(poly) >= 3 and self._area(poly) > 0.0:
                    yield i, b, poly

    def _area(self, keys):
        # Python puro (pedaços de 3 a 5 vértices: numpy aqui custa mais do que a conta),
        # relativo ao 1º vértice para não perder precisão com coordenadas UTM
        c = [self.coords[k] for k in keys]
        x0, y0 = c[0]
        s = 0.0
        for (xa, ya), (xb, yb) in zip(c[1:-1], c[2:]):
            s += (xa - x0) * (yb - y0) - (xb - x0) * (ya - y0)
        return 0.5 * s

    def integral(self, keys, thr_of):
        """Integral do valor (linear) sobre o pedaço: soma de leques, área × média dos vértices."""
        c = np.array([self.coords[k] for k in keys])
        val = np.array([self._value(k, thr_of) for k in keys])
        x, y = c[:, 0] - c[0, 0], c[:, 1] - c[0, 1]
        a = 0.5 * (x[1:-1] * y[2:] - x[2:] * y[1:-1])
        return float(np.sum(a * (val[0] + val[1:-1] + val[2:]) / 3.0))

    def xy_of(self, keys):
        return [self.coords[k] for k in keys]

    # ------------------------------------------------------------------ dissolver
    def dissolve(self, pieces):
        """Junta pedaços (listas de chaves, anti-horários) em [(anel externo, [furos]), ...]."""
        edges = set()
        for poly in pieces:
            n = len(poly)
            for i in range(n):
                p, q = poly[i], poly[(i + 1) % n]
                if (q, p) in edges:
                    edges.discard((q, p))          # aresta interna: some
                else:
                    edges.add((p, q))
        return _assemble(edges, self.coords)


def _assemble(edges, coords):
    out = defaultdict(list)
    for p, q in edges:
        out[p].append(q)
    rings = []
    while out:
        # o anel começa por uma aresta (e não por um vértice) para que a escolha nos vértices
        # "pinçados" seja feita sempre com a direção de chegada conhecida
        p0 = next(iter(out))
        q0 = out[p0].pop()
        if not out[p0]:
            del out[p0]
        ring, prev, cur = [p0], p0, q0
        while True:
            opts = list(out.get(cur, ()))
            if cur == p0:
                opts.append(q0)                    # fechar o anel é uma das opções
            if not opts:                           # malha inconsistente: abandona o anel
                ring = []
                break
            q = opts[0] if len(opts) == 1 else _leftmost(coords, prev, cur, opts)
            if cur == p0 and q == q0:
                break
            out[cur].remove(q)
            if not out[cur]:
                del out[cur]
            ring.append(cur)
            prev, cur = cur, q
        for loop in _split_loops(ring):
            if len(loop) >= 3:
                rings.append(np.array([coords[k] for k in loop]))
    outers, holes = [], []
    for r in rings:
        a = signed_area(r[:, 0], r[:, 1])
        if a > 0:
            outers.append([r, a, []])
        elif a < 0:
            holes.append(r)
    if holes and outers:
        boxes = np.array([[o[0][:, 0].min(), o[0][:, 1].min(), o[0][:, 0].max(), o[0][:, 1].max()]
                          for o in outers])
        for h in holes:
            # um vértice do furo pode tocar o externo; o ponto médio de uma aresta não
            px, py = (h[0] + h[1]) / 2.0
            cand = np.nonzero((boxes[:, 0] <= px) & (px <= boxes[:, 2]) &
                              (boxes[:, 1] <= py) & (py <= boxes[:, 3]))[0]
            best = None
            for j in cand:
                if (best is None or outers[j][1] < outers[best][1]) and _inside(outers[j][0], px, py):
                    best = j
            if best is not None:
                outers[best][2].append(h)
    return [(o[0], o[2]) for o in outers]


def _split_loops(ring):
    """Separa um anel que passa duas vezes pelo mesmo vértice em anéis simples."""
    loops, stack, pos = [], [], {}
    for k in ring:
        if k in pos:                               # fechou um laço: k ... (k)
            i = pos[k]
            loop = stack[i:]
            for j in loop[1:]:
                del pos[j]
            del stack[i + 1:]
            loops.append(loop)
        else:
            pos[k] = len(stack)
            stack.append(k)
    loops.append(stack)
    return loops


def _leftmost(coords, prev, cur, options):
    if prev is None:
        return options[0]
    x0, y0 = coords[prev]
    x1, y1 = coords[cur]
    din = math.atan2(y1 - y0, x1 - x0)
    best, best_turn = None, None
    for q in options:
        x2, y2 = coords[q]
        turn = (math.atan2(y2 - y1, x2 - x1) - din + math.pi) % (2 * math.pi) - math.pi
        if best is None or turn > best_turn:       # maior ângulo = mais à esquerda (rente à área)
            best, best_turn = q, turn
    return best


def _inside(ring, px, py):
    x, y = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cond = (y > py) != (y2 > py)
    with np.errstate(divide="ignore", invalid="ignore"):
        xi = x + (py - y) * (x2 - x) / (y2 - y)
    return bool(np.count_nonzero(cond & (px < xi)) % 2)


def polygons_area(polys):
    return float(sum(abs(signed_area(o[:, 0], o[:, 1])) - sum(abs(signed_area(h[:, 0], h[:, 1])) for h in hs)
                     for o, hs in polys))


def dissolved_bands(xy, v, tri, edges, integrate=False):
    """{classe: [(anel externo, [furos]), ...]} das faixas de `v` (um multipolígono por classe).

    integrate=True devolve também {classe: integral de v na área da classe} (ex.: volume, se v
    for a diferença de cota), exata para v linear em cada triângulo.
    """
    mesh = BandMesh(xy, v, tri)
    edges = np.asarray(edges, float)
    thr_of = {k: float(t) for k, t in enumerate(edges)}
    by_band, total = defaultdict(list), defaultdict(float)
    for _, b, poly in mesh.pieces(edges):
        by_band[b].append(poly)
        if integrate:
            total[b] += mesh.integral(poly, thr_of)
    polys = {b: mesh.dissolve(pcs) for b, pcs in sorted(by_band.items())}
    return (polys, dict(total)) if integrate else polys


def dissolved_classes(xy, tri, cls):
    """Como `dissolved_bands`, mas com uma classe já atribuída a cada triângulo (cls (m,))."""
    mesh = BandMesh(xy, np.zeros(len(xy)), tri)
    # BandMesh descarta triângulos degenerados; reaplica a classe pelos que ficaram
    tri = np.asarray(tri, int)
    p = np.asarray(xy, float)[tri]
    det = ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
           - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    cls = np.asarray(cls)[det != 0]
    by_band = defaultdict(list)
    for t, c in zip(mesh.tri, cls):
        by_band[int(c)].append([mesh._vert(t[0]), mesh._vert(t[1]), mesh._vert(t[2])])
    return {b: mesh.dissolve(pcs) for b, pcs in sorted(by_band.items())}
