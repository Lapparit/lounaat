// Lähilounaat Tampere — sivun toiminnallisuus.
// Erillinen tiedosto, jotta sivun tietoturvasääntö (CSP) voi kieltää
// kaiken sivun sisään kirjoitetun JavaScriptin. Katso index.html.
const PAIVAT = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"];
const PAIVAT_LYHYT = ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"];
const PAIVAT_NIMI = ["Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai", "Lauantai", "Sunnuntai"];
// Ryhmien nimet — muokkaa vapaasti (kategoria-numero → otsikko)
const RYHMAT = { 1: "Ryhmä 1", 2: "Ryhmä 2", 3: "Ryhmä 3" };
const RYHMA_JARJESTYS = [1, 2, 3];
const ALUE_JARJESTYS = ["Hervanta", "Hermia", "Rusko", "Sääksjärvi", "Lahdesjärvi"];

const SVG_ULOS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>';
const SVG_TAHTI = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.8 6.2.9-4.5 4.4 1.1 6.3L12 17.4 6.4 20.4l1.1-6.3L3 9.7l6.2-.9z"/></svg>';

// ---------- Tila ----------
const tila = {
  data: null,
  paiva: null,       // 0-6
  alue: lueTallenne("alue", "kaikki"),
  haku: "",
  suosikit: new Set(lueTallenne("suosikit", [])),
};

function lueTallenne(avain, oletus) {
  try {
    const v = localStorage.getItem("lounaat." + avain);
    return v === null ? oletus : JSON.parse(v);
  } catch (e) { return oletus; }
}
function tallenna(avain, arvo) {
  try { localStorage.setItem("lounaat." + avain, JSON.stringify(arvo)); } catch (e) {}
}

// ---------- Apurit ----------
function tanaanIndeksi() {
  const js = new Date().getDay();
  return js === 0 ? 6 : js - 1;
}
function viikonMaanantai() {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - tanaanIndeksi());
  return d;
}
function paivanPvm(idx) {
  const d = viikonMaanantai();
  d.setDate(d.getDate() + idx);
  return `${d.getDate()}.${d.getMonth() + 1}.`;
}
function paivanIndeksi(teksti) {
  return teksti ? PAIVAT.indexOf(teksti.toLowerCase()) : -1;
}
function escapoi(t) {
  return String(t)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function muotoileAika(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const nyt = new Date();
    const sama = d.toDateString() === nyt.toDateString();
    const klo = d.toLocaleTimeString("fi-FI", { hour: "2-digit", minute: "2-digit" });
    if (sama) return `Päivitetty tänään ${klo}`;
    return "Päivitetty " + d.toLocaleDateString("fi-FI", { weekday: "short", day: "numeric", month: "numeric" }) + ` ${klo}`;
  } catch (e) { return iso; }
}
function korosta(teksti, q) {
  // Etsitään raakatekstistä ja merkitään vasta sen jälkeen. Näin osuma ei voi
  // katkaista HTML-merkintää kesken (esim. &amp;), ja jokainen pala menee
  // escapoi():n läpi.
  const t = String(teksti);
  if (!q) return escapoi(t);
  const i = t.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return escapoi(t);
  return escapoi(t.slice(0, i)) + "<mark>" + escapoi(t.slice(i, i + q.length)) +
         "</mark>" + escapoi(t.slice(i + q.length));
}

// Sallitaan linkkeihin vain tavalliset verkko-osoitteet. Esimerkiksi
// "javascript:"-alkuinen osoite suorittaisi koodia, jos se päätyisi dataan.
function turvallinenUrl(url) {
  const u = String(url || "").trim();
  return /^https?:\/\//i.test(u) ? u : "";
}
function onMenu(r) { return r.paivat && r.paivat.length > 0; }
function paivanTiedot(r, idx) {
  return (r.paivat || []).find(p => paivanIndeksi(p.paiva) === idx) || null;
}
function paivanRuoat(r, idx) {
  const p = paivanTiedot(r, idx);
  return p ? p.ruoat : null;
}

