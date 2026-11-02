"""Assistente de importação de DXF de levantamento: papel de cada camada do CAD."""
import os

from qgis.core import QgsProject
from qgis.gui import QgsFileWidget, QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

ROLES = [("Ignorar", "ignorar"), ("Pontos", "pontos"), ("Textos de cota", "cotas"),
         ("Linhas (curvas, quebras)", "linhas"), ("Limite (polígono)", "limite")]


class ImportDxfDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface, self.drawing, self.path = iface, None, ""
        self.setWindowTitle("Importar DXF de levantamento")
        self.resize(760, 560)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.file = QgsFileWidget()
        self.file.setFilter("DXF (*.dxf *.DXF)")
        self.file.fileChanged.connect(self._load)
        form.addRow("Arquivo DXF", self.file)
        root.addLayout(form)
        root.addWidget(QLabel("Camadas do desenho e o papel de cada uma (sugerido pelo conteúdo e pelo nome):"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Camada do CAD", "Conteúdo", "Usar como"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        opts = QFormLayout()
        self.radius = QDoubleSpinBox()
        self.radius.setDecimals(2)
        self.radius.setRange(0.01, 1000)
        self.radius.setValue(2.0)
        self.chk_texts = QCheckBox("Textos de cota sem ponto próximo viram pontos")
        self.chk_texts.setChecked(True)
        self.chk_vertices = QCheckBox("Vértices das linhas com cota (curvas de nível) viram pontos cotados")
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setCrs(QgsProject.instance().crs())
        self.prefix = QLineEdit()
        opts.addRow("Distância máxima ponto–texto de cota", self.radius)
        opts.addRow("", self.chk_texts)
        opts.addRow("", self.chk_vertices)
        opts.addRow("CRS do desenho", self.crs)
        opts.addRow("Prefixo das camadas", self.prefix)
        root.addLayout(opts)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        btns = QHBoxLayout()
        self.btn_import = QPushButton("Importar")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._import)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        btns.addStretch()
        btns.addWidget(self.btn_import)
        btns.addWidget(close)
        root.addLayout(btns)

    def _load(self, path):
        from ..core.dxf_read import describe_layer, guess_roles, read_dxf
        if not path:
            return
        try:
            self.drawing = read_dxf(path)
        except (OSError, ValueError) as exc:
            self.drawing = None
            self.status.setText(f"Não foi possível ler o DXF: {exc}")
            self.btn_import.setEnabled(False)
            return
        self.path = path
        self.prefix.setText(os.path.splitext(os.path.basename(path))[0])
        layers, roles = self.drawing.layers(), guess_roles(self.drawing)
        self.table.setRowCount(len(layers))
        for r, (name, cnt) in enumerate(layers.items()):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(describe_layer(cnt)))
            cb = QComboBox()
            for label, key in ROLES:
                cb.addItem(label, key)
            cb.setCurrentIndex(cb.findData(roles.get(name, "ignorar")))
            self.table.setCellWidget(r, 2, cb)
        msg = f"{len(self.drawing.entities)} entidades em {len(layers)} camadas (codificação {self.drawing.encoding})."
        if self.drawing.unsupported:
            msg += " Não importadas: " + ", ".join(f"{n} {k}" for k, n in self.drawing.unsupported.items()) + "."
        self.status.setText(msg)
        self.btn_import.setEnabled(bool(layers))

    def roles(self):
        return {self.table.item(r, 0).text(): self.table.cellWidget(r, 2).currentData()
                for r in range(self.table.rowCount())}

    def _import(self):
        from ..adapters.dxf_import import survey_layers
        from ..core.dxf_read import build_survey
        if self.drawing is None:
            return
        sv = build_survey(self.drawing, self.roles(), self.radius.value(), self.chk_texts.isChecked(),
                          self.chk_vertices.isChecked())
        layers = survey_layers(sv, self.crs.crs(), self.prefix.text() or "DXF")
        if not layers:
            self.status.setText("Nada a importar: escolha o papel de ao menos uma camada.")
            return
        for lyr in layers:
            QgsProject.instance().addMapLayer(lyr)
        st = sv.stats
        msg = (f"Importados: {st['pontos'] - st['sem_cota']} pontos cotados (cota da geometria: "
               f"{st['cota_geometria']}, de atributo: {st['cota_atributo']}, de texto: {st['cota_texto']}, "
               f"textos sem ponto: {st['textos_sem_ponto']}), {st['linhas']} linhas, {st['poligonos']} polígonos.")
        if st["sem_cota"]:
            msg += (f" {st['sem_cota']} ponto(s) ficaram sem cota (camada 'pontos sem cota'): aumente a "
                    "distância ponto–texto ou confira a camada de textos.")
        self.status.setText(msg)
        self.iface.messageBar().pushSuccess("TopoLab", f"DXF importado: {len(layers)} camada(s).")
