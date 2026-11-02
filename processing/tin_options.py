"""Opções comuns de construção do TIN: linhas de quebra e limite do MDT."""
from qgis.core import QgsProcessingParameterFeatureSource, QgsProcessingParameterField

from ..adapters.qgis_adapters import make_tin
from ..compat import FIELD_NUMERIC, FLAG_ADVANCED, SOURCE_LINE, SOURCE_POLYGON


def check_canceled(feedback):
    """Interrompe o algoritmo se o usuário pediu para cancelar (botão Cancelar do TopoLab ou do
    Processing). Os cálculos longos chamam isto entre as etapas."""
    if feedback is not None and feedback.isCanceled():
        from qgis.core import QgsProcessingException
        raise QgsProcessingException("Cancelado pelo usuário.")


class TinOptionsMixin:
    BREAKLINES, BREAK_Z, BOUNDARY = "BREAKLINES", "BREAK_Z", "BOUNDARY"

    def _add_tin_options(self, suffix="", label=""):
        """Parâmetros avançados de linhas de quebra e limite. `suffix` ("_B") e `label`
        ("de B") distinguem a segunda superfície nos algoritmos com duas."""
        of = f" {label}" if label else ""
        params = [
            QgsProcessingParameterFeatureSource(
                self.BREAKLINES + suffix, f"Linhas de quebra{of} (opcional)", [SOURCE_LINE],
                optional=True),
            QgsProcessingParameterField(
                self.BREAK_Z + suffix, f"Campo da cota das linhas de quebra{of} (vazio = Z da "
                                       "geometria ou interpolada do MDT)",
                parentLayerParameterName=self.BREAKLINES + suffix,
                type=FIELD_NUMERIC, optional=True),
            QgsProcessingParameterFeatureSource(
                self.BOUNDARY + suffix, f"Limite do MDT{of}: polígono (opcional)", [SOURCE_POLYGON],
                optional=True),
        ]
        for p in params:
            p.setFlags(p.flags() | FLAG_ADVANCED)
            self.addParameter(p)

    @staticmethod
    def _lines_txt(tin_a, tin_b):
        n = [len(t.lines or []) for t in (tin_a, tin_b)]
        return "nenhuma" if not any(n) else f"A: {n[0]} linha(s); B: {n[1]} linha(s) (inclui anéis do limite)"

    def _make_tin(self, parameters, context, feedback, src, z_field, max_edge, warn_geographic=True,
                  suffix=""):
        if warn_geographic and src.sourceCrs().isGeographic():
            feedback.pushWarning("CRS geográfico (graus): use um CRS projetado (UTM).")
        check_canceled(feedback)
        tin = make_tin(
            src, z_field, max_edge,
            self.parameterAsSource(parameters, self.BREAKLINES + suffix, context),
            self.parameterAsString(parameters, self.BREAK_Z + suffix, context) or None,
            self.parameterAsSource(parameters, self.BOUNDARY + suffix, context),
            context.transformContext(), feedback)
        check_canceled(feedback)
        return tin
