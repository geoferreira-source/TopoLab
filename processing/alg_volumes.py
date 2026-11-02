from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
    QgsProcessingParameterFileDestination, QgsProcessingParameterNumber,
)

from ..adapters.qgis_adapters import region_from_source
from ..core.report_html import fmt, volume_report_html
from .tin_options import TinOptionsMixin
from ..core.volumes import volume_between, volume_vs_datum
from ..compat import FIELD_NUMERIC, NUM_DOUBLE, SOURCE_POINT, SOURCE_POLYGON


def _write_report(path, title, params, result):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(volume_report_html(title, params, result))


def _log_result(feedback, result):
    feedback.pushInfo(f"Corte:  {fmt(result.cut)}  (área {fmt(result.cut_area)})")
    feedback.pushInfo(f"Aterro: {fmt(result.fill)}  (área {fmt(result.fill_area)})")
    feedback.pushInfo(f"Saldo (corte - aterro): {fmt(result.net)}")


class _VolumeBase(QgsProcessingAlgorithm):
    CUT, FILL, NET = "CUT", "FILL", "NET"
    REPORT = "REPORT"
    REGION = "REGION"

    def group(self):
        return "Volumes"

    def groupId(self):
        return "volumes"

    def createInstance(self):
        return type(self)()

    def _add_region_param(self):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.REGION, "Limitar a polígono(s) (opcional)",
            [SOURCE_POLYGON], optional=True))

    def _region(self, parameters, context, target_crs, feedback):
        """(Region ou None, texto para o relatório)."""
        src = self.parameterAsSource(parameters, self.REGION, context)
        if src is None:
            return None, "nenhum (toda a superfície)"
        region, n = region_from_source(src, target_crs, context.transformContext())
        feedback.pushInfo(f"Recorte: {n} feição(ões) de '{src.sourceName()}'.")
        return region, f"{src.sourceName()} ({n} feição(ões))"

    def _add_outputs(self):
        self.addParameter(QgsProcessingParameterFileDestination(
            self.REPORT, "Relatório HTML", "Arquivos HTML (*.html)",
            optional=True, createByDefault=False))
        self.addOutput(QgsProcessingOutputNumber(self.CUT, "Volume de corte"))
        self.addOutput(QgsProcessingOutputNumber(self.FILL, "Volume de aterro"))
        self.addOutput(QgsProcessingOutputNumber(self.NET, "Saldo (corte - aterro)"))

    def _results(self, parameters, context, title, params, result):
        out = {self.CUT: result.cut, self.FILL: result.fill, self.NET: result.net}
        path = self.parameterAsFileOutput(parameters, self.REPORT, context)
        if path:
            _write_report(path, title, params, result)
            out[self.REPORT] = path
        return out


class VolumeDatumAlgorithm(TinOptionsMixin, _VolumeBase):
    INPUT, Z_FIELD, DATUM, MAX_EDGE = "INPUT", "Z_FIELD", "DATUM", "MAX_EDGE"

    def name(self):
        return "volume_datum"

    def displayName(self):
        return "Volume contra cota de referência"

    def shortHelpString(self):
        return (
            "Calcula corte (terreno acima da cota) e aterro (abaixo) de um TIN "
            "contra um plano horizontal de referência. Resultado exato por triângulo.\n\n"
            "Considera todo o TIN, ou apenas a parte dentro do(s) polígono(s) de "
            "recorte (exato por triângulo; furos são respeitados). Use a 'aresta "
            "máxima' para excluir triângulos falsos nas bordas e sobre vazios."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, "Pontos cotados", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD, "Campo da cota (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.DATUM, "Cota de referência", NUM_DOUBLE,
            defaultValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima do TIN (0 = desligado)",
            NUM_DOUBLE, defaultValue=0.0, minValue=0.0))
        self._add_region_param()
        self._add_tin_options()
        self._add_outputs()

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        z_field = self.parameterAsString(parameters, self.Z_FIELD, context) or None
        datum = self.parameterAsDouble(parameters, self.DATUM, context)
        max_edge = self.parameterAsDouble(parameters, self.MAX_EDGE, context)

        tin = self._make_tin(parameters, context, feedback, source, z_field, max_edge)
        region, region_txt = self._region(parameters, context, source.sourceCrs(), feedback)
        result = volume_vs_datum(tin, datum, region)
        _log_result(feedback, result)
        params = [("Camada", source.sourceName()), ("Campo da cota", z_field or "Z da geometria"),
                  ("Cota de referência", fmt(datum)),
                  ("Aresta máxima", fmt(max_edge) if max_edge else "desligada"),
                  ("Triângulos", len(tin.triangles)), ("Recorte", region_txt)]
        return self._results(parameters, context, "Volume contra cota de referência",
                             params, result)


