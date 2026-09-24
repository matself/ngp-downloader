"""Generate QML styles for Strandskydd and Kulturhistorisk lämning.

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
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsRuleBasedRenderer,
    QgsSvgMarkerSymbolLayer,
)

from make_detaljplan_styles import fill_colour, label_settings, save


def _rule(symbol, label: str, expression: str) -> QgsRuleBasedRenderer.Rule:
    return QgsRuleBasedRenderer.Rule(symbol, 0, 0, expression, label)


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
# (label, statuses, marker colour, line colour, fill rgba or None, glyph)
STATUS_CLASSES = [
    ("Fornlämning", ["Fornlämning"], "#c84a19", "#e8352b", fill_colour("#f9b1aa"), "runa"),
    ("Övrig kulturhistorisk lämning", ["Övrig kulturhistorisk lämning"], "#00547b", "#2f2fe0", None, "phi"),
    ("Möjlig fornlämning / övriga", [], "#6c6c6c", "#6c6c6c", None, "romb"),  # ELSE
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


def kulturhistorisk_lamning() -> None:
    for geometry, qgis_type in (("punkt", "MultiPoint"), ("linje", "MultiLineString"), ("yta", "MultiPolygon")):
        root = QgsRuleBasedRenderer.Rule(None)
        for label, statuses, marker, line, fill, glyph in STATUS_CLASSES:
            expression = _in(STATUS, statuses) if statuses else "ELSE"
            root.appendChild(_rule(_lamning_symbol(geometry, marker, line, fill, glyph), label, expression))
        # Lämningsnummer beside the symbol when zoomed in.
        labels = label_settings(f'"{NUMMER}"', 8, 5000)
        settings = labels.settings()
        settings.dist = 3.0
        labels.setSettings(settings)
        save(qgis_type, f"kulturhistorisklamning_{geometry}", QgsRuleBasedRenderer(root), labels,
             field_names=(STATUS, NUMMER))


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    strandskydd()
    kulturhistorisk_lamning()
    app.exitQgis()
