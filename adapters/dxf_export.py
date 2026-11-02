"""Exporta camadas vetoriais do QGIS para DXF (R12) usando o escritor em Python puro."""
import math

from qgis.core import QgsWkbTypes

from ..core.dxf import DxfWriter
from ..compat import GEOM_LINE, GEOM_POINT, GEOM_POLYGON, is_null


def _pick_z(vertex_z, field_z):
    if field_z is not None:
        return field_z
    return vertex_z if (vertex_z is not None and math.isfinite(vertex_z)) else None


def _num(feat, field):
    if not field:
        return None
    try:
        v = float(feat[field])
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, KeyError):
        return None


def export_layers_to_dxf(layers, path, z_field="", label_field="", text_height=1.0):
    """Cada camada vira uma camada DXF com o mesmo nome. Retorna o dicionário de contagens.

    z_field: campo numérico com a cota (ex.: ELEV nas curvas); vale para as camadas que o têm.
    label_field: campo cujo valor vira texto ao lado de cada ponto (ex.: ponto, cota).
    """
    w = DxfWriter()
    for lyr in layers:
        names = lyr.fields().names()
        zf = z_field if z_field in names else ""
        lf = label_field if label_field in names else ""
        for feat in lyr.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            fz = _num(feat, zf)
            label = "" if not lf or is_null(feat[lf]) else str(feat[lf])
            for part in geom.constParts():
                gtype = QgsWkbTypes.geometryType(part.wkbType())
                if gtype == GEOM_POINT:
                    z = _pick_z(part.z() if QgsWkbTypes.hasZ(part.wkbType()) else None, fz)
                    w.point(lyr.name(), part.x(), part.y(), z or 0.0)
                    if label:
                        off = 0.3 * text_height
                        w.text(lyr.name() + "_TXT", part.x() + off, part.y() + off, z or 0.0,
                               text_height, label)
                elif gtype == GEOM_LINE:
                    has_z = QgsWkbTypes.hasZ(part.wkbType())
                    w.polyline(lyr.name(), [(p.x(), p.y(), _pick_z(p.z() if has_z else None, fz))
                                            for p in part.points()])
                elif gtype == GEOM_POLYGON:
                    has_z = QgsWkbTypes.hasZ(part.wkbType())
                    rings = [part.exteriorRing()] + [part.interiorRing(i)
                                                     for i in range(part.numInteriorRings())]
                    for ring in rings:
                        pts = [(p.x(), p.y(), _pick_z(p.z() if has_z else None, fz))
                               for p in ring.points()]
                        if len(pts) > 1 and pts[0][:2] == pts[-1][:2]:
                            pts = pts[:-1]
                        w.polyline(lyr.name(), pts, closed=True)
    w.save(path)
    return w.counts
