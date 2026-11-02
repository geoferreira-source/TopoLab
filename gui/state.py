"""Parâmetros das telas do TopoLab: coleta, restaura e grava no projeto do QGIS ou em arquivo.

Os campos são achados pelos nomes dos atributos das páginas (ex.: ``VolumesPage.a.layer``),
que são estáveis entre versões. Só entradas são guardadas; resultados (relatórios, gráficos)
não. Camadas são guardadas por id e nome: no mesmo projeto, valem pelo id; em outro (arquivo
.topolab), pela camada de mesmo nome.
"""
import json

from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import (
    QAbstractButton, QComboBox, QDoubleSpinBox, QGroupBox, QLineEdit, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextBrowser, QTextEdit, QWidget,
)

FORMAT, VERSION = "topolab", 1
SCOPE, KEY = "TopoLab", "state"
SKIP = {"iface", "out", "out2", "roteiro", "summary", "view", "canvas", "memorial", "layers",
        "result", "steps", "stack"}
TEXT_INPUTS = {"text_in"}   # QTextEdit que são entrada (os demais são resultado)

# ordem de restauração: camadas antes dos campos; combos antes dos textos (trocar o tipo de
# mapa reescreve os limites de classe, por exemplo)
ORDER = ["layer", "field", "crs", "combo", "check", "number", "text", "table"]


def _kind(w):
    if isinstance(w, QgsMapLayerComboBox):
        return "layer"
    if isinstance(w, QgsFieldComboBox):
        return "field"
    if isinstance(w, QgsProjectionSelectionWidget):
        return "crs"
    if isinstance(w, QComboBox):
        return "combo"
    if isinstance(w, QAbstractButton) and w.isCheckable():
        return "check"
    if isinstance(w, QGroupBox) and w.isCheckable():
        return "check"
    if isinstance(w, (QDoubleSpinBox, QSpinBox)):
        return "number"
    if isinstance(w, QLineEdit):
        return "text"
    if isinstance(w, QTableWidget):
        return "table"
    return None


def _walk(obj, prefix, depth=0):
    """(chave, widget) de todos os campos de entrada de uma página."""
    if depth > 3:
        return
    for name, val in vars(obj).items():
        if name.startswith("_") or name in SKIP:
            continue
        key = f"{prefix}.{name}"
        if isinstance(val, QTextEdit) and not isinstance(val, QTextBrowser):
            if name in TEXT_INPUTS:
                yield key, val, "text"
            continue
        if isinstance(val, QWidget) and _kind(val):
            yield key, val, _kind(val)
            if isinstance(val, QGroupBox):
                continue
        if hasattr(val, "__dict__") and not isinstance(val, (list, dict, tuple, str)) \
                and type(val).__module__.startswith(__package__.rsplit(".", 1)[0]):
            yield from _walk(val, key, depth + 1)   # _LayerZPicker, TinOptions...


def fields(window):
    out = []
    for i in range(window.stack.count()):
        page = window.stack.widget(i)
        out += list(_walk(page, type(page).__name__))
    return out


def _get(w, kind):
    if kind == "layer":
        lyr = w.currentLayer()
        return None if lyr is None else {"id": lyr.id(), "name": lyr.name()}
    if kind == "field":
        return w.currentField()
    if kind == "crs":
        crs = w.crs()
        return crs.authid() or crs.toWkt()
    if kind == "combo":
        data = w.currentData()
        return {"data": data} if isinstance(data, (str, int, float, bool)) else {"text": w.currentText()}
    if kind == "check":
        return bool(w.isChecked())
    if kind == "number":
        return w.value()
    if kind == "text":
        return w.toPlainText() if isinstance(w, QTextEdit) else w.text()
    if kind == "table":
        return [[(w.item(r, c).text() if w.item(r, c) else "") for c in range(w.columnCount())]
                for r in range(w.rowCount())]


