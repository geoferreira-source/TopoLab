"""Mapas temáticos sobre TIN: declividade, faixas de elevação, inundação, corte/aterro."""
import numpy as np
from .geom import signed_area

# Classes de relevo (declividade em %), usadas pela EMBRAPA; o usuário pode informar outras.
SLOPE_EDGES = [3.0, 8.0, 20.0, 45.0, 75.0]
SLOPE_LABELS = ["Plano (0–3%)", "Suave ondulado (3–8%)", "Ondulado (8–20%)",
                "Forte ondulado (20–45%)", "Montanhoso (45–75%)", "Escarpado (>75%)"]


def triangle_stats(tin):
    """Declividade, orientação e áreas (planta e superfície) de cada triângulo do TIN."""
    P = tin.points[tin.triangles]
    x, y, z = P[:, :, 0], P[:, :, 1], P[:, :, 2]
    det = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    safe = np.where(det == 0, np.nan, det)
    gx = ((z[:, 1] - z[:, 0]) * (y[:, 2] - y[:, 0]) - (z[:, 2] - z[:, 0]) * (y[:, 1] - y[:, 0])) / safe
    gy = ((x[:, 1] - x[:, 0]) * (z[:, 2] - z[:, 0]) - (x[:, 2] - x[:, 0]) * (z[:, 1] - z[:, 0])) / safe
    g = np.hypot(gx, gy)
    area2d = 0.5 * np.abs(det)
    return {
        "slope_pct": g * 100.0,
        "slope_deg": np.degrees(np.arctan(g)),
        # azimute da direção de maior descida (0 = Norte, horário); NaN em área plana
        "aspect": np.where(g > 1e-12, np.degrees(np.arctan2(-gx, -gy)) % 360.0, np.nan),
        "area2d": area2d,
        "area3d": area2d * np.sqrt(1.0 + gx ** 2 + gy ** 2),
    }


def surface_area(tin):
    """(área em planta, área da superfície 3D) do TIN."""
    st = triangle_stats(tin)
    return float(np.nansum(st["area2d"])), float(np.nansum(st["area3d"]))


def class_index(values, edges):
    """Índice da classe: 0 abaixo do 1º limite; k entre edges[k-1] e edges[k]; len(edges) acima."""
    return np.searchsorted(np.asarray(edges, float), values, side="right")


def class_labels(edges, unit=""):
    e = list(edges)
    fmt = lambda v: f"{v:g}".replace(".", ",")  # noqa: E731
    labels = [f"< {fmt(e[0])}{unit}"]
    labels += [f"{fmt(a)} a {fmt(b)}{unit}" for a, b in zip(e[:-1], e[1:])]
    labels.append(f"≥ {fmt(e[-1])}{unit}")
    return labels


def _clip(poly, vals, thr, keep_above):
    out_p, out_v, n = [], [], len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        vp, vq = vals[i], vals[(i + 1) % n]
        sp = vp >= thr if keep_above else vp <= thr
        sq = vq >= thr if keep_above else vq <= thr
        if sp:
            out_p.append(p)
            out_v.append(vp)
        if sp != sq:
            t = (thr - vp) / (vq - vp)
            out_p.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
            out_v.append(thr)
    return out_p, out_v


def _area(poly):
    if len(poly) < 3:
        return 0.0
    a = np.array(poly)
    return abs(signed_area(a[:, 0], a[:, 1]))


def band_polygons(P, v, edges):
    """Divide cada triângulo em polígonos por faixas de um valor linear nos vértices.

    P: (m, 3, 2) vértices; v: (m, 3) valores; edges: limites crescentes.
    Retorna lista de (índice do triângulo, faixa, [(x, y), ...]); faixa 0 = abaixo do 1º
    limite, k = [edges[k-1], edges[k]), len(edges) = acima do último. Exato (interpolação linear).
    """
    edges = np.asarray(edges, dtype=float)
    P, v = np.asarray(P, float), np.asarray(v, float)
    bmin, bmax = class_index(v.min(axis=1), edges), class_index(v.max(axis=1), edges)
    out = []
    for i in range(len(P)):
        tri = [tuple(p) for p in P[i]]
        if bmin[i] == bmax[i]:
            out.append((i, int(bmin[i]), tri))
            continue
        tri_area = _area(tri)
        for b in range(int(bmin[i]), int(bmax[i]) + 1):
            poly, vals = tri, list(v[i])
            if b > 0:
                poly, vals = _clip(poly, vals, edges[b - 1], True)
            if b < len(edges) and len(poly) >= 3:
                poly, vals = _clip(poly, vals, edges[b], False)
            if len(poly) >= 3 and _area(poly) > 1e-9 * tri_area:
                out.append((i, b, poly))
    return out


def tolerance_edges(edges, tol):
    """Limites de classe da mancha de corte e aterro com uma faixa "sem alteração" [-tol, tol).

    Os limites informados dentro de (-tol, tol) somem (inclusive o zero) e entram -tol e +tol.
    Retorna (limites, índice da faixa sem alteração). tol é no mínimo 1 mm, para que áreas
    idênticas nas duas superfícies não virem "corte de 0 a ...".
    """
    tol = max(float(tol), 0.001)
    kept = {float(e) for e in edges if abs(float(e)) >= tol}
    out = sorted(kept | {-tol, tol})
    return out, out.index(-tol) + 1
