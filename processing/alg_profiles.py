import numpy as np
from qgis.core import (
    QgsField, QgsFields, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterFeatureSink, QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField, QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
)

from ..adapters.qgis_adapters import (
    axis_from_source, line_feature, point_feature,
)
from ..core.export import write_sections_csv
from ..core.profiles import (
    Axis, cross_sections, format_station, profile_along, section_volumes,
)
from ..core.report_html import fmt
from .tin_options import TinOptionsMixin
from ..compat import (
    FAST_INSERT, FIELD_NUMERIC, NUM_DOUBLE, SOURCE_LINE, SOURCE_POINT, TYPE_DOUBLE, TYPE_INT,
    TYPE_STRING, WKB_LINESTRING, WKB_POINT,
)


class _ProfileBase(TinOptionsMixin, QgsProcessingAlgorithm):
    INPUT, Z_FIELD, AXIS, MAX_EDGE = "INPUT", "Z_FIELD", "AXIS", "MAX_EDGE"
    OUTPUT = "OUTPUT"

    def group(self):
        return "Perfis e seções"

    def groupId(self):
        return "profiles"

    def createInstance(self):
        return type(self)()

    def _add_common(self):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, "Pontos cotados", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD, "Campo da cota (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.AXIS, "Eixo (linha)", [SOURCE_LINE]))
        self._add_tin_options()

    def _load(self, parameters, context, feedback):
        src = self.parameterAsSource(parameters, self.INPUT, context)
        axis_src = self.parameterAsSource(parameters, self.AXIS, context)
        if src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        if axis_src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.AXIS))
        z_field = self.parameterAsString(parameters, self.Z_FIELD, context) or None
        max_edge = self.parameterAsDouble(parameters, self.MAX_EDGE, context)
        if src.sourceCrs().isGeographic():
            feedback.pushWarning("CRS geográfico (graus): use um CRS projetado (UTM) "
                                 "para que distâncias e estacas façam sentido.")
        tin = self._make_tin(parameters, context, feedback, src, z_field, max_edge,
                             warn_geographic=False)
        try:
            xy, n_lines = axis_from_source(axis_src, src.sourceCrs(), context.transformContext())
            axis = Axis(xy)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))
        if n_lines > 1:
            feedback.pushWarning(f"O eixo tem {n_lines} feições; só a primeira foi usada.")
        feedback.pushInfo(f"TIN com {len(tin.triangles)} triângulos; eixo com "
                          f"{fmt(axis.length, 2)} de comprimento.")
        return src, tin, axis


class ProfileAlgorithm(_ProfileBase):
    STEP = "STEP"

    def name(self):
        return "profile"

    def displayName(self):
        return "Perfil longitudinal"

    def shortHelpString(self):
        return ("Amostra o TIN ao longo de um eixo (linha) a cada N metros e nos vértices "
                "do eixo. Gera pontos com distância acumulada, estaca e cota. Pontos fora "
                "do TIN são omitidos. Use um CRS projetado.")

    def initAlgorithm(self, config=None):
        self._add_common()
        self.addParameter(QgsProcessingParameterNumber(
            self.STEP, "Passo de amostragem", NUM_DOUBLE,
            defaultValue=5.0, minValue=0.001))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima do TIN (0 = desligado)",
            NUM_DOUBLE, defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Perfil (pontos)", SOURCE_POINT))

    def processAlgorithm(self, parameters, context, feedback):
        src, tin, axis = self._load(parameters, context, feedback)
        step = self.parameterAsDouble(parameters, self.STEP, context)
        prof = profile_along(tin, axis, step)

        fields = QgsFields()
        fields.append(QgsField("DIST", TYPE_DOUBLE))
        fields.append(QgsField("ESTACA", TYPE_STRING))
        fields.append(QgsField("COTA", TYPE_DOUBLE))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          WKB_POINT, src.sourceCrs())
        n = 0
        for s, x, y, z in zip(prof.station, prof.x, prof.y, prof.z):
            if np.isfinite(z):
                sink.addFeature(point_feature(x, y, [float(s), format_station(s), float(z)]),
                                FAST_INSERT)
                n += 1
        if n < len(prof.station):
            feedback.pushWarning(f"{len(prof.station) - n} ponto(s) fora do TIN omitido(s).")
        feedback.pushInfo(f"{n} pontos no perfil.")
        return {self.OUTPUT: dest}


