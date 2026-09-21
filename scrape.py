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
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import laatu

TIMEOUT = 25

# Turvarajat ulkopuolisten sivujen lataamiseen. Ravintoloiden sivut ovat
# lähtökohtaisesti luotettavia, mutta jos jokin niistä hajoaa tai joutuu
# vääriin käsiin, se ei saa kaataa ajoa eikä täyttää levyä.
MAKS_LATAUS_TAVUA = 10 * 1024 * 1024   # 10 Mt riittää kaikille lähteille

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


def sama_sivusto(url: str, sallittu_domain: str) -> bool:
    """
    Onko osoite luvatulla sivustolla? Esimerkiksi
    sama_sivusto("https://www.munkkimiehet.fi/kuva.png", "munkkimiehet.fi") → True

    Käytetään kun scraperi seuraa sivulta löytynyttä osoitetta (PDF, kuva).
    Näin sivun muutos ei voi ohjata hakua tuntemattomalle palvelimelle.
    """
    isanta = (urlparse(url).hostname or "").lower()
    sallittu = sallittu_domain.lower()
    return isanta == sallittu or isanta.endswith("." + sallittu)


def hae_tavut(url: str, sallittu_domain: str | None = None,
              maksimi: int = MAKS_LATAUS_TAVUA, aikakatkaisu: int = 15) -> bytes | None:
    """
    Lataa tiedoston (PDF, kuva) turvarajojen kanssa.

    - Osoitteen on oltava http(s) ja halutessa tietyllä sivustolla
    - Lataus keskeytetään jos tiedosto on liian iso
    - Uudelleenohjauksen päätepisteen sivusto tarkistetaan
    """
    if not url.lower().startswith(("http://", "https://")):
        print(f"  ! Osoite ei ole verkko-osoite: {url[:80]}")
        return None
    if sallittu_domain and not sama_sivusto(url, sallittu_domain):
        print(f"  ! Osoite ei ole sivustolla {sallittu_domain}: {url[:80]}")
        return None
    try:
        with requests.get(url, headers=HEADERS, timeout=aikakatkaisu, stream=True) as r:
            r.raise_for_status()
            if sallittu_domain and not sama_sivusto(r.url, sallittu_domain):
                print(f"  ! Uudelleenohjaus pois sivustolta {sallittu_domain}: {r.url[:80]}")
                return None
            pituus = r.headers.get("content-length")
            if pituus and pituus.isdigit() and int(pituus) > maksimi:
                print(f"  ! Tiedosto liian suuri ({int(pituus)} tavua): {url[:80]}")
                return None
            data = bytearray()
            for pala in r.iter_content(chunk_size=65536):
                data.extend(pala)
                if len(data) > maksimi:
                    print(f"  ! Lataus keskeytetty, yli {maksimi} tavua: {url[:80]}")
                    return None
            return bytes(data)
    except Exception as e:
        print(f"  ! Virhe ladattaessa {url[:80]}: {e}")
        return None


def paattele_merkisto(r: "requests.Response") -> str:
    """
    Päättelee sivun merkistön luotettavimmassa järjestyksessä:
    1. HTTP-otsakkeen charset
    2. HTML:n oma <meta charset=...>
    3. Sisällöstä arvattu merkistö
    4. UTF-8

    Väärä merkistö näkyy ruokalistassa sotkuna ("LohikeittoÃ¤"), joten
    arvaus on vasta viimeinen keino.
    """
    otsake = r.headers.get("content-type", "")
    if "charset=" in otsake.lower():
        return r.encoding or "utf-8"
    alku = r.content[:4096]
    m = re.search(rb"""<meta[^>]+charset=["']?\s*([A-Za-z0-9_\-]+)""", alku, re.I)
    if m:
        return m.group(1).decode("ascii", errors="ignore")
    return r.apparent_encoding or "utf-8"


def hae_sivu(url: str) -> str | None:
    """Hakee yhden URLin sisällön tekstinä. Palauttaa None jos epäonnistuu."""
    try:
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            data = bytearray()
            for pala in r.iter_content(chunk_size=65536):
                data.extend(pala)
                if len(data) > MAKS_LATAUS_TAVUA:
                    print(f"  ! Sivu liian suuri (yli {MAKS_LATAUS_TAVUA} tavua): {url}")
                    return None
            r._content = bytes(data)          # jotta r.text/apparent_encoding toimii
            r._content_consumed = True
            r.encoding = paattele_merkisto(r)
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
            uusi = {"paiva": nimi, "ruoat": p.get("ruoat", [])}
            if p.get("osastot"):
                uusi["osastot"] = p["osastot"]
            tulos.append(uusi)
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
    "rikkidioksidi", "gluteeni", "sipuli", "valkosipuli",
    # Joskus listattuja: alkuperätietojen yhteydessä (jätetään pois suoraan)
}


def siivoa_ruoka(rivi: str) -> str | None:
    """
    Siivoaa yksittäisen ruokarivin: poistaa allergeenitiedot, hinnat ja
    kellonajat. Pudottaa puuro-/aamupala-rivit.

    Siivous ajetaan uudelleen kunnes tulos ei enää muutu, koska yhden
    kierroksen jälkeen loppuun voi jäädä uusi irrallinen koodi
    (esim. "broileri L (" → "broileri L" → "broileri").

    Palauttaa puhdistetun rivin tai None jos rivi pitää pudottaa.
    """
    s = rivi
    for _ in range(4):
        uusi = _siivoa_ruoka_kerran(s)
        if uusi is None or uusi == s:
            return uusi
        s = uusi
    return s


