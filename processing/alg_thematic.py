import re

import numpy as np
from qgis.core import (
    QgsField, QgsFields, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingOutputNumber, QgsProcessingParameterBoolean, QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
    QgsProcessingParameterNumber, QgsProcessingParameterString,
)

from ..adapters.qgis_adapters import multipolygon_feature, points_from_source, polygon_feature
from ..core.contours import make_levels
from ..core.report_html import fmt
from ..core.surface import build_tin
from .tin_options import TinOptionsMixin, check_canceled
from ..core.thematic import (
    SLOPE_EDGES, SLOPE_LABELS, band_polygons, class_labels, tolerance_edges, triangle_stats,
)
from ..core.dissolve import dissolved_bands, dissolved_classes, polygons_area
from ..core.volumes import difference_surface, volume_between, volume_vs_datum
from ..compat import (
    FAST_INSERT, FIELD_NUMERIC, NUM_DOUBLE, SOURCE_POINT, SOURCE_POLYGON, TYPE_DOUBLE, TYPE_INT,
    TYPE_STRING, WKB_MULTIPOLYGON, WKB_POLYGON,
)
from ..core.geom import signed_area


def parse_edges(text, default=None):
    """'3; 8; 20' -> [3.0, 8.0, 20.0] (aceita vírgula decimal)."""
    parts = [p for p in re.split(r"[;\s]+", (text or "").strip()) if p]
    if not parts:
        if default is None:
            raise QgsProcessingException("Informe os limites das classes.")
        return list(default)
    try:
        return sorted({float(p.replace(",", ".")) for p in parts})
    except ValueError:
        raise QgsProcessingException(f"Limites inválidos: {text!r} (use números separados por ';').")


def _fields(*specs):
    f = QgsFields()
    for name, typ in specs:
        f.append(QgsField(name, typ))
    return f


class _ThematicBase(TinOptionsMixin, QgsProcessingAlgorithm):
    INPUT, Z_FIELD, MAX_EDGE, OUTPUT = "INPUT", "Z_FIELD", "MAX_EDGE", "OUTPUT"
    DISSOLVE = "DISSOLVE"

    def group(self):
        return "Mapas temáticos"

    def groupId(self):
        return "thematic"

    def createInstance(self):
        return type(self)()

    def _add_input(self, label="Pontos cotados"):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, label, [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD, "Campo da cota (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT,
            type=FIELD_NUMERIC, optional=True))

    def _add_max_edge(self):
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima do TIN (0 = desligado)",
            NUM_DOUBLE, defaultValue=0.0, minValue=0.0))

    def _add_dissolve(self, label="Juntar os polígonos de cada classe (recomendado: bem mais rápido)"):
        self.addParameter(QgsProcessingParameterBoolean(self.DISSOLVE, label, defaultValue=True))

    def _dissolve(self, parameters, context):
        return self.parameterAsBool(parameters, self.DISSOLVE, context)

    def _tin(self, parameters, context, feedback, key, zkey, label="Superfície", options=True, suffix=""):
        src = self.parameterAsSource(parameters, key, context)
        if src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, key))
        if src.sourceCrs().isGeographic():
            feedback.pushWarning("CRS geográfico (graus): use um CRS projetado (UTM).")
        zf = self.parameterAsString(parameters, zkey, context) or None
        max_edge = self.parameterAsDouble(parameters, self.MAX_EDGE, context)
        if options:  # linhas de quebra e limite (sufixo "_B" para a segunda superfície)
            return src, self._make_tin(parameters, context, feedback, src, zf, max_edge,
                                       warn_geographic=False, suffix=suffix)
        xyz = points_from_source(src, zf, feedback)
        try:
            tin = build_tin(xyz, max_edge=max_edge)
        except ValueError as exc:
            raise QgsProcessingException(f"{label}: {exc}")
        return src, tin

    def _sink(self, parameters, context, fields, crs, multi=False):
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          WKB_MULTIPOLYGON if multi else WKB_POLYGON, crs)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))
        return sink, dest


