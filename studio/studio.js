/* ══════════════════════════════════════════════════════════════════
   studio.js — de logica achter de interface.

   Eén regel houdt alles bij elkaar: het storyboard is de waarheid. Elke
   klik verandert het object `S.sb`, dat wordt bewaard als storyboard.yaml,
   en alle beelden komen van de server die datzelfde bestand rendert. Zo
   kan de studio niets tonen wat de render niet zou maken.
   ══════════════════════════════════════════════════════════════════ */
"use strict";

const $ = (id) => document.getElementById(id);
// een | in een titel dwingt een regeleinde af in de video; in de interface
// tonen we hem als spatie, anders lees je een streepje midden in je titel
const leesbaar = (t) => String(t == null ? "" : t).replace(/\|/g, " ");
const S = {
  start: null,       // formaten, merken, lessen
  les: null,         // naam van de open les
  sb: null,          // het storyboard
  duur: 0,
  bronruimte: [1920, 1080],
  clips: [],         // de opnames waaruit deze les bestaat
  t: 0,              // huidige tijd in de opname
  kandidaten: [],    // gekozen opnames voor een nieuwe les, in volgorde
  doel: null,        // tutorial | reel | broll — de keuze bovenaan stap 1
  bewaartimer: null,
};

/* ── hulpjes ─────────────────────────────────────────────────── */
async function haal(url, opties) {
  let r;
  try {
    r = await fetch(url, opties);
  } catch (e) {
    // "Failed to fetch" betekent bijna altijd: de studio draait niet meer.
    // Het terminalvenster is dichtgegaan, of er werd Ctrl-C gedrukt. Zeg dat,
    // in plaats van een browsermelding waar niemand iets aan heeft.
    toonServerWeg();
    throw new Error("De studio is gestopt. Start hem opnieuw in Terminal met "
                    + "./tutorial.sh studio en herlaad deze pagina.");
  }
  const type = r.headers.get("content-type") || "";
  if (!type.includes("json")) return r;
  const d = await r.json();
  if (d && d.fout) throw new Error(d.fout);
  return d;
}
function toonServerWeg() {
  if (document.getElementById("serverweg")) return;
  const b = document.createElement("div");
  b.id = "serverweg";
  b.innerHTML = "<strong>De studio is gestopt.</strong> Je browser praat tegen "
    + "een server die niet meer draait. Start hem opnieuw in Terminal:"
    + "<code>cd ~/Reelstudio &amp;&amp; ./tutorial.sh studio</code>"
    + "en klik dan hier: <button onclick=\"location.reload()\">Pagina herladen</button>";
  document.body.prepend(b);
}

const post = (url, body) =>
  haal(url, { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body || {}) });

function tijd(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r < 10 ? "0" : ""}${r.toFixed(1)}`;
}
function tijdKort(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s - m * 60)).padStart(2, "0")}`;
}
function ontleedTijd(v) {
  if (v === undefined || v === null) return 0;
  if (typeof v === "number") return v;
  const d = String(v).split(":").map(parseFloat);
  return d.reduce((a, b) => a * 60 + b, 0);
}
let toastTimer;
function melding(tekst, fout) {
  const t = $("toast");
  t.textContent = tekst;
  t.className = "toast" + (fout ? " fout" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), fout ? 7000 : 3200);
}

/* ── stappen ─────────────────────────────────────────────────── */
function toonStap(n) {
  n = Number(n);        // de navigatie geeft een string mee
  document.querySelectorAll(".stap").forEach((s) => s.classList.remove("aan"));
  $("stap" + n).classList.add("aan");
  document.querySelectorAll("#stappen button").forEach((b) =>
    b.classList.toggle("aan", b.dataset.stap === String(n)));
  if (n === 2) ververVoorbeeld();
  if (n === 3) { ververBeeld(); tekenElementen(); }
}
document.querySelectorAll("#stappen button").forEach((b) =>
  b.onclick = () => {
    if (b.dataset.stap !== "1" && !S.les) return melding("Kies eerst een video.", true);
    toonStap(b.dataset.stap);
  });

function zetStappenAan(aan) {
  document.querySelectorAll('#stappen button:not([data-stap="1"])')
    .forEach((b) => (b.disabled = !aan));
}

