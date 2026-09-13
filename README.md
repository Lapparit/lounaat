# Hervannan lounaat 🍽️

Automaattisesti päivittyvä HTML-sivu joka näyttää Hervannan ravintoloiden lounaslistat yhdellä sivulla.

## Mitä tämä sisältää

- `scrape.py` — Python-scripti joka käy hakemassa lounaslistat
- `laatu.py` — Tarkistaa haetun datan ja päättää julkaistaanko se
- `tarkista_data.py` — Varmistaa että `lounaat.json` on rakenteeltaan ehjä
- `test_scrape.py` — Testit, jotka ajetaan jokaisesta muutoksesta
- `lounaat.json` — Tallennettu data (luodaan ensimmäisen ajon jälkeen)
- `index.html` — Sivu joka näyttää lounaat selaimessa
- `.github/workflows/paivita.yml` — Hakee uudet listat joka yö
- `.github/workflows/julkaise.yml` — Julkaisee sivun GitHub Pagesissa
- `.github/workflows/testit.yml` — Ajaa testit jokaisesta muutoksesta

## Vaiheittainen pystytys (sinulle joka et osaa koodata)

### 1. Luo GitHub-tili (jos ei ole)

Mene osoitteeseen https://github.com → "Sign up". Ilmainen.

### 2. Luo uusi repositorio

1. Klikkaa oikeasta yläkulmasta `+` → `New repository`
2. Nimi: esim. `lounaat-tampere` (tai mikä tahansa)
3. Valitse **Public** (jotta GitHub Pages toimii ilmaiseksi)
4. Älä valitse "Add README" — meillä on jo
5. Klikkaa `Create repository`

### 3. Lataa tiedostot reposta

Helpoin tapa: **GitHub Web-käyttöliittymä**.

1. Sinulla on nyt tyhjä repo. Klikkaa "uploading an existing file" -linkkiä.
2. Vedä tähän kaikki tiedostot ja kansiot tästä projektista:
   - `scrape.py`
   - `index.html`
   - `requirements.txt`
   - `.gitignore`
   - `README.md`
   - `.github` -kansio (sisältää workflows-alikansion)
3. Kirjoita commit-viesti, esim. "Ensimmäinen versio"
4. Klikkaa `Commit changes`

**Huom:** jos `.github`-kansio ei tule mukaan vetämällä, sinun täytyy tehdä se manuaalisesti:
- Klikkaa `Add file` → `Create new file`
- Kirjoita nimeksi: `.github/workflows/paivita.yml`
- Liitä sisältö
- Toista tiedostolle `.github/workflows/julkaise.yml`

### 4. Aktivoi GitHub Actions ja Pages

**GitHub Actions** (jotta scriptit ajetaan automaattisesti):

1. Mene reposi `Actions`-välilehdelle
2. Jos näkyy "Workflows aren't being run on this forked repository" -viesti, klikkaa että haluat ajaa ne. Yleensä uusilla repoilla tämä ei tule esiin.

**GitHub Pages** (jotta sivu julkaistaan nettiin):

1. Mene reposi `Settings`-välilehdelle
2. Vasemmasta sivupalkista valitse `Pages`
3. Kohdassa "Build and deployment", "Source": valitse `GitHub Actions`
4. Tallenna

### 5. Aja scraper ensimmäisen kerran

Scraperi tarvitsee ajaa ensimmäisen kerran että `lounaat.json` syntyy.

1. Mene `Actions`-välilehdelle
2. Klikkaa vasemmalta `Päivitä lounaat`
3. Oikealla on nappi `Run workflow` → klikkaa sitä → klikkaa vihreää `Run workflow` -nappia
4. Odota 1-2 minuuttia. Sivu päivittyy ja näet työn etenemisen.
5. Kun työ on valmis (vihreä ✓), `lounaat.json` on tallennettu repoon.

### 6. Avaa sivusi

Sivun osoite on muotoa:

```
https://KAYTTAJANIMESI.github.io/REPOSI-NIMI/
```

Esim. jos käyttäjänimesi on `matti` ja repo on `lounaat-tampere`:
`https://matti.github.io/lounaat-tampere/`

Voit löytää tarkan osoitteen `Settings → Pages` -sivulta.

Voi mennä 5-10 minuuttia ennen kuin sivu on saatavilla ensimmäisen kerran.

## Mitä jatkossa?

- **Joka yö** GitHub Actions ajaa scriptin automaattisesti ja päivittää lounaat
- Sivu päivittyy itsestään
- **Et joudu tekemään mitään** ellei jonkin ravintolan sivu muutu — ja silloinkin
  saat siitä automaattisen ilmoituksen (katso "Automaattinen laadunvalvonta")

