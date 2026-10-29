"use strict";
// Football Intelligence - the page. Reads the JSON built by app/build.py; everything else is computed here:
// candidate fit, TOPSIS ranking, weight stability, budget plan and the team shape response to a moved player.

const DATA = "data/";
const S = {
  index: null, pool: [], leagues: {}, league: null, team: null, club: null, players: new Map(),
  view: "lineup", bench: "top6", tab: "club", slot: null, player: null, group: null, pbench: "top6",
  base: null, fixed: {}, whatIf: {}, lastMoved: null, manager: 0, cand: null, compare: "player",
  filters: { maxAge: 29, maxPrice: 50, better: true, leagues: null },
  weights: null, budget: null, future: false, plan: null,
};
const SLOT_RU = {
  GK: "Вратарь", RB: "Правый защитник", RCB: "Правый центральный защитник", CB: "Центральный защитник",
  LCB: "Левый центральный защитник", LB: "Левый защитник", RWB: "Правый латераль", LWB: "Левый латераль",
  RDM: "Правый опорный полузащитник", CDM: "Опорный полузащитник", LDM: "Левый опорный полузащитник",
  RCM: "Правый центральный полузащитник", CM: "Центральный полузащитник", LCM: "Левый центральный полузащитник",
  RM: "Правый полузащитник", LM: "Левый полузащитник", RW: "Правый вингер", LW: "Левый вингер",
  RAM: "Правый атакующий полузащитник", CAM: "Атакующий полузащитник", LAM: "Левый атакующий полузащитник",
  RCF: "Правый нападающий", LCF: "Левый нападающий", ST: "Нападающий", SS: "Второй нападающий",
};
const BENCH_RU = { top6: "топ-6 своей лиги", league: "вся своя лига", europe: "все топ-5 лиг" };
const RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
const YD = 0.9144;   // StatsBomb units are yards

// ---------------------------------------------------------------- helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = (v, d = 0) => (v == null || Number.isNaN(v) ? "—" : Number(v).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d }));
const money = (v) => v == null ? "—" : v >= 1e6 ? `€${fmt(v / 1e6, v < 1e7 ? 1 : 0)} млн` : `€${fmt(v / 1e3)} тыс.`;
const surname = (n) => { if (!n) return ""; const p = n.split(" "); return n.length > 10 ? p[p.length - 1] : n; };
const label = (m) => S.index.metrics[m].label.split(" (")[0];
const P = (x, y) => [y, 120 - x];                      // team frame (attacking up) -> svg
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };

async function load(file) {
  const r = await fetch(DATA + file);
  if (!r.ok) throw new Error(`${file}: ${r.status}`);
  return r.json();
}

function mix(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("");
}
function divColor(score) {             // 0 weak (red) - 50 benchmark median (neutral) - 100 strong (blue)
  const stops = ["#b3261e", "#e34948", "#f3b8b3", css("--neutral") || "#f0efec", "#a9c8f0", "#2a78d6", "#184f95"];
  const t = clamp(score, 0, 100) / 100 * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t));
  return mix(stops[i], stops[i + 1], t - i);
}
const inkOn = (score) => score != null && Math.abs(score - 50) > 22 ? "#ffffff" : css("--text-primary");
function seqColor(v) { const t = clamp(v, 0, 1) * (RAMP.length - 1); const i = Math.min(RAMP.length - 2, Math.floor(t)); return mix(RAMP[i], RAMP[i + 1], t - i); }

const tip = $("#tip");
function showTip(e, html) { tip.innerHTML = html; tip.hidden = false; moveTip(e); }
function moveTip(e) {
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(window.innerWidth - w - 8, e.clientX + 14) + "px";
  tip.style.top = Math.min(window.innerHeight - h - 8, e.clientY + 14) + "px";
}
const hideTip = () => { tip.hidden = true; };

// ---------------------------------------------------------------- pitch drawing
function pitchMarkup(half = false, filled = true) {
  const L = `stroke="var(--pitch-line)" stroke-width=".35" fill="none"`;
  const top = half ? "" : `
    <rect x="18" y="0" width="44" height="18" ${L}/><rect x="30" y="0" width="20" height="6" ${L}/>
    <circle cx="40" cy="12" r=".45" fill="var(--pitch-line)"/><path d="M32,18 A10,10 0 0,0 48,18" ${L}/>
    <rect x="36" y="-1.6" width="8" height="1.6" ${L}/>`;
  return `<rect x="0" y="0" width="80" height="120" ${L} ${filled ? `style="fill:var(--pitch)"` : ""}/>
    <line x1="0" y1="60" x2="80" y2="60" ${L}/><circle cx="40" cy="60" r="10" ${L}/>
    <circle cx="40" cy="60" r=".45" fill="var(--pitch-line)"/>${top}
    <rect x="18" y="102" width="44" height="18" ${L}/><rect x="30" y="114" width="20" height="6" ${L}/>
    <circle cx="40" cy="108" r=".45" fill="var(--pitch-line)"/><path d="M32,102 A10,10 0 0,1 48,102" ${L}/>
    <rect x="36" y="120" width="8" height="1.6" ${L}/>`;
}
const arrowUp = `<g opacity=".55"><line x1="83" y1="70" x2="83" y2="50" stroke="var(--text-muted)" stroke-width=".35"/>
  <path d="M81.8,52 L83,49.5 L84.2,52" fill="none" stroke="var(--text-muted)" stroke-width=".35"/></g>`;

// ---------------------------------------------------------------- team shape model
function shapeModel() { return S.index.shape_models[S.club.formation]; }
function solve(A, b) {                                   // Gauss-Jordan with partial pivoting
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    const d = M[c][c] || 1e-9;
    for (let k = c; k <= n; k++) M[c][k] /= d;
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  return M.map((r) => r[n]);
}
function shape() {
  // E[all slots | pinned slots]: base + C[:,K] C[K,K]^-1 (pinned - base_K), the pinned ones exactly where put
  const base = S.base, keys = Object.keys(S.fixed).map(Number), m = shapeModel();
  if (!keys.length) return base.map((p) => [...p]);
  const out = base.map((p) => [...p]);
  if (m) {
    const C = m.cov, idx = keys.flatMap((i) => [2 * i, 2 * i + 1]);
    const d = keys.flatMap((i) => [S.fixed[i][0] - base[i][0], S.fixed[i][1] - base[i][1]]);
    const sol = solve(idx.map((a) => idx.map((b) => C[a][b])), d);
    out.forEach((p, j) => {
      p[0] += idx.reduce((s, a, t) => s + C[2 * j][a] * sol[t], 0);
      p[1] += idx.reduce((s, a, t) => s + C[2 * j + 1][a] * sol[t], 0);
    });
  }
  keys.forEach((i) => { out[i] = [...S.fixed[i]]; });
  return out.map(([x, y]) => [clamp(x, 1, 119), clamp(y, 1, 79)]);
}

// ---------------------------------------------------------------- views on the pitch
function slotName(slot) {
  const w = S.whatIf[slot.i];
  if (w) return { text: surname(w.name), cand: true };
  const p = slot.players[0] && S.players.get(slot.players[0][0]);
  return { text: p ? surname(p.name) : "—", cand: false };
}

function renderPitch() {
  const svg = $("#pitch");
  svg.onpointerdown = svg.onpointermove = svg.onpointerup = svg.onpointercancel = null;
  $$("#views button").forEach((b) => b.classList.toggle("on", b.dataset.view === S.view));
  if (S.view === "scored" || S.view === "conceded") return renderShots(svg, S.view === "scored");
  svg.setAttribute("viewBox", "-3 -3 89 126");
  if (S.view === "network") return renderNetwork(svg);
  renderLineup(svg);
}

function renderLineup(svg) {
  const moved = Object.keys(S.fixed).length > 0;
  const tools = $("#pitch-tools");
  tools.innerHTML = `<span>Цвет — сила позиции к:</span>
    <div class="seg small">${["top6", "league"].map((b) => `<button data-b="${b}" class="${S.bench === b ? "on" : ""}">${b === "top6" ? "топ-6 лиги" : "всей лиге"}</button>`).join("")}</div>
    ${moved || Object.keys(S.whatIf).length ? `<button class="ghost" id="reset">Сбросить расстановку</button>` : ""}`;
  $$("[data-b]", tools).forEach((b) => b.onclick = () => { S.bench = b.dataset.b; renderPitch(); });
  if ($("#reset")) $("#reset").onclick = () => { S.fixed = {}; S.whatIf = {}; S.lastMoved = null; renderPitch(); renderPanel(); };

  let photos = 0, shown = false;
  const nodes = S.club.slots.map((s, i) => {
    const score = s[`score_${S.bench}`], w = S.whatIf[i], nm = slotName(s);
    const fill = w ? css("--surface-1") : score == null ? css("--neutral") : divColor(score);
    const txt = w ? css("--text-primary") : inkOn(score);
    const sel = S.slot === i, pin = i in S.fixed && !w, num = w ? fmt(w.fit) : score == null ? "—" : fmt(score);
    const label = (y) => `<text y="${y}" text-anchor="middle" font-size="2" fill="${nm.cand ? "var(--series-1)" : "var(--text-primary)"}" font-weight="${nm.cand ? 700 : 500}" paint-order="stroke" stroke="var(--pitch)" stroke-width=".5">${esc(nm.text)}</text>`;
    const url = w ? null : slotPhoto(s);
    if (url) { photos++; shown ||= PHOTOS.get(url) === true; }
    // two looks: the score circle, and the player's photo with the score in a badge - shown once the photo has
    // loaded (loadPhotos), so without Transfermarkt the pitch stays as it was
    const r = FACE.r, iw = 2 * r * FACE.zoom, ih = iw * 181 / 139, bx = .8 * r, by = .73 * r;
    return `<g class="node${sel ? " sel" : ""}${PHOTOS.get(url) ? " pic" : ""}" data-i="${i}"${url ? ` data-photo="${esc(url)}"` : ""}>
      <g class="plain">
        <circle class="hit" r="5"/>
        ${s.need ? `<circle r="4" fill="none" stroke="var(--ring)" stroke-width=".5"/>` : ""}
        ${sel ? `<circle r="4.8" fill="none" stroke="var(--series-1)" stroke-width=".65"/>` : ""}
        ${pin ? `<circle r=".8" cx="2.6" cy="-2.6" fill="var(--text-secondary)"><title>закреплён</title></circle>` : ""}
        <circle r="3.1" fill="${fill}" stroke="${w ? "var(--series-1)" : "var(--surface-1)"}" stroke-width="${w ? ".65" : ".5"}" ${w ? `stroke-dasharray="1 .7"` : ""}/>
        <text y=".8" text-anchor="middle" font-size="2.3" font-weight="700" fill="${txt}">${num}</text>
        ${label(5.6)}
      </g>
      ${url ? `<g class="face">
        <circle class="hit" r="${r + 1.6}"/>
        ${s.need ? `<circle r="${r + .8}" fill="none" stroke="var(--ring)" stroke-width=".45"/>` : ""}
        ${sel ? `<circle r="${r + 1.5}" fill="none" stroke="var(--series-1)" stroke-width=".7"/>` : ""}
        ${pin ? `<circle r=".8" cx="${-.8 * r}" cy="${-.8 * r}" fill="var(--text-secondary)"><title>закреплён</title></circle>` : ""}
        <circle r="${r}" fill="var(--surface-2)"/>
        <image href="${esc(url)}" x="${-iw / 2}" y="${-FACE.cy * ih}" width="${iw}" height="${ih}" preserveAspectRatio="xMidYMin slice" clip-path="url(#face-clip)"/>
        <circle r="${r - .25}" fill="none" stroke="${fill}" stroke-width=".5"/>
        <rect x="${bx - 2.3}" y="${by - 2.3}" width="4.6" height="4.6" rx="2.3" fill="${fill}" stroke="var(--pitch)" stroke-width=".35"/>
        <text x="${bx}" y="${by + .8}" text-anchor="middle" font-size="2.3" font-weight="700" fill="${txt}">${num}</text>
        ${label(r + 3.2)}
      </g>` : ""}
    </g>`;
  }).join("");
  const clip = `<defs><clipPath id="face-clip"><circle r="${FACE.r}"/></clipPath></defs>`;
  svg.innerHTML = clip + pitchMarkup() + arrowUp + `<g id="ghosts"></g>` + nodes;
  place(svg, shape());
  bindDrag(svg);
  loadPhotos(svg);

  $("#pitch-legend").innerHTML = `
    <span><span class="dot" style="background:${divColor(15)}"></span> слабее</span>
    <span><span class="dot" style="background:${divColor(50)}; border:1px solid var(--line)"></span> медиана (${S.bench === "top6" ? "топ-6" : "лига"}) = 50</span>
    <span><span class="dot" style="background:${divColor(85)}"></span> сильнее</span>
    <span><svg width="14" height="14" viewBox="-7 -7 14 14"><circle r="5.5" fill="none" stroke="var(--ring)" stroke-width="1.2"/></svg> потребность</span>
    ${Object.keys(S.whatIf).length ? `<span><svg width="14" height="14" viewBox="-7 -7 14 14"><circle r="5" fill="none" stroke="var(--series-1)" stroke-width="1.4" stroke-dasharray="2 1.5"/></svg> кандидат «что если», число — соответствие</span>` : ""}
    ${photos ? `<span class="muted" id="photo-credit"${shown ? "" : " hidden"}>фото: Transfermarkt</span>` : ""}`;
  noteLineup();
}

