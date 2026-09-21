"""
Offline-testit scrape.py:n parsereille ja siivousfunktioille.

Ajo: python -m unittest -v test_scrape
Testit eivät tee verkkoyhteyksiä — HTML/PDF-tekstit on upotettu tähän.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import laatu
import scrape
import tarkista_data

sys.path.insert(0, str(Path(__file__).parent / ".github" / "scripts"))
import issuet  # noqa: E402


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
            ("Jälkiruoka", ["Banoffee-mousse"]),
            ("Leipälounas (Break Cafe)", ["Sämpylä"]),
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
        self.assertEqual(paivat, [{"paiva": "Maanantai 14.9.2026",
                                   "ruoat": ["Makkarakastiketta (A, G)", "Mousse"]}])


class Kontukeittio(unittest.TestCase):
    DATA = {"success": True, "data": {"week": {"days": [
        {"dayNumber": 0, "dayName": {"fi": "Sunnuntai"}, "dateString": "2026-09-20", "isHidden": True, "isClosed": True, "lunches": []},
        {"dayNumber": 1, "dayName": {"fi": "Maanantai"}, "dateString": "2026-09-14", "isHidden": False, "isClosed": False, "lunches": [
            {"title": {"fi": "Metsäsienikeittoa"}, "description": {"fi": ""}},
            {"title": {"fi": "Lindströminpihvejä kermasipulikastikkeessa"}, "description": {"fi": ""}},
            {"title": {"fi": "Halloumi – punajuuripihvejä"}, "description": {"fi": "kylmäkastiketta"},
             "allergens": [{"abbreviation": {"fi": "K"}}]},
        ]},
        {"dayNumber": 6, "dayName": {"fi": "Lauantai"}, "dateString": "2026-09-19", "isHidden": False, "isClosed": True, "lunches": []},
    ]}}}

    def test_parsi(self):
        paivat = scrape._parsi_lounastaja(self.DATA)
        self.assertEqual(paivat[0]["paiva"], "2026-09-14")
        self.assertEqual(paivat[0]["ruoat"], [
            "Metsäsienikeittoa",
            "Lindströminpihvejä kermasipulikastikkeessa",
            "Halloumi – punajuuripihvejä – kylmäkastiketta (kasvisvaihtoehto)",
        ])
        self.assertEqual([o["nimi"] for o in paivat[0]["osastot"]], ["Keitto", "Lounasbuffet"])
        self.assertEqual(scrape.siivoa_ruoka("Halloumi – punajuuripihvejä (kasvisvaihtoehto)"),
                         "Halloumi – punajuuripihvejä (kasvisvaihtoehto)")
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


class HerttaJaLinkosuo(unittest.TestCase):
    HTML = """<dl><dt>Maanantai 21.09.</dt><dd>Kaurapuuro M &amp; hillo klo 7.45-9.30 á 2,30 €<br>
Naudanliha kebabia ranskalaisilla perunoilla M, G<br>
Punajuuripihvejä M, G, VEG &amp; raikas piparjuuridippi M, G (SAA VEG dippi keittiöstä)<br>
Keitto: Kermainen basilika-tomaattikeitto L, G<br>
Chef´s menu: Paistettua puna-ahventa &amp; beurre blanc- kastiketta L, G<br>
Jälkiruoaksi pähkinäistä snickers rahkaa L, G</dd>
<dt>Keskiviikko 23.09.</dt><dd>HUOM! Lounas tänään klo 10.30-13.00!<br>
Hoisin glaseerattua possua M</dd></dl>"""

    def test_chef_annos_ja_jalkiruoka_omiin_osastoihin(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = [scrape.siivoa_paiva(p) for p in
                      scrape.normalisoi_paivat(scrape.scrape_linkosuo("https://linkosuo.fi/toimipaikka/hertta/"))]
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in paivat[0]["osastot"]], [
            ("Buffet", ["Naudanliha kebabia ranskalaisilla perunoilla",
                        "Punajuuripihvejä M, G, VEG & raikas piparjuuridippi"]),
            ("Keitto", ["Kermainen basilika-tomaattikeitto"]),
            ("Chef-annos", ["Paistettua puna-ahventa & beurre blanc- kastiketta"]),
            ("Jälkiruoka", ["pähkinäistä snickers rahkaa"]),
        ])
        # HUOM-rivi pois, ruoka jää
        self.assertEqual(paivat[1]["ruoat"], ["Hoisin glaseerattua possua"])


class CaffitellaUusi(unittest.TestCase):
    HTML = """<main><p>MAANANTAI</p>