class SlopeMapAlgorithm(_ThematicBase):
    CLASSES = "CLASSES"

    def name(self):
        return "slope_map"

    def displayName(self):
        return "Mapa de declividade"

    def shortHelpString(self):
        return ("Classifica cada triângulo do TIN pela declividade (em %). Gera polígonos com "
                "declividade em % e graus, orientação da vertente, classe e áreas em planta e "
                "de superfície. Padrão: classes de relevo da EMBRAPA (3, 8, 20, 45 e 75 %); "
                "informe outros limites separados por ';' se precisar. Por padrão os triângulos de "
                "cada classe são juntados num polígono só (com a declividade média); desmarque "
                "para ter um polígono por triângulo, com declividade e orientação de cada um.")

    def initAlgorithm(self, config=None):
        self._add_input()
        self.addParameter(QgsProcessingParameterString(
            self.CLASSES, "Limites das classes de declividade (%)",
            defaultValue="3; 8; 20; 45; 75"))
        self._add_max_edge()
        self._add_tin_options()
        self._add_dissolve()
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Declividade", SOURCE_POLYGON))

    def processAlgorithm(self, parameters, context, feedback):
        src, tin = self._tin(parameters, context, feedback, self.INPUT, self.Z_FIELD)
        edges = parse_edges(self.parameterAsString(parameters, self.CLASSES, context), SLOPE_EDGES)
        labels = SLOPE_LABELS if edges == SLOPE_EDGES else class_labels(edges, " %")
        st = triangle_stats(tin)
        cls = np.searchsorted(np.array(edges), st["slope_pct"], side="right")
        a2, a3 = np.nansum(st["area2d"]), np.nansum(st["area3d"])
        if self._dissolve(parameters, context):
            sink, dest = self._sink(parameters, context, _fields(
                ("CLASSE", TYPE_INT), ("ROTULO", TYPE_STRING), ("DECLIV_MED", TYPE_DOUBLE),
                ("AREA_PLANTA", TYPE_DOUBLE), ("AREA_SUP", TYPE_DOUBLE), ("PERC_AREA", TYPE_DOUBLE)),
                src.sourceCrs(), multi=True)
            ok = np.isfinite(st["slope_pct"])
            feedback.setProgress(50)
            polys = dissolved_classes(tin.points[:, :2], tin.triangles[ok], cls[ok])
            for k, pl in polys.items():
                m = ok & (cls == k)
                ap, asup = float(st["area2d"][m].sum()), float(st["area3d"][m].sum())
                mean = float((st["slope_pct"][m] * st["area2d"][m]).sum() / ap) if ap else 0.0
                sink.addFeature(multipolygon_feature(pl, [int(k), labels[int(k)], mean, ap, asup,
                                                          float(100.0 * ap / a2) if a2 else 0.0]), FAST_INSERT)
            self._log_classes(feedback, labels, cls, st, a2, a3)
            return {self.OUTPUT: dest}
        sink, dest = self._sink(parameters, context, _fields(
            ("DECLIV_PCT", TYPE_DOUBLE), ("DECLIV_GR", TYPE_DOUBLE),
            ("ORIENT", TYPE_DOUBLE), ("CLASSE", TYPE_INT), ("ROTULO", TYPE_STRING),
            ("AREA_PLANTA", TYPE_DOUBLE), ("AREA_SUP", TYPE_DOUBLE)), src.sourceCrs())
        P = tin.points[tin.triangles][:, :, :2]
        for i in range(len(P)):
            if i % 2000 == 0:
                if feedback.isCanceled():
                    break
                feedback.setProgress(100 * i / len(P))
            if not np.isfinite(st["slope_pct"][i]):
                continue
            asp = st["aspect"][i]
            sink.addFeature(polygon_feature(
                [tuple(p) for p in P[i]],
                [float(st["slope_pct"][i]), float(st["slope_deg"][i]),
                 None if np.isnan(asp) else float(asp), int(cls[i]), labels[int(cls[i])],
                 float(st["area2d"][i]), float(st["area3d"][i])]), FAST_INSERT)
        self._log_classes(feedback, labels, cls, st, a2, a3)
        return {self.OUTPUT: dest}

    @staticmethod
    def _log_classes(feedback, labels, cls, st, a2, a3):
        feedback.pushInfo(f"Área em planta {fmt(a2)} | área da superfície {fmt(a3)}")
        for k, lab in enumerate(labels):
            a = np.nansum(st["area2d"][cls == k])
            if a:
                feedback.pushInfo(f"{lab}: {fmt(a)} ({fmt(100 * a / a2, 1)} %)")


