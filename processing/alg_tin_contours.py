from qgis.core import (
    QgsField, QgsFields, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterFeatureSink, QgsProcessingParameterField,
    QgsProcessingParameterNumber, QgsProcessingParameterFeatureSource,
)

from ..adapters.qgis_adapters import line_feature
from ..core.contours import contour_lines, is_master, make_levels
from .tin_options import TinOptionsMixin
from ..compat import (
    FAST_INSERT, FIELD_NUMERIC, NUM_DOUBLE, NUM_INTEGER, SOURCE_LINE, SOURCE_POINT, TYPE_DOUBLE,
    TYPE_INT, WKB_LINESTRING,
)


class TinContoursAlgorithm(TinOptionsMixin, QgsProcessingAlgorithm):
    INPUT = "INPUT"
    Z_FIELD = "Z_FIELD"
    INTERVAL = "INTERVAL"
    MASTER_EVERY = "MASTER_EVERY"
    MAX_EDGE = "MAX_EDGE"
    OUTPUT = "OUTPUT"

    def name(self):
        return "tin_contours"

    def displayName(self):
        return "TIN e curvas de nível"

    def group(self):
        return "Superfície"

    def groupId(self):
        return "surface"

    def shortHelpString(self):
        return (
            "Gera um TIN (Delaunay) a partir de pontos cotados e extrai as curvas "
            "de nível com a equidistância informada.\n\n"
            "Use um CRS projetado (ex.: SIRGAS 2000 / UTM). Se a camada não tiver "
            "Z na geometria, indique o campo da cota. A 'aresta máxima' descarta "
            "triângulos longos nas bordas e sobre vazios (0 = desligado)."
        )

    def createInstance(self):
        return TinContoursAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, "Pontos cotados", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD, "Campo da cota (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.INTERVAL, "Equidistância das curvas",
            NUM_DOUBLE, defaultValue=1.0, minValue=0.001))
        self.addParameter(QgsProcessingParameterNumber(
            self.MASTER_EVERY, "Curva mestra a cada N curvas (0 = nenhuma)",
            NUM_INTEGER, defaultValue=5, minValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima do TIN, em unidades do mapa (0 = desligado)",
            NUM_DOUBLE, defaultValue=0.0, minValue=0.0))
        self._add_tin_options()
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Curvas de nível", SOURCE_LINE))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        z_field = self.parameterAsString(parameters, self.Z_FIELD, context) or None
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        master_every = self.parameterAsInt(parameters, self.MASTER_EVERY, context)
        max_edge = self.parameterAsDouble(parameters, self.MAX_EDGE, context)

        if source.sourceCrs().isGeographic():
            feedback.pushWarning(
                "A camada está em CRS geográfico (graus). Reprojete para um CRS "
                "projetado (UTM) para que a aresta máxima e as distâncias façam sentido."
            )

        feedback.pushInfo("Construindo o TIN...")
        tin = self._make_tin(parameters, context, feedback, source, z_field, max_edge,
                             warn_geographic=False)
        feedback.pushInfo(f"TIN com {len(tin.triangles)} triângulos.")
        feedback.setProgress(20)

        fields = QgsFields()
        fields.append(QgsField("ELEV", TYPE_DOUBLE))
        fields.append(QgsField("MESTRA", TYPE_INT))
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            WKB_LINESTRING, source.sourceCrs())
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        zs = tin.points[:, 2]
        levels = make_levels(float(zs.min()), float(zs.max()), interval)
        if not levels:
            feedback.pushWarning("Nenhuma curva dentro do intervalo de cotas.")
        count = 0
        for i, level in enumerate(levels):
            if feedback.isCanceled():
                break
            master = 1 if is_master(level, interval, master_every) else 0
            for path in contour_lines(tin, level):
                if len(path) >= 2:
                    sink.addFeature(line_feature(path, [float(level), master]),
                                    FAST_INSERT)
                    count += 1
            feedback.setProgress(20 + 80 * (i + 1) / len(levels))

        feedback.pushInfo(f"{count} polilinhas geradas em {len(levels)} cotas.")
        return {self.OUTPUT: dest_id}
