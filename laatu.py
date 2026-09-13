"""
Lounaslistojen laadunvalvonta.

Tarkistaa jokaisen ravintolan tuoreen scrape-tuloksen ja vertaa sitä
edelliseen onnistuneeseen ajoon. Jos tulos näyttää rikkinäiseltä, scrape.py
säilyttää edellisen listan (sivusto ei mene tyhjäksi) ja merkitsee rivin
vanhentuneeksi.

Tässä tiedostossa ei tehdä verkkopyyntöjä — kaikki on puhdasta tarkistusta,
joten sen voi ajaa testeissä.
"""

from datetime import datetime, timedelta, timezone

# Kuinka kauan ravintolan pitää olla rikki ennen kuin siitä avataan issue.
# Viikonloppu on normaali syy tyhjään listaan (esim. lounaat.info julkaisee
# uuden viikon vasta maanantaina), joten hälytys ei saa lähteä heti. Lauantaista
# maanantaiaamuun kertyy tasan 48 tuntia, joten raja on sitä väljempi.
ILMOITUSRAJA = timedelta(hours=60)

# Rivit joissa nämä esiintyvät ovat lähes varmasti sivun muuta sisältöä
# (yhteystietoja, hinnastoa) eivätkä ruokia.
ROSKASANAT = ("http", "www.", "puh.", "@", "€")

MAKS_RIVIN_PITUUS = 220
MAKS_RIVEJA_PAIVASSA = 20


def _paivien_ruoat(paivat: list[dict]) -> list[list[str]]:
    return [p.get("ruoat", []) for p in paivat]


def tarkista(uusi: dict, vanha: dict | None = None) -> list[str]:
    """
    Palauttaa listan ongelmia ravintolan tuoreessa datassa.

    Tyhjä lista = data kelpaa julkaistavaksi.
    """
    ongelmat: list[str] = []

    if uusi.get("virhe"):
        return [f"scraper kaatui: {uusi['virhe']}"]

    paivat = uusi.get("paivat") or []
    vanhat_paivat = (vanha or {}).get("paivat") or []

    if not paivat:
        if vanhat_paivat:
            ongelmat.append(
                f"ei löytynyt yhtään päivää (edellisessä ajossa {len(vanhat_paivat)})"
            )
        else:
            ongelmat.append("ei löytynyt yhtään päivää")
        return ongelmat

    # Päivien määrä romahti — lähde on todennäköisesti muuttunut
    if len(vanhat_paivat) >= 4 and len(paivat) * 2 <= len(vanhat_paivat):
        ongelmat.append(
            f"päiviä vain {len(paivat)} (edellisessä ajossa {len(vanhat_paivat)})"
        )

    ruoat_per_paiva = _paivien_ruoat(paivat)

    for rivit in ruoat_per_paiva:
        if len(rivit) > MAKS_RIVEJA_PAIVASSA:
            ongelmat.append(
                f"yhdellä päivällä {len(rivit)} riviä (yli {MAKS_RIVEJA_PAIVASSA})"
            )
            break

    for rivit in ruoat_per_paiva:
        pitka = next((r for r in rivit if len(r) > MAKS_RIVIN_PITUUS), None)
        if pitka:
            ongelmat.append(f"liian pitkä rivi ({len(pitka)} merkkiä): {pitka[:60]}…")
            break

    for rivit in ruoat_per_paiva:
        roska = next(
            (r for r in rivit if any(s in r.lower() for s in ROSKASANAT)), None
        )
        if roska:
            ongelmat.append(f"rivi ei näytä ruoalta: {roska[:80]}")
            break

    # Sama sisältö joka päivälle = ravintolan yleistekstiä, ei ruokalistaa
    if len(paivat) >= 3 and len({tuple(r) for r in ruoat_per_paiva}) == 1:
        ongelmat.append("kaikilla päivillä sama sisältö")

    return ongelmat


