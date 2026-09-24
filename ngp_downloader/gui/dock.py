"""Main dock widget: pick auth, dataset, subsets, filters and area, then download."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.gui import QgsAuthConfigSelect, QgsFileWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULT_ENVIRONMENT, ENVIRONMENTS, NGP_CRS, PLUGIN_NAME, SETTINGS_PREFIX, search_base_url
from ..core.auth import authcfg_exists
from ..core.client import NgpClient, NgpError
from ..core.registry import Dataset, load_datasets
from ..core.task import DownloadTask
from .auth_dialog import CreateAuthDialog

AREA_NONE, AREA_EXTENT, AREA_SELECTION = "none", "extent", "selection"


class NgpDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__(PLUGIN_NAME, parent)
        self.iface = iface
        self.settings = QgsSettings()
        self.datasets = load_datasets()
        self.filter_edits: dict[str, QLineEdit] = {}
        self._task: DownloadTask | None = None

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_dataset_group())
        layout.addWidget(self._build_area_group())
        layout.addWidget(self._build_output_group())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setWidget(scroll)

        self._restore_settings()
        self._on_dataset_changed()

    # --- UI construction -------------------------------------------------

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("Anslutning")
        form = QFormLayout(group)

        self.env_combo = QComboBox()
        for env in ENVIRONMENTS.values():
            self.env_combo.addItem(env.label, env.key)
        form.addRow("Miljö", self.env_combo)

        # QGIS' own auth config picker: users can also create/edit configs here.
        self.auth_select = QgsAuthConfigSelect(self)
        form.addRow("Autentisering", self.auth_select)

        new_auth_btn = QPushButton("Ny Lantmäteriet-inloggning…")
        new_auth_btn.clicked.connect(self._create_auth)
        form.addRow("", new_auth_btn)
        return group

    def _build_dataset_group(self) -> QGroupBox:
        group = QGroupBox("Datamängd")
        layout = QVBoxLayout(group)

        self.dataset_combo = QComboBox()
        for ds in self.datasets:
            label = ds.title if ds.verified else f"{ds.title} (ej verifierad)"
            self.dataset_combo.addItem(label, ds.id)
        self.dataset_combo.currentIndexChanged.connect(self._on_dataset_changed)
        layout.addWidget(self.dataset_combo)

        row = QHBoxLayout()
        row.addWidget(QLabel("Delmängder (ingen vald = alla)"))
        load_btn = QPushButton("Hämta lista")
        load_btn.clicked.connect(self._load_collections)
        row.addWidget(load_btn)
        layout.addLayout(row)

        self.collection_filter = QLineEdit()
        self.collection_filter.setPlaceholderText("Filtrera lista…")
        self.collection_filter.textChanged.connect(self._filter_collection_list)
        layout.addWidget(self.collection_filter)

        self.collection_list = QListWidget()
        self.collection_list.setMinimumHeight(120)
        layout.addWidget(self.collection_list)

        self.filter_form = QFormLayout()
        layout.addLayout(self.filter_form)
        return group

    def _build_area_group(self) -> QGroupBox:
        group = QGroupBox("Geografisk avgränsning")
        layout = QVBoxLayout(group)
        self.area_combo = QComboBox()
        self.area_combo.addItem("Ingen", AREA_NONE)
        self.area_combo.addItem("Kartans utsträckning", AREA_EXTENT)
        self.area_combo.addItem("Valda objekt i aktivt lager", AREA_SELECTION)
        layout.addWidget(self.area_combo)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Utdata")
        layout = QVBoxLayout(group)
        self.output_widget = QgsFileWidget()
        self.output_widget.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        layout.addWidget(self.output_widget)

        self.download_btn = QPushButton("Hämta")
        self.download_btn.clicked.connect(self._start_download)
        layout.addWidget(self.download_btn)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return group

    # --- settings --------------------------------------------------------

    def _key(self, name: str) -> str:
        return f"{SETTINGS_PREFIX}/{name}"

    def _restore_settings(self) -> None:
        env = self.settings.value(self._key("environment"), DEFAULT_ENVIRONMENT)
        self.env_combo.setCurrentIndex(max(0, self.env_combo.findData(env)))
        self.auth_select.setConfigId(self.settings.value(self._key("authcfg"), ""))
        ds = self.settings.value(self._key("dataset"), self.datasets[0].id)
        self.dataset_combo.setCurrentIndex(max(0, self.dataset_combo.findData(ds)))
        self.output_widget.setFilePath(
            self.settings.value(self._key("output_dir"), str(Path.home() / "NGP"))
        )

    def _save_settings(self) -> None:
        self.settings.setValue(self._key("environment"), self.env_combo.currentData())
        self.settings.setValue(self._key("authcfg"), self.auth_select.configId())
        self.settings.setValue(self._key("dataset"), self.dataset_combo.currentData())
        self.settings.setValue(self._key("output_dir"), self.output_widget.filePath())

    # --- helpers ---------------------------------------------------------

    def _dataset(self) -> Dataset:
        ds_id = self.dataset_combo.currentData()
        return next(d for d in self.datasets if d.id == ds_id)

    def _base_url(self) -> str:
        ds = self._dataset()
        return search_base_url(self.env_combo.currentData(), ds.id, ds.version)

    def _authcfg_or_warn(self) -> str | None:
        authcfg = self.auth_select.configId()
        if not authcfg_exists(authcfg):
            self._message("Välj eller skapa en autentisering först.", Qgis.MessageLevel.Warning)
            return None
        return authcfg

    def _message(self, text: str, level=Qgis.MessageLevel.Info) -> None:
        self.status_label.setText(text)
        self.iface.messageBar().pushMessage(PLUGIN_NAME, text, level, 8)

    # --- slots -----------------------------------------------------------

    def _create_auth(self) -> None:
        dlg = CreateAuthDialog(self, self.env_combo.currentData())
        if dlg.exec() and dlg.authcfg:
            self.auth_select.setConfigId(dlg.authcfg)
            self._save_settings()

    def _on_dataset_changed(self) -> None:
        self.collection_list.clear()
        while self.filter_form.rowCount():
            self.filter_form.removeRow(0)
        self.filter_edits.clear()

        for f in self._dataset().filters:
            edit = QLineEdit()
            hint = ", ".join(f.suggestions) if f.suggestions else "kommaseparerade värden"
            edit.setPlaceholderText(hint)
            self.filter_form.addRow(f.label, edit)
            self.filter_edits[f.property] = edit

    def _load_collections(self) -> None:
        authcfg = self._authcfg_or_warn()
        if not authcfg:
            return
        self._save_settings()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            collections = NgpClient(self._base_url(), authcfg).collections()
        except NgpError as e:
            self._message(f"Kunde inte hämta delmängder (HTTP {e.status}): {e}", Qgis.MessageLevel.Critical)
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.collection_list.clear()
        for c in sorted(collections, key=lambda c: c.get("title") or c.get("id", "")):
            item = QListWidgetItem(f"{c.get('title') or c['id']} ({c['id']})")
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.collection_list.addItem(item)
        self._message(f"{len(collections)} delmängder hämtade.")

    def _filter_collection_list(self, text: str) -> None:
        text = text.lower()
        for i in range(self.collection_list.count()):
            item = self.collection_list.item(i)
            item.setHidden(text not in item.text().lower())

    def _search_body(self) -> dict | None:
        body: dict = {}

        collections = [
            self.collection_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.collection_list.count())
            if self.collection_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        if collections:
            body["collections"] = collections

        query = {}
        for f in self._dataset().filters:
            values = [v.strip() for v in self.filter_edits[f.property].text().split(",") if v.strip()]
            if values:
                query[f.property] = {"in": values} if f.operator == "in" else {f.operator: values[0]}
        if query:
            body["query"] = query

        area = self.area_combo.currentData()
        if area == AREA_NONE:
            return body

        target_crs = QgsCoordinateReferenceSystem(NGP_CRS)
        if area == AREA_EXTENT:
            canvas = self.iface.mapCanvas()
            transform = QgsCoordinateTransform(
                canvas.mapSettings().destinationCrs(), target_crs, QgsProject.instance()
            )
            rect = transform.transformBoundingBox(canvas.extent())
            body["bbox"] = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
        else:
            layer = self.iface.activeLayer()
            if not isinstance(layer, QgsVectorLayer) or layer.selectedFeatureCount() == 0:
                self._message("Markera minst ett objekt i det aktiva lagret.", Qgis.MessageLevel.Warning)
                return None
            geom = QgsGeometry.unaryUnion([f.geometry() for f in layer.selectedFeatures()])
            geom.transform(QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance()))
            body["intersects"] = json.loads(geom.asJson(3))
        return body

    def _start_download(self) -> None:
        if self._task is not None:
            self._message("En hämtning pågår redan.", Qgis.MessageLevel.Warning)
            return
        authcfg = self._authcfg_or_warn()
        if not authcfg:
            return
        body = self._search_body()
        if body is None:
            return
        if not self.output_widget.filePath():
            self._message("Välj en utdatamapp.", Qgis.MessageLevel.Warning)
            return
        self._save_settings()

        layer_name = f"{self._dataset().id}_{datetime.now():%Y%m%d_%H%M%S}"
        task = DownloadTask(
            self._base_url(), authcfg, body, Path(self.output_widget.filePath()), layer_name
        )
        task.completed.connect(self._on_completed)
        task.failed.connect(self._on_failed)
        task.taskCompleted.connect(self._clear_task)
        task.taskTerminated.connect(self._clear_task)
        self._task = task
        self.download_btn.setEnabled(False)
        self.status_label.setText("Hämtar… (följ förloppet i aktivitetshanteraren)")
        QgsApplication.taskManager().addTask(task)

    def _clear_task(self) -> None:
        self._task = None
        self.download_btn.setEnabled(True)

    def _on_completed(self, gpkg_path: str, layer_name: str, count: int) -> None:
        uri = f"{gpkg_path}|layername={layer_name}"
        layer = QgsVectorLayer(uri, layer_name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
        self._message(f"{count} objekt sparade i {gpkg_path}", Qgis.MessageLevel.Success)

    def _on_failed(self, error: str) -> None:
        self._message(f"Hämtningen misslyckades: {error}", Qgis.MessageLevel.Critical)
