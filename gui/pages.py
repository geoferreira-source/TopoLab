"""Páginas (etapas) da janela principal do TopoLab."""
import os
import tempfile

import processing
from qgis.core import QgsProcessingFeatureSourceDefinition
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QCheckBox, QDoubleSpinBox, QGroupBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSpinBox, QTableWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from ..compat import GEOM_POLYGON, LAYER_LINE, LAYER_POINT, LAYER_POLYGON, LAYER_RASTER, TYPE_DOUBLE, TYPE_STRING
from ..core.report_html import fmt
from . import runner


def _report_view():
    """Visualizador dos relatórios HTML (volumes, poligonal), sempre sobre fundo branco.

    Os relatórios têm cores próprias pensadas para papel (texto escuro); num tema escuro do
    QGIS o fundo ficava escuro e o texto, ilegível.
    """
    view = QTextBrowser()
    view.setStyleSheet("QTextBrowser { background-color: #ffffff; color: #222222; }")
    return view


class _LayerZPicker:
    """Par camada de pontos + campo da cota (vazio = Z da geometria)."""

    def __init__(self):
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(LAYER_POINT)
        self.field = QgsFieldComboBox()
        self.field.setAllowEmptyFieldName(True)
        self.field.setLayer(self.layer.currentLayer())
        self.layer.layerChanged.connect(self.field.setLayer)

    def value(self):
        return self.layer.currentLayer(), (self.field.currentField() or None)


class TinOptions(QWidget):
    """Linhas de quebra e limite do MDT (opcionais), reutilizado nas páginas que montam um TIN."""

    TITLE = "Linhas de quebra e limite do MDT (opcional)"

    def __init__(self, title=TITLE):
        super().__init__()
        self.box = QGroupBox(title)
        self.box.setCheckable(True)
        self.box.setChecked(False)
        form = QFormLayout(self.box)
        self.lines = QgsMapLayerComboBox()
        self.lines.setFilters(LAYER_LINE)
        self.lines.setAllowEmptyLayer(True)
        self.lines.setCurrentIndex(0)
        self.zf = QgsFieldComboBox()
        self.zf.setAllowEmptyFieldName(True)
        self.zf.setLayer(self.lines.currentLayer())
        self.lines.layerChanged.connect(self.zf.setLayer)
        self.bound = QgsMapLayerComboBox()
        self.bound.setFilters(LAYER_POLYGON)
        self.bound.setAllowEmptyLayer(True)
        self.bound.setCurrentIndex(0)
        note = QLabel("Linhas de quebra (taludes, valas, cristas, muros) viram arestas do TIN; a cota "
                      "vem do Z da geometria, do campo indicado ou do próprio MDT. O limite exclui "
                      "triângulos fora do polígono e dentro de furos. Cruzamentos com o limite ou com "
                      "linhas sem cota ganham vértice sozinhos; duas linhas com cota própria que se "
                      "cruzam precisam de um vértice comum.")
        note.setWordWrap(True)
        form.addRow("Linhas de quebra", self.lines)
        form.addRow("Campo da cota das linhas", self.zf)
        form.addRow("Limite do MDT (polígono)", self.bound)
        form.addRow(note)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.box)

    def layers(self):
        """(linhas, campo da cota, limite) — None para o que não foi escolhido/ativado."""
        if not self.box.isChecked():
            return None, None, None
        bl, bd = self.lines.currentLayer(), self.bound.currentLayer()
        return bl, ((self.zf.currentField() or None) if bl else None), bd

    def params(self, suffix=""):
        bl, bz, bd = self.layers()
        return {"BREAKLINES" + suffix: bl, "BREAK_Z" + suffix: bz, "BOUNDARY" + suffix: bd}

    def set_title(self, title):
        self.box.setTitle(title)


class PlaceholderPage(QWidget):
    def __init__(self, text):
        super().__init__()
        lay = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        lay.addWidget(label)
        lay.addStretch()


class PointsPage(QWidget):
    OTHER_FILTER = ("Dados geográficos (*.dxf *.shp *.gpkg *.geojson *.kml *.gpx *.tif *.tiff);;"
                    "Todos (*)")

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        lay = QVBoxLayout(self)
        info = QLabel(
            "Traga os pontos cotados do levantamento como camada de pontos.\n\n"
            "• CSV/TXT (ponto, X, Y, Z...): o assistente detecta separador, decimal "
            "(vírgula ou ponto), cabeçalho e codificação, e deixa você escolher a ordem "
            "das colunas, inclusive Norte/Leste invertidos.\n"
            "• DXF de levantamento: o assistente lê pontos (inclusive blocos e círculos), cotas "
            "escritas em texto ao lado dos pontos, curvas e linhas, e o limite.\n"
            "• DXF, Shapefile, GeoPackage, GeoJSON, KML/GPX: também podem entrar direto como camada.\n"
            "• GeoTIFF (MDE, ortomosaico): adicionado como raster.\n\n"
            "Use um CRS projetado (SIRGAS 2000 / UTM) e confira a ordem Leste/Norte.")
        info.setWordWrap(True)
        b_txt = QPushButton("Importar pontos (CSV/TXT)...")
        b_txt.clicked.connect(self._import_text)
        b_dxf = QPushButton("Importar DXF de levantamento (pontos, cotas em texto, linhas)...")
        b_dxf.clicked.connect(self._import_dxf)
        b_other = QPushButton("Adicionar DXF / Shapefile / GeoPackage / raster como camada...")
        b_other.clicked.connect(self._add_other)
        b_dem = QPushButton("Converter MDE (raster) em pontos cotados...")
        b_dem.clicked.connect(self._dem_to_points)
        b_qa = QPushButton("Verificar qualidade dos pontos (cota zero, duplicados, picos)...")
        b_qa.clicked.connect(self._check_points)
        lay.addWidget(info)
        lay.addWidget(b_txt)
        lay.addWidget(b_dxf)
        lay.addWidget(b_other)
        lay.addWidget(b_dem)
        lay.addWidget(b_qa)
        lay.addStretch()

    def _check_points(self):
        from qgis.PyQt.QtWidgets import QDialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Verificar qualidade dos pontos")
        dlg.resize(560, 480)
        root = QVBoxLayout(dlg)
        form = QFormLayout()
        pick = _LayerZPicker()
        idf = QgsFieldComboBox()
        idf.setAllowEmptyFieldName(True)
        idf.setLayer(pick.layer.currentLayer())
        pick.layer.layerChanged.connect(idf.setLayer)
        near = QDoubleSpinBox()
        near.setDecimals(3)
        near.setRange(0, 1000)
        near.setValue(0.05)
        near.setSpecialValueText("desligado")
        form.addRow("Camada de pontos", pick.layer)
        form.addRow("Campo da cota (vazio = Z)", pick.field)
        form.addRow("Campo do identificador", idf)
        form.addRow("Distância mínima entre pontos", near)
        root.addLayout(form)
        run = QPushButton("Verificar")
        out = QTextBrowser()
        root.addWidget(run)
        root.addWidget(out, 1)

        def go():
            layer, zf = pick.value()
            if layer is None:
                self.iface.messageBar().pushWarning("TopoLab", "Escolha a camada de pontos.")
                return
            fd, rep = tempfile.mkstemp(suffix=".html", prefix="topolab_qa_")
            os.close(fd)
            try:
                res = processing.runAndLoadResults("topolab:check_points", {
                    "INPUT": layer, "Z_FIELD": zf, "ID_FIELD": idf.currentField() or None,
                    "NEAR": near.value(), "ZERO_TOL": 0.0, "SPIKE_N": 6.0, "SPIKE_MIN": 0.02,
                    "OUTPUT": "TEMPORARY_OUTPUT", "REPORT": rep})
                with open(rep, encoding="utf-8") as fh:
                    out.setHtml(fh.read())
                self.iface.messageBar().pushInfo(
                    "TopoLab", f"{res.get('FLAGGED', '?')} de {res.get('TOTAL', '?')} pontos sinalizados "
                               "(camada 'Pontos sinalizados' adicionada).")
            except Exception as exc:  # noqa: BLE001
                self.iface.messageBar().pushCritical("TopoLab", str(exc))
            finally:
                try:
                    os.remove(rep)
                except OSError:
                    pass

        run.clicked.connect(go)
        dlg.exec()

    def _dem_to_points(self):
        from qgis.PyQt.QtWidgets import QDialog
        dlg = QDialog(self)
        dlg.setWindowTitle("MDE (raster) em pontos cotados")
        form = QFormLayout(dlg)
        cb = QgsMapLayerComboBox()
        cb.setFilters(LAYER_RASTER)
        band, step = QSpinBox(), QSpinBox()
        band.setRange(1, 99)
        step.setRange(1, 10000)
        step.setValue(5)
        hint = QLabel("O passo pega 1 célula a cada N. Passos menores dão mais detalhe e um TIN "
                      "maior (e mais lento).")
        hint.setWordWrap(True)
        run = QPushButton("Converter")
        run.clicked.connect(dlg.accept)
        form.addRow("MDE", cb)
        form.addRow("Banda", band)
        form.addRow("Passo (células)", step)
        form.addRow(hint)
        form.addRow(run)
        if dlg.exec() != QDialog.DialogCode.Accepted or cb.currentLayer() is None:
            return
        try:
            processing.runAndLoadResults("topolab:raster_to_points", {
                "INPUT": cb.currentLayer(), "BAND": band.value(), "STEP": step.value(),
                "OUTPUT": "TEMPORARY_OUTPUT"})
        except Exception as exc:  # noqa: BLE001
            self.iface.messageBar().pushCritical("TopoLab", str(exc))

    def _import_dxf(self):
        from .dxf_dialog import ImportDxfDialog
        ImportDxfDialog(self.iface, self).exec()

    def _import_text(self):
        from .import_dialog import ImportPointsDialog
        dlg = ImportPointsDialog(self.iface, self)
        dlg.exec()

    def _add_other(self):
        path, _ = QFileDialog.getOpenFileName(self, "Adicionar arquivo", "", self.OTHER_FILTER)
        if not path:
            return
        name = os.path.splitext(os.path.basename(path))[0]
        if path.lower().endswith((".tif", ".tiff")):
            layer = self.iface.addRasterLayer(path, name)
        else:  # DXF com várias camadas abre o seletor de subcamadas do próprio QGIS
            layer = self.iface.addVectorLayer(path, name, "ogr")
        if not layer:
            self.iface.messageBar().pushWarning("TopoLab", f"Não foi possível abrir {path}.")


