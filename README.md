# Hervannan lounaat 🍽️

Automaattisesti päivittyvä HTML-sivu joka näyttää Hervannan ravintoloiden lounaslistat yhdellä sivulla.

## Mitä tämä sisältää

- `scrape.py` — Python-scripti joka käy hakemassa lounaslistat
- `lounaat.json` — Tallennettu data (luodaan ensimmäisen ajon jälkeen)
- `index.html` — Sivu joka näyttää lounaat selaimessa
- `.github/workflows/paivita.yml` — Hakee uudet listat joka aamu
- `.github/workflows/julkaise.yml` — Julkaisee sivun GitHub Pagesissa

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

- **Joka arkiaamu klo 7** GitHub Actions ajaa scriptin automaattisesti ja päivittää lounaat
- Sivu päivittyy itsestään
- **Et joudu tekemään mitään** ellei jonkin ravintolan sivu muutu

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

Kaikki on parhaan arvioni mukaan, mutta ensimmäisen ajon jälkeen pitää tarkistaa jotka oikeasti toimivat:

| Ravintola | Tila | Lähde |
|-----------|------|-------|
| Sisu Buffet | ✅ Pitäisi toimia | Lounaat.info |
| Speakeasy | ✅ Pitäisi toimia | Oma sivu |
| Reaktori (FoodCo) | ✅ Pitäisi toimia | Oma sivu |
| Hertta | ✅ Pitäisi toimia | Linkosuo |
| Orvokki | ✅ Pitäisi toimia | Linkosuo |
| Fastelle | ✅ Pitäisi toimia | Linkosuo |
| Hermia 5 | ✅ Pitäisi toimia | Sodexo JSON |
| Hermia 6 | ⚠️ ID tarkistettava | Sodexo JSON |
| Hermianfarmi (Antell) | ⚠️ Yleisscraperi | Antell |
| Munkkimiehet | ⚠️ Yleisscraperi | Oma sivu |
| Ruskonhelmi | ⚠️ Yleisscraperi | Oma sivu |
| Ravintola Osku | ⚠️ Yleisscraperi | Oma sivu |
| Aitokoti | ⚠️ Yleisscraperi | Oma sivu |
| Caffitella | ⚠️ Yleisscraperi | Oma sivu |
| Kontukeittiö | ⚠️ Yleisscraperi | Oma sivu |
| Idaho | 🔗 Vain linkki | Facebook |
| Malabadi | 🔗 Vain linkki | — |
| Gate of India | 🔗 Vain linkki | — |

⚠️ = scrapaus saattaa tuottaa hassuja tuloksia, korjattava sen mukaan miltä lopputulos näyttää