def _siivoa_ruoka_kerran(rivi: str) -> str | None:
    """Yksi siivouskierros — katso siivoa_ruoka."""
    if not rivi:
        return None
    s = rivi.strip()
    if not s:
        return None

    # 0) Pudota allergeeniselitteet ("G=gluteeniton", "L = laktoositon",
    #    "VEG = vegaaninen") ja saatavuusinfot ("SAA M, G, VEG keittiöstä").
    if re.match(r"^[A-Za-zÄÖäö]{1,4}\s*=", s):
        return None
    if re.match(r"^(saa|saatavana|saatavilla)\b", s, flags=re.I):
        return None
    # Huomautukset ("HUOM! Lounas tänään klo 10.30-13.00!") eivät ole ruokia
    if re.match(r"^huom\b", s, flags=re.I):
        return None
    # Pelkkä päivämäärä ("21.9.") on otsikon jäänne
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.?(\d{2,4})?", s):
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
        # "(SAA VEG dippi keittiöstä)" = saatavuustieto, ei ruokaa
        if re.match(r"^saa\b", sisus, flags=re.I):
            return " "
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

    # Roikkuva välimerkki pois ennen loppukoodien tunnistusta, jotta
    # "broileri L," käsitellään samoin kuin "broileri L" (idempotenssi).
    s = s.strip().rstrip(",;:-").strip()

    def on_allergeenikoodi(sana: str) -> bool:
        """Onko sana allergeenikoodi (L, G, VL, VEG, Kasvis...) eikä ruokasana?"""
        w = sana.strip().rstrip(".")
        if not w:
            return False
        if w.lower() in ALLERGEENISANAT:
            return True
        # Lyhyt isokirjaiminen koodi: "L", "G", "VL", "VEG", "SAA"
        return len(w) <= 4 and w.isalpha() and w.isupper()

    # 4a) Pilkulla erotetut: vähintään 2 koodia, esim. "M, G", "L, G, M",
    #     "A, G, L, M, Veg". Poistetaan VAIN jos jokainen osa on tunnettu
    #     allergeenikoodi — muuten "kasviksia M, G, riisiä" menettäisi riisin.
    m = re.search(r"\s+([A-Za-zÄÖäö]{1,7}(?:\s*,\s*[A-Za-zÄÖäö]{1,7}){1,})\s*$", s)
    if m and all(on_allergeenikoodi(o) for o in m.group(1).split(",")):
        s = s[:m.start()]
    # 4b) Välilyönnillä erotetut LYHYET (1-3 merkkiä), vähintään 2 peräkkäin
    #     Esim. "l g k", "M G", "A, L M G" (loppupätkä)
    s = re.sub(
        r"\s+[A-Za-zÄÖäö]{1,3}(?:\s+[A-Za-zÄÖäö]{1,3}){1,}\s*$",
        "",
        s,
    )
    # 4c) Yksittäinen isokirjaiminen koodi tai "Veg"/"Kasvis" lopussa
    s = re.sub(r"\s+[A-ZÄÖ]{1,4}\s*$", "", s)
    # Pienellä kirjoitettu yksittäinen koodi lopussa: "Muikkuja l", "Pangasius g"
    s = re.sub(r"\s+[lgmv]\s*$", "", s)
    s = re.sub(r"\s+[Vv]eg\.?\s*$", "", s)
    s = re.sub(r"(?:\s+KASVIS|,\s*[Kk]asvis)\s*$", "", s)

    # Siisti välilyönnit
    s = re.sub(r"\s+", " ", s).strip()
    s = s.rstrip(",;:-#*")  # Joskus jää roikkumaan välimerkki tai huomautusmerkki
    s = re.sub(r"\s*<3\s*$", "", s)  # sydän rivin lopussa
    # Rivinvaihdon takia katkennut sulku: "SPEAKEASYN LOHIBUFFET (" → ilman sulkua
    s = re.sub(r"\s*[(\[]\s*$", "", s)
    s = re.sub(r"^\s*[)\]]\s*", "", s)

    if not s or len(s) < 4:
        return None

    # 5) Pudota aamupala-/puurorivit (Hertta, Fastelle alkavat puurolla ja
    #    aamiaisleivällä)
    s_lower = s.lower()
    aamupala_avainsanat = ("puuro", "porridge", "aamiais", "aamupala", "breakfast")
    if any(w in s_lower for w in aamupala_avainsanat):
        return None

    # 6) Pudota teemaviikon otsikot: "Lempiruokaviikko!", "Orvokin sadonkorjuuviikko"
    if re.fullmatch(r"(?:\S+\s+){0,2}\S*viikko!?", s, flags=re.I):
        return None

    return s


def jaa_vaihtoehdot(rivi: str) -> list[str]:
    """
    Jakaa yhdelle riville kirjoitetut vaihtoehtoiset pääruoat omiksi riveikseen:
    "Naudanlihapataa M,G / Kala-äyriäiswok M / Kasvispyöryköitä" → 3 riviä.
    Jaetaan vain välilyönnein ympäröidystä kauttaviivasta ("vesi/maito" jää).
    """
    osat = [o.strip() for o in re.split(r"\s+/\s+", rivi)]
    return [o for o in osat if o] or [rivi]


def siivoa_ruoat(ruoat: list[str]) -> list[str]:
    """Jakaa vaihtoehdot omille riveilleen, siivoaa ne ja suodattaa tyhjät pois."""
    tulos = []
    for r in ruoat:
        for osa in jaa_vaihtoehdot(r):
            siivottu = siivoa_ruoka(osa)
            if siivottu is not None and siivottu not in tulos:
                tulos.append(siivottu)
    return tulos


def osasto(nimi: str, ruoat: list[str]) -> dict:
    """Yksi listan osasto (esim. "Buffet", "Grilli", "Salaatti") ruokineen."""
    return {"nimi": siivoa(nimi), "ruoat": list(ruoat)}


def paiva_osastoista(paiva: str, osastot: list[dict]) -> dict:
    """
    Rakentaa päivän jossa ruoat on jaettu osastoihin. "ruoat" sisältää kaikki
    rivit litteänä (haku ja vanhat asiakkaat), "osastot" säilyttää jaon.
    """
    osastot = [o for o in osastot if o.get("ruoat")]
    return {
        "paiva": paiva,
        "ruoat": [r for o in osastot for r in o["ruoat"]],
        "osastot": osastot,
    }


