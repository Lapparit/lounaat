"""
Tampereen lähilounaslistojen kerääjä.

Käy läpi listan ravintoloita, hakee niiden lounaslistat ja tallentaa
tulokset tiedostoon lounaat.json.

Päivien nimet normalisoidaan muotoon "Maanantai", "Tiistai", jne.
ennen tallennusta — sivun JavaScript hoitaa loput.

Käyttö: python scrape.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fi,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


PAIVA_NIMET = ["Maanantai", "Tiistai", "Keskiviikko", "Torstai",
               "Perjantai", "Lauantai", "Sunnuntai"]

PAIVA_INDEKSI = {nimi.lower(): i for i, nimi in enumerate(PAIVA_NIMET)}
# Lisätään myös englanninkielisille
PAIVA_INDEKSI.update({
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
})


def hae_sivu(url: str) -> str | None:
    """Hakee yhden URLin sisällön. Palauttaa None jos epäonnistuu."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"  ! Virhe haettaessa {url}: {e}")
        return None


def normalisoi_paiva(teksti: str) -> str:
    """
    Muuntaa minkä tahansa päivätekstin pelkkään viikonpäivän nimeen.

    "Maanantaina 27.4." → "Maanantai"
    "TIISTAI"           → "Tiistai"
    "ke 29.4."          → "Keskiviikko"
    "2026-04-28"        → "Tiistai" (päivämäärästä)

    Jos viikonpäivää ei löydy, palautetaan alkuperäinen siivottuna.
    """
    if not teksti:
        return ""

    # 1. Yritä ensin tunnistaa viikonpäivä tekstistä
    teksti_lower = teksti.lower()

    # Pisin sopiva nimi ensin (jotta "torstaina" ei matchaa "ti")
    nimet_pituuden_mukaan = sorted(
        list(PAIVA_INDEKSI.keys()),
        key=len,
        reverse=True,
    )
    for nimi in nimet_pituuden_mukaan:
        if nimi in teksti_lower:
            return PAIVA_NIMET[PAIVA_INDEKSI[nimi]]

    # 2. Lyhenteet (ma, ti, ke, to, pe) — vain jos koko sana
    lyhenteet = {"ma": 0, "ti": 1, "ke": 2, "to": 3, "pe": 4, "la": 5, "su": 6}
    sanat = re.split(r"[\s,.\-]+", teksti_lower)
    for sana in sanat:
        if sana in lyhenteet:
            return PAIVA_NIMET[lyhenteet[sana]]

    # 3. Päivämäärä-muoto (esim. "2026-04-28" tai "27.4.2026")
    # ISO 8601: yyyy-mm-dd
    iso_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", teksti)
    if iso_match:
        try:
            d = datetime(int(iso_match[1]), int(iso_match[2]), int(iso_match[3]))
            return PAIVA_NIMET[d.weekday()]
        except (ValueError, OverflowError):
            pass

    # Suomalainen: dd.mm.yyyy
    fi_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", teksti)
    if fi_match:
        try:
            d = datetime(int(fi_match[3]), int(fi_match[2]), int(fi_match[1]))
            return PAIVA_NIMET[d.weekday()]
        except (ValueError, OverflowError):
            pass

    # Ei löytynyt — palautetaan alkuperäinen
    return teksti.strip()


def normalisoi_paivat(paivat: list[dict]) -> list[dict]:
    """Normalisoi listan päivien nimet ja järjestä ma-pe."""
    tulos = []
    nahdyt = set()
    for p in paivat:
        nimi = normalisoi_paiva(p.get("paiva", ""))
        if nimi and nimi in PAIVA_NIMET and nimi not in nahdyt:
            nahdyt.add(nimi)
            tulos.append({"paiva": nimi, "ruoat": p.get("ruoat", [])})
    # Järjestä ma-pe
    tulos.sort(key=lambda p: PAIVA_NIMET.index(p["paiva"]))
    return tulos


def siivoa(teksti: str) -> str:
    """Siivoa whitespace-virheet tekstistä."""
    return re.sub(r"\s+", " ", teksti).strip()


# Allergeenitiedot ja muut termit jotka voi tunnistaa sulkujen sisältä.
# Jos sulkujen sisus koostuu PELKÄSTÄÄN näistä sanoista (pilkulla erotettuna),
# koko sulkupätkä poistetaan.
ALLERGEENISANAT = {
    # Lyhenteet
    "a", "g", "l", "m", "v", "vs", "vl", "gl", "veg", "vegaani", "kasvis", "kasvi",
    "ilm", "mr", "saa", "ssaa", "saa veg", "vegan",
    # Yleiset allergeenit suomeksi
    "maito", "muna", "munat", "kananmuna", "vehnä", "ohra", "ruis", "kaura",
    "soija", "soja", "selleri", "sinappi", "kala", "äyriäinen", "äyriäiset",
    "nivelelain", "siemen", "siemenet", "seesami", "seesaminsiemen", "pähkinä",
    "pähkinät", "maapähkinä", "maapähkinät",
    "lupiini", "simpukka", "simpukat", "sulfiitti", "sulfiitit",
    "rikkidioksidi", "gluteeni",
    # Joskus listattuja: alkuperätietojen yhteydessä (jätetään pois suoraan)
}


