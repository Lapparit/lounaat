"""
Offline-testit scrape.py:n parsereille ja siivousfunktioille.

Ajo: python -m unittest -v test_scrape
Testit eivät tee verkkoyhteyksiä — HTML/PDF-tekstit on upotettu tähän.
"""
import unittest
from unittest import mock

import scrape


class SiivoaRuoka(unittest.TestCase):
    def test_katkennut_sulku_poistetaan(self):
        self.assertEqual(scrape.siivoa_ruoka("SPEAKEASYN LOHIBUFFET ("),
                         "SPEAKEASYN LOHIBUFFET")

    def test_allergeeniselite_pudotetaan(self):
        for rivi in ("G=gluteeniton", "L = laktoositon", "VEG = vegaaninen"):
            self.assertIsNone(scrape.siivoa_ruoka(rivi), rivi)

    def test_saatavuusinfo_pudotetaan(self):
        self.assertIsNone(scrape.siivoa_ruoka("SAA M, G, VEG keittiöstä"))
        self.assertIsNone(scrape.siivoa_ruoka("Saatavana myös gluteenittomana"))

    def test_saaristolaisleipa_ei_pudota(self):
        self.assertEqual(scrape.siivoa_ruoka("Saaristolaisleipää ja voita"),
                         "Saaristolaisleipää ja voita")

    def test_hinta_ja_allergeenit(self):
        self.assertEqual(scrape.siivoa_ruoka("Lohikeitto (L, G) 12,20€"), "Lohikeitto")
        self.assertEqual(scrape.siivoa_ruoka("BBQ-broileria (suomalaista broileria)"),
                         "BBQ-broileria (suomalaista broileria)")

    def test_loppukoodit(self):
        self.assertEqual(scrape.siivoa_ruoka("Sinappinen hunaja broileri L,"), "Sinappinen hunaja broileri")
        self.assertEqual(scrape.siivoa_ruoka("Hernekeittoa M, G"), "Hernekeittoa")
        self.assertEqual(scrape.siivoa_ruoka("Riisiä A, G, L, M, Veg"), "Riisiä")
        # Oikea ruokasana koodien perässä ei saa kadota
        self.assertEqual(scrape.siivoa_ruoka("lämpimiä kasviksia M, G, riisiä"),
                         "lämpimiä kasviksia M, G, riisiä")
        self.assertEqual(scrape.siivoa_ruoka("Salaatti, kurkku"), "Salaatti, kurkku")

    def test_useampi_kierros(self):
        self.assertEqual(scrape.siivoa_ruoka("Sinappinen hunaja broileri L ("), "Sinappinen hunaja broileri")
        self.assertEqual(scrape.siivoa_ruoka("Lohta M, G Veg"), "Lohta")

    def test_idempotentti(self):
        import json
        rivit = [x for r in json.load(open("lounaat.json", encoding="utf-8"))["ravintolat"]
                 for p in r["paivat"] for x in p["ruoat"]]
        self.assertGreater(len(rivit), 100)
        for rivi in rivit:
            kerran = scrape.siivoa_ruoka(rivi)
            if kerran is not None:
                self.assertEqual(scrape.siivoa_ruoka(kerran), kerran, rivi)

    def test_puuro_pudotetaan(self):
        self.assertIsNone(scrape.siivoa_ruoka("Kaurapuuroa ja hilloa"))


class NormalisoiPaiva(unittest.TestCase):
    def test_muodot(self):
        self.assertEqual(scrape.normalisoi_paiva("Maanantaina 27.4."), "Maanantai")
        self.assertEqual(scrape.normalisoi_paiva("TIISTAI"), "Tiistai")
        self.assertEqual(scrape.normalisoi_paiva("ke 29.4."), "Keskiviikko")
        self.assertEqual(scrape.normalisoi_paiva("2026-09-15"), "Tiistai")
        self.assertEqual(scrape.normalisoi_paiva("Friday"), "Perjantai")


class AitoPdf(unittest.TestCase):
    TEKSTI = """
AITO KOTILOUNAS Pitkäahteentie 1
MAANANTAI 14.09. TORSTAI 17.09.
• Soija-kasvislasagne
• Jauhelihapihvejä ja muusia
• Kanafilettä, aurajuustokastiketta ja
varhaisperunoita
Keittiöstä: Kana-pekonisalaatti
• Hernekeittoa
• Lasagnea
Keittiöstä: Kanasalaatti
TIISTAI 15.09. PERJANTAI 18.09.
• Kanakeittoa
Keittiöstä: Fetasalaatti
• Puna-ahvenleikettä ja muusia
Keittiöstä: Halloumisalaatti
KESKIVIIKKO 16.09.
• Borssikeittoa
Keittiöstä: Halloumisalaatti
Lounas tarjoillaan klo 10.30-14
"""

    def test_oikea_sarake_omalle_paivalle(self):
        paivat = {p["paiva"]: p["ruoat"] for p in scrape._parsi_aito_pdf_teksti(self.TEKSTI)}
        self.assertEqual(sorted(paivat), ["Keskiviikko", "Maanantai", "Perjantai", "Tiistai", "Torstai"])
        self.assertEqual(paivat["Maanantai"], [
            "Soija-kasvislasagne",
            "Jauhelihapihvejä ja muusia",
            "Kanafilettä, aurajuustokastiketta ja varhaisperunoita",
            "Keittiöstä: Kana-pekonisalaatti",
        ])
        self.assertEqual(paivat["Torstai"], ["Hernekeittoa", "Lasagnea", "Keittiöstä: Kanasalaatti"])
        self.assertEqual(paivat["Perjantai"], ["Puna-ahvenleikettä ja muusia", "Keittiöstä: Halloumisalaatti"])
        self.assertEqual(paivat["Keskiviikko"], ["Borssikeittoa", "Keittiöstä: Halloumisalaatti"])


