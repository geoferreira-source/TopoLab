"""Linhas de quebra: impõe polilinhas como arestas do TIN (Delaunay conforme).

Método: as linhas são divididas em subsegmentos; a cada rodada, os subsegmentos que
não aparecem como aresta da triangulação de Delaunay recebem um ponto no meio (com a
cota interpolada ao longo da linha) e a triangulação é refeita, até todos aparecerem.
O resultado continua sendo Delaunay e a linha é representada exatamente (com alguns
pontos a mais sobre ela). Não precisa de biblioteca extra.
"""
import numpy as np
from scipy.spatial import cKDTree

from .surface import Tin, _delaunay

TOL = 1e-6          # 1 µm: coincidência de pontos / ponto sobre segmento
MAX_ROUNDS = 80


def _chainage(xy):
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])


def _fill_z(xy, z, base_tin, xyz):
    """Cota dos vértices da linha: a informada; senão interpolada ao longo da linha; senão do MDT."""
    z = np.asarray(z, float).copy()
    fin = np.isfinite(z)
    if fin.all():
        return z
    if fin.any():
        s = _chainage(xy)
        return np.interp(s, s[fin], z[fin])
    zi = base_tin.z_at(xy)
    bad = ~np.isfinite(zi)
    if bad.any():  # fora do MDT: cota do ponto mais próximo
        _, nn = cKDTree(xyz[:, :2]).query(xy[bad])
        zi[bad] = xyz[nn, 2]
    return zi


def _prepare(lines, boundary, base_tin, xyz):
    """Lista de (polilinha (k, 3) com cotas preenchidas, cota_explicita)."""
    polys = [np.asarray(l, float) for l in lines]
    if boundary is not None:
        for ring, _ in boundary.rings:
            closed = np.vstack([ring, ring[:1]])
            polys.append(np.column_stack([closed, np.full(len(closed), np.nan)]))
    out = []
    for pl in polys:
        pl = pl.reshape(len(pl), -1)
        if pl.shape[1] == 2:
            pl = np.column_stack([pl, np.full(len(pl), np.nan)])
        pl = pl[np.isfinite(pl[:, :2]).all(axis=1)]
        if len(pl) > 1:
            pl = pl[np.concatenate([[True], np.any(np.diff(pl[:, :2], axis=0) != 0, axis=1)])]
        if len(pl) < 2:
            continue
        explicit = bool(np.isfinite(pl[:, 2]).any())
        out.append((np.column_stack([pl[:, :2], _fill_z(pl[:, :2], pl[:, 2], base_tin, xyz)]), explicit))
    return out


def _find_crossing(segs, P):
    """Primeiro par de segmentos que se cruzam em seus interiores, ou None."""
    A, B = P[segs[:, 0], :2], P[segs[:, 1], :2]
    n = len(segs)
    for i0 in range(0, n, 400):
        i1 = min(i0 + 400, n)
        p1, p2 = A[i0:i1, None, :], B[i0:i1, None, :]
        q1, q2 = A[None, :, :], B[None, :, :]

        def orient(a, b, c):
            return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
        d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
        d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
        hit = (d1 * d2 < 0) & (d3 * d4 < 0)
        if hit.any():
            r, c = np.argwhere(hit)[0]
            return i0 + int(r), int(c)
    return None