// photo URL -> true (loaded), false (failed), null (loading)
const PHOTOS = new Map();
// a photo node on the pitch: radius in pitch yards, and the 139x181 portrait as wide as the circle, its centre
// at 47 % of the height - the whole face from hair to chin fits, with no empty edges (zoom < 1 leaves some)
const FACE = { r: 5.6, zoom: 1, cy: .47 };
function slotPhoto(s) {
  const url = s.players[0] && S.players.get(s.players[0][0])?.photo;
  return url && PHOTOS.get(url) !== false ? url : null;
}
function loadPhotos(svg) {
  // the browser fetches each photo once; a node switches to it only after it arrived
  $$(".node[data-photo]", svg).forEach((n) => {
    const url = n.dataset.photo;
    if (PHOTOS.has(url)) return;
    PHOTOS.set(url, null);
    const im = new Image();
    im.onload = () => {
      PHOTOS.set(url, true);
      const on = $$(".node[data-photo]", svg).filter((m) => m.dataset.photo === url);
      if (!on.length) return;                       // the pitch has moved on to another club or view
      on.forEach((m) => m.classList.add("pic"));
      $("#photo-credit")?.removeAttribute("hidden");
      place(svg, shape());                          // photos are bigger: spread the nodes a little more
    };
    im.onerror = () => PHOTOS.set(url, false);
    im.src = url;
  });
}

function noteLineup() {
  $("#pitch-note").innerHTML = S.lastMoved != null ? moveNote(shape()) :
    `Средние позиции игроков в схеме ${fmtFormation(S.club.formation)}. Нажмите на игрока — статистика и замены; перетащите — команда перестроится так, как в среднем стояли команды в реальных матчах.`;
}

function declutter(pts, w = 10.5, h = 7) {
  // display only: slots with almost the same average spot (a front two) would hide each other and their
  // names, so circles closer than a label's width side by side (or a node's height one above the other)
  // are pushed apart a little; the numbers behind them do not change
  const q = pts.map(([x, y]) => [x / w, y / h]);
  for (let it = 0; it < 60; it++) {
    let moved = false;
    for (let i = 0; i < q.length; i++) for (let j = i + 1; j < q.length; j++) {
      let dx = q[j][0] - q[i][0], dy = q[j][1] - q[i][1], d = Math.hypot(dx, dy);
      if (d >= 1) continue;
      if (d < 1e-3) { dx = 1; dy = 0; d = 1e-3; }
      const k = (1 - d) / 2 / d;
      q[i][0] -= dx * k; q[i][1] -= dy * k; q[j][0] += dx * k; q[j][1] += dy * k; moved = true;
    }
    if (!moved) break;
  }
  return q.map(([x, y]) => [x * w, y * h]);
}

function place(svg, pos) {
  // move the existing nodes (no re-render, so a drag in progress keeps its element) and redraw the ghosts
  let ghosts = "";
  const [w, h] = $(".node.pic", svg) ? [2.5 * FACE.r, 2.7 * FACE.r] : [10.5, 7];
  const shown = declutter(pos.map((p) => P(...p)), w, h), base = declutter(S.base.map((p) => P(...p)), w, h);
  S.club.slots.forEach((s, i) => {
    const [x, y] = shown[i], [bx, by] = base[i];
    $(`.node[data-i="${i}"]`, svg).setAttribute("transform", `translate(${x},${y})`);
    if (Math.hypot(pos[i][0] - S.base[i][0], pos[i][1] - S.base[i][1]) > 0.6) ghosts += `<circle class="ghost-dot" cx="${bx}" cy="${by}" r="3"/><line class="moved-line" x1="${bx}" y1="${by}" x2="${x}" y2="${y}"/>`;
  });
  $("#ghosts", svg).innerHTML = ghosts;
  // a node higher on the pitch is drawn later, so the name under it stays on top of the photo below
  const nodes = $$(".node", svg), want = [...nodes].sort((a, b) => shown[b.dataset.i][1] - shown[a.dataset.i][1]);
  if (want.some((n, k) => n !== nodes[k])) want.forEach((n) => svg.appendChild(n));
}

function moveNote(pos) {
  const i = S.lastMoved, s = S.club.slots[i];
  const d = pos.map((p, j) => [j, (p[0] - S.base[j][0]) * YD, (p[1] - S.base[j][1]) * YD]).filter(([j]) => j !== i && !(j in S.fixed));
  d.sort((a, b) => Math.hypot(b[1], b[2]) - Math.hypot(a[1], a[2]));
  const dir = (dx, dy) => [Math.abs(dx) >= 0.5 ? `${fmt(Math.abs(dx), 1)} м ${dx > 0 ? "вперёд" : "назад"}` : "",
                           Math.abs(dy) >= 0.5 ? `${fmt(Math.abs(dy), 1)} м ${dy > 0 ? "вправо" : "влево"}` : ""].filter(Boolean).join(", ");
  const top = d.slice(0, 3).filter(([, dx, dy]) => Math.hypot(dx, dy) >= 0.5).map(([j, dx, dy]) => `<b>${S.club.slots[j].code}</b> ${dir(dx, dy)}`);
  const m = shapeModel();
  return `${s.code} сдвинут. Сильнее всего с ним смещаются: ${top.join("; ") || "остальные почти не меняются"}.
    <span class="muted">Связь по ${m ? fmt(m.parts) : "—"} отрезкам матчей ${m ? m.teams : ""} команд со схемой ${fmtFormation(S.club.formation)}: так команды стояли, когда этот игрок стоял там. Это связь, а не причина.</span>`;
}
const fmtFormation = (f) => String(f).split("").join("-");

