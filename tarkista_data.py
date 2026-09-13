"""
Tarkistaa että lounaat.json on rakenteeltaan kelvollinen.

Ajetaan Testit-workflow'ssa jokaisesta muutoksesta. Estää tilanteen, jossa
rikkinäinen tiedosto päätyy sivustolle ja kortit jäävät tyhjiksi.

Käyttö: python tarkista_data.py
Palauttaa 0 kun kaikki on kunnossa, 1 kun jotain on vialla.
"""

import json
import sys
from pathlib import Path

PAIVAT = {"Maanantai", "Tiistai", "Keskiviikko", "Torstai",
          "Perjantai", "Lauantai", "Sunnuntai"}

# Vähintään näin monella ravintolalla pitää olla lista, muuten jokin on
# mennyt pahasti rikki (normaalisti listallisia on yli kymmenen).
VAHIMMAIS_LISTALLISET = 6


def tarkista(polku: Path) -> list[str]:
    virheet: list[str] = []
    try:
        data = json.loads(polku.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{polku.name}: tiedostoa ei voitu lukea ({e})"]

    if not data.get("paivitetty"):
        virheet.append("puuttuu: paivitetty")
    ravintolat = data.get("ravintolat")
    if not isinstance(ravintolat, list) or not ravintolat:
        return virheet + ["puuttuu: ravintolat (tai lista on tyhjä)"]

    nimet = set()
    listallisia = 0
    for i, r in enumerate(ravintolat):
        tunniste = r.get("nimi") or f"ravintola #{i}"
        for kentta in ("nimi", "alue", "kategoria", "url"):
            if not r.get(kentta) and r.get(kentta) != 0:
                virheet.append(f"{tunniste}: puuttuu kenttä {kentta}")
        if r.get("nimi") in nimet:
            virheet.append(f"{tunniste}: sama nimi esiintyy kahdesti")
        nimet.add(r.get("nimi"))
        if not str(r.get("url", "")).startswith("http"):
            virheet.append(f"{tunniste}: url ei ole verkko-osoite")

        paivat = r.get("paivat", [])
        if not isinstance(paivat, list):
            virheet.append(f"{tunniste}: paivat ei ole lista")
            continue
        if paivat:
            listallisia += 1
        for p in paivat:
            nimi = p.get("paiva")
            if nimi not in PAIVAT:
                virheet.append(f"{tunniste}: tuntematon päivä {nimi!r}")
            ruoat = p.get("ruoat")
            if not isinstance(ruoat, list) or not ruoat:
                virheet.append(f"{tunniste} / {nimi}: ruoat puuttuu tai on tyhjä")
                continue
            if any(not isinstance(x, str) or not x.strip() for x in ruoat):
                virheet.append(f"{tunniste} / {nimi}: tyhjä tai kelvoton ruokarivi")

            osastot = p.get("osastot")
            if osastot is None:
                continue
            if not isinstance(osastot, list) or not osastot:
                virheet.append(f"{tunniste} / {nimi}: osastot on tyhjä")
                continue
            litteä = [x for o in osastot for x in o.get("ruoat", [])]
            if litteä != ruoat:
                virheet.append(
                    f"{tunniste} / {nimi}: osastojen ruoat eivät vastaa ruoat-listaa")
            for o in osastot:
                if "nimi" not in o:
                    virheet.append(f"{tunniste} / {nimi}: osastolta puuttuu nimi")
                if not o.get("ruoat"):
                    virheet.append(f"{tunniste} / {nimi}: tyhjä osasto")

    if listallisia < VAHIMMAIS_LISTALLISET:
        virheet.append(
            f"vain {listallisia} ravintolalla on lista "
            f"(odotettiin vähintään {VAHIMMAIS_LISTALLISET})")
    return virheet


def main() -> int:
    polku = Path(__file__).parent / "lounaat.json"
    virheet = tarkista(polku)
    if virheet:
        print("Virheitä lounaat.jsonissa:")
        for v in virheet:
            print(f"  - {v}")
        return 1
    print("lounaat.json on kunnossa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
