"""Detaljplan provisions at a point, read from downloaded GeoPackage layers.

Mirrors what Lantmäteriet's own plan viewer shows for a click: the plans
covering the point, and for each plan its provisions grouped by type with a
"N of M" count (N at the point, M in the whole plan). Everything is read from
layers in the QGIS project; nothing here talks to NGP.

The layers are those written by the plugin's detaljplan download: every feature
carries `feature_typ` and `detaljplan_objektidentitet`, and use / property
provisions carry `bestammelser_json` with the provisions merged into the feature.

How a detaljplan is built (the plan's domain object, the item asset with role
"detaljplan"): the use provision (användningsbestämmelse) is the base, saying what
the land may be used for. Property provisions (egenskapsbestämmelse) lie on top:
conditions within or across several uses, as an area, a line or a point, pointing
through `reglerarAnvandningsbestammelse` at the uses they apply to. Administrative
provisions (administrativ bestämmelse) apply to the whole plan (for example
implementation time and responsibility for public spaces), carry `reglerarDetaljplan`
and have an empty `reglerarAnvandningsbestammelse`. The domain object itself carries
`anvandningsform`, `kategori`, `underkategori` and `bestammelsevarde` on every
provision, so the labels below come from it and not from the Boverket catalogue.

A use is "at the point" only when its own area covers the point. A property
provision spans many uses, so it hitting the point says nothing about the others.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

from qgis.PyQt.QtCore import QDate, QDateTime

from .planbestammelser import COUNT_FIELD, ORIGINAL_FIELDS, ORIGINALS_FIELD
from .resources import MANIFEST_NAME, Resource, parse_assets

TYPE_FIELD = "feature_typ"
PLAN_ID_FIELD = "detaljplan_objektidentitet"
PLAN_TYPE = "detaljplan"
# The data also holds plans under work (påbörjad, samråd, granskning) that are not binding.
# They are listed, but with their provisions only when asked for, so that a draft is never
# read as what applies. Plans in force come first.
IN_FORCE_STATUS = "laga kraft"
# The order NGP delivers a plan document in; unknown types come last.
USE_TYPE, PROPERTY_TYPE, ADMIN_TYPE = "användningsbestämmelse", "egenskapsbestämmelse", "administrativ bestämmelse"
TYPE_ORDER = (USE_TYPE, PROPERTY_TYPE, ADMIN_TYPE)
PLAN_WIDE_HEADING = "Gäller hela planen"
OTHER_AT_POINT_HEADING = "Övriga bestämmelser i punkten"
HEADINGS = {
    "användningsbestämmelse": "Användningsbestämmelser",
    "egenskapsbestämmelse": "Egenskapsbestämmelser",
    "administrativ bestämmelse": "Administrativa bestämmelser",
}
# Plan machine-readable bundle: not a document to hand to a user.
HIDDEN_DOCUMENT_ROLES = {"detaljplan"}
# Half-width of the search box around the clicked point for areas, in layer units:
# an area is hit only when the point is inside it.
POINT_TOLERANCE = 0.001
# How close (in metres) the click must be to a line or point provision to count as a hit.
# Such a provision has no extent to click inside, so an exact hit would almost never
# happen. A few metres is about what one can aim at in the map at plan scale.
LINE_POINT_TOLERANCE_M = 3.0
# Metres per degree of latitude, for layers in a geographic CRS.
_METRES_PER_DEGREE = 111_320.0


@dataclass(frozen=True)
class Provision:
    id: str
    form: str  # användningsform, e.g. "Kvartersmark"
    text: str  # bestämmelseformulering
    category: str


@dataclass
class TypeGroup:
    type: str
    at_point: list[Provision] = field(default_factory=list)
    in_plan: list[Provision] = field(default_factory=list)


@dataclass
class UseNode:
    """A use provision with the property and administrative provisions that regulate it."""

    use: Provision
    children: list[tuple[str, Provision]] = field(default_factory=list)  # (feature type, provision)


@dataclass
class PlanDetail:
    """What the plan's domain object adds to the flat layers: purpose, decision, hierarchy."""

    purpose: str = ""
    decision: list[str] = field(default_factory=list)
    uses: list[UseNode] = field(default_factory=list)
    loose: list[tuple[str, Provision]] = field(default_factory=list)  # regulate no use, not plan-wide
    plan_wide: list[Provision] = field(default_factory=list)  # administrative: apply to the whole plan


