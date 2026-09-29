# Geodata: NGP (Lantmäteriet)

QGIS plugin to search and download reference objects from Lantmäteriet's **National Geodata Platform (NGP)** — Strandskydd (shoreline protection), Detaljplan (development plan), Översiktsplan (comprehensive plan) and more — and save them as GeoPackage.

The plugin is independent and not developed by Lantmäteriet. "Lantmäteriet" in the name indicates where the data comes from.

The user interface is in Swedish; see [User interface](#user-interface) below for an English explanation of every dialog and label. There is also a full [Swedish user guide](docs/anvandning.md) covering the whole workflow, from login to download, and troubleshooting.

> Strandskydd, Detaljplan, Byggnad, Kulturhistorisk lämning and Gräns för fjällnära skog have been tested against the API. Översiktsplan, Geoteknisk markundersökning and Stompunkt still return 404 (not yet published).

## How it works

All NGP datasets are exposed the same way:

| | URL |
|---|---|
| Search (STAC) | `https://api.lantmateriet.se/distribution/geodatakatalog/sokning/v1/{dataset}/{version}` |
| Domain object/document download | `https://api.lantmateriet.se/distribution/geodatakatalog/nedladdning/v1/asset/{uuid}` (303 → file) |
| Token (OAuth2) | `https://apimanager.lantmateriet.se/oauth2/token` |

The plugin does `POST /search` (optionally filtered on subsets/municipalities, attributes and geography), follows `next` links, flattens the attributes and writes `{dataset}_{time}.gpkg` plus a `.geojson`. Coordinates are SWEREF 99 TM (EPSG:3006).

Objects without geometry (e.g. decisions in Strandskydd) cannot be limited geographically or by attribute — the API returns all of them for the whole dataset. They are therefore dropped when the search has such filters.

The reference objects are Lantmäteriet's harmonised search version of the domain objects (the originals from the municipality/authority) and **must not be used as a basis for decisions**. Links to the domain objects and documents are saved in the `assets` column.

### Notation and colour (Detaljplan)

Plan provisions carry a reference to Boverket's provision catalogue (planbestämmelsekatalog). The plugin fetches the catalogue from Boverket's open API (`api.boverket.se/planbestammelsekatalogen`), caches it in the QGIS profile for 30 days, and adds the columns `planbestammelse_beteckning` (notation, e.g. `B`, `GATA`, `e`), `planbestammelse_farg` (colour name, e.g. `Gul`/Yellow), `planbestammelse_symbol` (e.g. `Prickmark (1949 - 2020)`) and `planbestammelse_etikett` — the notation, or for height symbols a value such as `nh 9` (ridge height), `th 3`, `bh 7`, `27°` — per Boverket's general guidelines BFS 2020:6. The colour is given as a name; neither Boverket nor the catalogue gives colour values.

Source: Boverket, Planbestämmelsekatalogen (the provision catalogue).

### Styles

When a style exists at `styles/{dataset}_{layer}.qml`, it is applied when the layer is added, and saved as the default style in the GeoPackage file so the file opens styled even without the plugin. Detaljplan follows Boverket's general guidelines BFS 2020:6:

- `anvandning` (use): colour from `planbestammelse_farg` (70% transparency), use boundary and notation (`B`, `BC`, `GATA` …). Combinations are merged into one polygon with the colour of the first notation.
- Provisions of the same type with exactly the same polygon in the same plan are merged into one object (`antal_bestammelser`, provision count), so one polygon gets one label (`BC`, `b e f h o p`). The provision texts are kept, joined with ` + `.
- `egenskap_*` (property): property boundary without fill, notation in italics (`e`, `p` …). Provisions denoted by symbol are drawn as raster fills from the `planbestammelse_symbol` column: dot pattern, cross pattern, rings (floor structures, structures below ground) and combinations.
- `plan`: plan area boundary. `administrativ` (administrative) is hidden by default.

BFS 2020:6 gives the colours as names, not values. The palette is modelled on Lantmäteriet's own map and lives in `tools/make_detaljplan_styles.py`, which rebuilds the QML files (run with QGIS Python).

**Strandskydd** (`tools/make_other_styles.py`): styled like NGP's own WMS, with 70% transparency — pink with a pink-red outline where shoreline protection applies (extended, generally mapped, introduced), near-white with a dark grey outline for exemptions, revocations and rejected. One legend entry per shoreline-protection type. Note that the general shoreline protection (100 m from the shoreline) is usually not mapped as a polygon — the absence of a polygon at a location does not mean shoreline protection does not apply there.

**Kulturhistorisk lämning** (cultural heritage site): styled as in Fornsök (the Swedish National Heritage Board's search service) — ancient monuments (fornlämning) as a bright orange symbol with the rune ᚱ and red polygons (70% transparency) and lines, other cultural heritage sites as a petrol-blue symbol with Φ and blue outlines, other statuses grey with ◇. Polygons and lines get the symbol at their centre. As in Fornsök's own defaults, former and non-heritage sites are unchecked in the layer panel and site numbers (label from 1:5000 scale) are off; everything can be switched on. The symbols are embedded SVG and need no font.

### Resources

*Hämta resurser för aktivt lager…* ("Fetch resources for active layer…") downloads what `assets` points to via NGP's download API — domain objects and documents such as plan maps, plan descriptions and decisions. Which roles exist is read from the data, so it works for any dataset without dataset-specific code.

- Each file is fetched once even if many objects point to it (one detaljplan = one domain object for all its provisions).
- Four files are fetched in parallel; already-fetched files are skipped (`resurser.json` in the folder keeps track of them).
- Files are saved unchanged under `{geopackage}_resurser/{role}/`, and the path is written to the `resurs_{role}` column.
- Links to other websites (e.g. Fornsök) are not fetched.

Domain objects are saved as delivered, per the relevant national specification — they are not interpreted. Note that they may use a different coordinate system than the reference objects (e.g. the municipality's local SWEREF 99 zone).

## Heritage sites from the Swedish National Heritage Board (Riksantikvarieämbetet)

NGP's *Kulturhistorisk lämning* is a search index with few attributes (no parish/socken or RAÄ number, masked texts). For the full register there is the **Lämningar (RAÄ, hela registret)** dataset: the plugin downloads RAÄ's open GeoPackage per municipality, county or all of Sweden from `pub.raa.se/nedladdning/datauttag/lamningar_v1/` (updated nightly, no login required).

- *Hämta lista* ("Fetch list") shows municipalities, counties and all of Sweden with file size; check one or more and click *Hämta* ("Fetch"; the button reads *Avbryt hämtning* / "Cancel download" while it runs).
- The file is saved as `{RAÄ file name}_{date}_{time}.gpkg`, so a new download never overwrites an already-loaded file. Points, lines and polygons are added with the Fornsök style and all attributes (`socken` (parish), `raa_nummer` (RAÄ number), `lamningstyp` (site type), `beskrivning` (description), `terrang` (terrain) …); the positional-uncertainty attribute (lägesosäkerhet) comes along as its own layer, unchecked by default.
- The file also contains the tables `lamning` (site), `egenskap` (property: type, form, find material …) and `ingaendelamning` (constituent sites).

## Authentication

NGP datasets require your own login: request access to NGP's Geodata Catalogue from Lantmäteriet via [Geotorget](https://geotorget.lantmateriet.se/), which gives you a *consumer key* and *consumer secret*. The account must have permission for the datasets you want to download. Heritage sites from RAÄ need no login.

The plugin stores no login credentials itself. It only saves the id of a configuration in **QGIS' authentication manager**; the key/secret is stored encrypted in QGIS' database, and tokens are fetched and renewed by QGIS' own OAuth2 method.

- **"Ny Lantmäteriet-inloggning…"** ("New Lantmäteriet login…") creates an OAuth2 (client credentials) configuration with the right token URL for the selected environment.
- Alternatively, any existing configuration can be selected (OAuth2, API header with `Authorization: Bearer …`, Basic).

## User interface

The user interface is in Swedish. This section explains it in English so the plugin can be reviewed and tested without knowing Swedish.

### Main panel (dock widget)

Opened from the *Web* menu and the *Web* toolbar, entry *Geodata: NGP (Lantmäteriet)*. Lets you pick an authentication, a dataset and subsets, an optional area filter, then download the dataset as GeoPackage; and fetch linked resources (documents, plan maps) for the active layer.

| Swedish label | English meaning | What it does |
|---|---|---|
| Fristående plugin, inte utvecklat av Lantmäteriet. | Independent plugin, not developed by Lantmäteriet. | Note shown at the top of the panel |
| Miljö | Environment | Chooses the NGP environment: production or verification (test) |
| Ny Lantmäteriet-inloggning… | New Lantmäteriet login… | Opens the [auth dialog](#new-login-dialog) to create an OAuth2 configuration |
| Datamängd | Dataset | Group box for choosing what to download |
| Delmängder (ingen vald = alla) | Subsets (none selected = all) | Multi-select list of the dataset's subsets/collections; nothing selected means all |
| Hämta lista | Fetch list | Loads the list of subsets/collections from NGP |
| Geografisk avgränsning | Geographic extent | Group box for the area filter |
| Kartans utsträckning | Map extent | Option to limit the search to the current map canvas extent |
| Hämta | Download / Fetch | Starts the download (main panel), or fetch action in other dialogs (see below) |
| Hämta resurser för aktivt lager… | Fetch resources for active layer… | Opens the [resource dialog](#fetch-resources-dialog) for the currently active NGP layer |

### Messages (main panel)

| Swedish message | English meaning |
|---|---|
| Välj eller skapa en autentisering först. | Select or create an authentication first. |
| kommaseparerade värden | comma-separated values (hint for a text filter) |
| Kunde inte hämta delmängder – {error} | Could not fetch subsets – {error} |
| {n} delmängder hämtade. | {n} subsets fetched. |
| En hämtning pågår redan. | A download is already running. |
| Välj en utdatamapp. | Select an output folder. |
| Hämtar… (följ förloppet i aktivitetshanteraren) | Fetching… (follow progress in the Task Manager) |
| Hämtningen misslyckades: {error} | Download failed: {error} |
| En resurshämtning pågår redan. | A resource download is already running. |
| Välj ett lager hämtat med Geodata: NGP (Lantmäteriet). | Select a layer fetched with Geodata: NGP (Lantmäteriet). |
| Resurshämtningen misslyckades: {error} | Resource download failed: {error} |
| Hämtar {n} resurser… (följ förloppet i aktivitetshanteraren) | Fetching {n} resources… (follow progress in the Task Manager) |
| {n} filer från Riksantikvarieämbetet (uppdateras varje natt). | {n} files from the Swedish National Heritage Board (updated nightly). |
| Hämta listan och välj minst en kommun eller ett län. | Fetch the list and select at least one municipality or county. |
| Avbryt hämtning | Cancel download (button label while a download is running) |
| RAÄ-hämtningen misslyckades: {error} | RAÄ download failed: {error} |
| Lämningar från RAÄ hämtade: {names} | Heritage sites from RAÄ fetched: {names} |

### New login dialog

Opened from *Ny Lantmäteriet-inloggning…* in the main panel. Creates a QGIS OAuth2 (client credentials) authentication configuration for the selected NGP environment.

| Swedish label | English meaning | What it does |
|---|---|---|
| Ny inloggning för Lantmäteriet (NGP) | New login for Lantmäteriet (NGP) | Dialog title |
| (name field, default "Lantmäteriet NGP") | | Name of the saved authentication configuration |
| Miljö | Environment | Which NGP environment (production/verification) the token URL points to |
| Ange både key och secret. | Enter both key and secret. | Validation message if either field is empty |

### Fetch resources dialog

Opened from *Hämta resurser för aktivt lager…*. Lists the resources (assets) available for the selected features (or the whole active layer if none are selected) and downloads the ones you choose.

| Swedish label | English meaning | What it does |
|---|---|---|
| Hämta resurser | Fetch resources | Dialog title |
| Hämta: | Fetch: | Label above the list of resource roles to fetch |
| Hämta | Fetch | Confirms and starts the download |
| okänd storlek | unknown size | Shown when a file's size is not known in advance |
| Objekten har inga resurser att hämta via NGP. | The objects have no resources to fetch via NGP. | Shown when there is nothing to download |
| Länkar till andra webbplatser hämtas inte ({names}); de finns kvar i kolumnen assets. | Links to other websites are not fetched ({names}); they remain in the assets column. | Informational note |
| Varje fil hämtas en gång även om flera objekt pekar på den. Redan hämtade filer hoppas över. | Each file is fetched once even if several objects point to it. Already-fetched files are skipped. | Informational note |

## Structure

```
ngp_downloader/
  icon.svg / .png     plugin icon (the PNG is rendered from the SVG)
  metadata.txt        plugin metadata (QGIS 3.34 - 4.x, Qt6-compatible)
  config.py           environments, base URLs
  datasets.json        dataset registry, filters and asset roles
  core/
    auth.py           creates an OAuth2 config in QgsAuthManager
    client.py         STAC client (QgsBlockingNetworkRequest + authcfg)
    export.py         flattening -> GeoJSON -> GeoPackage
    task.py           QgsTask for background downloads
    resources.py      resource (asset) download per role
    raa.py            RAÄ's heritage site register as a download source
    styles.py         applies a style from styles/ and saves it in the GeoPackage
    planbestammelser.py  notation and colour from Boverket's provision catalogue
    registry.py       reads datasets.json
  styles/             QML per dataset and layer, e.g. detaljplan_anvandning.qml
  gui/
    dock.py           main panel
    auth_dialog.py    new-login dialog
    resource_dialog.py  choice of resources to fetch
```

A new dataset = one row in `datasets.json` (id, version, filter attributes).

## Development

Link the plugin folder into the QGIS profile (run in `cmd` as administrator, or with developer mode enabled):

```bat
mklink /J "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\ngp_downloader" "C:\GITHUB\ngp-downloader\ngp_downloader"
```

Restart QGIS, enable *Geodata: NGP (Lantmäteriet)* under Plugins (Insticksprogram). *Plugin Reloader* is handy during development. Logs go to the *Geodata: NGP (Lantmäteriet)* tab in the log panel.

## Install

1. *Plugins → Manage and Install Plugins*
2. Search for *Geodata: NGP (Lantmäteriet)* and install.

Alternatively: download the zip file from [Releases](https://github.com/matself/ngp-downloader/releases) and use *Install from ZIP*.

## New release

1. Bump `version` in `ngp_downloader/metadata.txt`, update `changelog=` there and in `CHANGELOG.md`, and commit.
2. `python build.py` — builds `dist/ngp_downloader.<version>.zip` and updates `plugins.xml`.
3. Commit `plugins.xml`, push and create the release:
   ```
   gh release create v<version> dist/ngp_downloader.<version>.zip --title "v<version>"
   ```

For an internal source, e.g. a network share: `python build.py --base-url file:///S:/qgis-plugins` and copy the zip file and `plugins.xml` there.

## To do

- [ ] Let the user choose the download file name (instead of the automatic `{dataset}_{time}`)
- [ ] Add new layers and groups collapsed in the QGIS layer panel
- [ ] Verify and fill in filters for Detaljplan, Översiktsplan and others
- [ ] QML styles for more datasets (currently exist for Detaljplan, Strandskydd and Kulturhistorisk lämning)
- [ ] Detaljplan: secondary property boundary and remaining symbol notations (lines, arrows, etc.)

## Feedback to Lantmäteriet

Experience with NGP per dataset is collected in [docs/synpunkter-lantmateriet.md](docs/synpunkter-lantmateriet.md) (in Swedish).

## License

GPL-2.0-or-later, see [LICENSE](LICENSE). A copy is also kept in `ngp_downloader/`, since plugins.qgis.org requires the license file inside the plugin package.

## AI assistance

The code is developed with the help of AI (Claude). All code is reviewed and tested by the author before release.
