# Synpunkter på NGP Geodatakatalog – erfarenheter från ett QGIS-verktyg

*Utkast, september 2026.*

Vi har byggt ett QGIS-plugin ([NGP nedladdning](https://github.com/matself/ngp-downloader)) mot Geodatakatalogens sök- och nedladdnings-API och testat samtliga publicerade datamängder med produktionsdata. Sammanfattningsvis fungerar plattformen tekniskt väl, men nyttan varierar mellan datamängderna.

## Detaljplan – tydligt mervärde

En helt ny nationell datamängd, utan tidigare samlad distribution. Kopplingen till Boverkets planbestämmelsekatalog fungerar mycket bra (100 % av bestämmelserna i våra uttag matchade), vilket gör det möjligt att automatiskt redovisa planer enligt BFS 2020:6 med beteckningar, färger och symboler.

Önskemål om dokumentation:

- En kombination av användningar (t.ex. B + C) levereras som flera referensobjekt med identisk geometri – det bör framgå.
- Domänobjekten har kommunens koordinatsystem (t.ex. EPSG:3008) och `bbox` i ordningen N–Ö, till skillnad från referensobjekten (EPSG:3006).

## Strandskydd – kan bli den samlande källan

Strandskydd fanns som geodata tidigare men revideras nu. Här kan NGP bli den enande, aktuella nationella källan. Brister vi ser i dag:

- Beslutsobjekt saknar geometri och kommunkod och returneras därför i sin helhet (499 st, hela landet) vid sökning med `bbox`/`intersects`, oavsett område.
- Referensobjektet för en strandskyddsyta saknar koppling till sina beslut och till gällande plan (`beslut` och `gallandePlan` finns bara i domänobjektet). Att ta med dem i referensobjektet skulle göra datat användbart utan att hämta domänobjekt.
- Asset-rollerna i data (`strandskydd`, `beslut`) stämmer inte med specifikationens (`underlag`, `beslutsdokument`), och beslutsdokument saknas.

## Kulturhistorisk lämning – dubblerar RAÄ:s egen distribution

Riksantikvarieämbetet har länge haft en utmärkt distribution: hela lämningsregistret som öppen data (GeoPackage per kommun, län och riket, uppdaterat nattligen) med alla attribut och lägesosäkerhet. NGP:s referensobjekt saknar bl.a. socken och RAÄ-nummer, och beskrivning, terräng m.fl. fält är maskerade (`***`) trots att samma uppgifter är öppna hos RAÄ. För den som vill ladda ner hela datamängden och söka eller tematisera på t.ex. socken är NGP i dag inte ett alternativ.

Antingen bör referensobjektet kompletteras, eller så bör NGP tydligt hänvisa till RAÄ:s distribution.

## Allmänt

- Översiktsplan, Geoteknisk markundersökning och Stompunkt svarar `404` på `/collections`. En publicerad statuslista, eller ett svar som anger att datamängden inte är publicerad, vore till hjälp.
- `/collections` fungerar men saknas i OpenAPI-beskrivningarna, som bara dokumenterar `/search`.