@dataclass
class PlanInfo:
    plan_id: str
    name: str
    beteckning: str
    status: str
    date_in_force: str
    documents: list[Resource]
    groups: list[TypeGroup]
    gpkg_path: str | None  # where the plan layer is stored, for saving documents next to it
    domain: Resource | None = None  # the plan's domain object, if the data offers one
    at_point_ids: set[str] = field(default_factory=set)  # provisions that hit the clicked point
    use_at_point_ids: set[str] = field(default_factory=set)  # uses whose own area covers the point
    detail: PlanDetail | None = None  # parsed domain object, once fetched
    in_force: bool = True  # status "laga kraft"
    show_content: bool = True  # provisions are read; False for a plan under work unless asked for
    started: str = ""  # datumPaborjat
    status_date: str = ""  # datumStatusforandring


@dataclass
class Identification:
    plans: list[PlanInfo] = field(default_factory=list)
    highlight: list[QgsGeometry] = field(default_factory=list)  # use areas at the point, in the requested CRS
    highlight_marks: list[QgsGeometry] = field(default_factory=list)  # lines and points hit, same CRS
    has_layers: bool = False  # any detaljplan layer in the project at all
    legacy: bool = False  # merged provisions in a GeoPackage downloaded before bestammelser_json


def _clean(value: Any) -> Any:
    """NULL and other non-scalar values from the data provider become None; dates become text."""
    if isinstance(value, (QDate, QDateTime)):
        return value.toString("yyyy-MM-dd") if value.isValid() else None
    return value if isinstance(value, (str, int, float)) else None


def _attributes(feature: QgsFeature) -> dict[str, Any]:
    return {name: _clean(value) for name, value in zip(feature.fields().names(), feature.attributes())}


def _is_plan_data(layer: Any) -> bool:
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return False
    names = layer.fields().names()
    return TYPE_FIELD in names and PLAN_ID_FIELD in names


def layer_type(layer: QgsVectorLayer) -> str | None:
    """`feature_typ` of the layer's first feature; a layer holds one type."""
    request = QgsFeatureRequest().setLimit(1).setFlags(QgsFeatureRequest.Flag.NoGeometry)
    feature = next(layer.getFeatures(request), None)
    return _attributes(feature).get(TYPE_FIELD) if feature else None


def find_layers(project: QgsProject | None = None) -> tuple[list[QgsVectorLayer], list[QgsVectorLayer]]:
    """(plan layers, provision layers) among the project's layers."""
    plans, provisions = [], []
    for layer in (project or QgsProject.instance()).mapLayers().values():
        if not _is_plan_data(layer):
            continue
        kind = layer_type(layer)
        if kind == PLAN_TYPE:
            plans.append(layer)
        elif kind:
            provisions.append(layer)
    return plans, provisions


def _point_in(layer: QgsVectorLayer, point: QgsPointXY, point_crs: QgsCoordinateReferenceSystem) -> QgsPointXY:
    if point_crs == layer.crs():
        return point
    transform = QgsCoordinateTransform(point_crs, layer.crs(), QgsProject.instance())
    return transform.transform(point)


