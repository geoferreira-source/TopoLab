"""Assistente de importação de pontos (CSV/TXT) para uma camada do QGIS."""
from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPoint, QgsProject, QgsVectorLayer
from qgis.gui import QgsFileWidget, QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..core.importer import PRESETS, ROLES, parse_points, preview_rows, read_text_file
from ..compat import TYPE_DOUBLE, TYPE_STRING

DELIMS = [("Automático", None), ("Ponto e vírgula ;", ";"), ("Tabulação", "\t"),
          ("Vírgula ,", ","), ("Espaço", " ")]
DECIMALS = [("Automático", None), ("Ponto (1234.56)", "."), ("Vírgula (1234,56)", ",")]
HEADERS = [("Automático", None), ("Sim", True), ("Não", False)]


def _combo(options):
    cb = QComboBox()
    for label, value in options:
        cb.addItem(label, value)
    return cb


class ImportPointsDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.text = ""
        self.setWindowTitle("Importar pontos (CSV/TXT)")
        self.resize(780, 560)
        root = QVBoxLayout(self)

        self.file = QgsFileWidget()
        self.file.setFilter("Pontos (*.csv *.txt *.xyz *.pts *.dat *.prn);;Todos (*)")
        self.file.fileChanged.connect(self._load)
        form = QFormLayout()
        form.addRow("Arquivo", self.file)
        self.cb_delim, self.cb_dec = _combo(DELIMS), _combo(DECIMALS)
        self.cb_header = _combo(HEADERS)
        row = QHBoxLayout()
        for label, cb in (("Separador", self.cb_delim), ("Decimal", self.cb_dec),
                          ("Cabeçalho", self.cb_header)):
            row.addWidget(QLabel(label))
            row.addWidget(cb)
        row.addStretch()
        form.addRow(row)
        for cb in (self.cb_delim, self.cb_dec, self.cb_header):
            cb.currentIndexChanged.connect(self._refresh)
        self.cb_preset = QComboBox()
        self.cb_preset.addItems(list(PRESETS))
        self.cb_preset.currentIndexChanged.connect(self._apply_preset)
        form.addRow("Ordem das colunas", self.cb_preset)
        root.addLayout(form)

        self.roles_row = QHBoxLayout()
        root.addWidget(QLabel("Papel de cada coluna (ajuste se necessário):"))
        root.addLayout(self.roles_row)
        self.role_boxes = []
        self.table = QTableWidget()
        root.addWidget(self.table, 1)

        opts = QFormLayout()
        self.crs = QgsProjectionSelectionWidget()
        self.crs.setCrs(QgsProject.instance().crs())
        self.name = QLineEdit("Pontos importados")
        opts.addRow("CRS dos pontos", self.crs)
        opts.addRow("Nome da camada", self.name)
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

    # ------------------------------------------------------------------
    def _load(self, path):
        if not path:
            return
        try:
            self.text, enc = read_text_file(path)
        except OSError as exc:
            self.status.setText(f"Não foi possível ler o arquivo: {exc}")
            return
        base = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        self.name.setText(base)
        self.status.setText(f"Codificação detectada: {enc}.")
        self._refresh()

    def _refresh(self):
        if not self.text:
            return
        delim, rows = preview_rows(self.text, self.cb_delim.currentData(), 15)
        ncols = max((len(r) for r in rows), default=0)
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(ncols)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                self.table.setItem(i, j, QTableWidgetItem(v))
        if len(self.role_boxes) != ncols:
            for cb in self.role_boxes:
                cb.deleteLater()
            self.role_boxes = []
            for _ in range(ncols):
                cb = QComboBox()
                for key, label in ROLES.items():
                    cb.addItem(label, key)
                self.roles_row.addWidget(cb)
                self.role_boxes.append(cb)
            self._apply_preset()
        self.btn_import.setEnabled(ncols >= 3)

    def _apply_preset(self):
        preset = PRESETS[self.cb_preset.currentText()]
        for j, cb in enumerate(self.role_boxes):
            role = preset[j] if j < len(preset) else "skip"
            cb.setCurrentIndex(cb.findData(role))

    def _import(self):
        roles = [cb.currentData() for cb in self.role_boxes]
        try:
            res = parse_points(self.text, roles, self.cb_delim.currentData(),
                               self.cb_dec.currentData(), self.cb_header.currentData())
        except ValueError as exc:
            self.status.setText(f"Erro: {exc}")
            return
        crs = self.crs.crs()
        layer = QgsVectorLayer("PointZ?crs=" + (crs.authid() or crs.toWkt()),
                               self.name.text() or "Pontos importados", "memory")
        prov = layer.dataProvider()
        prov.addAttributes([QgsField("ponto", TYPE_STRING),
                            QgsField("cota", TYPE_DOUBLE), QgsField("desc", TYPE_STRING)])
        layer.updateFields()
        feats = []
        for pid, (x, y, z), d in zip(res.ids, res.xyz, res.desc):
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry(QgsPoint(float(x), float(y), float(z))))
            f.setAttributes([pid, float(z), d])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        msg = (f"{len(feats)} pontos importados (separador "
               f"{'TAB' if res.delimiter == chr(9) else repr(res.delimiter)}, decimal "
               f"'{res.decimal}'{', com cabeçalho' if res.header else ''}).")
        if res.n_skipped:
            ex = "; ".join(f"linha {k}: {t[:40]}" for k, t in res.skipped[:3])
            msg += f" {res.n_skipped} linha(s) ignorada(s), ex.: {ex}"
        self.status.setText(msg)
        self.iface.messageBar().pushSuccess("TopoLab", f"{len(feats)} pontos importados.")
