# NGP Downloader

QGIS-plugin för att söka och hämta referensobjekt från Lantmäteriets **Nationella geodataplattform (NGP)** – Strandskydd, Detaljplan, Översiktsplan m.fl. – och spara dem som GeoPackage.

> Status: tidigt skelett (0.1.0). Ingen datamängd är ännu verifierad mot API:et med riktigt token.

## Hur det fungerar

Alla NGP-datamängder exponeras på samma sätt:

| | URL |
|---|---|
| Sökning (STAC) | `https://api.lantmateriet.se/distribution/geodatakatalog/sokning/v1/{datamängd}/{version}` |
| Nedladdning av domänobjekt/dokument | `https://api.lantmateriet.se/distribution/geodatakatalog/nedladdning/v1/asset/{uuid}` (303 → fil) |
| Token (OAuth2) | `https://apimanager.lantmateriet.se/oauth2/token` |

Pluginet gör `POST /search` (valfritt filtrerat på delmängder/kommuner, attribut och geografi), följer `next`-länkar, plattar ut attributen och skriver `{datamängd}_{tid}.gpkg` + en `.geojson`. Koordinater är SWEREF 99 TM (EPSG:3006).

Referensobjekten är en cachad kopia av domänobjekten och **ska inte användas som beslutsunderlag**. Länkarna till originalobjekt och beslutsdokument sparas i kolumnen `assets`.

## Autentisering

Pluginet lagrar inga inloggningsuppgifter. Det sparar bara id:t för en konfiguration i **QGIS autentiseringshanterare**; nyckel/hemlighet ligger krypterat i QGIS databas och tokens hämtas och förnyas av QGIS OAuth2-metod.

- **"Ny Lantmäteriet-inloggning…"** skapar en OAuth2-konfiguration (client credentials) med rätt token-URL för vald miljö.
- Alternativt kan valfri befintlig konfiguration väljas (OAuth2, API-header med `Authorization: Bearer …`, Basic).

## Struktur

```
ngp_downloader/
  metadata.txt        plugin-metadata (QGIS 3.34 – 4.x, Qt6-kompatibel)
  config.py           miljöer, bas-URL:er
  datasets.json       register över datamängder, filter och asset-roller
  core/
    auth.py           skapar OAuth2-konfig i QgsAuthManager
    client.py         STAC-klient (QgsBlockingNetworkRequest + authcfg)
    export.py         utplattning → GeoJSON → GeoPackage
    task.py           QgsTask för hämtning i bakgrunden
    registry.py       läser datasets.json
  gui/
    dock.py           huvudpanel
    auth_dialog.py    dialog för ny inloggning
```

Ny datamängd = en rad i `datasets.json` (id, version, filterattribut).

## Utveckling

Länka in plugin-mappen i QGIS-profilen (kör i `cmd` som administratör eller med utvecklarläge påslaget):

```bat
mklink /J "%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\ngp_downloader" "C:\GITHUB\ngp-downloader\ngp_downloader"
```

Starta om QGIS, aktivera *NGP Downloader* under Insticksprogram. Använd gärna *Plugin Reloader* under utveckling. Loggar hamnar i fliken *NGP Downloader* i loggpanelen.

## Att göra

- [ ] Verifiera Strandskydd mot API:et (collections, query-syntax, paginering)
- [ ] Hämtning av assets per roll (domänobjekt, beslutsdokument) via nedladdnings-API:et
- [ ] Verifiera och fyll i filter för Detaljplan, Översiktsplan m.fl.
- [ ] QML-stilar per datamängd
- [ ] Ikon

## Licens

GPL-2.0-or-later, se [LICENSE](LICENSE). En kopia ligger även i `ngp_downloader/` eftersom plugins.qgis.org kräver licensfilen i plugin-paketet.

## AI-stöd

Koden är utvecklad med hjälp av AI (Claude). All kod granskas och testas av författaren innan release.
