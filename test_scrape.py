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


class AitoHtml(unittest.TestCase):
    HTML = """
<div><ul class="elementor-icon-list-items"><li class="elementor-icon-list-item">Pitkäahteentie 1</li></ul>
<p><strong>Lounas tarjoillaan arkisin klo 10:30 – 14:30</strong></p>
<p>Annokset saatavilla myös mukaan ja toimitettuna, puh. 03 410 230 38</p>
<p><strong><span>Maanantai 14.09.</span></strong></p>
<ul><li>Lohileikettä sitruuna-tillikastikkeella ja muusia (L)</li>
<li>Italialainen parmesanpasta (L)</li>
<li>Suklaarahkaa (G,L) Keittiöstä: Fetasalaatti (G,L)</li></ul>
<p><strong>Torstai 17.09.</strong></p>
<ul><li>Hernekeittoa (G,L)</li></ul>
<p>Keittiöstä: Mozzarellasalaatti (G,L)</p>
<p><strong>Perjantai 18.09.</strong></p>
<ul><li>Kanawok (L)</li></ul>
<div><span>KATSO SIJAINTIMME</span></div>
<ul class="elementor-icon-list-items"><li class="elementor-icon-list-item"><span>Etusivulle</span></li>
<li class="elementor-icon-list-item"><span>Yhteyslomake</span></li></ul></div>"""

    def test_html_lista(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = scrape.scrape_aito_kotilounas()
        self.assertEqual([p["paiva"] for p in paivat], ["Maanantai 14.09.", "Torstai 17.09.", "Perjantai 18.09."])
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in paivat[0]["osastot"]], [
            ("Lounas", ["Lohileikettä sitruuna-tillikastikkeella ja muusia (L)",
                        "Italialainen parmesanpasta (L)", "Suklaarahkaa (G,L)"]),
            ("Keittiöstä", ["Fetasalaatti (G,L)"]),
        ])
        self.assertEqual(paivat[2], {"paiva": "Perjantai 18.09.", "ruoat": ["Kanawok (L)"],
                                     "osastot": [{"nimi": "", "ruoat": ["Kanawok (L)"]}]})

    def test_ilman_listaa_palaa_pdf_polkuun(self):
        # Ei päiväotsikoita, ei PDF:ää → tyhjä (ei poikkeusta)
        with mock.patch.object(scrape, "hae_sivu", return_value="<p>Tervetuloa</p>"):
            self.assertEqual(scrape.scrape_aito_kotilounas(), [])


class Reaktori(unittest.TestCase):
    MENU = {
        "weekMenu": {"weekNumber": 38, "menus": [
            {"dayOfWeek": 1, "date": "2026-09-14T00:00:00", "menuPackages": [
                {"name": "So Green. (Kasvislounas)", "meals": [
                    {"name": "Italialaisia kasvispyöryköitä 8kpl/annos 0,50€/extra kpl"},
                    {"name": "Paahdettua perunaa"}]},
                {"name": "So Green Soup. (Linjastot 3-4)", "meals": [{"name": "Pinaattikeittoa"}]},
                {"name": "So Good.", "meals": [{"name": "Makkarakastiketta"}, {"name": "Tummaa riisiä"}]},
                {"name": "So Tasty.", "meals": [{"name": "Kalapyörykät 6kpl/annos, extra 0,50€/kpl"}]},
                {"name": "So Sweet. (Jälkiruoka)", "meals": [{"name": "Banoffee-mousse"}]},
                {"name": "So Bread. (Break Cafe)", "meals": [{"name": "Sämpylä"}]},
                {"name": "Pop Up Grill salaattilounas 10:30 - 13:30 (Break Cafe)", "meals": [{"name": "Mozzarellasalaattia"}]},
            ]},
            {"dayOfWeek": 2, "date": "2026-09-15T00:00:00", "menuPackages": []},
        ]}}

    def test_upotettu_json(self):
        import json
        html = ("<html><script>window.__INITIAL_MENU__ = " + json.dumps(self.MENU)
                + ";</script><h3>Maanantai 14.9.2026</h3></html>")
        with mock.patch.object(scrape, "hae_sivu", return_value=html):
            paivat = scrape.scrape_reaktori()
        self.assertEqual(paivat[0]["paiva"], "2026-09-14T00:00:00")
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in paivat[0]["osastot"]], [
            ("Kasvislounas", ["Italialaisia kasvispyöryköitä", "Paahdettua perunaa"]),
            ("Keitto", ["Pinaattikeittoa"]),
            ("So Good", ["Makkarakastiketta", "Tummaa riisiä"]),
            ("So Tasty", ["Kalapyörykät"]),
            ("Pop Up Grill salaatti", ["Mozzarellasalaattia"]),
        ])
        self.assertEqual(len(paivat), 1)
        self.assertEqual(scrape.normalisoi_paivat(paivat)[0]["paiva"], "Maanantai")

    def test_html_varapolku(self):
        html = ("<h3>Maanantai 14.9.2026</h3><h4>So Good.</h4><p>hinta</p>"
                "<ul><li>Makkarakastiketta (A, G)</li></ul>"
                "<h4>So Sweet. (Jälkiruoka)</h4><ul><li>Mousse</li></ul>")
        with mock.patch.object(scrape, "hae_sivu", return_value=html):
            paivat = scrape.scrape_reaktori()
        self.assertEqual(paivat, [{"paiva": "Maanantai 14.9.2026", "ruoat": ["Makkarakastiketta (A, G)"]}])