/* ══ 1. VIDEO ═════════════════════════════════════════════════ */
async function beginnen() {
  S.start = await haal("/api/start");
  $("omgeving").innerHTML =
    `<span>ffmpeg <b class="${S.start.ffmpeg ? "ja" : "nee"}">${S.start.ffmpeg ? "klaar" : "ontbreekt"}</b></span>` +
    `<span>ondertitels <b class="${S.start.whisper ? "ja" : "nee"}">${S.start.whisper ? "automatisch" : "zelf schrijven"}</b></span>`;
  tekenKopmerk(S.start.standaardmerk);
  $("whispernoot").textContent = S.start.whisper
    ? "Ondertitels worden automatisch gemaakt. Dat duurt een paar minuten."
    : "Whisper staat niet geïnstalleerd, dus je schrijft de ondertitels zelf in ondertitels.srt. De rest werkt gewoon.";

  $("snel").innerHTML = "";
  S.start.snelkoppelingen.forEach((s) => {
    const b = document.createElement("button");
    b.textContent = s.naam;
    b.onclick = () => bladeren(s.pad);
    $("snel").appendChild(b);
  });
  tekenLessen();
  bladeren(S.start.snelkoppelingen[0] ? S.start.snelkoppelingen[0].pad : "~");
  zetStappenAan(false);
}

function tekenLessen() {
  const d = $("lessen");
  d.innerHTML = "";
  if (!S.start.lessen.length) {
    d.innerHTML = '<div class="leeg">Nog geen lessen.</div>';
    return;
  }
  S.start.lessen.forEach((l) => {
    const b = document.createElement("button");
    b.className = "les";
    b.innerHTML = `<span><b>${leesbaar(l.titel)}</b><small>${l.naam} · ${l.formaat} · ${l.merk}</small></span><span>→</span>`;
    b.onclick = () => openLes(l.naam).then(() => toonStap(2)).catch((e) => melding(e.message, true));
    d.appendChild(b);
  });
}

async function bladeren(pad) {
  try {
    const d = await haal("/api/map?pad=" + encodeURIComponent(pad));
    $("huidigepad").textContent = d.pad;
    const lijst = $("bladeren");
    lijst.innerHTML = "";
    if (d.ouder) lijst.appendChild(rij("⤴  hoger", () => bladeren(d.ouder)));
    d.mappen.forEach((m) => lijst.appendChild(rij("📁  " + m.naam, () => bladeren(m.pad))));
    d.videos.forEach((v) => lijst.appendChild(videoRij(v)));
    if (!d.mappen.length && !d.videos.length)
      lijst.innerHTML = '<div class="leeg">Geen mappen of video\'s hier.</div>';
  } catch (e) { melding(e.message, true); }
}
function rij(tekst, bijKlik, rechts, isVideo) {
  const el = document.createElement("div");
  el.className = "rij-item" + (isVideo ? " video" : "");
  el.innerHTML = `<span>${tekst}</span>` + (rechts ? `<small>${rechts}</small>` : "");
  el.onclick = bijKlik;
  return el;
}

/* ── videorijen met een voorbeeldbeeldje ──────────────────────
   "IMG_2345.mov" zegt niemand iets — je wil zíen welk filmpje het is.
   De beeldjes komen pas als de rij in beeld scrolt: in een map met
   vijftig video's zou alles tegelijk ophalen de studio dichttrekken. */
const miniKijker = new IntersectionObserver((items) => items.forEach((it) => {
  if (!it.isIntersecting) return;
  miniKijker.unobserve(it.target);
  if (it.target._laadMini) it.target._laadMini();
}), { rootMargin: "120px" });

function videoRij(v) {
  const el = document.createElement("div");
  el.className = "rij-item video";
  el.innerHTML = `<span class="mini leeg-mini">🎬</span>` +
    `<span class="vnaam">${v.naam}</span><small>${v.mb} MB</small>`;
  el.onclick = () => kiesVideo(v.pad);
  el._laadMini = async () => {
    try {
      const r = await fetch("/api/miniatuur?pad=" + encodeURIComponent(v.pad));
      if (!r.ok) return;
      const duur = parseFloat(r.headers.get("X-Duur") || "0");
      if (duur) el.querySelector("small").textContent = `${tijdKort(duur)} · ${v.mb} MB`;
      const img = document.createElement("img");
      img.className = "mini";
      img.alt = "";
      img.src = URL.createObjectURL(await r.blob());
      el.querySelector(".mini").replaceWith(img);
    } catch (e) { /* geen beeldje is geen ramp — de naam staat er nog */ }
  };
  miniKijker.observe(el);
  return el;
}

