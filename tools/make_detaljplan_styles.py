"""Generate the Detaljplan QML styles in ngp_downloader/styles/.

Run with QGIS' Python, e.g.:
    "C:\\Program Files\\QGIS 3.44.2\\bin\\python-qgis.bat" tools\\make_detaljplan_styles.py

Follows Boverkets allmänna råd BFS 2020:6: colour per use (as named in
planbestammelse_farg), notation as label, and the boundary line types
(planområdesgräns, användningsgräns, egenskapsgräns). BFS 2020:6 names the
colours but gives no colour values; TARGET holds the colour an area should
appear as over a white map (modelled on Lantmäteriet's map), and the fill
colour is derived from it for the chosen fill opacity.
"""

from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointPatternFillSymbolLayer,
    QgsPalLayerSettings,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont

OUT = Path(__file__).resolve().parent.parent / "ngp_downloader" / "styles"
FILL_OPACITY = 0.3  # 70 % transparency: the background map shows through.
# Sizes in mm, tuned for legibility at 1:2000.
LABEL_USE, LABEL_PROPERTY = 12, 10

# Apparent colour over white per colour name in planbestammelse_farg.
TARGET = {
    "Gul": "#f5f68f",
    "Brun": "#e4cbb1",
    "Röd": "#f1b3a6",
    "Rosa": "#e6c8cc",
    "Orange": "#e9c08f",
    "Beige": "#ece5cf",
    "Lila": "#dac8e8",
    "Cerise": "#f2bcd8",
    "Blågrå": "#c6cfdc",
    "Grå": "#d3d3d3",
    "Ljusgrå": "#ececec",
    "Grön": "#bfe3b1",
    "Ljusgrön": "#cff5cc",
    "Mörkgrön": "#a8d3a2",
    "Blågrön": "#b6e1d9",
    "Blå": "#8ac6fd",
    "Ljusblå": "#c9e5fc",
}
INK = "#1a1a1a"


def fill_colour(target: str) -> str:
    """Colour that, at FILL_OPACITY over white, looks like `target`."""
    t = QColor(target)
    base = [
        max(0, min(255, round((c - (1 - FILL_OPACITY) * 255) / FILL_OPACITY)))
        for c in (t.red(), t.green(), t.blue())
    ]
    return "{},{},{},{}".format(*base, round(FILL_OPACITY * 255))


# Line types from BFS 2020:6 (dash patterns in mm).
def planomradesgrans() -> QgsLineSymbol:  # ▬▬ ▬▬ ● ▬▬ ▬▬ ●
    return QgsLineSymbol.createSimple({
        "line_color": INK, "line_width": "0.9", "capstyle": "round",
        "use_custom_dash": "1", "customdash": "3.8;1.5;3.8;1.5;0.01;1.5", "customdash_unit": "MM",
    })


def anvandningsgrans() -> QgsLineSymbol:  # ▬ ▪ ▬ ▪
    return QgsLineSymbol.createSimple({
        "line_color": INK, "line_width": "0.5", "capstyle": "flat",
        "use_custom_dash": "1", "customdash": "3.4;1.0;0.6;1.0", "customdash_unit": "MM",
    })


def egenskapsgrans(colour: str = INK) -> QgsLineSymbol:  # — ·· — ··
    return QgsLineSymbol.createSimple({
        "line_color": colour, "line_width": "0.35", "capstyle": "flat",
        "use_custom_dash": "1", "customdash": "3.4;0.8;0.35;0.6;0.35;0.8", "customdash_unit": "MM",
    })


def outline_only(line: QgsLineSymbol) -> QgsFillSymbol:
    """Polygon symbol drawn with just `line` as its boundary."""
    symbol = QgsFillSymbol.createSimple({"style": "no", "outline_style": "no"})
    symbol.changeSymbolLayer(0, _outline_layer(line))
    return symbol