def siivoa_ruoka(rivi: str) -> str | None:
    """
    Siivoaa yksittäisen ruokarivin: poistaa allergeenitiedot, hinnat ja
    kellonajat. Pudottaa puuro-/aamupala-rivit.

    Palauttaa puhdistetun rivin tai None jos rivi pitää pudottaa.
    """
    if not rivi:
        return None
    s = rivi.strip()
    if not s:
        return None

    # 1) Poista hinnat: "á 2,30 €", "8,90e", "1,50€/kpl", "12,20€", "10€"
    # Numero (mahdollisella desimaalilla) + e/E/€ + mahdollinen suffiksi.
    # Lookahead varmistaa että €/e on oikea hintamerkki (ei osa sanaa).
    s = re.sub(
        r"\s*á?\s*\d+(?:[,.]\d+)?\s*[€eE](?=[\s/,.;)]|$)(?:\s*/\s*\w+)?",
        " ",
        s,
    )

    # 2) Poista kellonajat: "klo 7.45-9.30", "8.00-9.30", "10:30-13:00"
    s = re.sub(
        r"\s*\bklo\s*\d{1,2}[:.]\d{2}\s*[–-]\s*\d{1,2}[:.]\d{2}",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(
        r"\s*\b\d{1,2}[:.]\d{2}\s*[–-]\s*\d{1,2}[:.]\d{2}\b",
        "",
        s,
    )

    # 3) Poista allergeenisulut: ne joiden sisus on pelkkiä allergeenisanoja.
    # Esim. "(maito)", "(L, G)", "(VEG, G)", "(suomalaista broileria)" jää.
    def poista_allergeenisulut(m: re.Match) -> str:
        sisus = m.group(1).strip()
        if not sisus or len(sisus) > 50:
            return m.group(0)
        # Jaa pilkuilla ja välilyönneillä
        osat = re.split(r"[,\s/]+", sisus.lower())
        osat = [o.strip().rstrip(".") for o in osat if o.strip()]
        if not osat:
            return m.group(0)
        # Sallitaan myös pelkkä 1-2 merkin "koodi" (G, GL, VEG jne.) vaikka ei
        # olisi listalla. Myös merkit kuten "*" ja "#" sallitaan (Reaktori käyttää).
        def on_allergeeni(s: str) -> bool:
            if s in ALLERGEENISANAT:
                return True
            # Yksittäinen erikoismerkki kuten "*", "#", "-"
            if len(s) == 1 and not s.isalnum():
                return True
            # Lyhyt isokirjaiminen koodi alkuperäisessä tekstissä
            return len(s) <= 4 and s.replace(".", "").isalpha()
        if all(on_allergeeni(o) for o in osat):
            return " "  # välilyönti ettei viereiset sanat liimaudu yhteen
        return m.group(0)

    s = re.sub(r"\s*\(([^()]+)\)", poista_allergeenisulut, s)

    # 4) Poista lopussa olevat irralliset allergeenikoodit.
    # Eri muotoja:
    #   "M, G", "L, G, M", "A, G, L, M, Veg"   ← pilkulla erotettu
    #   "l g k", "M G"                         ← välilyönnillä erotettu, lyhyet
    #   "L KASVIS", "Riisi Veg"                ← yksi koodi lopussa

    # 4a) Pilkulla erotetut: vähintään 2 lyhyttä "sanaa" (1-6 merkkiä)
    # Sallitaan 6 merkkiä koska KASVIS on 6 ja vegaani 7 — tämä riskeeraa
    # syödä oikeita sanoja jos rivi päättyy esim. "Salaatti, kurkku"
    s = re.sub(
        r"\s+[A-Za-zÄÖäö]{1,7}(?:\s*,\s*[A-Za-zÄÖäö]{1,7}){1,}\s*$",
        "",
        s,
    )
    # 4b) Välilyönnillä erotetut LYHYET (1-3 merkkiä), vähintään 2 peräkkäin
    #     Esim. "l g k", "M G", "A, L M G" (loppupätkä)
    s = re.sub(
        r"\s+[A-Za-zÄÖäö]{1,3}(?:\s+[A-Za-zÄÖäö]{1,3}){1,}\s*$",
        "",
        s,
    )
    # 4c) Yksittäinen isokirjaiminen koodi tai "Veg"/"Kasvis" lopussa
    s = re.sub(r"\s+[A-ZÄÖ]{1,4}\s*$", "", s)
    s = re.sub(r"\s+[Vv]eg\.?\s*$", "", s)
    s = re.sub(r"\s+[Kk]asvis\s*$", "", s)

    # Siisti välilyönnit
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(",;:-")  # Joskus jää roikkumaan välimerkki

    if not s or len(s) < 4:
        return None

    # 5) Pudota aamupala-/puurorivit (Hertta, Fastelle alkavat puurolla)
    s_lower = s.lower()
    aamupala_avainsanat = ("puuro", "porridge")
    if any(w in s_lower for w in aamupala_avainsanat):
        return None

    return s


def siivoa_ruoat(ruoat: list[str]) -> list[str]:
    """Soveltaa siivoa_ruoka kaikkiin ruokariveihin, suodattaa Nonet pois."""
    tulos = []
    for r in ruoat:
        siivottu = siivoa_ruoka(r)
        if siivottu is not None:
            tulos.append(siivottu)
    return tulos


# ============================================================
# RAVINTOLAKOHTAISET SCRAPERIT
# ============================================================


def scrape_sisu_buffet() -> list[dict]:
    url = "https://lounaat.info/lounas/sisu-buffet-hervanta/tampere"
    return _scrape_lounaat_info_yleinen(url)


def scrape_speakeasy() -> list[dict]:
    """Speakeasy Hervanta."""
    html = hae_sivu("https://www.speakeasy.fi/hervanta/lounas/")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    teksti = soup.get_text("\n", strip=True)

    paivat_nimet = ["MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI", "PERJANTAI"]
    palat = re.split(r"(" + "|".join(paivat_nimet) + r")", teksti)

    paivat = []
    nykyinen = None
    for pala in palat:
        pala = pala.strip()
        if pala in paivat_nimet:
            nykyinen = pala
        elif nykyinen:
            rivit = [r.strip() for r in pala.split("\n") if r.strip()]
            ruoat = []
            for rivi in rivit:
                if rivi.startswith("L =") or rivi == "Texas Pete Burger":
                    break
                if len(rivi) < 4:
                    continue
                ruoat.append(rivi)
            if ruoat:
                paivat.append({"paiva": nykyinen, "ruoat": ruoat[:6]})
            nykyinen = None
    return paivat


def scrape_kontukeittio() -> list[dict]:
    """Kontukeittiö Hervanta — Lounaat.infosta."""
    url = "https://lounaat.info/lounas/konnun-keittio-hervanta/tampere"
    return _scrape_lounaat_info_yleinen(url)


def _scrape_lounaat_info_yleinen(url: str) -> list[dict]:
    """Lounaat.info-yleinen scraperi: h3=päivä, ul=ruoat."""
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    paiva_re = re.compile(r"^(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)", re.I)

    for h3 in soup.find_all("h3"):
        otsikko = h3.get_text(strip=True)
        if not (paiva_re.match(otsikko) and re.search(r"\d{1,2}\.\d{1,2}", otsikko)):
            continue
        ul = h3.find_next("ul")
        if not ul:
            continue
        ruoat = []
        for li in ul.find_all("li"):
            t = siivoa(li.get_text(" "))
            if "katso päivän lounaslista" in t.lower():
                continue
            if t.lower().startswith("lounas kello"):
                continue
            if "alkaen lounaan hinta" in t.lower():
                continue
            if t and len(t) > 2:
                ruoat.append(t)
        if ruoat:
            paivat.append({"paiva": otsikko, "ruoat": ruoat})
    return paivat


def scrape_reaktori() -> list[dict]:
    """Reaktori (FoodCo / Compass-Group)."""
    url = "https://www.compass-group.fi/ravintolat-ja-ruokalistat/foodco/kaupungit/tampere/reaktori/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    paiva_re = re.compile(r"^(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)\s+\d", re.I)

    for h3 in soup.find_all("h3"):
        teksti = h3.get_text(strip=True)
        if not paiva_re.match(teksti):
            continue
        ruoat = []
        for sis in h3.find_all_next():
            if sis.name == "h3":
                break
            if sis.name == "h4":
                ryhma = sis.get_text(strip=True)
                if any(s in ryhma for s in ["Lounas", "Kasvislounas", "Vegaaninen"]):
                    ul = sis.find_next("ul")
                    if ul:
                        for li in ul.find_all("li"):
                            t = siivoa(li.get_text(" "))
                            if t and len(t) > 3:
                                ruoat.append(t)
        if ruoat:
            paivat.append({"paiva": teksti, "ruoat": ruoat[:8]})
    return paivat


def scrape_linkosuo(url: str) -> list[dict]:
    """Linkosuo (Hertta, Orvokki) — dl/dt/dd-rakenne."""
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    for dl in soup.find_all("dl"):
        dt_lista = dl.find_all("dt")
        dd_lista = dl.find_all("dd")
        for dt, dd in zip(dt_lista, dd_lista):
            paiva = dt.get_text(" ", strip=True)
            teksti = dd.get_text("\n", strip=True)
            ruoat = [r.strip() for r in teksti.split("\n") if r.strip()]
            if paiva and ruoat:
                paivat.append({"paiva": paiva, "ruoat": ruoat})
    return paivat


def scrape_fastelle() -> list[dict]:
    """
    Fastelle — sama dl/dt/dd-rakenne kuin muilla Linkosuoilla, MUTTA
    sisältää sekä suomi- että englanti-listan, eroteltuna '**'-merkillä.
    """
    url = "https://linkosuo.fi/toimipaikka/ravintola-fastelle/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    for dl in soup.find_all("dl"):
        dt_lista = dl.find_all("dt")
        dd_lista = dl.find_all("dd")
        for dt, dd in zip(dt_lista, dd_lista):
            paiva = dt.get_text(" ", strip=True)
            teksti = dd.get_text("\n", strip=True)

            # Katkaistaan englannin osuus pois
            if "**" in teksti:
                teksti = teksti.split("**")[0]

            ruoat = [r.strip() for r in teksti.split("\n") if r.strip()]
            ruoat = [r for r in ruoat if r and r != "*" and r != "**"]
            if paiva and ruoat:
                paivat.append({"paiva": paiva, "ruoat": ruoat})
    return paivat


def scrape_sodexo(rajapinta_id: int) -> list[dict]:
    """Sodexo — virallinen JSON-rajapinta."""
    url = f"https://www.sodexo.fi/ruokalistat/output/weekly_json/{rajapinta_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ! Sodexo {rajapinta_id} virhe: {e}")
        return []

    paivat = []
    for paiva in data.get("mealdates", []):
        ruoat = []
        for kategoria in paiva.get("courses", {}).values():
            nimi = (kategoria.get("title_fi") or kategoria.get("title_en") or "").strip()
            nimi = re.sub(r"^\*\s*", "", nimi).strip()
            if nimi:
                ruoat.append(nimi)
        if ruoat:
            paivat.append({"paiva": paiva.get("date", ""), "ruoat": ruoat})
    return paivat