class Kontukeittio(unittest.TestCase):
    DATA = {"success": True, "data": {"week": {"days": [
        {"dayNumber": 0, "dayName": {"fi": "Sunnuntai"}, "dateString": "2026-09-20", "isHidden": True, "isClosed": True, "lunches": []},
        {"dayNumber": 1, "dayName": {"fi": "Maanantai"}, "dateString": "2026-09-14", "isHidden": False, "isClosed": False, "lunches": [
            {"title": {"fi": "Metsäsienikeittoa"}, "description": {"fi": ""}},
            {"title": {"fi": "Lindströminpihvejä kermasipulikastikkeessa"}, "description": {"fi": ""}},
            {"title": {"fi": "Halloumi – punajuuripihvejä"}, "description": {"fi": "kylmäkastiketta"}},
        ]},
        {"dayNumber": 6, "dayName": {"fi": "Lauantai"}, "dateString": "2026-09-19", "isHidden": False, "isClosed": True, "lunches": []},
    ]}}}

    def test_parsi(self):
        paivat = scrape._parsi_lounastaja(self.DATA)
        self.assertEqual(paivat[0]["paiva"], "2026-09-14")
        self.assertEqual(paivat[0]["ruoat"], [
            "Metsäsienikeittoa",
            "Lindströminpihvejä kermasipulikastikkeessa",
            "Halloumi – punajuuripihvejä – kylmäkastiketta",
        ])
        self.assertEqual([o["nimi"] for o in paivat[0]["osastot"]], ["Keitto", "Lounas"])
        self.assertEqual(scrape.normalisoi_paivat(paivat)[0]["paiva"], "Maanantai")

    def test_api_avain_luetaan_sivulta(self):
        html = '<div data-lounastaja-widget-id="x" data-api-key="11111111-2222-3333-4444-555555555555"></div>'
        kutsut = []
        class Vastaus:
            def raise_for_status(self): pass
            def json(self): return Kontukeittio.DATA
        def feikki_get(url, **kw):
            kutsut.append(url); return Vastaus()
        with mock.patch.object(scrape, "hae_sivu", return_value=html), \
             mock.patch.object(scrape.requests, "get", side_effect=feikki_get):
            paivat = scrape.scrape_kontukeittio()
        self.assertIn("11111111-2222-3333-4444-555555555555", kutsut[0])
        self.assertEqual(len(paivat), 1)

    def test_tyhja_vastaus_palaa_lounaat_infoon(self):
        with mock.patch.object(scrape, "hae_sivu", return_value="<h3>Maanantai 14.9.</h3><ul><li>Kaalikeittoa</li></ul>"), \
             mock.patch.object(scrape, "_lounastaja_viikko", return_value=[]):
            paivat = scrape.scrape_kontukeittio()
        self.assertEqual(paivat, [{"paiva": "Maanantai 14.9.", "ruoat": ["Kaalikeittoa"]}])


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
        paivat = scrape._parsi_munkki_teksti(teksti)
        self.assertEqual(paivat[0]["ruoat"], ["Jauhelihakeitto", "Uunimakkara"])
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in paivat[0]["osastot"]],
                         [("Keitto", ["Jauhelihakeitto"]), ("Lounas", ["Uunimakkara"])])
        self.assertEqual(paivat[1], {"paiva": "Tiistai", "ruoat": ["Siskonmakkarakeitto"]})