<p>Pannupihvi sipuli-kermakastikkeessa (G,L) (suomalaista nautaa ja possua)</p>
<p>BBQ-broileria (G,M) (suomalaista broileria)<br>Paahdettua perunaa (G,M) &amp; riisiä (G,M)</p>
<p>Salaattibuffet</p>
<p><span>Broiler burger (L) Tofu poke (G,VE) (annosruoka ei sis.buffettiin)</span></p>
<p><br>TIISTAI</p><p>Ylikypsää possua (G,L)</p></main>"""

    def test_br_rivit_ja_annokset(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = [scrape.siivoa_paiva(p) for p in scrape.normalisoi_paivat(scrape.scrape_caffitella())]
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in paivat[0]["osastot"]], [
            ("Lounasbuffet", ["Pannupihvi sipuli-kermakastikkeessa (suomalaista nautaa ja possua)",
                              "BBQ-broileria (suomalaista broileria)", "Paahdettua perunaa & riisiä",
                              "Salaattibuffet"]),
            ("Annosruoat (ei sis. buffettiin)", ["Broiler burger", "Tofu poke"]),
        ])
        self.assertEqual(paivat[1]["ruoat"], ["Ylikypsää possua"])


class SpeakeasySpanit(unittest.TestCase):
    HTML = """<body><p><strong><span>MAANANTAI 21</span><span>.9.<br></span></strong>
<b><span>Kievinkana ja mango-chilimajoneesi</span><span>, ranskalaiset (</span><span>L</span><span>)<br></span></b>
<b>Speakeasyn original wingsejä (L,G)<br></b></p>
<p><strong>TIISTAI 22<span>.9.<br></span></strong><b>Mustamakkara ja puolukkahillo (L)<br></b></p>
<p>L=laktoositon</p></body>"""

    def test_spanit_yhdistyvat_ja_paivamaara_pois(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = [scrape.siivoa_paiva(p) for p in scrape.normalisoi_paivat(scrape.scrape_speakeasy())]
        self.assertEqual(paivat[0]["ruoat"], ["Kievinkana ja mango-chilimajoneesi, ranskalaiset",
                                             "Speakeasyn original wingsejä"])
        self.assertEqual(paivat[1]["ruoat"], ["Mustamakkara ja puolukkahillo"])


class SiivousLisat(unittest.TestCase):
    def test_pienet_koodit_ja_paivamaarat(self):
        self.assertEqual(scrape.siivoa_ruoka("Muikkuja l"), "Muikkuja")
        self.assertEqual(scrape.siivoa_ruoka("Pangasius g"), "Pangasius")
        self.assertIsNone(scrape.siivoa_ruoka("21.9."))
        self.assertIsNone(scrape.siivoa_ruoka("HUOM! Lounas tänään klo 10.30-13.00!"))
        self.assertEqual(scrape.siivoa_ruoka("Piparjuuridippi M, G (SAA VEG dippi keittiöstä)"), "Piparjuuridippi")

    def test_sodexo_kaannokset_ja_etuliite(self):
        self.assertEqual(scrape._sodexo_osaston_nimi("Soup of the day"), "Päivän keitto")
        data = {"mealdates": [{"date": "Maanantai", "courses": {
            "1": {"title_fi": "Bowl Factory: Nuudeleita ja kanaa", "category": "Bowl Factory 13,80 €"},
            "2": {"title_fi": "Bowl Factory Nuudeleita", "category": "Bowl Factory 13,80 €"}}}]}
        class R:
            def raise_for_status(self): pass
            def json(self): return data
        with mock.patch.object(scrape.requests, "get", return_value=R()):
            paivat = scrape.scrape_sodexo(110)
        self.assertEqual(paivat[0]["osastot"][0], {"nimi": "Bowl Factory",
                                                    "ruoat": ["Nuudeleita ja kanaa", "Nuudeleita"]})


class Fastelle(unittest.TestCase):
    HTML = """<dl><dt>Maanantai 14.09.</dt><dd>Kaurapuuro/oatmeal porridge &amp;<br>