def scrape_hermian_farmi() -> list[dict]:
    """
    Antell Hermian Farmi.

    Sivulla on jokaiselle päivälle paneeli #panel-Monday, #panel-Tuesday jne.
    Jokaisessa h5-otsikoita kategorioille (Pääruoaksi, Grilliannos, Delilounas...).
    Kategoria-h5:n jälkeen <ul> jonka jokainen <li> on yksi ruoka.

    Yksittäinen ruoka-li voi olla joko:
        <li>
          Kanaa paholaisenkastikkeessa
          <p><strong>Allergeenit</strong>: ...</p>
          <p>Huomioi, että raaka-aineet...</p>
          ...
        </li>
    TAI:
        <li>
          <p>Kanaa paholaisenkastikkeessa</p>
          <p>Allergeenit: ...</p>
          ...
        </li>

    Strategia: otetaan li:n KOKO teksti ja katkaistaan ensimmäiseen tunnettuun
    info-avainsanaan ("Allergeenit", "Huomioi, että", "Ravintoarvot" jne.).
    Tämä toimii molemmissa rakenteissa.
    """
    url = "https://antell.fi/lounas/tampere/hermianfarmi/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat_kaannos = {
        "Monday": "Maanantai", "Tuesday": "Tiistai", "Wednesday": "Keskiviikko",
        "Thursday": "Torstai", "Friday": "Perjantai",
    }

    # Hyväksyttävät kategoriat
    hyvaksytyt = ("pääruo", "grill", "deli", "pizza", "kasvis", "keitto")
    # Skipataan jälkkärit ja kaverit-linjat
    hylataan = ("jälkiruo", "kaveri")

    # Sanat joista ruoan nimen jälkeen tulee info-osio
    # (järjestys ei ole tärkeä: etsitään AIKAISIN esiintymä)
    INFO_AVAINSANAT = (
        "Allergeenit",
        "Huomioi, että",
        "Ravintoarvot",
        "Hiilijalanjälki",
        "Ainesosat",
        "Katso lisätiedot",
        "Miltä maistui",
    )

    paivat = []
    for eng, fi in paivat_kaannos.items():
        panel = soup.find(id=f"panel-{eng}")
        if not panel:
            continue
        ruoat = []
        for h5 in panel.find_all("h5"):
            ryhma = siivoa(h5.get_text()).lower()
            if not any(k in ryhma for k in hyvaksytyt):
                continue
            if any(k in ryhma for k in hylataan):
                continue
            ul = h5.find_next("ul")
            if not ul:
                continue
            for li in ul.find_all("li", recursive=False):
                # Otetaan li:n KOKO teksti
                teksti = li.get_text(separator=" ", strip=True)
                if not teksti:
                    continue

                # Etsi aikaisin info-avainsanan esiintymä
                katkaisupiste = len(teksti)
                for w in INFO_AVAINSANAT:
                    idx = teksti.find(w)
                    if idx >= 0 and idx < katkaisupiste:
                        katkaisupiste = idx

                ruoan_nimi = teksti[:katkaisupiste].strip()
                ruoan_nimi = siivoa(ruoan_nimi)

                # Poista mahdolliset allergeenikoodit lopusta
                ruoan_nimi = re.sub(
                    r"\s*[A-Z](\s*,\s*[A-Z]+)+\s*$", "", ruoan_nimi,
                ).strip()

                if not ruoan_nimi or len(ruoan_nimi) < 4:
                    continue

                ruoat.append(ruoan_nimi)

        # Poista duplikaatit järjestyksen säilyen
        nahdyt = set()
        ruoat_uniq = []
        for r in ruoat:
            if r not in nahdyt:
                nahdyt.add(r)
                ruoat_uniq.append(r)

        if ruoat_uniq:
            paivat.append({"paiva": fi, "ruoat": ruoat_uniq[:10]})

    return paivat