## Automaattinen laadunvalvonta

Ravintoloiden sivut muuttuvat aika ajoin, ja silloin jokin scraperi lakkaa
toimimasta. Tämä hoituu ilman että sinun tarvitsee seurata mitään:

1. **Sivusto ei mene tyhjäksi.** Jos ravintolan lista näyttää rikkinäiseltä
   (tyhjä, sama teksti joka päivälle, hintoja tai yhteystietoja ruokien
   seassa, poikkeuksellisen pitkiä rivejä), edellisen onnistuneen haun lista
   jää näkyviin. Kortissa lukee silloin "Ei päivittynyt" ja päivämäärä.
2. **Saat ilmoituksen.** Jos sama ravintola on rikki yli 60 tuntia, GitHub
   avaa automaattisesti issuen "Scraper rikki: <ravintola>". Sähköposti tulee
   GitHubin omista ilmoituksista. Yksi issue per ravintola — samasta viasta ei
   tule uutta viestiä joka aamu. Kun lista toimii taas, issue sulkeutuu itse.
3. **Rikkinäinen muutos ei pääse sivustolle.** Jokaisesta pull requestista ja
   main-haaran pushista ajetaan testit ja `lounaat.json`:n rakennetarkistus.

Viikonloppu ei laukaise hälytystä: osa lähteistä julkaisee uuden viikon listan
vasta maanantaina, ja 60 tunnin raja on tätä väljempi.

### Kun issue ilmestyy

Avaa Claude Code ja sano esimerkiksi *"korjaa Kontukeittiön scraper, katso
issue #12"*. Issuessa on ravintolan nimi, lähdeosoite ja mitä tarkistus havaitsi.
Korjauksen jälkeen issue sulkeutuu automaattisesti seuraavassa yöajossa.

## Jos jokin ei toimi

Tämä on melko todennäköistä — jokainen ravintolasivu on erilainen ja niiden rakenne voi muuttua. Yleisscraperi (`scrape_yleinen`) on epäluotettava ja saattaa tuottaa hassuja tuloksia.

**Jos joku ravintola näyttää tyhjältä tai sekavalta:**

1. Avaa scrape.py
2. Etsi kyseisen ravintolan rivi (`RAVINTOLAT`-listassa)
3. Voit pyytää AI-apua kirjoittamaan paremman scrapen vain sille ravintolalle. Anna AI:lle:
   - Linkki ravintolan sivulle
   - Nykyinen scrape.py
   - Pyydä että se kirjoittaa uuden funktion ja päivittää `RAVINTOLAT`-listan

**Jos scriptin ajo epäonnistuu:**

- Mene `Actions`-välilehdelle ja katso virheilmoitus
- Yleisin syy: jonkin ravintolan sivu on alhaalla tai sen rakenne on muuttunut

## Tämän hetkinen tila ravintoloittain

Tila tarkistettu 13.9.2026 GitHub Actions -lokeista ja tallennetusta datasta:

| Ravintola | Tila | Lähde |
|-----------|------|-------|
| Aito kotilounas Sääksjärvi | ✅ Toimii (HTML-lista, PDF varalla) | Oma sivu |
| Caffitella | ✅ Toimii | Oma sivu |
| Farmi (Antell) | ✅ Toimii | Antell |
| Fastelle | ✅ Toimii | Linkosuo |
| Hermia 5 | ✅ Toimii | Sodexo JSON |
| Hermia 6 | ✅ Toimii | Sodexo JSON |
| Munkkimiehet | ✅ Toimii (OCR kuvasta) | Oma sivu |
| Ravintola Osku | ✅ Toimii | Oma sivu |
| Ruskon Helmi | ✅ Toimii | Oma sivu |
| Hertta | ✅ Toimii | Linkosuo |
| Kontukeittiö | ✅ Toimii (oman sivun Lounastaja-widgetin rajapinta, lounaat.info varalla) | Oma sivu |
| Orvokki | ✅ Toimii | Linkosuo |
| Reaktori | ✅ Toimii (sivun upotettu JSON) | Compass Group |
| Sisu | ✅ Toimii arkisin (viikonloppuna lounaat.info ei vielä näytä uutta viikkoa) | Lounaat.info |
| Speakeasy | ✅ Toimii | Oma sivu |
| Heval | 🔗 Vain linkki | — |
| Malabadi | 🔗 Vain linkki | — |
| Malakai | 🔗 Vain linkki | — |

⚠️ = scrapaus saattaa tuottaa hassuja tuloksia, korjattava sen mukaan miltä lopputulos näyttää
