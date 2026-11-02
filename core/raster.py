"""MDE em grade (array) -> pontos cotados. Sem dependência do QGIS."""
import numpy as np


def grid_to_points(arr, x_min, y_max, xres, yres, step=1, nodata=None):
    """Centros das células de uma grade como (n, 3) x, y, z.

    arr: (linhas, colunas), linha 0 = norte. step: pega 1 célula a cada `step`.
    Células NaN/infinitas ou iguais a `nodata` são descartadas.
    """
    if step < 1:
        raise ValueError("O passo deve ser de ao menos 1 célula.")
    a = np.asarray(arr, dtype=float)
    rows, cols = np.arange(0, a.shape[0], step), np.arange(0, a.shape[1], step)
    sub = a[np.ix_(rows, cols)]
    cc, rr = np.meshgrid(cols, rows)
    x = x_min + (cc + 0.5) * xres
    y = y_max - (rr + 0.5) * yres
    ok = np.isfinite(sub)
    if nodata is not None:
        ok &= sub != nodata
    return np.column_stack([x[ok], y[ok], sub[ok]])
