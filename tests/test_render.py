"""Rooktest van begin tot eind: nepopname → yap → render. Slaat zichzelf over zonder
ffmpeg/libass. Draai: ./reelstudio.sh test"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import omgeving  # noqa: E402

FF, FFPROBE = omgeving.zoek_ffmpeg()
KLAAR = bool(FF) and omgeving.mogelijkheden(FF)["ass"]
NAAM = "rooktest-yap"
LESDIR = os.path.join(HERE, "lessen", NAAM)


def draai(*args):
    return subprocess.run([sys.executable, os.path.join(HERE, "reelstudio.py")] + list(args),
                          capture_output=True, text=True)


def lees(pad):
    with open(pad, encoding="utf-8") as fh:
        return fh.read()


def schrijf(pad, tekst):
    with open(pad, "w", encoding="utf-8") as fh:
        fh.write(tekst)


def dur(pad):
    r = subprocess.run([FFPROBE, "-v", "error",
                        "-show_entries", "format=duration", "-of", "csv=p=0", pad],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


@unittest.skipUnless(KLAAR, "ffmpeg met libass niet beschikbaar")
class VanBeginTotEind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bron = os.path.join(cls.tmp, "bron.mp4")
        # 12 s: 2,5 s "spraak" en 1 s stilte, vier keer na elkaar
        r = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "testsrc2=s=540x960:r=30:d=12",
                            "-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*220*t)*lt(mod(t,3.5),2.5)':s=48000:d=12",
                            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-shortest", cls.bron], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        shutil.rmtree(LESDIR, ignore_errors=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(LESDIR, ignore_errors=True)

    def test_1_yap_knipt_de_pauzes(self):
        r = draai("yap", NAAM, self.bron, "--hook", "Test hook", "--cta", "Volg mij", "--overschrijf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sb = lees(os.path.join(LESDIR, "storyboard.yaml"))
        self.assertIn("knip:", sb)
        self.assertIn("captions: woord", sb)
        self.assertGreaterEqual(sb.count("van:"), 3)

    def test_2_check_en_render_met_woorden(self):
        woorden = []
        for i, t in enumerate("dit is een test van de woordcaptions".split()):
            a = 0.1 + i * 0.3
            woorden.append(f"{i+1}\n00:00:0{int(a)},{int((a % 1)*1000):03d} --> "
                           f"00:00:0{int(a+.25)},{int(((a+.25) % 1)*1000):03d}\n{t}\n")
        schrijf(os.path.join(LESDIR, "woorden.srt"), "\n".join(woorden))
        with open(os.path.join(LESDIR, "storyboard.yaml"), "a", encoding="utf-8") as fh:
            fh.write("achtergrond: zacht\n"
                     "koppen:\n  - { van: 0:04, tot: 0:06, tekst: Een kop }\n"
                     "graphics:\n  - { van: 0:07, tot: 0:09, type: getal, tekst: \"3\" }\n")
        r = draai("check", NAAM)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        out = os.path.join(self.tmp, "uit.mp4")
        r = draai("render", NAAM, "--preview", "--uit", out)
        self.assertEqual(r.returncode, 0, r.stdout[-600:] + r.stderr[-600:])
        self.assertTrue(os.path.exists(out))
        # 12 s min 3 knippen (± 0,8 s elk) plus een eindkaart van 3,2 s
        self.assertGreater(dur(out), 8.0)
        self.assertLess(dur(out), 14.0)
        probe = subprocess.run([FF, "-hide_banner", "-i", out], capture_output=True, text=True).stderr
        self.assertIn("Audio:", probe)
        self.assertIn("Video:", probe)

    def test_3_bijsturen_past_storyboard_aan(self):
        r = draai("bijsturen", NAAM, "minder zooms")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sb = lees(os.path.join(LESDIR, "storyboard.yaml"))
        self.assertIn("autozoom: weinig", sb)
        voorkeur = os.path.join(HERE, "yap-voorkeuren.yaml")
        if os.path.exists(voorkeur):
            os.remove(voorkeur)


if __name__ == "__main__":
    unittest.main()