def _outline_layer(line: QgsLineSymbol):
    # A line symbol layer inside a fill symbol ("Outline: Simple line") keeps
    # the custom dash pattern, which a plain fill outline cannot have.
    return line.symbolLayer(0).clone()


def filled(fill: str) -> QgsFillSymbol:
    symbol = QgsFillSymbol.createSimple({"color": fill, "outline_style": "no"})
    symbol.appendSymbolLayer(_outline_layer(anvandningsgrans()))
    return symbol


# Raster symbols for property provisions, by catalogue symbol name
# (planbestammelse_symbol). Pre-2020 and current names share a pattern.
SYMBOL_PATTERNS = {
    "prickar": ["Prickmark (1949 - 2020)",
                "Marken får inte förses med byggnad/byggnadsverk (2020 - pågående)"],
    "kors": ["Korsmark (1949 - 2020)",
             "Marken får endast förses med viss typ av byggnadsverk (2020 - pågående)"],
    "ringar": ["Marken får byggas under/över med körbart bjälklag (1949 - 2015)",
               "Mark för byggnad under gatuplanet (1976 - 1986)",
               "Marken får endast förses med byggnadsverk under mark (2020 - pågående)"],
    "kors_prickar": ["Mark där uthus o dyl undantagsvis får uppföras (1949 - 1986)"],
    "ringar_prickar": ["Marken får byggas under/över med ett bjälklag som planteras (1949 - 2015)"],
}
SPACING = 5.0  # mm between symbols; rows are staggered by half of it


def _marker(kind: str) -> QgsMarkerSymbol:
    if kind == "prick":
        return QgsMarkerSymbol.createSimple({"name": "circle", "color": INK, "outline_style": "no", "size": "1.0"})
    if kind == "kors":
        return QgsMarkerSymbol.createSimple({"name": "cross", "color": INK, "outline_color": INK,
                                             "outline_width": "0.4", "size": "2.4"})
    return QgsMarkerSymbol.createSimple({"name": "circle", "color": "0,0,0,0", "outline_color": INK,
                                         "outline_width": "0.4", "size": "2.0"})  # ring


def _pattern(kind: str, shift: float = 0.0) -> QgsPointPatternFillSymbolLayer:
    layer = QgsPointPatternFillSymbolLayer()
    layer.setSubSymbol(_marker(kind))
    layer.setDistanceX(SPACING)
    layer.setDistanceY(SPACING)
    layer.setDisplacementX(SPACING / 2)
    layer.setOffsetX(shift)
    # Only whole symbols inside the area, like on a plan map.
    layer.setClipMode(Qgis.MarkerClipMode.CentroidWithin)
    return layer


def patterned(name: str) -> QgsFillSymbol:
    kinds = {"prickar": ["prick"], "kors": ["kors"], "ringar": ["ring"],
             "kors_prickar": ["kors", "prick"], "ringar_prickar": ["ring", "prick"]}[name]
    symbol = outline_only(egenskapsgrans())
    for i, kind in enumerate(kinds):
        # A second symbol kind sits between the first one's positions.
        symbol.insertSymbolLayer(0, _pattern(kind, shift=i * SPACING / 2))
    return symbol


def label_settings(expression: str, size: float, max_scale: int, italic=False, bold=False, **extra):
    s = QgsPalLayerSettings()
    s.fieldName = expression
    s.isExpression = True
    fmt = QgsTextFormat()
    font = QFont("Arial")
    font.setItalic(italic)
    font.setBold(bold)
    fmt.setFont(font)
    fmt.setSize(size)
    fmt.setColor(QColor(INK))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor(255, 255, 255, 190))
    fmt.setBuffer(buffer)
    s.setFormat(fmt)
    s.scaleVisibility = True
    s.minimumScale = max_scale  # QGIS: "minimum" is the most zoomed-out scale
    s.maximumScale = 1
    for key, value in extra.items():
        setattr(s, key, value)
    return QgsVectorLayerSimpleLabeling(s)