function bindDrag(svg) {
  let drag = null;
  const toPitch = (e) => {
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const q = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [clamp(120 - q.y, 1, 119), clamp(q.x, 1, 79)];
  };
  svg.onpointerdown = (e) => {
    const n = e.target.closest(".node"); if (!n) return;
    drag = { i: +n.dataset.i, start: toPitch(e), moved: false };
    svg.setPointerCapture(e.pointerId); hideTip(); e.preventDefault();
  };
  svg.onpointermove = (e) => {
    if (!drag) return;
    const p = toPitch(e);
    if (!drag.moved && Math.hypot(p[0] - drag.start[0], p[1] - drag.start[1]) < 1.2) return;
    drag.moved = true; S.fixed[drag.i] = p; S.lastMoved = drag.i;
    place(svg, shape()); noteLineup();
  };
  svg.onpointerup = (e) => {
    if (!drag) return;
    const d = drag; drag = null;
    if (svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
    if (d.moved) renderLineup(svg); else selectSlot(d.i);
  };
  svg.onpointercancel = () => { drag = null; };
  $$(".node", svg).forEach((n) => {
    n.addEventListener("mouseenter", (e) => { if (!drag) showTip(e, slotTip(+n.dataset.i)); });
    n.addEventListener("mousemove", (e) => { if (drag) hideTip(); else moveTip(e); });
    n.addEventListener("mouseleave", hideTip);
  });
}

function slotTip(i) {
  const s = S.club.slots[i];
  const ps = s.players.slice(0, 3).map(([id, m]) => `${esc(nameOf(id))} · ${fmt(m)}′`).join("<br>");
  return `<b>${s.code} · ${SLOT_RU[s.code] ?? s.code}</b><br>к топ-6: ${fmt(s.score_top6)} · к лиге: ${fmt(s.score_league)}
    ${s.need ? `<br><b>Потребность:</b> ${esc(s.reason)}` : ""}<br><span class="muted">${ps}</span>`;
}

function renderNetwork(svg) {
  const ms = S.club.managers.filter((m) => m.nodes);
  if (!ms.length) { svg.innerHTML = pitchMarkup(); $("#pitch-tools").innerHTML = "Нет тренера с 5+ матчами"; return; }
  S.manager = Math.min(S.manager, ms.length - 1);
  const m = ms[S.manager];
  $("#pitch-tools").innerHTML = `<div class="seg small">${ms.map((x, k) => `<button data-m="${k}" class="${k === S.manager ? "on" : ""}">${esc(x.name.split(" ").pop())} · ${x.matches}</button>`).join("")}</div>`;
  $$("[data-m]").forEach((b) => b.onclick = () => { S.manager = +b.dataset.m; renderPitch(); });
  const emax = Math.max(1, ...ms.flatMap((x) => x.edges.map((e) => e.per_match)));
  const nmax = Math.max(1, ...ms.flatMap((x) => x.nodes.map((n) => n.per_match)));
  const at = Object.fromEntries(m.nodes.map((n) => [n.slot, n]));
  let g = "";
  m.edges.forEach((e) => {
    const a = at[e.a], b = at[e.b]; if (!a || !b) return;
    const [x1, y1] = P(a.x, a.y), [x2, y2] = P(b.x, b.y);
    g += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--series-1)" stroke-linecap="round"
      stroke-width="${0.25 + 1.7 * e.per_match / emax}" opacity="${0.3 + 0.55 * e.per_match / emax}"><title>${a.code}–${b.code}: ${fmt(e.per_match, 1)} передачи за матч</title></line>`;
  });
  m.nodes.forEach((n) => {
    const [x, y] = P(n.x, n.y), r = 2 + 2 * n.per_match / nmax;
    g += `<g><circle cx="${x}" cy="${y}" r="${r}" fill="var(--surface-1)" stroke="var(--series-1)" stroke-width=".55"><title>${n.code}: ${fmt(n.per_match, 1)} касаний за матч</title></circle>
      <text x="${x}" y="${y + 0.75}" font-size="2" font-weight="700" text-anchor="middle" fill="var(--text-primary)">${S.club.slots[n.slot]?.code ?? n.code}</text>
      <text x="${x}" y="${y + r + 2.6}" font-size="2.1" text-anchor="middle" fill="var(--text-secondary)" paint-order="stroke" stroke="var(--pitch)" stroke-width=".6">${esc(surname(n.label))}</text></g>`;
  });
  svg.innerHTML = pitchMarkup() + arrowUp + g;
  const st = m.style;
  $("#pitch-legend").innerHTML = `<span>${m.matches} матчей · ${fmt(m.ppg, 2)} очка за матч · xG ${fmt(m.xg / m.matches, 2)} – xGA ${fmt(m.xga / m.matches, 2)} · владение ${fmt(st.possession * 100)}% · PPDA ${fmt(st.ppda, 1)}</span>`;
  $("#pitch-note").textContent = "Кружок — позиция в схеме: средняя точка, где игроки этой позиции отдают и принимают передачи (до первой замены). Линия — точные передачи между позициями, ≥2 за матч; толще — чаще.";
}

function renderShots(svg, ours) {
  // ours: our shots at the opponent's goal (top); otherwise the opponents' shots at our goal (bottom).
  // Shots come in the shooting team's frame (attacking towards x=120); our right flank is always on the right.
  svg.setAttribute("viewBox", ours ? "-3 -3 86 67" : "-3 56 86 67");
  const c = ours ? S.club.scored : S.club.conceded, z = S.index.zones, d = c.zone_diff;
  const at = ours ? (x, y) => [y, 120 - x] : (x, y) => [80 - y, x];
  const lim = Math.max(0.05, ...d.flat().map(Math.abs));
  const xgName = ours ? "xG" : "xGA", goalFill = ours ? "var(--series-1)" : "var(--critical)";
  S.shotMode = S.shotMode || "zones";
  let g = "", labels = "";                    // labels go above the pitch lines, so the penalty spot does not cut them
  if (S.shotMode === "zones") {
    for (let i = 0; i < z.x.length - 1; i++) for (let j = 0; j < z.y.length - 1; j++) {
      const [ax, ay] = at(z.x[i], z.y[j]), [bx, by] = at(z.x[i + 1], z.y[j + 1]);
      const x0 = Math.min(ax, bx), x1 = Math.max(ax, bx), y0 = Math.min(ay, by), y1 = Math.max(ay, by);
      const v = d[i][j], sc = 50 + (ours ? 50 : -50) * v / lim;        // blue = good for us, red = bad
      g += `<rect x="${x0 + .25}" y="${y0 + .25}" width="${x1 - x0 - .5}" height="${y1 - y0 - .5}" fill="${divColor(sc)}" rx=".6">
        <title>${v >= 0 ? "+" : "−"}${fmt(Math.abs(v), 2)} ${xgName} за матч к среднему по лиге</title></rect>`;
      if (Math.abs(v) >= 0.005) labels += `<text x="${(x0 + x1) / 2}" y="${(y0 + y1) / 2 + .7}" font-size="2" font-weight="600" text-anchor="middle" fill="${inkOn(sc)}" stroke="${divColor(sc)}" stroke-width=".6" paint-order="stroke">${v > 0 ? "+" : "−"}${fmt(Math.abs(v), 2)}</text>`;
    }
  } else {
    c.shots.forEach(([x, y, xg, goal]) => {
      const [cx, cy] = at(x, y), r = 0.45 + 2.6 * Math.sqrt(xg || 0);
      g += goal ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${goalFill}" stroke="var(--surface-1)" stroke-width=".25"><title>гол, xG ${fmt(xg, 2)}</title></circle>`
        : `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--text-muted)" stroke-width=".22" opacity=".8"/>`;
    });
  }
  svg.innerHTML = `<rect width="80" height="120" fill="var(--pitch)"/>` + g + pitchMarkup(false, false) + labels;
  const goals = c.shots.filter((x) => x[3]).length;
  $("#pitch-tools").innerHTML = `<div class="seg small"><button data-c="zones" class="${S.shotMode === "zones" ? "on" : ""}">Зоны</button><button data-c="shots" class="${S.shotMode === "shots" ? "on" : ""}">Удары</button></div>
    <span>${xgName} за матч: <b>${fmt(c.xg_pm, 2)}</b> · после угловых и штрафных <b>${fmt(c.set_piece_share * 100)}%</b> ${xgName}</span>`;
  $$("[data-c]").forEach((b) => b.onclick = () => { S.shotMode = b.dataset.c; renderPitch(); });
  $("#pitch-legend").innerHTML = S.shotMode === "zones"
    ? (ours ? `<span><span class="dot" style="background:${divColor(90)}"></span> создаём больше среднего по лиге</span><span><span class="dot" style="background:${divColor(10)}"></span> меньше</span>`
      : `<span><span class="dot" style="background:${divColor(10)}"></span> пропускаем больше среднего по лиге</span><span><span class="dot" style="background:${divColor(90)}"></span> меньше</span>`)
    : `<span><span class="dot" style="background:${goalFill}"></span> гол (${goals})</span><span><span class="dot" style="border:1px solid var(--text-muted)"></span> удар, размер = xG (${c.shots.length})</span>`;
  $("#pitch-note").textContent = S.shotMode === "zones"
    ? (ours ? "Ворота соперника вверху, правая сторона картинки — наш правый фланг. Число — xG наших ударов за матч из зоны минус среднее по лиге; зоны построены по разметке штрафной."
      : "Наши ворота внизу, правая сторона картинки — наш правый фланг. Число — xG пропущенных за матч из зоны минус среднее по лиге; зоны построены по разметке штрафной.")
    : (ours ? "Все наши удары по воротам соперника (вверху). Правая сторона картинки — наш правый фланг."
      : "Все удары соперников по нашим воротам (внизу). Правая сторона картинки — наш правый фланг.");
}

// ---------------------------------------------------------------- candidates
function weightsFor(slot, player) {
  const g = slot.group, ref = player?.groups[g]?.top6;
  if (S.compare !== "player" || !ref) return slot.weights;
  const raw = {}; let tot = 0;
  for (const m of S.index.role_metrics[g]) { raw[m] = 1 + Math.max(0, 50 - (ref[m] ?? 50)) / 50; tot += raw[m]; }
  for (const m in raw) raw[m] /= tot;
  return raw;
}
const nameOf = (id) => S.players.get(id)?.name ?? S.club.names?.[id] ?? String(id);
const fitOf = (pct, w) => Object.entries(w).reduce((s, [m, x]) => s + (pct?.[m] ?? 0) * x, 0);

function topsis(rows, weights) {
  const crit = Object.keys(S.index.criteria);
  if (!rows.length) return [];
  const tot = crit.reduce((s, k) => s + weights[k], 0) || 1;
  const lo = {}, hi = {};
  crit.forEach((k) => { lo[k] = Math.min(...rows.map((r) => r[k])); hi[k] = Math.max(...rows.map((r) => r[k])); });
  return rows.map((r) => {
    let dB = 0, dW = 0;
    crit.forEach((k) => {
      const w = weights[k] / tot;
      let v = hi[k] > lo[k] ? (r[k] - lo[k]) / (hi[k] - lo[k]) : 0;
      if (!S.index.criteria[k].benefit) v = 1 - v;
      dB += (w * v - w) ** 2; dW += (w * v) ** 2;
    });
    dB = Math.sqrt(dB); dW = Math.sqrt(dW);
    return dB + dW ? dW / (dB + dW) : 0;
  });
}

function candidates(slot, player, opts = S.filters) {
  const g = slot.group, w = weightsFor(slot, player), rules = S.index.rules;
  const inc = S.compare === "player" && player?.groups[g]?.europe ? fitOf(player.groups[g].europe, w) : slot.incumbent_fit;
  let c = S.pool.filter((p) => p.group === g);
  const funnel = [[`${S.index.groups[g]} с ≥${rules.min_minutes} мин`, c.length]];
  const step = (lab, f) => { c = c.filter(f); funnel.push([lab, c.length]); };
  step("не из своего клуба", (p) => p.team !== S.team);
  if (slot.side) step(slot.side === "right" ? "играет справа" : "играет слева", (p) => (slot.side === "right" ? p.right : p.left) >= rules.side_share);
  step("выбранные лиги", (p) => opts.leagues.has(p.league));
  step("есть стоимость на лето 2016", (p) => p.fresh && p.fair != null && p.age != null);
  step(`не старше ${opts.maxAge}`, (p) => p.age <= opts.maxAge);
  step(`до €${opts.maxPrice} млн`, (p) => p.value <= opts.maxPrice * 1e6);
  c = c.map((p) => ({ ...p, fit: fitOf(p.pct, w), role_minutes: p.minutes }));
  if (opts.better) step("лучше текущего по потребности", (p) => p.fit > (inc ?? -1));
  const sc = topsis(c, S.weights);
  c.forEach((p, k) => { p.score = sc[k]; });
  c.sort((a, b) => b.score - a.score);
  return { list: c, funnel, inc, w };
}

function stability(list, n = 400, top = 3) {
  // share of random weightings (uniform over the simplex) under which a candidate makes the top
  const crit = Object.keys(S.index.criteria), hits = new Map(list.map((p) => [p.id + p.team, 0]));
  if (list.length <= top) { list.forEach((p) => hits.set(p.id + p.team, 1)); return hits; }
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let s = 0; s < n; s++) {
    const e = crit.map(() => -Math.log(rnd() || 1e-9)), tot = e.reduce((a, b) => a + b, 0);
    const w = Object.fromEntries(crit.map((k, i) => [k, e[i] / tot]));
    topsis(list, w).map((v, i) => [v, i]).sort((a, b) => b[0] - a[0]).slice(0, top)
      .forEach(([, i]) => hits.set(list[i].id + list[i].team, hits.get(list[i].id + list[i].team) + 1 / n));
  }
  return hits;
}

const typicalCache = {};
function typical(group, side) {
  const key = group + side;
  if (!typicalCache[key]) {
    const rows = S.pool.filter((p) => p.group === group && p.ax != null && (!side || (side === "right" ? p.right : p.left) >= 0.6));
    typicalCache[key] = { ax: rows.reduce((s, p) => s + p.ax, 0) / rows.length, w: rows.reduce((s, p) => s + Math.abs(p.ay - 40), 0) / rows.length };
  }
  return typicalCache[key];
}
function putIn(slot, cand) {
  // the candidate takes the slot where the current shape has it, shifted by how much higher / wider than a typical
  // player of the role he acts; the rest of the team follows through the shape model
  S.whatIf[slot.i] = cand;
  const t = typical(slot.group, slot.side), b = S.base[slot.i];
  const sign = slot.side === "right" ? 1 : slot.side === "left" ? -1 : 0;
  S.fixed[slot.i] = [clamp(b[0] + (cand.ax - t.ax), 1, 119), clamp(b[1] + sign * (Math.abs(cand.ay - 40) - t.w), 1, 79)];
  S.lastMoved = slot.i;
}

// ---------------------------------------------------------------- panels
function setTab(t) { S.tab = t; $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t)); renderPanel(); }

function selectSlot(i, tab = "player") {
  S.slot = i; const s = S.club.slots[i];
  S.player = s.players[0] ? s.players[0][0] : null; S.group = s.group; S.cand = null;
  renderPitch(); setTab(tab);
}

function renderPanel() {
  const el = $("#panel");
  ({ club: panelClub, player: panelPlayer, replace: panelReplace, plan: panelPlan, value: panelValue, finance: panelFinance, method: panelMethod }[S.tab])(el);
}

