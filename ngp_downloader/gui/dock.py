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
    QgsEditorWidgetSetup,
    QgsFeatureRequest,
    QgsField,
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
from ..core.resources import ResourceTask, is_downloadable, parse_assets
from ..core.task import DownloadTask
from .auth_dialog import CreateAuthDialog
from .resource_dialog import ResourceDialog

AREA_NONE, AREA_EXTENT, AREA_SELECTION = "none", "extent", "selection"

try:  # QGIS >= 3.38
    from qgis.PyQt.QtCore import QMetaType

    _STRING_FIELD_TYPE = QMetaType.Type.QString
except (ImportError, AttributeError):  # older QGIS 3 uses QVariant types
    from qgis.PyQt.QtCore import QVariant

    _STRING_FIELD_TYPE = QVariant.String


class NgpDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__(PLUGIN_NAME, parent)
        self.iface = iface
        self.settings = QgsSettings()
        self.datasets = load_datasets()
        self.filter_edits: dict[str, QLineEdit] = {}
        self._task: DownloadTask | None = None
        self._resource_task: ResourceTask | None = None

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_dataset_group())
        layout.addWidget(self._build_area_group())
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_resource_group())
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

    def _build_resource_group(self) -> QGroupBox:
        group = QGroupBox("Resurser")
        layout = QVBoxLayout(group)
        hint = QLabel(
            "Domänobjekt och dokument (t.ex. plankarta, beslut) för objekten i det "
            "aktiva lagret. Markera objekt först för att bara hämta för dem."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.resource_btn = QPushButton("Hämta resurser för aktivt lager…")
        self.resource_btn.clicked.connect(self._start_resources)
        layout.addWidget(self.resource_btn)
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
            self._message(f"Kunde inte hämta delmängder – {e.describe()}", Qgis.MessageLevel.Critical)
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.collection_list.clear()
        labelled = [(self._collection_label(c), c) for c in collections]
        for label, c in sorted(labelled, key=lambda lc: lc[0].lower()):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.collection_list.addItem(item)
        self._message(f"{len(collections)} delmängder hämtade.")

    @staticmethod
    def _collection_label(collection: dict) -> str:
        """E.g. "Bodens kommun (2582)": many collections are titled with just their code."""
        cid = collection["id"]
        title = collection.get("title") or cid
        if title == cid:
            providers = [p.get("name") for p in collection.get("providers", []) if p.get("name")]
            title = providers[0] if providers else cid
        return title if title == cid else f"{title} ({cid})"

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

    def _on_completed(self, gpkg_path: str, layer_names: list, count: int) -> None:
        for layer_name in layer_names:
            uri = f"{gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
        self._message(f"{count} objekt sparade i {gpkg_path}", Qgis.MessageLevel.Success)

    def _on_failed(self, error: str) -> None:
        self._message(f"Hämtningen misslyckades: {error}", Qgis.MessageLevel.Critical)

    # --- resources -------------------------------------------------------

    def _start_resources(self) -> None:
        if self._resource_task is not None:
            self._message("En resurshämtning pågår redan.", Qgis.MessageLevel.Warning)
            return
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer) or "assets" not in layer.fields().names():
            self._message("Välj ett lager hämtat med NGP nedladdning.", Qgis.MessageLevel.Warning)
            return
        authcfg = self._authcfg_or_warn()
        if not authcfg:
            return

        dlg = ResourceDialog(layer, self)
        if not dlg.exec():
            return
        roles = set(dlg.roles())

        request = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
        request.setSubsetOfAttributes(["assets"], layer.fields())
        ids = dlg.feature_ids()
        if ids is not None:
            request.setFilterFids(ids)
        # feature id -> {role: [href, ...]}, and the unique resources to fetch
        links: dict[int, dict[str, list[str]]] = {}
        resources = {}
        for feature in layer.getFeatures(request):
            for r in parse_assets(feature["assets"]):
                if r.role in roles and is_downloadable(r.href):
                    links.setdefault(feature.id(), {}).setdefault(r.role, []).append(r.href)
                    resources.setdefault(r.href, r)

        gpkg = Path(layer.dataProvider().dataSourceUri().split("|")[0])
        target_dir = gpkg.parent / f"{gpkg.stem}_resurser"
        task = ResourceTask(authcfg, list(resources.values()), target_dir)
        layer_id = layer.id()
        task.completed.connect(
            lambda paths, failures: self._on_resources_completed(layer_id, links, paths, failures, target_dir)
        )
        task.failed.connect(
            lambda error: self._message(f"Resurshämtningen misslyckades: {error}", Qgis.MessageLevel.Critical)
        )
        task.taskCompleted.connect(self._clear_resource_task)
        task.taskTerminated.connect(self._clear_resource_task)
        self._resource_task = task
        self.resource_btn.setEnabled(False)
        self.status_label.setText(f"Hämtar {len(resources)} resurser… (följ förloppet i aktivitetshanteraren)")
        QgsApplication.taskManager().addTask(task)

    def _clear_resource_task(self) -> None:
        self._resource_task = None
        self.resource_btn.setEnabled(True)

    def _on_resources_completed(self, layer_id, links, paths, failures, target_dir) -> None:
        """Write local file paths to one `resurs_<roll>` column per role."""
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:  # removed while downloading; files are still saved
            self._message(f"{len(paths)} resurser i {target_dir}", Qgis.MessageLevel.Success)
            return
        provider = layer.dataProvider()
        roles = sorted({role for per_role in links.values() for role in per_role})
        missing = [QgsField(f"resurs_{role}", _STRING_FIELD_TYPE) for role in roles
                   if layer.fields().indexOf(f"resurs_{role}") < 0]
        if missing:
            provider.addAttributes(missing)
            layer.updateFields()

        changes: dict[int, dict[int, str]] = {}
        for fid, per_role in links.items():
            for role, hrefs in per_role.items():
                files = [paths[h] for h in hrefs if h in paths]
                if files:
                    changes.setdefault(fid, {})[layer.fields().indexOf(f"resurs_{role}")] = "; ".join(files)
        provider.changeAttributeValues(changes)
        layer.reload()

        # Clickable paths in the attribute form.
        for role in roles:
            layer.setEditorWidgetSetup(
                layer.fields().indexOf(f"resurs_{role}"),
                QgsEditorWidgetSetup("ExternalResource", {"UseLink": True, "FullUrl": True}),
            )

        text = f"{len(paths)} resurser i {target_dir}"
        if failures:
            text += f" – {len(failures)} misslyckades (se loggen)"
        self._message(text, Qgis.MessageLevel.Warning if failures else Qgis.MessageLevel.Success)
