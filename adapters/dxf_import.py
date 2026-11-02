"""Camadas do QGIS a partir de um levantamento lido de DXF (ver core.dxf_read)."""
import math

import numpy as np
from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsLineString, QgsPoint, QgsPointXY, QgsVectorLayer

from ..compat import TYPE_DOUBLE, TYPE_INT, TYPE_STRING
from ..core.geom import signed_area


def _layer(geom, crs, name, fields):
    uri = f"{geom}?crs={crs.authid() or crs.toWkt()}"
    lyr = QgsVectorLayer(uri, name, "memory")
    lyr.dataProvider().addAttributes([QgsField(n, t) for n, t in fields])
    lyr.updateFields()
    return lyr


def survey_layers(sv, crs, prefix):
    """Lista de camadas (só as que têm feições): pontos cotados, pontos sem cota, linhas,
    polígonos (limite)."""
    out = []
    pf = [("ponto", TYPE_STRING), ("cota", TYPE_DOUBLE), ("desc", TYPE_STRING),
          ("camada_cad", TYPE_STRING), ("origem_cota", TYPE_STRING)]
    good = [p for p in sv.points if math.isfinite(p[3])]
    bad = [p for p in sv.points if not math.isfinite(p[3])]
    if good:
        lyr = _layer("PointZ", crs, f"{prefix} - pontos cotados", pf)
        feats = []
        for pid, x, y, z, desc, layer, src in good:
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry(QgsPoint(x, y, z)))
            f.setAttributes([pid, z, desc, layer, src])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        out.append(lyr)
    if bad:
        lyr = _layer("Point", crs, f"{prefix} - pontos sem cota", pf)
        feats = []
        for pid, x, y, _z, desc, layer, src in bad:
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            f.setAttributes([pid, None, desc, layer, "sem cota"])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        out.append(lyr)
    if sv.lines:
        lyr = _layer("LineStringZ", crs, f"{prefix} - linhas",
                     [("camada_cad", TYPE_STRING), ("fechada", TYPE_INT), ("cota", TYPE_DOUBLE)])
        feats = []
        for layer, xyz, closed in sv.lines:
            z = xyz[:, 2]
            const = float(z[0]) if np.allclose(z, z[0]) and z[0] != 0 else None
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry(QgsLineString([QgsPoint(float(a), float(b), float(c)) for a, b, c in xyz])))
            f.setAttributes([layer, int(closed), const])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        out.append(lyr)
    if sv.polygons:
        lyr = _layer("Polygon", crs, f"{prefix} - limite", [("camada_cad", TYPE_STRING), ("area", TYPE_DOUBLE)])
        feats = []
        for layer, xy in sv.polygons:
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(float(a), float(b)) for a, b in xy]]))
            f.setAttributes([layer, abs(signed_area(xy[:-1, 0], xy[:-1, 1]))])
            feats.append(f)
        lyr.dataProvider().addFeatures(feats)
        out.append(lyr)
    for lyr in out:
        lyr.updateExtents()
    return out