def _features_at(layer: QgsVectorLayer, point: QgsPointXY) -> list[QgsFeature]:
    """Features hit by `point`: areas exactly, lines and points within a few metres."""
    target = QgsGeometry.fromPointXY(point)
    is_area = layer.geometryType() == Qgis.GeometryType.Polygon
    tolerance = POINT_TOLERANCE if is_area else LINE_POINT_TOLERANCE_M
    if not is_area and layer.crs().isGeographic():
        tolerance /= _METRES_PER_DEGREE
    box = QgsRectangle(
        point.x() - tolerance, point.y() - tolerance,
        point.x() + tolerance, point.y() + tolerance,
    )
    candidates = (
        f for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(box)) if f.hasGeometry()
    )
    if is_area:
        return [f for f in candidates if f.geometry().intersects(target)]
    return [f for f in candidates if f.geometry().distance(target) <= tolerance]


def _features_of_plan(layer: QgsVectorLayer, plan_id: str) -> list[QgsFeature]:
    expression = f'"{PLAN_ID_FIELD}" = {QgsExpression.quotedString(plan_id)}'
    return list(layer.getFeatures(QgsFeatureRequest().setFilterExpression(expression)))


def provisions_of(feature: QgsFeature) -> tuple[list[Provision], bool]:
    """The provisions a feature stands for, and whether it is a legacy merged feature.

    Merged features hold their provisions in `bestammelser_json`. A feature
    without it stands for one provision, unless it was merged by an older
    version of the plugin: then its texts are joined and cannot be separated.
    """
    attrs = _attributes(feature)
    items = None
    raw = attrs.get(ORIGINALS_FIELD)
    if raw:
        try:
            items = json.loads(raw)
        except ValueError:
            items = None
    legacy = False
    if items is None:
        items = [{key: attrs.get(key) for key in ORIGINAL_FIELDS}]
        legacy = (attrs.get(COUNT_FIELD) or 1) > 1
    provisions = []
    for item in items:
        text = _strip_placeholders(
            item.get("planbestammelse_bestammelseformulering")
            or item.get("planbestammelse_etikett")
            or item.get("planbestammelse_beteckning")
            or attrs.get("title")
            or ""
        )
        # A category that only repeats the text (e.g. "Bostäder") adds nothing.
        category = " · ".join(
            v
            for v in (item.get("planbestammelse_kategori"), item.get("planbestammelse_underkategori"))
            if v and v != text
        )
        provisions.append(
            Provision(
                id=str(item.get("ngp_id") or ""),
                form=item.get("planbestammelse_anvandningsform") or "",
                text=text,
                category=category,
            )
        )
    return provisions, legacy


def provision_geometry(
    plan_id: str, ids: list[str], target_crs: QgsCoordinateReferenceSystem, project: QgsProject | None = None
) -> QgsGeometry | None:
    """The area, line or point of the provisions with these ids, in `target_crs`; None if not found.

    Looks in the plan's provision layers, where a feature stands for one or several
    provisions (see `provisions_of`).
    """
    wanted = {i for i in ids if i}
    parts = []
    for layer in find_layers(project)[1]:
        for feature in _features_of_plan(layer, plan_id):
            if not feature.hasGeometry():
                continue
            found = {i for p in provisions_of(feature)[0] for i in _ids(p)}
            if wanted & found:
                geometry = QgsGeometry(feature.geometry())
                if layer.crs() != target_crs:
                    geometry.transform(QgsCoordinateTransform(layer.crs(), target_crs, QgsProject.instance()))
                parts.append(geometry)
    return QgsGeometry.collectGeometry(parts) if parts else None


def _ids(provision: Provision) -> list[str]:
    """The object ids behind a provision. Features merged by an older plugin version
    hold their ids joined with " + " and no JSON, so split them to match the domain object."""
    return [i for i in provision.id.split(" + ") if i]


def _strip_placeholders(text: str) -> str:
    """Drop template markers such as ' [text]' or ' [laga kraft:text]' from a wording."""
    text = re.sub(r"\s*\[[^\]]*\]", "", text)
    return re.sub(r"\s+([.,;:])", r"\1", text).strip()


def _type_rank(type_name: str) -> tuple[int, str]:
    lowered = type_name.lower()
    return (TYPE_ORDER.index(lowered) if lowered in TYPE_ORDER else len(TYPE_ORDER), lowered)