def scrape_munkkimiehet() -> list[dict]:
    """
    Munkkimiehet — lounaslista on PNG-kuvana sivulla.

    Strategia:
    1. Hae HTML
    2. Parsi kuvan URL <img>-tagista jonka src sisältää "netti"
    3. Lataa kuva
    4. Esikäsittele: pidä vain valkoinen ja punainen teksti (puutekstuuri pois)
    5. Aja Tesseract OCR suomenkielisellä sanastolla
    6. Parsi viikonpäivät ja ruoat
    """
    from io import BytesIO

    url = "https://munkkimiehet.fi/kuluttajille/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # 1) Etsi kuvan URL — <img> jonka src sisältää "netti"
    kuva_url = None
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if "netti" in src.lower() and src.endswith((".png", ".jpg", ".jpeg")):
            kuva_url = src
            break

    if not kuva_url:
        # Fallback: etsitään suurikokoinen kuva uploads-polusta
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if ("wp-content/uploads" in src and
                "logo" not in src.lower() and
                "ikoni" not in src.lower() and
                "valmistettu" not in src.lower() and
                src.endswith((".png", ".jpg", ".jpeg"))):
                kuva_url = src
                break

    if not kuva_url:
        print("  [Munkki] Kuvan URL ei löytynyt HTML:stä")
        return []

    print(f"  [Munkki] Kuva: {kuva_url}")

    # 2) Lataa kuva
    try:
        r = requests.get(kuva_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        kuva_data = r.content
    except Exception as e:
        print(f"  [Munkki] Kuvan lataus epäonnistui: {e}")
        return []

    # 3) Esikäsittely: pidä vain valkoinen ja punainen teksti
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("  [Munkki] Pillow tai numpy puuttuu — lisää requirements.txt:hen")
        return []

    try:
        img = Image.open(BytesIO(kuva_data)).convert("RGB")
        # Crop: poista 15% molemmilta sivuilta — kuvan reunoissa on
        # koristekuvioita (lusikat, ruutukangas) jotka aiheuttavat roskaa
        w, h = img.size
        margin_x = int(w * 0.15)
        img = img.crop((margin_x, 0, w - margin_x, h))
        arr = np.array(img)
        r_ch, g_ch, b_ch = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        # Valkoinen teksti: kaikki kanavat kirkkaita
        valkoinen = (r_ch > 180) & (g_ch > 180) & (b_ch > 180)
        # Punainen teksti: R kirkas, G ja B tummat
        punainen = (r_ch > 150) & (g_ch < 100) & (b_ch < 100)
        # Yhdistä — teksti = musta, muu = valkoinen
        teksti_maski = (valkoinen | punainen)
        bw = np.where(teksti_maski, 0, 255).astype(np.uint8)
        bw_img = Image.fromarray(bw)
    except Exception as e:
        print(f"  [Munkki] Esikäsittely epäonnistui: {e}")
        return []

    # 4) OCR
    try:
        import pytesseract
    except ImportError:
        print("  [Munkki] pytesseract puuttuu — lisää requirements.txt:hen")
        return []

    try:
        teksti = pytesseract.image_to_string(bw_img, lang="fin", config="--psm 6")
    except Exception as e:
        print(f"  [Munkki] OCR epäonnistui: {e}")
        return []

    if not teksti.strip():
        print("  [Munkki] OCR palautti tyhjän — onko tesseract-ocr-fin asennettu?")
        return []

    # 5) Parsi viikonpäivät ja ruoat
    return _parsi_munkki_teksti(teksti)


def _parsi_munkki_teksti(teksti: str) -> list[dict]:
    """Parsii Munkkimiesten OCR-tekstistä päivät ja ruoat."""
    PAIVA_NIMET_TR = ("MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI",
                      "PERJANTAI")
    NIMET_NORM = {p: p.capitalize() for p in PAIVA_NIMET_TR}

    paivat_dict: dict[str, list[str]] = {}
    nykyinen: str | None = None

    for raw in teksti.splitlines():
        rivi = siivoa(raw)
        if not rivi:
            continue

        # Onko rivi päivä-otsikko? Sallitaan pieniä OCR-virheitä:
        # rivi sisältää päivän nimen suurin osa kirjaimista oikein.
        # Yksinkertaisin: tarkistetaan onko rivin alkupätkä jonkin päivän nimen
        # kanssa lähes sama
        rivi_iso = rivi.upper()
        loytyi_paiva = None
        for p in PAIVA_NIMET_TR:
            if p in rivi_iso and len(rivi) < 30:
                loytyi_paiva = p
                break

        if loytyi_paiva:
            nykyinen = NIMET_NORM[loytyi_paiva]
            paivat_dict.setdefault(nykyinen, [])
            continue

        if not nykyinen:
            continue

        # Siivoa rivin alusta yksittäiset merkit ja kirjaimet (OCR-roskaa)
        # Esim. ". Lihakeitto" → "Lihakeitto", "L. SULJETTU!" → "SULJETTU!"
        import re as _re
        rivi = _re.sub(r"^[^A-Za-zÄÖÅäöå0-9]+", "", rivi)
        rivi = _re.sub(r"^[A-Za-zÄÖÅäöå]\.\s+", "", rivi)
        rivi = rivi.strip()

        # Suodatetaan roskat: lyhyet (<5 merkkiä) tai erikoismerkkejä täynnä
        if len(rivi) < 4:
            continue
        # Vaaditaan että rivissä on vähintään 3 peräkkäistä kirjainta
        import re as _re
        if not _re.search(r"[A-Za-zÄÖÅäöå]{3,}", rivi):
            continue
        # Suodatetaan header-rivit
        rivi_l = rivi.lower()
        if any(w in rivi_l for w in ("rusko lounas", "viikko ", "10:00", "14:30")):
            continue

        # Hyväksy ruokarivit
        paivat_dict[nykyinen].append(rivi)

    JARJESTYS = ["Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai"]
    paivat = []
    for p in JARJESTYS:
        if p in paivat_dict and paivat_dict[p]:
            paivat.append({"paiva": p, "ruoat": paivat_dict[p][:6]})
    return paivat


def scrape_ruskon_helmi() -> list[dict]:
    """Ruskon Helmi — <strong>-tagilla merkityt päivät."""
    url = "https://ruskonhelmi.fi/lounaslista/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup.find(class_="entry-content") or soup

    paivat_nimet = ("MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI", "PERJANTAI")
    paivat = []
    nykyinen_paiva = None
    nykyiset_ruoat: list[str] = []

    for el in main.find_all(["p", "strong", "h2", "h3", "h4"]):
        teksti = siivoa(el.get_text(" "))
        if not teksti:
            continue
        on_paiva = False
        for paiva_nimi in paivat_nimet:
            if teksti.upper().startswith(paiva_nimi):
                if nykyinen_paiva and nykyiset_ruoat:
                    paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})
                nykyinen_paiva = teksti
                nykyiset_ruoat = []
                on_paiva = True
                break
        if on_paiva:
            continue
        if nykyinen_paiva and len(teksti) > 3 and len(teksti) < 150:
            ohita = ["lounasruokien", "tilaa", "munkit", "kotiruoka", "lounas:",
                     "keittolounas", "puh.", "ruskon helmi", "vapuksi",
                     "tervetuloa", "take away"]
            if any(o in teksti.lower() for o in ohita):
                continue
            if teksti not in nykyiset_ruoat:
                nykyiset_ruoat.append(teksti)

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})

    return paivat


