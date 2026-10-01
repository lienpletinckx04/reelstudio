# Praatreels (yap edits)

Je filmt jezelf, Reelstudio doet de montage. Film → `yap` → kijken → bijsturen → posten.

```bash
./reelstudio.sh yap mijn-reel ~/Downloads/opname.mov \
    --hook "3 dingen die ik nooit meer doe" --cta "Volg voor meer" --merk asklien
./reelstudio.sh render mijn-reel --preview      # snel kijken (± 10 s)
./reelstudio.sh bijsturen mijn-reel "minder zooms, captions hoger"
./reelstudio.sh render mijn-reel                # de echte
```

## Wat `yap` automatisch doet

| Onderdeel | Hoe |
|---|---|
| **Pauzes eruit** | stiltes ≥ 0,35 s worden weggeknipt, 0,12 s blijft staan zodat het menselijk blijft; stilte vooraan en achteraan verdwijnt helemaal (`--pauze`, `--drempel`) |
| **Captions per woord** | 1–3 woorden tegelijk, het gesproken woord in je accentkleur, groot en met rand (whisper per woord; zonder whisper schat hij de timing uit zinnen) |
| **Zoomsprongen** | op de sneden: zoom vlot in bij een nieuw stuk, hard terug bij de volgende snede (`--zoom geen|weinig|normaal|veel`) |
| **Hook** | één regel boven het beeld in de eerste 2,6 s |
| **Koppen** | headline-stickers (`koppen:` in het storyboard), schuin, in je accentkleur |
| **Geluid** | zachte whoosh bij elke zoomsprong, pop bij elke kop — gemaakt door ffmpeg zelf, geen bestanden nodig (`geluid: nee` zet het uit) |
| **Eindkaart** | jouw CTA in je merk, 3 s |
| **Merk** | kleuren, lettertype, wordmark uit `merk/<naam>.yaml` |

Niet gedaan: achtergrond vervangen of opruimen. Dat vraagt een segmentatiemodel en
breekt de regel dat alles lokaal en zonder pakketten werkt. Een `look: warm` en een
net kader komen ver; wil je het toch, dan is dat een aparte stap vóór `yap`.

## Bijsturen in gewone taal

`./reelstudio.sh bijsturen <reel> "<zin>"` past het storyboard aan én schrijft het naar
`yap-voorkeuren.yaml`. Je volgende reel begint dus al met jouw smaak.

Herkend (NL en EN): minder / meer / geen zooms · geen geluidseffecten · captions
hoger / lager · grotere / kleinere captions · hoofdletters aan / uit.

## Wat Claude doet als je een opname aanlevert

1. `./reelstudio.sh dokter`, dan `yap` met hook en CTA. Vraag er niet om als de
   gebruiker ze al gaf; verzin geen hook als er geen is, stel er twee voor.
2. Lees `woorden.srt` na op verhoren (eigennamen!) en zet vaste fixes in `woordenboek.conf`.
3. Haal beelden op met `frame <reel> m:ss` en bepaal waar een kop hoort: één per
   nieuw idee, hooguit 1 per 5 s, max. 6 woorden, nooit tegelijk met de hook.
4. `check`, daarna `render --preview`, kijk drie frames na: hook, een caption midden
   in een zin, de eindkaart. Controleer dat captions niet onder de Instagram-UI vallen
   (onderste 430 px) en dat de zoom het gezicht niet afsnijdt (`zoom_midden: [x, y]`).
5. Stuur bij op feedback met `bijsturen`; wat niet herkend wordt zet je zelf in het storyboard.

## De regels waar een reel aan moet voldoen

1. **Hook in de eerste seconde**, in beeld én in woorden. Geen intro, geen "hoi allemaal".
2. **Eén idee per reel.** Twee ideeën zijn twee reels.
3. **Elke 2–4 seconden iets nieuws**: snede, zoom, kop of caption-wissel.
4. **Geluid uit moet werken**: alles wat telt staat als tekst in beeld.
5. **Captions in het midden, niet onderaan**, want onderaan zit het platform.
6. **Houd de laatste seconde leeg of de CTA**, niet beide.
7. **Kort eindigen**: stop zodra het punt gemaakt is.

## Storyboard-sleutels voor praatreels

```yaml
captions: woord              # woord | zin (zin = gewone ondertitels)
captions_hoogte: 0.64        # 0 = boven, 1 = onder (veilige zone wordt gerespecteerd)
captions_grootte: 1.0
captions_caps: ja
autozoom: normaal            # geen | weinig | normaal | veel
zoom_midden: [540, 800]      # waar het gezicht staat, in uitvoerpixels
geluid: ja
koppen:
  - { van: 0:04, tot: 0:07, tekst: "De fout die iedereen maakt" }
```