def _documents(assets: Any) -> list[Resource]:
    return [
        r for r in parse_assets(assets)
        if r.role not in HIDDEN_DOCUMENT_ROLES and r.title
    ]


def identify(
    point: QgsPointXY,
    point_crs: QgsCoordinateReferenceSystem,
    highlight_crs: QgsCoordinateReferenceSystem,
    project: QgsProject | None = None,
    include_pending: bool = False,
) -> Identification:
    """Plans and provisions at `point`, from the project's detaljplan layers.

    Plans not in force (laga kraft) are listed too, but their provisions are read only
    with `include_pending`; without it such a plan is marked by its outline alone.
    """
    plan_layers, provision_layers = find_layers(project)
    result = Identification(has_layers=bool(plan_layers or provision_layers))
    seen_plans: set[str] = set()
    plan_areas: dict[str, QgsGeometry] = {}

    for layer in plan_layers:
        for feature in _features_at(layer, _point_in(layer, point, point_crs)):
            attrs = _attributes(feature)
            plan_id = attrs.get(PLAN_ID_FIELD)
            if not plan_id or plan_id in seen_plans:
                continue
            seen_plans.add(plan_id)
            in_force = str(attrs.get("detaljplan_status") or "").lower() == IN_FORCE_STATUS
            source = layer.source().split("|")[0]
            area = QgsGeometry(feature.geometry())
            if layer.crs() != highlight_crs:
                area.transform(QgsCoordinateTransform(layer.crs(), highlight_crs, QgsProject.instance()))
            plan_areas[plan_id] = area
            result.plans.append(
                PlanInfo(
                    plan_id=plan_id,
                    name=attrs.get("detaljplan_namn") or attrs.get("title") or "",
                    beteckning=attrs.get("detaljplan_beteckning") or "",
                    status=attrs.get("detaljplan_status") or "",
                    date_in_force=attrs.get("detaljplan_datumLagakraft") or "",
                    documents=_documents(attrs.get("assets")),
                    groups=[],
                    gpkg_path=source,
                    domain=_domain_resource(attrs.get("assets")),
                    in_force=in_force,
                    show_content=in_force or include_pending,
                    started=attrs.get("detaljplan_datumPaborjat") or "",
                    status_date=attrs.get("detaljplan_datumStatusforandring") or "",
                )
            )

    # Plans in force first, then the newest first: versions of a plan are easy to compare.
    result.plans.sort(key=lambda p: p.status_date or p.started, reverse=True)
    result.plans.sort(key=lambda p: not p.in_force)

    for plan in result.plans:
        if not plan.show_content:
            result.highlight.append(plan_areas[plan.plan_id])  # the outline stands in for the content
            continue
        groups: dict[str, TypeGroup] = {}
        for layer in provision_layers:
            at_point_ids = {f.id() for f in _features_at(layer, _point_in(layer, point, point_crs))}
            for feature in _features_of_plan(layer, plan.plan_id):
                provisions, legacy = provisions_of(feature)
                result.legacy = result.legacy or legacy
                type_name = _attributes(feature).get(TYPE_FIELD) or "övrigt"
                group = groups.setdefault(type_name, TypeGroup(type_name))
                here = feature.id() in at_point_ids
                for provision in provisions:
                    if provision.id and provision.id in {p.id for p in group.in_plan}:
                        continue
                    group.in_plan.append(provision)
                    if here:
                        group.at_point.append(provision)
                # Highlight the areas of the uses at the point. A property area often spans
                # the whole plan and would just redraw the plan outline.
                # Lines and points that are hit are marked too: they are easy to miss otherwise.
                is_use_area = type_name.lower() == USE_TYPE and layer.geometryType() == Qgis.GeometryType.Polygon
                is_mark = layer.geometryType() in (Qgis.GeometryType.Line, Qgis.GeometryType.Point)
                if here and feature.hasGeometry() and (is_use_area or is_mark):
                    geometry = QgsGeometry(feature.geometry())
                    if layer.crs() != highlight_crs:
                        geometry.transform(QgsCoordinateTransform(layer.crs(), highlight_crs, QgsProject.instance()))
                    (result.highlight if is_use_area else result.highlight_marks).append(geometry)
        plan.groups = [groups[t] for t in sorted(groups, key=_type_rank)]
        plan.at_point_ids = {i for g in plan.groups for p in g.at_point for i in _ids(p)}
        plan.use_at_point_ids = {
            i for g in plan.groups if g.type.lower() == USE_TYPE for p in g.at_point for i in _ids(p)
        }
        plan.detail = cached_detail(plan)
    return result


