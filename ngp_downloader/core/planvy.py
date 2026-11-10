"""Detaljplan provisions at a point, read from downloaded GeoPackage layers.

Mirrors what Lantmäteriet's own plan viewer shows for a click: the plans
covering the point, and for each plan its provisions grouped by type with a
"N of M" count (N at the point, M in the whole plan). Everything is read from
layers in the QGIS project; nothing here talks to NGP.

The layers are those written by the plugin's detaljplan download: every feature
carries `feature_typ` and `detaljplan_objektidentitet`, and use / property
provisions carry `bestammelser_json` with the provisions merged into the feature.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
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

from .planbestammelser import COUNT_FIELD, ORIGINAL_FIELDS, ORIGINALS_FIELD
from .resources import Resource, parse_assets

TYPE_FIELD = "feature_typ"
PLAN_ID_FIELD = "detaljplan_objektidentitet"
PLAN_TYPE = "detaljplan"
# The order NGP delivers a plan document in; unknown types come last.
TYPE_ORDER = ("användningsbestämmelse", "egenskapsbestämmelse", "administrativ bestämmelse")
HEADINGS = {
    "användningsbestämmelse": "Användningsbestämmelser",
    "egenskapsbestämmelse": "Egenskapsbestämmelser",
    "administrativ bestämmelse": "Administrativa bestämmelser",
}
# Plan machine-readable bundle: not a document to hand to a user.
HIDDEN_DOCUMENT_ROLES = {"detaljplan"}
# Half-width of the search box around the clicked point, in layer units.
POINT_TOLERANCE = 0.001


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
class PlanInfo:
    plan_id: str
    name: str
    beteckning: str
    status: str
    date_in_force: str
    documents: list[Resource]
    groups: list[TypeGroup]
    gpkg_path: str | None  # where the plan layer is stored, for saving documents next to it


@dataclass
class Identification:
    plans: list[PlanInfo] = field(default_factory=list)
    highlight: list[QgsGeometry] = field(default_factory=list)  # polygons, in the requested CRS
    has_layers: bool = False  # any detaljplan layer in the project at all
    legacy: bool = False  # merged provisions in a GeoPackage downloaded before bestammelser_json


def _clean(value: Any) -> Any:
    """NULL and other non-scalar values from the data provider become None."""
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
    box = QgsRectangle(
        point.x() - POINT_TOLERANCE, point.y() - POINT_TOLERANCE,
        point.x() + POINT_TOLERANCE, point.y() + POINT_TOLERANCE,
    )
    target = QgsGeometry.fromPointXY(point)
    return [
        f for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(box))
        if f.hasGeometry() and f.geometry().intersects(target)
    ]


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
) -> Identification:
    """Plans and provisions at `point`, from the project's detaljplan layers."""
    plan_layers, provision_layers = find_layers(project)
    result = Identification(has_layers=bool(plan_layers or provision_layers))
    seen_plans: set[str] = set()

    for layer in plan_layers:
        for feature in _features_at(layer, _point_in(layer, point, point_crs)):
            attrs = _attributes(feature)
            plan_id = attrs.get(PLAN_ID_FIELD)
            if not plan_id or plan_id in seen_plans:
                continue
            seen_plans.add(plan_id)
            source = layer.source().split("|")[0]
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
                )
            )

    for plan in result.plans:
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
                if here and feature.hasGeometry() and feature.geometry().type() == Qgis.GeometryType.Polygon:
                    geometry = QgsGeometry(feature.geometry())
                    if layer.crs() != highlight_crs:
                        geometry.transform(QgsCoordinateTransform(layer.crs(), highlight_crs, QgsProject.instance()))
                    result.highlight.append(geometry)
        plan.groups = [groups[t] for t in sorted(groups, key=_type_rank)]
    return result


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
    if plan.date_in_force:
        decision += f" ({plan.date_in_force})"
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
        out.append(f'<p style="color:{colors["muted"]}; margin-bottom:2px;">Länkar</p><p>{"&nbsp;&nbsp; ".join(links)}</p>')

    for group in plan.groups:
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
            lines.append(_esc(provision.text))
            if provision.category:
                lines.append(f'<span style="color:{colors["muted"]};">{_esc(provision.category)}</span>')
            out.append(
                f'<tr><td style="border-bottom:1px solid {colors["border"]};">{"<br>".join(lines)}</td></tr>'
            )
        out.append("</table>")
    out.append(f'<hr style="color:{colors["border"]};">')
    return "".join(out)
