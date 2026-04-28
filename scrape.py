"""
Tampereen Hervannan lounaslistojen kerääjä.

Tämä script käy läpi listan ravintoloita, hakee niiden lounaslistat
ja tallentaa ne tiedostoon lounaat.json.

Käyttö: python scrape.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Kuinka kauan odotetaan ennen kuin jokin sivu luovutetaan
TIMEOUT = 20

# Selain-otsikot — jotkut sivut estävät pyynnöt joilla ei ole näitä
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fi,en;q=0.9",
}


def hae_sivu(url: str) -> str | None:
    """Hakee yhden URLin sisällön. Palauttaa None jos epäonnistuu."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        # Joillakin sivuilla on koodausvirheitä — pakotetaan UTF-8
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"  ! Virhe haettaessa {url}: {e}")
        return None


# ---------- Sodexo (käyttää JSON-rajapintaa, helpoin) ----------

def scrape_sodexo(rajapinta_id: int) -> list[dict]:
    """
    Hakee Sodexon ravintolan listan virallisesta JSON-rajapinnasta.
    rajapinta_id löytyy ravintolan sivun lähdekoodista (esim. Hermia 5 = 107).
    """
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
            kategoria_nimi = (kategoria.get("category") or "").strip()
            if nimi:
                rivi = nimi
                if kategoria_nimi:
                    rivi = f"{kategoria_nimi}: {nimi}"
                ruoat.append(rivi)
        if ruoat:
            paivat.append({"paiva": paiva.get("date", ""), "ruoat": ruoat})
    return paivat


# ---------- Lounaat.info ----------

def scrape_lounaat_info(url: str) -> list[dict]:
    """Lounaat.info on selkeä: päivät ovat h3-otsikoita ja ruoat ul-listoja."""
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    for h3 in soup.find_all("h3"):
        otsikko = h3.get_text(strip=True)
        # Esim. "Maanantaina 27.4."
        if not re.search(r"\d{1,2}\.\d{1,2}", otsikko):
            continue
        ul = h3.find_next("ul")
        if not ul:
            continue
        ruoat = [li.get_text(" ", strip=True) for li in ul.find_all("li")]
        ruoat = [r for r in ruoat if r]
        if ruoat:
            paivat.append({"paiva": otsikko, "ruoat": ruoat})
    return paivat


# ---------- Speakeasy Hervanta ----------

def scrape_speakeasy() -> list[dict]:
    """Speakeasylla on lista yhdessä isossa tekstilohkossa, jaetaan päiviksi."""
    html = hae_sivu("https://www.speakeasy.fi/hervanta/lounas/")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    teksti = soup.get_text("\n", strip=True)

    # Etsitään päivät: MAANANTAI, TIISTAI, ...
    paivat_nimet = ["MAANANTAI", "TIISTAI", "KESKIVIIKKO", "TORSTAI", "PERJANTAI"]
    palat = re.split(r"(" + "|".join(paivat_nimet) + r")", teksti)

    paivat = []
    nykyinen = None
    for pala in palat:
        pala = pala.strip()
        if pala in paivat_nimet:
            nykyinen = pala
        elif nykyinen:
            # Otetaan rivit kunnes tulee toinen päivä tai osio loppuu
            rivit = [r.strip() for r in pala.split("\n") if r.strip()]
            # Pidetään vain ensimmäiset rivit ennen kuin tulee selkeästi muuta sisältöä
            ruoat = []
            for rivi in rivit:
                # Lopeta jos osumakohdassa on selkeästi muuta (esim. "MENU", "Texas Pete")
                if rivi.startswith("L =") or rivi == "Texas Pete Burger":
                    break
                # Ohitetaan lyhyet "L,G"-tyyppiset
                if len(rivi) < 4:
                    continue
                ruoat.append(rivi)
            if ruoat:
                paivat.append({"paiva": nykyinen, "ruoat": ruoat[:6]})
            nykyinen = None
    return paivat


# ---------- Linkosuo (Hertta, Orvokki, Fastelle) ----------

def scrape_linkosuo(url: str) -> list[dict]:
    """Linkosuolla on dl-listat: dt = päivä, dd = ruoat."""
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
            # Jaetaan ruoat rivinvaihdon perusteella
            teksti = dd.get_text("\n", strip=True)
            ruoat = [r.strip() for r in teksti.split("\n") if r.strip()]
            if paiva and ruoat:
                paivat.append({"paiva": paiva, "ruoat": ruoat})
    return paivat