# --- the plan's domain object ----------------------------------------------

def _domain_resource(assets: Any) -> Resource | None:
    return next((r for r in parse_assets(assets) if r.role in HIDDEN_DOCUMENT_ROLES), None)


def documents_dir(plan: PlanInfo, fallback: Path) -> Path:
    """Where a plan's downloads go: next to its GeoPackage, else `fallback`."""
    if plan.gpkg_path and Path(plan.gpkg_path).is_file():
        gpkg = Path(plan.gpkg_path)
        return gpkg.parent / f"{gpkg.stem}_resurser"
    return fallback


def cached_detail(plan: PlanInfo) -> PlanDetail | None:
    """The domain object if it was fetched before (the download manifest knows where)."""
    if plan.domain is None or not plan.gpkg_path:
        return None
    folder = documents_dir(plan, Path())
    if folder == Path():
        return None
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
        return load_detail(folder / manifest[plan.domain.href])
    except (OSError, ValueError, KeyError):
        return None


def load_detail(path: Path | str) -> PlanDetail | None:
    try:
        return parse_domain(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def _value_text(values: Any) -> str:
    """'min 15 procent' style text from `bestammelsevarde`, for a provision without wording."""
    if isinstance(values, dict):
        values = [values]
    parts = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict) or value.get("variabelvarde") in (None, ""):
            continue
        parts.append(" ".join(
            str(v) for v in (value.get("vardetyp"), value.get("variabelvarde"), value.get("enhet")) if v
        ))
    return ", ".join(parts)


def _domain_provision(props: dict[str, Any]) -> Provision:
    """A provision from the domain object, which itself carries `anvandningsform`,
    `kategori`, `underkategori` and `bestammelsevarde`.

    The wording normally already contains the values; `bestammelsevarde` is the
    fallback when the wording is empty or was only a placeholder.
    """
    text = _strip_placeholders(props.get("bestammelseformulering") or "") or _value_text(
        props.get("bestammelsevarde")
    )
    category = " · ".join(
        v
        for v in (props.get("kategori"), props.get("underkategori"))
        if isinstance(v, str) and v and v.lower() != text.lower()
    )
    return Provision(
        id=str(props.get("objektidentitet") or ""),
        form=(props.get("anvandningsform") or "").capitalize(),
        text=text,
        category=category,
    )


def parse_domain(data: Any) -> PlanDetail | None:
    """Parse a detaljplan domain object (GeoJSON FeatureCollection); None if it is not one."""
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        return None
    detail = PlanDetail()
    uses: dict[str, UseNode] = {}
    regulating: list[tuple[str, dict[str, Any]]] = []
    found_plan = False
    for feature in data["features"]:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        kind = str(props.get("feature:typ") or "").lower()
        if kind == PLAN_TYPE:
            found_plan = True
            detail.purpose = props.get("syfte") or ""
            detail.decision = _decision_lines(props.get("beslutsinformation"))
        elif kind == USE_TYPE:
            node = UseNode(_domain_provision(props))
            uses[node.use.id] = node
        elif kind:
            regulating.append((kind, props))
    if not found_plan:
        return None
    for kind, props in regulating:
        provision = _domain_provision(props)
        if kind == ADMIN_TYPE:  # applies to the whole plan, whatever it points at
            _add_plan_wide(detail.plan_wide, provision)
            continue
        targets = props.get("reglerarAnvandningsbestammelse")
        parents = [uses[t] for t in targets if t in uses] if isinstance(targets, list) else []
        for node in parents:
            node.children.append((kind, provision))
        if not parents:
            detail.loose.append((kind, provision))
    detail.uses = list(uses.values())
    return detail