def scrape_osku() -> list[dict]:
    """Ravintola Osku — Ruskon ravintolan lista."""
    url = "https://ravintolaosku.fi/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    h2_rusko = None
    for h2 in soup.find_all("h2"):
        if "Lounaslista Rusko" in h2.get_text():
            h2_rusko = h2
            break
    if not h2_rusko:
        return []

    paivat = []
    nykyinen_paiva = None
    nykyiset_ruoat: list[str] = []
    paiva_re = re.compile(r"^(Ma|Ti|Ke|To|Pe)\s*\d{1,2}\.\d{1,2}\.?$", re.I)

    el = h2_rusko
    for _ in range(200):
        el = el.find_next()
        if el is None:
            break
        if el.name == "h2" and "lounaslista" in el.get_text().lower():
            break
        if el.name != "p":
            continue
        teksti = siivoa(el.get_text(" "))
        if not teksti:
            continue
        if paiva_re.match(teksti):
            if nykyinen_paiva and nykyiset_ruoat:
                paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat})
            nykyinen_paiva = teksti
            nykyiset_ruoat = []
        elif nykyinen_paiva and len(teksti) > 5:
            ohita = ["pidätämme", "lounas 10", "kalmarin", "ruokontie",
                     "vierailijat", "tervetuloa"]
            if any(o in teksti.lower() for o in ohita):
                continue
            nykyiset_ruoat.append(teksti)

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat})

    return paivat