function panelClub(el) {
  const c = S.club, s = c.summary;
  const luck = s.xgd_rank < s.place ? `По разнице xG команда ${s.xgd_rank}-я — играла лучше, чем говорит таблица.`
    : s.xgd_rank > s.place ? `По разнице xG команда ${s.xgd_rank}-я — место в таблице лучше качества моментов.` : `По разнице xG тоже ${s.xgd_rank}-е место.`;
  const needs = c.slots.filter((x) => x.need);
  el.innerHTML = `<h2>${esc(S.team)}</h2><p class="muted">${esc(S.index.leagues.find((l) => l.name === S.league).ru)} ${S.index.season} · схема ${fmtFormation(c.formation)} (${fmt(c.formation_share * 100)}% игрового времени)</p>
    <div class="kpis" style="margin:12px 0">
      ${kpi(`${s.place}-е`, "место", `${s.pts} очков`)}${kpi(`${s.gf}–${s.ga}`, "голы", "забито – пропущено")}
      ${kpi(`${fmt(s.xg, 1)}–${fmt(s.xga, 1)}`, "xG – xGA", `разница: ${s.xgd_rank}-я в лиге`)}
      ${kpi(`${fmt(s.possession * 100)}%`, "владение", "доля передач в матче")}${kpi(fmt(s.ppda, 1), "PPDA", "меньше — выше прессинг")}
    </div>
    <div class="callout">${luck}</div>
    <h3>Потребности летом 2016</h3>
    <p class="small muted">Позиция — потребность, если игроки на ней слабее медианы топ-6 своей лиги больше чем на ${50 - S.index.rules.weak} пунктов, или основному игроку ${S.index.rules.old}+ лет.</p>
    <div class="need-list">${needs.length ? needs.map((x) => `<div class="need" data-i="${x.i}">
        <span class="badge" style="background:${divColor(x.score_top6 ?? 50)};color:${inkOn(x.score_top6)}">${fmt(x.score_top6)}</span>
        <div><b>${x.code} · ${SLOT_RU[x.code] ?? ""}</b> — ${esc(S.players.get(x.players[0]?.[0])?.name ?? "")}<br><span class="small muted">${esc(x.reason)}</span></div>
        <span style="margin-left:auto" class="small">кем заменить →</span></div>`).join("") : `<div class="empty">Явных потребностей нет</div>`}</div>
    <h3>Тренеры</h3>
    <div class="scroll-x"><table><tr><th>Тренер</th><th class="num">Матчи</th><th class="num">Очки/матч</th><th class="num">Голы</th><th class="num">xG – xGA</th><th class="num">Реализация</th><th class="num">Пропуски</th></tr>
      ${c.managers.map((m) => `<tr><td>${esc(m.name)}<div class="small muted">${m.from} — ${m.to}</div></td><td class="num">${m.matches}</td><td class="num">${fmt(m.ppg, 2)}</td>
        <td class="num">${m.gf}–${m.ga}</td><td class="num">${fmt(m.xg, 1)} – ${fmt(m.xga, 1)}</td>
        <td class="num">${signed(m.gf - m.xg)}</td><td class="num">${signed(m.ga - m.xga)}</td></tr>`).join("")}</table></div>
    <p class="small muted">Реализация = голы − xG (плюс — забивали больше ожидаемого). Пропуски = пропущено − xGA (плюс — пропускали больше ожидаемого: вратарь, невезение).</p>`;
  $$(".need", el).forEach((n) => n.onclick = () => { S.compare = "slot"; selectSlot(+n.dataset.i, "replace"); });
}
const kpi = (v, l, s) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div><div class="s">${s}</div></div>`;
const later = (c) => c.v2018 == null ? `<span class="muted">нет оценки</span>`
  : `${money(c.v2018)}<div class="small muted">×${fmt(c.v2018 / c.value, 1)} к 2016</div>`;
const futureSwitch = (what = "стоимость в 2018") => `<label class="future"><input type="checkbox" id="future" ${S.future ? "checked" : ""}> Что было дальше: ${what} <span class="muted">(машина времени — рейтинг этого не видит)</span></label>`;
function bindFuture(el) { const f = $("#future", el); if (f) f.onchange = () => { S.future = f.checked; renderPanel(); }; }
const signed = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v), 1)}`;

function playerFair(id, team) { const p = S.pool.find((x) => x.id === id && x.team === team); return p || S.pool.find((x) => x.id === id); }

function rawValue(m, v) {
  if (v == null) return "—";
  if (["pass_pct", "aerial_win_pct", "save_pct"].includes(m)) return `${fmt(v * 100)}%`;
  return `${fmt(v, 2)} /90`;
}

// Transfermarkt portrait, loaded from their server (today's photo, not 2016's); a silhouette when there is none
const NO_PHOTO = `<div class="photo-none" role="img" aria-label="Нет фото"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>нет фото</div>`;
function photo(p) {
  return `<figure class="photo">${p.photo ? `<img src="${esc(p.photo)}" alt="Фото: ${esc(p.name)}" referrerpolicy="no-referrer">` : NO_PHOTO}</figure>`;
}

function panelPlayer(el) {
  if (S.slot == null) { el.innerHTML = `<div class="empty">Нажмите на игрока на поле</div>`; return; }
  const slot = S.club.slots[S.slot], p = S.players.get(S.player);
  const chips = slot.players.slice(0, 8).map(([id, m]) => `<button class="chip ${id === S.player ? "on" : ""}" data-p="${id}">${esc(nameOf(id))} · ${fmt(m)}′</button>`).join("");
  if (!p) { el.innerHTML = `<h2>${slot.code} · ${SLOT_RU[slot.code] ?? ""}</h2><div class="chips">${chips}</div><div class="empty">Нет данных об игроке</div>`; return; }
  const groups = Object.keys(p.groups);
  const g = groups.includes(S.group) ? S.group : groups[0];
  const gd = p.groups[g], pf = playerFair(p.id, S.team);
  const bench = gd[S.pbench] ? S.pbench : gd.top6 ? "top6" : "league";
  const pct = gd[bench] || {}, score = gd[`score_${bench}`];
  el.innerHTML = `
    <div class="row spread"><h2>${slot.code} · ${SLOT_RU[slot.code] ?? ""}</h2>${slot.need ? `<span class="badge">потребность: ${esc(slot.reason)}</span>` : ""}</div>
    <p class="small muted">Кто играл на позиции (минуты):</p><div class="chips">${chips}</div>
    <div class="card" style="margin-top:12px">
      <div class="who">${photo(p)}
        <div class="row spread" style="align-items:flex-start"><div><h2>${esc(p.name)}</h2><div class="small muted">${[p.full_name, p.country].filter(Boolean).map(esc).join(" · ")} · ${p.age ? fmt(p.age) + " лет летом 2016" : "возраст неизвестен"}</div></div>
          <div style="text-align:right"><div style="font-size:26px;font-weight:700">${fmt(score)}</div><div class="small muted">оценка роли к: ${BENCH_RU[bench]}</div></div></div>
        <div class="kpis">
          ${kpi(fmt(p.minutes), "минут за сезон", groups.length > 1 ? `в ${groups.length} ролях` : S.index.groups[g])}
          ${kpi(money(p.value), "рыночная стоимость", p.value_date ? `оценка от ${p.value_date}` : "нет оценки")}
          ${kpi(pf?.fair ? money(pf.fair) : "—", "справедливая (модель)", pf?.fair ? (pf.fair > p.value ? `×${fmt(pf.fair / p.value, 1)} — рынок недооценивает` : `×${fmt(pf.fair / p.value, 1)} — рынок ценит выше`) : "мало минут для оценки")}
        </div></div>
    </div>
    ${groups.length > 1 ? `<div class="chips" style="margin-bottom:8px">${groups.map((x) => `<button class="chip ${x === g ? "on" : ""}" data-g="${x}">${S.index.groups[x]} · ${fmt(p.groups[x].minutes)}′</button>`).join("")}</div>` : ""}
    <div class="row spread"><h3 style="margin:8px 0">Показатели — процентиль к: ${BENCH_RU[bench]}</h3>
      <div class="seg small">${["top6", "league", "europe"].map((b) => `<button data-pb="${b}" class="${bench === b ? "on" : ""}" ${gd[b] ? "" : "disabled"}>${{ top6: "топ-6", league: "лига", europe: "топ-5 лиг" }[b]}</button>`).join("")}</div></div>
    <div class="bars">${S.index.role_metrics[g].map((m) => bar(m, pct[m], gd.per90[m])).join("")}</div>
    <p class="small muted">50 — медиана игроков той же роли с ≥${S.index.rules.min_minutes} мин. «Сколько раз обыграли» и «потери» перевёрнуты: больше — лучше. Отборы и перехваты — с поправкой на владение соперника.</p>
    <h3>Где действует</h3>
    <div class="mini-pitches">${heatMini(p.grid)}${p.shots.length ? shotsMini(p.shots) : ""}</div>
    <div class="row" style="margin-top:14px"><button class="btn" id="go-replace">Кем заменить →</button></div>`;
  const img = $(".photo img", el);
  if (img) img.onerror = () => { img.parentElement.innerHTML = NO_PHOTO; };   // Transfermarkt down or blocking
  $$("[data-p]", el).forEach((b) => b.onclick = () => { S.player = +b.dataset.p; S.cand = null; renderPanel(); });
  $$("[data-g]", el).forEach((b) => b.onclick = () => { S.group = b.dataset.g; renderPanel(); });
  $$("[data-pb]", el).forEach((b) => b.onclick = () => { S.pbench = b.dataset.pb; renderPanel(); });
  $("#go-replace").onclick = () => { S.compare = "player"; setTab("replace"); };
}

function bar(m, v, raw) {
  const ok = v != null;
  return `<div class="bar-row"><div class="bar-label">${esc(label(m))}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${ok ? v : 0}%;background:${ok ? divColor(v) : "transparent"}"></div><div class="bar-mid"></div></div>
    <div class="bar-val"><b>${ok ? fmt(v) : "—"}</b><span class="muted">${rawValue(m, raw)}</span></div></div>`;
}