# Etuliitteet joita ravintolat käyttävät rivin alussa osoittamaan linjastoa:
# "Keitto: Kaalikeitto", "Chef: Puna-ahventa...", "Keittiöstä: Fetasalaatti".
OSASTO_ETULIITTEET = {
    "keitto": "Keitto",
    "keittolounas": "Keitto",
    "chef": "Chef-annos",
    "chefin": "Chef-annos",
    "chef´s menu": "Chef-annos",
    "chef's menu": "Chef-annos",
    "chef’s menu": "Chef-annos",
    "chefs menu": "Chef-annos",
    "chef´s": "Chef-annos",
    "chef's": "Chef-annos",
    "jälkiruoaksi": "Jälkiruoka",
    "jälkiruoka": "Jälkiruoka",
    "vegaaniruoka keittiöstä": "Vegaaninen keittiöstä",
    "vegaaninen": "Vegaaninen",
    "kasvis": "Kasvis",
    "kasvisruoka": "Kasvis",
    "keittiöstä": "Keittiöstä",
    "salaatti": "Salaatti",
    "salaattilounas": "Salaatti",
    "grilli": "Grilli",
    "grillistä": "Grilli",
    "buffet": "Buffet",
    "deli": "Deli",
}


def osastot_etuliitteista(rivit: list[str], oletus: str = "Lounas") -> list[dict]:
    """
    Jakaa rivit osastoihin rivin alun etuliitteen perusteella.

    - "Keitto: Kaalikeitto"        → osasto "Keitto", rivi "Kaalikeitto"
    - "Proteiinilisäkkeet ...:"    → seuraavat "– x"-rivit tähän osastoon
    - "– riisiä"                   → edellisen rivin alarivi (sama osasto)
    - muut rivit                   → oletus-osasto ("Lounas")

    Jos kaikki rivit päätyvät oletusosastoon, palautetaan yksi nimetön
    osasto (käyttöliittymä ei näytä väliotsikkoa).
    """
    osastot: list[dict] = []

    def hae_osasto(nimi: str) -> dict:
        for o in osastot:
            if o["nimi"] == nimi:
                return o
        o = {"nimi": nimi, "ruoat": []}
        osastot.append(o)
        return o

    listaosasto: str | None = None  # "Otsikko:"-rivin jälkeiset "– x"-rivit
    edellinen_osasto: str = oletus
    for raaka in rivit:
        rivi = siivoa(raaka)
        if not rivi:
            continue
        # Alarivi: kuuluu samaan osastoon kuin edellinen (tai listaotsikon osastoon)
        if re.match(r"^[–\-•]\s*\S", rivi):
            if listaosasto:
                # "Otsikko:"-rivin alla viiva on luettelomerkki → pois
                hae_osasto(listaosasto)["ruoat"].append(re.sub(r"^[–\-•]\s*", "", rivi))
            else:
                hae_osasto(edellinen_osasto)["ruoat"].append(rivi)
            continue
        # "Otsikko:" ilman sisältöä → seuraavat alarivit tähän osastoon
        if rivi.endswith(":") and len(rivi) < 60:
            listaosasto = rivi.rstrip(":").strip().lstrip("*–- ").strip()
            edellinen_osasto = listaosasto
            hae_osasto(listaosasto)
            continue
        # "Jälkiruoaksi X" ilman kaksoispistettä
        m = re.match(r"^(jälkiruoaksi|jälkiruokana)\s+(.+)$", rivi, flags=re.I)
        if m:
            listaosasto = None
            hae_osasto("Jälkiruoka")["ruoat"].append(m.group(2).strip())
            edellinen_osasto = "Jälkiruoka"
            continue
        # "Etuliite: ruoka" (myös "Chef´s menu: ...")
        m = re.match(r"^([A-Za-zÄÖÅäöå][\wÄÖÅäöå \-´'’]{1,30}):\s+(.+)$", rivi)
        if m and m.group(1).strip().lower() in OSASTO_ETULIITTEET:
            listaosasto = None
            nimi = OSASTO_ETULIITTEET[m.group(1).strip().lower()]
            hae_osasto(nimi)["ruoat"].append(m.group(2).strip())
            edellinen_osasto = nimi
            continue
        if listaosasto:
            # "Otsikko:"-rivin jälkeiset rivit kuuluvat otsikon osastoon
            # (Fastelle: "Proteiinilisäkkeet punnittavaan salaattiin:" + rivit)
            hae_osasto(listaosasto)["ruoat"].append(rivi)
            continue
        hae_osasto(oletus)["ruoat"].append(rivi)
        edellinen_osasto = oletus

    osastot = [o for o in osastot if o["ruoat"]]
    if len(osastot) <= 1:
        return [{"nimi": "", "ruoat": osastot[0]["ruoat"]}] if osastot else []
    # Oletusosasto ensin
    osastot.sort(key=lambda o: 0 if o["nimi"] == oletus else 1)
    return osastot


def siivoa_paiva(p: dict) -> dict | None:
    """Siivoaa päivän ruoat (ja osastot). Palauttaa None jos mitään ei jää."""
    if p.get("osastot"):
        osastot = []
        for o in p["osastot"]:
            puhtaat = siivoa_ruoat(o.get("ruoat", []))
            if puhtaat:
                osastot.append({"nimi": o.get("nimi", ""), "ruoat": puhtaat})
        if not osastot:
            return None
        ruoat = [r for o in osastot for r in o["ruoat"]]
        if len(osastot) == 1 and not osastot[0]["nimi"]:
            return {"paiva": p["paiva"], "ruoat": ruoat}
        return {"paiva": p["paiva"], "ruoat": ruoat, "osastot": osastot}
    puhtaat = siivoa_ruoat(p.get("ruoat", []))
    if not puhtaat:
        return None
    return {"paiva": p["paiva"], "ruoat": puhtaat}


