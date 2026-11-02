from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtGui import QIcon

from .compat import QAction
from .gui.window import TopoLabWindow
from .processing.provider import TopoLabProvider
from .resources import icon_path


class TopoLabPlugin:
    MENU = "&TopoLab"

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.window = None
        self.action = None
        self.toolbar = None

    def initGui(self):
        self.provider = TopoLabProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        # Janela independente, criada sob demanda (não é um painel do QGIS).
        self.action = QAction(QIcon(icon_path()), "Abrir TopoLab", self.iface.mainWindow())
        self.action.triggered.connect(self.open_window)
        self.iface.addPluginToMenu(self.MENU, self.action)
        self.toolbar = self.iface.addToolBar("TopoLab")
        self.toolbar.setObjectName("TopoLabToolbar")
        self.toolbar.addAction(self.action)
        # parâmetros das telas gravados junto com o projeto do QGIS
        QgsProject.instance().writeProject.connect(self._write_state)
        QgsProject.instance().readProject.connect(self._read_state)

    def _write_state(self, _doc=None):
        if self.window is not None:
            from .gui import state
            state.write_to_project(self.window)

    def _read_state(self, _doc=None):
        if self.window is not None:
            self.window.restore_from_project()

    def open_window(self):
        if self.window is None:
            self.window = TopoLabWindow(self.iface, self.iface.mainWindow())
            self.window.restore_from_project()
        self.window.show_window()

    def unload(self):
        try:  # um cálculo em segundo plano não deve sobreviver ao plugin
            from .gui import runner
            runner.cancel()
        except Exception:  # noqa: BLE001
            pass
        for sig, slot in ((QgsProject.instance().writeProject, self._write_state),
                          (QgsProject.instance().readProject, self._read_state)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        if self.action:
            self.iface.removePluginMenu(self.MENU, self.action)
        if self.toolbar:
            del self.toolbar
        if self.window:
            self.window.close()
            self.window.deleteLater()
            self.window = None
