"""Conversão entre camadas/feições do QGIS e as estruturas do núcleo."""
import numpy as np
from qgis.core import (
    QgsCoordinateTransform, QgsWkbTypes, QgsFeature, QgsGeometry, QgsPointXY, QgsProcessingException,
)

from ..core.region import Region
from ..core.surface import build_tin
from ..compat import GEOM_LINE, GEOM_POLYGON, is_null


def points_from_source(source, z_field=None, feedback=None):
    """Lê uma fonte de pontos e devolve array (n, 3) com x, y, z.

    z_field: nome de um campo numérico com a cota. Se None, usa o Z da geometria.
    """
    total = source.featureCount() or 1
    rows = []
    for i, feat in enumerate(source.getFeatures()):
        if feedback is not None:
            if feedback.isCanceled():
                break
            feedback.setProgress(10 * i / total)
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        zf = None
        if z_field:
            try:
                zf = float(feat[z_field])
            except (TypeError, ValueError):
                continue  # cota nula/inválida: ignora o ponto
        for v in geom.vertices():
            z = zf if z_field else v.z()
            if z != z:  # NaN -> geometria sem Z
                raise QgsProcessingException(
                    "A camada não tem Z na geometria. Escolha o campo da cota."
                )
            rows.append((v.x(), v.y(), z))
    if len(rows) < 3:
        raise QgsProcessingException("Menos de 3 pontos válidos na camada de entrada.")
    return np.array(rows, dtype=float)


def line_feature(path_xy, attributes):
    """Cria uma QgsFeature de linha a partir de [(x, y), ...]."""
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in path_xy]))
    feat.setAttributes(attributes)
    return feat


def region_from_source(source, target_crs, transform_context):
    """Lê polígonos (com furos) de uma fonte e devolve uma Region no CRS `target_crs`.

    Polígonos sobrepostos na mesma camada se anulam (regra par-ímpar): use polígonos
    disjuntos. Retorna (Region, quantidade de feições usadas).
    """
    ct = None
    if source.sourceCrs() != target_crs:
        ct = QgsCoordinateTransform(source.sourceCrs(), target_crs, transform_context)
    polys, nfeat = [], 0
    for feat in source.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        if ct is not None:
            geom = QgsGeometry(geom)
            geom.transform(ct)
        parts = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
        used = False
        for rings in parts:
            if not rings:
                continue
            conv = [[(p.x(), p.y()) for p in ring] for ring in rings]
            polys.append((conv[0], conv[1:]))
            used = True
        nfeat += used
    if not polys:
        raise QgsProcessingException("A camada de recorte não contém polígonos.")
    try:
        return Region(polys), nfeat
    except ValueError as exc:
        raise QgsProcessingException(str(exc))


def axis_from_source(source, target_crs, transform_context, selected_only=False):
    """Primeira linha da fonte (ou da seleção) como [(x, y), ...] no CRS `target_crs`.

    Em camadas do projeto, `selected_only=True` usa só as feições selecionadas.
    """
    from qgis.core import QgsFeatureRequest

    if selected_only and hasattr(source, "selectedFeatureIds"):
        ids = source.selectedFeatureIds()
        if not ids:
            raise QgsProcessingException("Nenhuma feição selecionada na camada do eixo.")
        feats = list(source.getFeatures(QgsFeatureRequest().setFilterFids(ids)))
    else:
        feats = list(source.getFeatures())
    feats = [f for f in feats if f.geometry() is not None and not f.geometry().isEmpty()]
    if not feats:
        raise QgsProcessingException("A camada do eixo não tem linhas.")
    geom = QgsGeometry(feats[0].geometry())
    if source.sourceCrs() != target_crs:
        geom.transform(QgsCoordinateTransform(source.sourceCrs(), target_crs, transform_context))
    line = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
    if len(line) < 2:
        raise QgsProcessingException("O eixo precisa de ao menos 2 vértices.")
    return [(p.x(), p.y()) for p in line], len(feats)