function kiesVideo(pad) {
  if (S.kandidaten.includes(pad)) return melding("Die opname staat er al bij.");
  S.kandidaten.push(pad);
  if (S.kandidaten.length === 1) {
    // de naam en titel volgen de eerste opname; daarna laten we ze met rust
    const basis = pad.split("/").pop().replace(/\.[^.]+$/, "");
    $("lesnaam").value = basis.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "");
    $("lestitel").value = basis.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  tekenKandidaten();
  pasDoelToe();
  const doelpaneel = S.doel === "broll" ? $("brollpaneel") : $("nieuwpaneel");
  doelpaneel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ── wat maak je vandaag? ─────────────────────────────────────
   De keuze bovenaan stuurt welk paneel je te zien krijgt en met welke
   instellingen een nieuwe les vertrekt. Nogmaals klikken zet ze weer uit
   en dan toont de studio gewoon beide panelen, zoals vroeger. */
document.querySelectorAll("#doelen .keuze").forEach((b) => {
  b.onclick = () => {
    S.doel = S.doel === b.dataset.doel ? null : b.dataset.doel;
    document.querySelectorAll("#doelen .keuze").forEach((k) =>
      k.classList.toggle("aan", S.doel === k.dataset.doel));
    pasDoelToe();
  };
});
function pasDoelToe() {
  const heeftVideo = S.kandidaten.length > 0;
  $("brollpaneel").hidden = !heeftVideo || S.doel === "tutorial" || S.doel === "reel";
  $("nieuwpaneel").hidden = !heeftVideo || S.doel === "broll";
}

$("broll_start").onclick = async () => {
  const hooks = $("broll_hooks").value.split("\n").map((r) => r.trim()).filter(Boolean);
  if (!hooks.length) return melding("Zet eerst je hooks in het tekstvak, één per regel.", true);
  if (!S.kandidaten.length) return melding("Kies eerst een of meer clips bij de video's hierboven.", true);
  $("broll_start").disabled = true;
  try {
    const r = await post("/api/broll", {
      hooks, bronnen: S.kandidaten,
      cta: $("broll_cta").value.trim(),
      stukjes: $("broll_stukjes").value,
      look: $("broll_look").value,
      merk: (S.sb && S.sb.merk) || (S.start && S.start.standaardmerk) || "",
    });
    await volgTaak(r.taak, r.aantal + " b-roll reels");
    S.start = await haal("/api/start");
    tekenLessen();
    melding("Klaar — je reels staan bij ‘Wat je al gemaakt hebt’.");
  } catch (e) { melding(e.message, true); }
  $("broll_start").disabled = false;
};

function tekenKandidaten() {
  const d = $("gekozenbestand");
  d.innerHTML = "";
  S.kandidaten.forEach((pad, i) => {
    const el = document.createElement("div");
    el.className = "clip";
    el.innerHTML = `<span class="nr">${i + 1}</span>` +
      `<span class="naam" title="${pad}">${pad.split("/").pop()}</span>` +
      `<button title="omhoog" ${i === 0 ? "disabled" : ""}>↑</button>` +
      `<button title="omlaag" ${i === S.kandidaten.length - 1 ? "disabled" : ""}>↓</button>` +
      `<button title="weghalen">×</button>`;
    const [op, neer, weg] = el.querySelectorAll("button");
    op.onclick = () => wissel(i, i - 1);
    neer.onclick = () => wissel(i, i + 1);
    weg.onclick = () => { S.kandidaten.splice(i, 1); tekenKandidaten(); };
    d.appendChild(el);
  });
  $("maakles").textContent = S.kandidaten.length > 1
    ? `${S.kandidaten.length} clips klaarzetten` : "Klaarzetten";
}

function wissel(a, b) {
  if (b < 0 || b >= S.kandidaten.length) return;
  [S.kandidaten[a], S.kandidaten[b]] = [S.kandidaten[b], S.kandidaten[a]];
  tekenKandidaten();
}
$("handknop").onclick = async () => {
  const p = $("handpad").value.trim();
  if (!p) return;
  try {
    const d = await haal("/api/bestand?pad=" + encodeURIComponent(p));
    if (!d.ok) return melding(d.reden, true);
    kiesVideo(d.pad);
  } catch (e) { melding(e.message, true); }
};

$("maakles").onclick = async () => {
  const naam = $("lesnaam").value.trim();
  if (!S.kandidaten.length || !naam) return melding("Kies een video en geef een naam.", true);
  $("maakles").disabled = true;
  try {
    const r = await post("/api/les", { bron: S.kandidaten, naam,
                                       titel: $("lestitel").value.trim(), overschrijf: true });
    await volgTaak(r.taak, "Klaarzetten");
    await openLes(r.naam);
    // de keuze bovenaan ("wat maak je vandaag?") bepaalt waarmee de les vertrekt
    if (S.doel === "reel") { S.sb.formaat = "reel"; S.sb.soort = "uitleg"; }
    if (S.doel === "tutorial") { S.sb.formaat = "liggend"; S.sb.soort = "tutorial"; }
    if (S.doel) { tekenFormaten(); tekenSoorten(); bewaar(); }
    toonStap(2);
  } catch (e) { melding(e.message, true); }
  $("maakles").disabled = false;
};

/* ── een taak volgen (transcriberen, renderen) ───────────────── */
function volgTaak(id, label, opVoortgang) {
  $("voortgang").hidden = false;
  $("voortlabel").textContent = label + " …";
  return new Promise((klaar, mis) => {
    const tik = async () => {
      let d;
      try { d = await haal("/api/taak/" + id); }
      catch (e) { return mis(e); }
      $("balk").style.width = Math.round(d.deel * 100) + "%";
      $("log").textContent = d.regels.join("\n");
      $("log").scrollTop = $("log").scrollHeight;
      if (opVoortgang) opVoortgang(d);
      if (!d.klaar) return setTimeout(tik, 700);
      $("voortlabel").textContent = d.fout ? "Mislukt" : label + " — klaar";
      if (d.fout) {
        // het voortgangsvak hangt onderaan stap 4; gaat er iets mis in stap 1,
        // dan staat het buiten beeld. Breng het naar de gebruiker toe.
        $("voortgang").scrollIntoView({ behavior: "smooth", block: "center" });
        mis(new Error(d.fout));
      } else klaar(d);
    };
    tik();
  });
}

/* ══ 2. STIJL ═════════════════════════════════════════════════ */
async function openLes(naam) {
  const d = await haal("/api/les/" + encodeURIComponent(naam));
  S.les = naam;
  S.sb = d.storyboard || {};
  S.duur = d.duur;
  S.bronruimte = d.bronruimte;
  S.clips = d.clips || [];
  toonSubhulp(d.ondertitels || 0);
  laadSubs();
  S.t = Math.min(2, S.duur / 3);
  zetStappenAan(true);
  tekenFormaten();
  tekenSoorten();
  tekenLooks();
  tekenMerken();
  tekenKopmerk(S.sb.merk || S.start.standaardmerk);
  tekenKaders();
  vulTekstvelden();
  $("tijd").max = S.duur;
  $("v_tijd").max = S.duur;
  $("tijd").value = S.t;
  $("v_tijd").value = S.t;
  $("tijdlabel").textContent = tijdKort(S.t);
  $("v_tijdlabel").textContent = tijdKort(S.t);
  document.title = `${leesbaar(S.sb.titel) || naam} — studio`;
  if (!d.ondertitels)
    melding("Deze les heeft nog geen ondertitels — de rest werkt gewoon.");
}

function tekenKopmerk(naam) {
  // De kop draagt het merk van wie de studio gebruikt — bij Lien ASKLIEN.ai,
  // bij een klant hún wordmark. "Reelstudio" wordt de bescheiden achternaam.
  const m = (S.start.merken || []).find((x) => x.naam === naam) || null;
  const d = $("kopmerk");
  if (!m) { d.textContent = "Reelstudio"; return; }
  let wm = m.wordmark || m.titel || "Reelstudio";
  let gedempt = m.wordmark_gedempt;
  if (!m.wordmark_accent && !gedempt) {
    const punt = wm.lastIndexOf(".");
    if (punt > 0) gedempt = wm.slice(punt);
  }
  const stuk = (tekst, kleur) => tekst
    ? `<span style="color:${kleur}">${tekst.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</span>` : "";
  let html = "", rest = wm;
  if (m.wordmark_accent) {
    const i = rest.toLowerCase().indexOf(m.wordmark_accent.toLowerCase());
    if (i >= 0) {
      html += stuk(rest.slice(0, i), "inherit") + stuk(rest.slice(i, i + m.wordmark_accent.length), m.accent);
      rest = rest.slice(i + m.wordmark_accent.length);
    }
  }
  if (gedempt && rest.toLowerCase().endsWith(gedempt.toLowerCase())) {
    html += stuk(rest.slice(0, rest.length - gedempt.length), "inherit")
          + stuk(rest.slice(rest.length - gedempt.length), "#9aa1ab");
  } else {
    html += stuk(rest, "inherit");
  }
  d.innerHTML = html + ' <small style="opacity:.45;font-weight:500">· Reelstudio</small>';
}

function tekenLooks() {
  const huidig = S.sb.look || "naturel";
  document.querySelectorAll("#looks button").forEach((b) => {
    b.classList.toggle("aan", b.dataset.look === huidig);
    b.onclick = () => { S.sb.look = b.dataset.look; tekenLooks(); bewaar(); };
  });
}

function tekenSoorten() {
  const huidig = S.sb.soort || "tutorial";
  document.querySelectorAll("#soorten button").forEach((b) => {
    b.classList.toggle("aan", b.dataset.soort === huidig);
    b.onclick = () => { S.sb.soort = b.dataset.soort; tekenSoorten(); bewaar(); };
  });
}

function tekenFormaten() {
  const d = $("formaten");
  d.innerHTML = "";
  const uitleg = {
    liggend: "Voor YouTube en je lesplatform.",
    reel: "Staand voor Instagram, met hook en eindkaart.",
    vierkant: "Voor een feed-post.",
  };
  S.start.formaten.forEach((f) => {
    const b = document.createElement("button");
    b.className = "keuze" + ((S.sb.formaat || "liggend") === f.naam ? " aan" : "");
    const h = 46, w = Math.round((f.breedte / f.hoogte) * h);
    b.innerHTML = `<span class="vorm" style="width:${w}px;height:${h}px"></span>` +
      `<b>${f.naam}</b><span>${f.breedte}×${f.hoogte} — ${uitleg[f.naam] || ""}</span>`;
    b.onclick = () => { S.sb.formaat = f.naam; tekenFormaten(); bewaar(); };
    d.appendChild(b);
  });
}

function tekenMerken() {
  const d = $("merken");
  d.innerHTML = "";
  const huidig = S.sb.merk || S.start.standaardmerk;
  S.start.merken.forEach((m) => {
    const b = document.createElement("button");
    b.className = "keuze" + (huidig === m.naam ? " aan" : "");
    b.innerHTML = `<span class="staal"><i style="background:${m.creme}"></i>` +
      `<i style="background:${m.ink}"></i><i style="background:${m.accent}"></i></span>` +
      `<b>${m.naam}</b><span>${m.wordmark}</span>`;
    b.onclick = () => { S.sb.merk = m.naam; tekenMerken(); tekenKopmerk(m.naam); bewaar(); };
    d.appendChild(b);
  });
}

function tekenKaders() {
  const huidig = S.sb.kader || "auto";
  document.querySelectorAll("#kaders .keuze").forEach((b) => {
    b.classList.toggle("aan", b.dataset.kader === huidig);
    b.onclick = () => { S.sb.kader = b.dataset.kader; tekenKaders(); bewaar(); };
  });
}

function vulTekstvelden() {
  $("v_titel").value = S.sb.titel || "";
  $("v_hook").value = S.sb.hook || "";
  $("v_outrotitel").value = S.sb.outro_titel || "";
  $("v_cta").value = S.sb.outro_volgende || "";
  $("v_intro").checked = S.sb.intro !== false && S.sb.intro !== "nee";
  $("v_outro").checked = S.sb.outro !== false && S.sb.outro !== "nee";
}
const koppel = (id, sleutel) => {
  $(id).oninput = () => { S.sb[sleutel] = $(id).value; bewaar(); };
};
koppel("v_titel", "titel");
koppel("v_hook", "hook");
koppel("v_outrotitel", "outro_titel");
koppel("v_cta", "outro_volgende");
$("v_intro").onchange = () => { S.sb.intro = $("v_intro").checked; bewaar(); };
$("v_outro").onchange = () => { S.sb.outro = $("v_outro").checked; bewaar(); };

/* ── bewaren en verversen ────────────────────────────────────── */
// Elke wijziging schrijft het storyboard weg en vraagt een nieuw voorbeeld.
// Even wachten voorkomt dat elke aanslag een render start.
function bewaar(stil) {
  clearTimeout(S.bewaartimer);
  S.bewaartimer = setTimeout(async () => {
    try {
      await post("/api/les/" + encodeURIComponent(S.les), { storyboard: S.sb });
      if (!stil && $("stap2").classList.contains("aan")) ververVoorbeeld();
    } catch (e) { melding(e.message, true); }
  }, 450);
}

let voorbeeldTeller = 0;
async function ververVoorbeeld() {
  if (!S.les) return;
  const mijn = ++voorbeeldTeller;
  $("voorbeeldbezig").hidden = false;
  try {
    const r = await fetch(`/api/voorbeeld/${encodeURIComponent(S.les)}?t=${S.t}&c=${Date.now()}`);
    if (mijn !== voorbeeldTeller) return;
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.fout || "voorbeeld mislukt");
    }
    const blob = await r.blob();
    $("voorbeeld").src = URL.createObjectURL(blob);
    let w = [];
    try { w = JSON.parse(r.headers.get("X-Waarschuwingen") || "[]"); } catch (e) {}
    $("v_meldingen").innerHTML = w.map((x) => `<div class="melding">${x}</div>`).join("");
  } catch (e) {
    melding(e.message, true);
  } finally {
    if (mijn === voorbeeldTeller) $("voorbeeldbezig").hidden = true;
  }
}
$("v_tijd").oninput = () => {
  S.t = parseFloat($("v_tijd").value);
  $("v_tijdlabel").textContent = tijdKort(S.t);
};
$("v_tijd").onchange = ververVoorbeeld;