def split_crossings(lines, explicit=None):
    """Insere um vértice em cada cruzamento entre polilinhas diferentes e devolve as novas linhas.

    lines: polilinhas (k, 2) ou (k, 3); a cota do vértice inserido é interpolada no segmento.
    explicit: para cada linha, True se a cota é dela (medida). Cruzamentos entre duas linhas
    com cota própria ficam como estão (a cota no cruzamento seria ambígua).
    """
    lines = [np.asarray(l, float) for l in lines]
    explicit = list(explicit) if explicit is not None else [False] * len(lines)
    segs = [(li, si) for li, l in enumerate(lines) for si in range(len(l) - 1)]
    if len(lines) < 2 or not segs:
        return lines
    A = np.array([lines[li][si, :2] for li, si in segs])
    B = np.array([lines[li][si + 1, :2] for li, si in segs])
    owner = np.array([li for li, _ in segs])
    expl = np.array([explicit[li] for li, _ in segs])
    off = np.vstack([A, B]).mean(axis=0)
    A, B = A - off, B - off
    n = len(segs)
    lo, hi = np.minimum(A, B), np.maximum(A, B)
    cuts = {}  # (linha, segmento) -> [(t, x, y)]

    def orient(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
    for i0 in range(0, n, 400):
        i1 = min(i0 + 400, n)
        p1, p2 = A[i0:i1, None, :], B[i0:i1, None, :]
        q1, q2 = A[None, :, :], B[None, :, :]
        cand = ((lo[i0:i1, None, 0] <= hi[None, :, 0]) & (lo[None, :, 0] <= hi[i0:i1, None, 0])
                & (lo[i0:i1, None, 1] <= hi[None, :, 1]) & (lo[None, :, 1] <= hi[i0:i1, None, 1])
                & (owner[i0:i1, None] != owner[None, :]) & ~(expl[i0:i1, None] & expl[None, :]))
        d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
        d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
        hit = cand & (d1 * d2 < 0) & (d3 * d4 < 0)
        for r, c in np.argwhere(hit):
            i = i0 + int(r)
            if c <= i:
                continue
            t = d1[r, c] / (d1[r, c] - d2[r, c])          # posição no segmento i
            u = d3[r, c] / (d3[r, c] - d4[r, c])          # posição no segmento c
            cuts.setdefault(segs[i], []).append(float(t))
            cuts.setdefault(segs[c], []).append(float(u))
    out = []
    for li, l in enumerate(lines):
        pts = [l[0]]
        for si in range(len(l) - 1):
            for t in sorted(cuts.get((li, si), [])):
                pts.append(l[si] + t * (l[si + 1] - l[si]))
            pts.append(l[si + 1])
        out.append(np.array(pts))
    return out


def _gabriel_cuts(P, tree, u, v, max_depth=12):
    """Posições (0 < t < 1) onde dividir o segmento u-v para que nenhum ponto de P fique dentro
    do círculo diametral de cada pedaço. Sempre divide ao menos uma vez (o trecho estava
    faltando no Delaunay)."""
    a, b = P[u], P[v]
    cuts = []

    def rec(t0, t1, depth):
        pa, pb = a + t0 * (b - a), a + t1 * (b - a)
        r = 0.5 * float(np.hypot(*(pb - pa)))
        inside = [i for i in tree.query_ball_point((pa + pb) / 2, r * (1 - 1e-9)) if i not in (u, v)]
        if inside and depth < max_depth:
            tm = 0.5 * (t0 + t1)
            rec(t0, tm, depth + 1)
            cuts.append(tm)
            rec(tm, t1, depth + 1)

    tm = 0.5
    rec(0.0, tm, 1)
    cuts.append(tm)
    rec(tm, 1.0, 1)
    return cuts


def conform(xyz, lines, boundary=None):
    """Acrescenta ao conjunto de pontos os vértices das linhas (e pontos intermediários
    necessários) para que cada linha seja uma cadeia de arestas do Delaunay.

    Retorna (xyz ampliado, objeto Delaunay, centro) — a triangulação já calculada.
    """
    xyz = np.asarray(xyz, float)
    base_dela, c0 = _delaunay(xyz)
    base = Tin(xyz, base_dela.simplices, base_dela, c0, np.ones(len(base_dela.simplices), bool))
    polys = _prepare(lines, boundary, base, xyz)
    if not polys:
        return xyz, base_dela, c0
    # Cruzamentos sem ambiguidade (o limite, ou linhas sem cota própria) ganham um vértice;
    # depois, as linhas com cota própria entram por último para prevalecer nos vértices comuns.
    split = split_crossings([pl for pl, _ in polys], [e for _, e in polys])
    # linhas sem cota própria (limite, linhas sem Z) seguem o terreno também nos pontos inseridos
    split = [pl if e else np.column_stack([pl[:, :2], _fill_z(pl[:, :2], np.full(len(pl), np.nan), base, xyz)])
             for pl, (_, e) in zip(split, polys)]
    polys = sorted(((pl, e) for pl, (_, e) in zip(split, polys)), key=lambda p: p[1])

    xs, ys, zs = list(xyz[:, 0]), list(xyz[:, 1]), list(xyz[:, 2])
    index = {(round(x, 6), round(y, 6)): i for i, (x, y) in enumerate(zip(xs, ys))}

    def add(x, y, z, override=False):
        key = (round(x, 6), round(y, 6))
        i = index.get(key)
        if i is None:
            i = len(xs)
            index[key] = i
            xs.append(x), ys.append(y), zs.append(z)
        elif override and np.isfinite(z):
            zs[i] = z          # a cota medida na linha vale mais que a do ponto coincidente
        return i

    segs, explicit_seg = set(), set()
    for pl, explicit in polys:
        ids = [add(x, y, z, override=True) for x, y, z in pl]
        for u, v in zip(ids[:-1], ids[1:]):
            if u != v:
                key = (min(u, v), max(u, v))
                segs.add(key)
                if explicit:
                    explicit_seg.add(key)

    # Pontos que já estão sobre um segmento (cruzamentos em T, pontos alinhados) dividem-no:
    P = np.column_stack([xs, ys])
    tree = cKDTree(P)
    split = set()
    for u, v in segs:
        a, b = P[u], P[v]
        d = b - a
        L = float(np.hypot(*d))
        near = [i for i in tree.query_ball_point((a + b) / 2, L / 2 + TOL) if i not in (u, v)]
        on = []
        for i in near:
            t = float(np.dot(P[i] - a, d)) / (L * L)
            dist = abs(d[0] * (P[i][1] - a[1]) - d[1] * (P[i][0] - a[0])) / L
            if dist <= TOL and TOL < t * L < L - TOL:
                on.append((t, i))
        chain = [u] + [i for _, i in sorted(on)] + [v]
        split.update((min(p, q), max(p, q)) for p, q in zip(chain[:-1], chain[1:]))
        if (u, v) in explicit_seg:  # linha com cota própria: ela define a cota ao longo do trecho
            explicit_seg.update((min(p, q), max(p, q)) for p, q in zip(chain[:-1], chain[1:]))
            for t, i in on:
                zs[i] = zs[u] + t * (zs[v] - zs[u])
    segs = split

    arr = np.array(sorted(segs))
    cross = _find_crossing(arr, np.column_stack([xs, ys])) if len(arr) > 1 else None
    if cross is not None:
        i, j = cross
        P = np.column_stack([xs, ys])
        a, b = P[arr[i][0]], P[arr[i][1]]
        c, d = P[arr[j][0]], P[arr[j][1]]
        r, s = b - a, d - c
        t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / (r[0] * s[1] - r[1] * s[0])
        x, y = a + t * r  # ponto do cruzamento
        raise ValueError(
            "Há linhas de quebra (ou o limite) que se cruzam sem um vértice no cruzamento, em "
            f"({x:.3f}; {y:.3f}). Insira um vértice comum no cruzamento.")

    for _ in range(MAX_ROUNDS):
        pts = np.column_stack([xs, ys, zs])
        dela, center = _delaunay(pts)
        tri = dela.simplices
        e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
        n = len(pts)
        have = set((e[:, 0].astype(np.int64) * n + e[:, 1]).tolist())
        missing = [s for s in segs if s[0] * n + s[1] not in have]
        if not missing:
            return pts, dela, center
        # Cada trecho que falta é dividido de uma vez até que nenhum ponto existente fique
        # dentro do círculo que tem o pedaço como diâmetro (aresta de Gabriel: está sempre no
        # Delaunay). Assim bastam uma ou duas triangulações a mais, em vez de uma por bisseção.
        tree = cKDTree(pts[:, :2])
        plans = [(u, v, _gabriel_cuts(pts[:, :2], tree, u, v)) for u, v in missing]
        where = np.array([(xs[u] + t * (xs[v] - xs[u]), ys[u] + t * (ys[v] - ys[u]))
                          for u, v, ts in plans for t in ts])
        # cota do terreno para os pontos sem cota própria (limite, linhas sem Z): da triangulação
        # atual, que já tem os vértices das linhas com cota (no vale, a "base" sem as linhas
        # daria o fundo raso)
        cur = Tin(pts, tri, dela, center, np.ones(len(tri), bool))
        z_mdt = cur.z_at(where)
        bad = ~np.isfinite(z_mdt)
        if bad.any():
            z_mdt[bad] = base.z_at(where[bad])
        k = 0
        for u, v, ts in plans:
            segs.discard((u, v))
            own = (u, v) in explicit_seg
            chain = [u]
            for t in ts:
                # cota própria: interpolada ao longo da linha; sem cota (limite): a do terreno
                mz = zs[u] + t * (zs[v] - zs[u]) if own or not np.isfinite(z_mdt[k]) else float(z_mdt[k])
                m = add(where[k, 0], where[k, 1], mz)
                k += 1
                if m in (u, v) or m == chain[-1]:
                    raise ValueError("Não foi possível impor uma linha de quebra: segmento curto demais "
                                     f"perto de ({xs[u]:.3f}; {ys[u]:.3f}).")
                chain.append(m)
            chain.append(v)
            pieces = [(min(a, b), max(a, b)) for a, b in zip(chain[:-1], chain[1:])]
            segs.update(pieces)
            if own:
                explicit_seg.update(pieces)
    raise ValueError("Não foi possível impor as linhas de quebra (muitas subdivisões). Verifique se "
                     "há linhas sobrepostas ou muito próximas de pontos do levantamento.")