function heatMini(grid) {
  let g = "";
  grid.forEach((col, i) => col.forEach((v, j) => {
    if (v > 0.04) g += `<rect x="${j * 10}" y="${120 - (i + 1) * 10}" width="10" height="10" fill="${seqColor(v)}" opacity=".9"/>`;
  }));
  return `<figure><figcaption>Касания мяча (темнее — чаще), атака вверх</figcaption><svg viewBox="-2 -3 84 125"><rect width="80" height="120" fill="var(--pitch)"/>${g}${pitchMarkup(false, false)}</svg></figure>`;
}
function shotsMini(shots) {
  const g = shots.map(([x, y, xg, goal]) => { const [cx, cy] = P(x, y), r = 0.5 + 2.8 * Math.sqrt(xg || 0);
    return goal ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width=".25"/>`
      : `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--text-muted)" stroke-width=".25"/>`; }).join("");
  const goals = shots.filter((s) => s[3]).length, xg = shots.reduce((a, s) => a + (s[2] || 0), 0);
  return `<figure><figcaption>Удары: ${shots.length}, голы ${goals}, xG ${fmt(xg, 1)} (закрашены — голы)</figcaption><svg viewBox="-2 -3 84 66">${pitchMarkup()}${g}</svg></figure>`;
}

function panelReplace(el) {
  if (S.slot == null) { el.innerHTML = `<div class="empty">Выберите позицию на поле или потребность на вкладке «Клуб»</div>`; return; }
  const slot = S.club.slots[S.slot], p = S.players.get(S.player);
  const res = candidates(slot, p);
  const top = res.list.slice(0, 12), stab = stability(res.list);
  const wsum = Object.values(S.weights).reduce((a, b) => a + b, 0) || 1;
  const leagues = S.index.candidate_leagues;
  el.innerHTML = `
    <div class="row spread"><h2>Кем заменить: ${slot.code} · ${SLOT_RU[slot.code] ?? ""}</h2>
      <div class="seg small"><button data-cmp="player" class="${S.compare === "player" ? "on" : ""}">к игроку: ${esc(surname(p?.name ?? "—"))}</button><button data-cmp="slot" class="${S.compare === "slot" ? "on" : ""}">к позиции в целом</button></div></div>
    <p class="small muted">Что должен уметь новый игрок: все показатели роли, а те, где ${S.compare === "player" ? "текущий игрок" : "игроки позиции"} ниже медианы топ-6, — с весом до ×2.</p>
    <div class="chips">${Object.entries(res.w).sort((a, b) => b[1] - a[1]).map(([m, w]) => `<span class="chip">${esc(label(m))} · ${fmt(w * 100)}%</span>`).join("")}</div>
    <p>Соответствие текущего: <b>${fmt(res.inc)}</b> из 100 (процентиль к игрокам топ-5 лиг с весами потребности).</p>
    <div class="controls">
      ${range("maxAge", "Возраст не старше", S.filters.maxAge, 18, 35, 1, (v) => `${v} лет`)}
      ${range("maxPrice", "Цена не выше", S.filters.maxPrice, 5, 150, 5, (v) => `€${v} млн`)}
      ${Object.entries(S.index.criteria).map(([k, c]) => range(`w_${k}`, `Вес: ${c.label}`, S.weights[k], 0, 100, 5, (v) => `${fmt(v / wsum * 100)}%`)).join("")}
    </div>
    <div class="checks">${leagues.map((l) => `<label><input type="checkbox" data-l="${esc(l.name)}" ${S.filters.leagues.has(l.name) ? "checked" : ""}> ${l.ru}</label>`).join("")}
      <label><input type="checkbox" id="better" ${S.filters.better ? "checked" : ""}> только лучше текущего</label></div>
    ${futureSwitch()}
    <div class="funnel">${res.funnel.map(([l, n]) => `<span>${esc(l)}: ${n}</span>`).join(" → ")}</div>
    ${top.length ? `<div class="scroll-x"><table><tr><th>#</th><th>Игрок</th><th class="num">Возраст</th><th class="num">Цена</th><th class="num">Справедл.</th><th class="num">Соответствие</th><th class="num">Минуты</th><th class="num">TOPSIS</th><th class="num" title="Доля случайных наборов весов, при которых игрок в топ-3">Устойч.</th>${S.future ? `<th class="num">2018</th>` : ""}</tr>
      ${top.map((c, k) => `<tr class="click ${S.cand && S.cand.id === c.id && S.cand.team === c.team ? "on" : ""}" data-k="${k}"><td>${k + 1}</td>
        <td><b>${esc(c.name)}</b><div class="small muted">${esc(c.team)} · ${c.team_league}, ${c.team_place}-е место</div></td>
        <td class="num">${fmt(c.age)}</td><td class="num">${money(c.value)}</td>
        <td class="num">${money(c.fair)}<div class="small muted">×${fmt(c.fair / c.value, 1)}</div></td>
        <td class="num"><b>${fmt(c.fit)}</b><div class="small muted">${signed(c.fit - (res.inc ?? 0))}</div></td>
        <td class="num">${fmt(c.minutes)}</td><td class="num">${fmt(c.score, 2)}</td><td class="num">${fmt(stab.get(c.id + c.team) * 100)}%</td>${S.future ? `<td class="num">${later(c)}</td>` : ""}</tr>`).join("")}
    </table></div>` : `<div class="empty">Никто не прошёл фильтры — ослабьте ограничения</div>`}
    <div id="cand-detail"></div>
    <p class="small muted">TOPSIS — близость к идеальному кандидату (лучший по каждому критерию среди найденных); критерии растянуты min–max, поэтому вес значит ровно то, что показан. Недооценённость = log₁₀(справедливая / рыночная). Устойчивость — в скольких из 400 случайных наборов весов игрок остаётся в тройке.</p>`;
  $$("[data-cmp]", el).forEach((b) => b.onclick = () => { S.compare = b.dataset.cmp; S.cand = null; renderPanel(); });
  $$("input[type=range]", el).forEach((r) => {
    const k = r.dataset.k;
    r.oninput = () => {
      const v = +r.value, out = r.previousElementSibling.lastElementChild;
      if (k.startsWith("w_")) { S.weights[k.slice(2)] = v; out.textContent = `${v}`; }
      else { S.filters[k] = v; out.textContent = k === "maxAge" ? `${v} лет` : `€${v} млн`; }
    };
    r.onchange = () => renderPanel();
  });
  $$("[data-l]", el).forEach((b) => b.onchange = () => { b.checked ? S.filters.leagues.add(b.dataset.l) : S.filters.leagues.delete(b.dataset.l); renderPanel(); });
  $("#better", el).onchange = (e) => { S.filters.better = e.target.checked; renderPanel(); };
  bindFuture(el);
  $$("tr[data-k]", el).forEach((tr) => tr.onclick = () => { S.cand = top[+tr.dataset.k]; renderPanel(); });
  if (S.cand) {
    const c = top.find((x) => x.id === S.cand.id && x.team === S.cand.team) || res.list.find((x) => x.id === S.cand.id);
    if (c) candDetail($("#cand-detail", el), slot, p, c, res);
  }
}
function range(k, lab, v, min, max, step, show) {
  return `<div class="control"><label><span>${lab}</span><b>${show(v)}</b></label><input type="range" data-k="${k}" min="${min}" max="${max}" step="${step}" value="${v}"></div>`;
}

function candDetail(el, slot, p, c, res) {
  const g = slot.group, mine = p?.groups[g]?.europe || {};
  const inPlace = S.whatIf[slot.i] && S.whatIf[slot.i].id === c.id;
  el.innerHTML = `<div class="card" style="margin-top:14px">
    <div class="row spread"><div><h2>${esc(c.name)}</h2><div class="small muted">${esc(c.team)} · ${c.team_league} · ${fmt(c.age)} лет · ${fmt(c.minutes)} мин в роли</div></div>
      <div class="row">${inPlace ? `<button class="btn secondary" id="out">Убрать с поля</button>` : `<button class="btn" id="in">Поставить в состав</button>`}</div></div>
    <div class="kpis" style="margin:10px 0">${kpi(money(c.value), "рыночная", "лето 2016")}${kpi(money(c.fair), "справедливая", `×${fmt(c.fair / c.value, 1)}`)}
      ${kpi(fmt(c.fit), "соответствие", `текущий: ${fmt(res.inc)}`)}${kpi(fmt(c.score, 2), "TOPSIS", "0…1")}</div>
    <h3>Сравнение с ${esc(p?.name ?? "текущим")} — процентиль к игрокам топ-5 лиг</h3>
    <div class="dumb">${S.index.role_metrics[g].map((m) => dumbRow(m, mine[m], c.pct[m], res.w[m])).join("")}</div>
    <div class="row small" style="margin-top:8px;gap:16px"><span><span class="dot" style="background:var(--text-muted)"></span> ${esc(surname(p?.name ?? "текущий"))}</span><span><span class="dot" style="background:var(--series-1)"></span> ${esc(surname(c.name))}</span><span class="muted">в скобках — вес в потребности</span></div>
    <p class="small muted">«Поставить в состав» помещает игрока на позицию с поправкой на его манеру: насколько выше и шире типичного игрока роли он действовал в своём клубе. Остальные смещаются по модели формы команды.</p></div>`;
  if ($("#in", el)) $("#in", el).onclick = () => { putIn(slot, c); S.view = "lineup"; renderPitch(); renderPanel(); };
  if ($("#out", el)) $("#out", el).onclick = () => { delete S.whatIf[slot.i]; delete S.fixed[slot.i]; S.lastMoved = null; renderPitch(); renderPanel(); };
}
function dumbRow(m, a, b, w) {
  const x = (v) => clamp(v ?? 0, 0, 100), lo = Math.min(x(a), x(b)), hi = Math.max(x(a), x(b));
  return `<div class="dumb-row"><div class="bar-label">${esc(label(m))} <span class="muted">(${fmt(w * 100)}%)</span></div>
    <div class="dumb-track"><div class="dumb-mid"></div><div class="dumb-seg" style="left:${lo}%;width:${hi - lo}%"></div>
      <span class="dumb-dot a" style="left:${x(a)}%" title="текущий: ${fmt(a)}"></span><span class="dumb-dot b" style="left:${x(b)}%" title="кандидат: ${fmt(b)}"></span></div></div>`;
}

function panelPlan(el) {
  const needs = S.club.slots.filter((s) => s.need);
  if (!needs.length) { el.innerHTML = `<div class="empty">У клуба нет позиций-потребностей по правилу</div>`; return; }
  const saved = S.compare; S.compare = "slot";
  const opts = needs.map((s) => ({ slot: s, list: candidates(s, null).list.slice(0, needs.length > 5 ? 4 : 6) }));
  S.compare = saved;
  const budget = S.budget * 1e6;
  let best = [], bestScore = -1;
  (function walk(k, cost, score, chosen) {
    if (cost > budget) return;
    if (k === opts.length) { if (score > bestScore) { bestScore = score; best = [...chosen]; } return; }
    walk(k + 1, cost, score, chosen);
    for (const c of opts[k].list) { chosen.push([opts[k].slot, c]); walk(k + 1, cost + c.value, score + c.score, chosen); chosen.pop(); }
  })(0, 0, 0, []);
  const spent = best.reduce((s, [, c]) => s + c.value, 0), fair = best.reduce((s, [, c]) => s + c.fair, 0);
  const later18 = best.reduce((s, [, c]) => s + (c.v2018 ?? 0), 0);
  S.plan = { budget: S.budget, best, spent, later18 };
  el.innerHTML = `<h2>План трансферов под бюджет</h2>
    <p class="small muted">По одному игроку на каждую позицию-потребность, чтобы сумма оценок TOPSIS была максимальной и цены укладывались в бюджет. Фильтры и веса — с вкладки «Кем заменить», сравнение — с позицией в целом.</p>
    <div class="controls">${range("budget", "Бюджет", S.budget, 10, 300, 10, (v) => `€${v} млн`)}</div>
    <div class="scroll-x"><table><tr><th>Позиция</th><th>Игрок</th><th class="num">Цена</th><th class="num">Справедл.</th><th class="num">Соответствие</th><th class="num">TOPSIS</th>${S.future ? `<th class="num">2018</th>` : ""}</tr>
      ${needs.map((s) => { const pick = best.find(([x]) => x.i === s.i);
        return pick ? `<tr><td><b>${s.code}</b><div class="small muted">${esc(s.reason)}</div></td><td><b>${esc(pick[1].name)}</b><div class="small muted">${esc(pick[1].team)} · ${pick[1].team_league} · ${fmt(pick[1].age)} лет</div></td>
          <td class="num">${money(pick[1].value)}</td><td class="num">${money(pick[1].fair)}</td><td class="num">${fmt(pick[1].fit)} <span class="muted">(${fmt(s.incumbent_fit)})</span></td><td class="num">${fmt(pick[1].score, 2)}</td>${S.future ? `<td class="num">${later(pick[1])}</td>` : ""}</tr>`
          : `<tr><td><b>${s.code}</b></td><td colspan="${S.future ? 6 : 5}" class="muted">не берём: не хватает бюджета или никто не прошёл фильтры</td></tr>`; }).join("")}
      <tr><td></td><td><b>Итого</b></td><td class="num"><b>${money(spent)}</b></td><td class="num">${money(fair)}</td><td></td><td></td>${S.future ? `<td class="num"><b>${money(later18)}</b></td>` : ""}</tr></table></div>
    ${S.future && spent ? `<p class="small">Годовая доходность плана: <b>${pct((later18 / spent) ** 0.5 - 1)}</b> (стоимость летом 2018 к цене 2016, два года). Для сравнения: медиана доходности составов ${esc(S.index.leagues.find((l) => l.name === S.league).ru)} за те же два сезона — ${pct(perYear((S.club.finance?.seasons ?? []).filter((s) => s.season > S.index.decision_season).map((s) => s.median)))} в год (вкладка «Доходность»).</p>` : ""}
    ${futureSwitch()}
    <div class="row" style="margin-top:12px"><button class="btn" id="show-plan" ${best.length ? "" : "disabled"}>Показать состав на поле</button></div>
    <div class="callout">Рекомендации — отправная точка для скаутов, а не готовое решение: модель не видит травм, характера, длины контракта и того, продаст ли клуб игрока.</div>`;
  const r = $("input[type=range]", el);
  r.oninput = () => { S.budget = +r.value; r.previousElementSibling.lastElementChild.textContent = `€${r.value} млн`; };
  r.onchange = () => renderPanel();
  bindFuture(el);
  $("#show-plan", el).onclick = () => { S.whatIf = {}; S.fixed = {}; best.forEach(([s, c]) => putIn(s, c)); S.view = "lineup"; renderPitch(); };
}

function panelValue(el) {
  const vm = S.index.value_model, chosen = vm[vm.chosen];
  const seen = new Set(), pts = S.pool.filter((p) => p.fair && p.value && p.fresh && !seen.has(p.id) && seen.add(p.id));
  const W = 640, H = 430, m = { l: 58, r: 16, t: 14, b: 44 };
  const lo = 5, hi = 8.3, sx = (v) => m.l + (Math.log10(v) - lo) / (hi - lo) * (W - m.l - m.r), sy = (v) => H - m.b - (Math.log10(v) - lo) / (hi - lo) * (H - m.t - m.b);
  const ticks = [0.2, 0.5, 1, 2, 5, 10, 20, 50, 100].map((t) => t * 1e6);
  let g = ticks.map((t) => `<line x1="${sx(t)}" y1="${m.t}" x2="${sx(t)}" y2="${H - m.b}" stroke="var(--line-soft)"/><line x1="${m.l}" y1="${sy(t)}" x2="${W - m.r}" y2="${sy(t)}" stroke="var(--line-soft)"/>
    <text x="${sx(t)}" y="${H - m.b + 16}" font-size="11" text-anchor="middle" fill="var(--text-secondary)">${t >= 1e6 ? fmt(t / 1e6) : fmt(t / 1e6, 1)}</text>
    <text x="${m.l - 8}" y="${sy(t) + 4}" font-size="11" text-anchor="end" fill="var(--text-secondary)">${t >= 1e6 ? fmt(t / 1e6) : fmt(t / 1e6, 1)}</text>`).join("");
  g += `<line x1="${sx(10 ** lo)}" y1="${sy(10 ** lo)}" x2="${sx(10 ** hi)}" y2="${sy(10 ** hi)}" stroke="var(--text-muted)" stroke-dasharray="4 4"/>
    <text x="${sx(6e7)}" y="${sy(6e7) - 8}" font-size="11" fill="var(--text-secondary)" text-anchor="end">цена = справедливой</text>
    <text x="${sx(1.2e8)}" y="${sy(2.5e5)}" font-size="11.5" fill="var(--text-secondary)" text-anchor="end">ниже линии — рынок ценит дешевле похожих</text>
    <text x="${(W + m.l) / 2}" y="${H - 6}" font-size="12" text-anchor="middle" fill="var(--text-secondary)">справедливая стоимость по модели, € млн</text>
    <text transform="translate(14,${(H - m.b) / 2}) rotate(-90)" font-size="12" text-anchor="middle" fill="var(--text-secondary)">рыночная стоимость (лето 2016), € млн</text>`;
  const mine = pts.filter((p) => p.team === S.team), rest = pts.filter((p) => p.team !== S.team);
  const dot = (p, r, fill, cls) => `<circle class="${cls}" data-id="${p.id}" cx="${sx(p.fair)}" cy="${sy(clamp(p.value, 10 ** lo, 10 ** hi))}" r="${r}" fill="${fill}" stroke="var(--surface-1)" stroke-width="1"/>`;
  g += rest.map((p) => dot(p, 3.4, "var(--text-muted)", "pt o")).join("") + mine.map((p) => dot(p, 5, "var(--series-1)", "pt")).join("");
  if (S.cand) g += `<circle cx="${sx(S.cand.fair)}" cy="${sy(S.cand.value)}" r="8" fill="none" stroke="var(--series-2)" stroke-width="2.5"/>`;
  const under = rest.filter((p) => p.age <= 29).sort((a, b) => b.gap - a.gap).slice(0, 12);
  el.innerHTML = `<h2>Справедливая стоимость</h2>
    <p class="small muted">Модель (${vm.chosen === "boosting" ? "градиентный бустинг" : "гребневая регрессия"}) учит, сколько рынок платит за игроков с таким возрастом, минутами, ролью, результативностью, командой и лигой. Оценка каждого игрока — от модели, которая его не видела (5-кратная кросс-валидация). R² ${fmt(chosen.r2, 2)}, типичная ошибка ×${fmt(chosen.median_x, 2)}, ${vm.n} игроков.</p>
    <div class="card" style="padding:8px"><svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" id="vscatter">${g}</svg>
      <div class="row small" style="gap:16px;padding:0 8px 6px"><span><span class="dot" style="background:var(--series-1)"></span> ${esc(S.team)}</span><span><span class="dot" style="background:var(--text-muted)"></span> остальные игроки (≥900 мин)</span>${S.cand ? `<span><span class="dot" style="border:2px solid var(--series-2)"></span> выбранный кандидат</span>` : ""}</div></div>
    <h3>Самые недооценённые (до 29 лет)</h3>
    <div class="scroll-x"><table><tr><th>Игрок</th><th>Роль</th><th class="num">Возраст</th><th class="num">Цена</th><th class="num">Справедл.</th><th class="num">Справедл. / цена</th></tr>
      ${under.map((p) => `<tr><td><b>${esc(p.name)}</b><div class="small muted">${esc(p.team)} · ${p.team_league}</div></td><td>${S.index.groups[p.group]}</td><td class="num">${fmt(p.age)}</td><td class="num">${money(p.value)}</td><td class="num">${money(p.fair)}</td><td class="num">${fmt(p.fair / p.value, 1)}</td></tr>`).join("")}</table></div>
    <p class="small muted">Разрыв — не обязательно ошибка рынка: туда попадает всё, чего модель не видит (травмы, контракт, репутация). Поэтому методика проверяется на будущих сезонах отдельно.</p>`;
  const byId = new Map(pts.map((p) => [p.id, p]));
  $$("#vscatter .pt", el).forEach((c) => {
    c.addEventListener("mouseenter", (e) => { const p = byId.get(+c.dataset.id);
      showTip(e, `<b>${esc(p.name)}</b> · ${esc(p.team)}<br>${S.index.groups[p.group]}, ${fmt(p.age)} лет<br>цена ${money(p.value)} · справедливая ${money(p.fair)}`); });
    c.addEventListener("mousemove", moveTip); c.addEventListener("mouseleave", hideTip);
  });
}

// ---------------------------------------------------------------- squad return
const pct = (v) => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmt(Math.abs(v) * 100)}%`;
function perYear(rets) {                              // geometric mean of yearly returns; null if any year is missing
  if (!rets.length || rets.some((v) => v == null)) return null;
  return rets.reduce((p, v) => p * (1 + v), 1) ** (1 / rets.length) - 1;
}
function barPath(x, w, y0, y1) {                      // a bar from the baseline y0 to y1, rounded only at the data end
  const h = Math.abs(y1 - y0), r = Math.min(4, h / 2, w / 2), up = y1 < y0;
  if (h < 0.5) return "";
  return up ? `M${x},${y0} V${y1 + r} Q${x},${y1} ${x + r},${y1} H${x + w - r} Q${x + w},${y1} ${x + w},${y1 + r} V${y0} Z`
    : `M${x},${y0} V${y1 - r} Q${x},${y1} ${x + r},${y1} H${x + w - r} Q${x + w},${y1} ${x + w},${y1 - r} V${y0} Z`;
}

function panelFinance(el) {
  const all = S.club.finance?.seasons ?? [], dec = S.index.decision_season;
  if (!all.length) { el.innerHTML = `<div class="empty">Нет данных о составе клуба в Transfermarkt</div>`; return; }
  const before = all.filter((s) => s.season <= dec), shown = S.future ? all : before;
  const now = before[before.length - 1], ru = S.index.leagues.find((l) => l.name === S.league).ru;
  const known = before.filter((s) => s.ret != null);          // a promoted club has no return for its seasons below
  const mine = perYear(known.map((s) => s.ret)), med = perYear(known.map((s) => s.median));
  // place among this league's clubs by return per year over the same seasons (clubs with every season in the league)
  const peers = Object.entries(S.leagues[S.league].clubs)
    .map(([t, c]) => [t, perYear((c.finance?.seasons ?? []).filter((s) => s.season <= dec).map((s) => s.ret))])
    .filter(([, v]) => v != null).sort((a, b) => b[1] - a[1]);
  const place = peers.findIndex(([t]) => t === S.team) + 1;
  S.finSeason = shown.some((s) => s.season === S.finSeason) ? S.finSeason : now.season;

  // chart: the club's return per season (bars) and the league median (tick)
  const W = 640, H = 250, m = { l: 46, r: 12, t: 26, b: 30 };
  const vals = shown.flatMap((s) => [s.ret, s.median]).filter((v) => v != null);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), span = hi - lo || 0.1;
  const step = span <= 0.6 ? 0.1 : span <= 1.2 ? 0.2 : 0.5;
  const y0v = Math.floor(lo / step - 0.6) * step, y1v = Math.ceil(hi / step + 0.6) * step;   // room for the labels
  const sy = (v) => m.t + (y1v - v) / (y1v - y0v) * (H - m.t - m.b);
  const band = (W - m.l - m.r) / shown.length, bw = Math.min(46, band * 0.42);
  let g = "";
  for (let v = y0v; v <= y1v + 1e-9; v += step) {
    g += `<line x1="${m.l}" y1="${sy(v)}" x2="${W - m.r}" y2="${sy(v)}" stroke="${Math.abs(v) < 1e-9 ? "var(--text-muted)" : "var(--line-soft)"}"/>
      <text x="${m.l - 8}" y="${sy(v) + 4}" font-size="11" text-anchor="end" fill="var(--text-secondary)">${pct(Math.round(v * 100) / 100)}</text>`;
  }
  const firstAfter = shown.findIndex((s) => s.season > dec);
  if (firstAfter > 0) {
    const x = m.l + firstAfter * band;
    g += `<rect x="${x}" y="${m.t - 18}" width="${W - m.r - x}" height="${H - m.b - m.t + 18}" fill="var(--surface-2)" opacity=".7"/>
      <line x1="${x}" y1="${m.t - 18}" x2="${x}" y2="${H - m.b}" stroke="var(--text-muted)" stroke-dasharray="4 4"/>
      <text x="${x + 8}" y="${m.t - 6}" font-size="11.5" fill="var(--text-secondary)">что было дальше</text>
      <text x="${x - 8}" y="${m.t - 6}" font-size="11.5" text-anchor="end" fill="var(--text-secondary)">решение: лето 2016</text>`;
  }
  shown.forEach((s, k) => {
    const cx = m.l + (k + 0.5) * band, sel = s.season === S.finSeason;
    if (s.ret != null) {
      // the value sits beyond both the bar end and the median tick, so the two never overlap
      const ends = [sy(s.ret), sy(0), ...(s.median != null ? [sy(s.median)] : [])];
      g += `<path d="${barPath(cx - bw / 2, bw, sy(0), sy(s.ret))}" fill="var(--series-1)"/>
        <text x="${cx}" y="${s.ret >= 0 ? Math.min(...ends) - 7 : Math.max(...ends) + 16}" font-size="12" font-weight="650" text-anchor="middle" fill="var(--text-primary)">${pct(s.ret)}</text>`;
    } else g += `<text x="${cx}" y="${sy(0) - 6}" font-size="11" text-anchor="middle" fill="var(--text-muted)">${s.squad == null ? "вне высшей лиги" : "нет прошлого сезона"}</text>`;
    if (s.median != null) g += `<line x1="${cx - bw / 2 - 7}" x2="${cx + bw / 2 + 7}" y1="${sy(s.median)}" y2="${sy(s.median)}" stroke="var(--text-primary)" stroke-width="2.5" stroke-linecap="round"/>`;
    g += `<text x="${cx}" y="${H - m.b + 18}" font-size="12" text-anchor="middle" fill="${sel ? "var(--text-primary)" : "var(--text-secondary)"}" font-weight="${sel ? 650 : 400}">${s.label}</text>
      <rect class="hit" data-s="${s.season}" x="${m.l + k * band}" y="${m.t - 18}" width="${band}" height="${H - m.t + 18}" fill="transparent" style="cursor:pointer"/>`;
  });

  const sel = shown.find((s) => s.season === S.finSeason);
  const moverList = (rows, empty) => rows.length ? rows.map(([n, a, b]) => `<div class="row spread small"><span>${esc(n)}</span><span class="muted">${money(a)} → <b style="color:var(--text-primary)">${money(b)}</b></span></div>`).join("") : `<div class="small muted">${empty}</div>`;
  el.innerHTML = `<h2>Доходность состава</h2>
    <p class="small muted">Насколько за сезон подорожали игроки, которые остались в клубе, — как доходность портфеля без покупок и продаж. Считается по рыночным стоимостям Transfermarkt на конец сезона; сравнение — с медианой клубов ${esc(ru)} в том же сезоне, потому что весь рынок дорожает неравномерно.</p>
    <div class="kpis" style="margin:12px 0">
      ${kpi(money(now.value), "стоимость состава", `${now.squad} игроков, конец ${now.label}`)}
      ${kpi(pct(mine), "доходность в год", known.length > 1 ? `${known[0].label} — ${known[known.length - 1].label}` : known.length ? `только ${known[0].label}` : "клуб не был в высшей лиге")}
      ${kpi(pct(med), `медиана ${esc(ru)}`, "та же мера по клубам лиги")}
      ${kpi(place ? `${place}-е` : "—", "место в лиге", place ? `из ${peers.length} клубов с полным рядом` : "нет полного ряда сезонов")}
    </div>
    <div class="card" style="padding:8px"><svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" id="fchart">${g}</svg>
      <div class="row small" style="gap:16px;padding:0 8px 6px"><span><span class="dot" style="background:var(--series-1);border-radius:3px"></span> ${esc(S.team)}: доходность оставшихся игроков</span><span><span style="display:inline-block;width:16px;height:3px;background:var(--text-primary);vertical-align:middle;border-radius:2px"></span> медиана лиги</span></div></div>
    ${futureSwitch("сезоны 2016/17 и 2017/18")}
    <div class="scroll-x"><table><tr><th>Сезон</th><th class="num">Стоимость состава</th><th class="num">Доходность</th><th class="num">Медиана лиги</th><th class="num">Место</th><th class="num">Пришли</th><th class="num">Ушли</th></tr>
      ${shown.map((s) => `<tr class="click ${s.season === S.finSeason ? "on" : ""}" data-s="${s.season}"><td><b>${s.label}</b>${s.season > dec ? `<div class="small muted">после решения</div>` : ""}</td>
        ${s.squad == null ? `<td colspan="6" class="muted">клуб играл вне высшей лиги — в данных этого сезона нет</td>`
          : `<td class="num">${money(s.value)}<div class="small muted">${s.squad} игроков</div></td>
        <td class="num"><b>${pct(s.ret)}</b><div class="small muted">${s.stayed == null ? "не с чем сравнить" : `${s.stayed} остались`}</div></td>
        <td class="num">${pct(s.median)}</td><td class="num">${s.rank ? `${s.rank} из ${s.of}` : "—"}</td>
        <td class="num">${s.joined == null ? "—" : `${s.joined} · ${money(s.joined_value)}`}</td><td class="num">${s.left == null ? "—" : `${s.left} · ${money(s.left_value)}`}</td>`}</tr>`).join("")}</table></div>
    <p class="small muted">Пришли и ушли — по рыночной стоимости (пришедшие — на конец сезона, ушедшие — на конец предыдущего), а не по суммам сделок.</p>
    ${sel && sel.ret != null ? `<h3>Кто двигал доходность в ${sel.label}</h3>
      <div class="card" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px 24px">
        <div><div class="small" style="margin-bottom:4px"><b>Подорожали сильнее всех</b></div>${moverList(sel.up, "никто не подорожал")}</div>
        <div><div class="small" style="margin-bottom:4px"><b>Подешевели сильнее всех</b></div>${moverList(sel.down, "никто не подешевел")}</div>
      </div>` : ""}
    <div class="callout">Это не выручка и не прибыль: их нет в открытых данных, а в таблице трансферов Transfermarkt не хватает крупных сделок (нет, например, продажи Давида Луиса за €49,5 млн в 2014). Зарплаты не учтены. Рыночная стоимость — оценка экспертов Transfermarkt, а не цена сделки. Игрок, пропустивший весь сезон, считается ушедшим.</div>`;
  const pick = (s) => { S.finSeason = +s; renderPanel(); };
  $$("#fchart .hit", el).forEach((h) => {
    const s = shown.find((x) => x.season === +h.dataset.s);
    h.onclick = () => pick(h.dataset.s);
    h.addEventListener("mouseenter", (e) => showTip(e, s.ret == null
      ? `<b>${s.label}</b><br>${s.squad == null ? "клуб играл вне высшей лиги — данных нет" : "в прошлом сезоне клуб был вне высшей лиги — не с чем сравнить"}`
      : `<b>${s.label}</b><br>остались ${s.stayed} игроков: ${money(s.v0)} → ${money(s.v1)} (${pct(s.ret)})<br>медиана ${esc(ru)}: ${pct(s.median)}${s.rank ? ` · место ${s.rank} из ${s.of}` : ""}<br>пришли ${s.joined} на ${money(s.joined_value)} · ушли ${s.left} на ${money(s.left_value)}`));
    h.addEventListener("mousemove", moveTip); h.addEventListener("mouseleave", hideTip);
  });
  $$("tr[data-s]", el).forEach((r) => r.onclick = () => pick(r.dataset.s));
  bindFuture(el);
}

function panelMethod(el) {
  const r = S.index.rules;
  el.innerHTML = `<div class="method">
    <h2>Как это работает</h2>
    <p><strong>Вопрос.</strong> Летом 2016 спортивный директор готовит трансферное окно. Какие позиции слабые, какой игрок нужен на каждую и кто из подходящих стоит дешевле, чем должен? Используется только то, что было известно тогда: события матчей сезона 2015/16 и рыночные стоимости до 30.06.2016.</p>
    <ol>
      <li><strong>Расстановка.</strong> Схема — та, в которой команда провела больше всего игрового времени; точка игрока — среднее место его действий с мячом.</li>
      <li><strong>Сила позиции.</strong> У каждой роли свои показатели на 90 минут (у нападающего — xG без пенальти, реализация, удары…, у защитника — отборы, воздух, передачи вперёд). Каждый переводится в процентиль среди игроков той же роли с ≥${r.min_minutes} мин; оценка позиции — среднее по игрокам, взвешенное по минутам.</li>
      <li><strong>Потребность.</strong> Позиция ниже медианы топ-6 своей лиги больше чем на ${50 - r.weak} пунктов, или основному игроку ${r.old}+ лет. Требования к новичку — все показатели роли, а слабые места текущего — с весом до ×2.</li>
      <li><strong>Кандидаты.</strong> Все игроки этой роли в открытых данных топ-5 лиг (Бундеслига — только «Байер»): не из своего клуба, нужной стороны (≥${r.side_share * 100}% минут), моложе порога, по цене, лучше текущего.</li>
      <li><strong>Недооценённость.</strong> Модель справедливой стоимости; разрыв = log₁₀(справедливая / рыночная).</li>
      <li><strong>Рейтинг.</strong> TOPSIS по соответствию, недооценённости, возрасту и минутам в роли (метод из Assignment 4), устойчивость — по случайным наборам весов; план — лучший набор под бюджет.</li>
      <li><strong>Перестроение.</strong> Модель формы: по тысячам отрезков матчей видно, как стоят остальные, когда один игрок стоит выше или шире. Это связь из данных, а не симулятор тактики.</li>
      <li><strong>Доходность состава.</strong> Состав на конец сезона — игроки, чей последний матч сезона был за клуб (Transfermarkt). Доходность — на сколько за сезон изменилась рыночная стоимость тех, кто остался, в сравнении с медианой клубов лиги.</li>
      <li><strong>ИИ-помощник.</strong> Claude отвечает на вопросы, но числа не придумывает: вызывает инструменты, которые считают так же, как эта страница (кандидаты, план, карточки игроков и клубов). Видит, что открыто на экране, и может сам открыть нужное; для фактов вне данных — поиск в интернете.</li>
    </ol>
    <h3>Ловушки</h3>
    <ul>
      <li><strong>Утечка из будущего:</strong> стоимости и события — только до лета 2016; проверка рекомендаций на 2016–2018 — отдельным шагом.</li>
      <li><strong>Разные лиги:</strong> поправки на силу лиги нет — 20 голов во Франции и в Англии весят одинаково. Учитывайте лигу при чтении.</li>
      <li><strong>Стиль команды:</strong> у игроков доминирующих клубов больше атакующих действий; оборонительные — с поправкой на владение соперника, атакующие — без.</li>
      <li><strong>Вратари:</strong> в открытых данных нет xG по точке удара в створ, оценка вратаря грубая и шумная за один сезон.</li>
      <li><strong>Мало минут:</strong> показатели надёжны от ${r.min_minutes} минут в роли.</li>
      <li><strong>Корреляция ≠ причинность:</strong> и перестроение, и «где забиваем / пропускаем» — описания, а не доказательство причин.</li>
      <li><strong>Доходность — не прибыль:</strong> выручки, зарплат и полной таблицы трансферов в открытых данных нет, поэтому доходность считается по рыночным стоимостям, а не по деньгам клуба.</li>
    </ul>
    <p class="small">Данные: StatsBomb Open Data (лицензия для исследований, источник указан на каждой странице), transfermarkt-datasets (CC0).</p></div>`;
}

// ---------------------------------------------------------------- club loading and boot
async function selectClub(league, team) {
  const info = S.index.leagues.find((l) => l.name === league);
  if (!S.leagues[league]) {
    try { S.leagues[league] = await load(info.file); }
    catch (e) {
      $("#panel").innerHTML = `<div class="empty">Не удалось загрузить данные: ${esc(info.ru)}<br>${esc(e.message)}</div>`;
      if (S.league) fillClubs();                  // the selects go back to the club still on the pitch
      return false;
    }
  }
  S.league = league; S.team = team; S.club = S.leagues[league].clubs[team];
  S.players = new Map(S.club.players.map((p) => [p.id, p]));
  S.base = S.club.slots.map((s) => [s.x, s.y]);
  S.fixed = {}; S.whatIf = {}; S.lastMoved = null; S.slot = null; S.player = null; S.cand = null; S.manager = 0;
  try { history.replaceState(null, "", `#${encodeURIComponent(league)}/${encodeURIComponent(team)}`); } catch { /* file:// */ }
  fillClubs();
  renderPitch(); setTab(S.tab === "player" || S.tab === "replace" ? "club" : S.tab);
  return true;
}
function fillClubs() {
  const l = S.index.leagues.find((x) => x.name === S.league);
  $("#league").innerHTML = S.index.leagues.map((x) => `<option value="${esc(x.name)}" ${x.name === S.league ? "selected" : ""}>${x.ru}</option>`).join("");
  $("#club").innerHTML = l.clubs.map((c) => `<option value="${esc(c.team)}" ${c.team === S.team ? "selected" : ""}>${c.place}. ${esc(c.team)}</option>`).join("");
}