class LounaatInfo(unittest.TestCase):
    def _aja(self, html):
        with mock.patch.object(scrape, "hae_sivu", return_value=html):
            return scrape._scrape_lounaat_info_yleinen("https://lounaat.info/x")

    def test_yleisteksti_joka_paivalle_hylataan(self):
        html = "".join(
            f"<h3>{p} 14.9.</h3><ul><li>Buffetin hinta 12€, opiskelijat 9€</li>"
            f"<li>Jätski ja kahvi aina jälkkäriksi</li></ul>"
            for p in ("Maanantai", "Tiistai", "Keskiviikko"))
        self.assertEqual(self._aja(html), [])

    def test_oikea_lista(self):
        html = ("<h3>Maanantai 14.9.</h3><ul><li>Yrttibroileria</li><li>Lounas kello 10.30-14</li></ul>"
                "<h3>Tiistai 15.9.</h3><ul><li>Lihapullia</li></ul>"
                "<h3>Muu otsikko</h3><ul><li>roska</li></ul>")
        self.assertEqual(self._aja(html), [
            {"paiva": "Maanantai 14.9.", "ruoat": ["Yrttibroileria"]},
            {"paiva": "Tiistai 15.9.", "ruoat": ["Lihapullia"]},
        ])


class Caffitella(unittest.TestCase):
    HTML = """
<main>
<div><p><strong>Maanantai</strong></p></div>
<p>Jauhelihapyöryköitä</p><p>Salaattibuffet</p>
<div><p><strong>Lauantai</strong></p></div>
<p>Paneroitua kampelaa</p><p>Salaattibuffet</p>
<p>Äänekoski, Seppälä, Cm keljo, Prisma keljo, Muurame, Vaajakoski, Laukaa</p>
<h3>MAANANTAI</h3><p>Avoinna 10-14</p>
<h3>TIISTAI</h3><p>Avoinna 10-14</p>
</main>"""

    def test_alaosan_aukioloajat_eivat_tule_mukaan(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = scrape.scrape_caffitella()
        self.assertEqual([p["paiva"] for p in paivat], ["Maanantai", "Lauantai"])
        self.assertEqual(paivat[0]["ruoat"], ["Jauhelihapyöryköitä", "Salaattibuffet"])
        self.assertEqual(paivat[1]["ruoat"], ["Paneroitua kampelaa", "Salaattibuffet"])


class Speakeasy(unittest.TestCase):
    HTML = """<body><h2>MAANANTAI</h2><p>Kanaa cheddar-jalapenokastikkeessa, riisi</p>
<p>Puolukkarahka</p><p>G=gluteeniton</p><p>L = laktoositon</p>
<h2>TIISTAI</h2><p>Spagetti bolognese</p><p>L = laktoositon</p></body>"""

    def test_selitteet_katkaisevat(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = scrape.scrape_speakeasy()
        self.assertEqual(paivat, [
            {"paiva": "MAANANTAI", "ruoat": ["Kanaa cheddar-jalapenokastikkeessa, riisi", "Puolukkarahka"]},
            {"paiva": "TIISTAI", "ruoat": ["Spagetti bolognese"]},
        ])


class Munkki(unittest.TestCase):
    def test_ocr_teksti(self):
        teksti = "RUSKO LOUNAS viikko 38\nMAANANTAI\n. Jauhelihakeitto\nUunimakkara\nTIISTAI\nSiskonmakkarakeitto\n"
        self.assertEqual(scrape._parsi_munkki_teksti(teksti), [
            {"paiva": "Maanantai", "ruoat": ["Jauhelihakeitto", "Uunimakkara"]},
            {"paiva": "Tiistai", "ruoat": ["Siskonmakkarakeitto"]},
        ])


class Ravintolalista(unittest.TestCase):
    def test_idaho_poistettu(self):
        self.assertNotIn("Ravintola Idaho", [r["nimi"] for r in scrape.RAVINTOLAT])

    def test_kentat_ja_uniikit_nimet(self):
        nimet = [r["nimi"] for r in scrape.RAVINTOLAT]
        self.assertEqual(len(nimet), len(set(nimet)))
        for r in scrape.RAVINTOLAT:
            for k in ("nimi", "alue", "kategoria", "url", "scraper"):
                self.assertIn(k, r, r["nimi"])
            self.assertIn(r["kategoria"], (1, 2, 3))
            if r["scraper"] is None:
                self.assertTrue(r.get("huom"), f"{r['nimi']}: linkkiravintola tarvitsee huom-tekstin")


if __name__ == "__main__":
    unittest.main()