class ContoursPage(QWidget):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        form = QFormLayout(self)
        self.pts = _LayerZPicker()
        self.sp_interval = QDoubleSpinBox()
        self.sp_interval.setDecimals(3)
        self.sp_interval.setRange(0.001, 10000)
        self.sp_interval.setValue(1.0)
        self.sp_master = QSpinBox()
        self.sp_master.setRange(0, 100)
        self.sp_master.setValue(5)
        self.sp_edge = QDoubleSpinBox()
        self.sp_edge.setRange(0, 1e6)
        self.sp_edge.setSpecialValueText("desligada")
        run = QPushButton("Gerar curvas de nível")
        run.clicked.connect(self._run)
        form.addRow("Camada de pontos", self.pts.layer)
        form.addRow("Campo da cota (vazio = Z)", self.pts.field)
        form.addRow("Equidistância", self.sp_interval)
        form.addRow("Mestra a cada N", self.sp_master)
        form.addRow("Aresta máxima", self.sp_edge)
        self.tin = TinOptions()
        form.addRow(self.tin)
        form.addRow(run)

    def _run(self):
        layer, zf = self.pts.value()
        if layer is None:
            self.iface.messageBar().pushWarning("TopoLab", "Escolha uma camada de pontos.")
            return
        runner.run(self, "topolab:tin_contours", {
            "INPUT": layer, "Z_FIELD": zf, "INTERVAL": self.sp_interval.value(),
            "MASTER_EVERY": self.sp_master.value(), "MAX_EDGE": self.sp_edge.value(),
            "OUTPUT": "TEMPORARY_OUTPUT", **self.tin.params()}, lambda res: None)


class VolumesPage(QWidget):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self._report_html = ""
        root = QVBoxLayout(self)

        modes = QHBoxLayout()
        self.rb_datum = QRadioButton("Contra cota de referência")
        self.rb_between = QRadioButton("Entre duas superfícies")
        self.rb_platform = QRadioButton("Platô com taludes")
        self.rb_datum.setChecked(True)
        grp = QButtonGroup(self)
        for rb in (self.rb_datum, self.rb_between, self.rb_platform):
            grp.addButton(rb)
            modes.addWidget(rb)
        modes.addStretch()
        root.addLayout(modes)

        form = QFormLayout()
        self.a = _LayerZPicker()
        self.b = _LayerZPicker()
        self.lbl_a = QLabel("Camada de pontos")
        self.lbl_a_field = QLabel("Campo da cota (vazio = Z)")
        self.lbl_b = QLabel("Superfície final (B)")
        self.lbl_b_field = QLabel("Campo da cota de B")
        self.sp_datum = QDoubleSpinBox()
        self.sp_datum.setDecimals(3)
        self.sp_datum.setRange(-1e6, 1e6)
        self.lbl_datum = QLabel("Cota de referência")
        self.sp_edge = QDoubleSpinBox()
        self.sp_edge.setRange(0, 1e6)
        self.sp_edge.setSpecialValueText("desligada")
        form.addRow(self.lbl_a, self.a.layer)
        form.addRow(self.lbl_a_field, self.a.field)
        form.addRow(self.lbl_b, self.b.layer)
        form.addRow(self.lbl_b_field, self.b.field)

        # platô com taludes
        self.plat = QgsMapLayerComboBox()
        self.plat.setFilters(LAYER_POLYGON)
        self.chk_plat_sel = QCheckBox("Somente feições selecionadas")
        self.chk_balance = QCheckBox("Calcular a cota de equilíbrio (corte = aterro × fator)")
        self.chk_balance.toggled.connect(self._update_mode)
        self.sp_mcut, self.sp_mfill = self._slope(1.0), self._slope(1.5)
        self.sp_factor = QDoubleSpinBox()
        self.sp_factor.setDecimals(2)
        self.sp_factor.setRange(0.01, 10)
        self.sp_factor.setValue(1.0)
        self.sp_cint = QDoubleSpinBox()
        self.sp_cint.setDecimals(2)
        self.sp_cint.setRange(0, 1000)
        self.sp_cint.setValue(1.0)
        self.sp_cint.setSpecialValueText("não gerar")
        self.sp_bench_h = QDoubleSpinBox()
        self.sp_bench_h.setDecimals(2)
        self.sp_bench_h.setRange(0, 100)
        self.sp_bench_h.setSuffix(" m de desnível")
        self.sp_bench_h.setSpecialValueText("sem bermas")
        self.sp_bench_h.setToolTip("A cada quantos metros de altura o talude ganha um degrau plano "
                                   "(berma). Usual: 5 a 10 m. Vale para corte e aterro.")
        self.sp_bench_w = QDoubleSpinBox()
        self.sp_bench_w.setDecimals(2)
        self.sp_bench_w.setRange(0.1, 100)
        self.sp_bench_w.setValue(2.0)
        self.sp_bench_w.setSuffix(" m de largura")
        self.sp_bench_h.valueChanged.connect(lambda v: self.sp_bench_w.setEnabled(v > 0))
        self.sp_bench_w.setEnabled(False)
        plat_rows = [("Platô (polígono)", self.plat), ("", self.chk_plat_sel), None,
                     ("", self.chk_balance), ("Talude de corte", self.sp_mcut),
                     ("Talude de aterro", self.sp_mfill), ("Bermas a cada", self.sp_bench_h),
                     ("Largura da berma", self.sp_bench_w), ("Fator de homogeneização", self.sp_factor),
                     ("Curvas do terreno final a cada", self.sp_cint)]
        self.plat_widgets = []
        for row in plat_rows:
            if row is None:  # a cota (do platô ou de referência) entra aqui
                form.addRow(self.lbl_datum, self.sp_datum)
                continue
            lbl = QLabel(row[0])
            form.addRow(lbl, row[1])
            self.plat_widgets += [lbl, row[1]]
        form.addRow("Aresta máxima", self.sp_edge)
        self.tin = TinOptions()
        form.addRow(self.tin)
        self.tin_b = TinOptions("Linhas de quebra e limite do MDT — superfície B (opcional)")
        form.addRow(self.tin_b)

        self.chk_region = QCheckBox("Limitar a polígono(s)")
        self.cb_region = QgsMapLayerComboBox()
        self.cb_region.setFilters(LAYER_POLYGON)
        self.chk_selected = QCheckBox("Somente feições selecionadas")
        self.cb_region.setEnabled(False)
        self.chk_selected.setEnabled(False)
        self.chk_region.toggled.connect(self.cb_region.setEnabled)
        self.chk_region.toggled.connect(self.chk_selected.setEnabled)
        self.lbl_selected = QLabel("")
        form.addRow(self.chk_region, self.cb_region)
        form.addRow(self.lbl_selected, self.chk_selected)
        root.addLayout(form)

        buttons = QHBoxLayout()
        run = QPushButton("Calcular volumes")
        run.clicked.connect(self._run)
        self.btn_save = QPushButton("Salvar relatório HTML...")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save)
        buttons.addWidget(run)
        buttons.addWidget(self.btn_save)
        buttons.addStretch()
        root.addLayout(buttons)

        self.out = _report_view()
        root.addWidget(self.out, 1)

        for rb in (self.rb_datum, self.rb_between, self.rb_platform):
            rb.toggled.connect(self._update_mode)
        self._update_mode()

    @staticmethod
    def _slope(value):
        sp = QDoubleSpinBox()
        sp.setDecimals(2)
        sp.setRange(0, 100)
        sp.setValue(value)
        sp.setSuffix(" : 1 (H:V)")
        sp.setSpecialValueText("vertical (muro)")
        return sp

    def _mode(self):
        if self.rb_platform.isChecked():
            return "platform"
        return "datum" if self.rb_datum.isChecked() else "between"

    def _update_mode(self):
        mode = self._mode()
        single = mode != "between"
        self.lbl_a.setText("Superfície original (A)" if not single else
                           "Terreno natural (pontos)" if mode == "platform" else "Camada de pontos")
        self.lbl_a_field.setText("Campo da cota (vazio = Z)" if single else "Campo da cota de A")
        for w in (self.lbl_b, self.b.layer, self.lbl_b_field, self.b.field):
            w.setVisible(not single)
        for w in (self.lbl_datum, self.sp_datum):
            w.setVisible(single)
        self.lbl_datum.setText("Cota do platô" if mode == "platform" else "Cota de referência")
        self.sp_datum.setEnabled(not (mode == "platform" and self.chk_balance.isChecked()))
        for w in self.plat_widgets:
            w.setVisible(mode == "platform")
        for w in (self.chk_region, self.cb_region, self.lbl_selected, self.chk_selected):
            w.setVisible(mode != "platform")  # no platô, o próprio polígono delimita o cálculo
        self.tin.set_title(TinOptions.TITLE if single else
                           "Linhas de quebra e limite do MDT — superfície A (opcional)")
        self.tin_b.setVisible(not single)

    def _run(self):
        layer_a, za = self.a.value()
        if layer_a is None:
            self.iface.messageBar().pushWarning("TopoLab", "Escolha a camada de pontos.")
            return
        region = None
        if self._mode() == "platform":
            return self._run_platform(layer_a, za)
        if self.chk_region.isChecked():
            rl = self.cb_region.currentLayer()
            if rl is None:
                self.iface.messageBar().pushWarning("TopoLab", "Escolha a camada de polígonos.")
                return
            region = QgsProcessingFeatureSourceDefinition(rl.id(), self.chk_selected.isChecked())
        if self.rb_datum.isChecked():
            alg, params = "topolab:volume_datum", {
                "INPUT": layer_a, "Z_FIELD": za, "DATUM": self.sp_datum.value(),
                "MAX_EDGE": self.sp_edge.value(), "REGION": region, **self.tin.params()}
        else:
            layer_b, zb = self.b.value()
            if layer_b is None:
                self.iface.messageBar().pushWarning("TopoLab", "Escolha a superfície B.")
                return
            alg, params = "topolab:volume_between", {
                "INPUT_A": layer_a, "Z_FIELD_A": za, "INPUT_B": layer_b, "Z_FIELD_B": zb,
                "MAX_EDGE": self.sp_edge.value(), "REGION": region,
                **self.tin.params(), **self.tin_b.params("_B")}
        report = _temp_report()
        runner.run(self, alg, {**params, "REPORT": report},
                   lambda res: self._show_report(report), load=False)

    def _show_report(self, report):
        try:
            with open(report, encoding="utf-8") as fh:
                self._report_html = fh.read()
            self.out.setHtml(self._report_html)
            self.btn_save.setEnabled(True)
        finally:
            try:
                os.remove(report)
            except OSError:
                pass

    def _run_platform(self, layer, zf):
        from qgis.core import QgsProject
        bar = self.iface.messageBar()
        pl = self.plat.currentLayer()
        if pl is None:
            bar.pushWarning("TopoLab", "Escolha a camada do platô (polígono).")
            return
        if self.chk_plat_sel.isChecked() and not pl.selectedFeatureCount():
            bar.pushWarning("TopoLab", "Nenhuma feição selecionada na camada do platô.")
            return
        plat = QgsProcessingFeatureSourceDefinition(pl.id(), True) if self.chk_plat_sel.isChecked() else pl
        balance, cint = self.chk_balance.isChecked(), self.sp_cint.value()
        report = _temp_report()

        def done(res):
            self._show_report(report)
            if balance:
                self.sp_datum.setValue(res["LEVEL_USED"])
                bar.pushInfo("TopoLab", f"Cota de equilíbrio: {fmt(res['LEVEL_USED'])}")
            if not res.get("COMPLETE", 1):
                bar.pushWarning("TopoLab", "Os taludes saem da área do MDT: volumes incompletos "
                                           "(veja o relatório).")
            out = res.get("OUTPUT")
            lyr = QgsProject.instance().mapLayer(out) if isinstance(out, str) else out
            if lyr is not None and hasattr(lyr, "fields"):
                colors = {"Corte": "#c0392b", "Aterro": "#2b6cb0", "Fora do MDT": "#888888",
                          "Berma de corte": "#e67e22", "Berma de aterro": "#16a085"}
                _style_categorized(lyr, "TIPO", lambda v: colors.get(v, "#888888"))

        runner.run(self, "topolab:platform", {
            "INPUT": layer, "Z_FIELD": zf, "PLATFORM": plat, "LEVEL": self.sp_datum.value(),
            "BALANCE": balance, "CUT_SLOPE": self.sp_mcut.value(), "FILL_SLOPE": self.sp_mfill.value(),
            "FACTOR": self.sp_factor.value(), "MAX_EDGE": self.sp_edge.value(),
            "BENCH_HEIGHT": self.sp_bench_h.value(), "BENCH_WIDTH": self.sp_bench_w.value(),
            "CONTOUR_INTERVAL": cint, "CELL": 0.0, "OUTPUT": "TEMPORARY_OUTPUT",
            "CONTOURS": "TEMPORARY_OUTPUT" if cint > 0 else None, "REPORT": report,
            **self.tin.params()}, done)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", "volumes.html",
                                              "HTML (*.html)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._report_html)


