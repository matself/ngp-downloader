"""Loads the dataset register (datasets.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
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
    label: str = ""  # layer name in the layer tree, e.g. "Användning"


@dataclass(frozen=True)
class Dataset:
    id: str
    title: str
    version: str
    verified: bool = False
    # "ngp" (Geodatakatalog STAC API) or "raa" (Riksantikvarieämbetet's file downloads).
    source: str = "ngp"
    spec: str = ""
    filters: tuple[DatasetFilter, ...] = field(default_factory=tuple)
    # Listed bottom to top: the order layers are drawn in.
    layer_types: tuple[LayerType, ...] = ()
    # Plural name for the layer group, e.g. "Detaljplaner"; falls back to the title.
    group_label: str = ""


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
                source=d.get("source", "ngp"),
                spec=d.get("spec", ""),
                filters=filters,
                layer_types=tuple(
                    LayerType(t["typ"], t["name"], t.get("hidden", False), t.get("label", ""))
                    for t in d.get("layer_types", [])
                ),
                group_label=d.get("group_label", ""),
            )
        )
    return datasets


MAX_NAMED_AREAS = 2


def group_name(dataset: Dataset, areas: list[str], fallback_area: str, when: datetime) -> str:
    """E.g. "Detaljplaner Kristianstads kommun 2026-11-10".

    `areas` are the names of the chosen subsets (kommuner); with none chosen,
    `fallback_area` describes the search instead (e.g. "kartutsnitt").
    """
    if not areas:
        area = fallback_area
    elif len(areas) <= MAX_NAMED_AREAS:
        area = " och ".join(areas)
    else:
        area = f"{len(areas)} kommuner"
    return " ".join(part for part in (dataset.group_label or dataset.title, area, f"{when:%Y-%m-%d}") if part)


def layer_label(dataset: Dataset, suffix: str) -> str | None:
    """Layer tree name for a layer with this suffix, e.g. "egenskap_yta" -> "Egenskap yta".

    None when there is no suffix (a dataset with one layer, named after the group).
    """
    if not suffix:
        return None
    labels = {t.name: t.label for t in dataset.layer_types if t.label}
    type_part, _, geometry = suffix.partition("_")
    if type_part in labels:
        return f"{labels[type_part]} {geometry}".strip()
    # No type label: a bare geometry suffix ("yta") or an unlabelled type.
    return suffix.replace("_", " ").capitalize()