class ElevationBandsAlgorithm(_ThematicBase):
    INTERVAL = "INTERVAL"

    def name(self):
        return "elevation_bands"

    def displayName(self):
        return "Mapa de elevação (faixas)"

    def shortHelpString(self):
        return ("Divide o terreno em faixas de elevação com a equidistância informada. Os "
                "limites das faixas seguem exatamente as curvas de nível (recorte dos "
                "triângulos do TIN).")

    def initAlgorithm(self, config=None):
        self._add_input()
        self.addParameter(QgsProcessingParameterNumber(
            self.INTERVAL, "Altura de cada faixa", NUM_DOUBLE,
            defaultValue=5.0, minValue=0.001))
        self._add_max_edge()
        self._add_tin_options()
        self._add_dissolve()
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Faixas de elevação", SOURCE_POLYGON))

    def processAlgorithm(self, parameters, context, feedback):
        src, tin = self._tin(parameters, context, feedback, self.INPUT, self.Z_FIELD)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        zmin, zmax = float(tin.points[:, 2].min()), float(tin.points[:, 2].max())
        edges = make_levels(zmin, zmax, interval)
        if not edges:
            raise QgsProcessingException("O intervalo é maior que a variação de cota do terreno.")
        dissolve = self._dissolve(parameters, context)
        sink, dest = self._sink(parameters, context, _fields(
            ("FAIXA", TYPE_INT), ("Z_MIN", TYPE_DOUBLE), ("Z_MAX", TYPE_DOUBLE),
            ("ROTULO", TYPE_STRING), ("AREA", TYPE_DOUBLE)), src.sourceCrs(), multi=dissolve)
        if dissolve:
            feedback.setProgress(30)
            for b, pl in dissolved_bands(tin.points[:, :2], tin.points[:, 2], tin.triangles, edges).items():
                lo = edges[b - 1] if b > 0 else zmin
                hi = edges[b] if b < len(edges) else zmax
                sink.addFeature(multipolygon_feature(pl, [b, lo, hi, f"{fmt(lo, 2)} a {fmt(hi, 2)}",
                                                          polygons_area(pl)]), FAST_INSERT)
            feedback.pushInfo(f"{len(edges) + 1} faixas entre {fmt(zmin, 2)} e {fmt(zmax, 2)}.")
            return {self.OUTPUT: dest}
        P3 = tin.points[tin.triangles]
        for n, (i, b, poly) in enumerate(band_polygons(P3[:, :, :2], P3[:, :, 2], edges)):
            if n % 2000 == 0 and feedback.isCanceled():
                break
            lo = edges[b - 1] if b > 0 else zmin
            hi = edges[b] if b < len(edges) else zmax
            a = np.array(poly)
            area = abs(signed_area(a[:, 0], a[:, 1]))
            sink.addFeature(polygon_feature(poly, [b, lo, hi, f"{fmt(lo, 2)} a {fmt(hi, 2)}", area]),
                            FAST_INSERT)
        feedback.pushInfo(f"{len(edges) + 1} faixas entre {fmt(zmin, 2)} e {fmt(zmax, 2)}.")
        return {self.OUTPUT: dest}