class ProfilePage(QWidget):
    """Perfil longitudinal e seções transversais (calculado direto no núcleo)."""

    def __init__(self, iface):
        super().__init__()
        from qgis.PyQt.QtWidgets import QComboBox

        from .profile_canvas import ProfileCanvas

        self.iface = iface
        self._profile = None
        self._sections = []
        self._datum = None
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.axis = QgsMapLayerComboBox()
        self.axis.setFilters(LAYER_LINE)
        self.chk_selected = QCheckBox("Somente a feição selecionada")
        self.pts = _LayerZPicker()
        self.sp_pstep = self._spin(5.0, 0.001, 1e5)
        self.sp_interval = self._spin(20.0, 0.001, 1e5)
        self.sp_half = self._spin(15.0, 0.001, 1e5)
        self.sp_sstep = self._spin(1.0, 0.001, 1e4)
        self.chk_datum = QCheckBox("Cota de referência (greide)")
        self.sp_datum = self._spin(0.0, -1e6, 1e6)
        self.sp_datum.setEnabled(False)
        self.chk_datum.toggled.connect(self.sp_datum.setEnabled)
        self.sp_edge = QDoubleSpinBox()
        self.sp_edge.setRange(0, 1e6)
        self.sp_edge.setSpecialValueText("desligada")
        form.addRow("Eixo (linha)", self.axis)
        form.addRow("", self.chk_selected)
        form.addRow("Camada de pontos", self.pts.layer)
        form.addRow("Campo da cota (vazio = Z)", self.pts.field)
        form.addRow("Passo do perfil", self.sp_pstep)
        form.addRow("Intervalo entre seções", self.sp_interval)
        form.addRow("Largura de cada lado", self.sp_half)
        form.addRow("Passo na seção", self.sp_sstep)
        form.addRow(self.chk_datum, self.sp_datum)
        form.addRow("Aresta máxima", self.sp_edge)
        self.tin = TinOptions()
        form.addRow(self.tin)
        root.addLayout(form)

        buttons = QHBoxLayout()
        run = QPushButton("Calcular")
        run.clicked.connect(self._compute)
        self.btn_csv = QPushButton("Exportar CSV...")
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_layers = QPushButton("Criar camadas no projeto")
        self.btn_layers.clicked.connect(self._make_layers)
        for b in (self.btn_csv, self.btn_layers):
            b.setEnabled(False)
        for b in (run, self.btn_csv, self.btn_layers):
            buttons.addWidget(b)
        buttons.addStretch()
        root.addLayout(buttons)

        self.view = QComboBox()
        self.view.currentIndexChanged.connect(self._draw)
        root.addWidget(self.view)
        self.canvas = ProfileCanvas()
        root.addWidget(self.canvas, 1)
        self.summary = QTextBrowser()
        self.summary.setMaximumHeight(130)
        root.addWidget(self.summary)

    @staticmethod
    def _spin(value, lo, hi):
        sp = QDoubleSpinBox()
        sp.setDecimals(3)
        sp.setRange(lo, hi)
        sp.setValue(value)
        return sp

    def _warn(self, text):
        self.iface.messageBar().pushWarning("TopoLab", text)

    def _compute(self):
        from qgis.core import QgsProject

        from ..adapters.qgis_adapters import axis_from_source, make_tin
        from ..core.profiles import Axis, cross_sections, profile_along, section_volumes
        from ..core.report_html import fmt as f

        axis_layer, (pl, zf) = self.axis.currentLayer(), self.pts.value()
        if axis_layer is None or pl is None:
            self._warn("Escolha a camada do eixo e a camada de pontos.")
            return
        try:
            bl, bz, bd = self.tin.layers()
            tin = make_tin(pl, zf, self.sp_edge.value(), bl, bz, bd,
                           QgsProject.instance().transformContext())
            xy, _ = axis_from_source(axis_layer, pl.crs(), QgsProject.instance().transformContext(),
                                     self.chk_selected.isChecked())
            ax = Axis(xy)
            self._datum = self.sp_datum.value() if self.chk_datum.isChecked() else None
            self._profile = profile_along(tin, ax, self.sp_pstep.value())
            self._sections = cross_sections(tin, ax, self.sp_interval.value(), self.sp_half.value(),
                                            self.sp_sstep.value(), self._datum)
        except Exception as exc:  # noqa: BLE001
            self.iface.messageBar().pushCritical("TopoLab", str(exc))
            return

        from ..core.profiles import format_station
        self.view.blockSignals(True)
        self.view.clear()
        self.view.addItem("Perfil longitudinal")
        for s in self._sections:
            self.view.addItem(f"Seção {format_station(s.station)}  ({f(s.station, 2)} m)")
        self.view.blockSignals(False)
        self.view.setCurrentIndex(0)
        self._draw()

        html = f"<b>Eixo:</b> {f(ax.length, 2)} m &nbsp; <b>Seções:</b> {len(self._sections)}"
        bad = sum(not s.complete for s in self._sections)
        if bad:
            html += f" &nbsp; <span style='color:#c0392b'>{bad} incompleta(s) (fora do TIN)</span>"
        if self._datum is not None:
            rows = section_volumes(self._sections)
            html += (f"<br><b>Volumes (média das áreas):</b> corte {f(sum(r[2] for r in rows))} "
                     f"&nbsp; aterro {f(sum(r[3] for r in rows))} &nbsp; "
                     f"saldo {f(sum(r[2] - r[3] for r in rows))}")
        self.summary.setHtml(html)
        self.btn_csv.setEnabled(True)
        self.btn_layers.setEnabled(True)

    def _draw(self):
        from ..core.profiles import format_station
        i = self.view.currentIndex()
        if self._profile is None or i < 0:
            return
        if i == 0:
            self.canvas.set_data(self._profile.station, self._profile.z,
                                 "Perfil longitudinal", "distância (m)", None)
        else:
            s = self._sections[i - 1]
            self.canvas.set_data(s.offsets, s.z, f"Seção {format_station(s.station)}",
                                 "deslocamento (m) — direita (+) / esquerda (−)", self._datum)

    def _export_csv(self):
        from ..core.export import write_profile_csv, write_sections_csv
        base, _ = QFileDialog.getSaveFileName(self, "Exportar CSV (prefixo)", "topolab.csv", "CSV (*.csv)")
        if not base:
            return
        stem = base[:-4] if base.lower().endswith(".csv") else base
        write_profile_csv(stem + "_perfil.csv", self._profile)
        write_sections_csv(stem + "_secoes.csv", self._sections)
        self.iface.messageBar().pushSuccess("TopoLab", f"Gravados {stem}_perfil.csv e {stem}_secoes.csv")

    def _make_layers(self):
        axis_layer, (pl, zf) = self.axis.currentLayer(), self.pts.value()
        axis_in = (QgsProcessingFeatureSourceDefinition(axis_layer.id(), True)
                   if self.chk_selected.isChecked() else axis_layer)
        base = {"INPUT": pl, "Z_FIELD": zf, "AXIS": axis_in, "MAX_EDGE": self.sp_edge.value(),
                "OUTPUT": "TEMPORARY_OUTPUT", **self.tin.params()}
        sections = {**base, "INTERVAL": self.sp_interval.value(), "HALF_WIDTH": self.sp_half.value(),
                    "STEP": self.sp_sstep.value(),
                    "DATUM": self.sp_datum.value() if self.chk_datum.isChecked() else None}
        runner.run(self, "topolab:profile", {**base, "STEP": self.sp_pstep.value()},
                   lambda res: runner.run(self, "topolab:cross_sections", sections, lambda r: None))