def _add_plan_wide(provisions: list[Provision], provision: Provision) -> None:
    """Add unless an identical text is there already (one wording often sits on many areas).

    The ids of merged duplicates are joined onto the kept one (with " + ", like the
    legacy merge) so that a link can still zoom to all of their areas.
    """
    if not provision.text:
        return
    for index, existing in enumerate(provisions):
        if existing.text == provision.text:
            if provision.id and provision.id not in _ids(existing):
                provisions[index] = replace(existing, id=f"{existing.id} + {provision.id}".strip(" +"))
            return
    provisions.append(provision)


def _decision_lines(info: Any) -> list[str]:
    """Short 'label: value' lines from the plan's beslutsinformation."""
    if not isinstance(info, list) or not info or not isinstance(info[0], dict):
        return []
    entry = info[0]
    force = entry.get("datumLagakraft")
    force = force[0] if isinstance(force, list) and force else force
    time = f"{entry['genomforandetid']} månader" if entry.get("genomforandetid") else None
    pairs = [
        ("Beslutstyp", entry.get("beslutstyp")),
        ("Antagen", entry.get("datumAntagande")),
        ("Laga kraft", force),
        ("Genomförandetid", time),
        ("Instans", entry.get("instansInomKommunen")),
        ("Diarienummer", entry.get("diarienummerKommun")),
    ]
    return [f"{label}: {value}" for label, value in pairs if value]


# --- presentation ----------------------------------------------------------

def _esc(value: Any) -> str:
    return html.escape(str(value or ""))


def render_html(result: Identification, show_all: bool, colors: dict[str, str]) -> str:
    """The result as the HTML a QTextBrowser can show.

    `colors` holds hex strings for text, muted, border, card and accent, taken
    from the widget palette so the view follows the light or dark theme.
    """
    if not result.has_layers:
        return _notice(
            "Inga detaljplanslager i projektet. Hämta Detaljplan med NGP-panelen, "
            "eller öppna ett projekt som innehåller en sådan GeoPackage.",
            colors,
        )
    if not result.plans:
        return _notice(
            "Ingen detaljplan i de hämtade lagren på den klickade platsen. Det betyder inte "
            "att platsen saknar detaljplan, bara att den inte finns i det du hämtat "
            "eller i Lantmäteriets digitala data.",
            colors,
        )

    parts = [f'<div style="color:{colors["text"]};">']
    if result.legacy:
        parts.append(_notice(
            "Lagret är hämtat med en äldre version av pluginet. Sammanslagna bestämmelser "
            "visas som en text och räknas inte rätt. Hämta planen igen för full visning.",
            colors,
        ))
    for plan_index, plan in enumerate(result.plans):
        parts.append(_render_plan(plan_index, plan, show_all, colors))
    parts.append("</div>")
    return "".join(parts)


def _notice(text: str, colors: dict[str, str]) -> str:
    return (
        f'<p style="color:{colors["muted"]};">{_esc(text)}</p>'
    )