# ---------- Compass Group / Reaktori ----------

def scrape_reaktori() -> list[dict]:
    """Reaktorilla on h3 = päivä, sitten h4-otsikot ja ul-listat ruoista."""
    url = "https://www.compass-group.fi/ravintolat-ja-ruokalistat/foodco/kaupungit/tampere/reaktori/"
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    paivat_re = re.compile(r"^(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)\s+\d")

    for h3 in soup.find_all("h3"):
        teksti = h3.get_text(strip=True)
        if not paivat_re.match(teksti):
            continue
        ruoat = []
        # Käydään läpi seuraavia elementtejä kunnes tulee uusi h3
        for sis in h3.find_all_next():
            if sis.name == "h3":
                break
            if sis.name == "h4":
                ryhma = sis.get_text(strip=True)
                # Otetaan vain pääateriat, ei "Jälkiruoka" tai "Pop Up Grill"
                if any(s in ryhma for s in ["Lounas", "Kasvislounas", "Vegaaninen", "Keitto"]):
                    ul = sis.find_next("ul")
                    if ul:
                        for li in ul.find_all("li"):
                            t = li.get_text(" ", strip=True)
                            if t and len(t) > 3:
                                ruoat.append(t)
        if ruoat:
            paivat.append({"paiva": teksti, "ruoat": ruoat[:8]})
    return paivat


# ---------- Antell ----------

def scrape_antell(url: str) -> list[dict]:
    """Antellilla on yleensä strong-tagit päivinä ja sitten tekstiä."""
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    paivat = []
    paivat_re = re.compile(
        r"(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)", re.IGNORECASE
    )

    # Yritetään useaa rakennetta — Antell ei ole täysin vakio
    for tag in soup.find_all(["strong", "b", "h2", "h3", "h4"]):
        teksti = tag.get_text(" ", strip=True)
        if not paivat_re.match(teksti):
            continue
        # Etsitään seuraavasta sisarusta tai vanhemmasta ruoat
        seur = tag.find_next_sibling()
        ruoat = []
        if seur:
            for rivi in seur.get_text("\n", strip=True).split("\n"):
                rivi = rivi.strip()
                if rivi and len(rivi) > 3 and not paivat_re.match(rivi):
                    ruoat.append(rivi)
        if ruoat:
            paivat.append({"paiva": teksti, "ruoat": ruoat[:6]})
    return paivat


# ---------- Yleisscraper sivuille joiden rakennetta emme tunne tarkasti ----------

def scrape_yleinen(url: str, etsi_paivat: bool = True) -> list[dict]:
    """
    Hakee sivun ja yrittää löytää lounaslistan tunnistamalla viikonpäivät tekstistä.
    Ei aina onnistu, mutta toimii usein.
    """
    html = hae_sivu(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Poistetaan navigaatio, footer, jne.
    for tag in soup(["nav", "footer", "header", "script", "style", "aside"]):
        tag.decompose()

    teksti = soup.get_text("\n", strip=True)
    rivit = [r.strip() for r in teksti.split("\n") if r.strip()]

    paivat_nimet = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai"]
    paivat = []
    nykyinen_paiva = None
    nykyiset_ruoat = []

    for rivi in rivit:
        rivi_lower = rivi.lower()
        # Tunnistetaanko päivä?
        on_paiva = any(p in rivi_lower for p in paivat_nimet) and len(rivi) < 60
        if on_paiva:
            if nykyinen_paiva and nykyiset_ruoat:
                paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})
            nykyinen_paiva = rivi
            nykyiset_ruoat = []
        elif nykyinen_paiva and len(rivi) > 5 and len(rivi) < 200:
            # Ohitetaan selkeästi muuhun kuin ruokaan liittyvät rivit
            if any(s in rivi_lower for s in ["yhteystiedot", "puh.", "varaa", "lue lisää"]):
                continue
            nykyiset_ruoat.append(rivi)
            if len(nykyiset_ruoat) >= 6:
                paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat})
                nykyinen_paiva = None
                nykyiset_ruoat = []

    if nykyinen_paiva and nykyiset_ruoat:
        paivat.append({"paiva": nykyinen_paiva, "ruoat": nykyiset_ruoat[:6]})

    return paivat