class _PasteTable(QTableWidget):
    """Tabela editável que aceita colar células copiadas do Excel/Calc (Ctrl+V)."""

    def keyPressEvent(self, event):
        from qgis.PyQt.QtGui import QKeySequence
        from qgis.PyQt.QtWidgets import QApplication, QTableWidgetItem
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            r0, c0 = max(self.currentRow(), 0), max(self.currentColumn(), 0)
            for i, line in enumerate(l for l in text.splitlines() if l.strip()):
                if r0 + i >= self.rowCount():
                    self.setRowCount(r0 + i + 1)
                for j, cell in enumerate(line.split("\t")):
                    if c0 + j < self.columnCount():
                        self.setItem(r0 + i, c0 + j, QTableWidgetItem(cell.strip()))
            return
        super().keyPressEvent(event)


class TraversePage(QWidget):
    """Planilha (caderneta) de poligonal: fechamento, ajuste, coordenadas, área e memorial."""

    HEADERS_H = ["Estação", "Ângulo", "Distância até a próxima (m)"]
    HEADERS_S = ["Estação", "Ângulo horizontal", "Dist. inclinada até a próxima (m)", "Ângulo zenital",
                 "Alt. instrumento (m)", "Alt. sinal na próxima (m)"]
    MODES = [("Fechada (volta ao ponto inicial)", "fechada"),
             ("Enquadrada (parte e chega em pontos conhecidos)", "enquadrada"),
             ("Aberta (sem verificação)", "aberta")]

    def __init__(self, iface):
        super().__init__()
        from qgis.gui import QgsProjectionSelectionWidget
        from qgis.core import QgsProject
        from qgis.PyQt.QtWidgets import QComboBox, QTabWidget, QTextEdit

        from ..core.angles import ANGLE_FORMATS
        from ..core.traverse import METHODS

        self.iface = iface
        self.result = None
        self._params = []
        root = QVBoxLayout(self)

        self.table = _PasteTable(4, 3)
        self.table.setHorizontalHeaderLabels(self.HEADERS_H)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(150)
        root.addWidget(QLabel("Caderneta de campo — cole células do Excel com Ctrl+V:"))
        root.addWidget(self.table)
        rowbtn = QHBoxLayout()
        for text, slot in (("+ linha", self._add_row), ("− linha", self._del_row),
                           ("Limpar", self._clear), ("Carregar CSV...", self._load_csv)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            rowbtn.addWidget(b)
        rowbtn.addStretch()
        root.addLayout(rowbtn)

        form = QFormLayout()
        self.cb_mode = QComboBox()
        for label, v in self.MODES:
            self.cb_mode.addItem(label, v)
        self.cb_turn = QComboBox()
        self.cb_turn.addItem("À direita (horário, a partir da ré)", "direita")
        self.cb_turn.addItem("À esquerda (anti-horário, a partir da ré)", "esquerda")
        self.cb_fmt = QComboBox()
        for k, label in ANGLE_FORMATS.items():
            self.cb_fmt.addItem(label, k)
        self.x0, self.y0 = self._coord(), self._coord()
        self.az0 = QLineEdit("0°00'00\"")
        self.lbl_az0 = QLabel("Azimute da 1ª linha")
        self.xe, self.ye = self._coord(), self._coord()
        self.aze = QLineEdit("0°00'00\"")
        self.end_widgets = [QLabel("X final"), self.xe, QLabel("Y final"), self.ye,
                            QLabel("Azimute da linha de vante (final)"), self.aze]
        self.cb_method = QComboBox()
        for k, label in METHODS.items():
            self.cb_method.addItem(label, k)
        self.sp_atol = QDoubleSpinBox()
        self.sp_atol.setRange(0, 10000)
        self.sp_atol.setValue(30.0)
        self.sp_atol.setSuffix(' " × √n')
        self.sp_ptol = QDoubleSpinBox()
        self.sp_ptol.setRange(0, 1e7)
        self.sp_ptol.setDecimals(0)
        self.sp_ptol.setValue(5000)
        self.sp_ptol.setPrefix("1 : ")
        self.title = QLineEdit("Poligonal")
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setCrs(QgsProject.instance().crs())

        form.addRow("Tipo de poligonal", self.cb_mode)
        form.addRow("Sentido do ângulo", self.cb_turn)
        form.addRow("Formato do ângulo", self.cb_fmt)
        form.addRow("X (Leste) da 1ª estação", self.x0)
        form.addRow("Y (Norte) da 1ª estação", self.y0)
        form.addRow(self.lbl_az0, self.az0)
        form.addRow(self.end_widgets[0], self.xe)
        form.addRow(self.end_widgets[2], self.ye)
        form.addRow(self.end_widgets[4], self.aze)
        # distâncias: horizontais, ou inclinadas com ângulo zenital (nivelamento trigonométrico)
        self.cb_dist = QComboBox()
        self.cb_dist.addItem("Horizontais", "horizontal")
        self.cb_dist.addItem("Inclinadas + ângulo zenital (calcula as cotas)", "inclinada")
        self.z0 = self._coord()
        self.ze = self._coord()
        self.lbl_z0, self.lbl_ze = QLabel("Cota da 1ª estação"), QLabel("Cota final (estação de chegada)")
        self.chk_curv = QCheckBox("Corrigir curvatura e refração (k = 0,13)")
        self.chk_curv.setChecked(True)
        self.sp_vtol = QDoubleSpinBox()
        self.sp_vtol.setRange(0, 10000)
        self.sp_vtol.setValue(50.0)
        self.sp_vtol.setSuffix(" mm × √km")
        self.sp_vtol.setSpecialValueText("sem tolerância")
        self.lbl_vtol, self.lbl_curv = QLabel("Tolerância altimétrica"), QLabel("")
        form.addRow("Distâncias", self.cb_dist)
        form.addRow(self.lbl_z0, self.z0)
        form.addRow(self.lbl_ze, self.ze)
        form.addRow(self.lbl_curv, self.chk_curv)
        form.addRow(self.lbl_vtol, self.sp_vtol)
        form.addRow("Ajuste linear", self.cb_method)
        form.addRow("Tolerância angular", self.sp_atol)
        form.addRow("Precisão linear mínima", self.sp_ptol)
        form.addRow("Título", self.title)
        form.addRow("CRS (para as camadas)", self.crs)
        root.addLayout(form)
        self.cb_mode.currentIndexChanged.connect(self._mode_changed)
        self.cb_dist.currentIndexChanged.connect(self._dist_changed)
        self._dist_changed()
        self._mode_changed()

        btns = QHBoxLayout()
        self.btn_run = QPushButton("Calcular")
        self.btn_run.clicked.connect(self._calculate)
        self.btn_csv = QPushButton("Exportar CSV...")
        self.btn_html = QPushButton("Salvar relatório HTML...")
        self.btn_layers = QPushButton("Criar camadas")
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_html.clicked.connect(self._export_html)
        self.btn_layers.clicked.connect(self._make_layers)
        for b in (self.btn_csv, self.btn_html, self.btn_layers):
            b.setEnabled(False)
        for b in (self.btn_run, self.btn_csv, self.btn_html, self.btn_layers):
            btns.addWidget(b)
        btns.addStretch()
        root.addLayout(btns)

        self.tabs = QTabWidget()
        self.out = _report_view()
        self.memorial = QTextEdit()
        mem = QWidget()
        ml = QVBoxLayout(mem)
        note = QLabel("Rascunho gerado a partir dos vértices e lados calculados. Complete com os "
                      "dados do imóvel (confrontantes, matrícula, responsável técnico etc.) "
                      "conforme a exigência do órgão a que se destina.")
        note.setWordWrap(True)
        save_mem = QPushButton("Salvar memorial (.txt)...")
        save_mem.clicked.connect(self._save_memorial)
        ml.addWidget(note)
        ml.addWidget(self.memorial, 1)
        ml.addWidget(save_mem)
        self.tabs.addTab(self.out, "Resultado")
        self.tabs.addTab(mem, "Memorial descritivo")
        root.addWidget(self.tabs, 1)

    # --- utilidades -----------------------------------------------------
    @staticmethod
    def _coord():
        sp = QDoubleSpinBox()
        sp.setDecimals(3)
        sp.setRange(-1e9, 1e9)
        return sp

    def _mode(self):
        return self.cb_mode.currentData()

    def _slope(self):
        return self.cb_dist.currentData() == "inclinada"

    def _dist_changed(self):
        slope = self._slope()
        self.table.setColumnCount(6 if slope else 3)
        self.table.setHorizontalHeaderLabels(self.HEADERS_S if slope else self.HEADERS_H)
        for w in (self.lbl_z0, self.z0, self.lbl_curv, self.chk_curv, self.lbl_vtol, self.sp_vtol):
            w.setVisible(slope)
        self._mode_changed()

    def _mode_changed(self):
        mode = self._mode()
        for w in (self.lbl_ze, self.ze):
            w.setVisible(mode == "enquadrada" and self._slope())
        self.lbl_az0.setText("Azimute da 1ª linha" if mode == "fechada"
                             else "Azimute da ré (linha que chega à 1ª estação)")
        for w in self.end_widgets:
            w.setVisible(mode == "enquadrada")

    def _add_row(self):
        self.table.setRowCount(self.table.rowCount() + 1)

    def _del_row(self):
        r = self.table.currentRow()
        self.table.removeRow(r if r >= 0 else self.table.rowCount() - 1)

    def _clear(self):
        self.table.clearContents()

    def _load_csv(self):
        from qgis.PyQt.QtWidgets import QTableWidgetItem
        from ..core.importer import data_lines, guess_delimiter, read_text_file, split_line
        path, _ = QFileDialog.getOpenFileName(self, "Carregar caderneta", "", "CSV/TXT (*.csv *.txt *.tsv);;Todos (*)")
        if not path:
            return
        try:
            text, _enc = read_text_file(path)
            lines = data_lines(text)
            d = guess_delimiter(lines) or ";"
            rows = [split_line(l, d)[:self.table.columnCount()] for l in lines]
        except OSError as exc:
            self._warn(str(exc))
            return
        if rows and any(c.isalpha() for c in "".join(rows[0][1:])):
            rows = rows[1:]  # cabeçalho
        self.table.clearContents()
        self.table.setRowCount(max(len(rows), 4))
        for i, r in enumerate(rows):
            for j, c in enumerate(r):
                self.table.setItem(i, j, QTableWidgetItem(c))

    def _warn(self, text):
        self.iface.messageBar().pushWarning("TopoLab", text)

    def _read_table(self):
        """(nomes, ângulos, distâncias horizontais, desníveis ou None)."""
        from ..core.angles import parse_angle
        from ..core.importer import to_float
        from ..core.traverse import reduce_observations
        fmt_a, mode, slope = self.cb_fmt.currentData(), self._mode(), self._slope()
        ncol = self.table.columnCount()
        names, angles, dists, rows = [], [], [], []
        zen, hi, hs = [], [], []
        for r in range(self.table.rowCount()):
            cells = [(self.table.item(r, c).text().strip() if self.table.item(r, c) else "")
                     for c in range(ncol)]
            if any(cells[:3]):
                rows.append((r + 1, cells))
        for k, (r, cells) in enumerate(rows):
            nm, ang, dist = cells[:3]
            names.append(nm or f"P{k + 1}")
            try:
                angles.append(parse_angle(ang, fmt_a))
            except ValueError as exc:
                raise ValueError(f"Linha {r}: {exc}")
            last = k == len(rows) - 1
            if dist == "" and mode != "fechada" and last:
                continue
            v = to_float(dist)
            if v is None or v <= 0:
                raise ValueError(f"Linha {r}: distância inválida ({dist!r}).")
            dists.append(v)
            if slope:
                try:
                    zen.append(parse_angle(cells[3], fmt_a))
                except ValueError as exc:
                    raise ValueError(f"Linha {r}: ângulo zenital: {exc}")
                for col, out in ((4, hi), (5, hs)):
                    h = to_float(cells[col]) if cells[col] else 0.0
                    if h is None:
                        raise ValueError(f"Linha {r}: altura inválida ({cells[col]!r}).")
                    out.append(h)
        if not slope:
            return names, angles, dists, None
        try:
            dh, dv = reduce_observations(dists, zen, hi, hs, curvature=self.chk_curv.isChecked())
        except ValueError as exc:
            raise ValueError(str(exc))
        return names, angles, list(dh), list(dv)

    # --- cálculo ---------------------------------------------------------
    def _calculate(self):
        from ..core.angles import parse_angle
        from ..core.traverse import solve_traverse
        from ..core.traverse_report import memorial_text, traverse_report_html
        mode, fmt_a = self._mode(), self.cb_fmt.currentData()
        try:
            names, angles, dists, dv = self._read_table()
            az0 = parse_angle(self.az0.text(), fmt_a)
            kw = {}
            if mode == "enquadrada":
                kw = dict(x_end=self.xe.value(), y_end=self.ye.value(),
                          az_end=parse_angle(self.aze.text(), fmt_a))
            self.result = solve_traverse(
                names, angles, dists, mode, self.x0.value(), self.y0.value(), az0,
                turn=self.cb_turn.currentData(), method=self.cb_method.currentData(),
                ang_tol_per_sqrt_n=self.sp_atol.value() or None,
                min_precision=self.sp_ptol.value() or None, dv=dv, z0=self.z0.value(),
                z_end=self.ze.value() if mode == "enquadrada" and dv is not None else None,
                v_tol_mm_per_sqrt_km=self.sp_vtol.value() or None,
                curvature=self.chk_curv.isChecked(), **kw)
        except ValueError as exc:
            self.iface.messageBar().pushCritical("TopoLab", str(exc))
            return
        self._params = [("Tipo", self.cb_mode.currentText()), ("Sentido do ângulo", self.cb_turn.currentText()),
                        ("Estação inicial (X; Y)", f"{self.x0.value():.3f} ; {self.y0.value():.3f}"),
                        ("Azimute inicial", self.az0.text()),
                        ("Distâncias", self.cb_dist.currentText())]
        if dv is not None:
            self._params.append(("Cota da 1ª estação", f"{self.z0.value():.3f}"))
        title = self.title.text() or "Poligonal"
        self.out.setHtml(traverse_report_html(self.result, title, self._params))
        self.memorial.setPlainText(memorial_text(self.result, f"Memorial descritivo — {title}",
                                                 self.crs.crs().description()))
        for b in (self.btn_csv, self.btn_html, self.btn_layers):
            b.setEnabled(True)
        self.tabs.setCurrentIndex(0)

    # --- saídas ----------------------------------------------------------
    def _export_csv(self):
        from ..core.traverse_report import write_traverse_csv
        path, _ = QFileDialog.getSaveFileName(self, "Exportar caderneta calculada", "poligonal.csv", "CSV (*.csv)")
        if path:
            write_traverse_csv(path, self.result)

    def _export_html(self):
        from ..core.traverse_report import traverse_report_html
        path, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", "poligonal.html", "HTML (*.html)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(traverse_report_html(self.result, self.title.text() or "Poligonal", self._params))

    def _save_memorial(self):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar memorial", "memorial.txt", "Texto (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.memorial.toPlainText())

    def _make_layers(self):
        from qgis.core import (QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject,
                               QgsVectorLayer)
        res, crs = self.result, self.crs.crs()
        uri_crs = "crs=" + (crs.authid() or crs.toWkt())
        lev = res.z is not None
        pts = QgsVectorLayer(f"{'PointZ' if lev else 'Point'}?{uri_crs}", "Poligonal - vértices", "memory")
        pts.dataProvider().addAttributes([QgsField("estacao", TYPE_STRING),
                                          QgsField("x", TYPE_DOUBLE), QgsField("y", TYPE_DOUBLE)]
                                         + ([QgsField("cota", TYPE_DOUBLE)] if lev else []))
        pts.updateFields()
        feats = []
        for i, (nm, x, y) in enumerate(zip(res.names, res.x, res.y)):
            f = QgsFeature(pts.fields())
            if lev:
                from qgis.core import QgsPoint
                f.setGeometry(QgsGeometry(QgsPoint(float(x), float(y), float(res.z[i]))))
                f.setAttributes([nm, float(x), float(y), float(res.z[i])])
            else:
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(x), float(y))))
                f.setAttributes([nm, float(x), float(y)])
            feats.append(f)
        pts.dataProvider().addFeatures(feats)
        ring = [QgsPointXY(float(x), float(y)) for x, y in zip(res.x, res.y)]
        if res.mode == "fechada":
            shape = QgsVectorLayer(f"Polygon?{uri_crs}", "Poligonal - perímetro", "memory")
            geom = QgsGeometry.fromPolygonXY([ring + [ring[0]]])
        else:
            shape = QgsVectorLayer(f"LineString?{uri_crs}", "Poligonal - linha", "memory")
            geom = QgsGeometry.fromPolylineXY(ring)
        shape.dataProvider().addAttributes([
            QgsField("perimetro", TYPE_DOUBLE), QgsField("area", TYPE_DOUBLE),
            QgsField("erro_ang_s", TYPE_DOUBLE), QgsField("erro_lin", TYPE_DOUBLE),
            QgsField("precisao", TYPE_DOUBLE)])
        shape.updateFields()
        f = QgsFeature(shape.fields())
        f.setGeometry(geom)
        area = None if res.area != res.area else float(res.area)
        prec = None if res.rel_precision == float("inf") else float(res.rel_precision)
        f.setAttributes([float(res.perimeter), area, float(res.ang_error_sec),
                         float(res.lin_error), prec])
        shape.dataProvider().addFeatures([f])
        for lyr in (shape, pts):
            lyr.updateExtents()
            QgsProject.instance().addMapLayer(lyr)
        self.iface.messageBar().pushSuccess("TopoLab", "Camadas da poligonal criadas.")


