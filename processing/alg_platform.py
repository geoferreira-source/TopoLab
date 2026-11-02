"""Processing: platô horizontal com taludes de corte e aterro."""
from qgis.core import (
    QgsField, QgsFields, QgsProcessingException, QgsProcessingOutputNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink, QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField, QgsProcessingParameterNumber,
)

from ..adapters.qgis_adapters import line_feature, line_feature_z, region_from_source
from ..compat import (
    FAST_INSERT, FIELD_NUMERIC, FLAG_ADVANCED, NUM_DOUBLE, SOURCE_LINE, SOURCE_POINT,
    SOURCE_POLYGON, TYPE_DOUBLE, TYPE_INT, TYPE_STRING, WKB_LINESTRING, WKB_LINESTRINGZ,
)
from ..core.platform import platform_earthwork
from ..core.report_html import fmt, volume_report_html
from .alg_volumes import _VolumeBase, _log_result
from .tin_options import TinOptionsMixin

INCOMPLETE = ("O platô ou os taludes saem da área coberta pelo MDT: parte da terraplenagem "
              "não foi calculada e os volumes estão subestimados. Amplie o levantamento ou "
              "reduza o platô.")
NOTE = ("Platô horizontal na cota indicada; fora dele, taludes com inclinação constante a "
        "partir da borda (cantos convexos arredondados, como um cone). Corte = terreno acima "
        "da superfície final; aterro = abaixo. Volumes integrados numa malha regular de células "
        "(o tamanho usado está nos dados de entrada); áreas de corte e de aterro com a precisão "
        "de uma célula. Bermas, se informadas, são degraus planos a cada desnível indicado, "
        "contados a partir da borda do platô, nos taludes de corte e de aterro. Não considera "
        "camadas de pavimento nem empolamento além do fator informado.")


def _slope_txt(m):
    return "vertical (muro)" if m == 0 else f"{fmt(m, 2)} : 1 (H:V)"


