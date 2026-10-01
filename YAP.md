# Praatreels (yap edits)

Je filmt jezelf, Reelstudio doet de montage. Film → `yap` → kijken → bijsturen → posten.

Liever begeleid? `./reelstudio.sh start` stelt de vragen en doet de rest. Cursusmateriaal om dit aan anderen te leren zit niet in de repo maar in het
betaalde pakket (`pakket --met-cursus`).

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
| **Versprekingen eruit** | "euh", dubbele woorden ("ik ik") en herstarts (je zegt een zin, begint opnieuw) worden uit de woordtiming gehaald; wat geknipt is staat in het storyboard (`--bewaar-versprekingen` zet het uit) |
| **Pauzes eruit** | stiltes ≥ 0,35 s worden weggeknipt, 0,12 s blijft staan zodat het menselijk blijft; stilte vooraan en achteraan verdwijnt helemaal (`--pauze`, `--drempel`) |
| **Captions per woord** | standaard één woord per keer (`--woorden 2` of `captions_woorden: 3` voor meer), het gesproken woord in je accentkleur, het gesproken woord in je accentkleur, groot en met rand (whisper per woord; zonder whisper schat hij de timing uit zinnen) |
| **Zoomsprongen** | op de sneden: zoom vlot in bij een nieuw stuk, hard terug bij de volgende snede (`--zoom geen|weinig|normaal|veel`) |
| **Hook** | één regel boven het beeld in de eerste 2,6 s |
| **Zachte achtergrond** | `achtergrond: zacht`: scherp in een ellips rond je gezicht, de rand wazig (geen persoonsherkenning; stel `zoom_midden` in als je gezicht niet in het midden staat) |
| **Graphics** | `graphics:` met `getal`, `vink` of `pijl`, geanimeerd en met pop-geluid |
| **Koppen** | headline-stickers (`koppen:` in het storyboard), schuin, in je accentkleur |
| **Geluid** | zachte whoosh bij elke zoomsprong, pop bij elke kop — gemaakt door ffmpeg zelf, geen bestanden nodig (`geluid: nee` zet het uit) |
| **Eindkaart** | jouw CTA in je merk, 3 s |
| **Helderder beeld** | `look: helder`: automatische niveaus, wat meer kleur en scherpte (trager renderen); `look: warm` voor een warmere huid |
| **Merk** | kleuren, lettertype, wordmark uit `merk/<naam>.yaml` |

Niet gedaan: de achtergrond vervangen of een persoon uitsnijden. Dat vraagt een segmentatiemodel en breekt de regel dat alles lokaal en zonder extra pakketten werkt. Dat vraagt een segmentatiemodel en
breekt de regel dat alles lokaal en zonder pakketten werkt. Een `look: warm` en een
net kader komen ver; wil je het toch, dan is dat een aparte stap vóór `yap`.

## Bijsturen in gewone taal

`./reelstudio.sh bijsturen <reel> "<zin>"` past het storyboard aan én schrijft het naar
`yap-voorkeuren.yaml`. Je volgende reel begint dus al met jouw smaak.

Herkend (NL en EN): één woord per keer / meer woorden · minder / meer / geen zooms · geen geluidseffecten · captions
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
achtergrond: zacht           # nee | zacht   (achtergrond_sterkte: 18)
look: helder                 # naturel | helder | warm
koppen:
  - { van: 0:04, tot: 0:07, tekst: "De fout die iedereen maakt" }
graphics:
  - { van: 0:10, tot: 0:12, type: getal, tekst: "3" }
  - { van: 0:14, tot: 0:17, type: vink, tekst: "Klaar in 5 min" }
  - { van: 0:18, tot: 0:20, type: pijl, x: 0.5, y: 0.4, tekst: "Kijk hier" }
```