let subsTimer = null;
S.subs = [];

async function laadSubs() {
  try {
    const d = await haal("/api/ondertitels/" + encodeURIComponent(S.les));
    S.subs = d.cues || [];
  } catch (e) { S.subs = []; }
  tekenSubs();
}

function tekenSubs() {
  const d = $("subs");
  d.innerHTML = "";
  $("subsuitleg").textContent = S.subs.length
    ? "Klik op een zin om ze te verbeteren. Leegmaken haalt ze weg. Tijden blijven staan."
    : "Nog geen ondertitels — maak ze in stap 2, of schrijf ondertitels.srt.";
  S.subs.forEach((c, i) => {
    const el = document.createElement("div");
    el.className = "item";
    const tijdEl = document.createElement("span");
    tijdEl.className = "tijd";
    tijdEl.textContent = tijdKort(c.van);
    tijdEl.title = "spring naar dit moment";
    tijdEl.onclick = () => springNaar(c.van);
    const inp = document.createElement("input");
    inp.value = c.tekst;
    inp.oninput = () => {
      S.subs[i].tekst = inp.value;
      clearTimeout(subsTimer);
      subsTimer = setTimeout(bewaarSubs, 800);
    };
    el.append(tijdEl, inp);
    d.appendChild(el);
  });
}

