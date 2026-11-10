from __future__ import annotations

from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

try:  # Qt6 / QGIS 4
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 / QGIS 3
    from qgis.PyQt.QtWidgets import QAction

from .config import PLUGIN_NAME


class NgpDownloaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action: QAction | None = None
        self.dock = None
        self.viewer_action: QAction | None = None
        self.viewer_dock = None

    def initGui(self) -> None:
        icon = QIcon(str(Path(__file__).resolve().parent / "icon.svg"))
        self.action = QAction(icon, PLUGIN_NAME, self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.toggled.connect(self._toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.action)

        self.viewer_action = QAction(
            QgsApplication.getThemeIcon("/mActionIdentify.svg"), "Planvisare", self.iface.mainWindow()
        )
        self.viewer_action.setCheckable(True)
        self.viewer_action.toggled.connect(self._toggle_viewer)
        self.iface.addToolBarIcon(self.viewer_action)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.viewer_action)

    def unload(self) -> None:
        if self.viewer_dock:
            self.viewer_dock.cleanup()
            self.iface.removeDockWidget(self.viewer_dock)
            self.viewer_dock.deleteLater()
            self.viewer_dock = None
        if self.viewer_action:
            self.iface.removeToolBarIcon(self.viewer_action)
            self.iface.removePluginMenu(PLUGIN_NAME, self.viewer_action)
            self.viewer_action = None
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu(PLUGIN_NAME, self.action)
            self.action = None

    def _toggle_viewer(self, checked: bool) -> None:
        if self.viewer_dock is None:
            from .gui.planvisare import PlanvisareDock

            self.viewer_dock = PlanvisareDock(self.iface, self.iface.mainWindow())
            self.viewer_dock.visibilityChanged.connect(self.viewer_action.setChecked)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.viewer_dock)
        self.viewer_dock.setVisible(checked)

    def _toggle_dock(self, checked: bool) -> None:
        if self.dock is None:
            from .gui.dock import NgpDock

            self.dock = NgpDock(self.iface, self.iface.mainWindow())
            self.dock.visibilityChanged.connect(self.action.setChecked)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.setVisible(checked)