function resetChoices() {                            // filters, weights and budget as the method sets them
  S.weights = Object.fromEntries(Object.entries(S.index.criteria).map(([k, c]) => [k, Math.round(c.weight * 100)]));
  S.filters = { maxAge: S.index.rules.max_age, maxPrice: S.index.rules.max_price / 1e6, better: true,
                leagues: new Set(S.index.candidate_leagues.map((l) => l.name)) };
  S.compare = "player"; S.budget = 120;
}

async function boot() {
  const theme = new URLSearchParams(location.search).get("theme") || store.get("fi-theme");
  if (theme) document.documentElement.dataset.theme = theme;
  $("#theme").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark"; store.set("fi-theme", dark ? "light" : "dark");
    renderPitch(); renderPanel();
  };
  try {
    [S.index, S.pool] = await Promise.all([load("index.json"), load("pool.json")]);
  } catch (e) {
    $("#panel").innerHTML = `<div class="empty">Нет данных: сначала соберите их — <code>python -m app.build</code><br>${esc(e.message)}</div>`;
    return;
  }
  resetChoices();
  $$("#views button").forEach((b) => b.onclick = () => { S.view = b.dataset.view; renderPitch(); });
  $$("#tabs button").forEach((b) => b.onclick = () => setTab(b.dataset.tab));
  $("#league").onchange = (e) => { const l = S.index.leagues.find((x) => x.name === e.target.value); selectClub(l.name, l.clubs[0].team); };
  $("#club").onchange = (e) => selectClub(S.league, e.target.value);
  const [hl, ht] = decodeURIComponent(location.hash.slice(1)).split("/");
  const l = S.index.leagues.find((x) => x.name === hl) || S.index.leagues.find((x) => x.name === "Premier League") || S.index.leagues[0];
  const t = l.clubs.find((c) => c.team === ht) ? ht : l.clubs.find((c) => c.team === "Chelsea") ? "Chelsea" : l.clubs[0].team;
  if (!await selectClub(l.name, t)) return;
  const q = new URLSearchParams(location.search);
  S.future = q.get("future") === "1";
  if (q.get("view")) { S.view = q.get("view"); renderPitch(); }
  const si = S.club.slots.findIndex((s) => s.code === q.get("slot"));
  if (si >= 0) selectSlot(si, q.get("tab") || "player");
  else if (q.get("tab")) setTab(q.get("tab"));
  for (const mv of q.getAll("move")) {
    const [code, xy] = mv.split(":"), k = S.club.slots.findIndex((s) => s.code === code);
    if (k >= 0) { S.fixed[k] = xy.split(",").map(Number); S.lastMoved = k; }
  }
  if (q.getAll("move").length) renderPitch();
  if (q.get("cand") && S.tab === "replace") { const c = $(`tr[data-k="${+q.get("cand")}"]`); if (c) c.click(); }
  initAI();
}