class DxfPage(QWidget):
    """Exporta camadas do projeto para DXF (abre em AutoCAD, BricsCAD, LibreCAD...)."""

    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Camadas vetoriais do projeto a exportar (cada uma vira uma "
                              "camada do DXF com o mesmo nome):"))
        self.layers = QListWidget()
        root.addWidget(self.layers, 1)
        refresh = QPushButton("Atualizar lista")
        refresh.clicked.connect(self._refresh)
        root.addWidget(refresh)

        form = QFormLayout()
        self.z_field = QLineEdit("ELEV")
        self.z_field.setPlaceholderText("ex.: ELEV (curvas), COTA / cota (pontos)")
        self.lbl_field = QLineEdit("ponto")
        self.lbl_field.setPlaceholderText("ex.: ponto, ESTACA (vazio = sem texto)")
        self.text_height = QDoubleSpinBox()
        self.text_height.setDecimals(2)
        self.text_height.setRange(0.01, 1000)
        self.text_height.setValue(1.0)
        form.addRow("Campo da cota (Z)", self.z_field)
        form.addRow("Campo do rótulo (texto ao lado dos pontos)", self.lbl_field)
        form.addRow("Altura do texto (unidades do mapa)", self.text_height)
        root.addLayout(form)
        note = QLabel("Linhas com cota viram polilinhas 3D; pontos viram POINT (com texto, se "
                      "houver rótulo). Formato DXF R12, aceito por praticamente qualquer CAD.")
        note.setWordWrap(True)
        root.addWidget(note)
        run = QPushButton("Exportar DXF...")
        run.clicked.connect(self._export)
        root.addWidget(run)
        self._refresh()

    def showEvent(self, event):
        self._refresh()
        super().showEvent(event)

    def _refresh(self):
        from qgis.core import QgsProject, QgsVectorLayer
        from qgis.PyQt.QtCore import Qt
        checked = {self.layers.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.layers.count())
                   if self.layers.item(i).checkState() == Qt.CheckState.Checked}
        self.layers.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer):
                item = QListWidgetItem(lyr.name())
                item.setData(Qt.ItemDataRole.UserRole, lyr.id())
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if lyr.id() in checked else Qt.CheckState.Unchecked)
                self.layers.addItem(item)

    def _export(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import Qt
        from ..adapters.dxf_export import export_layers_to_dxf
        sel = [QgsProject.instance().mapLayer(self.layers.item(i).data(Qt.ItemDataRole.UserRole))
               for i in range(self.layers.count()) if self.layers.item(i).checkState() == Qt.CheckState.Checked]
        sel = [l for l in sel if l is not None]
        if not sel:
            self.iface.messageBar().pushWarning("TopoLab", "Marque ao menos uma camada.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar DXF", "topolab.dxf", "DXF (*.dxf)")
        if not path:
            return
        try:
            c = export_layers_to_dxf(sel, path, self.z_field.text().strip(),
                                     self.lbl_field.text().strip(), self.text_height.value())
        except Exception as exc:  # noqa: BLE001
            self.iface.messageBar().pushCritical("TopoLab", str(exc))
            return
        self.iface.messageBar().pushSuccess(
            "TopoLab", f"DXF gravado: {c['POINT']} pontos, {c['POLYLINE']} polilinhas, "
                       f"{c['TEXT']} textos.")


def _temp_report():
    fd, path = tempfile.mkstemp(suffix=".html", prefix="topolab_")
    os.close(fd)
    return path


def _style_categorized(layer, field, colors, labels=None):
    """Estilo por categoria (sem contorno nos polígonos). Falha em silêncio: é só estética."""
    try:
        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtGui import QColor
        if labels is None and layer.fields().indexOf("ROTULO") >= 0:
            labels = {}                                    # legenda com o rótulo da classe
            for f in layer.getFeatures():
                labels.setdefault(f[field], f["ROTULO"])
        cats = []
        for value in sorted(layer.uniqueValues(layer.fields().indexOf(field))):
            sym = QgsSymbol.defaultSymbol(layer.geometryType())
            sym.setColor(QColor(colors(value)))
            try:
                sym.symbolLayer(0).setStrokeStyle(Qt.PenStyle.NoPen)
            except Exception:  # noqa: BLE001
                pass
            cats.append(QgsRendererCategory(value, sym, (labels or {}).get(value, str(value))))
        layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))
        layer.triggerRepaint()
    except Exception:  # noqa: BLE001
        pass


