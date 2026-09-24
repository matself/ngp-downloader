"""Loads the dataset register (datasets.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "datasets.json"


@dataclass(frozen=True)
class DatasetFilter:
    property: str
    label: str
    operator: str = "in"
    suggestions: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayerType:
    """How objects of one `feature:typ` become a layer: short name, visibility."""

    typ: str
    name: str
    hidden: bool = False


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    version: str
    verified: bool = False
    spec: str = ""
    filters: tuple[DatasetFilter, ...] = field(default_factory=tuple)
    # Listed bottom to top: the order layers are drawn in.
    layer_types: tuple[LayerType, ...] = ()


def load_datasets(path: Path = REGISTRY_PATH) -> list[Dataset]:
    data = json.loads(path.read_text(encoding="utf-8"))
    datasets = []
    for d in data["datasets"]:
        filters = tuple(
            DatasetFilter(
                property=f["property"],
                label=f.get("label", f["property"]),
                operator=f.get("operator", "in"),
                suggestions=tuple(f.get("suggestions", [])),
            )
            for f in d.get("filters", [])
        )
        datasets.append(
            Dataset(
                id=d["id"],
                title=d.get("title", d["id"]),
                version=d.get("version", "v1"),
                verified=d.get("verified", False),
                spec=d.get("spec", ""),
                filters=filters,
                layer_types=tuple(
                    LayerType(t["typ"], t["name"], t.get("hidden", False))
                    for t in d.get("layer_types", [])
                ),
            )
        )
    return datasets