async function bewaarSubs() {
  try {
    await post("/api/ondertitels/" + encodeURIComponent(S.les), { cues: S.subs });
    melding("Ondertitels bewaard.");
  } catch (e) { melding(e.message, true); }
}

function toonSubhulp(aantal) {
  const kan = S.start && S.start.whisper;
  $("subhulp").hidden = aantal > 0;
  if (aantal > 0) return;
  $("subhulptekst").textContent = kan
    ? "Deze video heeft nog geen ondertitels."
    : "Nog geen ondertitels, en whisper staat niet op deze computer. "
      + "Installeer het met ./installeer.sh in Terminal, of schrijf ze zelf in ondertitels.srt.";
  $("subknop").hidden = !kan;
}

$("subknop").onclick = async () => {
  $("subknop").disabled = true;
  try {
    const r = await post("/api/transcribeer/" + encodeURIComponent(S.les));
    await volgTaak(r.taak, "Ondertitels maken");
    await openLes(S.les);
    melding("Ondertitels staan klaar — lees ze even na in stap 3.");
  } catch (e) { melding(e.message, true); }
  $("subknop").disabled = false;
};

/* ══ 3. AANWIJZEN ═════════════════════════════════════════════ */
async function ververBeeld() {
  if (!S.les) return;
  $("beeldbezig").hidden = false;
  $("beeld").src = `/api/frame/${encodeURIComponent(S.les)}?t=${S.t}&c=${Date.now()}`;
  $("tijdlabel").textContent = tijdKort(S.t);
  tekenClipbalk();
}
$("beeld").onload = () => ($("beeldbezig").hidden = true);
$("beeld").onerror = () => ($("beeldbezig").hidden = true);