class CrossSectionsAlgorithm(_ProfileBase):
    INTERVAL, HALF_WIDTH, STEP, DATUM, CSV = "INTERVAL", "HALF_WIDTH", "STEP", "DATUM", "CSV"

    def name(self):
        return "cross_sections"

    def displayName(self):
        return "Seções transversais"

    def shortHelpString(self):
        return (
            "Gera seções transversais perpendiculares ao eixo a cada N metros, com "
            "largura para cada lado. Deslocamentos positivos ficam à DIREITA do eixo "
            "(sentido do estaqueamento).\n\n"
            "Com a cota de referência (greide) informada, calcula as áreas de corte e "
            "aterro de cada seção; os volumes entre seções saem pelo método da média "
            "das áreas e aparecem no log. O CSV opcional traz todos os pontos das seções."
        )

    def initAlgorithm(self, config=None):
        self._add_common()
        D = NUM_DOUBLE
        self.addParameter(QgsProcessingParameterNumber(
            self.INTERVAL, "Intervalo entre seções", D, defaultValue=20.0, minValue=0.001))
        self.addParameter(QgsProcessingParameterNumber(
            self.HALF_WIDTH, "Largura para cada lado do eixo", D, defaultValue=15.0,
            minValue=0.001))
        self.addParameter(QgsProcessingParameterNumber(
            self.STEP, "Passo de amostragem na seção", D, defaultValue=1.0, minValue=0.001))
        self.addParameter(QgsProcessingParameterNumber(
            self.DATUM, "Cota de referência / greide (opcional)", D, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima do TIN (0 = desligado)", D, defaultValue=0.0,
            minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Seções (linhas)", SOURCE_LINE))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.CSV, "Pontos das seções (CSV)", "Arquivos CSV (*.csv)",
            optional=True, createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):
        src, tin, axis = self._load(parameters, context, feedback)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        half = self.parameterAsDouble(parameters, self.HALF_WIDTH, context)
        step = self.parameterAsDouble(parameters, self.STEP, context)
        datum = (None if parameters.get(self.DATUM) in (None, "")
                 else self.parameterAsDouble(parameters, self.DATUM, context))
        try:
            secs = cross_sections(tin, axis, interval, half, step, datum)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))

        fields = QgsFields()
        fields.append(QgsField("DIST", TYPE_DOUBLE))
        fields.append(QgsField("ESTACA", TYPE_STRING))
        fields.append(QgsField("COTA_EIXO", TYPE_DOUBLE))
        fields.append(QgsField("AREA_CORTE", TYPE_DOUBLE))
        fields.append(QgsField("AREA_ATERRO", TYPE_DOUBLE))
        fields.append(QgsField("COMPLETA", TYPE_INT))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          WKB_LINESTRING, src.sourceCrs())

        def val(v):
            return float(v) if np.isfinite(v) else None

        for s in secs:
            sink.addFeature(
                line_feature([(s.x[0], s.y[0]), (s.x[-1], s.y[-1])],
                             [s.station, format_station(s.station), val(s.z_axis),
                              val(s.area_cut), val(s.area_fill), int(s.complete)]),
                FAST_INSERT)
        n_inc = sum(not s.complete for s in secs)
        feedback.pushInfo(f"{len(secs)} seções geradas.")
        if n_inc:
            feedback.pushWarning(f"{n_inc} seção(ões) parcial/totalmente fora do TIN "
                                 "(campo COMPLETA = 0); ficam fora dos volumes.")

        out = {self.OUTPUT: dest}
        if datum is not None:
            rows = section_volumes(secs)
            feedback.pushInfo("Estaca ini -> fim | corte | aterro (média das áreas)")
            for a, b, cut, fill, ok in rows:
                feedback.pushInfo(f"{format_station(a)} -> {format_station(b)} | "
                                  f"{fmt(cut)} | {fmt(fill)}" + ("" if ok else "  (incompleto)"))
            feedback.pushInfo(f"TOTAL corte {fmt(sum(r[2] for r in rows))}  "
                              f"aterro {fmt(sum(r[3] for r in rows))}")
        path = self.parameterAsFileOutput(parameters, self.CSV, context)
        if path:
            write_sections_csv(path, secs)
            out[self.CSV] = path
        return out