def scrape_aito_kotilounas() -> list[dict]:
    """
    Aito kotilounas Sääksjärvi (Sääksjärven Lounaskahvila).

    Sivu: https://www.aitokotilounas.fi/lounaslista/

    HUOM: Lounaslista on PDF-tiedostona, ei HTML-sisältönä. Sivu käyttää
    WordPressin pdf-poster -pluginia. Strategia:
    1. Hae HTML
    2. Parsi PDF:n URL data-attributes -attribuutista
    3. Lataa PDF
    4. Lue teksti pypdf:llä
    5. Parsi teksti viikonpäiviksi ja ruoiksi
    """
    import json
    from io import BytesIO

    url = "https://www.aitokotilounas.fi/lounaslista/"
    html = hae_sivu(url)
    if not html:
        print("  [Aito] hae_sivu palautti None")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 1) Etsi PDF-URL data-attributes -atribuutista
    pdf_url = None
    for div in soup.find_all(class_="wp-block-pdfp-pdf-poster"):
        attrs = div.get("data-attributes")
        if not attrs:
            continue
        try:
            data = json.loads(attrs)
            if data.get("file"):
                pdf_url = data["file"]
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    if not pdf_url:
        print("  [Aito] PDF-URL ei löytynyt HTML:stä")
        return []

    print(f"  [Aito] PDF: {pdf_url}")

    # 2) Lataa PDF
    try:
        r = requests.get(pdf_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        pdf_data = r.content
    except Exception as e:
        print(f"  [Aito] PDF-lataus epäonnistui: {e}")
        return []

    # 3) Lue teksti pypdf:llä
    try:
        from pypdf import PdfReader
    except ImportError:
        print("  [Aito] pypdf-kirjasto puuttuu — lisää 'pypdf' "
              "requirements.txt:hen")
        return []

    try:
        reader = PdfReader(BytesIO(pdf_data))
        teksti = ""
        for page in reader.pages:
            teksti += (page.extract_text() or "") + "\n"
    except Exception as e:
        print(f"  [Aito] PDF-luku epäonnistui: {e}")
        return []

    if not teksti.strip():
        print("  [Aito] PDF:stä ei saatu tekstiä (skannattu kuva?)")
        return []

    # 4) Parsi teksti viikonpäiviksi ja ruoiksi
    return _parsi_aito_pdf_teksti(teksti)


def _parsi_aito_pdf_teksti(teksti: str) -> list[dict]:
    """
    Parsii Aito kotilounas -PDF:n teksti päiviksi ja ruoiksi.

    PDF on 2-sarakkeinen, joten pypdf tuottaa tekstin jossa:
    - Otsikkorivillä on 1 tai 2 päivää (esim. "MAANANTAI 11.05. TORSTAI 14.05.")
    - Bullet (•) -ruoat kuuluvat vasempaan sarakkeen päivään
    - Multilinet ruoat: jatkorivi ei ala bulletilla eikä isolla kirjaimella
    - Erikoispäivien viestit ("Helatorstai, ei lounasta") kuuluvat oikean
      sarakkeen päivään
    """
    import re as _re

    PAIVA_NIMET_TR = ("MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI",
                      "PERJANTAI")
    NIMET_NORM = {p: p.capitalize() for p in PAIVA_NIMET_TR}

    paivat_dict: dict[str, list[str]] = {}
    nykyinen_vasen: str | None = None
    nykyinen_oikea: str | None = None

    # Rivit jotka eivät ole ruokia (header/footer)
    def on_otsikko_tai_footer(rivi: str) -> bool:
        rl = rivi.lower()
        avainsanat = (
            "pitkäahteentie", "puh.", "lempäälä", "sääksjärven liikekeskus",
            "annokset myös", "lounastoimitukset",
            "lounas tarjoillaan", "sis. lounas", "salaattipöytä, leivät",
            "vesi/maito", "kahvi/tee",
        )
        return any(w in rl for w in avainsanat)

    # Erikoisviestit jotka kuuluvat oikealle sarakkeelle
    def on_erikoisviesti(rivi: str) -> bool:
        rl = rivi.lower()
        return ("ei lounasta" in rl or
                "vapaapäivä" in rl or
                "helatorstai" in rl or
                "pyhäpäivä" in rl or
                "suljettu" in rl)

    for raw in teksti.splitlines():
        rivi = siivoa(raw)
        if not rivi:
            continue
        if on_otsikko_tai_footer(rivi):
            continue

        # Onko tämä otsikkorivi? Etsi päivien nimet rivillä (vain isolla
        # kirjaimella, koska PDF:ssä käytetään isoja kirjaimia otsikoissa).
        loydot = []
        for p in PAIVA_NIMET_TR:
            idx = rivi.find(p)
            if idx >= 0:
                # Tarkistetaan että ei ole keskellä sanaa (esim. ei matchaa
                # "TIISTAI" sisällä jossain). Tarkistetaan ympäröivät merkit.
                ennen = rivi[idx-1] if idx > 0 else " "
                jalkeen_idx = idx + len(p)
                jalkeen = rivi[jalkeen_idx] if jalkeen_idx < len(rivi) else " "
                if not ennen.isalpha() and not jalkeen.isalpha():
                    loydot.append((idx, p))
        loydot.sort()

        if loydot:
            # Otsikkorivi
            nykyinen_vasen = NIMET_NORM[loydot[0][1]]
            paivat_dict.setdefault(nykyinen_vasen, [])
            if len(loydot) >= 2:
                nykyinen_oikea = NIMET_NORM[loydot[1][1]]
                paivat_dict.setdefault(nykyinen_oikea, [])
            else:
                nykyinen_oikea = None
            continue

        # Sisältörivi — minne kuuluu?
        if on_erikoisviesti(rivi):
            # Erikoisviesti — oikealle sarakkeelle jos sellainen on
            kohde = nykyinen_oikea or nykyinen_vasen
            if kohde and rivi not in paivat_dict.get(kohde, []):
                paivat_dict[kohde].append(rivi)
            continue

        if not nykyinen_vasen:
            continue

        # Tämä on ruokarivi tai sen jatko, kuuluu vasemmalle sarakkeelle
        # Tunnistetaan jatkorivi: ei ala bulletilla EIKÄ "Keittiöstä":lla
        # EIKÄ isolla kirjaimella (lauseen alku)
        on_uusi_rivi = (rivi.startswith("•") or
                       rivi.lower().startswith("keittiöstä") or
                       (rivi[0].isupper() and not rivi[0].islower()))
        # Erikoisuus: "riisiä (L)" alkaa pienellä → on jatkorivi
        # "Keittiöstä:" alkaa isolla → uusi rivi
        # "• Kalaleikettä" alkaa bulletilla → uusi rivi
        on_jatkorivi = not (rivi.startswith("•") or
                            rivi.lower().startswith("keittiöstä") or
                            (rivi[0].isupper() if rivi else False))

        if on_jatkorivi and paivat_dict[nykyinen_vasen]:
            # Yhdistä edelliseen
            paivat_dict[nykyinen_vasen][-1] += " " + rivi
        else:
            # Poista bullet ja whitespace alusta
            puhdas = _re.sub(r"^[•\-\*]\s*", "", rivi)
            if puhdas:
                paivat_dict[nykyinen_vasen].append(puhdas)

    # Muunna ma-pe-järjestykseen
    JARJESTYS = ["Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai"]
    paivat = []
    for p in JARJESTYS:
        if p in paivat_dict and paivat_dict[p]:
            paivat.append({"paiva": p, "ruoat": paivat_dict[p][:8]})

    if not paivat:
        print(f"  [Aito] PDF:n teksti löytyi mutta ei päiviä. "
              f"Ote tekstistä:\n  {teksti[:500]!r}")

    return paivat


def scrape_caffitella() -> list[dict]:
    """Caffitella — yritys jossa duplikaatit estetään."""
    url = "https://www.caffitella.fi/lounaslista/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["nav", "footer", "header", "script", "style", "aside"]):
        tag.decompose()

    paivat_nimet = ("Maanantai", "Tiistai", "Keskiviikko", "Torstai",
                    "Perjantai", "Lauantai")
    paivat = []
    nykyinen_paiva = None
    nykyiset_ruoat: list[str] = []
    nahdyt_paivat = set()

    for el in soup.find_all(["p", "strong", "h2", "h3", "h4", "li", "div"]):
        teksti = siivoa(el.get_text(" "))
        if not teksti or len(teksti) > 200:
            continue
        on_paiva = False
        for paiva in paivat_nimet:
            if teksti.lower().startswith(paiva.lower()) and len(teksti) < 30:
                if paiva.lower() in nahdyt_paivat:
                    continue
                nahdyt_paivat.add(paiva.lower())
                if nykyinen_paiva and nykyiset_ruoat:
                    paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})
                nykyinen_paiva = teksti
                nykyiset_ruoat = []
                on_paiva = True
                break
        if on_paiva:
            continue
        if nykyinen_paiva and 5 < len(teksti) < 150:
            ohita = ["lounaslista", "tilaa", "leipomo", "vapun", "ole hyvä"]
            if any(o in teksti.lower() for o in ohita):
                continue
            if teksti not in nykyiset_ruoat:
                nykyiset_ruoat.append(teksti)

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})

    return paivat