$("tijd").oninput = () => {
  S.t = parseFloat($("tijd").value);
  $("tijdlabel").textContent = tijdKort(S.t);
};
$("tijd").onchange = ververBeeld;
$("stap_terug").onclick = () => springNaar(S.t - 1);
$("stap_vooruit").onclick = () => springNaar(S.t + 1);
function springNaar(t) {
  S.t = Math.max(0, Math.min(S.duur, t));
  $("tijd").value = S.t;
  $("v_tijd").value = S.t;
  ververBeeld();
}

/* ── slepen om een gebied aan te wijzen ──────────────────────── */
(() => {
  const houder = $("beeldhouder"), sel = $("selectie");
  let begin = null;
  const punt = (e) => {
    const r = $("beeld").getBoundingClientRect();
    return { x: Math.max(0, Math.min(r.width, e.clientX - r.left)),
             y: Math.max(0, Math.min(r.height, e.clientY - r.top)), r };
  };
  houder.addEventListener("pointerdown", (e) => {
    if (!S.les) return;
    begin = punt(e);
    houder.setPointerCapture(e.pointerId);
    sel.hidden = false;
    Object.assign(sel.style, { left: begin.x + "px", top: begin.y + "px",
                               width: "0px", height: "0px" });
  });
  houder.addEventListener("pointermove", (e) => {
    if (!begin) return;
    const p = punt(e);
    Object.assign(sel.style, {
      left: Math.min(begin.x, p.x) + "px", top: Math.min(begin.y, p.y) + "px",
      width: Math.abs(p.x - begin.x) + "px", height: Math.abs(p.y - begin.y) + "px" });
  });
  houder.addEventListener("pointerup", (e) => {
    if (!begin) return;
    const p = punt(e);
    const b = { x: Math.min(begin.x, p.x), y: Math.min(begin.y, p.y),
                w: Math.abs(p.x - begin.x), h: Math.abs(p.y - begin.y) };
    begin = null;
    sel.hidden = true;
    if (b.w < 12 || b.h < 12) return;              // een klik, geen sleep
    // van beeldpixels naar broncoördinaten van de clip die nu in beeld is
    const s = bronruimteOp(S.t)[0] / p.r.width;
    const gebied = [b.x * s, b.y * s, b.w * s, b.h * s].map((v) => Math.round(v));
    const tekst = prompt("Wat staat hier? (label bij de highlight)", "Klik hier");
    if (tekst === null) return;
    (S.sb.highlights = S.sb.highlights || []).push({
      van: tijd(S.t), tot: tijd(Math.min(S.duur, S.t + 3)), gebied,
      tekst: tekst || undefined });
    sorteer("highlights");
    tekenElementen();
    bewaar(true);
    melding("Highlight toegevoegd.");
  });
})();

