"""
Avaa ja sulkee GitHub-issueita laaturaportin perusteella.

Ajetaan Päivitä lounaat -workflow'ssa. Jos ravintola on ollut rikki yli
laatu.ILMOITUSRAJAn, siitä avataan issue. Kun ravintola toimii taas, issue
suljetaan. Yksi issue per ravintola — samasta viasta ei tule uusia ilmoituksia
joka aamu.

Ei kaadu koskaan: jos gh-komento epäonnistuu, virhe tulostetaan ja ajo jatkuu.
"""

import json
import subprocess
import sys
from pathlib import Path

LABEL = "scraper-rikki"
OTSIKKO = "Scraper rikki: {nimi}"
JUURI = Path(__file__).resolve().parents[2]


def gh(*args: str) -> str | None:
    """Ajaa gh-komennon. Palauttaa tulosteen tai None jos komento epäonnistui."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"! gh ei käytettävissä: {e}")
        return None
    if r.returncode != 0:
        print(f"! gh {' '.join(args[:2])} epäonnistui: {r.stderr.strip()[:300]}")
        return None
    return r.stdout


def avoimet_issuet() -> dict[str, int]:
    """Avoimet scraper-rikki-issuet: ravintolan nimi → issue-numero."""
    ulos = gh("issue", "list", "--label", LABEL, "--state", "open",
              "--limit", "100", "--json", "number,title")
    if not ulos:
        return {}
    try:
        rivit = json.loads(ulos)
    except json.JSONDecodeError:
        return {}
    tulos = {}
    for i in rivit:
        otsikko = i.get("title", "")
        if otsikko.startswith("Scraper rikki: "):
            tulos[otsikko[len("Scraper rikki: "):].strip()] = i["number"]
    return tulos


def runko(tieto: dict) -> str:
    ongelmat = "\n".join(f"- {o}" for o in tieto["ongelmat"])
    tila = ("Sivustolla näytetään toistaiseksi edellisen onnistuneen ajon lista."
            if tieto["vanhentunut"] else
            "Ravintolalta ei ole aiempaa listaa näytettäväksi.")
    return f"""Automaattinen laatutarkistus havaitsi, ettei tämän ravintolan lounaslistaa saada haettua.

**Ravintola:** {tieto['nimi']}
**Lähde:** {tieto['url']}
**Rikki:** noin {tieto['tunteja_rikki']} tuntia

**Havainnot**
{ongelmat}

{tila}

Korjaaminen: avaa Claude Code ja pyydä korjaamaan tämän ravintolan scraper.
Ravintolan sivun rakenne on todennäköisesti muuttunut.

---
_Tämän issuen avasi automaattisesti Päivitä lounaat -workflow._
"""


def main() -> int:
    raportti_polku = JUURI / "laaturaportti.json"
    if not raportti_polku.exists():
        print("Laaturaporttia ei löytynyt — ohitetaan.")
        return 0
    rap = json.loads(raportti_polku.read_text(encoding="utf-8"))

    gh("label", "create", LABEL, "--color", "d73a4a",
       "--description", "Lounaslistan haku ei toimi")

    avoimet = avoimet_issuet()

    for tieto in rap.get("ilmoitettavat", []):
        nimi = tieto["nimi"]
        if nimi in avoimet:
            print(f"Issue jo auki: {nimi} (#{avoimet[nimi]})")
            continue
        ulos = gh("issue", "create", "--title", OTSIKKO.format(nimi=nimi),
                  "--label", LABEL, "--body", runko(tieto))
        if ulos:
            print(f"Avattiin issue: {nimi} -> {ulos.strip()}")

    for nimi in rap.get("kunnossa", []):
        numero = avoimet.get(nimi)
        if numero is None:
            continue
        gh("issue", "close", str(numero), "--comment",
           f"Lounaslistan haku toimii taas ({nimi}). Suljetaan automaattisesti.")
        print(f"Suljettiin issue #{numero}: {nimi}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
