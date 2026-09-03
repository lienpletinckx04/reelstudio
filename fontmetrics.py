#!/usr/bin/env python3
"""
fontmetrics.py — meet tekstbreedtes zonder externe bibliotheken.

Leest rechtstreeks de tabellen van een .ttf/.otf/.ttc-bestand (name, head,
hhea, hmtx, cmap) en telt de letterbreedtes op. Geen kerning, maar ruim
nauwkeurig genoeg om een afgeronde "pil" rond een ondertitel te tekenen.

Waarom dit ertoe doet: libass kiest zélf een vervangend font als de gevraagde
naam niet bestaat, zónder te klagen. Op een computer zonder "Helvetica Neue"
wordt dat stilletjes een ander font met andere breedtes — de tekst past dan
niet meer in de vlakken die wij eromheen tekenen. Daarom zoeken we hier eerst
op welk font er écht staat, en geven we díe naam door aan libass.

Gebruik:
    from fontmetrics import Font, zoek_keten
    f = Font.find("Helvetica Neue Bold")
    f.width("Hallo wereld", 38)      # breedte in pixels bij 38px
    f.line_height(38)                # regelhoogte zoals libass ze rekent

    naam, f = zoek_keten("Archivo Black | Arial Bold | DejaVu Sans Bold")
"""
import os
import platform
import struct
import sys


def _font_mappen():
    """Waar fonts staan, per besturingssysteem. Eigen fonts gaan voor.

    De map fonts/ naast dit bestand staat bewust vooraan: wie een merk exact
    wil overnemen zet daar de echte lettertypes in, en dan gebruikt zowel deze
    meting als libass (via fontsdir) precies dat bestand.
    """
    eigen = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
    s = platform.system().lower()
    if s == "darwin":
        return [eigen,
                os.path.expanduser("~/Library/Fonts"),
                "/Library/Fonts",
                "/System/Library/Fonts",
                "/System/Library/Fonts/Supplemental"]
    if s == "windows":
        return [eigen,
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"),
                os.path.expandvars(r"%WINDIR%\Fonts")]
    return [eigen,
            os.path.expanduser("~/.local/share/fonts"),
            os.path.expanduser("~/.fonts"),
            "/usr/local/share/fonts",
            "/usr/share/fonts"]


FONT_DIRS = _font_mappen()

_CACHE = {}
_BESTANDEN = {}


def _u16(b, o): return struct.unpack(">H", b[o:o + 2])[0]
def _s16(b, o): return struct.unpack(">h", b[o:o + 2])[0]
def _u32(b, o): return struct.unpack(">I", b[o:o + 4])[0]