def _render_plan(plan_index: int, plan: PlanInfo, show_all: bool, colors: dict[str, str]) -> str:
    decision = plan.status.capitalize()
    if plan.in_force:
        if plan.date_in_force:
            decision += f" ({plan.date_in_force})"
    else:
        stamps = (("påbörjad", plan.started), ("status ändrad", plan.status_date))
        dates = [f"{label} {value}" for label, value in stamps if value and label != plan.status.lower()]
        if dates:
            decision += f" ({', '.join(dates)})"
    out = [
        f'<h2 style="margin-bottom:2px;">{_esc(plan.name)}</h2>',
        f'<table cellspacing="0" cellpadding="3"><tr>'
        f'<td style="color:{colors["muted"]};">Beteckning</td>'
        f'<td style="color:{colors["muted"]};">Beslutsinformation</td></tr>'
        f'<tr><td><b>{_esc(plan.beteckning)}</b></td><td><b>{_esc(decision)}</b></td></tr></table>',
    ]
    if plan.documents:
        links = []
        for doc_index, document in enumerate(plan.documents):
            links.append(
                f'<a href="doc:{plan_index}:{doc_index}" style="color:{colors["accent"]};">'
                f'&#8595; {_esc(document.title)}</a>'
            )
        joined = "&nbsp;&nbsp; ".join(links)
        out.append(f'<p style="color:{colors["muted"]}; margin-bottom:2px;">Länkar</p><p>{joined}</p>')

    if not plan.in_force:
        note = "Planen är under arbete och inte bindande."
        if not plan.show_content:
            note += " Bestämmelserna visas inte. Bocka i Visa även planer som inte vunnit laga kraft för att se dem."
        out.append(_notice(note, colors))
    if not plan.show_content:
        out.append(f'<hr style="color:{colors["border"]};">')
        return "".join(out)

    if plan.detail:
        out.append(_render_detail(plan_index, plan, show_all, colors))
        out.append(f'<hr style="color:{colors["border"]};">')
        return "".join(out)

    for group in plan.groups:
        if group.type.lower() == ADMIN_TYPE:  # whole-plan provisions: merged, always shown
            merged: list[Provision] = []
            for provision in group.in_plan:
                _add_plan_wide(merged, provision)
            if merged:
                out.append(f'<h3 style="margin-bottom:4px;">{PLAN_WIDE_HEADING}</h3>')
                out.append(_provision_table(plan_index, merged, colors))
            continue
        shown = group.in_plan if show_all else group.at_point
        if not shown:
            continue
        heading = HEADINGS.get(group.type.lower(), group.type.capitalize())
        out.append(
            f'<h3 style="margin-bottom:4px;">{_esc(heading)} &ndash; '
            f'{len(group.at_point)} av {len(group.in_plan)} st</h3>'
        )
        out.append(
            f'<table width="100%" cellspacing="0" cellpadding="6" '
            f'style="border:1px solid {colors["border"]};">'
        )
        for provision in shown:
            lines = []
            if provision.form:
                lines.append(f"<b>{_esc(provision.form)}</b>")
            lines.append(_zoom_link(plan_index, provision, _esc(provision.text), colors))
            if provision.category:
                lines.append(f'<span style="color:{colors["muted"]};">{_esc(provision.category)}</span>')
            out.append(
                f'<tr><td style="border-bottom:1px solid {colors["border"]};">{"<br>".join(lines)}</td></tr>'
            )
        out.append("</table>")
    out.append(f'<hr style="color:{colors["border"]};">')
    return "".join(out)


def _zoom_link(plan_index: int, provision: Provision, inner: str, colors: dict[str, str]) -> str:
    """`inner` as a link that zooms to the provision's area, or as it is without an id."""
    ids = _ids(provision)
    if not ids:
        return inner
    return (
        f'<a href="zoom:{plan_index}:{",".join(ids)}" style="color:{colors["text"]}; text-decoration:none;">'
        f'{inner}</a> <span style="color:{colors["accent"]};">&#8982;</span>'
    )


def _provision_table(plan_index: int, provisions: list[Provision], colors: dict[str, str]) -> str:
    """Wording and category of plain provisions, one row each; the wording zooms to the area."""
    rows = []
    for provision in provisions:
        lines = [_zoom_link(plan_index, provision, _esc(provision.text), colors)]
        if provision.category:
            lines.append(f'<span style="color:{colors["muted"]};">{_esc(provision.category)}</span>')
        rows.append(f'<tr><td style="border-bottom:1px solid {colors["border"]};">{"<br>".join(lines)}</td></tr>')
    return (
        f'<table width="100%" cellspacing="0" cellpadding="5" style="border:1px solid {colors["border"]};">'
        + "".join(rows) + "</table>"
    )


