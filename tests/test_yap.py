"""Eenheidstests voor yap.py — geen ffmpeg nodig. Draai: ./reelstudio.sh test"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yap  # noqa: E402


def w(a, b, t):
    return (a, b, t)


class Pauzes(unittest.TestCase):
    def test_begin_en_einde_verdwijnen_helemaal(self):
        k = yap.pauzes_naar_knips([(0.0, 0.5), (9.5, 10.0)], 10.0)
        self.assertEqual(k[0][0], 0.0)
        self.assertEqual(k[-1][1], 10.0)

    def test_tussen_zinnen_blijft_marge(self):
        (van, tot), = yap.pauzes_naar_knips([(3.0, 3.8)], 10.0)
        self.assertAlmostEqual(van, 3.0 + yap.PAUZE_MARGE, places=3)
        self.assertAlmostEqual(tot, 3.8 - yap.PAUZE_MARGE, places=3)

    def test_te_korte_knip_wordt_genegeerd(self):
        self.assertEqual(yap.pauzes_naar_knips([(3.0, 3.3)], 10.0), [])


class Groepen(unittest.TestCase):
    def test_breekt_na_leesteken(self):
        g = yap.groepeer_woorden([w(0, .3, "a"), w(.3, .6, "b."), w(.6, .9, "c")])
        self.assertEqual([[x[2] for x in grp] for grp in g], [["a", "b."], ["c"]])

    def test_maximum_woorden(self):
        ws = [w(i * .3, i * .3 + .25, "x") for i in range(7)]
        g = yap.groepeer_woorden(ws, max_woorden=1)
        self.assertEqual(len(g), 7)

    def test_breekt_op_adempauze(self):
        g = yap.groepeer_woorden([w(0, .3, "a"), w(2.0, 2.3, "b")])
        self.assertEqual(len(g), 2)

    def test_geknipte_woorden_verdwijnen(self):
        ws = [w(0, .3, "a"), w(1.0, 1.3, "b"), w(2.0, 2.3, "c")]
        rest = yap.woorden_zonder_geknipte(ws, [(0.9, 1.5)])
        self.assertEqual([x[2] for x in rest], ["a", "c"])


class Versprekingen(unittest.TestCase):
    def test_vulwoord(self):
        ws = [w(0, .3, "ik"), w(.4, .7, "euh"), w(.8, 1.1, "plan")]
        k = yap.vind_versprekingen(ws)
        self.assertEqual(len(k), 1)
        self.assertTrue(k[0][0] < .4 and k[0][1] > .7)

    def test_dubbel_woord(self):
        ws = [w(0, .3, "ik"), w(.3, .6, "ik"), w(.6, .9, "plan")]
        k = yap.vind_versprekingen(ws)
        self.assertEqual(len(k), 1)
        self.assertLess(k[0][1], .6)          # het tweede "ik" blijft

    def test_herstart_knipt_de_mislukte_poging(self):
        ws = [w(0, .3, "ik"), w(.3, .6, "plan"), w(.6, .9, "nummer"),
              w(3, 3.3, "ik"), w(3.3, 3.6, "plan"), w(3.6, 3.9, "alles")]
        k = yap.vind_versprekingen(ws)
        self.assertEqual(len(k), 1)
        self.assertGreater(k[0][1], 2.9)      # tot waar de goede poging begint
        self.assertLess(k[0][1], 3.0)

    def test_gewone_zin_blijft_heel(self):
        ws = [w(i * .3, i * .3 + .25, t) for i, t in enumerate("dit is een gewone zin zonder fouten".split())]
        self.assertEqual(yap.vind_versprekingen(ws), [])

    def test_herhaling_ver_uit_elkaar_is_geen_herstart(self):
        ws = [w(0, .3, "ik"), w(.3, .6, "plan"), w(10, 10.3, "ik"), w(10.3, 10.6, "plan")]
        self.assertEqual(yap.vind_versprekingen(ws), [])


class Zooms(unittest.TestCase):
    SEGS = [(0, 2.5, 1.0), (3, 6, 1.0), (6.5, 9, 1.0), (9.5, 12, 1.0)]

    def test_geen(self):
        self.assertEqual(yap.plan_zooms(self.SEGS, "geen"), [])

    def test_normaal_om_de_andere(self):
        z = yap.plan_zooms(self.SEGS, "normaal")
        self.assertEqual([x[0] for x in z], [3, 9.5])

    def test_korte_stukken_krijgen_geen_zoom(self):
        self.assertEqual(yap.plan_zooms([(0, .5, 1.0), (1, 1.6, 1.0)], "veel"), [])

    def test_versnelde_stukken_slaan_we_over(self):
        self.assertEqual(yap.plan_zooms([(0, 5, 8.0)], "veel"), [])

    def test_zoom_overlapt_nooit(self):
        z = sorted(yap.plan_zooms(self.SEGS + [(13, 25, 1.0)], "veel"))
        for a, b in zip(z, z[1:]):
            self.assertLessEqual(a[1], b[0])


class Feedback(unittest.TestCase):
    def test_minder_zooms(self):
        wz, _ = yap.feedback_naar_wijzigingen("minder zooms", {"autozoom": "normaal"})
        self.assertEqual(wz["autozoom"], "weinig")

    def test_meer_zooms_blijft_binnen_de_trap(self):
        wz, _ = yap.feedback_naar_wijzigingen("meer zooms", {"autozoom": "veel"})
        self.assertEqual(wz["autozoom"], "veel")

    def test_engels(self):
        wz, _ = yap.feedback_naar_wijzigingen("fewer zooms and no sound effects", {"autozoom": "normaal"})
        self.assertEqual(wz, {"autozoom": "weinig", "geluid": False})

    def test_captions_hoger(self):
        wz, _ = yap.feedback_naar_wijzigingen("captions hoger", {})
        self.assertLess(wz["captions_hoogte"], 0.64)

    def test_een_woord(self):
        wz, _ = yap.feedback_naar_wijzigingen("één woord per keer", {})
        self.assertEqual(wz["captions_woorden"], 1)

    def test_onbegrepen_geeft_niets(self):
        self.assertEqual(yap.feedback_naar_wijzigingen("maak het blauw", {})[0], {})


class Woorden(unittest.TestCase):
    def test_srt_met_ruis(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "w.srt")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("1\n00:00:00,100 --> 00:00:00,400\nHallo\n\n"
                         "2\n00:00:00,500 --> 00:00:00,900\n[MUZIEK]\n\n"
                         "3\n00:00:01,000 --> 00:00:01,600\nTwee woorden\n")
            ws = yap.lees_woorden(p)
            self.assertEqual([x[2] for x in ws], ["Hallo", "Twee", "woorden"])
            self.assertAlmostEqual(ws[0][0], 0.1)

    def test_voorkeuren_rondje(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v.yaml")
            yap.schrijf_voorkeuren(p, {"autozoom": "weinig", "geluid": False, "captions_hoogte": 0.58})
            self.assertEqual(yap.lees_voorkeuren(p),
                             {"autozoom": "weinig", "geluid": False, "captions_hoogte": 0.58})


if __name__ == "__main__":
    unittest.main()
