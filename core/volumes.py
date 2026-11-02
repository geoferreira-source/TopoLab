"""Volumes de corte e aterro sobre TIN (soluções exatas por triângulo)."""
from dataclasses import dataclass

import numpy as np

from .region import Region
from .surface import Tin, build_tin


@dataclass
class VolumeResult:
    cut: float         # volume acima da referência (material a remover)
    fill: float        # volume abaixo da referência (material a aterrar)
    cut_area: float    # área em planta onde há corte
    fill_area: float   # área em planta onde há aterro
    total_area: float  # área em planta total considerada

    @property
    def net(self):
        """Saldo = corte - aterro (positivo: sobra material)."""
        return self.cut - self.fill


def _triangle_areas(xy, tri):
    a, b, c = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
    return 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                        - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


def _split_heights(h, area):
    """Para cada triângulo plano com alturas `h` (m, 3) nos vértices, devolve
    volume e área da parte positiva e da parte negativa (relação a h = 0).
    Fórmulas fechadas, exatas para função linear no triângulo.
    """
    m = len(h)
    vol_pos, vol_neg = np.zeros(m), np.zeros(m)
    a_pos, a_neg = np.zeros(m), np.zeros(m)
    npos = (h > 0).sum(axis=1)
    mean = h.mean(axis=1)
    s = np.sort(h, axis=1)

    k = npos == 3
    vol_pos[k], a_pos[k] = area[k] * mean[k], area[k]

    k = npos == 0
    vol_neg[k], a_neg[k] = -area[k] * mean[k], area[k]

    k = npos == 1  # um vértice acima
    hp, p, q = s[k, 2], s[k, 0], s[k, 1]
    den = (hp - p) * (hp - q)
    vol_pos[k] = area[k] * hp ** 3 / (3 * den)
    a_pos[k] = area[k] * hp ** 2 / den
    vol_neg[k] = vol_pos[k] - area[k] * mean[k]
    a_neg[k] = area[k] - a_pos[k]

    k = npos == 2  # um vértice abaixo (ou sobre) a referência
    hn, p, q = s[k, 0], s[k, 1], s[k, 2]
    den = (p - hn) * (q - hn)
    vol_neg[k] = area[k] * (-hn) ** 3 / (3 * den)
    a_neg[k] = area[k] * hn ** 2 / den
    vol_pos[k] = vol_neg[k] + area[k] * mean[k]
    a_pos[k] = area[k] - a_neg[k]

    return vol_pos, vol_neg, a_pos, a_neg


def _areas_p(P):
    a, b, c = P[:, 0], P[:, 1], P[:, 2]
    return 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                        - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