def line_feature_z(xyz, attributes):
    """QgsFeature de linha 3D a partir de [(x, y, z), ...]."""
    from qgis.core import QgsLineString, QgsPoint
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry(QgsLineString([QgsPoint(float(x), float(y), float(z)) for x, y, z in xyz])))
    feat.setAttributes(attributes)
    return feat


def point_feature(x, y, attributes):
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    feat.setAttributes(attributes)
    return feat


def polygon_feature(poly_xy, attributes):
    """QgsFeature de polígono a partir de [(x, y), ...] (fecha o anel)."""
    ring = [QgsPointXY(x, y) for x, y in poly_xy]
    ring.append(ring[0])
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
    feat.setAttributes(attributes)
    return feat


def multipolygon_feature(polys, attributes):
    """QgsFeature multipolígono a partir de [(anel externo (n, 2), [furos]), ...]."""
    def ring(r):
        pts = [QgsPointXY(float(x), float(y)) for x, y in r]
        pts.append(pts[0])
        return pts
    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromMultiPolygonXY(
        [[ring(outer)] + [ring(h) for h in holes] for outer, holes in polys]))
    feat.setAttributes(attributes)
    return feat


def points_for_qa(source, z_field=None, id_field=None):
    """Como points_from_source, mas mantém pontos com cota inválida (para serem sinalizados).

    Retorna (xyz (n, 3) com NaN onde a cota é inválida, nomes).
    """
    rows, names = [], []
    for feat in source.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        name = ""
        if id_field:
            val = feat[id_field]
            name = "" if is_null(val) else str(val)
        for v in geom.vertices():
            if z_field:
                try:
                    z = float(feat[z_field])
                except (TypeError, ValueError):
                    z = float("nan")
            else:
                z = v.z()  # NaN quando a geometria não tem Z
            rows.append((v.x(), v.y(), z))
            names.append(name)
    return np.array(rows, dtype=float).reshape(-1, 3), names


def lines_from_source(source, z_field, target_crs, transform_context):
    """Polilinhas (k, 3) de uma fonte de linhas (ou contornos de polígonos) para linhas de quebra.

    Cota: campo `z_field` (constante na feição), senão o Z dos vértices, senão NaN (será
    interpolada do MDT).
    """
    ct = None
    if source.sourceCrs() != target_crs:
        ct = QgsCoordinateTransform(source.sourceCrs(), target_crs, transform_context)
    out = []
    for feat in source.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        if ct is not None:
            geom = QgsGeometry(geom)
            geom.transform(ct)
        fz = None
        if z_field:
            try:
                fz = float(feat[z_field])
            except (TypeError, ValueError):
                fz = None
        for part in geom.constParts():
            gtype = QgsWkbTypes.geometryType(part.wkbType())
            if gtype == GEOM_LINE:
                rings = [part.points()]
            elif gtype == GEOM_POLYGON:
                rings = [part.exteriorRing().points()] + [
                    part.interiorRing(i).points() for i in range(part.numInteriorRings())]
            else:
                continue
            for pts in rings:
                arr = np.array([(p.x(), p.y(), fz if fz is not None else p.z()) for p in pts], float)
                if len(arr) >= 2:
                    out.append(arr)
    return out


def make_tin(source, z_field, max_edge, break_source=None, break_z_field=None,
             boundary_source=None, transform_context=None, feedback=None):
    """TIN a partir de uma fonte de pontos, com linhas de quebra e limite opcionais."""
    xyz = points_from_source(source, z_field, feedback)
    lines = boundary = None
    if break_source is not None:
        lines = lines_from_source(break_source, break_z_field, source.sourceCrs(), transform_context)
        if not lines:
            raise QgsProcessingException("A camada de linhas de quebra não tem linhas.")
    if boundary_source is not None:
        boundary, _ = region_from_source(boundary_source, source.sourceCrs(), transform_context)
    if feedback is not None:
        feedback.pushInfo(f"{len(xyz)} pontos"
                          + (f", {len(lines)} linha(s) de quebra" if lines else "")
                          + (", com limite do MDT" if boundary is not None else "") + ".")
    try:
        return build_tin(xyz, max_edge=max_edge, breaklines=lines, boundary=boundary)
    except ValueError as exc:
        raise QgsProcessingException(str(exc))