class FloodMapAlgorithm(_ThematicBase):
    LEVEL, AREA, VOLUME = "LEVEL", "AREA", "VOLUME"

    def name(self):
        return "flood_map"

    def displayName(self):
        return "Mapa de inundação (área abaixo de uma cota)"

    def shortHelpString(self):
        return ("Mostra as áreas do terreno abaixo de uma cota (nível d'água) e calcula a área e o "
                "volume de água correspondentes. Considera toda a área abaixo da cota, sem "
                "verificar conexão com o curso d'água: NÃO substitui modelagem hidráulica.")

    def initAlgorithm(self, config=None):
        self._add_input()
        self.addParameter(QgsProcessingParameterNumber(
            self.LEVEL, "Cota do nível d'água", NUM_DOUBLE,
            defaultValue=0.0))
        self._add_max_edge()
        self._add_tin_options()
        self._add_dissolve()
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Área inundada", SOURCE_POLYGON))
        self.addOutput(QgsProcessingOutputNumber(self.AREA, "Área inundada"))
        self.addOutput(QgsProcessingOutputNumber(self.VOLUME, "Volume d'água"))

    def processAlgorithm(self, parameters, context, feedback):
        src, tin = self._tin(parameters, context, feedback, self.INPUT, self.Z_FIELD)
        level = self.parameterAsDouble(parameters, self.LEVEL, context)
        res = volume_vs_datum(tin, level)
        dissolve = self._dissolve(parameters, context)
        sink, dest = self._sink(parameters, context, _fields(
            ("COTA_NIVEL", TYPE_DOUBLE), ("AREA", TYPE_DOUBLE)), src.sourceCrs(), multi=dissolve)
        if dissolve:
            pl = dissolved_bands(tin.points[:, :2], tin.points[:, 2] - level, tin.triangles, [0.0]).get(0)
            if pl:
                sink.addFeature(multipolygon_feature(pl, [level, polygons_area(pl)]), FAST_INSERT)
        else:
            P3 = tin.points[tin.triangles]
            for i, b, poly in band_polygons(P3[:, :, :2], P3[:, :, 2] - level, [0.0]):
                if b == 0:
                    a = np.array(poly)
                    area = abs(signed_area(a[:, 0], a[:, 1]))
                    sink.addFeature(polygon_feature(poly, [level, area]), FAST_INSERT)
        feedback.pushInfo(f"Área abaixo de {fmt(level, 2)}: {fmt(res.fill_area)} | volume: {fmt(res.fill)}")
        return {self.OUTPUT: dest, self.AREA: res.fill_area, self.VOLUME: res.fill}


