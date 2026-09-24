# NGP nedladdning

QGIS-plugin för att söka och hämta referensobjekt från Lantmäteriets **Nationella geodataplattform (NGP)** – Strandskydd, Detaljplan, Översiktsplan m.fl. – och spara dem som GeoPackage.

> Status: experimentell. Alla datamängder utom Stompunkt (ännu ej publicerad i produktion) är provade mot API:et.

## Hur det fungerar

Alla NGP-datamängder exponeras på samma sätt:

| | URL |
|---|---|
| Sökning (STAC) | `https://api.lantmateriet.se/distribution/geodatakatalog/sokning/v1/{datamängd}/{version}` |
| Nedladdning av domänobjekt/dokument | `https://api.lantmateriet.se/distribution/geodatakatalog/nedladdning/v1/asset/{uuid}` (303 → fil) |
| Token (OAuth2) | `https://apimanager.lantmateriet.se/oauth2/token` |

Pluginet gör `POST /search` (valfritt filtrerat på delmängder/kommuner, attribut och geografi), följer `next`-länkar, plattar ut attributen och skriver `{datamängd}_{tid}.gpkg` + en `.geojson`. Koordinater är SWEREF 99 TM (EPSG:3006).

Referensobjekten är Lantmäteriets harmoniserade sökversion av domänobjekten (originalen från kommun/myndighet) och **ska inte användas som beslutsunderlag**. Länkarna till domänobjekt och dokument sparas i kolumnen `assets`.

### Resurser

*Hämta resurser för aktivt lager…* laddar ner det som `assets` pekar på via NGP:s nedladdnings-API – domänobjekt och dokument som plankarta, planbeskrivning och beslut. Vilka roller som finns läses ur datat, så det fungerar för alla datamängder utan särskild kod.

- Varje fil hämtas en gång även om många objekt pekar på den (en detaljplan = ett domänobjekt för alla bestämmelser).
- Fyra filer hämtas parallellt; redan hämtade filer hoppas över (`resurser.json` i mappen håller reda på dem).
- Filerna sparas oförändrade i `{geopackage}_resurser/{roll}/` och sökvägen skrivs till kolumnen `resurs_{roll}`.
- Länkar till andra webbplatser (t.ex. Fornsök) hämtas inte.

Domänobjekten sparas som de levereras enligt respektive nationell specifikation – de tolkas inte. Observera att de kan ha ett annat koordinatsystem än referensobjekten (t.ex. kommunens lokala SWEREF 99-zon).

## Autentisering

Pluginet lagrar inga inloggningsuppgifter. Det sparar bara id:t för en konfiguration i **QGIS autentiseringshanterare**; nyckel/hemlighet ligger krypterat i QGIS databas och tokens hämtas och förnyas av QGIS OAuth2-metod.

- **"Ny Lantmäteriet-inloggning…"** skapar en OAuth2-konfiguration (client credentials) med rätt token-URL för vald miljö.
- Alternativt kan valfri befintlig konfiguration väljas (OAuth2, API-header med `Authorization: Bearer …`, Basic).

## Struktur

```
ngp_downloader/
  icon.svg / .png     pluginets ikon (PNG:en renderas från SVG:en)
  metadata.txt        plugin-metadata (QGIS 3.34 – 4.x, Qt6-kompatibel)
  config.py           miljöer, bas-URL:er
  datasets.json       register över datamängder, filter och asset-roller
  core/
    auth.py           skapar OAuth2-konfig i QgsAuthManager
    client.py         STAC-klient (QgsBlockingNetworkRequest + authcfg)
    export.py         utplattning → GeoJSON → GeoPackage
    task.py           QgsTask för hämtning i bakgrunden
    resources.py      hämtning av resurser (assets) per roll
    registry.py       läser datasets.json
  gui/
    dock.py           huvudpanel
    auth_dialog.py    dialog för ny inloggning
    resource_dialog.py  val av resurser att hämta
```

Ny datamängd = en rad i `datasets.json` (id, version, filterattribut).

## Utveckling

Länka in plugin-mappen i QGIS-profilen (kör i `cmd` som administratör eller med utvecklarläge påslaget):

```bat
mklink /J "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\ngp_downloader" "C:\GITHUB\ngp-downloader\ngp_downloader"
```

Starta om QGIS, aktivera *NGP nedladdning* under Insticksprogram. Använd gärna *Plugin Reloader* under utveckling. Loggar hamnar i fliken *NGP nedladdning* i loggpanelen.

## Installera

Pluginet finns inte i det officiella plugin-repot. Lägg i stället till det här repot som plugin-källa i QGIS:

1. *Insticksprogram → Hantera och installera → Inställningar → Lägg till…*
2. URL: `https://raw.githubusercontent.com/matself/ngp-downloader/main/plugins.xml`
3. Kryssa i *Visa även experimentella insticksprogram* (pluginet är markerat experimentellt).
4. Sök efter *NGP nedladdning* och installera. Nya versioner visas sedan som vanliga uppdateringar.

Alternativt: hämta zip-filen under [Releases](https://github.com/matself/ngp-downloader/releases) och välj *Installera från ZIP*.

## Ny version

1. Höj `version` i `ngp_downloader/metadata.txt` och committa.
2. `python build.py` – skapar `dist/ngp_downloader-<version>.zip` och uppdaterar `plugins.xml`.
3. Committa `plugins.xml`, pusha och skapa releasen:
   ```
   gh release create v<version> dist/ngp_downloader-<version>.zip --title "v<version>"
   ```

För en intern källa, t.ex. en nätverksdisk: `python build.py --base-url file:///S:/qgis-plugins` och kopiera zip-filen och `plugins.xml` dit.

## Att göra

- [ ] Verifiera och fyll i filter för Detaljplan, Översiktsplan m.fl.
- [ ] QML-stilar per datamängd

## Licens

GPL-2.0-or-later, se [LICENSE](LICENSE). En kopia ligger även i `ngp_downloader/` eftersom plugins.qgis.org kräver licensfilen i plugin-paketet.

## AI-stöd

Koden är utvecklad med hjälp av AI (Claude). All kod granskas och testas av författaren innan release.
