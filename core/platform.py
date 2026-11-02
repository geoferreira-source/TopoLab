"""Platô horizontal com taludes de corte e aterro sobre um TIN (terraplenagem).

Modelo
------
Dentro do polígono do platô a superfície final é o plano na cota H. Fora dele, os taludes
partem da borda com inclinação constante, dada como horizontal por 1 de vertical (H:V):
a uma distância ``d`` da borda, o talude de corte está na cota ``H + d/m_corte`` e o de
aterro em ``H - d/m_aterro``. A superfície final é o terreno T limitado por esses dois
taludes::

    final = min(max(T, H - d/m_aterro), H + d/m_corte)

Assim, onde o terreno passa acima do talude de corte há corte, onde passa abaixo do
talude de aterro há aterro, e entre os dois o terreno fica como está. O off-set (crista do
corte e pé do aterro) é a linha em que o talude encontra o terreno. Nos cantos convexos
o talude forma um cone (canto arredondado); nos côncavos, os dois planos se encontram
numa aresta. Talude 0 = parede vertical (muro), sem avanço para fora do platô.

Bermas: com altura de berma h e largura w, o talude sobe (ou desce) h metros, segue w metros
na horizontal e recomeça, como uma escada. ``d/m`` vira a altura do talude em degraus,
``rise(d)``; o resto do cálculo não muda, porque só depende dessa altura em cada ponto.

Cálculo
-------
O volume é a integral de (T - final) numa malha regular de células que cobre o platô e o
alcance máximo dos taludes (regra do ponto médio; o integrando é contínuo, então o erro
cai com o quadrado do tamanho da célula). A cota de equilíbrio (corte = aterro x fator) é
obtida por bisseção, já que o saldo diminui sempre que H sobe; cada avaliação é uma busca
binária em valores pré-ordenados.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from .contours import contour_lines, is_master, make_levels
from .region import Region
from .surface import Tin
from .volumes import VolumeResult
from .geom import signed_area

TARGET_CELLS = 250_000     # malha fina automática
COARSE_CELLS = 40_000      # malha grossa (localiza a área e a cota de equilíbrio)
MAX_CELLS = 2_000_000      # limite de memória/tempo
MIN_CELLS_ACROSS = 40      # células na menor dimensão do platô (malha automática)


@dataclass
class OffsetLine:
    kind: str          # "Corte" (crista do corte), "Aterro" (pé do aterro) ou "Fora do MDT"
    xyz: np.ndarray    # (k, 3)

    @property
    def length(self):
        return float(np.hypot(*np.diff(self.xyz[:, :2], axis=0).T).sum())


@dataclass
class PlatformResult:
    level: float            # cota do platô usada
    cut: float              # volume de corte (platô + taludes)
    fill: float             # volume de aterro
    cut_area: float         # área em planta com corte
    fill_area: float        # área em planta com aterro
    platform_area: float    # área do polígono do platô
    footprint_area: float   # área total da terraplenagem (dentro do off-set)
    complete: bool          # False se o platô ou os taludes saem da área do MDT
    cell: float             # tamanho da célula usada no cálculo
    factor: float = 1.0     # fator de homogeneização (corte necessário = aterro x fator)
    balanced: bool = False  # True se `level` é a cota de equilíbrio calculada
    offsets: list = field(default_factory=list)    # [OffsetLine]
    contours: list = field(default_factory=list)   # [(cota, mestra, [(x, y), ...])]
    benches: dict = field(default_factory=dict)    # {"Corte": n, "Aterro": n} bermas usadas

    @property
    def net(self):
        """Saldo = corte - aterro (positivo: sobra material)."""
        return self.cut - self.fill

    @property
    def balance(self):
        """Corte - aterro x fator (zero na cota de equilíbrio)."""
        return self.cut - self.fill * self.factor

    def volume_result(self):
        return VolumeResult(cut=self.cut, fill=self.fill, cut_area=self.cut_area,
                            fill_area=self.fill_area, total_area=self.footprint_area)


def _inv(m):
    """1/m, com m = 0 (parede vertical) -> infinito."""
    if m < 0:
        raise ValueError("A inclinação do talude não pode ser negativa.")
    return math.inf if m == 0 else 1.0 / m


class Slope:
    """Talude H:V com bermas opcionais: altura atingida a uma distância horizontal da borda.

    m: inclinação H:V (0 = vertical). bench_h: desnível entre bermas (0 = sem bermas).
    bench_w: largura de cada berma (plana). As bermas contam a partir da borda do platô.
    """

    def __init__(self, m, bench_h=0.0, bench_w=0.0):
        self.inv = _inv(m)
        self.m = float(m)
        self.h = float(bench_h or 0.0)
        self.w = float(bench_w or 0.0)
        if self.h < 0 or self.w < 0:
            raise ValueError("Altura e largura de berma não podem ser negativas.")
        if self.benched and self.m == 0:
            raise ValueError("Bermas exigem talude inclinado (H:V maior que zero).")
        self.period = self.m * self.h + self.w

    @property
    def benched(self):
        return self.h > 0 and self.w > 0

    def rise(self, d):
        """Altura do talude a uma distância d (> 0) da borda do platô."""
        d = np.asarray(d, float)
        if not self.benched:
            with np.errstate(invalid="ignore"):
                return d * self.inv
        k = np.floor(d / self.period)
        r = d - k * self.period
        return k * self.h + np.minimum(r / self.m, self.h)

    def run(self, height):
        """Distância horizontal para o talude atingir `height` (inverso de rise)."""
        height = max(float(height), 0.0)
        if not self.benched:
            return self.m * height
        if height == 0:
            return 0.0
        k = math.ceil(height / self.h) - 1          # bermas completas antes desta altura
        return k * self.period + (height - k * self.h) * self.m

    def bench_distances(self, max_height):
        """[(k, altura, d da borda externa, d da borda interna)] das bermas até max_height."""
        out = []
        if not self.benched:
            return out
        k = 1
        while k * self.h < max_height:
            out.append((k, k * self.h, k * self.period - self.w, k * self.period))
            k += 1
        return out


def _as_slope(s):
    return s if isinstance(s, Slope) else Slope(s)


def _dist_to_rings(P, region: Region):
    """Distância de cada ponto (n, 2) à borda mais próxima (anéis externos e furos)."""
    best = np.full(len(P), np.inf)
    x, y = P[:, 0], P[:, 1]
    for ring, _ in region.rings:
        for (ax, ay), (bx, by) in zip(ring, np.roll(ring, -1, axis=0)):
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            tx, ty = x - ax, y - ay
            t = np.clip((tx * dx + ty * dy) / L2, 0.0, 1.0)
            tx -= t * dx
            ty -= t * dy
            np.minimum(best, tx * tx + ty * ty, out=best)   # distância ao quadrado
    return np.sqrt(best, out=best)


def _region_area(region: Region):
    total = 0.0
    for ring, sign in region.rings:
        x, y = ring[:, 0], ring[:, 1]
        total += sign * abs(signed_area(x, y))
    return total


def _ring_area(path):
    a = np.asarray(path, float)
    return signed_area(a[:, 0], a[:, 1])


def _closed_rings_area(paths):
    """Área delimitada por anéis fechados (regra par-ímpar: anel dentro de anel = furo)."""
    rings = [np.asarray(p, float) for p in paths]
    if any(len(r) < 4 or not np.array_equal(r[0], r[-1]) for r in rings):
        return None
    total = 0.0
    for i, r in enumerate(rings):
        depth = sum(Region([(o, [])]).contains(r[:1])[0] for j, o in enumerate(rings) if j != i)
        total += (-1) ** depth * abs(_ring_area(r))
    return total


def _domain(tin: Tin, region: Region, m_cut, m_fill, h_lo, h_hi):
    """Retângulo que contém o platô e o maior alcance possível dos taludes (cotas h_lo..h_hi),
    limitado à extensão do MDT."""
    z = tin.points[:, 2]
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
    reach = max(_as_slope(m_cut).run(zmax - h_lo), _as_slope(m_fill).run(h_hi - zmin))
    bx0, by0, bx1, by1 = region.bbox
    tx0, ty0 = tin.points[:, :2].min(axis=0)
    tx1, ty1 = tin.points[:, :2].max(axis=0)
    box = (max(bx0 - reach, tx0), max(by0 - reach, ty0), min(bx1 + reach, tx1), min(by1 + reach, ty1))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("O platô está fora da área do MDT.")
    return box


class _Grid:
    """Malha de células (centros) com o terreno, a distância à borda e o lado do platô.

    O corte de uma célula é max(a - H, 0) e o aterro max(H - b, 0), com a = T - d/m_corte e
    b = T + d/m_aterro (fora do platô; dentro, a = b = T). Como a e b não dependem de H,
    ficam ordenados com somas acumuladas: cada avaliação dos totais é uma busca binária.
    """

    def __init__(self, tin: Tin, region: Region, m_cut, m_fill, box, cell=0.0,
                 target=TARGET_CELLS, min_across=MIN_CELLS_ACROSS):
        s_cut, s_fill = _as_slope(m_cut), _as_slope(m_fill)
        x0, y0, x1, y1 = box
        area = (x1 - x0) * (y1 - y0)
        if not cell or cell <= 0:
            cell = math.sqrt(area / target)
            if min_across:
                bx0, by0, bx1, by1 = region.bbox
                cell = min(cell, min(bx1 - bx0, by1 - by0) / min_across)
            cell = max(cell, math.sqrt(area / MAX_CELLS))
        # duas células de folga para o off-set não encostar na borda da malha
        x0, y0, x1, y1 = x0 - 2 * cell, y0 - 2 * cell, x1 + 2 * cell, y1 + 2 * cell
        nx, ny = int(math.ceil((x1 - x0) / cell)), int(math.ceil((y1 - y0) / cell))
        if nx * ny > MAX_CELLS:
            raise ValueError(
                f"Resolução fina demais ({nx * ny:,} células). Use células de pelo menos "
                f"{math.sqrt(area / MAX_CELLS):.2f} (ou 0 = automática).".replace(",", "."))
        self.box, self.cell, self.nx, self.ny = (x0, y0, x1, y1), float(cell), nx, ny
        self.xs = x0 + (np.arange(nx) + 0.5) * cell
        self.ys = y0 + (np.arange(ny) + 0.5) * cell
        X, Y = np.meshgrid(self.xs, self.ys)
        P = np.column_stack([X.ravel(), Y.ravel()])
        del X, Y
        self.T = tin.z_at(P).reshape(ny, nx)
        self.inside = region.contains(P).reshape(ny, nx)
        self.d = _dist_to_rings(P, region).reshape(ny, nx)
        del P
        self.region, self.tin = region, tin
        if not np.isfinite(self.T[self.inside]).any():
            raise ValueError("O platô está fora da área do MDT.")
        finite = np.isfinite(self.T)
        self.tmin, self.tmax = float(self.T[finite].min()), float(self.T[finite].max())
        d = np.where(self.inside, 0.0, self.d)
        with np.errstate(invalid="ignore"):
            self.up = np.where(d > 0, s_cut.rise(d), 0.0)     # talude de corte acima de H
            self.down = np.where(d > 0, s_fill.rise(d), 0.0)  # talude de aterro abaixo de H
        self.a, self.b = self.T - self.up, self.T + self.down
        sa = np.sort(self.a[np.isfinite(self.a)])
        sb = np.sort(self.b[np.isfinite(self.b)])
        self._sa, self._sa_suf = sa, np.concatenate([np.cumsum(sa[::-1])[::-1], [0.0]])
        self._sb, self._sb_pre = sb, np.concatenate([[0.0], np.cumsum(sb)])

    def totals(self, level):
        """(volume de corte, volume de aterro) com o platô na cota `level`."""
        i = int(np.searchsorted(self._sa, level, side="right"))
        j = int(np.searchsorted(self._sb, level, side="left"))
        cut = self._sa_suf[i] - level * (len(self._sa) - i)
        fill = level * j - self._sb_pre[j]
        area = self.cell * self.cell
        return max(float(cut), 0.0) * area, max(float(fill), 0.0) * area

    def depths(self, level):
        """(profundidade de corte, altura de aterro) por célula; NaN fora do MDT."""
        return np.maximum(self.a - level, 0.0), np.maximum(level - self.b, 0.0)

    def psi(self, level):
        """Positivo dentro da área terraplenada, negativo fora; zero no off-set.

        Dentro do platô vale a distância à borda; fora, a altura de corte ou de aterro
        (negativa onde o terreno fica entre os taludes), limitada a -distância. Assim a
        borda de um muro vertical (talude 0) também cai exatamente no lugar.
        """
        with np.errstate(invalid="ignore"):
            v = np.maximum(self.a - level, level - self.b)
        out = np.where(np.isfinite(v), np.maximum(v, -self.d), -self.d)
        return np.where(self.inside, self.d, out)

    def footprint_box(self, h_lo, h_hi, margin=2):
        """Retângulo da área terraplenada para qualquer cota em [h_lo, h_hi], com folga."""
        with np.errstate(invalid="ignore"):
            foot = self.inside | (self.a > h_lo) | (self.b < h_hi)
        jj, ii = np.nonzero(foot)
        x0, y0, x1, y1 = self.box
        c = self.cell
        return (max(self.xs[ii.min()] - (margin + 0.5) * c, x0), max(self.ys[jj.min()] - (margin + 0.5) * c, y0),
                min(self.xs[ii.max()] + (margin + 0.5) * c, x1), min(self.ys[jj.max()] + (margin + 0.5) * c, y1))

    def final(self, level):
        return np.minimum(np.maximum(self.T, level - self.down), level + self.up)

    def lattice_contours(self, Z, levels, cells=None):
        """Curvas de um campo Z nos centros das células (triângulos marchantes).

        Retorna [(cota, [(x, y), ...])] para cada cota de `levels`.
        """
        z00, z01, z10, z11 = Z[:-1, :-1], Z[:-1, 1:], Z[1:, :-1], Z[1:, 1:]
        with np.errstate(invalid="ignore"):
            lo = np.minimum(np.minimum(z00, z01), np.minimum(z10, z11))
            hi = np.maximum(np.maximum(z00, z01), np.maximum(z10, z11))
        if cells is not None:
            lo = np.where(cells, lo, np.nan)
        out, nx, zr = [], self.nx, Z.ravel()
        for level in levels:
            with np.errstate(invalid="ignore"):
                jj, ii = np.nonzero((lo < level) & (hi >= level))
            if len(jj) == 0:
                continue
            n00 = jj * nx + ii
            n01, n10, n11 = n00 + 1, n00 + nx, n00 + nx + 1
            tri = np.vstack([np.column_stack([n00, n01, n11]), np.column_stack([n00, n11, n10])])
            used, inv = np.unique(tri, return_inverse=True)
            pts = np.column_stack([self.xs[used % nx], self.ys[used // nx], zr[used]])
            out += [(level, p) for p in contour_lines(Tin(points=pts, triangles=inv.reshape(-1, 3)), level)]
        return out

    def touches_inner_border(self, foot, outer_box):
        """True se a área terraplenada encosta numa borda da malha que não é a do domínio."""
        x0, y0, x1, y1 = self.box
        ox0, oy0, ox1, oy1 = outer_box
        tol = 1e-9 + 0.5 * self.cell
        return ((foot[:, 0].any() and x0 > ox0 + tol) or (foot[:, -1].any() and x1 < ox1 - tol)
                or (foot[0].any() and y0 > oy0 + tol) or (foot[-1].any() and y1 < oy1 - tol))


def _offset_lines(grid: _Grid, level, paths, tol=0.01):
    """Classifica cada trecho do off-set como corte (crista), aterro (pé) ou fora do MDT."""
    out = []
    for path in paths:
        xy = np.asarray(path, float)
        if len(xy) < 2:
            continue
        T = grid.tin.z_at(xy)
        eps = 1e-7 * max(1.0, abs(level))   # terreno na cota do platô conta como corte (altura 0)
        kind = np.where(~np.isfinite(T), "Fora do MDT", np.where(T >= level - eps, "Corte", "Aterro"))
        xyz = np.column_stack([xy, np.where(np.isfinite(T), T, level)])
        runs, start = [], 0
        for i in range(1, len(xy)):
            if kind[i] != kind[start]:
                runs.append(OffsetLine(str(kind[start]), xyz[start:i + 1]))  # fecha no vértice i
                start = i
        if start < len(xy) - 1:
            runs.append(OffsetLine(str(kind[start]), xyz[start:]))
        closed = np.array_equal(xy[0], xy[-1])
        if closed and len(runs) > 1 and runs[0].kind == runs[-1].kind:
            runs[0] = OffsetLine(runs[0].kind, np.vstack([runs[-1].xyz, runs[0].xyz[1:]]))
            runs.pop()
        out += [OffsetLine(r.kind, simplify(r.xyz, tol)) for r in runs]
    return out


def _bench_masks(grid, level):
    """Células onde há talude de corte / de aterro (fora do platô), com um canto ao menos."""
    with np.errstate(invalid="ignore"):
        cut = (grid.a > level) & ~grid.inside
        fill = (grid.b < level) & ~grid.inside
    def cells(m):
        return m[:-1, :-1] | m[:-1, 1:] | m[1:, :-1] | m[1:, 1:]
    return cells(cut), cells(fill)


def _bench_lines(grid, level, s_cut, s_fill, tol=0.01):
    """Bordas das bermas (externa e interna) onde o talude existe, como linhas 3D na cota da berma."""
    out = []
    masks = _bench_masks(grid, level)
    spans = (grid.tmax - level, level - grid.tmin)       # maior altura possível de cada talude
    for slope, mask, sign, kind, span in ((s_cut, masks[0], 1, "Berma de corte", spans[0]),
                                          (s_fill, masks[1], -1, "Berma de aterro", spans[1])):
        if not mask.any():
            continue
        for k, h, d_out, d_in in slope.bench_distances(span):
            z = level + sign * h
            for _, path in grid.lattice_contours(grid.d, [d_out, d_in], mask):
                xy = np.asarray(path, float)
                closed = len(xy) > 2 and np.array_equal(xy[0], xy[-1])
                # onde a berma mal chega a existir (terreno quase na cota dela) a borda vira
                # pedacinhos: trechos abertos menores que 3 células ou que o dobro da largura
                # da berma não servem para locação e são descartados
                min_len = max(3 * grid.cell, 2 * slope.w)
                if len(xy) >= 2 and (closed or np.hypot(*np.diff(xy, axis=0).T).sum() >= min_len):
                    out.append(OffsetLine(kind, simplify(np.column_stack([xy, np.full(len(xy), z)]), tol)))
    return out


def _bench_count(grid, level, s_cut, s_fill):
    """Quantas bermas cada lado usa (pela maior altura de corte e de aterro)."""
    cut_d, fill_d = grid.depths(level)
    out = {}
    for slope, depth, kind in ((s_cut, cut_d, "Corte"), (s_fill, fill_d, "Aterro")):
        if not slope.benched:
            continue
        with np.errstate(invalid="ignore"):
            hmax = float(np.nanmax(np.where(grid.inside, 0.0, slope.rise(np.where(depth > 0, grid.d, 0.0)))))
        n = int(math.floor(hmax / slope.h + 1e-9)) if hmax > 0 else 0
        if n:
            out[kind] = n
    return out


def simplify(xyz, tol):
    """Douglas-Peucker em planta (mantém o primeiro e o último vértice)."""
    xyz = np.asarray(xyz, float)
    n = len(xyz)
    if n < 3 or tol <= 0:
        return xyz
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = xyz[i, :2], xyz[j, :2]
        seg = b - a
        L = float(np.hypot(*seg))
        pts = xyz[i + 1:j, :2] - a
        if L == 0:
            dist = np.hypot(pts[:, 0], pts[:, 1])
        else:
            dist = np.abs(seg[0] * pts[:, 1] - seg[1] * pts[:, 0]) / L
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return xyz[keep]


def _complete(grid: _Grid, foot):
    """False se o platô ou a área terraplenada encostam onde não há MDT."""
    nan = ~np.isfinite(grid.T)
    if (nan & grid.inside).any():
        return False
    near = np.zeros_like(nan)
    near[1:, :] |= nan[:-1, :]
    near[:-1, :] |= nan[1:, :]
    near[:, 1:] |= nan[:, :-1]
    near[:, :-1] |= nan[:, 1:]
    if (foot & near).any():
        return False
    return not (foot[0].any() or foot[-1].any() or foot[:, 0].any() or foot[:, -1].any())


def _bisect(fn, lo, hi, tol=1e-6, it=100):
    """Raiz de fn decrescente em [lo, hi] (fn(lo) >= 0 >= fn(hi))."""
    for _ in range(it):
        if hi - lo <= tol:
            break
        mid = 0.5 * (lo + hi)
        if fn(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _balance_fn(grid, factor):
    def g(h):
        cut, fill = grid.totals(h)
        return cut - factor * fill
    return g


def platform_earthwork(tin: Tin, region: Region, m_cut=1.0, m_fill=1.5, level=None,
                       factor=1.0, cell=0.0, contour_interval=0.0, master_every=5,
                       bench_h=0.0, bench_w=0.0):
    """Terraplenagem de um platô horizontal com taludes.

    tin: terreno natural; region: polígono(s) do platô (todos na mesma cota).
    m_cut, m_fill: taludes de corte e de aterro em H:V (ex.: 1,0 e 1,5). 0 = vertical.
    level: cota do platô; None = cota de equilíbrio (corte = aterro x `factor`).
    factor: fator de homogeneização (volume de corte necessário por volume de aterro).
    cell: tamanho da célula do cálculo (0 = automático).
    contour_interval: > 0 gera as curvas de nível do terreno final dentro da terraplenagem.
    bench_h, bench_w: bermas a cada bench_h metros de desnível, com bench_w de largura, nos
    taludes de corte e de aterro (0 = sem bermas). As linhas das bermas saem em `offsets`.

    Uma malha grossa sobre o alcance máximo dos taludes localiza a área terraplenada (e a
    cota de equilíbrio); a malha fina cobre só essa área.
    """
    if factor <= 0:
        raise ValueError("O fator de homogeneização deve ser maior que zero.")
    m_cut0, m_fill0 = float(m_cut), float(m_fill)
    s_cut = Slope(m_cut, bench_h, bench_w)
    s_fill = Slope(m_fill, bench_h, bench_w)
    m_cut, m_fill = s_cut, s_fill        # a malha e o domínio usam os taludes (com bermas)
    balanced = level is None
    z = tin.points[:, 2]
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
    h_lo, h_hi = (zmin, zmax) if balanced else (float(level), float(level))
    outer = _domain(tin, region, m_cut, m_fill, h_lo, h_hi)
    coarse = _Grid(tin, region, m_cut, m_fill, outer, target=COARSE_CELLS, min_across=0)
    if balanced:
        h1 = _bisect(_balance_fn(coarse, factor), coarse.tmin, coarse.tmax)
        delta = max(0.01 * (zmax - zmin), 0.1)
    else:
        h1, delta = float(level), 0.0

    for attempt in range(4):
        lo, hi = h1 - delta, h1 + delta
        grid = _Grid(tin, region, m_cut, m_fill, coarse.footprint_box(lo, hi), cell)
        if balanced:
            g = _balance_fn(grid, factor)
            if not (g(lo) >= 0 >= g(hi)):   # estimativa grossa longe demais: amplia
                delta *= 4
                continue
            level = _bisect(g, lo, hi)
        foot = grid.psi(level) > 0
        if not grid.touches_inner_border(foot, coarse.box):
            break
        # a malha fina cortou a área terraplenada: usa o domínio inteiro
        grid = _Grid(tin, region, m_cut, m_fill, outer, cell)
        if balanced:
            level = _bisect(_balance_fn(grid, factor), grid.tmin, grid.tmax)
        break
    else:  # não achou o intervalo: busca na malha do domínio inteiro
        grid = _Grid(tin, region, m_cut, m_fill, outer, cell)
        level = _bisect(_balance_fn(grid, factor), grid.tmin, grid.tmax)

    cut, fill = grid.totals(level)
    cut_d, fill_d = grid.depths(level)
    a = grid.cell ** 2
    cut_area, fill_area = float((cut_d > 0).sum()) * a, float((fill_d > 0).sum()) * a
    if m_cut0 == 0 or m_fill0 == 0:
        # Muro (talude 0): o volume salta na borda do platô e a malha não seria exata ali.
        # Nesse lado nada sai do platô, então vale o cálculo exato por triângulo do TIN.
        from .volumes import volume_vs_datum
        exact = volume_vs_datum(tin, level, region)
        if m_cut0 == 0:
            cut, cut_area = exact.cut, exact.cut_area
        if m_fill0 == 0:
            fill, fill_area = exact.fill, exact.fill_area
    psi = grid.psi(level)
    foot = psi > 0
    complete = _complete(grid, foot)
    paths = [p for _, p in grid.lattice_contours(psi, [0.0])]
    footprint = _closed_rings_area(paths) if complete else None
    if footprint is None:
        footprint = float(foot.sum()) * a

    contours = []
    if contour_interval and contour_interval > 0:
        fin = grid.final(level)
        # células com ao menos um canto na área terraplenada: perto do off-set a curva do
        # terreno final segue a do terreno natural (são a mesma), então pode passar até uma
        # célula além dele sem ser cortada em pedaços ao longo da borda
        node_in = psi >= 0
        cells = node_in[:-1, :-1] | node_in[:-1, 1:] | node_in[1:, :-1] | node_in[1:, 1:]
        vals = fin[foot & np.isfinite(fin)]
        if len(vals):
            flat = [level] + [level + sg * h for sl, sg, sp in ((s_cut, 1, grid.tmax - level),
                                                                  (s_fill, -1, level - grid.tmin))
                              for _, h, _, _ in sl.bench_distances(sp)]
            levels = [lv for lv in make_levels(float(vals.min()), float(vals.max()), contour_interval)
                      if min(abs(lv - f) for f in flat) >= 1e-6]   # platô e bermas (planos) não têm curva
            min_len = 3 * grid.cell                 # restos menores que 3 células são ruído da malha
            for lv, p in grid.lattice_contours(fin, levels, cells):
                a = np.asarray(p)
                closed = len(a) > 2 and np.array_equal(a[0], a[-1])
                if len(a) >= 2 and (closed or np.hypot(*np.diff(a, axis=0).T).sum() >= min_len):
                    contours.append((lv, is_master(lv, contour_interval, master_every), p))

    return PlatformResult(
        level=float(level), cut=cut, fill=fill, cut_area=cut_area, fill_area=fill_area,
        platform_area=_region_area(region), footprint_area=float(footprint),
        complete=complete, cell=grid.cell, factor=factor, balanced=balanced,
        offsets=_offset_lines(grid, level, paths) + _bench_lines(grid, level, s_cut, s_fill),
        contours=contours, benches=_bench_count(grid, level, s_cut, s_fill))