# =====================================================

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
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Sivu pilkkoo rivit useaan <span>:iin ("Kievinkana…" + ", ranskalaiset (L)"),
    # joten rivit kootaan <br>- ja lohkorajojen mukaan, ei span-rajojen.
    teksti = teksti_riveina(soup.body or soup)

    paivat_nimet = ["MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI", "PERJANTAI"]
    palat = re.split(r"(" + "|".join(paivat_nimet) + r")", teksti)

    paivat = []
    nykyinen = None
    for pala in palat:
        pala = pala.strip()
        if pala in paivat_nimet:
            nykyinen = pala
        elif nykyinen:
            rivit = [siivoa(r) for r in pala.split("\n") if r.strip()]
            ruoat = []
            otsikko = ""
            for rivi in rivit:
                # Allergeeniselite ("L = laktoositon", "G=gluteeniton")
                # tai à la carte -osio päättää päivän listan
                if re.match(r"^[A-Za-zÄÖäö]{1,4}\s*=", rivi) or rivi == "Texas Pete Burger":
                    break
                if len(rivi) < 4:
                    continue
                # "SPEAKEASYN LOHIBUFFET (L)" → päivän buffetin nimi väliotsikoksi
                if "BUFFET" in rivi.upper() and rivi.upper() == rivi.upper() and len(rivi) < 40 \
                        and re.sub(r"[^A-Za-zÄÖÅäöå]", "", rivi).isupper():
                    otsikko = re.sub(r"\s*\(.*$", "", rivi).strip().capitalize()
                    continue
                ruoat.append(rivi)
            if ruoat:
                if otsikko:
                    paivat.append(paiva_osastoista(nykyinen, [osasto(otsikko, ruoat[:6])]))
                else:
                    paivat.append({"paiva": nykyinen, "ruoat": ruoat[:6]})
            nykyinen = None
    return paivat


# Kontukeittiön sivu (kontukoti.fi) näyttää listan Lounastaja-widgetillä.
# Widgetin julkinen API-avain on sivun HTML:ssä (data-api-key). Luetaan se
# sivulta ajon yhteydessä; jos ei löydy, käytetään viimeksi tunnettua.
KONTUKEITTIO_SIVU = "https://kontukoti.fi/kontukeittio/kontukeittio-hervanta/"
KONTUKEITTIO_API_AVAIN = "0d173806-41da-4600-ae6e-a1c7fd3e8246"


def _lounastaja_viikko(api_avain: str) -> list[dict]:
    """
    Lounastaja-palvelun viikkolista (lounastaja.app/api/v1/week/<avain>/active).

    Rakenne: data.week.days[] → {dayName.fi, dateString, isHidden, isClosed,
    lunches[] → {title.fi, description.fi, allergens[]}}.
    """
    url = f"https://lounastaja.app/api/v1/week/{api_avain}/active?language=fi"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [Lounastaja] virhe: {e}")
        return []
    return _parsi_lounastaja(data)


def _parsi_lounastaja(data: dict) -> list[dict]:
    viikko = ((data or {}).get("data") or {}).get("week") or {}
    paivat = []
    for day in viikko.get("days", []):
        if day.get("isHidden") or day.get("isClosed"):
            continue
        keitto, lounas_, kasvis = [], [], []
        for lounas in day.get("lunches", []):
            nimi = siivoa(((lounas.get("title") or {}).get("fi") or ""))
            kuvaus = siivoa(((lounas.get("description") or {}).get("fi") or ""))
            if not nimi:
                continue
            rivi = f"{nimi} – {kuvaus}" if kuvaus else nimi
            koodit = {((a.get("abbreviation") or {}).get("fi") or "").upper()
                      for a in lounas.get("allergens", [])}
            # Ravintolan oma jako: keittolounas erikseen, lounasbuffetissa
            # kaksi lämmintä ruokaa, joista toinen on kasvisruoka.
            if "keitto" in nimi.lower():
                keitto.append(rivi)
            elif koodit & {"K", "VEG"}:
                kasvis.append(rivi + " (kasvisvaihtoehto)")
            else:
                lounas_.append(rivi)
        if keitto or lounas_ or kasvis:
            # dateString ("2026-09-14") → normalisoi_paiva tunnistaa viikonpäivän
            paiva = day.get("dateString") or (day.get("dayName") or {}).get("fi", "")
            paivat.append(paiva_osastoista(paiva, [osasto("Keitto", keitto),
                                                   osasto("Lounasbuffet", lounas_ + kasvis)]))
    return paivat


def scrape_kontukeittio() -> list[dict]:
    """
    Kontukeittiö Hervanta — ravintolan oman sivun Lounastaja-widgetin data.
    Varalla lounaat.info (näyttää vain kuluvan viikon).
    """
    api_avain = KONTUKEITTIO_API_AVAIN
    html = hae_sivu(KONTUKEITTIO_SIVU)
    if html:
        m = re.search(r'data-api-key="([0-9a-f\-]{20,})"', html)
        if m:
            api_avain = m.group(1)
    paivat = _lounastaja_viikko(api_avain)
    if paivat:
        return paivat
    print("  [Kontukeittiö] Lounastaja ei palauttanut listaa, kokeillaan lounaat.infoa")
    return _scrape_lounaat_info_yleinen("https://lounaat.info/lounas/konnun-keittio-hervanta/tampere")


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
            tl = t.lower()
            if any(k in tl for k in LOUNAAT_INFO_OHITA):
                continue
            if t and len(t) > 2:
                ruoat.append(t)
        if ruoat:
            paivat.append({"paiva": otsikko, "ruoat": ruoat})

    # Jos jokaisella päivällä on täsmälleen sama sisältö, kyse on ravintolan
    # yleistekstistä (esim. Sisu viikonloppuna ennen uuden listan julkaisua),
    # ei oikeasta ruokalistasta.
    if len(paivat) > 1 and len({tuple(p["ruoat"]) for p in paivat}) == 1:
        print("  [lounaat.info] Sama teksti joka päivälle — ei vielä listaa")
        return []
    return paivat


