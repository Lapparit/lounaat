"""
Tampereen Hervannan lounaslistojen kerääjä.

Käy läpi listan ravintoloita, hakee niiden lounaslistat ja tallentaa
tulokset tiedostoon lounaat.json.

Jokaisella hankalalla ravintolalla on oma scraper-funktio joka tuntee
sen sivun rakenteen tarkasti.

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


PAIVA_JARJESTYS = {
    "maanantai": 0, "tiistai": 1, "keskiviikko": 2, "torstai": 3,
    "perjantai": 4, "lauantai": 5, "sunnuntai": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


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


def jarjesta_paivat(paivat: list[dict]) -> list[dict]:
    """Järjestää päivät ma-pe-järjestykseen."""
    def avain(p):
        teksti = (p.get("paiva") or "").lower()
        for nimi, idx in PAIVA_JARJESTYS.items():
            if nimi in teksti or nimi.rstrip("i") in teksti:
                return idx
        return 99
    return sorted(paivat, key=avain)


def siivoa(teksti: str) -> str:
    """Siivoa whitespace-virheet tekstistä."""
    return re.sub(r"\s+", " ", teksti).strip()


# ============================================================
# RAVINTOLAKOHTAISET SCRAPERIT
# ============================================================


def scrape_sisu_buffet() -> list[dict]:
    """Sisu Buffet — Lounaat.infosta. Vain lounas-otsikot, ei arvosteluja."""
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
    return jarjesta_paivat(paivat)


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
    return jarjesta_paivat(paivat)


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
    return jarjesta_paivat(paivat)


def scrape_linkosuo(url: str) -> list[dict]:
    """
    Linkosuo (Hertta, Orvokki) — dl/dt/dd-rakenne.
    HUOM: Fastellelle on oma funktio koska siellä on suomi+englanti.
    """
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
    return jarjesta_paivat(paivat)


def scrape_fastelle() -> list[dict]:
    """
    Fastelle — sama dl/dt/dd-rakenne kuin muilla Linkosuoilla, MUTTA
    sisältää sekä suomi- että englanti-listan, eroteltuna '**'-merkillä.
    Otetaan vain suomenkielinen osa (ennen '**').
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

            # Katkaistaan englannin osuus pois — se alkaa '**':lla
            if "**" in teksti:
                teksti = teksti.split("**")[0]

            ruoat = [r.strip() for r in teksti.split("\n") if r.strip()]
            # Suodatetaan tähdet jos jäänyt yksittäisiä
            ruoat = [r for r in ruoat if r and r != "*" and r != "**"]
            if paiva and ruoat:
                paivat.append({"paiva": paiva, "ruoat": ruoat})
    return jarjesta_paivat(paivat)


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