class Font:
    def __init__(self, path, data, offset):
        self.path = path
        self._d = data
        self.tables = {}
        num = _u16(data, offset + 4)
        p = offset + 12
        for _ in range(num):
            tag = data[p:p + 4].decode("latin-1")
            off = _u32(data, p + 8)
            ln = _u32(data, p + 12)
            self.tables[tag] = (off, ln)
            p += 16
        self.names = self._read_names()
        self.upm = 1000
        self.asc = 800
        self.desc = -200
        self.gap = 0
        self._adv = None
        self._cmap = None
        if "head" in self.tables:
            o, _ = self.tables["head"]
            self.upm = _u16(data, o + 18) or 1000
        if "hhea" in self.tables:
            o, _ = self.tables["hhea"]
            self.asc = _s16(data, o + 4)
            self.desc = _s16(data, o + 6)
            self.gap = _s16(data, o + 8)
            self._nhm = _u16(data, o + 34)
        self.win_asc = self.win_desc = 0
        if "OS/2" in self.tables:
            o, ln = self.tables["OS/2"]
            if ln >= 78:
                self.win_asc = _u16(data, o + 74)
                self.win_desc = _u16(data, o + 76)

    # ── naam ──────────────────────────────────────────────────────
    def _read_names(self):
        out = {}
        if "name" not in self.tables:
            return out
        d = self._d
        o, _ = self.tables["name"]
        count = _u16(d, o + 2)
        stro = o + _u16(d, o + 4)
        p = o + 6
        for _ in range(count):
            pid, eid, lid, nid, ln, so = struct.unpack(">HHHHHH", d[p:p + 12])
            p += 12
            raw = d[stro + so:stro + so + ln]
            try:
                if pid in (0, 3):
                    s = raw.decode("utf-16-be")
                elif pid == 1:
                    s = raw.decode("mac_roman")
                else:
                    continue
            except Exception:
                continue
            if nid in (1, 2, 4, 6, 16, 17) and (nid not in out or pid == 3):
                out[nid] = s
        return out

    @property
    def fullname(self):
        n = self.names
        if 4 in n:
            return n[4]
        return ((n.get(1, "") + " " + n.get(2, "")).strip())

    def matches(self, wanted):
        w = wanted.lower().replace("-", " ").split()
        cands = [self.fullname]
        n = self.names
        if 1 in n and 2 in n:
            cands.append(n[1] + " " + n[2])
        if 16 in n and 17 in n:
            cands.append(n[16] + " " + n[17])
        if 1 in n and n.get(2, "").lower() == "regular":
            cands.append(n[1])
        for c in cands:
            if c.lower().replace("-", " ").split() == w:
                return True
        return False

    # ── metrics ───────────────────────────────────────────────────
    def _load_hmtx(self):
        d = self._d
        o, _ = self.tables["hmtx"]
        self._adv = [_u16(d, o + 4 * i) for i in range(self._nhm)]

    def _load_cmap(self):
        d = self._d
        self._cmap = {}
        if "cmap" not in self.tables:
            return
        o, _ = self.tables["cmap"]
        n = _u16(d, o + 2)
        best = None
        for i in range(n):
            pid, eid, off = struct.unpack(">HHI", d[o + 4 + 8 * i:o + 12 + 8 * i])
            fmt = _u16(d, o + off)
            score = {12: 3, 4: 2}.get(fmt, 0)
            if pid == 3 and eid in (1, 10) or pid == 0:
                score += 1
            if score and (best is None or score > best[0]):
                best = (score, o + off, fmt)
        if not best:
            return
        _, so, fmt = best
        if fmt == 4:
            segx2 = _u16(d, so + 6)
            seg = segx2 // 2
            ends = [_u16(d, so + 14 + 2 * i) for i in range(seg)]
            starts = [_u16(d, so + 16 + segx2 + 2 * i) for i in range(seg)]
            deltas = [_s16(d, so + 16 + 2 * segx2 + 2 * i) for i in range(seg)]
            rng_off_base = so + 16 + 3 * segx2
            for i in range(seg):
                ro = _u16(d, rng_off_base + 2 * i)
                for c in range(starts[i], min(ends[i], 0xFFFE) + 1):
                    if ro == 0:
                        g = (c + deltas[i]) & 0xFFFF
                    else:
                        gp = rng_off_base + 2 * i + ro + 2 * (c - starts[i])
                        g = _u16(d, gp)
                        if g:
                            g = (g + deltas[i]) & 0xFFFF
                    if g:
                        self._cmap[c] = g
        elif fmt == 12:
            ngroups = _u32(d, so + 12)
            p = so + 16
            for _ in range(ngroups):
                sc, ec, sg = struct.unpack(">III", d[p:p + 12])
                p += 12
                for c in range(sc, min(ec, 0x10FFFF) + 1):
                    self._cmap[c] = sg + (c - sc)

    def advance(self, ch):
        if self._adv is None:
            self._load_hmtx()
        if self._cmap is None:
            self._load_cmap()
        g = self._cmap.get(ord(ch))
        if g is None:
            g = self._cmap.get(ord("x"), 0)
        if g < len(self._adv):
            return self._adv[g]
        return self._adv[-1] if self._adv else self.upm // 2

    # libass schaalt een font zó dat winAscent+winDescent (OS/2) gelijk is aan
    # de ASS-fontgrootte. De echte em-grootte in pixels is dus kleiner.
    def em(self, size):
        tot = (self.win_asc + self.win_desc) or (self.asc - self.desc) or self.upm
        return size * self.upm / tot

    def width(self, text, size):
        return sum(self.advance(c) for c in text) * self.em(size) / self.upm

    def line_height(self, size):
        return (self.asc - self.desc + self.gap) * self.em(size) / self.upm

    def ascent(self, size):
        return self.asc * self.em(size) / self.upm

    def descent(self, size):
        return -self.desc * self.em(size) / self.upm

    # ── zoeken ────────────────────────────────────────────────────
    @staticmethod
    def _iter_fonts_in_file(path):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception:
            return
        if data[:4] == b"ttcf":
            n = _u32(data, 8)
            for i in range(n):
                yield Font(path, data, _u32(data, 12 + 4 * i))
        elif data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            yield Font(path, data, 0)

    @classmethod
    def find(cls, name, dirs=None):
        """Zoek een font op volledige naam, bv. 'Helvetica Neue Bold'."""
        sleutel = (name, tuple(dirs) if dirs else None)
        if sleutel in _CACHE:
            return _CACHE[sleutel]
        for pad in _fontbestanden(dirs):
            for f in cls._iter_fonts_in_file(pad) or []:
                if f.matches(name):
                    _CACHE[sleutel] = f
                    return f
        _CACHE[sleutel] = None
        return None