def _halfplane(poly, vals, keep_positive):
    """Recorta um polígono convexo pelo semiplano onde a função linear (valores
    `vals` nos vértices) é >= 0 (ou <= 0)."""
    out, n = [], len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        vp, vq = vals[i], vals[(i + 1) % n]
        sp = vp >= 0 if keep_positive else vp <= 0
        sq = vq >= 0 if keep_positive else vq <= 0
        if sp:
            out.append(p)
        if sp != sq:
            t = vp / (vp - vq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def _clip_convex(subject, clip):
    """Sutherland-Hodgman: recorta `subject` (qualquer polígono) por `clip` (convexo, anti-horário)."""
    out = subject
    for i in range(len(clip)):
        if not out:
            break
        a, b = clip[i], clip[(i + 1) % len(clip)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        inp, out = out, []
        s = inp[-1]
        s_in = dx * (s[1] - a[1]) - dy * (s[0] - a[0]) >= 0
        for e in inp:
            e_in = dx * (e[1] - a[1]) - dy * (e[0] - a[0]) >= 0
            if e_in != s_in:
                # interseção da aresta s->e com a reta a->b
                ex, ey = e[0] - s[0], e[1] - s[1]
                den = dx * ey - dy * ex
                if den != 0:
                    t = (dx * (a[1] - s[1]) - dy * (a[0] - s[0])) / den
                    out.append((s[0] + t * ex, s[1] + t * ey))
            if e_in:
                out.append(e)
            s, s_in = e, e_in
    return out


def _area_centroid(poly):
    n = len(poly)
    if n < 3:
        return 0.0, 0.0, 0.0
    x0, y0 = poly[0]
    a2 = cx = cy = 0.0
    for i in range(n):
        x1, y1 = poly[i][0] - x0, poly[i][1] - y0
        x2, y2 = poly[(i + 1) % n][0] - x0, poly[(i + 1) % n][1] - y0
        cr = x1 * y2 - x2 * y1
        a2 += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    if abs(a2) < 1e-300:
        return 0.0, 0.0, 0.0
    return a2 / 2, cx / (3 * a2) + x0, cy / (3 * a2) + y0


def _integrate_triangle(P3, h3, ring_lists):
    """Volume/área positivos e negativos de um triângulo recortado pela região."""
    (x0, y0), (x1, y1), (x2, y2) = P3
    h0, h1, h2 = h3
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if det == 0:
        return 0.0, 0.0, 0.0, 0.0
    tri, vals = [(x0, y0), (x1, y1), (x2, y2)], [h0, h1, h2]
    if det < 0:  # garante sentido anti-horário
        tri, vals = [tri[0], tri[2], tri[1]], [h0, h2, h1]
        (x1, y1), (x2, y2), h1, h2 = (x2, y2), (x1, y1), h2, h1
        det = -det
    gx = ((h1 - h0) * (y2 - y0) - (h2 - h0) * (y1 - y0)) / det
    gy = ((x1 - x0) * (h2 - h0) - (x2 - x0) * (h1 - h0)) / det

    vp = vn = ap = an = 0.0
    for keep_pos in (True, False):
        piece = _halfplane(tri, vals, keep_pos)
        if len(piece) < 3:
            continue
        # Parte degenerada (ponto/linha, ex.: vértice exatamente na cota): sem área.
        if abs(_area_centroid(piece)[0]) <= 1e-12 * det:
            continue
        integral = area = 0.0
        for ring, sign in ring_lists:
            clipped = _clip_convex(ring, piece)
            a, cx, cy = _area_centroid(clipped)
            if a:
                integral += sign * a * (h0 + gx * (cx - x0) + gy * (cy - y0))
                area += sign * a
        if keep_pos:
            vp, ap = integral, area
        else:
            vn, an = -integral, area
    return vp, vn, ap, an


def _result_clipped(xy, tri, h, region: Region):
    """Como _result_from_heights, mas só dentro de `region` (exato por triângulo)."""
    P = xy[tri]
    off = P.reshape(-1, 2).mean(axis=0)  # desloca para perto da origem (precisão)
    P = P - off
    region = region.translated(off)

    tx0, tx1 = P[:, :, 0].min(axis=1), P[:, :, 0].max(axis=1)
    ty0, ty1 = P[:, :, 1].min(axis=1), P[:, :, 1].max(axis=1)
    bx0, by0, bx1, by1 = region.bbox
    near = np.nonzero((tx1 >= bx0) & (tx0 <= bx1) & (ty1 >= by0) & (ty0 <= by1))[0]
    touch = region.touches(tx0[near], tx1[near], ty0[near], ty1[near])
    boundary, rest = near[touch], near[~touch]

    # Triângulos que nenhuma aresta do polígono cruza: ou inteiros dentro, ou fora.
    inside = region.contains(P[rest].mean(axis=1))
    full = rest[inside]
    area_f = _areas_p(P[full])
    vp, vn, ap, an = _split_heights(h[full], area_f)
    cut, fill = vp.sum(), vn.sum()
    cut_a, fill_a = ap.sum(), an.sum()
    total = area_f.sum()

    for i in boundary:  # poucos: só os da borda do polígono
        a, b, c, d = _integrate_triangle(P[i], h[i], region.ring_lists)
        cut, fill, cut_a, fill_a = cut + a, fill + b, cut_a + c, fill_a + d
        total += c + d
    return VolumeResult(cut=float(cut), fill=float(fill), cut_area=float(cut_a),
                        fill_area=float(fill_a), total_area=float(total))


def _result_from_heights(xy, tri, h, region=None):
    if region is not None:
        return _result_clipped(xy, tri, h, region)
    area = _triangle_areas(xy, tri)
    vp, vn, ap, an = _split_heights(h, area)
    return VolumeResult(cut=float(vp.sum()), fill=float(vn.sum()),
                        cut_area=float(ap.sum()), fill_area=float(an.sum()),
                        total_area=float(area.sum()))


def volume_vs_datum(tin: Tin, datum: float, region: Region = None) -> VolumeResult:
    """Corte (terreno acima de `datum`) e aterro (abaixo) contra uma cota fixa.

    region: se informado, considera apenas a parte do TIN dentro do(s) polígono(s).
    """
    xy = tin.points[:, :2]
    h = tin.points[tin.triangles, 2] - datum
    return _result_from_heights(xy, tin.triangles, h, region)


def difference_surface(tin_a: Tin, tin_b: Tin, use_lines=True):
    """TIN composto da diferença zA - zB sobre a união dos vértices das duas superfícies.

    As linhas de quebra e os limites das duas superfícies (``Tin.lines``) viram arestas do
    TIN composto, com um vértice onde linhas de A e de B se cruzam: assim a diferença não
    atravessa taludes, cristas e valas de nenhuma das duas.
    Retorna (pontos (n, 3) com z = diferença, triângulos (m, 3)), só na região em que
    as duas superfícies existem.
    """
    pts = np.unique(np.vstack([tin_a.points[:, :2], tin_b.points[:, :2]]), axis=0)
    za, zb = tin_a.z_at(pts, use_kept=False), tin_b.z_at(pts, use_kept=False)
    ok = np.isfinite(za) & np.isfinite(zb)
    if ok.sum() < 3:
        raise ValueError("As superfícies não se sobrepõem.")
    lines = ((tin_a.lines or []) + (tin_b.lines or [])) if use_lines else []
    if lines:
        from .breaklines import split_crossings
        base = build_tin(np.column_stack([pts[ok], np.zeros(int(ok.sum()))]),
                         breaklines=split_crossings(lines))
        q = base.points[:, :2]
        dz = tin_a.z_at(q, use_kept=False) - tin_b.z_at(q, use_kept=False)
        diff = Tin(points=np.column_stack([q, dz]), triangles=base.triangles)
        tri_ok = np.isfinite(dz[diff.triangles]).all(axis=1)
    else:
        diff = build_tin(np.column_stack([pts[ok], (za - zb)[ok]]))
        tri_ok = np.ones(len(diff.triangles), bool)
    cent = diff.points[diff.triangles, :2].mean(axis=1)
    inside = tri_ok & np.isfinite(tin_a.z_at(cent)) & np.isfinite(tin_b.z_at(cent))
    tri = diff.triangles[inside]
    if len(tri) == 0:
        raise ValueError("As superfícies não se sobrepõem.")
    return diff.points, tri


def volume_between(tin_a: Tin, tin_b: Tin, region: Region = None) -> VolumeResult:
    """Volume entre duas superfícies: A = original, B = final (projeto/2º levantamento).

    Corte = onde A está acima de B; aterro = onde A está abaixo de B.
    Método: TIN composto (ver `difference_surface`). Aproximação nas interseções.
    """
    pts, tri = difference_surface(tin_a, tin_b)
    return _result_from_heights(pts[:, :2], tri, pts[tri, 2], region)