class PlatformAlgorithm(TinOptionsMixin, _VolumeBase):
    INPUT, Z_FIELD, PLATFORM = "INPUT", "Z_FIELD", "PLATFORM"
    LEVEL, BALANCE, FACTOR = "LEVEL", "BALANCE", "FACTOR"
    CUT_SLOPE, FILL_SLOPE = "CUT_SLOPE", "FILL_SLOPE"
    MAX_EDGE, CELL, CONTOUR_INTERVAL = "MAX_EDGE", "CELL", "CONTOUR_INTERVAL"
    BENCH_H, BENCH_W = "BENCH_HEIGHT", "BENCH_WIDTH"
    OUTPUT, CONTOURS = "OUTPUT", "CONTOURS"
    LEVEL_OUT, FOOTPRINT, COMPLETE = "LEVEL_USED", "FOOTPRINT_AREA", "COMPLETE"

    def name(self):
        return "platform"

    def displayName(self):
        return "Platô com taludes (corte e aterro)"

    def shortHelpString(self):
        return (
            "Projeta um platô horizontal com taludes sobre o terreno: calcula o off-set (crista "
            "do corte e pé do aterro), os volumes de corte e aterro do platô e dos taludes e, se "
            "pedido, a cota de equilíbrio (corte = aterro × fator de homogeneização).\n\n"
            "Taludes em H:V (horizontal por 1 de vertical): 1,0 = 45°; 1,5 = 33,7°; 0 = muro "
            "vertical. Bermas: a cada 'desnível entre bermas' metros de altura, o talude ganha um "
            "degrau plano com a largura informada (0 = sem bermas); valem para corte e aterro e "
            "exigem talude maior que zero. Todas as feições da camada do platô formam um único platô na mesma cota "
            "(use 'Somente feições selecionadas' para escolher uma).\n\n"
            "Saídas: linha de off-set 3D (TIPO = Corte/Aterro; com bermas, também as bordas de "
            "cada berma, TIPO = Berma de corte/Berma de aterro, na cota da berma), curvas de nível do terreno final "
            "dentro da terraplenagem e relatório HTML. Se os taludes saírem da área do MDT, o "
            "resultado é marcado como incompleto.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, "Pontos cotados (terreno natural)", [SOURCE_POINT]))
        self.addParameter(QgsProcessingParameterField(
            self.Z_FIELD, "Campo da cota (vazio = Z da geometria)",
            parentLayerParameterName=self.INPUT, type=FIELD_NUMERIC, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PLATFORM, "Platô (polígono)", [SOURCE_POLYGON]))
        self.addParameter(QgsProcessingParameterNumber(
            self.LEVEL, "Cota do platô", NUM_DOUBLE, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.BALANCE, "Calcular a cota de equilíbrio (ignora a cota acima)", defaultValue=False))
        self.addParameter(QgsProcessingParameterNumber(
            self.CUT_SLOPE, "Talude de corte (H:V, 0 = vertical)", NUM_DOUBLE,
            defaultValue=1.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.FILL_SLOPE, "Talude de aterro (H:V, 0 = vertical)", NUM_DOUBLE,
            defaultValue=1.5, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BENCH_H, "Bermas: desnível entre bermas (m, 0 = sem bermas)", NUM_DOUBLE,
            defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BENCH_W, "Bermas: largura de cada berma (m)", NUM_DOUBLE,
            defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.FACTOR, "Fator de homogeneização (corte necessário = aterro × fator)", NUM_DOUBLE,
            defaultValue=1.0, minValue=0.01))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_EDGE, "Aresta máxima do TIN (0 = desligado)", NUM_DOUBLE,
            defaultValue=0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CONTOUR_INTERVAL, "Equidistância das curvas do terreno final (0 = não gerar)",
            NUM_DOUBLE, defaultValue=1.0, minValue=0.0))
        cell = QgsProcessingParameterNumber(
            self.CELL, "Tamanho da célula do cálculo (0 = automático)", NUM_DOUBLE,
            defaultValue=0.0, minValue=0.0)
        cell.setFlags(cell.flags() | FLAG_ADVANCED)
        self.addParameter(cell)
        self._add_tin_options()
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, "Off-set (crista do corte e pé do aterro)", SOURCE_LINE))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.CONTOURS, "Curvas do terreno final", SOURCE_LINE, optional=True,
            createByDefault=True))
        self._add_outputs()
        for name, text in ((self.LEVEL_OUT, "Cota do platô usada"),
                           (self.FOOTPRINT, "Área da terraplenagem"),
                           (self.COMPLETE, "Cálculo completo (1) ou incompleto (0)")):
            self.addOutput(QgsProcessingOutputNumber(name, text))

    def processAlgorithm(self, parameters, context, feedback):
        src = self.parameterAsSource(parameters, self.INPUT, context)
        if src is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        plat = self.parameterAsSource(parameters, self.PLATFORM, context)
        if plat is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.PLATFORM))
        z_field = self.parameterAsString(parameters, self.Z_FIELD, context) or None
        balance = self.parameterAsBool(parameters, self.BALANCE, context)
        level = None if balance else self.parameterAsDouble(parameters, self.LEVEL, context)
        m_cut = self.parameterAsDouble(parameters, self.CUT_SLOPE, context)
        m_fill = self.parameterAsDouble(parameters, self.FILL_SLOPE, context)
        factor = self.parameterAsDouble(parameters, self.FACTOR, context) or 1.0
        max_edge = self.parameterAsDouble(parameters, self.MAX_EDGE, context)
        interval = self.parameterAsDouble(parameters, self.CONTOUR_INTERVAL, context)
        cell = self.parameterAsDouble(parameters, self.CELL, context)
        bench_h = self.parameterAsDouble(parameters, self.BENCH_H, context)
        bench_w = self.parameterAsDouble(parameters, self.BENCH_W, context) if bench_h > 0 else 0.0

        tin = self._make_tin(parameters, context, feedback, src, z_field, max_edge)
        region, nplat = region_from_source(plat, src.sourceCrs(), context.transformContext())
        feedback.pushInfo(f"Platô: {nplat} feição(ões) de '{plat.sourceName()}'.")
        feedback.pushInfo("Calculando a cota de equilíbrio..." if balance else
                          f"Platô na cota {fmt(level)}.")
        feedback.setProgress(40)
        try:
            res = platform_earthwork(tin, region, m_cut, m_fill, level, factor, cell, interval,
                                     bench_h=bench_h, bench_w=bench_w)
        except ValueError as exc:
            raise QgsProcessingException(str(exc))
        feedback.setProgress(80)
        if balance:
            feedback.pushInfo(f"Cota de equilíbrio: {fmt(res.level)}")
        _log_result(feedback, res.volume_result())
        if not res.complete:
            feedback.reportError(INCOMPLETE, fatalError=False)

        fields = QgsFields()
        fields.append(QgsField("TIPO", TYPE_STRING))
        fields.append(QgsField("COMPRIMENTO", TYPE_DOUBLE))
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields,
                                          WKB_LINESTRINGZ, src.sourceCrs())
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))
        for o in res.offsets:
            sink.addFeature(line_feature_z(o.xyz, [o.kind, o.length]), FAST_INSERT)
        out = {self.OUTPUT: dest}

        cfields = QgsFields()
        cfields.append(QgsField("ELEV", TYPE_DOUBLE))
        cfields.append(QgsField("MESTRA", TYPE_INT))
        csink, cdest = self.parameterAsSink(parameters, self.CONTOURS, context, cfields,
                                            WKB_LINESTRING, src.sourceCrs())
        if csink is not None:
            for lv, master, path in res.contours:
                csink.addFeature(line_feature(path, [float(lv), int(master)]), FAST_INSERT)
            out[self.CONTOURS] = cdest

        lengths = {k: sum(o.length for o in res.offsets if o.kind == k) for k in ("Corte", "Aterro")}
        params = [("Terreno natural", src.sourceName()), ("Campo da cota", z_field or "Z da geometria"),
                  ("Platô", f"{plat.sourceName()} ({nplat} feição(ões))"),
                  ("Cota do platô", f"{fmt(res.level)}" + (" (equilíbrio calculado)" if balance else "")),
                  ("Talude de corte", _slope_txt(m_cut)), ("Talude de aterro", _slope_txt(m_fill)),
                  ("Bermas", f"a cada {fmt(bench_h, 2)} m de desnível, {fmt(bench_w, 2)} m de largura"
                   if bench_h > 0 and bench_w > 0 else "não"),
                  ("Fator de homogeneização", fmt(factor, 2)),
                  ("Aresta máxima", fmt(max_edge) if max_edge else "desligada"),
                  ("Triângulos do TIN", len(tin.triangles)), ("Célula do cálculo", fmt(res.cell, 3))]
        extra = [("Área do platô", fmt(res.platform_area)),
                 ("Aterro × fator (corte necessário)", fmt(res.fill * factor)),
                 ("Saldo compensado (corte − aterro × fator)", fmt(res.balance)),
                 ("Off-set em corte (comprimento)", fmt(lengths["Corte"], 2)),
                 ("Off-set em aterro (comprimento)", fmt(lengths["Aterro"], 2))]
        for side in ("Corte", "Aterro"):
            if res.benches.get(side):
                extra.append((f"Bermas no {side.lower()}", res.benches[side]))
        title = "Platô com taludes"
        out.update({self.CUT: res.cut, self.FILL: res.fill, self.NET: res.net,
                    self.LEVEL_OUT: res.level, self.FOOTPRINT: res.footprint_area,
                    self.COMPLETE: int(res.complete)})
        path = self.parameterAsFileOutput(parameters, self.REPORT, context)
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(volume_report_html(title, params, res.volume_result(), note=NOTE, extra=extra,
                                            warning=None if res.complete else INCOMPLETE))
            out[self.REPORT] = path
        return out