# Lounaat.info-rivit jotka eivät ole ruokia (ravintolan yleistekstiä)
LOUNAAT_INFO_OHITA = (
    "katso päivän lounaslista",
    "lounas kello",
    "alkaen lounaan hinta",
    "buffetin hinta",
    "jälkkäriksi",
    "pyrimme valmistamaan",
    "tervetuloa",
)


# Reaktorin linjastot joita EI näytetä (tyhjä: kaikki näytetään omina osastoinaan)
REAKTORI_OHITA: tuple[str, ...] = ()


def _reaktori_siivoa_nimi(nimi: str) -> str:
    """Poistaa Reaktorin annoskoot ja lisähinnat: "8kpl/annos 0,50€/extra kpl"."""
    nimi = re.sub(r"\s*\d+\s*kpl\s*/\s*annos.*$", "", nimi, flags=re.I)
    nimi = re.sub(r",?\s*extra\b.*$", "", nimi, flags=re.I)
    return siivoa(nimi)


def _parsi_reaktori_json(html: str) -> list[dict]:
    """
    Compass Groupin sivu sisältää valmiin viikkolistan JavaScript-muuttujassa
    window.__INITIAL_MENU__ = {..., "weekMenu": {"menus": [{"date": ...,
    "menuPackages": [{"name": "So Good.", "meals": [{"name": ...}]}]}]}}.

    Jokainen menuPackage (linjasto) on yksi rivi: ruoat pilkulla erotettuna.
    """
    m = re.search(r"window\.__INITIAL_MENU__\s*=\s*(\{)", html)
    if not m:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(html[m.start(1):])
    except json.JSONDecodeError as e:
        print(f"  [Reaktori] JSON-virhe: {e}")
        return []

    paivat = []
    for menu in (data.get("weekMenu") or {}).get("menus", []):
        osastot: list[dict] = []
        for paketti in menu.get("menuPackages", []):
            nimi = (paketti.get("name") or "").strip()
            if any(o in nimi.lower() for o in REAKTORI_OHITA):
                continue
            ateriat = [_reaktori_siivoa_nimi(a.get("name") or "")
                       for a in paketti.get("meals", [])]
            ateriat = [a for a in ateriat if a]
            if not ateriat:
                continue
            osastot.append(osasto(_reaktori_osaston_nimi(nimi), ateriat))
        if osastot:
            paivat.append(paiva_osastoista(menu.get("date", ""), osastot))
    return paivat


def _reaktori_osaston_nimi(nimi: str) -> str:
    """
    "So Green. (Kasvislounas)" → "Kasvislounas", "So Green Soup. (Linjastot 3-4)"
    → "Keitto", "So Good." → "So Good", "Pop Up Grill lounasannos 10:30 - 13:30
    (Break Cafe)" → "Pop Up Grill".
    """
    n = siivoa(nimi)
    nl = n.lower()
    if "pop up grill" in nl:
        return "Pop Up Grill salaatti" if "salaatti" in nl else "Pop Up Grill"
    if "soup" in nl or "keitto" in nl:
        return "Keitto"
    if "sweet" in nl or "jälkiruoka" in nl:
        return "Jälkiruoka"
    if "bread" in nl:
        return "Leipälounas (Break Cafe)"
    sulut = re.findall(r"\(([^)]*)\)", n)
    kuvaus = next((x.strip() for x in sulut if not x.lower().startswith("linjasto")), "")
    if kuvaus:
        return kuvaus
    return re.sub(r"\s*\(.*?\)", "", n).strip().rstrip(".")


def scrape_reaktori() -> list[dict]:
    """
    Reaktori (FoodCo / Compass-Group).

    Ensisijaisesti sivun upotettu JSON (window.__INITIAL_MENU__), varalla
    HTML-otsikoiden (h3 päivä, h4 linjasto) parsinta.
    """
    url = "https://www.compass-group.fi/ravintolat-ja-ruokalistat/foodco/kaupungit/tampere/reaktori/"
    html = hae_sivu(url)
    if not html:
        return []

    paivat = _parsi_reaktori_json(html)
    if paivat:
        return paivat
    print("  [Reaktori] Upotettua JSONia ei löytynyt, käytetään HTML-parsintaa")

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
                ryhma = sis.get_text(strip=True).lower()
                if any(o in ryhma for o in REAKTORI_OHITA):
                    continue
                ul = sis.find_next("ul")
                if ul:
                    for li in ul.find_all("li"):
                        t = _reaktori_siivoa_nimi(li.get_text(" "))
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
                paivat.append(paiva_osastoista(paiva, osastot_etuliitteista(ruoat, oletus="Buffet")))
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
            # Tyhjät rivit (kaksi <br>) säilytetään: ne erottavat ruokaryhmät.
            # get_text() hukkaisi ne, joten <br> muunnetaan rivinvaihdoksi itse.
            teksti = _dd_teksti_riveina(dd)
            # Katkaistaan englannin osuus pois
            if "**" in teksti:
                teksti = teksti.split("**")[0]
            ruoat = _fastelle_ryhmat(teksti)
            if paiva and ruoat:
                paivat.append(paiva_osastoista(paiva, osastot_etuliitteista(ruoat)))
    return paivat


LOHKOTAGIT = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "dt", "dd"}


def teksti_riveina(elementti) -> str:
    """
    Elementin teksti niin, että jokainen <br> ja lohkoelementin raja on
    rivinvaihto, mutta saman rivin <span>-palat pysyvät yhdessä.
    (get_text("\n") katkaisisi rivin jokaisen <span>:n kohdalta.)
    """
    palat: list[str] = []
    for lapsi in elementti.descendants:
        nimi = getattr(lapsi, "name", None)
        if nimi == "br":
            palat.append("\n")
        elif nimi in LOHKOTAGIT:
            palat.append("\n")
        elif nimi is None:
            # Lähdekoodin omat rivinvaihdot <br>-tagien ympärillä eivät ole
            # sisältöä — vain <br> merkitsee rivinvaihtoa.
            teksti = str(lapsi).replace("\n", " ").replace("\r", " ")
            if teksti.strip():
                palat.append(teksti)
    return "".join(palat)