def _ramp(colors, t):
    from qgis.PyQt.QtGui import QColor
    t = min(max(t, 0.0), 1.0) * (len(colors) - 1)
    i = min(int(t), len(colors) - 2)
    a, b, f = QColor(colors[i]), QColor(colors[i + 1]), t - i
    return QColor(int(a.red() + f * (b.red() - a.red())), int(a.green() + f * (b.green() - a.green())),
                  int(a.blue() + f * (b.blue() - a.blue()))).name()


class ThematicPage(QWidget):
    """Mapas temáticos do MDT: declividade, elevação, inundação, corte e aterro."""

    KINDS = [("Declividade", "slope"), ("Faixas de elevação", "elev"),
             ("Inundação (área abaixo de uma cota)", "flood"), ("Mancha de corte e aterro", "cutfill")]
    SLOPE_COLORS = ["#1a9641", "#a6d96a", "#ffffbf", "#fdae61", "#d7191c", "#7f0000"]
    ELEV_COLORS = ["#1a9850", "#91cf60", "#d9ef8b", "#fee08b", "#d8b365", "#8c510a", "#ffffff"]

    def __init__(self, iface):
        super().__init__()
        from qgis.PyQt.QtWidgets import QComboBox
        self.iface = iface
        form = QFormLayout(self)
        self.kind = QComboBox()
        for label, key in self.KINDS:
            self.kind.addItem(label, key)
        self.a = _LayerZPicker()
        self.b = _LayerZPicker()
        self.lbl_a, self.lbl_af = QLabel("Camada de pontos"), QLabel("Campo da cota (vazio = Z)")
        self.lbl_b, self.lbl_bf = QLabel("Superfície final (B)"), QLabel("Campo da cota de B")
        self.classes = QLineEdit("3; 8; 20; 45; 75")
        self.lbl_cls = QLabel("Limites das classes (%)")
        self.interval = self._spin(5.0, 0.001, 1e5)
        self.level = self._spin(0.0, -1e6, 1e6)
        self.lbl_int, self.lbl_lvl = QLabel("Altura de cada faixa"), QLabel("Cota do nível d'água")
        self.tol = self._spin(0.05, 0.0, 100.0)
        self.tol.setSuffix(" m")
        self.lbl_tol = QLabel("Tolerância \"sem alteração\"")
        self.tol.setToolTip("Diferenças entre A e B menores que este valor são ruído de medição "
                            "e ficam fora do mapa. Obra de terra: 5 cm; pavimento: 1 a 2 cm.")
        self.chk_dissolve = QCheckBox("Juntar os polígonos de cada classe (mais rápido)")
        self.chk_dissolve.setChecked(True)
        self.chk_dissolve.setToolTip("Desmarcado, gera um polígono por triângulo (no mapa de "
                                     "declividade, com a declividade e a orientação de cada um).")
        self.edge = QDoubleSpinBox()
        self.edge.setRange(0, 1e6)
        self.edge.setSpecialValueText("desligada")
        self.note = QLabel("")
        self.note.setWordWrap(True)
        run = QPushButton("Gerar mapa")
        run.clicked.connect(self._run)
        form.addRow("Mapa", self.kind)
        form.addRow(self.lbl_a, self.a.layer)
        form.addRow(self.lbl_af, self.a.field)
        form.addRow(self.lbl_b, self.b.layer)
        form.addRow(self.lbl_bf, self.b.field)
        form.addRow(self.lbl_cls, self.classes)
        form.addRow(self.lbl_int, self.interval)
        form.addRow(self.lbl_lvl, self.level)
        form.addRow(self.lbl_tol, self.tol)
        form.addRow("Aresta máxima", self.edge)
        form.addRow("", self.chk_dissolve)
        self.tin = TinOptions()
        form.addRow(self.tin)
        self.tin_b = TinOptions("Linhas de quebra e limite do MDT — superfície B (opcional)")
        form.addRow(self.tin_b)
        form.addRow(self.note)
        form.addRow(run)
        self.kind.currentIndexChanged.connect(self._update)
        self._update()

    @staticmethod
    def _spin(value, lo, hi):
        sp = QDoubleSpinBox()
        sp.setDecimals(3)
        sp.setRange(lo, hi)
        sp.setValue(value)
        return sp

    def _update(self):
        k = self.kind.currentData()
        for w in (self.lbl_b, self.b.layer, self.lbl_bf, self.b.field):
            w.setVisible(k == "cutfill")
        for w in (self.lbl_cls, self.classes):
            w.setVisible(k in ("slope", "cutfill"))
        for w in (self.lbl_int, self.interval):
            w.setVisible(k == "elev")
        for w in (self.lbl_lvl, self.level):
            w.setVisible(k == "flood")
        for w in (self.lbl_tol, self.tol):
            w.setVisible(k == "cutfill")
        self.tin.set_title("Linhas de quebra e limite do MDT — superfície A (opcional)"
                           if k == "cutfill" else TinOptions.TITLE)
        self.tin_b.setVisible(k == "cutfill")
        self.lbl_a.setText("Superfície original (A)" if k == "cutfill" else "Camada de pontos")
        if k == "slope":
            self.classes.setText("3; 8; 20; 45; 75")
            self.lbl_cls.setText("Limites das classes (%) — padrão EMBRAPA")
            self.note.setText("Um polígono por classe, com declividade média e áreas. Desmarque "
                              "\"Juntar\" para ter declividade e orientação de cada triângulo.")
        elif k == "cutfill":
            self.classes.setText("-2; -1; -0.5; 0; 0.5; 1; 2")
            self.lbl_cls.setText("Limites das classes de altura (m)")
            self.note.setText("Corte onde A está acima de B; aterro onde está abaixo. Diferenças "
                              "menores que a tolerância ficam fora do mapa.")
        elif k == "flood":
            self.note.setText("Considera toda a área abaixo da cota, sem verificar conexão com o curso "
                              "d'água. Não substitui modelagem hidráulica.")
        else:
            self.note.setText("Faixas limitadas exatamente pelas curvas de nível.")

    def _run(self):
        k = self.kind.currentData()
        la, za = self.a.value()
        if la is None:
            self.iface.messageBar().pushWarning("TopoLab", "Escolha a camada de pontos.")
            return
        base = {"INPUT": la, "Z_FIELD": za, "MAX_EDGE": self.edge.value(), "OUTPUT": "TEMPORARY_OUTPUT",
                "DISSOLVE": self.chk_dissolve.isChecked()}
        base.update(self.tin.params())
        if k == "cutfill":
            base.update(self.tin_b.params("_B"))
        if k == "slope":
            runner.run(self, "topolab:slope_map", {**base, "CLASSES": self.classes.text()},
                       lambda res: self._style(res, "CLASSE", lambda v: self.SLOPE_COLORS[min(int(v), 5)]))
        elif k == "elev":
            def done(res):
                lyr = self._layer(res)
                n = max(len(lyr.uniqueValues(lyr.fields().indexOf("FAIXA"))) - 1, 1) if lyr else 1
                self._style(res, "FAIXA", lambda v: _ramp(self.ELEV_COLORS, int(v) / n))
            runner.run(self, "topolab:elevation_bands", {**base, "INTERVAL": self.interval.value()}, done)
        elif k == "flood":
            def done(res):
                self._style(res, "COTA_NIVEL", lambda v: "#3182bd")
                self.iface.messageBar().pushInfo("TopoLab", "Área abaixo da cota: {:.2f} | volume: {:.2f}".format(
                    res.get("AREA", 0), res.get("VOLUME", 0)))
            runner.run(self, "topolab:flood_map", {**base, "LEVEL": self.level.value()}, done)
        else:
            lb, zb = self.b.value()
            if lb is None:
                self.iface.messageBar().pushWarning("TopoLab", "Escolha a superfície B.")
                return
            runner.run(self, "topolab:cut_fill_map", {
                **base, "INPUT_B": lb, "Z_FIELD_B": zb, "CLASSES": self.classes.text(),
                "TOLERANCE": self.tol.value()}, self._style_cutfill)

    def _layer(self, res):
        from qgis.core import QgsProject
        out = res.get("OUTPUT")
        if isinstance(out, str):
            return QgsProject.instance().mapLayer(out)
        return out

    def _style(self, res, field, colors):
        lyr = self._layer(res)
        if lyr is not None and hasattr(lyr, "fields"):
            _style_categorized(lyr, field, colors)

    def _style_cutfill(self, res):
        lyr = self._layer(res)
        if lyr is None or not hasattr(lyr, "fields"):
            return
        from ..core.thematic import tolerance_edges
        user = {float(p.replace(",", ".")) for p in self.classes.text().replace(";", " ").split()}
        edges, still = tolerance_edges(user, self.tol.value())
        n_fill = still                                     # classes 0..still-1 = aterro
        n_cut = len(edges) - still                         # classes still+1..len(edges) = corte

        def color(v):
            v = int(v)
            if v < still:                                  # azul escuro -> claro até o zero
                return _ramp(["#08519c", "#c6dbef"], v / max(n_fill - 1, 1))
            return _ramp(["#fdd0a2", "#a50f15"], (v - still - 1) / max(n_cut - 1, 1))
        _style_categorized(lyr, "CLASSE", color)


