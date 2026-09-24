"""Turns STAC reference objects into flat GeoPackage layers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from osgeo import gdal

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


# A GPKG layer holds one geometry type, so mixed datasets (e.g. Kulturhistorisk
# lämning) are split into one layer per family. Single/multi share a layer.
GEOMETRY_GROUPS = {
    "Point": "punkt",
    "MultiPoint": "punkt",
    "LineString": "linje",
    "MultiLineString": "linje",
    "Polygon": "yta",
    "MultiPolygon": "yta",
}


def split_by_geometry(features: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        geom_type = (feature.get("geometry") or {}).get("type")
        key = GEOMETRY_GROUPS.get(geom_type, "ovrigt" if geom_type else "utan_geometri")
        groups.setdefault(key, []).append(feature)
    return groups


def write_gpkg(features: list[dict[str, Any]], gpkg_path: Path, layer_name: str) -> list[str]:
    """Write features to GeoPackage, one layer per geometry family.

    Returns the layer names written. A single-type result keeps `layer_name`
    as is; mixed results get suffixes like `_punkt`, `_linje`, `_yta`.
    """
    groups = split_by_geometry(features)
    names = []
    with tempfile.TemporaryDirectory() as tmp:
        for suffix, group in groups.items():
            name = layer_name if len(groups) == 1 else f"{layer_name}_{suffix}"
            geojson_path = Path(tmp) / f"{name}.geojson"
            write_geojson(group, geojson_path)
            geojson_to_gpkg(geojson_path, gpkg_path, name)
            names.append(name)
    return names


def geojson_to_gpkg(geojson_path: Path, gpkg_path: Path, layer_name: str) -> None:
    # GDAL directly rather than QgsVectorFileWriter: QGIS' OGR connection pool
    # keeps the source open, which blocks deleting the temp file on Windows.
    with gdal.ExceptionMgr(useExceptions=True):
        try:
            ds = gdal.VectorTranslate(
                str(gpkg_path),
                str(geojson_path),
                format="GPKG",
                accessMode="overwrite" if gpkg_path.exists() else None,
                layerName=layer_name,
                geometryType="PROMOTE_TO_MULTI",
            )
            ds = None  # noqa: F841 — closes and flushes the GeoPackage
        except RuntimeError as e:
            raise RuntimeError(f"Kunde inte skriva GeoPackage: {e}") from e