def _render_detail(plan_index: int, plan: PlanInfo, show_all: bool, colors: dict[str, str]) -> str:
    """Purpose, decision and the provisions nested under the use they regulate.

    Each provision's wording is a `zoom:` link; the dock zooms the map to its area.
    """
    detail = plan.detail
    muted = colors["muted"]
    out = []
    if detail.purpose:
        out.append(f'<p style="color:{muted}; margin-bottom:2px;">Syfte</p><p>{_esc(detail.purpose)}</p>')
    if detail.decision:
        out.append(
            f'<p style="color:{muted}; margin-bottom:2px;">Beslut</p><p>'
            + "<br>".join(_esc(line) for line in detail.decision)
            + "</p>"
        )
    here = plan.at_point_ids  # provisions hitting the point, of any type
    uses_here = plan.use_at_point_ids  # uses whose own area covers the point

    def section(children: list[tuple[str, Provision]], only_here: bool) -> str:
        """Provisions grouped by type; those hitting the point come first."""
        parts = []
        by_type: dict[str, list[Provision]] = {}
        for kind, provision in children:
            by_type.setdefault(kind, []).append(provision)
        for kind in sorted(by_type, key=_type_rank):
            items = sorted(by_type[kind], key=lambda p: p.id not in here)  # stable
            shown = [p for p in items if p.id in here] if only_here else items
            if not shown:
                continue
            heading = HEADINGS.get(kind, kind.capitalize())
            parts.append(
                f'<p style="margin-bottom:2px;"><b>{_esc(heading)}</b> '
                f'<span style="color:{muted};">{sum(p.id in here for p in items)} av {len(items)} st</span></p>'
                + _provision_table(plan_index, shown, colors)
            )
        return "".join(parts)

    # A use counts as "at the point" only through its own area; a property provision
    # that hits the point says nothing about the many uses it points at.
    nodes = sorted(detail.uses, key=lambda n: n.use.id not in uses_here)
    for node in nodes:
        use_here = node.use.id in uses_here
        if not show_all and not use_here:
            continue
        body = section(node.children, only_here=not show_all)
        title = _zoom_link(
            plan_index, node.use, " &ndash; ".join(_esc(v) for v in (node.use.form, node.use.text) if v), colors
        )
        category = f'<p style="color:{muted}; margin-top:0;">{_esc(node.use.category)}</p>' if node.use.category else ""
        out.append(f'<h3 style="margin-bottom:4px;">{title}</h3>{category}{body}')

    if show_all:
        other = section(detail.loose, only_here=False)
        if other:
            out.append(f'<h3 style="margin-bottom:4px;">Utan särskild användning</h3>{other}')
    else:
        # Hits whose uses are all elsewhere: nowhere else to show them.
        stray: dict[str, tuple[str, Provision]] = {}
        for node in detail.uses:
            if node.use.id in uses_here:
                continue
            for kind, provision in node.children:
                if provision.id in here:
                    stray.setdefault(provision.id, (kind, provision))
        covered = {p.id for node in detail.uses if node.use.id in uses_here for _k, p in node.children}
        stray = {i: kp for i, kp in stray.items() if i not in covered}
        stray.update({p.id: (k, p) for k, p in detail.loose if p.id in here})
        other = section(list(stray.values()), only_here=True)
        if other:
            out.append(f'<h3 style="margin-bottom:4px;">{OTHER_AT_POINT_HEADING}</h3>{other}')

    if detail.plan_wide:
        out.append(f'<h3 style="margin-bottom:4px;">{PLAN_WIDE_HEADING}</h3>{_provision_table(plan_index, detail.plan_wide, colors)}')
    return "".join(out)