_dd_teksti_riveina = teksti_riveina  # vanha nimi


def _fastelle_ryhmat(teksti: str) -> list[str]:
    """
    Fastellen lista on ryhmitelty tyhjillä riveillä:

        -Maissipaneroitua kananfilettä M,G     ← pääruoka (viiva alussa)
        Ranch kastiketta L,G                   ← sen lisäke

        *Proteiinit punnittavaan salaattiin:   ← otsikko
        – Keitettyä kananmunaa                 ← otsikon alle kuuluvat rivit

    Palauttaa rivit muodossa, jonka osastot_etuliitteista ymmärtää:
    pääruoka ilman viivaa, lisäkkeet "– "-alkuisina alariveinä, otsikot
    sellaisenaan.
    """
    ryhmat: list[list[str]] = [[]]
    for raaka in teksti.split("\n"):
        rivi = siivoa(raaka)
        if not rivi or rivi in ("*", "**"):
            if ryhmat[-1]:
                ryhmat.append([])
            continue
        ryhmat[-1].append(rivi)

    tulos: list[str] = []
    for ryhma in ryhmat:
        if not ryhma:
            continue
        eka = ryhma[0]
        if eka.endswith(":"):
            # Otsikkoryhmä ("*Proteiinit punnittavaan salaattiin:")
            tulos.append(eka.lstrip("*–- ").strip())
            tulos.extend(ryhma[1:])
            continue
        tulos.append(re.sub(r"^[–\-•]\s*", "", eka))
        for lisake in ryhma[1:]:
            if re.match(r"^[–\-•]\s*\S", lisake):
                # Uusi pääruoka samassa ryhmässä
                tulos.append(re.sub(r"^[–\-•]\s*", "", lisake))
            else:
                tulos.append("– " + lisake)
    return tulos


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
        osastot: list[dict] = []
        for kurssi in paiva.get("courses", {}).values():
            nimi = (kurssi.get("title_fi") or kurssi.get("title_en") or "").strip()
            nimi = re.sub(r"^\*\s*", "", nimi).strip()
            if not nimi or nimi in ("-", "–"):
                continue
            linjasto = _sodexo_osaston_nimi(kurssi.get("category") or "")
            # "Bowl Factory: Nuudeleita…" osaston "Bowl Factory" alla → etuliite pois
            nimi = re.sub(rf"^{re.escape(linjasto)}\s*:?\s+", "", nimi, flags=re.I).strip() or nimi
            kohde = next((o for o in osastot if o["nimi"] == linjasto), None)
            if kohde is None:
                kohde = {"nimi": linjasto, "ruoat": []}
                osastot.append(kohde)
            kohde["ruoat"].append(nimi)
        if osastot:
            paivat.append(paiva_osastoista(paiva.get("date", ""), osastot))
    return paivat


def _sodexo_osaston_nimi(category: str) -> str:
    """
    Sodexon linjaston nimi siistittynä: "Kitchen Buffet 13,80 €" → "Kitchen Buffet",
    "FROM THE GRILL" → "Grilli", " Pop Up Lunch 13,80 €" → "Pop Up Lunch".
    """
    c = siivoa(category)
    c = re.sub(r"\s*\d+[,.]\d+\s*(?:/\s*\d+[,.]\d+\s*)?€?\s*$", "", c).strip()
    if not c:
        return "Lounas"
    if c.upper() == c:  # "FROM THE GRILL"
        c = "Grilli" if "GRILL" in c else c.capitalize()
    kaannokset = {"soup of the day": "Päivän keitto", "soup": "Keitto", "salad": "Salaatti",
                  "dessert": "Jälkiruoka", "grill": "Grilli"}
    return kaannokset.get(c.lower(), c)


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

    # Hyväksyttävät kategoriat (h5-otsikot). Hintaotsikot ("13,80 €") toistavat
    # edellisen listan, ne ohitetaan.
    hyvaksytyt = ("pääruo", "grill", "deli", "pizza", "kasvis", "keitto", "kaveri", "jälkiruo")
    hylataan: tuple[str, ...] = ()

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
        osastot: list[dict] = []
        for h5 in panel.find_all("h5"):
            ryhma_nimi = siivoa(h5.get_text())
            ryhma = ryhma_nimi.lower()
            if not any(k in ryhma for k in hyvaksytyt):
                continue
            if any(k in ryhma for k in hylataan):
                continue
            ul = h5.find_next("ul")
            if not ul:
                continue
            ruoat: list[str] = []
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
                if ruoan_nimi not in ruoat:
                    ruoat.append(ruoan_nimi)

            if ruoat and not any(o["nimi"] == ryhma_nimi for o in osastot):
                osastot.append(osasto(ryhma_nimi, ruoat[:8]))

        if osastot:
            paivat.append(paiva_osastoista(fi, osastot))

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

    # 2) Lataa kuva (vain munkkimiehet.fi-sivustolta, korkeintaan 10 Mt)
    kuva_data = hae_tavut(kuva_url, sallittu_domain="munkkimiehet.fi")
    if kuva_data is None:
        print("  [Munkki] Kuvan lataus epäonnistui")
        return []

    # 3) Esikäsittely: pidä vain valkoinen ja punainen teksti
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("  [Munkki] Pillow tai numpy puuttuu — lisää requirements.txt:hen")
        return []

    # Suojaa "pakkauspommilta": pieni tiedosto joka purkautuu jättikuvaksi ja
    # söisi koko muistin. Lounaslistakuva on korkeintaan muutama megapikseli.
    Image.MAX_IMAGE_PIXELS = 50_000_000

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
            rivit = paivat_dict[p][:6]
            keitot = [r for r in rivit if "keitto" in r.lower()]
            muut = [r for r in rivit if "keitto" not in r.lower()]
            if keitot and muut:
                paivat.append(paiva_osastoista(p, [osasto("Keitto", keitot), osasto("Lounas", muut)]))
            else:
                paivat.append({"paiva": p, "ruoat": rivit})
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

    return [_osku_osastot(p) for p in paivat]