def scrape_hermianfarmi() -> list[dict]:
    """
    Antell Hermianfarmi — sivulla on jokaiselle päivälle paneeli #panel-Monday jne.
    Sisällä kategoriat (Pääruoaksi, Grilliannos, Delilounas, Pizzalounas).
    Jokaisen kategorian alla <ul> jossa <li>-elementit.

    Jokainen ruoka-li sisältää:
    - ruoan nimen suoraan tekstinä li:n alussa (ennen "Allergeenit" tms.)
    - alielementtejä (allergiatiedot, "Miltä maistui?" -linkki)

    Aiempi versio nappasi "Miltä maistui?" -tekstin koska li:n .get_text() palautti
    koko sisällön. Korjaus: otetaan vain li:n SUORAAN sisältönä oleva teksti
    (NavigableString-tyyppiset lapset, eivät elementtien sisällä olevat).
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

    # Hyväksyttävät kategoriat — otetaan kaikki pääruoat, grilli, deli, pizza
    hyvaksytyt_kategoriat = ("pääruoa", "grilli", "deli", "pizza")
    # Suodatetaan pois lisäkkeet ja jälkkärit
    hylataan_kategoriat = ("kaveri", "jälkiruo", "salaatti")

    paivat = []
    for eng, fi in paivat_kaannos.items():
        panel = soup.find(id=f"panel-{eng}")
        if not panel:
            continue
        ruoat = []
        for h5 in panel.find_all("h5"):
            ryhma = siivoa(h5.get_text()).lower()
            if not any(k in ryhma for k in hyvaksytyt_kategoriat):
                continue
            if any(k in ryhma for k in hylataan_kategoriat):
                continue
            # Etsitään seuraava ul, joka kuuluu tähän kategoriaan
            ul = h5.find_next("ul")
            if not ul:
                continue
            for li in ul.find_all("li", recursive=False):
                # Otetaan li:n SUORAAN sisältönä oleva teksti (ei alielementtien)
                # Tämä on ruoan nimi ennen "Allergeenit"-osiota
                suorat_tekstit = []
                for child in li.children:
                    # NavigableString = puhdas tekstinpätkä, ei elementti
                    if isinstance(child, str):
                        teksti = child.strip()
                        if teksti:
                            suorat_tekstit.append(teksti)
                    # Pysähdy ennen <p> tai <div> jossa "Allergeenit"
                    elif hasattr(child, "name") and child.name in ("p", "div"):
                        if "allergeenit" in child.get_text("").lower():
                            break
                        # Jos ei allergeenit, mutta on muu p, voi sisältää nimen
                        teksti = child.get_text(" ", strip=True)
                        if teksti and "allergeenit" not in teksti.lower() and "miltä maistui" not in teksti.lower():
                            suorat_tekstit.append(teksti)

                nimi = siivoa(" ".join(suorat_tekstit))
                # Suodatetaan pois tyhjät ja "Miltä maistui?"
                if not nimi or len(nimi) < 4:
                    continue
                if "miltä maistui" in nimi.lower():
                    continue
                # Joskus rivin lopussa on allergeenikoodit kuten "A, G, L"
                # Poistetaan ne
                nimi = re.sub(r",?\s*[A-Z](,\s*[A-Z]+)+\s*$", "", nimi).strip()
                if nimi and len(nimi) > 3:
                    ruoat.append(nimi)
        # Poistetaan duplikaatit säilyttäen järjestys
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
    """Munkkimiehet — lista on kuvana, ei voida automaattisesti lukea."""
    return []


def scrape_ruskonhelmi() -> list[dict]:
    """Ruskonhelmi — <strong>-tagilla merkityt päivät."""
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

    return jarjesta_paivat(paivat)


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
            kaannos = {"Ma": "Maanantai", "Ti": "Tiistai", "Ke": "Keskiviikko",
                       "To": "Torstai", "Pe": "Perjantai"}
            for lyhyt, pitka in kaannos.items():
                if teksti.startswith(lyhyt):
                    teksti = teksti.replace(lyhyt, pitka, 1)
                    break
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

    return jarjesta_paivat(paivat)


def scrape_aitokoti() -> list[dict]:
    """
    Lounas Lempäälä (Sääksjärven lounaskahvila) - 'Aitokoti' on yrityksen
    domain, mutta ravintolan virallinen nimi on 'Lounas Lempäälä'.

    Yritetään hakea oikea lounaslista. Sivu voi olla 403-suojattu osalle
    palvelimista (esim. tämän tutkimuksen ympäristö), mutta toimii
    GitHub Actionsista. Yleisparseri tunnistaa viikonpäivät tekstistä.
    """
    url = "https://www.aitokotilounas.fi/lounaslista/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    main = soup.find("main") or soup.find(class_="entry-content") or soup

    paivat_nimet = ("Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai")
    paivat = []
    nykyinen_paiva = None
    nykyiset_ruoat: list[str] = []

    for el in main.find_all(["p", "strong", "h2", "h3", "h4", "li"]):
        teksti = siivoa(el.get_text(" "))
        if not teksti:
            continue
        on_paiva = False
        for paiva in paivat_nimet:
            if teksti.lower().startswith(paiva.lower()) and len(teksti) < 60:
                if nykyinen_paiva and nykyiset_ruoat:
                    paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})
                nykyinen_paiva = teksti
                nykyiset_ruoat = []
                on_paiva = True
                break
        if on_paiva:
            continue
        if nykyinen_paiva and 5 < len(teksti) < 150:
            if teksti not in nykyiset_ruoat:
                nykyiset_ruoat.append(teksti)

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})

    return jarjesta_paivat(paivat)


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

    return jarjesta_paivat(paivat)


# ============================================================
# RAVINTOLAT
# ============================================================

RAVINTOLAT = [
    {
        "nimi": "Sisu Buffet",
        "alue": "Hervanta",
        "url": "https://lounaat.info/lounas/sisu-buffet-hervanta/tampere",
        "scraper": lambda: scrape_sisu_buffet(),
    },
    {
        "nimi": "Speakeasy",
        "alue": "Hervanta",
        "url": "https://www.speakeasy.fi/hervanta/lounas/",
        "scraper": lambda: scrape_speakeasy(),
    },
    {
        "nimi": "Kontukeittiö",
        "alue": "Hervanta",
        "url": "https://kontukoti.fi/kontukeittio/kontukeittio-hervanta/",
        "scraper": lambda: scrape_kontukeittio(),
    },
    {
        "nimi": "Reaktori (FoodCo)",
        "alue": "Hervanta",
        "url": "https://www.compass-group.fi/ravintolat-ja-ruokalistat/foodco/kaupungit/tampere/reaktori/",
        "scraper": lambda: scrape_reaktori(),
    },
    {
        "nimi": "Hertta",
        "alue": "Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/hertta/",
        "scraper": lambda: scrape_linkosuo("https://linkosuo.fi/toimipaikka/hertta/"),
    },
    {
        "nimi": "Orvokki",
        "alue": "Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/lounasravintola-orvokki/",
        "scraper": lambda: scrape_linkosuo("https://linkosuo.fi/toimipaikka/lounasravintola-orvokki/"),
    },
    {
        "nimi": "Hermia 5",
        "alue": "Hervanta",
        "url": "https://www.sodexo.fi/ravintolat/ravintola-hermia-5",
        "scraper": lambda: scrape_sodexo(107),
    },
    {
        "nimi": "Hermia 6",
        "alue": "Hervanta",
        "url": "https://www.sodexo.fi/ravintolat/tampere/hermia-6",
        "scraper": lambda: scrape_sodexo(108),
    },
    {
        "nimi": "Hermian Farmi",
        "alue": "Hervanta",
        "url": "https://antell.fi/lounas/tampere/hermianfarmi/",
        "scraper": lambda: scrape_hermianfarmi(),
    },
    {
        "nimi": "Munkkimiehet",
        "alue": "Hervanta",
        "url": "https://munkkimiehet.fi/kuluttajille/",
        "scraper": lambda: scrape_munkkimiehet(),
        "huom": "Lounaslista on kuvana — avaa ravintolan sivulta",
    },
    {
        "nimi": "Ruskonhelmi",
        "alue": "Hervanta",
        "url": "https://ruskonhelmi.fi/lounaslista/",
        "scraper": lambda: scrape_ruskonhelmi(),
    },
    {
        "nimi": "Ravintola Osku",
        "alue": "Rusko",
        "url": "https://ravintolaosku.fi/",
        "scraper": lambda: scrape_osku(),
    },
    {
        "nimi": "Aito kotilounas Sääksjärvi",
        "alue": "Lempäälä",
        "url": "https://www.aitokotilounas.fi/lounaslista/",
        "scraper": lambda: scrape_aitokoti(),
    },
    {
        "nimi": "Fastelle",
        "alue": "Lahdesjärvi",
        "url": "https://linkosuo.fi/toimipaikka/ravintola-fastelle/",
        "scraper": lambda: scrape_fastelle(),
    },
    {
        "nimi": "Caffitella",
        "alue": "Hervanta",
        "url": "https://www.caffitella.fi/lounaslista/",
        "scraper": lambda: scrape_caffitella(),
    },
    # Vain linkit (ei lounaslistaa nettisivulla)
    {
        "nimi": "Ravintola Idaho",
        "alue": "Hervanta",
        "url": "https://www.facebook.com/people/Ravintola-Idaho-Oy/100070629319742/",
        "scraper": None,
        "huom": "Lounaslista löytyy Facebookista",
    },
    {
        "nimi": "Malabadi",
        "alue": "Hervanta",
        "url": "https://www.malabadi.fi/",
        "scraper": None,
        "huom": "Ei lounaslistaa nettisivulla",
    },
    {
        "nimi": "Gate of India",
        "alue": "Hervanta",
        "url": "https://www.gateofindia.fi/",
        "scraper": None,
        "huom": "Ei lounaslistaa nettisivulla",
    },
    {
        "nimi": "Malakai",
        "alue": "Hervanta",
        "url": "https://malakairavintola.fi/",
        "scraper": None,
        "huom": "Ei lounaslistaa nettisivulla",
    },
    {
        "nimi": "Heval",
        "alue": "Hervanta",
        "url": "https://heval.fi/lounas/",
        "scraper": None,
        "huom": "Avaa lounaslista ravintolan sivulta",
    },
]


def main():
    tulokset = []
    for ravintola in RAVINTOLAT:
        print(f"Haetaan: {ravintola['nimi']}...")
        rivi = {
            "nimi": ravintola["nimi"],
            "alue": ravintola["alue"],
            "url": ravintola["url"],
            "huom": ravintola.get("huom", ""),
            "paivat": [],
        }
        if ravintola["scraper"] is not None:
            try:
                rivi["paivat"] = ravintola["scraper"]()
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