DETALJPLAN_FIELDS = (
    "planbestammelse_etikett", "planbestammelse_farg", "planbestammelse_symbol", "detaljplan_beteckning",
)


def save(geometry: str, name: str, renderer, labeling=None, field_names=DETALJPLAN_FIELDS,
         labels_on: bool = True) -> None:
    fields = "&".join(f"field={f}:string" for f in field_names)
    layer = QgsVectorLayer(f"{geometry}?crs=EPSG:3006&{fields}", name, "memory")
    layer.setRenderer(renderer)
    if labeling:
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(labels_on)
    _msg, ok = layer.saveNamedStyle(str(OUT / f"{name}.qml"))
    print(f"{name}.qml", "ok" if ok else "FEL")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    # Notation, or a value like 'nh 9' for height symbols; merged areas carry all of them.
    beteckning = 'coalesce("planbestammelse_etikett", \'\')'

    # Användning: fill per colour name, användningsgräns, notation as label.
    root = QgsRuleBasedRenderer.Rule(None)
    for colour, target in TARGET.items():
        root.appendChild(QgsRuleBasedRenderer.Rule(
            filled(fill_colour(target)), 0, 0, f"\"planbestammelse_farg\" = '{colour}'", colour))
    root.appendChild(QgsRuleBasedRenderer.Rule(
        outline_only(anvandningsgrans()), 0, 0, "ELSE", "Ofärgad / okänd färg"))
    # Inside the area only: labels of narrow parks and streets would otherwise
    # drift into neighbouring blocks.
    inside = {"placement": Qgis.LabelPlacement.Horizontal, "fitInPolygonOnly": True}
    save("MultiPolygon", "detaljplan_anvandning", QgsRuleBasedRenderer(root),
         label_settings(beteckning, LABEL_USE, 12000, bold=True, **inside))

    # Egenskap: no fill, egenskapsgräns, notation in italics.
    props = QgsRuleBasedRenderer.Rule(None)
    for name, symbols in SYMBOL_PATTERNS.items():
        names = ", ".join("'" + n.replace("'", "''") + "'" for n in symbols)
        props.appendChild(QgsRuleBasedRenderer.Rule(
            patterned(name), 0, 0, f"\"planbestammelse_symbol\" IN ({names})", name.replace("_", " + ")))
    props.appendChild(QgsRuleBasedRenderer.Rule(outline_only(egenskapsgrans()), 0, 0, "ELSE", "Egenskapsgräns"))
    # Merged properties ('b e f m nh 9 p') wrap into short lines to fit the area.
    save("MultiPolygon", "detaljplan_egenskap_yta", QgsRuleBasedRenderer(props),
         label_settings(beteckning, LABEL_PROPERTY, 5000, italic=True, autoWrapLength=7, **inside))
    save("MultiLineString", "detaljplan_egenskap_linje", QgsSingleSymbolRenderer(egenskapsgrans()),
         label_settings(beteckning, LABEL_PROPERTY, 5000, italic=True))
    save("MultiPoint", "detaljplan_egenskap_punkt",
         QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
             {"name": "circle", "color": INK, "outline_style": "no", "size": "1.3"})),
         label_settings(beteckning, LABEL_PROPERTY, 5000, italic=True))

    # Administrativ: hidden by default; dashed violet outline.
    admin = QgsLineSymbol.createSimple({"line_color": "#7a4a9a", "line_width": "0.4", "line_style": "dash"})
    save("MultiPolygon", "detaljplan_administrativ", QgsSingleSymbolRenderer(outline_only(admin)),
         label_settings(beteckning, LABEL_PROPERTY, 5000, italic=True))

    # Plan: planområdesgräns.
    save("MultiPolygon", "detaljplan_plan", QgsSingleSymbolRenderer(outline_only(planomradesgrans())))


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    main()
    app.exitQgis()
