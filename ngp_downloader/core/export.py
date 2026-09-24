"""Turns STAC reference objects into a flat GeoPackage layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from ..config import NGP_CRS


def flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts to `a_b` columns; lists become JSON strings."""
    out: dict[str, Any] = {}
    for key, value in obj.items():
        name = f"{prefix}{key}".replace(".", "_")
        if isinstance(value, dict):
            out.update(flatten(value, f"{name}_"))
        elif isinstance(value, list):
            out[name] = json.dumps(value, ensure_ascii=False)
        else:
            out[name] = value
    return out


def item_to_feature(item: dict[str, Any]) -> dict[str, Any]:
    props = {"ngp_id": item.get("id"), "ngp_collection": item.get("collection")}
    props.update(flatten(item.get("properties", {})))
    # Keep asset links for later download of domain objects / documents.
    props["assets"] = json.dumps(item.get("assets", {}), ensure_ascii=False)
    return {"type": "Feature", "geometry": item.get("geometry"), "properties": props}


def write_geojson(features: list[dict[str, Any]], path: Path) -> None:
    """Write features as GeoJSON with an explicit CRS member.

    GDAL assumes WGS 84 for GeoJSON unless told otherwise; NGP data is in
    SWEREF 99 TM, so the legacy `crs` member is required here.
    """
    epsg = NGP_CRS.split(":")[1]
    fc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{epsg}"}},
        "features": features,
    }
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")


def geojson_to_gpkg(geojson_path: Path, gpkg_path: Path, layer_name: str) -> None:
    source = QgsVectorLayer(str(geojson_path), layer_name, "ogr")
    if not source.isValid():
        raise RuntimeError(f"Kunde inte läsa {geojson_path}")

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer_name
    options.fileEncoding = "UTF-8"
    if gpkg_path.exists():
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        source, str(gpkg_path), QgsCoordinateTransformContext(), options
    )
    error, message = result[0], result[1]
    if error != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(f"Kunde inte skriva GeoPackage: {message}")