// ---------------------------------------------------------------- AI assistant
// Talks to app/server.py (the API key stays on the server). A static host such as GitHub Pages has no server,
// so there the panel only says how to run it.
const AI = { chatId: null, busy: false, status: null };

async function initAI() {
  try { const r = await fetch("api/ai"); AI.status = r.ok ? await r.json() : null; } catch { AI.status = null; }
  $("#ai-fab").hidden = false;
  $("#ai-fab").onclick = () => openAI(true);
  $("#ai-close").onclick = () => openAI(false);
  $("#ai-new").onclick = () => {
    if (AI.busy) return;
    AI.chatId = null;
    $$("#ai-log > .msg-user, #ai-log > .msg-ai").forEach((m) => m.remove());
    $("#ai-hello").hidden = false;
    fillChips();
  };
  const input = $("#ai-input");
  input.oninput = () => { input.style.height = "auto"; input.style.height = Math.min(140, input.scrollHeight) + "px"; };
  input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ai-form").requestSubmit(); } };
  $("#ai-form").onsubmit = (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (q) { input.value = ""; input.style.height = "auto"; askAI(q); }
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#ai").hidden) openAI(false); });
  const ready = AI.status?.enabled;
  input.disabled = $("#ai-send").disabled = !ready;
  $("#ai-sub").textContent = ready ? `Claude · данные приложения${AI.status.web_search ? " + веб-поиск" : ""}` : "не подключён";
  if (!ready) $("#ai-hello").insertAdjacentHTML("beforeend", `<div class="ai-note">${AI.status
    ? "На сервере нет ключа API: добавьте <code>ANTHROPIC_API_KEY</code> в файл <code>.env</code> проекта и перезапустите сервер."
    : "Помощнику нужен сервер, на котором хранится ключ API (в браузере его держать нельзя). Запустите страницу локально: <code>python -m app.server</code> и откройте http://127.0.0.1:8200."}</div>`);
}
function openAI(open) {
  $("#ai").hidden = !open;
  document.body.classList.toggle("ai-open", open);
  if (open) { fillChips(); if (!$("#ai-input").disabled) $("#ai-input").focus(); }
}
function fillChips() {
  const c = S.club, need = c.slots.find((s) => s.need);
  const qs = [
    "Объясни простыми словами, что показано на экране",
    `Почему ${S.team} занял ${c.summary.place}-е место?`,
    need ? `Кем заменить: ${(SLOT_RU[need.code] ?? need.code).toLowerCase()} (${need.code})?` : "Какие позиции у клуба самые слабые?",
    "Где команда забивает и где пропускает?",
    "Доходность состава: клуб растёт в цене или дешевеет?",
    "Кто самый недооценённый нападающий до 24 лет?",
  ];
  $("#ai-chips").innerHTML = qs.map((q) => `<button type="button" class="chip" data-ask="${esc(q)}">${esc(q)}</button>`).join("");
  $$("#ai-chips [data-ask]").forEach((b) => b.onclick = () => askAI(b.dataset.ask));
}

function aiState() {
  const slot = S.slot != null ? S.club.slots[S.slot] : null;
  return {
    league: S.league, team: S.team, tab: S.tab, view: S.view, bench: S.bench, future: S.future,
    slot: slot?.code ?? null, player: S.player ? nameOf(S.player) : null, compare: S.compare,
    candidate: S.cand ? `${S.cand.name} (${S.cand.team})` : null,
    lineup_changes: Object.entries(S.whatIf).map(([i, c]) => `${S.club.slots[i].code}: ${c.name}`),
    moved: Object.keys(S.fixed).filter((i) => !S.whatIf[i]).map((i) => S.club.slots[i].code),
    filters: { max_age: S.filters.maxAge, max_price_m: S.filters.maxPrice, leagues: [...S.filters.leagues], only_better: S.filters.better },
    weights: S.weights, budget: S.budget,
  };
}

async function showFromAI(ev) {
  // the same paths as the user's own clicks
  if (ev.team && ev.team !== S.team && !await selectClub(ev.league, ev.team)) return;
  if (ev.future != null) S.future = ev.future;
  if (ev.view) S.view = ev.view;
  const i = ev.slot ? S.club.slots.findIndex((s) => s.code === ev.slot) : -1;
  if (i >= 0) selectSlot(i, ev.tab || "player");
  else { renderPitch(); ev.tab ? setTab(ev.tab) : renderPanel(); }
}

async function askAI(question) {
  openAI(true);
  if (AI.busy || !AI.status?.enabled) return;
  AI.busy = true;
  $("#ai-send").disabled = true;
  $("#ai-hello").hidden = true;
  const log = $("#ai-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg-user">${esc(question)}</div>`);
  const box = document.createElement("div");
  box.className = "msg-ai";
  box.innerHTML = `<ul class="steps"></ul><details class="think" hidden><summary>Ход рассуждений</summary><div></div></details><div class="md"></div><div class="wait">Думаю…</div>`;
  log.appendChild(box);
  const steps = $(".steps", box), think = $("details.think", box), out = $(".md", box), stepEl = {};
  let text = "", thinking = "";
  const stick = () => { if (log.scrollHeight - log.scrollTop - log.clientHeight < 160) log.scrollTop = log.scrollHeight; };
  log.scrollTop = log.scrollHeight;
  const note = (t, cls = "note") => { const li = document.createElement("li"); li.className = cls; li.innerHTML = "<i></i><span></span>"; $("span", li).textContent = t; steps.appendChild(li); };
  const handle = (ev) => {
    if (ev.type === "chat") { AI.chatId = ev.chat_id; return; }
    if (ev.type !== "thinking" && ev.type !== "done") $(".wait", box)?.remove();
    if (ev.type === "thinking") { thinking += ev.text; think.hidden = false; $("div", think).textContent = thinking; }
    else if (ev.type === "text") { text += ev.text; out.innerHTML = md(text); }
    else if (ev.type === "step") {
      let li = stepEl[ev.id];
      if (!li) { li = document.createElement("li"); li.innerHTML = "<i></i><span></span>"; steps.appendChild(li); stepEl[ev.id] = li; }
      li.className = ev.status === "start" ? "" : ev.status;
      if (ev.label) $("span", li).textContent = ev.label;
    } else if (ev.type === "show") {
      showFromAI(ev);
      note("Открыл на экране: " + [ev.team, ev.slot, ev.tab && $(`#tabs [data-tab="${ev.tab}"]`)?.textContent,
        ev.view && $(`#views [data-view="${ev.view}"]`)?.textContent].filter(Boolean).join(" · "));
    } else if (ev.type === "sources") {
      box.insertAdjacentHTML("beforeend", `<div class="sources"><span>Поиск нашёл:</span>${ev.items.map((s) =>
        `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>`).join("")}</div>`);
    } else if (ev.type === "error") box.insertAdjacentHTML("beforeend", `<p class="err">${esc(ev.message)}</p>`);
    stick();
  };
  try {
    const r = await fetch("api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: AI.chatId, message: question, state: aiState() }),
    });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || `HTTP ${r.status}`); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const line of chunk.split("\n")) if (line.startsWith("data: ")) { try { handle(JSON.parse(line.slice(6))); } catch (err) { console.warn(err); } }
      }
    }
  } catch (e) {
    handle({ type: "error", message: "Не удалось получить ответ: " + e.message });
  } finally {
    $(".wait", box)?.remove();
    $$(".steps li", box).forEach((li) => { if (!li.className) li.className = "done"; });   // nothing is still running
    AI.busy = false;
    $("#ai-send").disabled = false;
    stick();
  }
}