Punnittava aamiaisleipä/Breakfast bread to be weighed from 8:00 to 9:30<br><br>
Lempiruokaviikko!<br><br>
-Välimeren tomaattikeitto M,G,V<br><br>
-Maissipaneroitua kananfilettä M,G<br>
Ranch kastiketta L,G<br><br>
-Lempiruokatoive: Perinteisiä kaalikääryleitä M,G,sipuli<br>
Puolukkahillo M,G,V<br><br>
*Proteiinit punnittavaan salaattiin:<br>
– Keitettyä kananmunaa M,G,V<br>
– Broileria (linjasta)<br>
**<br>
Favorite Food Week!<br>
– Mediterranean tomato soup M,G,V</dd></dl>"""

    def test_uusi_muoto(self):
        with mock.patch.object(scrape, "hae_sivu", return_value=self.HTML):
            paivat = [scrape.siivoa_paiva(p) for p in scrape.normalisoi_paivat(scrape.scrape_fastelle())]
        self.assertEqual(len(paivat), 1)
        self.assertEqual([(o["nimi"], o["ruoat"]) for o in paivat[0]["osastot"]], [
            ("Lounas", ["Välimeren tomaattikeitto",
                        "Maissipaneroitua kananfilettä", "– Ranch kastiketta",
                        "Lempiruokatoive: Perinteisiä kaalikääryleitä", "– Puolukkahillo"]),
            ("Proteiinit punnittavaan salaattiin", ["Keitettyä kananmunaa", "Broileria (linjasta)"]),
        ])

    def test_siivous(self):
        self.assertIsNone(scrape.siivoa_ruoka("Lempiruokaviikko!"))
        self.assertIsNone(scrape.siivoa_ruoka("Punnittava aamiaisleipä/Breakfast bread 8:00 to 9:30"))
        self.assertEqual(scrape.siivoa_ruoka("Kermainen lohikiusaus L,G,sipuli"), "Kermainen lohikiusaus")
        self.assertEqual(scrape.siivoa_ruoka("pannukakkua ja hilloa <3"), "pannukakkua ja hilloa")
        self.assertEqual(scrape.siivoa_ruoka("Sipulikeitto"), "Sipulikeitto")


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
            ("Chef-annos", ["Puna-ahventa"]),
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


class Tietoturva(unittest.TestCase):
    def test_sama_sivusto(self):
        f = scrape.sama_sivusto
        self.assertTrue(f("https://munkkimiehet.fi/kuva.png", "munkkimiehet.fi"))
        self.assertTrue(f("https://www.munkkimiehet.fi/kuva.png", "munkkimiehet.fi"))
        # Huijausyritykset: oikea domain vain osana toista nimeä tai polkua
        self.assertFalse(f("https://munkkimiehet.fi.paha.example/x.png", "munkkimiehet.fi"))
        self.assertFalse(f("https://paha.example/munkkimiehet.fi/x.png", "munkkimiehet.fi"))
        self.assertFalse(f("https://eimunkkimiehet.fi/x.png", "munkkimiehet.fi"))
        self.assertFalse(f("ei-osoite", "munkkimiehet.fi"))

    def test_hae_tavut_hylkaa_muut_kuin_verkko_osoitteet(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", ""):
            self.assertIsNone(scrape.hae_tavut(url), url)

    def test_hae_tavut_hylkaa_vaaran_sivuston(self):
        # Ei verkkopyyntöä: tarkistus tehdään ennen latausta
        with mock.patch.object(scrape.requests, "get",
                               side_effect=AssertionError("ei saa hakea")):
            self.assertIsNone(scrape.hae_tavut("https://paha.example/x.pdf",
                                               sallittu_domain="aitokotilounas.fi"))

    def test_latausraja_on_asetettu(self):
        self.assertLessEqual(scrape.MAKS_LATAUS_TAVUA, 20 * 1024 * 1024)

    def test_issuen_teksti_siivotaan(self):
        siivoa = issuet.siivoa_teksti
        self.assertEqual(siivoa("rivi: <b>paha</b> [linkki](http://paha.example)"),
                         "rivi: bpaha/b linkki([linkki poistettu]")
        self.assertEqual(siivoa("rivi\nkahdella\nrivillä"), "rivi kahdella rivillä")
        self.assertTrue(siivoa("x" * 500).endswith("…"))
        self.assertLessEqual(len(siivoa("x" * 500)), 201)

    def test_issuen_runko_ei_paasta_javascript_osoitetta(self):
        runko = issuet.runko({"nimi": "X", "url": "javascript:alert(1)",
                              "ongelmat": ["ei löytynyt yhtään päivää"],
                              "tunteja_rikki": 72, "vanhentunut": False})
        self.assertNotIn("javascript:", runko)
        self.assertIn("(osoite puuttuu)", runko)

    def test_sivun_skriptit_ovat_omassa_tiedostossa(self):
        html = Path("index.html").read_text(encoding="utf-8")
        # Sivun sisään kirjoitettu JavaScript estäisi tiukan CSP:n
        self.assertNotIn("<script>", html)
        self.assertIn('<script src="app.js">', html)
        self.assertIn("Content-Security-Policy", html)
        self.assertIn("script-src 'self'", html)


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


class Laatutarkistus(unittest.TestCase):
    def paiva(self, ruoat, nimi="Maanantai"):
        return {"paiva": nimi, "ruoat": list(ruoat)}

    def test_kelvollinen_ei_ongelmia(self):
        uusi = {"nimi": "X", "paivat": [self.paiva(["Lihapullia"]), self.paiva(["Kalaa"], "Tiistai")]}
        self.assertEqual(laatu.tarkista(uusi, None), [])

    def test_tyhja_lista_on_ongelma(self):
        vanha = {"paivat": [self.paiva(["Lihapullia"])] * 5}
        self.assertEqual(laatu.tarkista({"paivat": []}, vanha),
                         ["ei löytynyt yhtään päivää (edellisessä ajossa 5)"])

    def test_kaatunut_scraper(self):
        self.assertEqual(laatu.tarkista({"virhe": "timeout"}, None), ["scraper kaatui: timeout"])

    def test_roskarivit_ja_pituus(self):
        self.assertIn("rivi ei näytä ruoalta: Lounas 12,20 €",
                      laatu.tarkista({"paivat": [self.paiva(["Lounas 12,20 €"])]}, None))
        pitka = "a" * 300
        ongelmat = laatu.tarkista({"paivat": [self.paiva([pitka])]}, None)
        self.assertTrue(any("liian pitkä rivi" in o for o in ongelmat), ongelmat)

    def test_identtiset_paivat(self):
        paivat = [self.paiva(["Sama"], p) for p in ("Maanantai", "Tiistai", "Keskiviikko")]
        self.assertIn("kaikilla päivillä sama sisältö", laatu.tarkista({"paivat": paivat}, None))

    def test_paivien_romahdus(self):
        vanha = {"paivat": [self.paiva(["Ruokaa"], p) for p in
                            ("Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai")]}
        ongelmat = laatu.tarkista({"paivat": [self.paiva(["Ruokaa"])]}, vanha)
        self.assertEqual(ongelmat, ["päiviä vain 1 (edellisessä ajossa 5)"])

    def test_yhdista_sailyttaa_vanhan_listan(self):
        nyt = datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc)
        vanha = {"nimi": "X", "paivat": [self.paiva(["Lihapullia"])] * 5,
                 "paivitetty": "2026-09-13T06:00:00+00:00"}
        rivi = laatu.yhdista({"nimi": "X", "paivat": []}, vanha, nyt)
        self.assertEqual(rivi["paivat"], vanha["paivat"])
        self.assertTrue(rivi["vanhentunut"])
        self.assertEqual(rivi["paivitetty"], "2026-09-13T06:00:00+00:00")
        self.assertEqual(rivi["rikki_alkaen"], nyt.isoformat())

    def test_yhdista_muistaa_milloin_rikkoutui(self):
        nyt = datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc)
        vanha = {"nimi": "X", "paivat": [self.paiva(["Lihapullia"])] * 5,
                 "paivitetty": "2026-09-13T06:00:00+00:00",
                 "rikki_alkaen": "2026-09-14T06:00:00+00:00"}
        rivi = laatu.yhdista({"nimi": "X", "paivat": []}, vanha, nyt)
        self.assertEqual(rivi["rikki_alkaen"], "2026-09-14T06:00:00+00:00")

    def test_yhdista_siivoaa_merkinnat_kun_korjaantuu(self):
        nyt = datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc)
        vanha = {"nimi": "X", "paivat": [], "vanhentunut": True,
                 "ongelmat": ["ei löytynyt yhtään päivää"],
                 "rikki_alkaen": "2026-09-13T06:00:00+00:00"}
        rivi = laatu.yhdista({"nimi": "X", "paivat": [self.paiva(["Lihapullia"])]}, vanha, nyt)
        self.assertNotIn("vanhentunut", rivi)
        self.assertNotIn("ongelmat", rivi)
        self.assertNotIn("rikki_alkaen", rivi)
        self.assertEqual(rivi["paivitetty"], nyt.isoformat())

    def test_raportti_ilmoittaa_vasta_rajan_jalkeen(self):
        nyt = datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc)
        tuore = {"nimi": "Tuore", "url": "https://a.fi", "ongelmat": ["ei löytynyt yhtään päivää"],
                 "rikki_alkaen": "2026-09-14T18:00:00+00:00"}
        vanha = {"nimi": "Pitkaan", "url": "https://b.fi", "ongelmat": ["ei löytynyt yhtään päivää"],
                 "rikki_alkaen": "2026-09-12T06:00:00+00:00", "vanhentunut": True}
        kunnossa = {"nimi": "Kunnossa", "url": "https://c.fi"}
        rap = laatu.raportti([tuore, vanha, kunnossa], nyt)
        self.assertEqual([r["nimi"] for r in rap["rikki"]], ["Tuore", "Pitkaan"])
        self.assertEqual([r["nimi"] for r in rap["ilmoitettavat"]], ["Pitkaan"])
        self.assertEqual(rap["kunnossa"], ["Kunnossa"])
        self.assertEqual(rap["ilmoitettavat"][0]["tunteja_rikki"], 72)

    def test_viikonlopun_katko_ei_aiheuta_ilmoitusta(self):
        # Lauantain ensimmäisestä ajosta maanantain ensimmäiseen = 48 h
        lauantai = datetime(2026, 9, 19, 0, 37, tzinfo=timezone.utc)
        maanantai = lauantai + timedelta(hours=48)
        rivi = {"nimi": "Sisu", "url": "https://a.fi",
                "ongelmat": ["ei löytynyt yhtään päivää"],
                "rikki_alkaen": lauantai.isoformat()}
        self.assertEqual(laatu.raportti([rivi], maanantai)["ilmoitettavat"], [])


class DataTarkistus(unittest.TestCase):
    def kirjoita(self, data):
        import tempfile
        polku = Path(tempfile.mkdtemp()) / "lounaat.json"
        polku.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return polku

    def kelvollinen(self):
        return {
            "paivitetty": "2026-09-14T06:00:00+00:00",
            "ravintolat": [
                {"nimi": f"R{i}", "alue": "Hervanta", "kategoria": 1,
                 "url": "https://example.fi",
                 "paivat": [{"paiva": "Maanantai", "ruoat": ["Lihapullia"]}]}
                for i in range(laatu_vahimmais())
            ],
        }

    def test_oikea_repo_data_kelpaa(self):
        self.assertEqual(tarkista_data.tarkista(Path("lounaat.json")), [])

    def test_kelvollinen_menee_lapi(self):
        self.assertEqual(tarkista_data.tarkista(self.kirjoita(self.kelvollinen())), [])

    def test_tuntematon_paiva_ja_tyhja_ruoka(self):
        d = self.kelvollinen()
        d["ravintolat"][0]["paivat"][0]["paiva"] = "Maanatai"
        d["ravintolat"][1]["paivat"][0]["ruoat"] = []
        virheet = tarkista_data.tarkista(self.kirjoita(d))
        self.assertTrue(any("tuntematon päivä" in v for v in virheet), virheet)
        self.assertTrue(any("ruoat puuttuu" in v for v in virheet), virheet)

    def test_osastot_eivat_vastaa_ruokia(self):
        d = self.kelvollinen()
        d["ravintolat"][0]["paivat"][0]["osastot"] = [{"nimi": "Buffet", "ruoat": ["Muuta"]}]
        virheet = tarkista_data.tarkista(self.kirjoita(d))
        self.assertTrue(any("eivät vastaa" in v for v in virheet), virheet)

    def test_liian_harva_lista_havaitaan(self):
        d = self.kelvollinen()
        for r in d["ravintolat"][1:]:
            r["paivat"] = []
        virheet = tarkista_data.tarkista(self.kirjoita(d))
        self.assertTrue(any("vain 1 ravintolalla" in v for v in virheet), virheet)


def laatu_vahimmais() -> int:
    return tarkista_data.VAHIMMAIS_LISTALLISET


if __name__ == "__main__":
    unittest.main()
