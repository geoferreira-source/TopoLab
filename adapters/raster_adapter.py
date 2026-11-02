"""Leitura de bandas raster do QGIS como arrays numpy."""
import numpy as np
from qgis.core import QgsProcessingException

from ..core.raster import grid_to_points

# Códigos do tipo de dado (iguais aos do GDAL / Qgis.DataType)
_DTYPES = {1: "u1", 2: "<u2", 3: "<i2", 4: "<u4", 5: "<i4", 6: "<f4", 7: "<f8"}
MAX_POINTS = 3_000_000


def raster_points(layer, band=1, step=1):
    """Pontos (x, y, z) dos centros das células de uma banda, 1 a cada `step` células.

    O QGIS reamostra a leitura (vizinho mais próximo) para a grade reduzida, então
    rasters grandes não são carregados inteiros na memória.
    """
    prov = layer.dataProvider()
    if band < 1 or band > layer.bandCount():
        raise QgsProcessingException(f"A banda {band} não existe (o raster tem {layer.bandCount()}).")
    w, h = layer.width(), layer.height()
    nw, nh = max(w // step, 1), max(h // step, 1)
    if nw * nh > MAX_POINTS:
        raise QgsProcessingException(
            f"{nw * nh:,} pontos é demais para um TIN. Aumente o passo (tente "
            f"{int((w * h / MAX_POINTS) ** 0.5) + 1} ou mais).".replace(",", "."))
    ext = layer.extent()
    block = prov.block(band, ext, nw, nh)
    dt = block.dataType()
    code = int(getattr(dt, "value", dt))
    if code not in _DTYPES:
        raise QgsProcessingException(f"Tipo de dado do raster não suportado (código {code}).")
    arr = np.frombuffer(bytes(block.data()), dtype=_DTYPES[code]).reshape(nh, nw).astype(float)
    nodata = block.noDataValue() if block.hasNoDataValue() else None
    pts = grid_to_points(arr, ext.xMinimum(), ext.yMaximum(), ext.width() / nw,
                         ext.height() / nh, 1, nodata)
    if len(pts) < 3:
        raise QgsProcessingException("O raster não tem células válidas suficientes.")
    return pts
