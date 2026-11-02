import numpy as np
from qgis.core import (
    QgsField, QgsFields, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingOutputNumber, QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
    QgsProcessingParameterFileDestination, QgsProcessingParameterNumber,
)

from ..adapters.qgis_adapters import point_feature, points_for_qa
from ..core.quality import KINDS, check_points, quality_html
from ..compat import (
    FAST_INSERT, FIELD_ANY, FIELD_NUMERIC, NUM_DOUBLE, SOURCE_POINT, TYPE_DOUBLE, TYPE_STRING,
    WKB_POINT,
)


class CheckPointsAlgorithm(QgsProcessingAlgorithm):
    INPUT, Z_FIELD, ID_FIELD = "INPUT", "Z_FIELD", "ID_FIELD"
    NEAR, ZERO_TOL, SPIKE_N, SPIKE_MIN = "NEAR", "ZERO_TOL", "SPIKE_N", "SPIKE_MIN"
    OUTPUT, REPORT, TOTAL, FLAGGED = "OUTPUT", "REPORT", "TOTAL", "FLAGGED"

    def name(self):
        return "check_points"

    def displayName(self):
        return "Verificar qualidade dos pontos"

    def group(self):
        return "Verificação"

    def groupId(self):
        return "quality"

    def createInstance(self):
        return CheckPointsAlgorithm()

    def shortHelpString(self):
        return ("Procura problemas que distorcem o MDT e os volumes: cota zerada ou inválida, "
                "pontos repetidos (com cotas iguais ou diferentes), pontos muito próximos, "
                "picos de cota em relação aos vizinhos e identificadores repetidos. Gera uma "
                "camada só com os pontos sinalizados e o tipo de problema.\n\n"
                "A sinalização é automática e não prova erro: confira os pontos antes de corrigir.")

    def initAlgorithm(self, config=None):
        D = NUM_DOUBLE
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, "Pontos cotados", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD, "Campo da cota (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.ID_FIELD, "Campo do identificador (opcional)",
            parentLayerParameterName=self.INPUT, type=FIELD_ANY,
            optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.NEAR, "Distância mínima entre pontos distintos (0 = desligado)", D,
            defaultValue=0.05, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.ZERO_TOL, "Tolerância para cota zerada", D, defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SPIKE_N, "Sensibilidade do pico (× desvio robusto; menor = mais sensível)", D,
            defaultValue=6.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SPIKE_MIN, "Variação mínima de cota para contar como pico", D,
            defaultValue=0.02, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Pontos sinalizados", SOURCE_POINT))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.REPORT, "Relatório HTML", "Arquivos HTML (*.html)", optional=True,
            createByDefault=False))
        self.addOutput(QgsProcessingOutputNumber(self.TOTAL, "Pontos analisados"))
        self.addOutput(QgsProcessingOutputNumber(self.FLAGGED, "Pontos sinalizados"))

    def processAlgorithm(self, parameters, context, feedback):
        src = self.parameterAsSource(parameters, self.INPUT, context)
        if src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        z_field = self.parameterAsString(parameters, self.Z_FIELD, context) or None
        id_field = self.parameterAsString(parameters, self.ID_FIELD, context) or None
        xyz, names = points_for_qa(src, z_field, id_field)
        if len(xyz) == 0:
            raise QgsProcessingException("A camada não tem pontos.")
        rep = check_points(
            xyz, names if id_field else None,
            zero_tol=self.parameterAsDouble(parameters, self.ZERO_TOL, context),
            near_dist=self.parameterAsDouble(parameters, self.NEAR, context),
            spike_nmad=self.parameterAsDouble(parameters, self.SPIKE_N, context),
            spike_min_abs=self.parameterAsDouble(parameters, self.SPIKE_MIN, context))

        fields = QgsFields()
        fields.append(QgsField("ID", TYPE_STRING))
        fields.append(QgsField("COTA", TYPE_DOUBLE))
        fields.append(QgsField("PROBLEMAS", TYPE_STRING))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          WKB_POINT, src.sourceCrs())
        examples = []
        for i in rep.flagged():
            kinds = ", ".join(KINDS[k] for k in rep.kinds_of(i))
            x, y, z = xyz[i]
            label = names[i] or f"#{i + 1}"
            sink.addFeature(point_feature(x, y, [label, None if not np.isfinite(z) else float(z), kinds]),
                            FAST_INSERT)
            if len(examples) < 50:
                examples.append((label, x, y, z if np.isfinite(z) else float("nan"), kinds))
        for k, c in rep.counts().items():
            if c:
                feedback.pushInfo(f"{KINDS[k]}: {c}")
        feedback.pushInfo(f"{len(rep.flagged())} de {rep.n} pontos sinalizados.")
        out = {self.OUTPUT: dest, self.TOTAL: rep.n, self.FLAGGED: int(len(rep.flagged()))}
        path = self.parameterAsFileOutput(parameters, self.REPORT, context)
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("<html><meta charset='utf-8'><body>" + quality_html(rep, examples=examples)
                         + "</body></html>")
            out[self.REPORT] = path
        return out