def _find_layer(ref):
    proj = QgsProject.instance()
    lyr = proj.mapLayer(ref.get("id", ""))
    if lyr is None:
        same = proj.mapLayersByName(ref.get("name", ""))
        lyr = same[0] if same else None
    return lyr


def _set(w, kind, value, missing):
    if kind == "layer":
        if value is None:
            w.setLayer(None)
            return
        lyr = _find_layer(value)
        if lyr is None:
            missing.add(value.get("name", "?"))
        else:
            w.setLayer(lyr)
    elif kind == "field":
        w.setField(value or "")
    elif kind == "crs":
        crs = QgsCoordinateReferenceSystem(value)
        if crs.isValid():
            w.setCrs(crs)
    elif kind == "combo":
        i = w.findData(value["data"]) if "data" in value else w.findText(value.get("text", ""))
        if i >= 0:
            w.setCurrentIndex(i)
    elif kind == "check":
        if isinstance(w, QAbstractButton) and w.autoExclusive() and not value:
            return  # em grupo exclusivo basta marcar o escolhido
        w.setChecked(bool(value))
    elif kind == "number":
        w.setValue(value)
    elif kind == "text":
        if isinstance(w, QTextEdit):
            w.setPlainText(value)
        else:
            w.setText(value)
    elif kind == "table":
        w.clearContents()
        w.setRowCount(max(len(value), 1))
        for r, row in enumerate(value):
            for c, text in enumerate(row[:w.columnCount()]):
                if text:
                    w.setItem(r, c, QTableWidgetItem(text))


def collect(window):
    """Dicionário serializável com os parâmetros de todas as telas."""
    values = {key: _get(w, kind) for key, w, kind in fields(window)}
    return {"format": FORMAT, "version": VERSION, "step": window.steps.currentRow(), "values": values}


def apply(window, state):
    """Restaura os parâmetros. Retorna os nomes das camadas que não foram encontradas."""
    if not isinstance(state, dict) or state.get("format") != FORMAT:
        raise ValueError("Não é um arquivo de parâmetros do TopoLab.")
    values, missing = state.get("values", {}), set()
    known = {key: (w, kind) for key, w, kind in fields(window)}
    window._restoring = True
    try:
        for kind in ORDER:
            for key, value in values.items():
                if key in known and known[key][1] == kind:
                    try:
                        _set(known[key][0], kind, value, missing)
                    except Exception:  # noqa: BLE001 - um campo ruim não impede os demais
                        pass
        if isinstance(state.get("step"), int) and state["step"] >= 0:
            window.steps.setCurrentRow(state["step"])
    finally:
        window._restoring = False
    return sorted(missing)


def dumps(window):
    return json.dumps(collect(window), ensure_ascii=False, indent=1)


def loads(window, text):
    try:
        state = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"Arquivo de parâmetros inválido: {exc}")
    return apply(window, state)


def write_to_project(window, project=None):
    (project or QgsProject.instance()).writeEntry(SCOPE, KEY, dumps(window))


def read_from_project(window, project=None):
    """Restaura o que estiver salvo no projeto. Retorna (havia estado, camadas não achadas)."""
    text, ok = (project or QgsProject.instance()).readEntry(SCOPE, KEY, "")
    if not ok or not text:
        return False, []
    return True, loads(window, text)


# combos: só a escolha do usuário (`activated`); a lista de camadas muda sozinha quando o
# QGIS carrega um projeto, e isso não deve marcar o projeto como modificado
SIGNALS = {"layer": "activated", "field": "activated", "crs": "crsChanged",
           "combo": "activated", "check": "toggled", "number": "valueChanged",
           "text": "textEdited", "table": "cellChanged"}


def watch(window, callback):
    """Chama `callback()` quando o usuário muda qualquer parâmetro (fora da restauração)."""
    def changed(*_):
        if not getattr(window, "_restoring", False):
            callback()
    for _, w, kind in fields(window):
        name = "textChanged" if isinstance(w, QTextEdit) else SIGNALS[kind]
        sig = getattr(w, name, None)
        if sig is not None:
            sig.connect(changed)