// a small, safe markdown subset: paragraphs, lists, tables, headings, bold, italics, code, links
function md(src) {
  const inline = (s) => s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, `<a href="$2" target="_blank" rel="noopener">$1</a>`);
  const lines = esc(src).split("\n");
  let html = "", list = null, para = [], table = [];
  const flushPara = () => { if (para.length) { html += `<p>${inline(para.join("<br>"))}</p>`; para = []; } };
  const flushList = () => { if (list) { html += `<${list.tag}>${list.items.map((x) => `<li>${inline(x)}</li>`).join("")}</${list.tag}>`; list = null; } };
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
    if (rows.length) {
      html += `<div class="scroll-x"><table><tr>${rows[0].map((c) => `<th>${c}</th>`).join("")}</tr>`
        + rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</table></div>";
    }
    table = [];
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^\s*\|/.test(line)) { flushPara(); flushList(); table.push(line.trim()); continue; }
    flushTable();
    let m;
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if ((m = line.match(/^#{1,6}\s+(.*)/))) { flushPara(); flushList(); html += `<h4>${inline(m[1])}</h4>`; continue; }
    if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { flushPara(); if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; } list.items.push(m[1]); continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { flushPara(); if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; } list.items.push(m[1]); continue; }
    if (list && /^\s{2,}/.test(raw)) { list.items[list.items.length - 1] += " " + line.trim(); continue; }
    flushList();
    para.push(line);
  }
  flushPara(); flushList(); flushTable();
  return html;
}

boot();