def _osku_osastot(paiva: dict) -> dict:
    """
    Oskun rivit ovat aina samassa järjestyksessä: pääruoka (/ vaihtoehto),
    kasvisruoka, "Delisalaatti (...) & keitto", jälkiruoka "/ hedelmä".
    """
    lounas, deli, jalkiruoka = [], [], []
    for r in paiva["ruoat"]:
        r = re.sub(r"\s*/\s*hedelmä\s*$", " tai hedelmä", r, flags=re.I)
        rl = r.lower()
        if rl.startswith("delisalaatti") or "delisalaatti" in rl:
            deli.append(r)
        elif re.search(r"\bhedelmä\s*$", rl) or re.search(r"rahka|mousse|kiisseli|smoothie|vanukas|jälkiruo", rl):
            jalkiruoka.append(r)
        else:
            lounas.append(r)
    if not deli and not jalkiruoka:
        return paiva
    return paiva_osastoista(paiva["paiva"], [osasto("Lounas", lounas),
                                             osasto("Delisalaatti & keitto", deli),
                                             osasto("Jälkiruoka", jalkiruoka)])


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

    # 0) Syyskuusta 2026 lista on suoraan sivun HTML:ssä (ei PDF:nä)
    paivat = _parsi_aito_html(soup)
    if paivat:
        return paivat
    print("  [Aito] HTML-listaa ei löytynyt, kokeillaan PDF:ää")

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
        # Varasuunnitelma 1: linkki, iframe, embed tai object joka viittaa PDF:ään
        for tag in soup.find_all(["a", "iframe", "embed", "object"]):
            viite = tag.get("href") or tag.get("src") or tag.get("data") or ""
            if ".pdf" in viite.lower():
                pdf_url = viite
                break

    if not pdf_url:
        # Varasuunnitelma 2: mikä tahansa .pdf-osoite sivun lähdekoodissa
        # (myös JSON-koodattu muoto "https:\/\/...")
        m = re.search(r"https?://[^\s\"'<>]+?\.pdf", html.replace("\\/", "/"), re.I)
        if m:
            pdf_url = m.group(0)

    if not pdf_url:
        print("  [Aito] PDF-URL ei löytynyt HTML:stä — sivun rakenne on "
              "muuttunut, tarkista https://www.aitokotilounas.fi/lounaslista/")
        return []

    # Suhteellinen osoite → absoluuttinen
    pdf_url = urljoin(url, pdf_url)

    print(f"  [Aito] PDF: {pdf_url}")

    # 2) Lataa PDF (vain aitokotilounas.fi-sivustolta, korkeintaan 10 Mt)
    pdf_data = hae_tavut(pdf_url, sallittu_domain="aitokotilounas.fi")
    if pdf_data is None:
        print("  [Aito] PDF-lataus epäonnistui")
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


def _parsi_aito_html(soup: BeautifulSoup) -> list[dict]:
    """
    Aito kotilounaan HTML-lista (Elementor):

        <p><strong>Maanantai 14.09.</strong></p>
        <ul>
          <li>Lohileikettä sitruuna-tillikastikkeella ja muusia (L)</li>
          <li>Suklaarahkaa (G,L) Keittiöstä: Fetasalaatti (G,L)</li>
        </ul>
        <p>Keittiöstä: Mozzarellasalaatti (G,L)</p>   ← joskus omana p:nä

    "Keittiöstä: X" voi olla liimautunut edellisen ruoan perään samaan li:hin,
    joten se erotetaan omaksi rivikseen.
    """
    paiva_re = re.compile(
        r"^(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai|Lauantai)\s+\d{1,2}\.\d{1,2}",
        re.I,
    )
    ohita = ("etusivulle", "yhteyslomake", "tietosuoja", "katso sijaintimme",
             "catering", "pysäköinti", "lounas tarjoillaan", "lounashinta",
             "annokset saatavilla")

    paivat: list[dict] = []
    nykyinen: str | None = None
    ruoat: list[str] = []

    def lopeta_paiva():
        nonlocal nykyinen, ruoat
        if nykyinen and ruoat:
            paivat.append(paiva_osastoista(nykyinen, osastot_etuliitteista(ruoat[:8])))
        nykyinen, ruoat = None, []

    for el in soup.find_all(["p", "li", "h2", "h3", "h4"]):
        # Sisäkkäiset elementit (li > p) tuottaisivat duplikaatteja
        if el.find(["p", "li"]):
            continue
        teksti = siivoa(el.get_text(" "))
        if not teksti:
            continue
        if paiva_re.match(teksti) and len(teksti) < 40:
            lopeta_paiva()
            nykyinen = teksti
            continue
        if not nykyinen:
            continue
        # Navigaatio/footer-listat (Elementorin icon-list) päättävät listan
        luokat = " ".join(el.get("class") or [])
        if "icon-list" in luokat or any(o in teksti.lower() for o in ohita):
            lopeta_paiva()
            continue
        if el.name in ("h2", "h3", "h4"):
            lopeta_paiva()
            continue
        if len(teksti) > 200:
            continue
        # "Suklaarahkaa (G,L) Keittiöstä: Fetasalaatti (G,L)" → kaksi riviä
        osat = re.split(r"\s*(?=Keittiöstä:)", teksti)
        for osa in osat:
            osa = osa.strip()
            if len(osa) >= 4:
                ruoat.append(osa)
    lopeta_paiva()
    return paivat


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
    # pypdf tulostaa 2-sarakkeisen PDF:n niin, että vasemman sarakkeen päivän
    # kaikki rivit tulevat ensin ja oikean sarakkeen päivän rivit sen jälkeen.
    # Päivän viimeinen rivi on aina "Keittiöstä: ..." — sen jälkeen siirrytään
    # oikeaan sarakkeeseen.
    sarake_oikea = False

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
            sarake_oikea = False
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

        # Kumman sarakkeen päivälle rivi kuuluu?
        kohde = nykyinen_oikea if (sarake_oikea and nykyinen_oikea) else nykyinen_vasen

        if on_jatkorivi:
            # Yhdistä edelliseen riviin (jos oikea sarake on vielä tyhjä,
            # jatkorivi kuuluu vasemman sarakkeen viimeiseen riviin)
            jatko_kohde = kohde if paivat_dict[kohde] else nykyinen_vasen
            if paivat_dict[jatko_kohde]:
                paivat_dict[jatko_kohde][-1] += " " + rivi
        else:
            # Poista bullet ja whitespace alusta
            puhdas = _re.sub(r"^[•\-\*]\s*", "", rivi)
            if puhdas:
                paivat_dict[kohde].append(puhdas)
                if puhdas.lower().startswith("keittiöstä") and nykyinen_oikea:
                    sarake_oikea = True

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

    rivit: list[str] = []
    for el in soup.find_all(["p", "h2", "h3", "h4", "li"]):
        if el.find(["p", "li"]):
            continue  # sisäkkäinen: käsitellään lapsissa
        for rivi in teksti_riveina(el).split("\n"):
            rivi = siivoa(rivi)
            if rivi:
                rivit.append(rivi)

    for teksti in rivit:
        if len(teksti) > 200:
            continue
        on_paiva = False
        valmis = False
        for paiva in paivat_nimet:
            if teksti.lower().startswith(paiva.lower()) and len(teksti) < 30:
                on_paiva = True
                if paiva.lower() in nahdyt_paivat:
                    # Sama päivä toistuu. Jos välissä ei ole ruokia, kyse on
                    # sisäkkäisestä elementistä (div > p) → ohitetaan. Jos
                    # ruokia on jo kerätty, lista on päättynyt ja sivun
                    # alaosa (aukioloajat "MAANANTAI ...") alkaa → lopetetaan.
                    if nykyiset_ruoat:
                        valmis = True
                    break
                nahdyt_paivat.add(paiva.lower())
                if nykyinen_paiva and nykyiset_ruoat:
                    paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})
                nykyinen_paiva = teksti
                nykyiset_ruoat = []
                break
        if valmis:
            break
        if on_paiva:
            continue
        if nykyinen_paiva and 5 < len(teksti) < 150:
            ohita = ["lounaslista", "tilaa", "leipomo", "vapun", "ole hyvä",
                     # Sivun alaosan toimipaikkalista
                     "prisma", "äänekoski", "keljo", "vaajakoski", "muurame"]
            if any(o in teksti.lower() for o in ohita):
                continue
            if teksti not in nykyiset_ruoat:
                nykyiset_ruoat.append(teksti)

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})

    return [_caffitella_osastot(p) for p in paivat]