// ---------- Renderöinti ----------
function rendoiPaivaSirut() {
  const idx = tanaanIndeksi();
  const onLauantai = tila.data.ravintolat.some(r => paivanRuoat(r, 5));
  const nakyvat = onLauantai ? [0, 1, 2, 3, 4, 5] : [0, 1, 2, 3, 4];
  document.getElementById("paivat").innerHTML = nakyvat.map(i => `
    <button type="button" class="chip${i === idx ? " tanaan" : ""}" data-paiva="${i}"
            aria-pressed="${i === tila.paiva}" aria-label="${PAIVAT_NIMI[i]} ${paivanPvm(i)}">
      <span class="nimi">${PAIVAT_LYHYT[i]}</span><span class="pvm">${paivanPvm(i)}</span>
    </button>`).join("");
}

function rendoiAlueSirut() {
  const alueet = [...new Set(tila.data.ravintolat.map(r => r.alue).filter(Boolean))]
    .sort((a, b) => {
      const ia = ALUE_JARJESTYS.indexOf(a), ib = ALUE_JARJESTYS.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b, "fi");
    });
  const kaikki = [["kaikki", "Kaikki"], ...alueet.map(a => [a, a])];
  if (tila.suosikit.size) kaikki.splice(1, 0, ["suosikit", "★ Suosikit"]);
  if (!kaikki.some(([k]) => k === tila.alue)) tila.alue = "kaikki";
  document.getElementById("alueet").innerHTML = kaikki.map(([k, n]) => `
    <button type="button" class="chip" data-alue="${escapoi(k)}" aria-pressed="${k === tila.alue}">
      <span class="nimi">${escapoi(n)}</span>
    </button>`).join("");
}

function rendoiIlmoitus() {
  const el = document.getElementById("ilmoitus");
  const idx = tanaanIndeksi();
  const viestit = [];
  if (idx >= 5) {
    viestit.push("Viikonloppu: näytetään kuluneen viikon listat. Uudet listat päivittyvät maanantaiaamuna.");
  }
  const paivitetty = new Date(tila.data.paivitetty);
  if (!isNaN(paivitetty) && (Date.now() - paivitetty) > 2 * 24 * 3600 * 1000 && idx < 5) {
    viestit.push("Tietoja ei ole päivitetty yli kahteen päivään — listat voivat olla vanhoja.");
  }
  el.hidden = viestit.length === 0;
  el.innerHTML = viestit.map(v => `<p>${escapoi(v)}</p>`).join("");
}

function siistiRivi(r) {
  // "MAKKARAPANNU" → "Makkarapannu" (vain jos koko rivi on isoilla kirjaimilla)
  const kirjaimet = r.replace(/[^A-Za-zÄÖÅäöå]/g, "");
  if (kirjaimet.length >= 4 && kirjaimet === kirjaimet.toUpperCase()) {
    return r.charAt(0).toUpperCase() + r.slice(1).toLowerCase();
  }
  return r;
}

function paivamaara(iso) {
  try {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return "· " + d.toLocaleDateString("fi-FI", { day: "numeric", month: "numeric" });
  } catch (e) { return ""; }
}

function rendoiOsastot(osastot, q) {
  return osastot.map(o => {
    const otsikko = o.nimi ? `<li class="valiotsikko">${escapoi(o.nimi)}</li>` : "";
    return otsikko + rendoiRuoat(o.ruoat, q);
  }).join("");
}

function rendoiRuoat(ruoat, q) {
  return ruoat.map(rivi => {
    // "– riisiä" tai "- Salaattijuustoa" → edellisen ruoan alarivi
    const ala = /^[–\-•]\s*(.+)$/.exec(rivi);
    if (ala) return `<li class="alarivi">${korosta(siistiRivi(ala[1]), q)}</li>`;
    const r = siistiRivi(rivi);
    // "Keitto: Pinaattikeittoa" → pieni osastonimi + teksti
    const m = /^([A-ZÄÖÅ][\wÄÖÅäöå .\-]{1,22}):\s+(.+)$/.exec(r);
    if (m) {
      return `<li class="osasto"><span class="osasto-nimi">${escapoi(m[1])}</span>${korosta(m[2], q)}</li>`;
    }
    return `<li>${korosta(r, q)}</li>`;
  }).join("");
}

