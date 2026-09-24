"""Turns STAC reference objects into flat GeoPackage layers."""

from __future__ import annotations

import json
import re
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


# Polygons first so that lines and points end up drawn on top of them.
GEOMETRY_ORDER = ("yta", "linje", "punkt", "ovrigt", "utan_geometri")
TYPE_FIELD = "feature_typ"


def _slug(text: str) -> str:
    text = text.lower().translate(str.maketrans("åäöé", "aaoe"))
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "ovrigt"


def plan_layers(
    features: list[dict[str, Any]], layer_name: str, type_names: dict[str, str] | None = None
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Split features into layers per object type, then per geometry family.

    Returns (layer name, features) bottom to top: types in `type_names` order
    first, then others as found. Suffixes are only added where needed, so a
    dataset with one type and one geometry keeps `layer_name` as is.
    """
    type_names = type_names or {}
    by_type: dict[Any, list[dict[str, Any]]] = {}
    for feature in features:
        by_type.setdefault(feature["properties"].get(TYPE_FIELD), []).append(feature)
    types = [t for t in type_names if t in by_type] + [t for t in by_type if t not in type_names]

    layers = []
    for typ in types:
        base = layer_name
        if len(by_type) > 1:
            base += "_" + (type_names.get(typ) or _slug(str(typ or "ovrigt")))
        groups = split_by_geometry(by_type[typ])
        for suffix in sorted(groups, key=GEOMETRY_ORDER.index):
            name = base if len(groups) == 1 else f"{base}_{suffix}"
            layers.append((name, groups[suffix]))
    return layers


def write_gpkg(
    features: list[dict[str, Any]],
    gpkg_path: Path,
    layer_name: str,
    type_names: dict[str, str] | None = None,
) -> list[str]:
    """Write features to GeoPackage, one layer per object type and geometry family.

    Returns the layer names written, bottom to top.
    """
    names = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, group in plan_layers(features, layer_name, type_names):
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
