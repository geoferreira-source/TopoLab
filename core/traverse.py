"""Poligonais topográficas: fechamento angular e linear, ajuste, coordenadas e área.

Convenções
- Azimutes a partir do Norte, sentido horário. X = Leste, Y = Norte.
- Ângulo medido na estação i entre a ré (i-1) e a vante (i+1):
  'direita' = no sentido horário a partir da ré; 'esquerda' = anti-horário.
  Azimute da vante = azimute anterior + 180° + (±ângulo)  (+ direita, - esquerda).
- Modos: 'fechada' (volta ao ponto inicial; azimute da 1ª linha conhecido),
  'enquadrada' (parte e chega em pontos de coordenadas e azimutes conhecidos) e
  'aberta' (sem verificação de fechamento).
- Nivelamento trigonométrico (opcional): com distância inclinada DI e ângulo zenital z,
  DH = DI·sen z e ΔV = DI·cos z + hi − hs (+ curvatura e refração). O erro altimétrico
  de fechamento é distribuído proporcionalmente às distâncias.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from .angles import norm360, wrap180
from .geom import signed_area

MODES = ("fechada", "enquadrada", "aberta")
EARTH_RADIUS = 6_371_000.0   # m
K_REFRACTION = 0.13          # coeficiente de refração usual
METHODS = {"bowditch": "Proporcional às distâncias (Bowditch)",
           "transito": "Proporcional às projeções (regra do trânsito)"}


@dataclass
class TraverseResult:
    mode: str
    names: list
    angle_meas: np.ndarray      # graus, como medidos
    angle_corr: float           # correção aplicada a cada ângulo (graus)
    angle_adj: np.ndarray
    azimuth: np.ndarray         # azimute de cada lado (n_lados)
    dist: np.ndarray
    dE: np.ndarray              # projeções antes do ajuste
    dN: np.ndarray
    dE_adj: np.ndarray
    dN_adj: np.ndarray
    x: np.ndarray               # coordenadas ajustadas das estações
    y: np.ndarray
    ang_error_sec: float = 0.0  # erro angular de fechamento (s); + = excesso
    ang_tol_sec: float = float("nan")
    err_E: float = 0.0
    err_N: float = 0.0
    lin_error: float = 0.0
    perimeter: float = 0.0
    rel_precision: float = float("inf")  # 1 : N
    min_precision: float = float("nan")
    area: float = float("nan")
    method: str = "bowditch"
    checks: dict = field(default_factory=dict)
    # nivelamento trigonométrico (None quando as distâncias já são horizontais)
    dv: np.ndarray = None       # desnível de cada lado, como medido (m)
    dv_adj: np.ndarray = None   # desnível ajustado
    z: np.ndarray = None        # cotas ajustadas das estações
    v_error: float = float("nan")   # erro altimétrico de fechamento (m); + = sobra
    v_tol: float = float("nan")     # tolerância altimétrica (m)
    curvature: bool = False

    @property
    def vertical_ok(self):
        return bool(np.isnan(self.v_tol) or abs(self.v_error) <= self.v_tol)

    @property
    def angular_ok(self):
        return bool(np.isnan(self.ang_tol_sec) or abs(self.ang_error_sec) <= self.ang_tol_sec)

    @property
    def linear_ok(self):
        return bool(np.isnan(self.min_precision) or self.rel_precision >= self.min_precision)


def reduce_observations(slope, zenith_deg, hi=None, hs=None, curvature=True, k=K_REFRACTION):
    """Distâncias horizontais e desníveis a partir de distância inclinada e ângulo zenital.

    slope: distâncias inclinadas (m); zenith_deg: ângulos zenitais (graus, 0 = zênite);
    hi: altura do instrumento na estação; hs: altura do sinal (prisma) visado.
    curvature: soma (1 - k)·DH²/(2R), a correção conjunta de curvatura e refração.
    Retorna (DH, ΔV) como arrays.
    """
    slope = np.asarray(slope, float)
    z = np.radians(np.asarray(zenith_deg, float))
    if (slope <= 0).any() or not np.isfinite(slope).all():
        raise ValueError("As distâncias inclinadas devem ser números positivos.")
    if ((z <= 0) | (z >= math.pi)).any():
        raise ValueError("Ângulo zenital fora de 0° a 180° (o zênite é 0°; horizontal = 90°).")
    n = len(slope)
    hi = np.zeros(n) if hi is None else np.asarray(hi, float)
    hs = np.zeros(n) if hs is None else np.asarray(hs, float)
    dh = slope * np.sin(z)
    dv = slope * np.cos(z) + hi - hs
    if curvature:
        dv = dv + (1.0 - k) * dh ** 2 / (2.0 * EARTH_RADIUS)
    return dh, dv


def _level(res, dv, z0, z_end, tol_mm_per_sqrt_km, curvature):
    """Fechamento e ajuste altimétrico (proporcional às distâncias) dentro do resultado."""
    dv = np.asarray(dv, float)
    if len(dv) != len(res.dist):
        raise ValueError("Número de desníveis diferente do número de lados.")
    D = float(res.dist.sum())
    if res.mode == "fechada":
        err = float(dv.sum())
    elif res.mode == "enquadrada":
        if z_end is None:
            raise ValueError("Poligonal enquadrada com cotas: informe a cota final.")
        err = float(dv.sum() - (z_end - z0))
    else:
        err = 0.0
    corr = -err * res.dist / D if res.mode != "aberta" else np.zeros(len(dv))
    dva = dv + corr
    zs = np.concatenate([[z0], z0 + np.cumsum(dva)])
    res.dv, res.dv_adj, res.curvature = dv, dva, bool(curvature)
    res.z = zs[:len(res.names)] if res.mode == "fechada" else zs
    if res.mode != "aberta":
        res.v_error = err
        if tol_mm_per_sqrt_km is not None:
            res.v_tol = float(tol_mm_per_sqrt_km) / 1000.0 * math.sqrt(D / 1000.0)
    return res


def _propagate(az_first, angles, sgn):
    """Azimutes dos lados a partir do azimute do primeiro lado e dos ângulos 1..n-1."""
    az = [az_first]
    for a in angles:
        az.append(norm360(az[-1] + 180.0 + sgn * a))
    return np.array(az)


def solve_traverse(names, angles, dists, mode, x0, y0, az0, turn="direita",
                   x_end=None, y_end=None, az_end=None, method="bowditch",
                   ang_tol_per_sqrt_n=None, min_precision=None, dv=None, z0=0.0, z_end=None,
                   v_tol_mm_per_sqrt_km=None, curvature=False):
    """Calcula a poligonal.

    angles: ângulos medidos em cada estação (graus decimais).
    dists:  distâncias horizontais de cada lado (estação i -> i+1; na fechada, o último
            lado volta à estação 1).
    az0:    fechada -> azimute da 1ª linha (1->2); enquadrada/aberta -> azimute da linha
            de ré que chega à 1ª estação.
    az_end: enquadrada -> azimute da linha que sai da última estação.
    dv:     desníveis de cada lado (ver `reduce_observations`); se informado, calcula as
            cotas a partir de z0 (enquadrada: fecha em z_end), com tolerância em mm·√km.
    """
    if mode not in MODES:
        raise ValueError(f"Modo inválido: {mode}")
    if turn not in ("direita", "esquerda"):
        raise ValueError("O sentido do ângulo deve ser 'direita' ou 'esquerda'.")
    if method not in METHODS:
        raise ValueError(f"Método de ajuste inválido: {method}")
    sgn = 1.0 if turn == "direita" else -1.0
    angles = np.asarray(angles, dtype=float)
    dists = np.asarray(dists, dtype=float)
    n = len(angles)
    names = list(names)
    if len(names) != n:
        raise ValueError("Número de nomes diferente do número de ângulos.")
    if (dists <= 0).any() or not np.isfinite(dists).all():
        raise ValueError("Todas as distâncias devem ser números positivos.")

    if mode == "fechada":
        if n < 3 or len(dists) != n:
            raise ValueError("Poligonal fechada: informe ao menos 3 estações, cada uma com "
                             "ângulo e distância até a próxima (a última volta à primeira).")
        S = angles.sum()
        theo = min(((n - 2) * 180.0, (n + 2) * 180.0), key=lambda t: abs(S - t))
        err_deg = S - theo                      # interno ou externo: o mais próximo
        corr = -err_deg / n
        adj = angles + corr
        az = _propagate(az0, adj[1:], sgn)      # n lados
        end_e = end_n = 0.0
        n_sides = n
    else:
        if n < 2 or len(dists) != n - 1:
            raise ValueError("Informe ao menos 2 estações e uma distância para cada lado "
                             "(estações - 1).")
        n_sides = n - 1
        err_deg, corr = 0.0, 0.0
        adj = angles.copy()
        if mode == "enquadrada":
            if None in (x_end, y_end, az_end):
                raise ValueError("Poligonal enquadrada: informe X, Y e azimute finais.")
            def az_out(a):
                v = norm360(az0 + 180.0 + sgn * a[0])
                for k in range(1, n):
                    v = norm360(v + 180.0 + sgn * a[k])
                return v
            err_deg = wrap180(az_out(angles) - az_end)
            corr = -sgn * err_deg / n
            adj = angles + corr
            end_e, end_n = x_end - x0, y_end - y0
        else:
            end_e = end_n = None
        first = norm360(az0 + 180.0 + sgn * adj[0])
        az = _propagate(first, adj[1:n_sides], sgn)

    rad = np.radians(az)
    dE, dN = dists * np.sin(rad), dists * np.cos(rad)
    D = dists.sum()
    if mode == "aberta":
        eE = eN = 0.0
        cE = cN = np.zeros(n_sides)
    else:
        eE, eN = dE.sum() - end_e, dN.sum() - end_n
        if method == "bowditch":
            cE, cN = -eE * dists / D, -eN * dists / D
        else:
            sE, sN = np.abs(dE).sum() or 1.0, np.abs(dN).sum() or 1.0
            cE, cN = -eE * np.abs(dE) / sE, -eN * np.abs(dN) / sN
    dEa, dNa = dE + cE, dN + cN

    x = np.concatenate([[x0], x0 + np.cumsum(dEa)])
    y = np.concatenate([[y0], y0 + np.cumsum(dNa)])
    lin = math.hypot(eE, eN)

    res = TraverseResult(
        mode=mode, names=names, angle_meas=angles, angle_corr=float(corr), angle_adj=adj,
        azimuth=az, dist=dists, dE=dE, dN=dN, dE_adj=dEa, dN_adj=dNa,
        x=x[:n] if mode == "fechada" else x, y=y[:n] if mode == "fechada" else y,
        ang_error_sec=float(err_deg * 3600.0), err_E=float(eE), err_N=float(eN),
        lin_error=lin, perimeter=float(D),
        rel_precision=(D / lin if lin > 0 else float("inf")), method=method)
    if ang_tol_per_sqrt_n is not None and mode != "aberta":
        res.ang_tol_sec = float(ang_tol_per_sqrt_n) * math.sqrt(n)
    if min_precision is not None and mode != "aberta":
        res.min_precision = float(min_precision)
    if mode == "fechada":
        xs, ys = res.x, res.y
        res.area = abs(signed_area(xs, ys))
    if dv is not None:
        _level(res, dv, float(z0), z_end, v_tol_mm_per_sqrt_km, curvature)
    return res


def traverse_rows(res: TraverseResult):
    """Linhas da planilha de resultados (uma por estação)."""
    from .angles import format_dms
    rows = []
    for i, name in enumerate(res.names):
        has_side = i < len(res.dist)
        rows.append({
            "estacao": name,
            "angulo": format_dms(res.angle_meas[i] % 360, 0),
            "angulo_ajustado": format_dms(res.angle_adj[i] % 360, 1),
            "azimute": format_dms(res.azimuth[i], 1) if has_side else "",
            "distancia": float(res.dist[i]) if has_side else None,
            "dE": float(res.dE_adj[i]) if has_side else None,
            "dN": float(res.dN_adj[i]) if has_side else None,
            "x": float(res.x[i]), "y": float(res.y[i]),
            "dv": float(res.dv_adj[i]) if res.dv_adj is not None and has_side else None,
            "z": float(res.z[i]) if res.z is not None else None,
        })
    return rows
