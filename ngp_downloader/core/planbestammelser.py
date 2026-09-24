"""Beteckning and colour from Boverket's planbestämmelsekatalog.

Detaljplan reference objects carry the UUID of their provision in Boverket's
catalogue (planbestammelsekatalogreferens). The catalogue gives the notation
(B, C, GATA, …), colour name (Gul, Brun, …) and map symbol (e.g. Prickmark)
per Boverkets allmänna råd BFS 2020:6. It is open data, fetched from Boverket and cached in the QGIS
profile rather than bundled. Source: Boverket, Planbestämmelsekatalogen.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from qgis.core import QgsApplication, QgsBlockingNetworkRequest, QgsFeedback
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..config import SETTINGS_PREFIX

CATALOG_URL = "https://api.boverket.se/planbestammelsekatalogen/release/full/platt/aktuell"
MAX_AGE_SECONDS = 30 * 24 * 3600
REF_FIELD = "planbestammelse_planbestammelsekatalogreferens"
BETECKNING_FIELD = "planbestammelse_beteckning"
FARG_FIELD = "planbestammelse_farg"
# Name of the plan map symbol, e.g. "Prickmark (1949 - 2020)", for notations drawn as rasters.
SYMBOL_FIELD = "planbestammelse_symbol"
# Map label: the notation, or for value symbols (heights etc.) a short value like "nh 9".
ETIKETT_FIELD = "planbestammelse_etikett"
VALUE_FIELD = "planbestammelse_bestammelsevarde_variabelvarde"
FORMULERING_FIELD = "planbestammelse_bestammelseformulering"
# Catalogue symbol name prefix -> (label prefix, suffix) for value symbols.
VALUE_SYMBOLS = {
    "Högsta nockhöjd": ("nh ", ""),
    "Högsta totalhöjd": ("th ", ""),
    "Högsta byggnadshöjd": ("bh ", ""),
    "Takvinkel": ("", "°"),
}
CACHE_FORMAT = 2  # bump when the cached entry layout changes


def cache_path() -> Path:
    return Path(QgsApplication.qgisSettingsDirPath()) / SETTINGS_PREFIX / "planbestammelsekatalog.json"


def clean_beteckning(value: str | None) -> str | None:
    """'B#' -> 'B'. Placeholders like '[beteckning:text]' have no fixed notation."""
    if not value or "[" in value:
        return None
    return re.sub(r"[#$]", "", value).strip() or None


def _download(feedback: QgsFeedback | None) -> dict[str, Any]:
    blocking = QgsBlockingNetworkRequest()
    error = blocking.get(QNetworkRequest(QUrl(CATALOG_URL)), True, feedback)
    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise RuntimeError(f"Kunde inte hämta planbestämmelsekatalogen: {blocking.errorMessage()}")
    data = json.loads(bytes(blocking.reply().content()).decode("utf-8"))
    entries = {
        b["id"].lower(): [clean_beteckning(b.get("beteckning")), b.get("farg"), b.get("symbol")]
        for b in data.get("bestammelser", [])
        if b.get("id")
    }
    return {
        "format": CACHE_FORMAT,
        "release": data.get("namn"),
        "publicerad": data.get("publicerad"),
        "bestammelser": entries,
    }


def load_catalog(feedback: QgsFeedback | None = None) -> dict[str, Any]:
    """Cached catalogue, refreshed when older than MAX_AGE_SECONDS.

    Falls back to a stale cache if Boverket cannot be reached.
    """
    path = cache_path()
    fresh = (
        path.exists()
        and time.time() - path.stat().st_mtime < MAX_AGE_SECONDS
        and _cached_format(path) == CACHE_FORMAT
    )
    if not fresh:
        try:
            catalog = _download(feedback)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            return catalog
        except (RuntimeError, ValueError, OSError):
            if not path.exists():
                raise
    return json.loads(path.read_text(encoding="utf-8"))


def _cached_format(path: Path) -> int | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("format")
    except (OSError, ValueError):
        return None


def _number(value: Any) -> str | None:
    try:
        return f"{float(str(value).replace(',', '.')):g}"
    except (TypeError, ValueError):
        return None


def value_label(props: dict[str, Any], symbol: str | None) -> str | None:
    """'nh 9' for a notation drawn as a value symbol, else None."""
    affix = next((a for prefix, a in VALUE_SYMBOLS.items() if (symbol or "").startswith(prefix)), None)
    if affix is None:
        return None
    value = _number(props.get(VALUE_FIELD))
    if value is None:  # often only in the wording: "Högsta nockhöjd är 9 meter"
        match = re.search(r"(\d+(?:[.,]\d+)?)", props.get(FORMULERING_FIELD) or "")
        value = _number(match.group(1)) if match else None
    return f"{affix[0]}{value}{affix[1]}" if value else None


def needs_catalog(features: list[dict[str, Any]]) -> bool:
    return any(f["properties"].get(REF_FIELD) for f in features)


def enrich(features: list[dict[str, Any]], catalog: dict[str, Any]) -> int:
    """Add notation, colour and symbol columns; returns the number of features matched."""
    entries = catalog["bestammelser"]
    matched = 0
    for feature in features:
        props = feature["properties"]
        ref = props.get(REF_FIELD)
        if not ref:
            continue
        entry = entries.get(ref.lower())
        beteckning, farg, symbol = (list(entry) + [None, None, None])[:3] if entry else (None, None, None)
        props[BETECKNING_FIELD], props[FARG_FIELD], props[SYMBOL_FIELD] = beteckning, farg, symbol
        props[ETIKETT_FIELD] = beteckning or value_label(props, symbol)
        matched += bool(entry)
    return matched


USE_TYPE = "användningsbestämmelse"
PROPERTY_TYPE = "egenskapsbestämmelse"
PLAN_ID_FIELD = "detaljplan_objektidentitet"
COUNT_FIELD = "antal_bestammelser"


def _join_beteckningar(values: list[str], spaced: bool) -> str | None:
    """Uses: ['B', 'C'] -> 'BC', words spaced ('CYKEL GÅNG'). Properties: 'e h p'."""
    unique = sorted(set(v for v in values if v))
    if not unique:
        return None
    return ("" if not spaced and all(len(v) == 1 for v in unique) else " ").join(unique)


def _merge(group: list[dict[str, Any]]) -> dict[str, Any]:
    # Alphabetical by notation; the first one's colour is used for the area
    # (BFS 2020:6 2.5: a combination is coloured with one of its uses' colours).
    group = sorted(group, key=lambda f: f["properties"].get(BETECKNING_FIELD) or "~")
    spaced = group[0]["properties"].get("feature_typ") == PROPERTY_TYPE
    merged = dict(group[0]["properties"])
    for key in {k for f in group for k in f["properties"]}:
        values = [f["properties"].get(key) for f in group]
        if key in (BETECKNING_FIELD, ETIKETT_FIELD):
            merged[key] = _join_beteckningar(values, spaced)
        elif key == FARG_FIELD:
            merged[key] = values[0]
        elif key == SYMBOL_FIELD:  # an area pattern (e.g. prickmark) wins over none
            merged[key] = next((v for v in values if v), None)
        elif key == "assets":
            assets = {}
            for value in values:
                for asset in json.loads(value or "{}").values():
                    if asset.get("href") not in {a.get("href") for a in assets.values()}:
                        assets[f"asset-{len(assets) + 1}"] = asset
            merged[key] = json.dumps(assets, ensure_ascii=False)
        else:
            distinct = list(dict.fromkeys(v for v in values if v not in (None, "")))
            merged[key] = distinct[0] if len(distinct) == 1 else (
                " + ".join(str(v) for v in distinct) if distinct else None
            )
    merged[COUNT_FIELD] = len(group)
    return {"type": "Feature", "geometry": group[0]["geometry"], "properties": merged}


def merge_combinations(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge use or property provisions of one plan that share the exact same geometry.

    A combination of uses (e.g. B + C) comes as one reference object per use
    with identical geometry; a plan map shows it as one area labelled 'BC'.
    Properties valid for the same area likewise get one label, e.g. 'e h p'.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []
    for feature in features:
        props = feature["properties"]
        if props.get("feature_typ") not in (USE_TYPE, PROPERTY_TYPE) or not feature.get("geometry"):
            out.append(feature)
            continue
        key = (props.get("feature_typ"), props.get(PLAN_ID_FIELD), json.dumps(feature["geometry"], sort_keys=True))
        if key not in groups:
            groups[key] = []
            out.append(key)  # placeholder keeps the original order
        groups[key].append(feature)
    for group in groups.values():
        if len(group) == 1:
            group[0]["properties"][COUNT_FIELD] = 1
    return [
        (_merge(groups[f]) if len(groups[f]) > 1 else groups[f][0]) if isinstance(f, tuple) else f
        for f in out
    ]