class VolumeBetweenAlgorithm(TinOptionsMixin, _VolumeBase):
    INPUT_A, Z_FIELD_A = "INPUT_A", "Z_FIELD_A"
    INPUT_B, Z_FIELD_B = "INPUT_B", "Z_FIELD_B"
    MAX_EDGE = "MAX_EDGE"

    def name(self):
        return "volume_between"

    def displayName(self):
        return "Volume entre duas superfícies"

    def shortHelpString(self):
        return (
            "Calcula corte e aterro entre a superfície ORIGINAL (A) e a FINAL (B): "
            "corte onde A está acima de B, aterro onde A está abaixo.\n\n"
            "Usa um TIN composto sobre os vértices das duas superfícies e considera "
            "apenas a região em que ambas existem (e, se informado, dentro do polígono "
            "de recorte). As duas camadas de pontos devem estar no mesmo CRS.\n\n"
            "Linhas de quebra e limite do MDT (avançado) podem ser dados para A e para B; "
            "eles viram arestas também do TIN composto, para que a diferença não atravesse "
            "taludes, cristas e valas de nenhuma das duas superfícies."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_A, "Superfície original (A)", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD_A, "Campo da cota de A (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT_A,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_B, "Superfície final (B)", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD_B, "Campo da cota de B (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT_B,
            type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima dos TINs (0 = desligado)",
            NUM_DOUBLE, defaultValue=0.0, minValue=0.0))
        self._add_region_param()
        self._add_tin_options(label="de A")
        self._add_tin_options("_B", "de B")
        self._add_outputs()

    def processAlgorithm(self, parameters, context, feedback):
        a = self.parameterAsSource(parameters, self.INPUT_A, context)
        b = self.parameterAsSource(parameters, self.INPUT_B, context)
        if a is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT_A))
        if b is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT_B))
        if a.sourceCrs() != b.sourceCrs():
            raise QgsProcessingException(
                "As camadas A e B estão em CRS diferentes. Reprojete uma delas.")
        za = self.parameterAsString(parameters, self.Z_FIELD_A, context) or None
        zb = self.parameterAsString(parameters, self.Z_FIELD_B, context) or None
        max_edge = self.parameterAsDouble(parameters, self.MAX_EDGE, context)

        if a.sourceCrs().isGeographic():
            feedback.pushWarning("CRS geográfico (graus): use um CRS projetado (UTM) "
                                 "para obter volumes em m³.")
        feedback.pushInfo("Superfície A:")
        tin_a = self._make_tin(parameters, context, feedback, a, za, max_edge, warn_geographic=False)
        feedback.pushInfo("Superfície B:")
        tin_b = self._make_tin(parameters, context, feedback, b, zb, max_edge, warn_geographic=False,
                               suffix="_B")
        region, region_txt = self._region(parameters, context, a.sourceCrs(), feedback)
        try:
            result = volume_between(tin_a, tin_b, region)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))
        _log_result(feedback, result)
        params = [("Superfície A (original)", a.sourceName()),
                  ("Campo da cota de A", za or "Z da geometria"),
                  ("Superfície B (final)", b.sourceName()),
                  ("Campo da cota de B", zb or "Z da geometria"),
                  ("Aresta máxima", fmt(max_edge) if max_edge else "desligada"),
                  ("Linhas de quebra / limite", self._lines_txt(tin_a, tin_b)),
                  ("Recorte", region_txt)]
        return self._results(parameters, context, "Volume entre duas superfícies",
                             params, result)