class CutFillMapAlgorithm(_ThematicBase):
    INPUT_B, Z_FIELD_B, CLASSES = "INPUT_B", "Z_FIELD_B", "CLASSES"
    TOLERANCE, STILL_AREA = "TOLERANCE", "STILL_AREA"

    def name(self):
        return "cut_fill_map"

    def displayName(self):
        return "Mancha de corte e aterro"

    def shortHelpString(self):
        return ("Mapeia onde a superfície original (A) está acima (corte) ou abaixo (aterro) da "
                "final (B), em classes de altura. Gera polígonos com tipo, faixa de altura e "
                "área. Diferenças menores que a tolerância (padrão 5 cm) são tratadas como \"sem "
                "alteração\" e ficam fora do mapa: dois levantamentos do mesmo terreno nunca dão "
                "cotas idênticas. Com os polígonos juntados, cada classe traz também o volume. Mesmas premissas do volume entre "
                "superfícies (TIN composto, com as linhas de quebra e limites de A e de B).")

    def initAlgorithm(self, config=None):
        self._add_input("Superfície original (A)")
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_B, "Superfície final (B)", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD_B, "Campo da cota de B (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT_B,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.CLASSES, "Limites das classes de altura (m)",
            defaultValue="-2; -1; -0.5; 0; 0.5; 1; 2"))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOLERANCE, "Tolerância \"sem alteração\" (m): diferenças menores ficam fora do mapa",
            NUM_DOUBLE, defaultValue=0.05, minValue=0.0))
        self._add_max_edge()
        self._add_tin_options(label="de A")
        self._add_tin_options("_B", "de B")
        self._add_dissolve()
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Corte e aterro", SOURCE_POLYGON))
        self.addOutput(QgsProcessingOutputNumber(self.STILL_AREA, "Área sem alteração"))

    def processAlgorithm(self, parameters, context, feedback):
        src_a, tin_a = self._tin(parameters, context, feedback, self.INPUT, self.Z_FIELD, "Superfície A")
        src_b, tin_b = self._tin(parameters, context, feedback, self.INPUT_B, self.Z_FIELD_B, "Superfície B",
                                 suffix="_B")
        if src_a.sourceCrs() != src_b.sourceCrs():
            raise QgsProcessingException("As camadas A e B estão em CRS diferentes.")
        tol = self.parameterAsDouble(parameters, self.TOLERANCE, context)
        edges, still = tolerance_edges(parse_edges(self.parameterAsString(parameters, self.CLASSES, context)), tol)
        labels = class_labels(edges, " m")
        try:
            check_canceled(feedback)
            pts, tri = difference_surface(tin_a, tin_b)
            check_canceled(feedback)
            res = volume_between(tin_a, tin_b)
            check_canceled(feedback)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))
        dissolve = self._dissolve(parameters, context)
        fields = [("TIPO", TYPE_STRING), ("CLASSE", TYPE_INT), ("ALT_MIN", TYPE_DOUBLE),
                  ("ALT_MAX", TYPE_DOUBLE), ("ROTULO", TYPE_STRING), ("AREA", TYPE_DOUBLE)]
        if dissolve:
            fields.append(("VOLUME", TYPE_DOUBLE))
        sink, dest = self._sink(parameters, context, _fields(*fields), src_a.sourceCrs(), multi=dissolve)

        def attrs(b, area):
            lo = edges[b - 1] if b > 0 else None
            hi = edges[b] if b < len(edges) else None
            tipo = "Corte" if b > still else "Aterro"
            return [tipo, b, lo, hi, labels[b], area]

        still_area = 0.0
        if dissolve:
            feedback.setProgress(60)
            polys, vol = dissolved_bands(pts[:, :2], pts[:, 2], tri, edges, integrate=True)
            for b, pl in polys.items():
                area = polygons_area(pl)
                if b == still:
                    still_area = area
                    continue
                sink.addFeature(multipolygon_feature(pl, attrs(b, area) + [abs(vol.get(b, 0.0))]),
                                FAST_INSERT)
            cut_t = sum(v for b, v in vol.items() if b > still)
            fill_t = -sum(v for b, v in vol.items() if b < still)
        else:
            P3 = pts[tri]
            for n, (i, b, poly) in enumerate(band_polygons(P3[:, :, :2], P3[:, :, 2], edges)):
                if n % 2000 == 0 and feedback.isCanceled():
                    break
                a = np.array(poly)
                area = abs(signed_area(a[:, 0], a[:, 1]))
                if b == still:
                    still_area += area
                    continue
                sink.addFeature(polygon_feature(poly, attrs(b, area)), FAST_INSERT)
            cut_t = fill_t = None
        t = edges[still]
        feedback.pushInfo(f"Sem alteração (|A − B| < {fmt(t, 3)} m): área {fmt(still_area)}, fora do mapa.")
        feedback.pushInfo(f"Corte: {fmt(res.cut)} (área {fmt(res.cut_area)}) | "
                          f"Aterro: {fmt(res.fill)} (área {fmt(res.fill_area)})")
        if cut_t is not None:
            feedback.pushInfo(f"Só fora da tolerância: corte {fmt(cut_t)} | aterro {fmt(fill_t)}")
        return {self.OUTPUT: dest, self.STILL_AREA: still_area}