function tekenClipbalk() {
  const d = $("clipbalk");
  d.innerHTML = "";
  if (S.clips.length < 2) return;      // bij één opname zegt een balk niets
  const nu = clipOp(S.t);
  S.clips.forEach((c) => {
    const el = document.createElement("div");
    el.style.flex = String(Math.max(0.5, c.einde - c.start));
    el.className = c === nu ? "aan" : "";
    el.textContent = c.naam;
    el.title = `${c.naam} · ${c.breedte}×${c.hoogte} · ${tijdKort(c.start)}–${tijdKort(c.einde)}`
             + (c.geluid ? "" : " · zonder geluid");
    el.onclick = () => springNaar(c.start + 0.3);
    d.appendChild(el);
  });
}

function clipOp(t) {
  return S.clips.find((c) => t < c.einde - 0.001) || S.clips[S.clips.length - 1];
}
function bronruimteOp(t) {
  const c = clipOp(t);
  return (c && c.bronruimte) || S.bronruimte;
}

function sorteer(sleutel) {
  (S.sb[sleutel] || []).sort((a, b) => ontleedTijd(a.van) - ontleedTijd(b.van));
}

$("voeg_stap").onclick = () => {
  const titel = prompt("Wat gebeurt er in deze stap?", "");
  if (!titel) return;
  (S.sb.stappen = S.sb.stappen || []).push({ van: tijd(S.t), titel });
  sorteer("stappen"); tekenElementen(); bewaar(true);
};
$("voeg_tip").onclick = () => {
  const tekst = prompt("De tip (één zin)", "");
  if (!tekst) return;
  (S.sb.tips = S.sb.tips || []).push({ van: tijd(S.t), tekst, duur: 6 });
  sorteer("tips"); tekenElementen(); bewaar(true);
};
$("voeg_prompt").onclick = () => {
  const titel = prompt("Titel van de prompt", "");
  if (!titel) return;
  const lijst = (S.sb.prompts = S.sb.prompts || []);
  lijst.push({ van: tijd(S.t), nummer: lijst.length + 1, titel });
  sorteer("prompts"); tekenElementen(); bewaar(true);
};
let knipStart = null;
$("voeg_knip").onclick = () => {
  if (knipStart === null) {
    knipStart = S.t;
    $("voeg_knip").textContent = "✂ … tot hier (op " + tijdKort(knipStart) + " begonnen)";
    $("voeg_knip").classList.add("aan");
    melding("Schuif nu naar waar het stuk moet eindigen en klik nog eens.");
    return;
  }
  const a = Math.min(knipStart, S.t), b = Math.max(knipStart, S.t);
  knipStart = null;
  $("voeg_knip").textContent = "✂ Knip vanaf hier";
  $("voeg_knip").classList.remove("aan");
  if (b - a < 0.2) return melding("Begin en einde liggen op hetzelfde moment.", true);
  (S.sb.knip = S.sb.knip || []).push({ van: tijd(a), tot: tijd(b) });
  sorteer("knip"); tekenElementen(); bewaar(true);
  melding("Stuk van " + tijdKort(a) + " tot " + tijdKort(b) + " wordt weggeknipt.");
};