# ============================================================
# RAVINTOLAT — alueet käyttäjän päättämällä tavalla
# ============================================================

RAVINTOLAT = [
    # ----- KATEGORIA 1 -----
    {
        "nimi": "Aito kotilounas Sääksjärvi",
        "alue": "Sääksjärvi",
        "kategoria": 1,
        "url": "https://www.aitokotilounas.fi/lounaslista/",
        "scraper": lambda: scrape_aito_kotilounas(),
    },
    {
        "nimi": "Caffitella",
        "alue": "Hervanta",
        "kategoria": 1,
        "url": "https://www.caffitella.fi/lounaslista/",
        "scraper": lambda: scrape_caffitella(),
    },
    {
        "nimi": "Farmi",
        "alue": "Hermia",
        "kategoria": 1,
        "url": "https://antell.fi/lounas/tampere/hermianfarmi/",
        "scraper": lambda: scrape_hermian_farmi(),
    },
    {
        "nimi": "Fastelle",
        "alue": "Lahdesjärvi",
        "kategoria": 1,
        "url": "https://linkosuo.fi/toimipaikka/ravintola-fastelle/",
        "scraper": lambda: scrape_fastelle(),
    },
    {
        "nimi": "Hermia 5",
        "alue": "Hermia",
        "kategoria": 1,
        "url": "https://www.sodexo.fi/ravintolat/ravintola-hermia-5",
        "scraper": lambda: scrape_sodexo(107),
    },
    {
        "nimi": "Hermia 6",
        "alue": "Hermia",
        "kategoria": 1,
        "url": "https://www.sodexo.fi/ravintolat/tampere/hermia-6",
        "scraper": lambda: scrape_sodexo(110),
    },
    {
        "nimi": "Munkkimiehet",
        "alue": "Rusko",
        "kategoria": 1,
        "url": "https://munkkimiehet.fi/kuluttajille/",
        "scraper": lambda: scrape_munkkimiehet(),
    },
    {
        "nimi": "Ravintola Idaho",
        "alue": "Sääksjärvi",
        "kategoria": 1,
        "url": "https://www.facebook.com/people/Ravintola-Idaho-Oy/100070629319742/",
        "scraper": None,
        "huom": "Lounaslista löytyy Facebookista",
    },
    {
        "nimi": "Ravintola Osku",
        "alue": "Rusko",
        "kategoria": 1,
        "url": "https://ravintolaosku.fi/",
        "scraper": lambda: scrape_osku(),
    },
    {
        "nimi": "Ruskon Helmi",
        "alue": "Rusko",
        "kategoria": 1,
        "url": "https://ruskonhelmi.fi/lounaslista/",
        "scraper": lambda: scrape_ruskon_helmi(),
    },

    # ----- KATEGORIA 2 -----
    {
        "nimi": "Gate of India",
        "alue": "Hervanta",
        "kategoria": 2,
        "url": "https://www.gateofindia.fi/",
        "scraper": None,
        "huom": "Ei lounaslistaa nettisivulla",
    },
    {
        "nimi": "Hertta",
        "alue": "Hermia",
        "kategoria": 2,
        "url": "https://linkosuo.fi/toimipaikka/hertta/",
        "scraper": lambda: scrape_linkosuo("https://linkosuo.fi/toimipaikka/hertta/"),
    },
    {
        "nimi": "Kontukeittiö",
        "alue": "Hervanta",
        "kategoria": 2,
        "url": "https://kontukoti.fi/kontukeittio/kontukeittio-hervanta/",
        "scraper": lambda: scrape_kontukeittio(),
    },
    {
        "nimi": "Malabadi",
        "alue": "Hervanta",
        "kategoria": 2,
        "url": "https://www.malabadi.fi/",
        "scraper": None,
        "huom": "Ei lounaslistaa nettisivulla",
    },

    # ----- KATEGORIA 3 -----
    {
        "nimi": "Heval",
        "alue": "Hervanta",
        "kategoria": 3,
        "url": "https://heval.fi/lounas/",
        "scraper": None,
        "huom": "Avaa lounaslista ravintolan sivulta",
    },
    {
        "nimi": "Malakai",
        "alue": "Sääksjärvi",
        "kategoria": 3,
        "url": "https://malakairavintola.fi/",
        "scraper": None,
        "huom": "Ei lounaslistaa nettisivulla",
    },
    {
        "nimi": "Orvokki",
        "alue": "Hermia",
        "kategoria": 3,
        "url": "https://linkosuo.fi/toimipaikka/lounasravintola-orvokki/",
        "scraper": lambda: scrape_linkosuo("https://linkosuo.fi/toimipaikka/lounasravintola-orvokki/"),
    },
    {
        "nimi": "Reaktori",
        "alue": "Hervanta",
        "kategoria": 3,
        "url": "https://www.compass-group.fi/ravintolat-ja-ruokalistat/foodco/kaupungit/tampere/reaktori/",
        "scraper": lambda: scrape_reaktori(),
    },
    {
        "nimi": "Sisu",
        "alue": "Hervanta",
        "kategoria": 3,
        "url": "https://lounaat.info/lounas/sisu-buffet-hervanta/tampere",
        "scraper": lambda: scrape_sisu_buffet(),
    },
    {
        "nimi": "Speakeasy",
        "alue": "Hervanta",
        "kategoria": 3,
        "url": "https://www.speakeasy.fi/hervanta/lounas/",
        "scraper": lambda: scrape_speakeasy(),
    },
]


