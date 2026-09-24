"""Generate QML styles for Strandskydd and Kulturhistorisk lämning (NGP and RAÄ).

Run with QGIS' Python, e.g.:
    "C:\\Program Files\\QGIS 3.44.2\\bin\\python-qgis.bat" tools\\make_other_styles.py

Strandskydd follows the legend of NGP's own strandskydd WMS.
Kulturhistorisk lämning follows Fornsök's look: fornlämning as a burnt
orange disc with the rune ᚱ and red areas, övrig kulturhistorisk lämning as
a petrol blue disc with Φ and blue outlines, other statuses grey with ◇.
"""

import base64

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCentroidFillSymbolLayer,
    QgsFillSymbol,
    QgsLinePatternFillSymbolLayer,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsRuleBasedRenderer,
    QgsSvgMarkerSymbolLayer,
)

from make_detaljplan_styles import fill_colour, label_settings, save


def _rule(symbol, label: str, expression: str, active: bool = True) -> QgsRuleBasedRenderer.Rule:
    rule = QgsRuleBasedRenderer.Rule(symbol, 0, 0, expression, label)
    rule.setActive(active)  # inactive = unchecked in the layer panel, can be switched on
    return rule


def _in(field: str, values: list[str]) -> str:
    return f'"{field}" IN (' + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")"


# --- Strandskydd -------------------------------------------------------------

STRANDSKYDDSTYP = "strandskydd_strandskyddstyp"


def strandskydd() -> None:
    """As NGP's own WMS legend: pink where shore protection applies, near-white
    with a dark grey outline for exemptions, repeals and rejected cases."""
    # 70 % transparency; fills chosen to look like the WMS legend over white.
    applies = QgsFillSymbol.createSimple({"color": fill_colour("#fcc7d7"), "outline_color": "#f65081",
                                          "outline_width": "0.5"})
    other = QgsFillSymbol.createSimple({"color": fill_colour("#ffeff9"), "outline_color": "#424242",
                                        "outline_width": "0.4"})
    root = QgsRuleBasedRenderer.Rule(None)
    for typ in ("utvidgat", "generellt, inritat", "infört"):
        root.appendChild(_rule(applies.clone(), typ, f"\"{STRANDSKYDDSTYP}\" = '{typ}'"))
    for typ in ("förordnande om undantag", "undantag, äldre plan", "upphävt i plan",
                "upphävt i enskilda fall", "avvisat"):
        root.appendChild(_rule(other.clone(), typ, f"\"{STRANDSKYDDSTYP}\" = '{typ}'"))
    root.appendChild(_rule(other.clone(), "övrigt", "ELSE"))
    # Suffix-less name: used for the strandskydd layer whether or not the
    # download also held decisions (…_strandskydd or just …).
    save("MultiPolygon", "strandskydd_yta", QgsRuleBasedRenderer(root), field_names=(STRANDSKYDDSTYP,))


# --- Kulturhistorisk lämning -------------------------------------------------

STATUS = "kulturhistoriskLamning_antikvariskBedomning_status"
NUMMER = "kulturhistoriskLamning_lamningsnummer"

# Glyphs drawn as white strokes in a 24x24 box centred on 12,12 (no font needed).
GLYPHS = {
    "runa": "M9.5 6.5 V17.5 M9.5 6.5 L14.5 9.5 L9.5 12.5 L14.5 17.5",  # ᚱ as in Fornsök
    "phi": "M12 6 V18 M12 8.3 C15.2 8.3 15.2 15.7 12 15.7 C8.8 15.7 8.8 8.3 12 8.3",  # Φ
    "romb": "M12 7.5 L16.5 12 L12 16.5 L7.5 12 Z",  # ◇
}
# (label, status or None for ELSE, marker colour, line colour, fill or None, glyph, on)
# On/off as Fornsök's default layer choices.
STATUS_CLASSES = [
    ("Fornlämning", "Fornlämning", "#c84a19", "#e8352b", fill_colour("#f9b1aa"), "runa", True),
    ("Övrig kulturhistorisk lämning", "Övrig kulturhistorisk lämning", "#00547b", "#2f2fe0", None, "phi", True),
    ("Möjlig fornlämning", "Möjlig fornlämning", "#6c6c6c", "#6c6c6c", None, "romb", True),
    ("Uppgift om kulturhistorisk lämning", "Uppgift om kulturhistorisk lämning (ingen antikvarisk bedömning)",
     "#8c8c8c", "#8c8c8c", None, "romb", True),
    ("Före detta kulturhistorisk lämning", "Före detta kulturhistorisk lämning (ingen antikvarisk bedömning)",
     "#a6a6a6", "#a6a6a6", None, "romb", False),
    ("Ej kulturhistorisk lämning", "Ej kulturhistorisk lämning", "#a6a6a6", "#a6a6a6", None, "romb", False),
    ("Övrigt", None, "#6c6c6c", "#6c6c6c", None, "romb", True),
]


