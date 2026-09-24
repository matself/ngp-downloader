"""Background task: search a dataset and save the hits as GeoPackage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.core import Qgis, QgsFeedback, QgsMessageLog, QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from ..config import PLUGIN_NAME
from .client import NgpClient, NgpError
from .export import item_to_feature, write_geojson, write_gpkg
from .planbestammelser import enrich, load_catalog, merge_combinations, needs_catalog

PAGE_LIMIT = 1000  # API max is 10000; smaller pages give smoother progress.
# Search filters that objects without geometry can never meet.
UNMATCHABLE_FILTERS = ("query", "bbox", "intersects")


class DownloadTask(QgsTask):
    # Emitted in the main thread via QgsTask.finished → safe for UI work.
    completed = pyqtSignal(str, list, int)  # gpkg path, layer names, feature count
    failed = pyqtSignal(str)

    def __init__(
        self,
        base_url: str,
        authcfg: str,
        search_body: dict[str, Any],
        output_dir: Path,
        layer_name: str,
        type_names: dict[str, str] | None = None,
    ):
        super().__init__(f"NGP: hämtar {layer_name}", QgsTask.Flag.CanCancel)
        self.base_url = base_url
        self.authcfg = authcfg
        self.search_body = {**search_body, "limit": PAGE_LIMIT}
        self.output_dir = output_dir
        self.layer_name = layer_name
        self.type_names = type_names or {}
        self.gpkg_path = output_dir / f"{layer_name}.gpkg"
        self.feature_count = 0
        self.layer_names: list[str] = []
        self.error: str | None = None
        self._feedback = QgsFeedback()

    def cancel(self) -> None:
        # Aborts an in-flight network request, not just the next page.
        self._feedback.cancel()
        super().cancel()

    def run(self) -> bool:
        client = NgpClient(self.base_url, self.authcfg, self._feedback)
        self._log(f"POST {self.base_url}/search {self.search_body}")

        features = []
        try:
            for page in client.search(self.search_body):
                if self.isCanceled():
                    return False
                features.extend(item_to_feature(i) for i in page.get("features", []))
                matched = page.get("numberMatched") or page.get("context", {}).get("matched")
                if matched:
                    self.setProgress(min(99.0, 100.0 * len(features) / matched))
                self._log(f"{len(features)} objekt hämtade")
        except NgpError as e:
            self.error = e.describe()
            return False

        if any(key in self.search_body for key in UNMATCHABLE_FILTERS):
            # Objects without geometry (e.g. Strandskydd decisions) lack the filtered
            # attributes and location, so the API returns all of them regardless.
            with_geometry = [f for f in features if f["geometry"]]
            dropped = len(features) - len(with_geometry)
            if dropped:
                self._log(f"{dropped} objekt utan geometri borttagna – filtret kan inte tillämpas på dem")
            features = with_geometry

        if not features:
            self.error = "Sökningen gav inga träffar."
            return False

        if needs_catalog(features):
            try:
                catalog = load_catalog(self._feedback)
                matched = enrich(features, catalog)
                self._log(f"Beteckning och färg från Boverkets planbestämmelsekatalog "
                          f"({catalog.get('release')}): {matched} objekt")
            except Exception as e:  # noqa: BLE001 — the data is still useful without it
                self._log(f"Planbestämmelsekatalogen kunde inte användas: {e}", Qgis.MessageLevel.Warning)
            before = len(features)
            features = merge_combinations(features)
            if len(features) < before:
                self._log(f"Kombinationer av användningar sammanslagna: {before} → {len(features)} objekt")

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            geojson_path = self.output_dir / f"{self.layer_name}.geojson"
            write_geojson(features, geojson_path)
            self.layer_names = write_gpkg(features, self.gpkg_path, self.layer_name, self.type_names)
        except Exception as e:  # noqa: BLE001 — report any write failure to the UI
            self.error = str(e)
            return False

        self.feature_count = len(features)
        return True

    def finished(self, result: bool) -> None:
        if result:
            self.completed.emit(str(self.gpkg_path), self.layer_names, self.feature_count)
        elif not self.isCanceled():
            self._log(self.error or "Okänt fel", Qgis.MessageLevel.Critical)
            self.failed.emit(self.error or "Okänt fel")

    def _log(self, message: str, level=Qgis.MessageLevel.Info) -> None:
        QgsMessageLog.logMessage(message, PLUGIN_NAME, level)