# ---------- RAVINTOLAT ----------
# Jokainen ravintola: nimi, alue, url, scrape-funktio

RAVINTOLAT = [
    {
        "nimi": "Sisu Buffet",
        "alue": "Hervanta",
        "url": "https://lounaat.info/lounas/sisu-buffet-hervanta/tampere",
        "scraper": lambda r: scrape_lounaat_info(r["url"]),
    },
    {
        "nimi": "Speakeasy",
        "alue": "Hervanta",
        "url": "https://www.speakeasy.fi/hervanta/lounas/",
        "scraper": lambda r: scrape_speakeasy(),
    },
    {
        "nimi": "Kontukeittiö",
        "alue": "Hervanta",
        "url": "https://kontukoti.fi/kontukeittio/kontukeittio-hervanta/",
        "scraper": lambda r: scrape_yleinen(r["url"]),
    },
    {
        "nimi": "Reaktori (FoodCo)",
        "alue": "Hervanta",
        "url": "https://www.compass-group.fi/ravintolat-ja-ruokalistat/foodco/kaupungit/tampere/reaktori/",
        "scraper": lambda r: scrape_reaktori(),
    },
    {
        "nimi": "Hertta",
        "alue": "Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/hertta/",
        "scraper": lambda r: scrape_linkosuo(r["url"]),
    },
    {
        "nimi": "Orvokki",
        "alue": "Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/lounasravintola-orvokki/",
        "scraper": lambda r: scrape_linkosuo(r["url"]),
    },
    {
        "nimi": "Hermia 5",
        "alue": "Hervanta",
        "url": "https://www.sodexo.fi/ravintolat/ravintola-hermia-5",
        "scraper": lambda r: scrape_sodexo(107),
    },
    {
        "nimi": "Hermia 6",
        "alue": "Hervanta",
        "url": "https://www.sodexo.fi/ravintolat/tampere/hermia-6",
        # ID täytyy tarkistaa Sodexon sivulta, oletus tämä:
        "scraper": lambda r: scrape_sodexo(108),
    },
    {
        "nimi": "Hermianfarmi",
        "alue": "Hervanta",
        "url": "https://antell.fi/lounas/tampere/hermianfarmi/",
        "scraper": lambda r: scrape_antell(r["url"]),
    },
    {
        "nimi": "Munkkimiehet",
        "alue": "Hervanta",
        "url": "https://munkkimiehet.fi/kuluttajille/",
        "scraper": lambda r: scrape_yleinen(r["url"]),
    },
    {
        "nimi": "Ruskonhelmi",
        "alue": "Hervanta",
        "url": "https://ruskonhelmi.fi/lounaslista/",
        "scraper": lambda r: scrape_yleinen(r["url"]),
    },
    {
        "nimi": "Ravintola Osku",
        "alue": "Hervanta",
        "url": "https://ravintolaosku.fi/",
        "scraper": lambda r: scrape_yleinen(r["url"]),
    },
    {
        "nimi": "Aitokoti",
        "alue": "Hervanta",
        "url": "https://www.aitokotilounas.fi/lounaslista/",
        "scraper": lambda r: scrape_yleinen(r["url"]),
    },
    {
        "nimi": "Fastelle",
        "alue": "Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/ravintola-fastelle/",
        "scraper": lambda r: scrape_linkosuo(r["url"]),
    },
    {
        "nimi": "Caffitella",
        "alue": "Hervanta",
        "url": "https://www.caffitella.fi/lounaslista/",
        "scraper": lambda r: scrape_yleinen(r["url"]),
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
                rivi["paivat"] = ravintola["scraper"](ravintola)
                print(f"  -> {len(rivi['paivat'])} päivää löytyi")
            except Exception as e:
                print(f"  ! Virhe scraping: {e}")
                rivi["virhe"] = str(e)
        else:
            print(f"  -> vain linkki ({ravintola.get('huom', '')})")
        tulokset.append(rivi)

    # Tallennetaan
    ulos = {
        "paivitetty": datetime.now(timezone.utc).isoformat(),
        "ravintolat": tulokset,
    }
    polku = Path(__file__).parent / "lounaat.json"
    polku.write_text(json.dumps(ulos, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nValmis. Tallennettu: {polku}")


if __name__ == "__main__":
    main()