def _fontbestanden(dirs=None):
    """Alle fontbestanden, recursief — op Linux zitten ze in submappen."""
    sleutel = tuple(dirs) if dirs else None
    if sleutel in _BESTANDEN:
        return _BESTANDEN[sleutel]
    uit = []
    for d in (dirs or FONT_DIRS):
        if not os.path.isdir(d):
            continue
        for wortel, _submappen, namen in os.walk(d):
            for fn in sorted(namen):
                if fn.lower().endswith((".ttf", ".otf", ".ttc")):
                    uit.append(os.path.join(wortel, fn))
    _BESTANDEN[sleutel] = uit
    return uit


def zoek_keten(keten, dirs=None):
    """Eerste font uit een keten dat op deze computer bestaat.

    Een keten is 'Archivo Black | Helvetica Neue Bold | Arial Bold' — het merk
    noemt zijn ideale lettertype eerst en daarna wat er op andere computers
    voorhanden is. We geven de naam terug die we écht gevonden hebben, zodat
    libass exact hetzelfde font pakt als wat we hier opmeten.

    Geeft (naam, Font) terug, of (None, None) als niets uit de keten bestaat.
    """
    for naam in [n.strip() for n in str(keten).split("|")]:
        if not naam:
            continue
        f = Font.find(naam, dirs)
        if f is not None:
            return naam, f
    return None, None


class EstimatedFont:
    """Noodoplossing als het font niet gevonden wordt: ruwe schatting."""
    path = None

    def __init__(self, factor=0.56):
        self.factor = factor

    def width(self, text, size):
        return len(text) * size * self.factor

    def line_height(self, size):
        return size * 1.36

    def ascent(self, size):
        return size * 1.0

    def descent(self, size):
        return size * 0.36


def get_font(keten):
    """Font uit een keten, met een schatting als noodrem.

    Bij een schatting kloppen de vlakken rond de tekst niet meer precies; de
    aanroeper hoort dat te melden. Daarom geeft haal_font() ook terug wát er
    gevonden is.
    """
    return haal_font(keten)[1]


def haal_font(keten):
    """(naam, font, gevonden) — naam is wat je aan libass moet doorgeven."""
    naam, f = zoek_keten(keten)
    if f is not None:
        return naam, f, True
    eerste = str(keten).split("|")[0].strip()
    return eerste, EstimatedFont(), False


if __name__ == "__main__":
    for n in sys.argv[1:] or ["Avenir Next Demi Bold", "Avenir Next Ultra Light", "Avenir Next Medium", "Avenir Next"]:
        f = Font.find(n)
        if f:
            print(f"{n}: {f.path}  upm={f.upm} asc={f.asc} desc={f.desc} gap={f.gap} win={f.win_asc}+{f.win_desc} em(38)={f.em(38):.1f}")
            print(f"   'Hallo wereld' @38px = {f.width('Hallo wereld', 38):.1f}px, regelhoogte={f.line_height(38):.1f}px")
        else:
            print(f"{n}: NIET GEVONDEN")