def yhdista(uusi: dict, vanha: dict | None, nyt: datetime) -> dict:
    """
    Päättää mitä ravintolasta julkaistaan.

    Kelvollinen tulos julkaistaan sellaisenaan. Rikkinäisen tilalla pidetään
    edellinen onnistunut lista ja rivi merkitään vanhentuneeksi, jotta sivusto
    ei mene tyhjäksi yhden lähteen muuttuessa.

    Kentät:
      paivitetty    — milloin lista viimeksi haettiin onnistuneesti
      vanhentunut   — true jos näytetään edellisen ajon lista
      ongelmat      — tämän ajon havainnot
      rikki_alkaen  — milloin ongelmat alkoivat (tyhjä kun kunnossa)
    """
    rivi = dict(uusi)
    ongelmat = tarkista(uusi, vanha)
    aika = nyt.isoformat()

    if not ongelmat:
        rivi["paivitetty"] = aika
        rivi.pop("vanhentunut", None)
        rivi.pop("ongelmat", None)
        rivi.pop("rikki_alkaen", None)
        return rivi

    rivi["ongelmat"] = ongelmat
    rivi["rikki_alkaen"] = (vanha or {}).get("rikki_alkaen") or aika

    vanhat_paivat = (vanha or {}).get("paivat") or []
    if vanhat_paivat:
        rivi["paivat"] = vanhat_paivat
        rivi["vanhentunut"] = True
        rivi["paivitetty"] = (vanha or {}).get("paivitetty", "")
    else:
        rivi["paivitetty"] = (vanha or {}).get("paivitetty", "")
        rivi.pop("vanhentunut", None)
    return rivi


def _rikki_kuinka_kauan(rivi: dict, nyt: datetime) -> timedelta | None:
    alkaen = rivi.get("rikki_alkaen")
    if not alkaen:
        return None
    try:
        alku = datetime.fromisoformat(alkaen)
    except ValueError:
        return None
    if alku.tzinfo is None:
        alku = alku.replace(tzinfo=timezone.utc)
    return nyt - alku


def raportti(ravintolat: list[dict], nyt: datetime) -> dict:
    """
    Kokoaa ajon laaturaportin.

    "ilmoitettavat" = ravintolat jotka ovat olleet rikki yli ILMOITUSRAJAn.
    Niistä avataan GitHub-issue. "korjaantuneet" = ravintolat joilla ei enää
    ole ongelmia; niiden issue suljetaan.
    """
    rikki, ilmoitettavat, kunnossa = [], [], []
    for r in ravintolat:
        nimi = r.get("nimi", "")
        if r.get("ongelmat"):
            kesto = _rikki_kuinka_kauan(r, nyt)
            tunnit = round(kesto.total_seconds() / 3600) if kesto else 0
            tieto = {
                "nimi": nimi,
                "url": r.get("url", ""),
                "ongelmat": r["ongelmat"],
                "tunteja_rikki": tunnit,
                "vanhentunut": bool(r.get("vanhentunut")),
            }
            rikki.append(tieto)
            if kesto is not None and kesto >= ILMOITUSRAJA:
                ilmoitettavat.append(tieto)
        else:
            kunnossa.append(nimi)

    return {
        "aika": nyt.isoformat(),
        "rikki": rikki,
        "ilmoitettavat": ilmoitettavat,
        "kunnossa": kunnossa,
    }


def tulosta_raportti(rap: dict) -> None:
    """Tulostaa raportin Actions-lokiin luettavassa muodossa."""
    print("\n=== Laaturaportti ===")
    print(f"Kunnossa: {len(rap['kunnossa'])} ravintolaa")
    if not rap["rikki"]:
        print("Ei ongelmia.")
        return
    for r in rap["rikki"]:
        merkki = "ILMOITETAAN" if r in rap["ilmoitettavat"] else "seurannassa"
        vanha = " (näytetään edellinen lista)" if r["vanhentunut"] else ""
        print(f"- {r['nimi']}: rikki {r['tunteja_rikki']} h [{merkki}]{vanha}")
        for o in r["ongelmat"]:
            print(f"    * {o}")