class Osastot(unittest.TestCase):
    def test_etuliitteet(self):
        rivit = ["Paneroitua hietakampelaa M & dippi", "Kukkakaali-kikherne muhennos",
                 "– riisiä", "Keitto: Kaalikeitto", "Chef: Puna-ahventa",
                 "Vegaaniruoka keittiöstä: Kasvispata",
                 "Proteiinilisäkkeet punnittavaan salaattiin:", "– Salaattijuustoa", "– Kikherneitä"]
        osastot = scrape.osastot_etuliitteista(rivit)
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in osastot], [
            ("Lounas", ["Paneroitua hietakampelaa M & dippi", "Kukkakaali-kikherne muhennos", "– riisiä"]),
            ("Keitto", ["Kaalikeitto"]),
            ("Chef", ["Puna-ahventa"]),
            ("Vegaaninen keittiöstä", ["Kasvispata"]),
            ("Proteiinilisäkkeet punnittavaan salaattiin", ["Salaattijuustoa", "Kikherneitä"]),
        ])

    def test_ilman_etuliitteita_ei_osastoja(self):
        self.assertEqual(scrape.osastot_etuliitteista(["Makkarapannu", "Lohilasagnette"]),
                         [{"nimi": "", "ruoat": ["Makkarapannu", "Lohilasagnette"]}])
        p = scrape.siivoa_paiva(scrape.paiva_osastoista("Maanantai", scrape.osastot_etuliitteista(["Makkarapannu"])))
        self.assertEqual(p, {"paiva": "Maanantai", "ruoat": ["Makkarapannu"]})

    def test_siivoa_paiva_osastoilla(self):
        p = scrape.paiva_osastoista("Maanantai", [
            scrape.osasto("Buffet", ["Lihapullia M, G / Kasvispihvejä VEG", "Puuroa"]),
            scrape.osasto("Grilli", ["Burgeri 13,80 €"]),
            scrape.osasto("Tyhjä", []),
        ])
        self.assertEqual(scrape.siivoa_paiva(p), {
            "paiva": "Maanantai",
            "ruoat": ["Lihapullia", "Kasvispihvejä", "Burgeri"],
            "osastot": [{"nimi": "Buffet", "ruoat": ["Lihapullia", "Kasvispihvejä"]},
                        {"nimi": "Grilli", "ruoat": ["Burgeri"]}],
        })

    def test_kauttaviivajako(self):
        self.assertEqual(scrape.jaa_vaihtoehdot("Naudanlihapataa M,G / Kala-äyriäiswok M / Kasvispyöryköitä"),
                         ["Naudanlihapataa M,G", "Kala-äyriäiswok M", "Kasvispyöryköitä"])
        self.assertEqual(scrape.jaa_vaihtoehdot("Kaurapuuro/oatmeal porridge"), ["Kaurapuuro/oatmeal porridge"])
        self.assertEqual(scrape.siivoa_ruoka("Kanaa, yrtti-lohkoperunat & lämmin kasvis"),
                         "Kanaa, yrtti-lohkoperunat & lämmin kasvis")
        self.assertEqual(scrape.siivoa_ruoka("Lihapullat L KASVIS"), "Lihapullat")
        self.assertEqual(scrape.siivoa_ruoka("Sitruuna-timjami beurre blanc #"), "Sitruuna-timjami beurre blanc")

    def test_sodexo_osaston_nimi(self):
        self.assertEqual(scrape._sodexo_osaston_nimi("Kitchen Buffet 13,80 €"), "Kitchen Buffet")
        self.assertEqual(scrape._sodexo_osaston_nimi("FROM THE GRILL"), "Grilli")
        self.assertEqual(scrape._sodexo_osaston_nimi("Special Grilli 13,80 /11,20 €"), "Special Grilli")
        self.assertEqual(scrape._sodexo_osaston_nimi(" Pop Up Lunch 13,80 €"), "Pop Up Lunch")
        self.assertEqual(scrape._sodexo_osaston_nimi(""), "Lounas")

    def test_reaktori_osaston_nimi(self):
        f = scrape._reaktori_osaston_nimi
        self.assertEqual(f("So Green. (Kasvislounas)"), "Kasvislounas")
        self.assertEqual(f("So Green Soup. (Linjastot 3-4)"), "Keitto")
        self.assertEqual(f("So Good."), "So Good")
        self.assertEqual(f("Pop Up Grill lounasannos 10:30 - 13:30 (Break Cafe)"), "Pop Up Grill")
        self.assertEqual(f("So Fresh. (Salaattilounaan proteiini) (Linjastot 3-4)"), "Salaattilounaan proteiini")


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