def add_route_layers(iface, names, x, y, closed, crs, base):
    """Cria camadas de vértices e de perímetro/linha (memória) no projeto."""
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
    uri_crs = "crs=" + (crs.authid() or crs.toWkt())
    pts = QgsVectorLayer(f"Point?{uri_crs}", f"{base} - vértices", "memory")
    pts.dataProvider().addAttributes([QgsField("vertice", TYPE_STRING),
                                      QgsField("x", TYPE_DOUBLE), QgsField("y", TYPE_DOUBLE)])
    pts.updateFields()
    feats = []
    for nm, px, py in zip(names, x, y):
        f = QgsFeature(pts.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(px), float(py))))
        f.setAttributes([nm, float(px), float(py)])
        feats.append(f)
    pts.dataProvider().addFeatures(feats)
    ring = [QgsPointXY(float(px), float(py)) for px, py in zip(x, y)]
    if closed:
        shape = QgsVectorLayer(f"Polygon?{uri_crs}", f"{base} - perímetro", "memory")
        geom = QgsGeometry.fromPolygonXY([ring + [ring[0]]])
    else:
        shape = QgsVectorLayer(f"LineString?{uri_crs}", f"{base} - linha", "memory")
        geom = QgsGeometry.fromPolylineXY(ring)
    f = QgsFeature(shape.fields())
    f.setGeometry(geom)
    shape.dataProvider().addFeatures([f])
    for lyr in (shape, pts):
        lyr.updateExtents()
        QgsProject.instance().addMapLayer(lyr)
    iface.messageBar().pushSuccess("TopoLab", "Camadas criadas.")