function rendoiKortti(r, q) {
  const suosikki = tila.suosikit.has(r.nimi);
  const ruoat = paivanRuoat(r, tila.paiva);
  const linkkiVain = !onMenu(r);

  const tahti = `
    <button type="button" class="tahti" data-suosikki="${escapoi(r.nimi)}"
            aria-pressed="${suosikki}" aria-label="${suosikki ? "Poista suosikeista" : "Lisää suosikiksi"}: ${escapoi(r.nimi)}"
            title="${suosikki ? "Poista suosikeista" : "Lisää suosikiksi"}">${SVG_TAHTI}</button>`;

  const vanhaMerkki = r.vanhentunut
    ? `<span class="vanha" title="Lista ei päivittynyt viimeisimmässä haussa — tarkista ravintolan sivu">
         Ei päivittynyt${r.paivitetty ? " " + paivamaara(r.paivitetty) : ""}</span>`
    : "";

  const url = turvallinenUrl(r.url);
  const linkki = url
    ? `<a href="${escapoi(url)}" target="_blank" rel="noopener noreferrer">Ravintolan sivu ${SVG_ULOS}</a>`
    : "";

  const meta = `
    <div class="meta">
      <span>${escapoi(r.alue || "")}</span>
      ${linkki}
      ${vanhaMerkki}
    </div>`;

  let sisalto;
  if (linkkiVain) {
    const teksti = r.virhe
      ? `<p class="huom virhe">Listaa ei voitu hakea automaattisesti.</p>`
      : `<p class="huom">${escapoi(r.huom || "Lounaslistaa ei löytynyt.")}</p>`;
    sisalto = teksti + (url
      ? `<a class="linkkinappi" href="${escapoi(url)}" target="_blank" rel="noopener noreferrer">Avaa lounaslista ${SVG_ULOS}</a>`
      : "");
  } else if (ruoat) {
    const tiedot = paivanTiedot(r, tila.paiva);
    const sisus = tiedot.osastot && tiedot.osastot.length
      ? rendoiOsastot(tiedot.osastot, q)
      : rendoiRuoat(ruoat, q);
    sisalto = `<ul class="ruoat">${sisus}</ul>`;
  } else {
    sisalto = `<p class="huom">Ei listaa ${PAIVAT_NIMI[tila.paiva].toLowerCase().replace(/i$/, "ille").replace(/o$/, "olle")}.</p>`;
  }

  return `
    <article class="kortti${linkkiVain ? " tiivis" : ""}" data-nimi="${escapoi(r.nimi)}">
      <div class="kortti-ylä">
        <h3>${url
          ? `<a href="${escapoi(url)}" target="_blank" rel="noopener noreferrer">${korosta(r.nimi, q)}</a>`
          : korosta(r.nimi, q)}</h3>
        ${tahti}
      </div>
      ${meta}
      ${sisalto}
    </article>`;
}

function suodata(ravintolat) {
  const q = tila.haku.trim().toLowerCase();
  return ravintolat.filter(r => {
    if (tila.alue === "suosikit" && !tila.suosikit.has(r.nimi)) return false;
    if (tila.alue !== "kaikki" && tila.alue !== "suosikit" && r.alue !== tila.alue) return false;
    if (!q) return true;
    const ruoat = paivanRuoat(r, tila.paiva) || [];
    const teksti = (r.nimi + " " + (r.alue || "") + " " + ruoat.join(" ")).toLowerCase();
    return teksti.includes(q);
  });
}

function jarjesta(lista) {
  // Suosikit ensin, sitten listalliset, sitten linkkiravintolat; aakkosissa
  const arvo = r => (tila.suosikit.has(r.nimi) ? 0 : 2) + (onMenu(r) ? 0 : 1);
  return [...lista].sort((a, b) => arvo(a) - arvo(b) || a.nimi.localeCompare(b.nimi, "fi"));
}

