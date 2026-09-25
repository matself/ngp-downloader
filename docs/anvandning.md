# Användning

> **Fristående plugin.** Det här pluginet är inte utvecklat, granskat eller supportat av Lantmäteriet. Namnet Lantmäteriet
> används bara för att säga vilka tjänster pluginet fungerar mot. Frågor om pluginet ställer du i
> [det här repots ärenden](https://github.com/matself/ngp-downloader/issues), inte till Lantmäteriets support. Data hämtas
> från Lantmäteriets tjänster och omfattas av deras användningsvillkor.

NGP Downloader (Lantmäteriet) hämtar referensobjekt från Lantmäteriets **Nationella geodataplattform (NGP)**, till exempel
Strandskydd, Detaljplan och Byggnad, och sparar dem som GeoPackage. Här finns också en datamängd med lämningar från
Riksantikvarieämbetet. Den här sidan går igenom hela flödet och vad man gör när något inte fungerar.

## Innan du börjar

Du behöver:

* **QGIS 3.34 eller senare** (enligt pluginets metadata).
* **Åtkomst till NGP:s Geodatakatalog** för de datamängder du vill hämta, se nedan. Lämningar från Riksantikvarieämbetet
  kräver ingen inloggning.

### Skaffa åtkomst till NGP

1. Logga in på [Geotorget](https://geotorget.lantmateriet.se/) och välj *Nationella geodataplattformen*.
2. Under *Bli konsument*, klicka på *Ansök* och godkänn användarvillkoren. Åtkomsten till API:erna kommer automatiskt, men
   kan ta några minuter.
3. Logga in i [API-managern](https://apimanager.lantmateriet.se/) med ditt konto och skapa en **application**. Prenumerera på
   de API:er för Geodatakatalog som ingår i NGP (sökning och nedladdning).
4. Under *Production Keys*, generera nycklar och kopiera **Consumer Key** och **Consumer Secret**.

Pluginet använder nycklarna för att logga in mot NGP. Kontot måste ha behörighet till de datamängder du vill hämta.

Nycklar för ett konto av typen *NGP-konsument* fungerar för NGP men inte för Lantmäteriets ortofoto- och höjdnedladdning. För
dem finns [LM-STAC Downloader](https://github.com/matself/LM-STAC-Downloader), som använder nycklar från ett
konto av typen *Geodataprodukter*.

## 1. Skapa en inloggning

1. Öppna panelen via webbmenyn (*Webb → NGP Downloader (Lantmäteriet)*) eller ikonen i verktygsfältet.
2. Under **Anslutning**, välj **Miljö**: *Produktion* eller *Verifikation*. Verifikation är Lantmäteriets testmiljö.
3. Väljaren **Autentisering** är QGIS egen. Välj en befintlig konfiguration (OAuth 2, API-header med
   `Authorization: Bearer …` eller Basic), eller klicka på **Ny Lantmäteriet-inloggning…**.
4. I dialogen anger du namn, miljö, Consumer Key och Consumer Secret. Pluginet skapar en OAuth 2-konfiguration (Client
   Credentials) i QGIS autentiseringshanterare med rätt token-adress för den miljön. Nyckeln sparas krypterat av QGIS,
   inte av pluginet.

QGIS kan be om huvudlösenord första gången.

## 2. Välj datamängd

Under **Datamängd** väljer du vad du vill hämta:

| Datamängd | Kommentar |
|---|---|
| Strandskydd | Filter på strandskyddstyp och kommunkod. |
| Detaljplan | Stil enligt Boverkets allmänna råd BFS 2020:6. Delas upp i ett lager per typ av bestämmelse. |
| Byggnad | |
| Kulturhistorisk lämning | Ett sökindex med få attribut, se *Lämningar från Riksantikvarieämbetet* nedan för hela registret. |
| Gräns för fjällnära skog | |
| Lämningar (RAÄ, hela registret) | Hämtas från Riksantikvarieämbetet, ingen inloggning. |
| Översiktsplan, Geoteknisk markundersökning, Stompunkt | Märkta *ej verifierad*: de svarar ännu 404 (inte publicerade). |

Datamängder som inte hunnit publiceras hos Lantmäteriet svarar med felet *datamängden finns inte i vald miljö*. Det är ett
fel hos leverantören och inget pluginet kan lösa.

### Delmängder

Många datamängder är uppdelade, oftast per kommun. Klicka på **Hämta lista** för att se delmängderna, och kryssa i de du vill
ha. Skriv i rutan *Filtrera lista…* för att söka i listan. **Ingen vald betyder alla.**

### Filter

För vissa datamängder finns ett eller flera fält att fylla i, till exempel *Strandskyddstyp* och *Kommunkod*. Ange värden
skilda med komma. Placeholdern visar förslag på värden. Lämnar du dem tomma filtreras inget bort.

## 3. Avgränsa geografiskt

Under **Geografisk avgränsning** väljer du en av:

* **Ingen**: hela datamängden (eller de delmängder du valt).
* **Kartans utsträckning**: det som syns i kartan just nu.
* **Valda objekt i aktivt lager**: markera ett eller flera objekt i ett vektorlager först. Deras sammanlagda yta används.

Avgränsningen räknas om till SWEREF 99 TM (EPSG:3006), som NGP använder. Den gäller inte lämningar från
Riksantikvarieämbetet, som hämtas som hela kommuner eller län.

**Objekt utan geometri**, till exempel vissa beslut i Strandskydd, kan inte avgränsas geografiskt eller på attribut. API:et
returnerar alla sådana objekt i hela datamängden. När du har ett geografiskt filter eller ett attributfilter tar pluginet
därför bort de objekt som saknar geometri.

## 4. Hämta

1. Välj en **utdatamapp** under *Utdata*.
2. Klicka **Hämta**. Hämtningen körs i bakgrunden och du följer förloppet i statusraden och i QGIS aktivitetshanterare.
   NGP anger inte hur många objekt det totalt finns, så förloppet visas som antal hämtade objekt och inte som procent.

Resultatet blir:

* en GeoPackage, `<datamängd>_<datum>_<tid>.gpkg`, och en `.geojson` med samma innehåll, i din utdatamapp. Koordinaterna är
  SWEREF 99 TM (EPSG:3006).
* ett eller flera lager som läggs till i projektet. När en hämtning ger flera lager, till exempel en detaljplan med olika
  typer av bestämmelser, hamnar de i en grupp med hämtningens namn.

Attributen plattas ut till kolumner. Länkar till domänobjekt och dokument sparas i kolumnen `assets`.

Referensobjekten är Lantmäteriets harmoniserade sökversion av originalen från kommun eller myndighet, och **ska inte användas
som beslutsunderlag**.

### Detaljplan: beteckning och färg

Planbestämmelserna har en referens till Boverkets planbestämmelsekatalog. Pluginet hämtar katalogen från Boverkets öppna
API och sparar den i QGIS-profilen i 30 dagar. Den ger extra kolumner:

* `planbestammelse_beteckning`, till exempel `B`, `GATA`, `e`
* `planbestammelse_farg`, färgen som namn, till exempel `Gul`
* `planbestammelse_symbol`, till exempel `Prickmark (1949 - 2020)`
* `planbestammelse_etikett`, beteckningen, eller för höjdsymboler ett värde som `nh 9` (nockhöjd)

Bestämmelser av samma typ med exakt samma yta i samma plan slås ihop till ett objekt (`antal_bestammelser`), så att en yta får
en etikett. Bestämmelsetexterna behålls sammanfogade med ` + `.

### Stilar

För Detaljplan, Strandskydd och Kulturhistorisk lämning läggs en färdig stil på lagret och sparas som standardstil i
GeoPackage-filen, så filen öppnas med stil även utan pluginet. Stilarna följer Boverkets allmänna råd BFS 2020:6, NGP:s egen
WMS respektive Fornsök. Lagret *administrativ* (Detaljplan) är avslaget från början.

Det generella strandskyddet (100 m från strandlinjen) är i regel inte inritat. Att en plats saknar yta betyder alltså inte
att strandskydd saknas.

## 5. Hämta resurser (dokument och domänobjekt)

Objekten pekar på domänobjekt och dokument som plankarta, planbeskrivning och beslut. Du hämtar dem så här:

1. Gör lagret från din hämtning aktivt. Markera gärna de objekt du vill hämta för.
2. Klicka **Hämta resurser för aktivt lager…** under *Resurser*.
3. I dialogen väljer du **Endast valda objekt** eller **Alla objekt**, och vilka **resurstyper** (roller) du vill ha. Listan visar
   antal filer och storlek för varje.
4. Klicka **Hämta**.

* Varje fil hämtas en gång, även om många objekt pekar på den. En detaljplan är ett domänobjekt för alla dess bestämmelser.
* Fyra filer hämtas åt gången, och redan hämtade filer hoppas över (`resurser.json` i mappen håller reda på dem).
* Filerna sparas oförändrade i `<geopackage>_resurser/<roll>/`. Sökvägen skrivs till en ny kolumn `resurs_<roll>` i lagret,
  och är klickbar i attributformuläret.
* Länkar till andra webbplatser, till exempel Fornsök, hämtas inte. De finns kvar i kolumnen `assets`.

Domänobjekten sparas som de levereras enligt respektive nationell specifikation. De tolkas inte, och de kan ha ett annat
koordinatsystem än referensobjekten, till exempel kommunens lokala SWEREF 99-zon.

## Lämningar från Riksantikvarieämbetet

NGP:s *Kulturhistorisk lämning* är ett sökindex med få attribut: ingen socken eller RAÄ-nummer, och maskerade texter. För
hela registret finns datamängden **Lämningar (RAÄ, hela registret)**. Den hämtas direkt från Riksantikvarieämbetets öppna
GeoPackage-filer, per kommun, per län eller för hela Sverige. Filerna uppdateras varje natt, och ingen inloggning behövs.

1. Välj datamängden *Lämningar (RAÄ, hela registret)*.
2. Klicka **Hämta lista**. Kommuner, län och hela Sverige visas med filstorlek.
3. Kryssa i en eller flera och klicka **Hämta**. Under hämtningen heter knappen **Avbryt hämtning**. Väljer du ingen fil
   görs ingenting, så du hämtar aldrig hela Sverige av misstag.

* Filen sparas som `<RAÄ:s filnamn>_<datum>_<tid>.gpkg`, så en ny hämtning skriver aldrig över en tidigare.
* Punkter, linjer och ytor läggs till med Fornsök-stil och alla attribut (till exempel `socken`, `raa_nummer`,
  `lamningstyp`, `beskrivning`). Lägesosäkerheten följer med som eget lager, avslaget från början.
* Filen innehåller också tabellerna `lamning`, `egenskap` och `ingaendelamning`.

Sökområdet och filtren gäller inte här.

## Felsökning

**"Välj eller skapa en autentisering först".** Ingen inloggning är vald. Skapa eller välj en under *Anslutning*.

**"Kunde inte hämta delmängder" eller HTTP 401/403.** Nycklarna gäller inte för den miljön eller saknar behörighet till
datamängden. Kontrollera att du valt rätt miljö (*Produktion* eller *Verifikation*), att applikationen prenumererar på NGP:s
API:er och att kontot har ansökt om att bli NGP-konsument.

**"HTTP 404: datamängden finns inte i vald miljö".** Datamängden är inte publicerad hos Lantmäteriet, eller finns inte i den
miljön. Det gäller bland annat Översiktsplan, Geoteknisk markundersökning och Stompunkt.

**Sökningen gav inga träffar.** Kontrollera avgränsningen och filtren. Har du valt *Kartans utsträckning* måste kartan visa
området du vill ha.

**Objekt saknas i resultatet.** Objekt utan geometri tas bort när du använder geografiskt filter eller attributfilter. Se
avsnittet *Avgränsa geografiskt*.

**"Välj ett lager hämtat med NGP Downloader (Lantmäteriet)".** Resurshämtningen kräver att det aktiva lagret har kolumnen
`assets`, alltså att det kommer från en hämtning med pluginet.

**Inloggningen frågar efter huvudlösenord.** QGIS skyddar autentiseringsdatabasen. Ange ditt huvudlösenord.

Loggmeddelanden hittar du i QGIS *Loggmeddelanden*-panel, under fliken *NGP Downloader (Lantmäteriet)*.
