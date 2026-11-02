"""Janela principal independente do TopoLab (fora do painel do QGIS)."""
from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog, QFileDialog, QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout,
)

from ..compat import QAction
from ..resources import guide_path, icon_path
from . import state
from .pages import (
    ContoursPage, DxfPage, MemorialPage, PointsPage, ProfilePage, ThematicPage, TraversePage,
    VolumesPage,
)

STEPS = ["1. Pontos", "2. Superfície e curvas", "3. Volumes",
         "4. Perfis e seções", "5. Poligonal e memorial", "6. Mapas temáticos", "7. Roteiro e memorial",
         "8. Exportar DXF"]


class TopoLabWindow(QMainWindow):
    def __init__(self, iface, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.iface = iface
        self.setObjectName("TopoLabWindow")
        self.setWindowTitle("TopoLab - Topografia")
        self.setWindowIcon(QIcon(icon_path()))
        self.resize(900, 600)

        self.steps = QListWidget()
        self.steps.addItems(STEPS)
        self.steps.setMaximumWidth(190)
        self.stack = QStackedWidget()
        self.stack.addWidget(PointsPage(iface))
        self.stack.addWidget(ContoursPage(iface))
        self.stack.addWidget(VolumesPage(iface))
        self.stack.addWidget(ProfilePage(iface))
        self.stack.addWidget(TraversePage(iface))
        self.stack.addWidget(ThematicPage(iface))
        self.stack.addWidget(MemorialPage(iface))
        self.stack.addWidget(DxfPage(iface))
        self.steps.currentRowChanged.connect(self._goto)
        self.steps.setCurrentRow(0)

        split = QSplitter()
        split.addWidget(self.steps)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self._build_menus()
        # progresso dos cálculos em segundo plano (ver gui/runner.py)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setRange(0, 100)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self._cancel_task)
        for w in (self.progress, self.btn_cancel):
            self.statusBar().addPermanentWidget(w)
            w.hide()
        self.statusBar().showMessage("Pronto.")
        self._restoring = False
        # parâmetros fazem parte do projeto: mudar um deles marca o projeto como modificado
        state.watch(self, lambda: QgsProject.instance().setDirty(True))

    def restore_from_project(self):
        """Aplica os parâmetros salvos no projeto do QGIS (se houver)."""
        try:
            found, missing = state.read_from_project(self)
        except ValueError:
            return
        if found:
            self._report_missing(missing, "Parâmetros do TopoLab restaurados do projeto.")

    def _report_missing(self, missing, ok_text):
        bar = self.iface.messageBar()
        if missing:
            bar.pushWarning("TopoLab", "Camada(s) não encontrada(s) no projeto: " + ", ".join(missing)
                            + ". Escolha-as de novo nas telas.")
        else:
            bar.pushInfo("TopoLab", ok_text)

    def _save_params(self):
        path, _ = QFileDialog.getSaveFileName(self, "Salvar parâmetros do TopoLab", "parametros.topolab",
                                              "Parâmetros do TopoLab (*.topolab);;Todos (*)")
        if not path:
            return
        if not path.lower().endswith(".topolab"):
            path += ".topolab"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(state.dumps(self))
        self.statusBar().showMessage(f"Parâmetros salvos em {path}")

    def _open_params(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir parâmetros do TopoLab", "",
                                              "Parâmetros do TopoLab (*.topolab);;Todos (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                missing = state.loads(self, fh.read())
        except (OSError, ValueError) as exc:
            self.iface.messageBar().pushCritical("TopoLab", str(exc))
            return
        QgsProject.instance().setDirty(True)
        self._report_missing(missing, "Parâmetros carregados.")

    # ------------------------------------------------------------------ tarefas
    def task_started(self, title, feedback):
        self.stack.setEnabled(False)          # evita mudar parâmetros ou disparar outro cálculo
        self.progress.setValue(0)
        self.progress.show()
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.show()
        self.statusBar().showMessage(f"Calculando: {title}... (o QGIS continua disponível)")
        feedback.progressChanged.connect(lambda v: self.progress.setValue(int(v)))

    def task_finished(self):
        self.stack.setEnabled(True)
        self.progress.hide()
        self.btn_cancel.hide()
        self.statusBar().showMessage("Pronto.")

    def _cancel_task(self):
        from . import runner
        runner.cancel()
        self.btn_cancel.setEnabled(False)
        self.statusBar().showMessage("Cancelando...")

    def _goto(self, row):
        self.stack.setCurrentIndex(row)
        self.statusBar().showMessage(STEPS[row] if row >= 0 else "")

    def _build_menus(self):
        bar = self.menuBar()
        m_file = bar.addMenu("&Arquivo")
        act_open = QAction("Abrir parâmetros...", self)
        act_open.triggered.connect(self._open_params)
        act_save = QAction("Salvar parâmetros como...", self)
        act_save.triggered.connect(self._save_params)
        m_file.addAction(act_open)
        m_file.addAction(act_save)
        m_file.addSeparator()
        act_close = QAction("Fechar janela", self)
        act_close.setShortcut("Ctrl+W")
        act_close.triggered.connect(self.close)
        m_file.addAction(act_close)

        m_tools = bar.addMenu("&Ferramentas")
        for row, text in ((1, "Curvas de nível"), (2, "Volumes"), (3, "Perfis e seções"),
                          (4, "Poligonal e memorial"),
                          (5, "Mapas temáticos"), (6, "Roteiro e memorial"),
                          (7, "Exportar DXF")):
            act = QAction(text, self)
            act.triggered.connect(lambda _=False, r=row: self.steps.setCurrentRow(r))
            m_tools.addAction(act)

        m_help = bar.addMenu("A&juda")
        act_guide = QAction("Guia rápido", self)
        act_guide.setShortcut("F1")
        act_guide.triggered.connect(self._guide)
        m_help.addAction(act_guide)
        act_about = QAction("Sobre o TopoLab", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

        tb = self.addToolBar("Etapas")
        tb.setMovable(False)
        for row, text in enumerate(("Pontos", "Curvas", "Volumes", "Perfis", "Poligonal", "Mapas", "Memorial", "DXF")):
            act = QAction(text, self)
            act.triggered.connect(lambda _=False, r=row: self.steps.setCurrentRow(r))
            tb.addAction(act)

    def _guide(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Guia rápido do TopoLab")
        dlg.resize(620, 520)
        lay = QVBoxLayout(dlg)
        view = QTextBrowser()
        with open(guide_path(), encoding="utf-8") as fh:
            view.setHtml(fh.read())
        lay.addWidget(view)
        dlg.exec()

    def _about(self):
        QMessageBox.about(
            self, "Sobre o TopoLab",
            "TopoLab 0.16.0 (experimental)\n\nTIN, curvas de nível, volumes (com recorte por polígono), platô com taludes, perfil, seções transversais e poligonais com memorial descritivo, MDE raster, mapas temáticos, verificação de pontos e exportação DXF.\n"
            "Confira os resultados antes de uso profissional.")

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()
