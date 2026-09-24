# NGP nedladdning

QGIS-plugin för att söka och hämta referensobjekt från Lantmäteriets **Nationella geodataplattform (NGP)** – Strandskydd, Detaljplan, Översiktsplan m.fl. – och spara dem som GeoPackage.

> Status: experimentell. Strandskydd, Detaljplan, Byggnad, Kulturhistorisk lämning och Gräns för fjällnära skog är provade mot API:et. Översiktsplan, Geoteknisk markundersökning och Stompunkt svarar ännu 404 (inte publicerade).

## Hur det fungerar

Alla NGP-datamängder exponeras på samma sätt:

| | URL |
|---|---|
| Sökning (STAC) | `https://api.lantmateriet.se/distribution/geodatakatalog/sokning/v1/{datamängd}/{version}` |
| Nedladdning av domänobjekt/dokument | `https://api.lantmateriet.se/distribution/geodatakatalog/nedladdning/v1/asset/{uuid}` (303 → fil) |
| Token (OAuth2) | `https://apimanager.lantmateriet.se/oauth2/token` |

Pluginet gör `POST /search` (valfritt filtrerat på delmängder/kommuner, attribut och geografi), följer `next`-länkar, plattar ut attributen och skriver `{datamängd}_{tid}.gpkg` + en `.geojson`. Koordinater är SWEREF 99 TM (EPSG:3006).

Objekt utan geometri (t.ex. beslut i Strandskydd) kan inte avgränsas geografiskt eller på attribut – API:et returnerar alla i hela datamängden. De tas därför bort när sökningen har sådana filter.

Referensobjekten är Lantmäteriets harmoniserade sökversion av domänobjekten (originalen från kommun/myndighet) och **ska inte användas som beslutsunderlag**. Länkarna till domänobjekt och dokument sparas i kolumnen `assets`.

### Beteckning och färg (Detaljplan)

Planbestämmelser har en referens till Boverkets planbestämmelsekatalog. Pluginet hämtar katalogen från Boverkets öppna API (`api.boverket.se/planbestammelsekatalogen`), cachar den i QGIS-profilen i 30 dagar och lägger till kolumnerna `planbestammelse_beteckning` (t.ex. `B`, `GATA`, `e`) och `planbestammelse_farg` (t.ex. `Gul`) `planbestammelse_symbol` (t.ex. `Prickmark (1949 - 2020)`) och `planbestammelse_etikett` – beteckningen, eller för höjdsymboler ett värde som `nh 9` (nockhöjd), `th 3`, `bh 7`, `27°` – enligt Boverkets allmänna råd BFS 2020:6. Färgen anges som namn – varken Boverket eller katalogen anger färgvärden.

Källa: Boverket, Planbestämmelsekatalogen.

### Stilar

Finns en stil i `styles/{datamängd}_{lager}.qml` läggs den på när lagret läggs till, och sparas som standardstil i GeoPackage-filen så att filen öppnas med stil även utan pluginet. Detaljplan följer Boverkets allmänna råd BFS 2020:6:

- `anvandning`: färg efter `planbestammelse_farg` (70 % transparens), användningsgräns och beteckning (`B`, `BC`, `GATA` …). Kombinationer är sammanslagna till en yta med den första beteckningens färg.
- Bestämmelser av samma typ med exakt samma yta i samma plan slås ihop till ett objekt (`antal_bestammelser`), så att en yta får en etikett (`BC`, `b e f h o p`). Bestämmelsetexterna behålls sammanfogade med ` + `.
- `egenskap_*`: egenskapsgräns utan fyllning, beteckning i kursiv (`e`, `p` …). Bestämmelser som betecknas med symbol ritas som raster efter kolumnen `planbestammelse_symbol`: prickmark, korsmark, ringar (bjälklag, byggnadsverk under mark) och kombinationer.
- `plan`: planområdesgräns. `administrativ` är dold från början.

BFS 2020:6 anger färgerna som namn, inte värden. Paletten är modellerad på Lantmäteriets karta och finns i `tools/make_detaljplan_styles.py`, som bygger om QML-filerna (körs med QGIS Python).

**Strandskydd** (`tools/make_other_styles.py`): som NGP:s egen WMS, med 70 % transparens – rosa med rosaröd kontur där strandskydd gäller (utvidgat, generellt inritat, infört), nästan vit med mörkgrå kontur för undantag, upphävanden och avvisat. En legend-post per strandskyddstyp. Observera att det generella strandskyddet (100 m från strandlinjen) i regel inte är inritat – att en plats saknar yta betyder inte att strandskydd saknas.

**Kulturhistorisk lämning**: som i Fornsök – fornlämning som brandorange symbol med runan ᚱ och röda ytor (70 % transparens) och linjer, övrig kulturhistorisk lämning som petrolblå symbol med Φ och blå konturer, övriga statusar (möjlig fornlämning, uppgift om, före detta) grå med ◇. Ytor och linjer får symbolen i mitten. Lämningsnummer som etikett från 1:5000. Symbolerna är inbäddade SVG och kräver inget typsnitt.

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
    styles.py         lägger på stil från styles/ och sparar den i GeoPackage
    planbestammelser.py  beteckning och färg från Boverkets planbestämmelsekatalog
    registry.py       läser datasets.json
  styles/             QML per datamängd och lager, t.ex. detaljplan_anvandning.qml
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
- [ ] QML-stilar för fler datamängder (finns för Detaljplan, Strandskydd och Kulturhistorisk lämning)
- [ ] Detaljplan: sekundär egenskapsgräns och övriga symbolbeteckningar (linjer, pilar m.m.)

## Licens

GPL-2.0-or-later, se [LICENSE](LICENSE). En kopia ligger även i `ngp_downloader/` eftersom plugins.qgis.org kräver licensfilen i plugin-paketet.

## AI-stöd

Koden är utvecklad med hjälp av AI (Claude). All kod granskas och testas av författaren innan release.
