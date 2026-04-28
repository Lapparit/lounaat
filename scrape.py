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


# Suomalaiset päivien nimet päivien järjestämistä varten
PAIVA_JARJESTYS = {
    "maanantai": 0, "tiistai": 1, "keskiviikko": 2, "torstai": 3,
    "perjantai": 4, "lauantai": 5, "sunnuntai": 6,
    # myös englanninkieliset koska Antell käyttää niitä
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
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    paiva_re = re.compile(r"^(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)", re.I)

    for h3 in soup.find_all("h3"):
        otsikko = h3.get_text(strip=True)
        # Lounaat.infon päiväotsikoissa on aina päivämäärä
        if not (paiva_re.match(otsikko) and re.search(r"\d{1,2}\.\d{1,2}", otsikko)):
            continue
        ul = h3.find_next("ul")
        if not ul:
            continue
        ruoat = []
        for li in ul.find_all("li"):
            t = siivoa(li.get_text(" "))
            # Suodatetaan pois ravintolan ilmoitukset (hinta, kellonaika)
            if "alkaen lounaan hinta" in t.lower():
                continue
            if t.lower().startswith("lounas kello"):
                continue
            if t and len(t) > 2:
                ruoat.append(t)
        if ruoat:
            paivat.append({"paiva": otsikko, "ruoat": ruoat})
    return jarjesta_paivat(paivat)


def scrape_speakeasy() -> list[dict]:
    """Speakeasy Hervanta — toimii hyvin jo nyt, säilytetään logiikka."""
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
    """
    Kontukeittiö Hervanta — oma sivu lataa listan dynaamisesti, joten
    haetaan Lounaat.infosta missä se on staattisena.
    Lounaat.info-osoite: konnun-keittio-hervanta (huom: ei "kontukeittio").
    """
    url = "https://lounaat.info/lounas/konnun-keittio-hervanta/tampere"
    return _scrape_lounaat_info_yleinen(url)


def _scrape_lounaat_info_yleinen(url: str) -> list[dict]:
    """Yleinen Lounaat.info-scraperi — käytetään ravintoloille jotka eivät
    syötä listoja omille sivuilleen."""
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
            # "Katso päivän lounaslista ravintolan sivuilta!" ei ole oikea ruokarivi
            if "katso päivän lounaslista" in t.lower():
                continue
            if t.lower().startswith("lounas kello"):
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
                # Vain pääateriat
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
    """Linkosuo (Hertta, Orvokki, Fastelle) — dl/dt/dd-rakenne."""
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


def scrape_sodexo(rajapinta_id: int) -> list[dict]:
    """Sodexo — virallinen JSON-rajapinta. Tarkin ja luotettavin."""
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
            # Siivotaan "* "-merkki nimien alusta
            nimi = re.sub(r"^\*\s*", "", nimi).strip()
            if nimi:
                ruoat.append(nimi)
        if ruoat:
            paivat.append({"paiva": paiva.get("date", ""), "ruoat": ruoat})
    return paivat


def scrape_hermianfarmi() -> list[dict]:
    """
    Antell Hermianfarmi — sivulla on jokaiselle päivälle oma välilehti
    id:llä #panel-Monday, #panel-Tuesday jne. Jokaisessa h5-otsikko
    "Pääruoaksi" alkavat kategoriat. Otetaan vain h5 = "Pääruoaksi"
    sisältö ja li-elementtien ENSIMMÄISET tekstit (ei ainesosia).
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

    paivat = []
    for eng, fi in paivat_kaannos.items():
        panel = soup.find(id=f"panel-{eng}")
        if not panel:
            continue
        ruoat = []
        # Etsitään h5-otsikot ja niiden sisällöt
        for h5 in panel.find_all("h5"):
            ryhma = siivoa(h5.get_text())
            # Otetaan vain "Pääruoaksi" jotta ei tule liikaa rivejä
            if "pääruoa" not in ryhma.lower():
                continue
            # Kerätään seuraavan ul:n li:t, mutta vain ensimmäinen tekstirivi
            # ennen "Allergeenit:" tai muut yksityiskohdat
            ul = h5.find_next("ul")
            if not ul:
                continue
            for li in ul.find_all("li", recursive=False):
                # Otetaan vain otsikko, ei ainesosia
                ensimmainen_teksti = ""
                for kohta in li.children:
                    if hasattr(kohta, "get_text"):
                        teksti = kohta.get_text(strip=True)
                        if teksti and "Allergeenit" not in teksti:
                            ensimmainen_teksti = teksti
                            break
                    elif isinstance(kohta, str) and kohta.strip():
                        ensimmainen_teksti = kohta.strip()
                        break
                if ensimmainen_teksti and len(ensimmainen_teksti) > 3:
                    ruoat.append(ensimmainen_teksti)
        if ruoat:
            paivat.append({"paiva": fi, "ruoat": ruoat[:8]})
    return paivat


def scrape_munkkimiehet() -> list[dict]:
    """
    Munkkimiehet — lounaslista on kuvana (PNG), ei tekstinä.
    Ei voida automaattisesti lukea. Palautetaan tyhjä lista.
    """
    return []


def scrape_ruskonhelmi() -> list[dict]:
    """
    Ruskonhelmi — sivulla on rakenne: <p><strong>MAANANTAI 27.4</strong></p>
    sitten <p>RUOKA1</p><p>RUOKA2</p>. Päivät ovat strong-elementeissä.
    """
    url = "https://ruskonhelmi.fi/lounaslista/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Hae lounaslistan sisältöalue
    main = soup.find("main") or soup.find(class_="entry-content") or soup

    paivat_nimet = ("MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI", "PERJANTAI")
    paivat = []
    nykyinen_paiva = None
    nykyiset_ruoat: list[str] = []

    # Käydään kaikki tekstipätkät läpi
    for el in main.find_all(["p", "strong", "h2", "h3", "h4"]):
        teksti = siivoa(el.get_text(" "))
        if not teksti:
            continue
        # Tarkistetaan onko päivä-otsikko
        on_paiva = False
        for paiva_nimi in paivat_nimet:
            if teksti.upper().startswith(paiva_nimi):
                # Tallennetaan edellinen päivä jos sellainen on
                if nykyinen_paiva and nykyiset_ruoat:
                    paivat.append({
                        "paiva": nykyinen_paiva,
                        "ruoat": nykyiset_ruoat[:6],
                    })
                nykyinen_paiva = teksti
                nykyiset_ruoat = []
                on_paiva = True
                break
        if on_paiva:
            continue
        # Muut rivit lisätään ruokina nykyiselle päivälle
        if nykyinen_paiva and len(teksti) > 3 and len(teksti) < 150:
            # Suodatetaan pois muu sisältö
            ohita = ["lounasruokien", "tilaa", "munkit", "kotiruoka", "lounas:",
                     "keittolounas", "puh.", "ruskon helmi", "vapuksi",
                     "tervetuloa", "take away"]
            if any(o in teksti.lower() for o in ohita):
                continue
            # Suodatetaan duplikaatit
            if teksti not in nykyiset_ruoat:
                nykyiset_ruoat.append(teksti)

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})

    return jarjesta_paivat(paivat)


def scrape_osku() -> list[dict]:
    """
    Ravintola Osku — Ruskon ravintolan lista. Sivulla h2 = "Lounaslista Rusko",
    sitten p-elementtejä joista osa on päivä-otsikko ("Ma 27.4.") ja osa ruoka.
    """
    url = "https://ravintolaosku.fi/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Etsitään Ruskon lounaslista
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
        # Pysäytä kun tulee seuraava h2 (esim. "Lounaslista Linnavuori")
        if el.name == "h2" and "lounaslista" in el.get_text().lower():
            break
        if el.name != "p":
            continue
        teksti = siivoa(el.get_text(" "))
        if not teksti:
            continue
        # Onko tämä päivä?
        if paiva_re.match(teksti):
            if nykyinen_paiva and nykyiset_ruoat:
                paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat})
            # Käännetään lyhennetty päivä täysmuotoon
            kaannos = {"Ma": "Maanantai", "Ti": "Tiistai", "Ke": "Keskiviikko",
                       "To": "Torstai", "Pe": "Perjantai"}
            for lyhyt, pitka in kaannos.items():
                if teksti.startswith(lyhyt):
                    teksti = teksti.replace(lyhyt, pitka, 1)
                    break
            nykyinen_paiva = teksti
            nykyiset_ruoat = []
        elif nykyinen_paiva and len(teksti) > 5:
            # Suodatetaan loppuhuomautukset
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
    Aitokoti / Sääksjärven lounaskahvila (Lempäälä).
    Sivu lataa listan jollakin tavalla joka voi olla 403-suojattu.
    Yritetään, palautetaan tyhjä jos ei onnistu.
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
    """
    Caffitella — sivu vaikuttaa monimutkaiselta. Yritetään yksinkertainen
    parseri joka etsii viikonpäivien jälkeisiä rivejä.
    Aikaisemmin se duplikoitui — käytetään siksi setiä.
    """
    url = "https://www.caffitella.fi/lounaslista/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Poistetaan navigointi ja muu turhat osat
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
                # Vältetään saman päivän duplikaatit
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
            # Suodatetaan turhia
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
        "nimi": "Hermianfarmi",
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
        "nimi": "Aitokoti",
        "alue": "Lempäälä",
        "url": "https://www.aitokotilounas.fi/lounaslista/",
        "scraper": lambda: scrape_aitokoti(),
    },
    {
        "nimi": "Fastelle",
        "alue": "Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/ravintola-fastelle/",
        "scraper": lambda: scrape_linkosuo("https://linkosuo.fi/toimipaikka/ravintola-fastelle/"),
    },
    {
        "nimi": "Caffitella",
        "alue": "Hervanta",
        "url": "https://www.caffitella.fi/lounaslista/",
        "scraper": lambda: scrape_caffitella(),
    },
    # Vain linkit
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
