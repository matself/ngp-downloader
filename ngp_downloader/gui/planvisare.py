"""Planvisare: a detachable dock that shows the detaljplan provisions at a clicked point."""

from __future__ import annotations

import tempfile
from pathlib import Path

from qgis.core import Qgis, QgsApplication, QgsGeometry, QgsSettings
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QPalette
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..config import PLUGIN_NAME, SETTINGS_PREFIX
from ..core.auth import authcfg_exists
from ..core.planvy import Identification, PlanInfo, documents_dir, identify, load_detail, render_html
from ..core.resources import ResourceTask, is_downloadable

HIGHLIGHT_COLOR = "#e64a19"
LINK_COLOR = "#3d85c6"
START_TEXT = "Klicka i kartan för att se vilka planbestämmelser som gäller på platsen."


class PlanvisareDock(QDockWidget):
    """Floatable, so the text can be pulled out of the QGIS window onto another screen."""

    def __init__(self, iface, parent=None):
        super().__init__("Planvisare", parent)
        self.setObjectName("NgpPlanvisareDock")
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self._result: Identification | None = None
        self._tasks: list[ResourceTask] = []

        self.tool = QgsMapToolEmitPoint(self.canvas)
        self.tool.canvasClicked.connect(self._on_click)
        self.canvas.mapToolSet.connect(self._on_map_tool_set)

        self.rubber = QgsRubberBand(self.canvas, Qgis.GeometryType.Polygon)
        self.rubber.setStrokeColor(QColor(HIGHLIGHT_COLOR))
        self.rubber.setFillColor(QColor(0, 0, 0, 0))
        self.rubber.setWidth(3)

        body = QWidget()
        layout = QVBoxLayout(body)
        top = QHBoxLayout()
        self.pick_btn = QPushButton("Välj plats i kartan")
        self.pick_btn.setCheckable(True)
        self.pick_btn.toggled.connect(self._toggle_tool)
        top.addWidget(self.pick_btn)
        self.show_all = QCheckBox("Visa alla bestämmelser i planen")
        self.show_all.toggled.connect(self._render)
        top.addWidget(self.show_all)
        top.addStretch()
        layout.addLayout(top)

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._on_link)
        layout.addWidget(self.browser)
        self.setWidget(body)
        self._show_text(START_TEXT)

    # --- map tool ---------------------------------------------------------

    def activate_tool(self) -> None:
        self.canvas.setMapTool(self.tool)

    def release_tool(self) -> None:
        if self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
        self.rubber.reset(Qgis.GeometryType.Polygon)

    def _toggle_tool(self, checked: bool) -> None:
        if checked:
            self.activate_tool()
        else:
            self.release_tool()

    def _on_map_tool_set(self, new_tool, _old_tool) -> None:
        self.pick_btn.blockSignals(True)
        self.pick_btn.setChecked(new_tool is self.tool)
        self.pick_btn.blockSignals(False)

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        self.activate_tool()

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().hideEvent(event)
        self.release_tool()

    def cleanup(self) -> None:
        """Called when the plugin unloads."""
        self.release_tool()
        try:
            self.canvas.mapToolSet.disconnect(self._on_map_tool_set)
        except (TypeError, RuntimeError):
            pass
        self.canvas.scene().removeItem(self.rubber)

    # --- result -----------------------------------------------------------

    def _on_click(self, point, _button) -> None:
        crs = self.canvas.mapSettings().destinationCrs()
        self._result = identify(point, crs, crs)
        self.rubber.reset(Qgis.GeometryType.Polygon)
        if self._result.highlight:
            self.rubber.setToGeometry(QgsGeometry.collectGeometry(self._result.highlight), None)
        self._render()
        for plan in self._result.plans:
            if plan.domain is not None and plan.detail is None:
                self._fetch_detail(plan, self._result)

    def _fetch_detail(self, plan: PlanInfo, result: Identification) -> None:
        """Fetch the plan's domain object in the background; the flat view stays until it arrives."""
        authcfg = QgsSettings().value(f"{SETTINGS_PREFIX}/authcfg", "")
        if not authcfg_exists(authcfg):
            return
        task = ResourceTask(authcfg, [plan.domain], self._documents_dir(plan))
        task.completed.connect(lambda paths, _failures, p=plan, r=result: self._on_detail(p, r, paths))
        task.taskCompleted.connect(lambda t=task: self._tasks.remove(t) if t in self._tasks else None)
        self._tasks.append(task)
        QgsApplication.taskManager().addTask(task)

    def _on_detail(self, plan: PlanInfo, result: Identification, paths: dict) -> None:
        path = paths.get(plan.domain.href)
        if not path or result is not self._result:  # failed, or the user has clicked elsewhere since
            return
        plan.detail = load_detail(path)
        if plan.detail:
            self._render()

    def _colors(self) -> dict[str, str]:
        palette = self.browser.palette()
        text = palette.color(QPalette.ColorRole.Text)
        base = palette.color(QPalette.ColorRole.Base)
        muted = QColor(
            (text.red() + base.red()) // 2, (text.green() + base.green()) // 2, (text.blue() + base.blue()) // 2
        )
        return {
            "text": text.name(),
            "muted": muted.name(),
            "border": muted.name(),
            "accent": LINK_COLOR,  # the palette's link colour is grey in some styles
        }

    def _render(self, *_args) -> None:
        if self._result is None:
            self._show_text(START_TEXT)
            return
        self.browser.setHtml(render_html(self._result, self.show_all.isChecked(), self._colors()))

    def _show_text(self, text: str) -> None:
        self.browser.setPlainText(text)

    # --- documents --------------------------------------------------------

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() != "doc" or self._result is None:
            return
        try:
            plan_index, doc_index = (int(n) for n in url.path().split(":"))
            plan = self._result.plans[plan_index]
            document = plan.documents[doc_index]
        except (ValueError, IndexError):
            return
        if not is_downloadable(document.href):  # an ordinary web page
            QDesktopServices.openUrl(QUrl(document.href))
            return
        authcfg = QgsSettings().value(f"{SETTINGS_PREFIX}/authcfg", "")
        if not authcfg_exists(authcfg):
            self._message(
                "Välj en autentisering i NGP-panelen först, så kan dokumentet hämtas.",
                Qgis.MessageLevel.Warning,
            )
            return
        task = ResourceTask(authcfg, [document], self._documents_dir(plan))
        task.completed.connect(lambda paths, failures, d=document: self._on_document(d, paths, failures))
        task.failed.connect(lambda error: self._message(f"Kunde inte hämta dokumentet: {error}", Qgis.MessageLevel.Critical))
        task.taskCompleted.connect(lambda t=task: self._tasks.remove(t) if t in self._tasks else None)
        self._tasks.append(task)  # keep a reference while the task runs
        QgsApplication.taskManager().addTask(task)
        self._message(f"Hämtar {document.title}…")

    @staticmethod
    def _documents_dir(plan: PlanInfo) -> Path:
        """Next to the GeoPackage, like the plugin's other resource downloads."""
        return documents_dir(plan, Path(tempfile.gettempdir()) / "ngp_planvisare")

    def _on_document(self, document, paths: dict, failures: list) -> None:
        path = paths.get(document.href)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self._message(f"Kunde inte hämta {document.title}: {'; '.join(failures)}", Qgis.MessageLevel.Warning)

    def _message(self, text: str, level=Qgis.MessageLevel.Info) -> None:
        self.iface.messageBar().pushMessage(PLUGIN_NAME, text, level, 8)