$("toon_voorbeeld").onclick = () => { toonStap(2); $("v_tijd").value = S.t; ververVoorbeeld(); };

const SOORTEN = [["knip", "knip"], ["stappen", "stap"], ["highlights", "highlight"],
                 ["tips", "tip"], ["prompts", "prompt"]];

function tekenElementen() {
  const d = $("elementen");
  d.innerHTML = "";
  let n = 0;
  SOORTEN.forEach(([sleutel, label]) => {
    (S.sb[sleutel] || []).forEach((it, i) => {
      n++;
      const el = document.createElement("div");
      el.className = "item";
      const tekst = sleutel === "knip"
        ? "weg tot " + tijdKort(ontleedTijd(it.tot))
        : (it.tekst || it.titel || "(zonder tekst)");
      el.innerHTML = `<span class="soort">${label}</span>` +
        `<span class="tijd">${tijdKort(ontleedTijd(it.van))}</span>` +
        `<span class="tekst" title="${tekst}">${tekst}</span>` +
        `<button class="weg" title="verwijderen">×</button>`;
      el.querySelector(".tijd").onclick = () => springNaar(ontleedTijd(it.van));
      el.querySelector(".tekst").onclick = () => {
        if (sleutel === "knip") return;
        const v = prompt("Tekst aanpassen", tekst);
        if (v === null) return;
        if (it.tekst !== undefined || sleutel === "tips") it.tekst = v; else it.titel = v;
        tekenElementen(); bewaar(true);
      };
      el.querySelector(".weg").onclick = () => {
        S.sb[sleutel].splice(i, 1);
        tekenElementen(); bewaar(true);
      };
      d.appendChild(el);
    });
  });
  if (!n) d.innerHTML = '<div class="leeg">Nog niets aangewezen. Sleep een kader ' +
    'over het beeld, of gebruik de knoppen eronder.</div>';
}

/* ══ 4. RENDEREN ══════════════════════════════════════════════ */
async function render(preview) {
  if (!S.les) return melding("Kies eerst een video.", true);
  $("render_preview").disabled = $("render_final").disabled = true;
  $("resultaat").innerHTML = "";
  try {
    const r = await post("/api/render/" + encodeURIComponent(S.les), { preview });
    const d = await volgTaak(r.taak, preview ? "Preview renderen" : "Eindrender");
    if (d.bestand) {
      const naam = d.bestand.split("/").pop();
      $("resultaat").innerHTML =
        `<video controls src="/uit/${encodeURIComponent(S.les)}/${encodeURIComponent(naam)}"></video>` +
        `<div class="pad-uit">${d.bestand}</div>`;
    }
    melding("Klaar.");
  } catch (e) { melding(e.message, true); }
  $("render_preview").disabled = $("render_final").disabled = false;
}
$("render_preview").onclick = () => render(true);
$("render_final").onclick = () => render(false);

/* ── starten ─────────────────────────────────────────────────── */
beginnen().catch((e) => melding("Kon niet starten: " + e.message, true));