function rendoiLista() {
  const q = tila.haku.trim();
  const lista = document.getElementById("lista");
  const kaikki = suodata(tila.data.ravintolat);

  if (kaikki.length === 0) {
    lista.innerHTML = `
      <div class="tyhja">
        <p>Ei tuloksia${q ? ` haulle ”${escapoi(q)}”` : ""}${tila.alue !== "kaikki" ? " tällä rajauksella" : ""}.</p>
        <button type="button" id="nollaa">Näytä kaikki</button>
      </div>`;
    return;
  }

  const ryhmat = new Map();
  for (const r of kaikki) {
    const k = r.kategoria || 0;
    if (!ryhmat.has(k)) ryhmat.set(k, []);
    ryhmat.get(k).push(r);
  }
  const avaimet = [...RYHMA_JARJESTYS.filter(k => ryhmat.has(k)), ...[...ryhmat.keys()].filter(k => !RYHMA_JARJESTYS.includes(k))];

  lista.innerHTML = avaimet.map(k => {
    const rs = jarjesta(ryhmat.get(k));
    const otsikko = RYHMAT[k] || `Ryhmä ${k}`;
    return `
      <section class="ryhma">
        <h2 class="ryhma-otsikko">${escapoi(otsikko)} <span class="lkm">· ${rs.length}</span></h2>
        <div class="grid">${rs.map(r => rendoiKortti(r, q)).join("")}</div>
      </section>`;
  }).join("");
}

function rendoiKaikki() {
  rendoiPaivaSirut();
  rendoiAlueSirut();
  rendoiIlmoitus();
  rendoiLista();
}

// ---------- Tapahtumat ----------
function asetaTapahtumat() {
  document.getElementById("paivat").addEventListener("click", e => {
    const b = e.target.closest("[data-paiva]");
    if (!b) return;
    tila.paiva = Number(b.dataset.paiva);
    rendoiPaivaSirut();
    rendoiLista();
  });

  document.getElementById("alueet").addEventListener("click", e => {
    const b = e.target.closest("[data-alue]");
    if (!b) return;
    tila.alue = b.dataset.alue;
    tallenna("alue", tila.alue);
    rendoiAlueSirut();
    rendoiLista();
  });

  const haku = document.getElementById("haku");
  const tyhjenna = document.getElementById("tyhjenna");
  haku.addEventListener("input", () => {
    tila.haku = haku.value;
    tyhjenna.hidden = !haku.value;
    rendoiLista();
  });
  tyhjenna.addEventListener("click", () => {
    haku.value = "";
    tila.haku = "";
    tyhjenna.hidden = true;
    rendoiLista();
    haku.focus();
  });

  document.getElementById("lista").addEventListener("click", e => {
    const t = e.target.closest("[data-suosikki]");
    if (t) {
      const nimi = t.dataset.suosikki;
      if (tila.suosikit.has(nimi)) tila.suosikit.delete(nimi); else tila.suosikit.add(nimi);
      tallenna("suosikit", [...tila.suosikit]);
      rendoiAlueSirut();
      rendoiLista();
      return;
    }
    if (e.target.id === "nollaa") {
      tila.alue = "kaikki";
      tallenna("alue", tila.alue);
      tila.haku = "";
      haku.value = "";
      tyhjenna.hidden = true;
      rendoiAlueSirut();
      rendoiLista();
    }
  });
}

// ---------- Käynnistys ----------
async function lataa() {
  try {
    const r = await fetch("lounaat.json?t=" + Date.now());
    if (!r.ok) throw new Error("Ei löytynyt: " + r.status);
    tila.data = await r.json();

    document.getElementById("paivitetty").textContent = muotoileAika(tila.data.paivitetty);

    // Oletuspäivä: tänään arkena; lauantaina la jos listaa, muuten maanantai
    const idx = tanaanIndeksi();
    const onLauantai = tila.data.ravintolat.some(x => paivanRuoat(x, 5));
    tila.paiva = idx <= 4 ? idx : (idx === 5 && onLauantai ? 5 : 0);

    asetaTapahtumat();
    rendoiKaikki();
  } catch (e) {
    document.getElementById("lista").innerHTML =
      `<p class="tyhja">Virhe ladattaessa: ${escapoi(e.message)}<br>
      Tämä on normaalia, jos GitHub Actions ei ole vielä ajanut ensimmäistä kertaa.</p>`;
  }
}

lataa();