def main():
    tulokset = []
    for ravintola in RAVINTOLAT:
        print(f"Haetaan: {ravintola['nimi']}...")
        rivi = {
            "nimi": ravintola["nimi"],
            "alue": ravintola["alue"],
            "kategoria": ravintola.get("kategoria", 0),
            "url": ravintola["url"],
            "huom": ravintola.get("huom", ""),
            "paivat": [],
        }
        if ravintola["scraper"] is not None:
            try:
                raakapaivat = ravintola["scraper"]()
                # Normalisoi päivien nimet ja järjestä ma-pe
                normalisoidut = normalisoi_paivat(raakapaivat)
                # Siivoa jokaisen päivän ruokarivit (allergeenit, hinnat, kellonajat)
                # ja pudota päivät joilla ei jäänyt yhtään ruokaa
                siivotut = []
                for p in normalisoidut:
                    puhtaat = siivoa_ruoat(p["ruoat"])
                    if puhtaat:
                        siivotut.append({"paiva": p["paiva"], "ruoat": puhtaat})
                rivi["paivat"] = siivotut
                print(f"  -> {len(rivi['paivat'])} päivää löytyi")
            except Exception as e:
                print(f"  ! Virhe: {e}")
                rivi["virhe"] = str(e)
        else:
            print(f"  -> vain linkki")
        tulokset.append(rivi)

    ulos = {
        "paivitetty": datetime.now(timezone.utc).isoformat(),
        "ravintolat": tulokset,
    }
    polku = Path(__file__).parent / "lounaat.json"
    polku.write_text(json.dumps(ulos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nValmis. Tallennettu: {polku}")


if __name__ == "__main__":
    main()
