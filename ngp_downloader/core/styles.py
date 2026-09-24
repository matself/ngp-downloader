"""QML styles per dataset and layer (styles/{dataset}_{layer suffix}.qml, e.g. detaljplan_anvandning.qml).

Falls back to styles/{dataset}_{yta|linje|punkt}.qml by geometry type.
"""

from __future__ import annotations

from pathlib import Path

from qgis.core import Qgis, QgsMapLayer, QgsVectorLayer

STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"
SUFFIXES = {
    Qgis.GeometryType.Point: "punkt",
    Qgis.GeometryType.Line: "linje",
    Qgis.GeometryType.Polygon: "yta",
}
# Only symbology and labels: the rest of the QML (fields, forms) belongs to the data.
CATEGORIES = QgsMapLayer.StyleCategory.Symbology | QgsMapLayer.StyleCategory.Labeling


def find_style(dataset_id: str, layer_suffix: str, geometry_type) -> Path | None:
    """Most specific existing style: {dataset}_{suffix}, with or without a
    geometry part (a type only gets one when it has several geometries), then
    {dataset}_{geometry}."""
    geom = SUFFIXES.get(geometry_type)
    base = layer_suffix
    if geom and base.endswith(f"_{geom}"):
        base = base[: -len(geom) - 1]
    candidates = [f"{dataset_id}_{layer_suffix}" if layer_suffix else dataset_id]
    if base and geom:
        candidates += [f"{dataset_id}_{base}_{geom}", f"{dataset_id}_{base}"]
    if geom:
        candidates.append(f"{dataset_id}_{geom}")
    return next((STYLES_DIR / f"{c}.qml" for c in candidates if (STYLES_DIR / f"{c}.qml").exists()), None)


def apply_style(layer: QgsVectorLayer, dataset_id: str, layer_suffix: str = "") -> bool:
    """Apply the dataset's style if there is one, and store it as default in the GeoPackage."""
    path = find_style(dataset_id, layer_suffix, layer.geometryType())
    if path is None:
        return False
    _message, ok = layer.loadNamedStyle(str(path), CATEGORIES)
    if ok:
        # Default style in the GeoPackage's layer_styles table: the file opens
        # styled in any QGIS, also without this plugin.
        if hasattr(layer, "saveStyleToDatabaseV2"):  # QGIS >= 3.40
            layer.saveStyleToDatabaseV2(dataset_id, "NGP nedladdning", True, "", CATEGORIES)
        else:
            layer.saveStyleToDatabase(dataset_id, "NGP nedladdning", True, "", CATEGORIES)
        layer.triggerRepaint()
    return ok