def _svg_marker(colour: str, glyph: str, size: float = 5.0):
    """Fornsök-like marker: coloured disc, thin white ring, white glyph; embedded SVG."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<circle cx="12" cy="12" r="11" fill="{colour}" stroke="#ffffff" stroke-width="1.4"/>'
        f'<path d="{GLYPHS[glyph]}" fill="none" stroke="#ffffff" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    layer = QgsSvgMarkerSymbolLayer("base64:" + base64.b64encode(svg.encode()).decode(), size)
    return QgsMarkerSymbol([layer])


def _lamning_symbol(geometry: str, marker: str, line: str, fill: str | None, glyph: str):
    if geometry == "punkt":
        return _svg_marker(marker, glyph)
    if geometry == "linje":
        symbol = QgsLineSymbol.createSimple({"line_color": line, "line_width": "0.6"})
        centre = QgsMarkerLineSymbolLayer()
        centre.setPlacements(Qgis.MarkerLinePlacement.CentralPoint)
        centre.setSubSymbol(_svg_marker(marker, glyph))
        symbol.appendSymbolLayer(centre)
        return symbol
    symbol = QgsFillSymbol.createSimple({
        "color": fill or "0,0,0,0", "outline_color": line, "outline_width": "0.6",
    })
    centroid = QgsCentroidFillSymbolLayer()
    centroid.setPointOnSurface(True)  # inside even for odd shapes
    centroid.setSubSymbol(_svg_marker(marker, glyph))
    symbol.appendSymbolLayer(centroid)
    return symbol


# RAÄ's own register (pub.raa.se downloads): other field names and statuses.
RAA_STATUS, RAA_NUMMER = "antikvariskbedomning", "lamningsnummer"
RAA_STATUS_CLASSES = [
    ("Fornlämning", "Fornlämning", "#c84a19", "#e8352b", fill_colour("#f9b1aa"), "runa", True),
    ("Övrig kulturhistorisk lämning", "Övrig kulturhistorisk lämning", "#00547b", "#2f2fe0", None, "phi", True),
    ("Möjlig fornlämning", "Möjlig fornlämning", "#6c6c6c", "#6c6c6c", None, "romb", True),
    ("Ingen antikvarisk bedömning", "Ingen antikvarisk bedömning", "#8c8c8c", "#8c8c8c", None, "romb", True),
    ("Ej kulturhistorisk lämning", "Ej kulturhistorisk lämning", "#a6a6a6", "#a6a6a6", None, "romb", False),
    ("Övrigt", None, "#6c6c6c", "#6c6c6c", None, "romb", True),
]


def _lamning_styles(prefix: str, status_field: str, number_field: str, classes: list) -> None:
    known = [c[1] for c in classes if c[1]]
    for geometry, qgis_type in (("punkt", "MultiPoint"), ("linje", "MultiLineString"), ("yta", "MultiPolygon")):
        root = QgsRuleBasedRenderer.Rule(None)
        for label, status, marker, line, fill, glyph, on in classes:
            # Not ELSE: an ELSE rule would also catch statuses whose rule is switched off.
            expression = (_in(status_field, [status]) if status
                          else f'"{status_field}" IS NULL OR NOT ({_in(status_field, known)})')
            root.appendChild(_rule(_lamning_symbol(geometry, marker, line, fill, glyph), label, expression, on))
        # Lämningsnummer beside the symbol when zoomed in; off by default as in Fornsök.
        labels = label_settings(f'"{number_field}"', 8, 5000)
        settings = labels.settings()
        settings.dist = 3.0
        labels.setSettings(settings)
        save(qgis_type, f"{prefix}_{geometry}", QgsRuleBasedRenderer(root), labels,
             field_names=(status_field, number_field), labels_on=False)


def kulturhistorisk_lamning() -> None:
    _lamning_styles("kulturhistorisklamning", STATUS, NUMMER, STATUS_CLASSES)


def raa_lamningar() -> None:
    _lamning_styles("raa_lamningar", RAA_STATUS, RAA_NUMMER, RAA_STATUS_CLASSES)
    # Lägesosäkerhet: the area the remain may lie within, hatched grey.
    symbol = QgsFillSymbol.createSimple({"style": "no", "outline_color": "#8c8c8c", "outline_width": "0.25",
                                         "outline_style": "dash"})
    hatch = QgsLinePatternFillSymbolLayer()
    hatch.setLineAngle(45)
    hatch.setDistance(2.0)  # mm, sparse so the remains stay readable
    hatch.setSubSymbol(QgsLineSymbol.createSimple({"line_color": "#a0a0a0", "line_width": "0.15"}))
    symbol.insertSymbolLayer(0, hatch)
    root = QgsRuleBasedRenderer.Rule(None)
    root.appendChild(_rule(symbol, "Lägesosäkerhet", "TRUE"))
    save("MultiPolygon", "raa_lamningar_lagesosakerhet", QgsRuleBasedRenderer(root),
         field_names=("lagesosakerhet_i_meter",))


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    strandskydd()
    kulturhistorisk_lamning()
    raa_lamningar()
    app.exitQgis()