def _caffitella_osastot(paiva: dict) -> dict:
    """
    Caffitella: "(annosruoka ei sis. buffettiin)" -rivit omaan osastoon.
    Samalla rivillä voi olla useita annoksia allergeenisulkujen erottamina:
    "Broiler burger (L) Tofu poke (G,VE)" → kaksi riviä.
    """
    buffet, annokset = [], []
    for r in paiva["ruoat"]:
        if "annosruoka" in r.lower():
            r = re.sub(r"\s*\(annosruoka[^)]*\)", "", r, flags=re.I).strip()
            annokset.extend(a.strip() for a in re.split(r"(?<=\))\s+(?=[A-ZÄÖÅ])", r) if a.strip())
        else:
            buffet.append(r)
    if not annokset:
        return paiva
    return paiva_osastoista(paiva["paiva"], [osasto("Lounasbuffet", buffet),
                                             osasto("Annosruoat (ei sis. buffettiin)", annokset)])


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
        "url": KONTUKEITTIO_SIVU,
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


def lue_edellinen(polku: Path) -> dict[str, dict]:
    """Edellisen ajon tulokset ravintolan nimen mukaan (tyhjä jos ei tiedostoa)."""
    if not polku.exists():
        return {}
    try:
        data = json.loads(polku.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"! Edellistä lounaat.jsonia ei voitu lukea: {e}")
        return {}
    return {r["nimi"]: r for r in data.get("ravintolat", []) if r.get("nimi")}


def main():
    polku = Path(__file__).parent / "lounaat.json"
    edellinen = lue_edellinen(polku)
    nyt = datetime.now(timezone.utc)

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
                    puhdas = siivoa_paiva(p)
                    if puhdas:
                        siivotut.append(puhdas)
                rivi["paivat"] = siivotut
                print(f"  -> {len(rivi['paivat'])} päivää löytyi")
            except Exception as e:
                print(f"  ! Virhe: {e}")
                rivi["virhe"] = str(e)
        else:
            print(f"  -> vain linkki")

        if ravintola["scraper"] is not None:
            # Laadunvalvonta: rikkinäisen tuloksen tilalle edellinen lista,
            # jotta yhden lähteen muutos ei tyhjennä sivustoa.
            rivi = laatu.yhdista(rivi, edellinen.get(rivi["nimi"]), nyt)
            if rivi.get("ongelmat"):
                for o in rivi["ongelmat"]:
                    print(f"  ! Laatuongelma: {o}")
                if rivi.get("vanhentunut"):
                    print("  -> säilytetään edellisen ajon lista")
        tulokset.append(rivi)

    ulos = {
        "paivitetty": nyt.isoformat(),
        "ravintolat": tulokset,
    }
    polku.write_text(json.dumps(ulos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nValmis. Tallennettu: {polku}")

    rap = laatu.raportti(tulokset, nyt)
    laatu.tulosta_raportti(rap)
    raportti_polku = Path(__file__).parent / "laaturaportti.json"
    raportti_polku.write_text(json.dumps(rap, ensure_ascii=False, indent=2),
                              encoding="utf-8")


if __name__ == "__main__":
    main()