class MemorialPage(QWidget):
    """Roteiro perimétrico/memorial a partir de uma camada, e restituição de um memorial em texto."""

    def __init__(self, iface):
        super().__init__()
        from qgis.gui import QgsProjectionSelectionWidget
        from qgis.core import QgsProject
        from qgis.PyQt.QtWidgets import QTabWidget, QTextEdit
        self.iface = iface
        self._route = None
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # --- aba 1: camada -> roteiro e memorial
        t1 = QWidget()
        l1 = QVBoxLayout(t1)
        f1 = QFormLayout()
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(LAYER_POLYGON | LAYER_LINE)
        self.chk_sel = QCheckBox("Somente a feição selecionada")
        self.prefix = QLineEdit("P")
        self.title = QLineEdit("Imóvel")
        self.dec = QSpinBox()
        self.dec.setRange(0, 4)
        self.dec.setValue(2)
        f1.addRow("Camada (polígono ou linha)", self.layer)
        f1.addRow("", self.chk_sel)
        f1.addRow("Prefixo dos vértices", self.prefix)
        f1.addRow("Título", self.title)
        f1.addRow("Casas decimais", self.dec)
        l1.addLayout(f1)
        run1 = QPushButton("Gerar roteiro e memorial")
        run1.clicked.connect(self._from_layer)
        l1.addWidget(run1)
        self.roteiro = QTextBrowser()
        self.memorial = QTextEdit()
        inner = QTabWidget()
        inner.addTab(self.roteiro, "Roteiro perimétrico")
        inner.addTab(self.memorial, "Memorial (rascunho)")
        l1.addWidget(inner, 1)
        row = QHBoxLayout()
        b_csv, b_txt = QPushButton("Exportar roteiro (CSV)..."), QPushButton("Salvar memorial (.txt)...")
        b_csv.clicked.connect(self._save_csv)
        b_txt.clicked.connect(self._save_txt)
        row.addWidget(b_csv)
        row.addWidget(b_txt)
        row.addStretch()
        l1.addLayout(row)
        tabs.addTab(t1, "De uma camada")

        # --- aba 2: texto -> geometria
        t2 = QWidget()
        l2 = QVBoxLayout(t2)
        l2.addWidget(QLabel("Cole o texto do memorial (\"...no vértice P1... segue com azimute de ... e "
                            "distância de ... m até o vértice P2...\"):"))
        self.text_in = QTextEdit()
        l2.addWidget(self.text_in, 1)
        f2 = QFormLayout()
        self.chk_start = QCheckBox("Usar as coordenadas iniciais abaixo (se o texto não trouxer)")
        self.e0, self.n0 = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.e0, self.n0):
            sp.setDecimals(3)
            sp.setRange(-1e9, 1e9)
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setCrs(QgsProject.instance().crs())
        f2.addRow(self.chk_start)
        f2.addRow("E (X) inicial", self.e0)
        f2.addRow("N (Y) inicial", self.n0)
        f2.addRow("CRS", self.crs)
        l2.addLayout(f2)
        run2 = QPushButton("Restituir geometria e criar camadas")
        run2.clicked.connect(self._from_text)
        self.out2 = QTextBrowser()
        self.out2.setMaximumHeight(110)
        l2.addWidget(run2)
        l2.addWidget(self.out2)
        tabs.addTab(t2, "Ler memorial")

    # --- aba 1 --------------------------------------------------------
    def _coords(self):
        from qgis.core import QgsFeatureRequest
        lyr = self.layer.currentLayer()
        if lyr is None:
            raise ValueError("Escolha uma camada.")
        if self.chk_sel.isChecked():
            ids = lyr.selectedFeatureIds()
            if not ids:
                raise ValueError("Nenhuma feição selecionada.")
            feats = list(lyr.getFeatures(QgsFeatureRequest().setFilterFids(ids)))
        else:
            feats = list(lyr.getFeatures())
        feats = [f for f in feats if f.geometry() and not f.geometry().isEmpty()]
        if not feats:
            raise ValueError("A camada não tem geometrias.")
        geom = feats[0].geometry()
        closed = geom.type() == GEOM_POLYGON
        if closed:
            rings = geom.asMultiPolygon()[0] if geom.isMultipart() else geom.asPolygon()
            pts = rings[0][:-1]
        else:
            pts = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
        return [p.x() for p in pts], [p.y() for p in pts], closed, lyr.crs(), len(feats)

    def _from_layer(self):
        from ..core.angles import format_dms
        from ..core.route import memorial_from_coords, polygon_area, route_from_coords
        try:
            x, y, closed, crs, nfeat = self._coords()
            if len(x) < 2:
                raise ValueError("A geometria precisa de ao menos 2 vértices.")
        except ValueError as exc:
            self.iface.messageBar().pushWarning("TopoLab", str(exc))
            return
        names = [f"{self.prefix.text()}{i + 1}" for i in range(len(x))]
        az, dist = route_from_coords(x, y, closed)
        d = self.dec.value()
        rows = "".join(
            f"<tr><td>{names[i]}</td><td align=right>{fmt(x[i], d)}</td><td align=right>{fmt(y[i], d)}</td>"
            f"<td align=right>{format_dms(az[i], 0) if i < len(az) else ''}</td>"
            f"<td align=right>{fmt(dist[i], d) if i < len(dist) else ''}</td></tr>" for i in range(len(x)))
        extra = f"Área: {fmt(polygon_area(x, y), 2)} m² | " if closed else ""
        warn = "<p style='color:#c0392b'>CRS geográfico: azimutes e distâncias não fazem sentido em graus. Use CRS projetado.</p>" if crs.isGeographic() else ""
        self.roteiro.setHtml(
            f"{warn}<p>{extra}{'Perímetro' if closed else 'Comprimento'}: {fmt(dist.sum(), 2)} m"
            f"{' (usada a 1ª de ' + str(nfeat) + ' feições)' if nfeat > 1 else ''}</p>"
            "<table border=1 cellpadding=4 style='border-collapse:collapse'>"
            "<tr><th>Vértice</th><th>E (X)</th><th>N (Y)</th><th>Azimute até o próximo</th>"
            f"<th>Distância (m)</th></tr>{rows}</table>")
        self.memorial.setPlainText(memorial_from_coords(names, x, y, closed,
                                                        f"Memorial descritivo — {self.title.text()}",
                                                        crs.description(), d))
        self._route = (names, x, y, closed, az, dist)

    def _save_csv(self):
        if self._route is None:
            return
        import csv
        from ..core.angles import format_dms
        path, _ = QFileDialog.getSaveFileName(self, "Exportar roteiro", "roteiro.csv", "CSV (*.csv)")
        if not path:
            return
        names, x, y, closed, az, dist = self._route
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["VERTICE", "E", "N", "AZIMUTE_PROXIMO", "DISTANCIA_PROXIMO"])
            for i in range(len(x)):
                w.writerow([names[i], f"{x[i]:.3f}".replace(".", ","), f"{y[i]:.3f}".replace(".", ","),
                            format_dms(az[i], 0) if i < len(az) else "",
                            f"{dist[i]:.3f}".replace(".", ",") if i < len(dist) else ""])

    def _save_txt(self):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar memorial", "memorial.txt", "Texto (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.memorial.toPlainText())

    # --- aba 2 --------------------------------------------------------
    def _from_text(self):
        from ..core.route import parse_memorial, polygon_area
        start = (self.e0.value(), self.n0.value()) if self.chk_start.isChecked() else None
        try:
            g = parse_memorial(self.text_in.toPlainText(), start)
        except ValueError as exc:
            self.out2.setHtml(f"<span style='color:#c0392b'>{exc}</span>")
            return
        msg = f"{len(g.names)} vértices, {'polígono fechado' if g.closed else 'linha aberta'}. "
        if g.closed:
            msg += f"Erro de fechamento do texto: {fmt(g.misclosure, 3)} m. Área: {fmt(polygon_area(g.x, g.y), 2)} m². "
        elif g.misclosure:
            msg += f"Maior diferença para as coordenadas citadas: {fmt(g.misclosure, 3)} m. "
        self.out2.setHtml(msg + "<br><small>Confira com o documento original.</small>")
        add_route_layers(self.iface, g.names, g.x, g.y, g.closed, self.crs.crs(), "Memorial")
