#!/usr/bin/env python3
"""srt_van_txt.py — zet een eenvoudig 'start|einde|tekst'-bestand om naar .srt
(handig om ondertitels met de hand te herschrijven zonder srt-gedoe)."""
import sys, os, re

def t(s):
    parts = [float(p) for p in s.strip().split(":")]
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v

def srt(v):
    h = int(v // 3600); m = int((v % 3600) // 60); s = int(v % 60); ms = int(round((v - int(v)) * 1000))
    if ms == 1000: ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".srt"
n = 0
with open(dst, "w", encoding="utf-8") as out:
    for line in open(src, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        a, b, tekst = line.split("|", 2)
        n += 1
        out.write(f"{n}\n{srt(t(a))} --> {srt(t(b))}\n{tekst.strip()}\n\n")
print(f"✓ {dst}: {n} ondertitels")
