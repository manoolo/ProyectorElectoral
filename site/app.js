// Proyector electoral: una elección por página, elegida desde el menú (site/elecciones.json).
// Los datos de cada elección los escriben run_live.py / replay.py; los mapas, build_maps.py.
"use strict";
const STATE = {reg:null, paises:[], eid:null, data:{}, idx:{}, playing:null, sort:"close", showAll:false,
               mode:"conteo", region:null, uq:"", usort:"votes", geo:{}, det:{}, cache:{}};
const $ = s => document.querySelector(s);
const pct = (x,d=1) => (x*100).toFixed(d).replace(".",",")+"%";
const pts = (x,d=1) => (x>=0?"+":"−")+Math.abs(x*100).toFixed(d).replace(".",",");
const esc = s => String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = n => Math.round(n).toLocaleString("es-AR");
const MESES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
const fecha = s => { const [y,m,d] = s.split("-").map(Number); return `${d} ${MESES[m-1]} ${y}`; };
const norm = s => s.normalize("NFD").replace(/[̀-ͯ]/g,"").toLowerCase();

async function getJSON(url){ try { const r = await fetch(url,{cache:"no-store"}); return r.ok ? await r.json() : null; } catch(e){ return null; } }

/* ---------------- registro y menú */
const election = () => STATE.reg.elections.find(e => e.id === STATE.eid);
// carpeta del mapa: la del JSON (config.geo.map) o la del registro; sin resultados por unidad igual se dibuja por región
const mapId = d => (d.config.geo && d.config.geo.map) || (election() || {}).map;

function route(){
  const h = decodeURIComponent(location.hash.slice(1)), E = STATE.reg.elections;
  if (h.startsWith("pais-")) { STATE.eid = null; STATE.pais = h.slice(5); return; }
  STATE.pais = null;
  let e = E.find(x => x.id === h);
  if (!e && h) {           // #br, #us, #ar: la elección más relevante de ese país
    const rank = {live:0, upcoming:2, replay:1};
    e = E.filter(x => x.country === h).sort((a,b) => rank[a.status]-rank[b.status])[0];
    if (!e) { STATE.eid = null; STATE.pais = h; return; }
  }
  STATE.eid = (e || E.find(x => x.id === STATE.reg.default) || E[0]).id;
}

function menuList(){
  const q = norm($("#menuq").value.trim()), E = STATE.reg.elections;
  const hit = e => !q || norm(`${e.name} ${e.office} ${e.year} ${e.country}`).includes(q);
  const item = e => `<a class="mitem" href="#${e.id}" ${e.id===STATE.eid?'aria-current="true"':""}><span>${esc(e.name)} ${e.year}</span><small>${esc(e.office)}</small></a>`;
  const groups = [["En vivo y próximas", E.filter(e => e.status !== "replay" && hit(e))], ["Repeticiones", E.filter(e => e.status === "replay" && hit(e))]];
  let h = groups.filter(g => g[1].length).map(([t,l]) => `<div class="mgroup">${t}</div>${l.map(item).join("")}`).join("");
  const have = new Set(E.map(e => e.country));
  const others = STATE.paises.filter(([c,n]) => !have.has(c) && (q ? norm(n).includes(q) : false)).slice(0, 12);
  if (others.length) h += `<div class="mgroup">Preparar otro país</div>` + others.map(([c,n]) => `<a class="mitem" href="#pais-${c}"><span>${esc(n)}</span><small>sin configurar</small></a>`).join("");
  if (!q) h += `<p class="mgroup" style="text-transform:none;letter-spacing:0;font-weight:500">Escribí el nombre de cualquier país para ver qué hace falta para lanzar su elección.</p>`;
  if (!h) h = `<p class="mgroup" style="text-transform:none;letter-spacing:0">Sin resultados.</p>`;
  $("#menulist").innerHTML = h;
}
function menuOpen(open){
  $("#menu").hidden = !open; $("#menubtn").setAttribute("aria-expanded", open);
  if (open) { menuList(); $("#menuq").focus(); }
}

/* ---------------- datos */
async function load(e){
  if (STATE.data[e.id] !== undefined) return STATE.data[e.id];
  const pre = window.__DATA__ && window.__DATA__[e.id];
  const d = pre || (window.__DATA__ ? null : await getJSON(e.data));
  STATE.data[e.id] = d || null;
  if (d) STATE.idx[e.id] = d.mode === "replay" ? Math.min(10, d.history.length-1) : d.history.length-1;
  return STATE.data[e.id];
}
async function geoNational(c){
  if (!STATE.geo[c]) STATE.geo[c] = (window.__GEO__ && window.__GEO__[c]) || await getJSON(`geo/${c}.json`);
  return STATE.geo[c];
}
async function geoDetail(c, r){
  const k = c + "/" + r;
  if (!STATE.det[k]) STATE.det[k] = await getJSON(`geo/${c}/${encodeURIComponent(r)}.json`);
  return STATE.det[k];
}

// Estado del mapa en el corte idx: se acumulan los cambios por unidad de los frames 0..idx.
function mapState(d, idx){
  if (!d.geo) return null;
  const n = d.geo.ids.length, C = Object.keys(d.config.candidates).length;
  let s = STATE.cache[STATE.eid];
  if (!s || s.d !== d || s.k > idx) s = STATE.cache[STATE.eid] = {d, k:-1, F:new Int16Array(n), V:new Int16Array(n*C), N:new Float64Array(n), has:new Uint8Array(n), any:false, C};
  for (let k = s.k + 1; k <= idx; k++) {
    const m = d.history[k].map; if (!m) continue;
    s.any = true;
    m.i.forEach((i,j) => { s.F[i] = m.f[j]; s.N[i] = m.n ? m.n[j] : 0; s.has[i] = 1; for (let c = 0; c < C; c++) s.V[i*C+c] = m.v[j][c]; });
  }
  s.k = idx;
  if (!s.pos) { s.pos = new Map(d.geo.ids.map((id,i) => [id,i])); }
  return s;
}

/* ---------------- colores */
let PAPER = [255,255,255];
function readPaper(){
  const c = getComputedStyle(document.body).backgroundColor.match(/\d+/g);
  if (c) PAPER = c.slice(0,3).map(Number);
}
const hex = h => [1,3,5].map(i => parseInt(h.slice(i,i+2),16));
function tint(h, t){ const a = hex(h); return `rgb(${a.map((v,i) => Math.round(PAPER[i] + (v-PAPER[i])*t)).join(",")})`; }
const BINS = [[50,.38],[100,.56],[200,.78],[1e9,1]];      // margen en por mil → intensidad
const binT = m => BINS.find(b => m < b[0])[1];

/* ---------------- página */
async function render(){
  stop();
  const app = $("#app");
  if (STATE.pais) { app.innerHTML = setupView(STATE.pais); document.title = "Proyector electoral"; return; }
  const e = election(), d = await load(e);
  document.title = `${e.name} ${e.year}: ${e.office} · Proyector electoral`;
  if (!d) { app.innerHTML = emptyView(e); return; }
  STATE.region = null; STATE.uq = ""; STATE.showAll = false;
  const hasMap = !!mapId(d);
  app.innerHTML = `<div id="hdr"></div><div id="board" class="board"></div>
    ${d.history.length>1?`<div class="sticky"><div class="scrub" id="scrub"></div></div>`:""}
    ${hasMap?`<section id="mapsec"><h2 class="sec">Mapa de resultados</h2><div class="maptools"><div class="crumbs" id="crumbs"></div><div class="seg" id="modes" role="group" aria-label="Qué muestra el mapa"></div></div>
      <div class="mapbox" id="mapbox"><div class="loading">Cargando mapa…</div></div><div class="legend" id="mlegend"></div></section>`:""}
    <section id="tablesec"></section><section class="chart" id="chartsec"></section><section class="changes" id="changes"></section><section class="method" id="method"></section>`;
  if (d.history.length>1) scrubber(d);
  update();
  if (hasMap) buildMap();
}

function update(){
  const e = election(), d = STATE.data[e.id]; if (!d) return;
  const f = d.history[STATE.idx[e.id]], cfg = d.config, C = Object.keys(cfg.candidates);
  const order = C.map((n,i)=>i).sort((a,b)=>f.proj[b]-f.proj[a]);
  $("#hdr").innerHTML = header(e,d,f,cfg,C,order);
  $("#board").innerHTML = board(cfg,C,f,d,order);
  const so = $("#sout"); if (so) { so.textContent = `${pct(f.counted)} escrutado`; $("#slider").value = STATE.idx[e.id]; $("#play").textContent = STATE.playing?"Pausar":"Reproducir"; }
  if ($("#mapbox")) { tools(d,cfg,C,order); paint(); }
  $("#tablesec").innerHTML = STATE.region ? unitsTable(d,cfg,C,f,order) : regionsView(d,cfg,C,f,order);
  wireTable();
  $("#chartsec").innerHTML = `<h2 class="sec">Proyección y conteo a lo largo de la noche</h2>
    <div class="legend2">${order.slice(0,2).map(i=>`<span style="color:${cfg.colors[C[i]]}"><i></i>${esc(C[i])} proyectado</span><span style="color:${cfg.colors[C[i]]}"><i class="dash"></i>conteo</span>`).join("")}${d.truth?`<span><i class="dot"></i>resultado final</span>`:""}</div>
    <div class="svgwrap">${chart(d,cfg,C,order.slice(0,2))}</div>`;
  $("#changes").innerHTML = changesView(d,cfg,f);
  $("#method").innerHTML = d.backtest ? methodView(d) : "";
}

function header(e,d,f,cfg,C,order){
  const lead = C[order[0]], mg = f.margin;
  const pill = d.mode === "replay" ? `<span class="pill replay">Repetición</span>` : `<span class="pill live">En vivo</span>`;
  const head = d.mode === "replay"
    ? `Repetición: ${esc(/\d{4}/.test(cfg.title||"") ? cfg.title : `${e.name} ${e.year}`)}`
    : `${esc(lead)} ${mg && mg.p_a_ahead>0.95 ? "está proyectado adelante" : "va levemente arriba"} en ${esc(e.name)}`;
  const sub = d.mode === "replay"
    ? (d.replay_sub || `Reproduce el escrutinio de 2024 condado por condado, con la base 2020, en el orden aproximado de cierre por huso horario. Mové el control para ver qué decía la proyección en cada momento.`)
    : `Proyección del resultado final con ${pct(f.counted)} de los votos esperados ya escrutados. No es un resultado oficial.`;
  const upd = f.ts && /\d{4}-/.test(f.ts) ? `Actualizado ${new Date(f.ts).toLocaleString("es-AR",{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})} · ` : "";
  return `<div class="kicker">${pill}<span>${esc(e.name)} · ${esc(e.office)} · ${fecha(e.date)}</span></div>
    <h1 class="hed">${head}</h1><p class="dek">${sub}</p>
    <p class="meta">${upd}${pct(f.counted)} de los votos esperados escrutados · ${num(f.units[0])} de ${num(f.units[1])} ${esc(cfg.unit_label)} con datos</p>`;
}

function board(cfg,C,f,d,order){
  const a = order[0], b = order[1], mg = f.margin;
  const called = mg && mg.p_a_ahead > .995 && f.counted > .5;
  const top = (i, right) => `<div class="top1 ${right?"r":""}"><div class="nm">${esc(C[i])}${i===a&&called?`<span class="check" title="Proyectado ganador en votos">✓</span>`:""}</div>
      <div class="pc" style="color:${cfg.colors[C[i]]}">${pct(f.proj[i])}</div><div class="ci">${f.lo?`${pct(f.lo[i])}–${pct(f.hi[i])}`:"proyectado"}</div></div>`;
  const mid = cfg.rule_kind === "runoff" || cfg.rule === "brasil";
  const stack = order.map(i => `<div style="width:${f.proj[i]*100}%;background:${cfg.colors[C[i]]}" title="${esc(C[i])} ${pct(f.proj[i])}"></div>`).join("");
  const rows = order.map(i => `<div class="row"><span><span class="sw" style="background:${cfg.colors[C[i]]}"></span>${esc(C[i])}</span>
      <span>${pct(f.proj[i])} <span style="color:var(--muted)">proy. · ${pct(f.crude[i])} contado${d.truth?` · final ${pct(d.truth.shares[i])}`:""}</span></span></div>`).join("");
  return `<div><div class="tops">${top(a,false)}${top(b,true)}</div>
      <div class="stack" role="img" aria-label="Reparto proyectado del voto">${stack}${mid?`<span class="mid"></span>`:""}</div>
      <div class="stackcap"><span>Proyección del total</span>${mid?`<span>50%</span>`:""}</div>
      <div class="others">${rows}</div>
      ${mg ? `<p class="mline">Diferencia proyectada: ${esc(mg.a)} ${pts(mg.mid)} pts sobre ${esc(mg.b)} (${pts(mg.lo)} a ${pts(mg.hi)}). Probabilidad de que ${esc(mg.a)} termine adelante: ${pct(mg.p_a_ahead,0)}.</p>`:""}</div>
    ${outcome(cfg,C,f,d)}`;
}

function scrubber(d){
  const e = election();
  $("#scrub").innerHTML = `<button id="play" type="button">Reproducir</button>
    <input id="slider" type="range" min="0" max="${d.history.length-1}" value="${STATE.idx[e.id]}" aria-label="Momento del escrutinio">
    <output id="sout"></output>`;
  $("#slider").oninput = ev => { stop(); STATE.idx[e.id] = +ev.target.value; update(); };
  $("#play").onclick = togglePlay;
}

/* ---------------- mapa */
const MODES = [["conteo","Quién lidera"],["corrimiento","Corrimiento"],["proy","Proyección"],["escrutado","Escrutado"]];

function tools(d,cfg,C,order){
  const g = STATE.geo[mapId(d)];
  const rname = STATE.region ? regName(g, STATE.region) : null;
  $("#crumbs").innerHTML = STATE.region
    ? `<button type="button" id="back">${esc(election().name)}</button><span aria-hidden="true">›</span><strong>${esc(rname)}</strong>`
    : `<span style="color:var(--muted)">Tocá ${art(cfg.region_label)} ${esc(cfg.region_label.toLowerCase())} para ver sus ${esc(unitPl(g,cfg))}.</span>`;
  const b = $("#back"); if (b) b.onclick = () => setRegion(null);
  const a = order[0], bb = order[1], G = d.geo ? d.geo.groups : [], ga = G.indexOf(cfg.candidates[C[a]]), gb = G.indexOf(cfg.candidates[C[bb]]);
  const can = {corrimiento: ga >= 0 && gb >= 0 && ga !== gb, proy: !STATE.region};
  if (can[STATE.mode] === false) STATE.mode = "conteo";
  $("#modes").innerHTML = MODES.filter(([k]) => can[k] !== false).map(([k,l]) => `<button type="button" data-m="${k}" aria-pressed="${STATE.mode===k}">${l}</button>`).join("");
  $("#modes").querySelectorAll("button").forEach(x => x.onclick = () => { STATE.mode = x.dataset.m; update(); });
}
const art = l => /[aá]$|ón$|d$/.test(l.toLowerCase()) ? "una" : "un";
const regName = (g, r) => { const x = g && g.regions.find(o => o.id === r); return x ? x.n : r; };
function unitPl(g,cfg){ const u = (g && g.unit) || "Unidad"; return {Condado:"condados",Municipio:"municipios",Departamento:"departamentos"}[u] || cfg.unit_label; }

async function buildMap(){
  const e = election(), d = STATE.data[e.id], c = mapId(d), box = $("#mapbox");
  const g = await geoNational(c);
  if (!g) { box.innerHTML = `<p class="loading">No se encontró el mapa (site/geo/${esc(c)}.json). Corré <code>python build_maps.py ${esc(c)}</code>.</p>`; return; }
  let units = g.units, vb = [0,0,g.w,g.h], regs = g.regions;
  if (STATE.region) {
    const det = await geoDetail(c, STATE.region), R = g.regions.find(r => r.id === STATE.region);
    if (det) units = det.units.map(u => ({...u, r:STATE.region})); else units = g.units.filter(u => u.r === STATE.region);
    const bb = R.bb, w = bb[2]-bb[0], h = bb[3]-bb[1], p = Math.max(w,h)*.04;
    vb = [bb[0]-p, bb[1]-p, w+2*p, h+2*p]; regs = [R];
  }
  if (STATE.eid !== e.id) return;                 // cambió la elección mientras cargaba
  const s = mapState(d, STATE.idx[e.id]);
  STATE.units = units.map(u => ({...u, k: s ? s.pos.get(u.id) : undefined}));
  STATE.vb = vb;
  // nombres completos de las regiones, donde entran (un carácter ≈ 6,3 unidades del mapa)
  const fits = r => r.c && (r.bb[2]-r.bb[0]) > r.n.length*6.3 + 8 && (r.bb[3]-r.bb[1]) > 16;
  const lab = !STATE.region ? regs.filter(fits).map(r => `<text class="rl" x="${r.c[0]}" y="${r.c[1]+4}" text-anchor="middle">${esc(r.n)}</text>`).join("") : "";
  box.className = "mapbox" + (STATE.region ? " detail" : "");
  box.innerHTML = `<svg viewBox="${vb.map(v=>v.toFixed(1)).join(" ")}" role="img" aria-label="Mapa de ${esc(STATE.region?regName(g,STATE.region):e.name)} por ${esc((g.unit||"unidad").toLowerCase())}">
    <g id="gu">${STATE.units.map((u,j) => `<path class="u" d="${u.d}" data-j="${j}"/>`).join("")}</g>
    <g>${regs.map(r => `<path class="rg" d="${r.d}"/>`).join("")}</g><g id="ga"></g><g>${lab}</g></svg>`;
  STATE.paths = box.querySelectorAll("#gu path");
  const svg = box.querySelector("svg");
  svg.addEventListener("pointermove", ev => { if (ev.pointerType === "mouse") tipAt(ev); });
  svg.addEventListener("pointerleave", () => tipHide());
  svg.addEventListener("click", ev => {
    const p = ev.target.closest("path.u"); if (!p) return;
    const u = STATE.units[+p.dataset.j];
    if (!STATE.region) { tipHide(); setRegion(u.r); }
    else tipAt(ev, true);
  });
  update();                     // con la geometría ya cargada: nombres de región y enlaces de la tabla
}

function setRegion(r){
  STATE.region = r; STATE.uq = ""; STATE.showAll = false;
  if (r && STATE.mode === "proy") STATE.mode = "conteo";
  update(); buildMap();
  const m = $("#mapsec"); if (m && r) m.scrollIntoView({behavior:"smooth", block:"start"});
}

function paint(){
  const e = election(), d = STATE.data[e.id]; if (!STATE.paths || !d) return;
  const cfg = d.config, C = Object.keys(cfg.candidates), f = d.history[STATE.idx[e.id]];
  const s = mapState(d, STATE.idx[e.id]), order = C.map((n,i)=>i).sort((a,b)=>f.proj[b]-f.proj[a]);
  const a = order[0], b = order[1], NC = C.length, mode = STATE.mode;
  const col = C.map(n => cfg.colors[n] || "#8a8f98");
  const G = d.geo ? d.geo.groups : [], ga = G.indexOf(cfg.candidates[C[a]]), gb = G.indexOf(cfg.candidates[C[b]]), NG = G.length;
  const ridx = new Map(d.regions.map((r,i) => [r,i]));
  const box = $("#mapbox"); box.classList.toggle("proy", mode === "proy");
  const regFill = r => {           // proyección por región: líder e intensidad según la probabilidad
    const i = ridx.get(r); if (i == null) return "var(--nodata)";
    const p = f.regions.proj[i]; let L = 0; p.forEach((v,k) => { if (v > p[L]) L = k; });
    const pa = f.regions.p_ahead ? f.regions.p_ahead[i] : null;
    const conf = pa == null ? 1 : (L === a ? pa : L === b ? 1-pa : .5);
    return tint(col[L], conf > .95 ? 1 : conf > .8 ? .6 : .38);
  };
  const leaders = new Set(), vbw = STATE.vb[2], Lmax = vbw * (STATE.region ? .07 : .035), arrows = [];
  STATE.paths.forEach((p, j) => {
    const u = STATE.units[j], k = u.k;
    let fill = "var(--nodata)";
    const has = s && k != null && s.has[k];
    if (mode === "proy") fill = regFill(u.r);
    else if (mode === "escrutado") {
      if (has) fill = tint("#3d3d3d", .12 + .88 * s.F[k]/1000);
      else if (!s || k == null) { const i = ridx.get(u.r); if (i != null && f.regions.counted[i] > 0) fill = tint("#3d3d3d", .12 + .88 * f.regions.counted[i]); }
    }
    else if (has) {
      const v = s.V.subarray(k*NC, k*NC+NC);
      if (mode === "conteo") {
        let L = 0, S = -1; for (let c = 1; c < NC; c++) if (v[c] > v[L]) L = c;
        for (let c = 0; c < NC; c++) if (c !== L && (S < 0 || v[c] > v[S])) S = c;
        fill = tint(col[L], binT(v[L] - (S < 0 ? 0 : v[S]))); leaders.add(L);
      } else {
        fill = "var(--nodata)";
        const base = d.geo.base[k], sh = (v[a] - v[b]) - (base[ga] - base[gb]);
        if (u.c && Math.abs(sh) >= 5) arrows.push([u.c, sh]);
      }
    } else if (mode === "conteo" && (!s || k == null)) {      // sin unidad propia en el escrutinio: el conteo de su región
      const i = ridx.get(u.r);
      if (i != null && f.regions.counted[i] > 0) {
        const v = f.regions.crude[i]; let L = 0, S = -1;
        v.forEach((x,c) => { if (x > v[L]) L = c; }); v.forEach((x,c) => { if (c !== L && (S < 0 || x > v[S])) S = c; });
        fill = tint(col[L], binT(1000*(v[L] - (S < 0 ? 0 : v[S])))); leaders.add(L);
      }
    }
    if (mode === "corrimiento" && !has) fill = "var(--nodata2)";
    p.setAttribute("fill", fill);
    p.style.stroke = mode === "proy" ? fill : "";        // sin costuras entre unidades de la misma región
  });
  const ga_ = $("#ga");
  if (ga_) ga_.innerHTML = mode === "corrimiento" ? arrows.map(([c, sh]) => {
    const L = Math.min(Math.abs(sh)/250, 1) * Lmax, dx = (sh > 0 ? 1 : -1) * L * .7, dy = -L * .7, h = Math.max(L*.32, Lmax*.12);
    const x1 = c[0]+dx, y1 = c[1]+dy, ang = Math.atan2(dy, dx);
    const hx = t => (x1 - h*Math.cos(ang+t)).toFixed(1), hy = t => (y1 - h*Math.sin(ang+t)).toFixed(1);
    return `<path class="ar" stroke="${sh > 0 ? col[a] : col[b]}" d="M${c[0]} ${c[1]}L${x1.toFixed(1)} ${y1.toFixed(1)}M${hx(.5)} ${hy(.5)}L${x1.toFixed(1)} ${y1.toFixed(1)}L${hx(-.5)} ${hy(-.5)}"/>`;
  }).join("") : "";
  legend(cfg,C,col,a,b,s,leaders);
}

function legend(cfg,C,col,a,b,s,leaders){
  const m = STATE.mode, el = $("#mlegend"); if (!el) return;
  const ramp = i => `<span class="ramp"><b>${esc(C[i])}</b>${BINS.map(x => `<i style="background:${tint(col[i],x[1])}"></i>`).join("")}</span>`;
  const uu = esc(((STATE.geo[mapId(STATE.data[STATE.eid])]||{}).unit||"unidad").toLowerCase());
  const note = !s ? `<span>Estos datos no traen resultados por ${uu}: se muestra cada región según su conteo.</span>` : !s.any ? `<span>El mapa por ${uu} está disponible para el último corte.</span>` : "";
  if (m === "conteo") {
    const shown = C.map((n,i)=>i).filter(i => i === a || i === b || leaders.has(i));
    el.innerHTML = shown.map(ramp).join("") + `<span>Ventaja en el voto contado: menos de 5, 5 a 10, 10 a 20 y más de 20 puntos</span><span class="ramp"><i style="background:var(--nodata)"></i>Sin datos todavía</span>${note}`;
  } else if (m === "corrimiento") {
    const arr = (c, dir) => `<svg viewBox="0 0 24 16" width="24" height="16"><path d="M${dir>0?4:20} 14L${dir>0?16:8} 3M${dir>0?10:14} 3L${dir>0?16:8} 3L${dir>0?16:8} 9" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round"/></svg>`;
    el.innerHTML = `<span>${arr(col[a],1)} Más ${esc(C[a])} que en la elección anterior</span><span>${arr(col[b],-1)} Más ${esc(C[b])}</span><span>El largo indica cuántos puntos se movió la diferencia (tope: 25 puntos).</span>${note}`;
  } else if (m === "proy") {
    el.innerHTML = [a,b].map(i => `<span class="ramp"><b>${esc(C[i])}</b>${[.38,.6,1].map(t => `<i style="background:${tint(col[i],t)}"></i>`).join("")}</span>`).join("") + `<span>Probabilidad de ganar la región: menos de 80%, 80 a 95% y más de 95%, según la proyección.</span>`;
  } else {
    el.innerHTML = `<span class="ramp"><b>Escrutado</b>${[.1,.4,.7,1].map(t => `<i style="background:${tint("#3d3d3d",.12+.88*t)}"></i>`).join("")}</span><span>De 0 a 100% de los votos esperados</span><span class="ramp"><i style="background:var(--nodata)"></i>Sin datos</span>${note}`;
  }
}

/* tooltip */
function tipAt(ev, pinned){
  const p = ev.target.closest && ev.target.closest("path.u");
  STATE.paths && STATE.paths.forEach(x => x.classList.remove("on"));
  if (!p) { tipHide(); return; }
  p.classList.add("on");
  const e = election(), d = STATE.data[e.id], cfg = d.config, C = Object.keys(cfg.candidates), f = d.history[STATE.idx[e.id]];
  const u = STATE.units[+p.dataset.j], s = mapState(d, STATE.idx[e.id]), g = STATE.geo[mapId(d)];
  let body;
  if (STATE.mode === "proy") {
    const i = d.regions.indexOf(u.r), pr = i >= 0 ? f.regions.proj[i] : null;
    body = pr ? `<table>${C.map((n,c)=>[n,pr[c]]).sort((x,y)=>y[1]-x[1]).map(([n,v]) => `<tr><td><span class="sw" style="background:${cfg.colors[n]}"></span>${esc(n)}</td><td>${pct(v)}</td></tr>`).join("")}</table>
      <div class="hint">Proyección para ${esc(regName(g,u.r))}; ${pct(f.regions.counted[i],0)} escrutado.</div>` : `<div class="hint">Sin datos.</div>`;
  } else if (s && u.k != null && s.has[u.k]) {
    const NC = C.length, v = Array.from(s.V.subarray(u.k*NC, u.k*NC+NC));
    const rows = C.map((n,c)=>[n,v[c]]).sort((x,y)=>y[1]-x[1]);
    let extra = "";
    if (STATE.mode === "corrimiento") {
      const order = C.map((n,i)=>i).sort((x,y)=>f.proj[y]-f.proj[x]), a = order[0], b = order[1], G = d.geo.groups;
      const base = d.geo.base[u.k], bm = base[G.indexOf(cfg.candidates[C[a]])] - base[G.indexOf(cfg.candidates[C[b]])], nm = v[a]-v[b];
      extra = `<div class="hint">Diferencia ${esc(C[a])} − ${esc(C[b])}: ${pts(bm/1000)} antes → ${pts(nm/1000)} ahora.</div>`;
    }
    body = `<table>${rows.map(([n,x]) => `<tr><td><span class="sw" style="background:${cfg.colors[n]}"></span>${esc(n)}</td><td>${pct(x/1000)}</td></tr>`).join("")}</table>
      <div class="hint">${pct(s.F[u.k]/1000,0)} escrutado${s.N[u.k]?` · ${num(s.N[u.k])} votos contados`:""}</div>${extra}`;
  } else body = `<div class="hint">${u.k == null ? "Sin resultados propios en el escrutinio" : "Todavía sin votos contados"}.</div>`;
  const t = $("#tip");
  t.innerHTML = `<h3>${esc(u.n)}</h3><div class="sub">${esc(regName(g,u.r))}</div>${body}${!STATE.region?`<div class="hint">Clic para ver ${esc(regName(g,u.r))}.</div>`:""}`;
  t.hidden = false;
  const W = t.offsetWidth, H = t.offsetHeight, x = ev.clientX + 14, y = ev.clientY + 14;
  t.style.left = Math.max(8, Math.min(innerWidth - W - 8, x + W > innerWidth ? ev.clientX - W - 14 : x)) + "px";
  t.style.top = Math.max(60, Math.min(innerHeight - H - 8, y + H > innerHeight ? ev.clientY - H - 14 : y)) + "px";
  if (pinned) { clearTimeout(STATE.tipT); STATE.tipT = setTimeout(tipHide, 5000); }
}
function tipHide(){ $("#tip").hidden = true; STATE.paths && STATE.paths.forEach(x => x.classList.remove("on")); }

/* ---------------- tablas */
function regionsView(d,cfg,C,f,order){
  const a = order[0], b = order[1], R = d.regions, g = mapId(d) ? STATE.geo[mapId(d)] : null, drill = !!g;
  let rows = R.map((id,r)=>({id, name:regName(g,id), cnt:f.regions.counted[r], p:f.regions.proj[r], v:f.regions.votes[r], pa:f.regions.p_ahead?f.regions.p_ahead[r]:null}));
  const key = {close:o=>Math.abs(o.p[a]-o.p[b]), votes:o=>-o.v, counted:o=>o.cnt, name:o=>o.name}[STATE.sort];
  rows.sort((x,y)=> STATE.sort==="name" ? x.name.localeCompare(y.name) : key(x)-key(y));
  const shown = STATE.showAll ? rows : rows.slice(0,12);
  const ca = cfg.colors[C[a]], cb = cfg.colors[C[b]];
  return `<h2 class="sec">Por ${esc(cfg.region_label.toLowerCase())}</h2>
  <div class="tools"><label for="sort">Ordenar por</label><select id="sort">
    ${[["close","más reñidos"],["votes","más votos"],["counted","menos escrutados"],["name","nombre"]].map(([k,l])=>`<option value="${k}" ${STATE.sort===k?"selected":""}>${l}</option>`).join("")}</select></div>
  <div class="tablewrap"><table><thead><tr><th>${esc(cfg.region_label)}</th><th>Escrutado</th><th>${esc(C[a])}</th><th>${esc(C[b])}</th><th>Diferencia proyectada</th>${rows[0].pa!=null?`<th>P(${esc(C[a])} adelante)</th>`:""}</tr></thead><tbody>
  ${shown.map(o=>{ const dm=o.p[a]-o.p[b], w=Math.min(50,Math.abs(dm)*250);
    return `<tr><td>${drill?`<button class="lnk" type="button" data-r="${esc(o.id)}">${esc(o.name)}</button>`:esc(o.name)}</td><td>${pct(o.cnt,0)}</td><td>${pct(o.p[a])}</td><td>${pct(o.p[b])}</td>
    <td>${pts(dm)}<span class="mbar"><span style="${dm>=0?`left:50%;width:${w}%;background:${ca}`:`right:50%;width:${w}%;background:${cb}`}"></span></span></td>
    ${o.pa!=null?`<td>${pct(o.pa,0)}</td>`:""}</tr>`;}).join("")}
  </tbody></table></div>
  ${rows.length>12?`<button class="more" id="more" type="button">${STATE.showAll?"Mostrar menos":`Mostrar los ${rows.length}`}</button>`:""}`;
}

function unitsTable(d,cfg,C,f,order){
  const a = order[0], b = order[1], g = STATE.geo[mapId(d)], s = mapState(d, STATE.idx[STATE.eid]), NC = C.length;
  const label = (g && g.unit) || "Unidad", q = norm(STATE.uq);
  let rows = (STATE.units || []).filter(u => u.r === STATE.region).map(u => {
    const has = s && u.k != null && s.has[u.k], v = has ? Array.from(s.V.subarray(u.k*NC, u.k*NC+NC)) : null;
    return {n:u.n, has, f: has ? s.F[u.k]/1000 : 0, v, N: has ? s.N[u.k] : 0};
  });
  const total = rows.length;
  if (q) rows = rows.filter(r => norm(r.n).includes(q));
  const key = {votes:r=>-r.N, close:r=>r.has?Math.abs(r.v[a]-r.v[b]):1e9, counted:r=>r.f, name:null}[STATE.usort];
  rows.sort((x,y)=> key ? key(x)-key(y) : x.n.localeCompare(y.n));
  const shown = STATE.showAll || q ? rows.slice(0,400) : rows.slice(0,15);
  const ca = cfg.colors[C[a]], cb = cfg.colors[C[b]];
  return `<h2 class="sec">${esc(regName(g,STATE.region))}, por ${esc(label.toLowerCase())}</h2>
  <p class="secdek">Voto contado hasta ahora en cada ${esc(label.toLowerCase())}. La proyección se hace con todos juntos, no ${esc(label.toLowerCase()==="municipio"?"municipio por municipio":"uno por uno")}.</p>
  <div class="tools"><input id="uq" type="search" placeholder="Buscar ${esc(label.toLowerCase())}" aria-label="Buscar ${esc(label.toLowerCase())}" value="${esc(STATE.uq)}">
    <label for="usort">Ordenar por</label><select id="usort">${[["votes","más votos"],["close","más reñidos"],["counted","menos escrutados"],["name","nombre"]].map(([k,l])=>`<option value="${k}" ${STATE.usort===k?"selected":""}>${l}</option>`).join("")}</select></div>
  <div class="tablewrap"><table><thead><tr><th>${esc(label)}</th><th>Escrutado</th><th>${esc(C[a])}</th><th>${esc(C[b])}</th><th>Diferencia</th><th>Votos contados</th></tr></thead><tbody>
  ${shown.map(r => { if (!r.has) return `<tr><td>${esc(r.n)}</td><td>—</td><td></td><td></td><td></td><td></td></tr>`;
    const dm = (r.v[a]-r.v[b])/1000, w = Math.min(50, Math.abs(dm)*100);
    return `<tr><td>${esc(r.n)}</td><td>${pct(r.f,0)}</td><td>${pct(r.v[a]/1000)}</td><td>${pct(r.v[b]/1000)}</td>
      <td>${pts(dm)}<span class="mbar"><span style="${dm>=0?`left:50%;width:${w}%;background:${ca}`:`right:50%;width:${w}%;background:${cb}`}"></span></span></td><td>${r.N?num(r.N):"—"}</td></tr>`; }).join("")}
  </tbody></table></div>
  ${!q && total>15?`<button class="more" id="more" type="button">${STATE.showAll?"Mostrar menos":`Mostrar los ${total}`}</button>`:""}`;
}

function wireTable(){
  const m = $("#more"); if (m) m.onclick = () => { STATE.showAll = !STATE.showAll; update(); };
  const so = $("#sort"); if (so) so.onchange = e => { STATE.sort = e.target.value; update(); };
  const us = $("#usort"); if (us) us.onchange = e => { STATE.usort = e.target.value; update(); };
  const uq = $("#uq"); if (uq) uq.oninput = e => { STATE.uq = e.target.value; const pos = e.target.selectionStart; update(); const n = $("#uq"); n.focus(); n.setSelectionRange(pos,pos); };
  document.querySelectorAll("#tablesec [data-r]").forEach(x => x.onclick = () => setRegion(x.dataset.r));
}

/* ---------------- resultado según la regla */
function outcome(cfg,C,f,d){
  const r = f.rule;
  if (!r) return `<div class="outcome"><h2>Resultado</h2><p class="note">Todavía hay muy pocas unidades escrutadas para simular escenarios.</p></div>`;
  if (cfg.rule_kind === "ec") {
    const evs = C.map(n=>({n, v:r["ev_"+n]})).filter(o=>o.v && o.v.mid>0).sort((a,b)=>b.v.mid-a.v.mid);
    const tot = 538;
    const winners = Object.entries(r.ganador||{}).sort((a,b)=>b[1]-a[1]);
    return `<div class="outcome"><h2>Colegio electoral proyectado</h2>
      <div class="big">${evs.map(o=>`<span style="color:${cfg.colors[o.n]}">${esc(o.n)} ${Math.round(o.v.mid)}</span>`).join(" · ")}</div>
      <div class="ev" role="img" aria-label="Votos electorales proyectados">${evs.map(o=>`<div style="width:${o.v.mid/tot*100}%;background:${cfg.colors[o.n]}"></div>`).join("")}<span class="half"></span></div>
      <div class="note" style="margin-top:0">La línea marca 270, la mayoría.</div>
      ${evs.map(o=>`<div class="line"><span>${esc(o.n)}</span><span>${Math.round(o.v.lo)}–${Math.round(o.v.hi)} votos electorales</span></div>`).join("")}
      ${winners.map(([n,p])=>`<div class="line"><span>${n==="sin mayoría"?"Nadie llega a 270":"Gana "+esc(n)}</span><strong>${pct(p,0)}</strong></div>`).join("")}
      ${d.truth&&d.truth.ev?`<div class="note">Resultado real: Trump 312, Harris 226.</div>`:""}
      <div class="note">${esc(cfg.note||"")}</div></div>`;
  }
  if (cfg.rule_kind === "runoff") {
    const w = Object.entries(r.ganador||{}).sort((a,b)=>b[1]-a[1]);
    return `<div class="outcome"><h2>¿Quién gana?</h2>
      ${w.length?`<div class="big"><span style="color:${cfg.colors[w[0][0]]||"inherit"}">${esc(w[0][0])}</span> ${pct(w[0][1],0)}</div>`:""}
      ${w.map(([k,p])=>`<div class="line"><span>Gana ${esc(k)}</span><strong>${pct(p,0)}</strong></div>`).join("")}
      ${d.truth&&d.truth.text?`<div class="note">${esc(d.truth.text)}</div>`:""}
      <div class="note">${esc(cfg.note||"")}</div></div>`;
  }
  const res = Object.entries(r.resultado||{}).sort((a,b)=>b[1]-a[1]);
  const pb = typeof r.balotaje === "number" ? r.balotaje : null;
  return `<div class="outcome"><h2>¿Hay balotaje?</h2>
    ${pb!=null?`<div class="big">${pct(pb,0)} <span style="font-size:1rem;font-weight:500">de probabilidad de segunda vuelta</span></div>`:""}
    ${res.map(([k,p])=>`<div class="line"><span>${esc(k)}</span><strong>${pct(p,0)}</strong></div>`).join("")}
    ${d.truth&&d.truth.text?`<div class="note">${esc(d.truth.text)}</div>`:""}
    <div class="note">${esc(cfg.note||"")}</div></div>`;
}

/* ---------------- gráfico de la noche */
function chart(d,cfg,C,idx){
  const H = d.history, W = Math.round(Math.max(340, Math.min(1048, ($(".wrap").clientWidth||760) - 32))), Ht = W < 520 ? 280 : 320, m = {l:40,r:12,t:14,b:30};
  const xs = v => m.l + v*(W-m.l-m.r);
  let lo = 1, hi = 0;
  H.forEach(f => idx.forEach(i => { [f.proj[i], f.crude[i], f.lo?f.lo[i]:f.proj[i], f.hi?f.hi[i]:f.proj[i]].forEach(v=>{lo=Math.min(lo,v);hi=Math.max(hi,v);}); }));
  if (d.truth) idx.forEach(i=>{lo=Math.min(lo,d.truth.shares[i]);hi=Math.max(hi,d.truth.shares[i]);});
  lo = Math.floor(lo*50)/50 - .01; hi = Math.ceil(hi*50)/50 + .01;
  const ys = v => m.t + (hi-v)/(hi-lo)*(Ht-m.t-m.b);
  const path = (get) => H.map((f,k)=>`${k?"L":"M"}${xs(f.counted).toFixed(1)},${ys(get(f)).toFixed(1)}`).join("");
  let g = "";
  const step = (hi - lo) > .2 ? .04 : .02;
  for (let v = Math.ceil(lo/step)*step; v <= hi + 1e-9; v += step) g += `<line x1="${m.l}" x2="${W-m.r}" y1="${ys(v)}" y2="${ys(v)}" stroke="var(--rule)"/><text x="${m.l-6}" y="${ys(v)+4}" text-anchor="end">${Math.round(v*100)}%</text>`;
  [0,.25,.5,.75,1].forEach(v => g += `<text x="${xs(v)}" y="${Ht-8}" text-anchor="middle">${Math.round(v*100)}%</text>`);
  g += `<text x="${W-m.r}" y="${Ht-20}" text-anchor="end">votos escrutados</text>`;
  idx.forEach(i => {
    const col = cfg.colors[C[i]];
    const withCI = H.filter(f=>f.lo);
    if (withCI.length > 1) {
      const top = withCI.map((f,k)=>`${k?"L":"M"}${xs(f.counted).toFixed(1)},${ys(f.hi[i]).toFixed(1)}`).join("");
      const bot = withCI.slice().reverse().map(f=>`L${xs(f.counted).toFixed(1)},${ys(f.lo[i]).toFixed(1)}`).join("");
      g += `<path d="${top}${bot}Z" fill="${col}" style="opacity:var(--band)"/>`;
    }
    g += `<path d="${path(f=>f.crude[i])}" fill="none" stroke="${col}" stroke-width="1.6" stroke-dasharray="5 4"/>`;
    g += `<path d="${path(f=>f.proj[i])}" fill="none" stroke="${col}" stroke-width="2.6"/>`;
    if (d.truth) g += `<line x1="${m.l}" x2="${W-m.r}" y1="${ys(d.truth.shares[i])}" y2="${ys(d.truth.shares[i])}" stroke="${col}" stroke-dasharray="1 4" stroke-width="2"/>`;
  });
  const cur = H[STATE.idx[STATE.eid]];
  g += `<line x1="${xs(cur.counted)}" x2="${xs(cur.counted)}" y1="${m.t}" y2="${Ht-m.b}" stroke="var(--ink)" stroke-width="1"/>`;
  idx.forEach(i => g += `<circle cx="${xs(cur.counted)}" cy="${ys(cur.proj[i])}" r="4.5" fill="${cfg.colors[C[i]]}" stroke="var(--paper)" stroke-width="2"/>`);
  return `<svg viewBox="0 0 ${W} ${Ht}" role="img" aria-label="Evolución de la proyección y del conteo">${g}</svg>`;
}

/* ---------------- qué cambió */
function changesView(d,cfg,f){
  const A = f.analysis; if (!A) return "";
  const ca = cfg.colors[A.a], cb = cfg.colors[A.b], md = A.margin_delta, toward = md >= 0 ? A.a : A.b;
  const u = esc(cfg.unit_label||"unidades"), rl = esc((cfg.region_label||"región").toLowerCase());
  const art = /[aá]$|ón$/.test(rl) ? "La" : "El";
  const g = mapId(d) ? STATE.geo[mapId(d)] : null;
  const chg = Object.entries(A.change).filter(([n,v]) => Math.abs(v.delta) > 0.001 || v.now > 0.02);
  const lead = `Comparando los mismos ${A.units.toLocaleString("es-AR")} ${u} ya escrutados con la elección anterior, la diferencia entre ${esc(A.a)} y ${esc(A.b)} se movió <strong>${Math.abs(md*100).toFixed(1).replace(".",",")} puntos hacia ${esc(toward)}</strong>.`;
  const cards = chg.map(([n,v]) => `<div class="card"><div class="k">${esc(n)}${v.shared_group?" (grupo)":""}</div>
     <div class="v" style="color:${cfg.colors[n]||"var(--ink)"}">${pts(v.delta)}</div>
     <div class="s">${pct(v.base)} → ${pct(v.now)}${v.shared_group?", contra el grupo de la base":""}</div></div>`).join("")
   + (A.polls && A.polls.error!=null ? `<div class="card"><div class="k">Contra las encuestas</div><div class="v">${pts(A.polls.error)}</div><div class="s">La proyección da ${esc(A.a)} ${pts(f.margin.mid)}; las encuestas, ${pts(A.polls.margin)}${A.polls.source?` (${esc(A.polls.source)})`:""}</div></div>` : "");
  const R = A.by_region, W = 560, rowH = 18, H = R.length*rowH + 30, nameW = 128, valW = 46;
  const lo = Math.min(0, ...R.map(r=>r.delta)), hi = Math.max(0, ...R.map(r=>r.delta)), span = Math.max(hi - lo, .01);
  const xL = nameW + (lo < 0 ? valW : 0), xR = W - (hi > 0 ? valW : 6), sc = (xR - xL)/span, x0 = xL - lo*sc;
  let gg = `<line x1="${x0}" x2="${x0}" y1="4" y2="${H-22}" stroke="var(--ink)" stroke-width="1"/>`;
  R.forEach((r,i) => { const y = 8 + i*rowH + rowH/2, x1 = x0 + r.delta*sc, col = r.delta >= 0 ? ca : cb;
    gg += `<text x="${nameW-8}" y="${y+4}" text-anchor="end">${esc(regName(g, r.region))}</text>`;
    gg += `<line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="5" stroke-linecap="round"/>`;
    gg += `<text x="${x1 + (r.delta>=0?6:-6)}" y="${y+4}" text-anchor="${r.delta>=0?"start":"end"}" style="fill:var(--ink)">${pts(r.delta)}</text>`; });
  gg += `${hi>0?`<text x="${x0+6}" y="${H-6}">hacia ${esc(A.a)} →</text>`:""}${lo<0?`<text x="${x0-6}" y="${H-6}" text-anchor="end">← hacia ${esc(A.b)}</text>`:""}`;
  const arrows = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cambio de la diferencia por ${rl}">${gg}</svg>`;
  const Z = A.by_size, mz = Math.max(...Z.map(z=>Math.abs(z.delta)), .01), W2 = 420, H2 = Z.length*34 + 10;
  let g2 = ""; Z.forEach((z,i) => { const y = 6 + i*34, w = Math.abs(z.delta)/mz*(W2-170), col = z.delta>=0?ca:cb;
    g2 += `<text x="0" y="${y+14}" style="fill:var(--ink)">${esc(z.label)}</text><text x="0" y="${y+28}" font-size="11">${Math.round(z.share_votes*100)}% de los votos</text>`;
    g2 += `<rect x="130" y="${y+6}" width="${Math.max(2,w)}" height="16" fill="${col}"/><text x="${136+w}" y="${y+19}" style="fill:var(--ink)">${pts(z.delta)}</text>`; });
  const sizes = `<svg viewBox="0 0 ${W2} ${H2}" role="img" aria-label="Cambio por tamaño">${g2}</svg>`;
  let sf = null; const H0 = d.history, k0 = STATE.idx[STATE.eid];
  for (let k = k0; k >= 0; k--) if (H0[k].analysis && H0[k].analysis.scatter) { sf = H0[k].analysis; break; }
  let scat = "";
  if (sf) { const P = sf.scatter, Ws = 360, Hs = 300, m = 34, lim = Math.min(1, Math.max(.3, ...P.map(p=>Math.max(Math.abs(p[0]),Math.abs(p[1])))));
    const X = v => m + (v+lim)/(2*lim)*(Ws-m-8), Y = v => 8 + (lim-v)/(2*lim)*(Hs-m-8);
    let gs = `<rect x="${m}" y="8" width="${Ws-m-8}" height="${Hs-m-8}" fill="none" stroke="var(--rule)"/>`;
    gs += `<line x1="${X(0)}" x2="${X(0)}" y1="8" y2="${Hs-m}" stroke="var(--rule)"/><line x1="${m}" x2="${Ws-8}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--rule)"/>`;
    gs += `<line x1="${X(-lim)}" y1="${Y(-lim)}" x2="${X(lim)}" y2="${Y(lim)}" stroke="var(--ink)" stroke-dasharray="4 4"/>`;
    P.forEach(p => { const col = p[1] >= 0 ? ca : cb; gs += `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="${(1+ (p[2]-2)*0.7).toFixed(1)}" fill="${col}" fill-opacity=".45"/>`; });
    gs += `<text x="${(Ws+m)/2}" y="${Hs-6}" text-anchor="middle">diferencia en la elección anterior</text><text x="10" y="${(Hs-m)/2}" transform="rotate(-90 10 ${(Hs-m)/2})" text-anchor="middle">diferencia ahora</text>`;
    scat = `<div class="panel"><h3>La geografía se mantiene</h3><p class="cap">Cada punto es uno de los ${u}; el tamaño, sus votos. Sobre la diagonal, no cambió nada. Correlación entre ambas elecciones: ${sf.persistence.toFixed(2).replace(".",",")}.</p><svg viewBox="0 0 ${Ws} ${Hs}" role="img" aria-label="Diferencia anterior contra actual">${gs}</svg></div>`; }
  const F = A.flips, flipList = arr => arr.length ? `<ul class="flips">${arr.slice(0,6).map(x=>`<li>${esc(x.name)} (${esc(regName(g, x.region))}): ${pts(x.base)} → ${pts(x.now)}</li>`).join("")}</ul>` : "";
  const flipsTxt = `<div class="panel"><h3>Cambios de ganador</h3>
    <p class="cap">Entre los ${u} ya completos, ${F.to_a.toLocaleString("es-AR")} pasaron a ${esc(A.a)} y ${F.to_b.toLocaleString("es-AR")} a ${esc(A.b)}. Había ${F.vulnerable.toLocaleString("es-AR")} que el perjudicado por el corrimiento había ganado por menos de ${Math.abs(md*100).toFixed(1).replace(".",",")} puntos, lo mismo que se movió el total; ${F.vulnerable_flipped.toLocaleString("es-AR")} cambiaron de mano.</p>
    ${F.to_a?`<p class="cap" style="margin-top:6px">Los más grandes que pasaron a ${esc(A.a)} (diferencia de ${esc(A.a)} sobre ${esc(A.b)}, antes → ahora):</p>${flipList(F.top_to_a)}`:""}
    ${F.to_b?`<p class="cap" style="margin-top:6px">Los más grandes que pasaron a ${esc(A.b)}:</p>${flipList(F.top_to_b)}`:""}</div>`;
  return `<h2 class="sec">Qué cambió respecto de la elección anterior</h2>
   <p class="lead">${lead}</p><div class="cards">${cards}</div>
   <div class="two"><div class="panel"><h3>Por ${rl}</h3><p class="cap">El largo indica cuántos puntos cambió la diferencia entre ${esc(A.a)} y ${esc(A.b)}, en los ${u} ya escrutados.</p>${arrows}</div>
   <div style="display:flex;flex-direction:column;gap:22px"><div class="panel"><h3>Por tamaño</h3><p class="cap">Según los votos válidos que tenía cada uno en la elección anterior.</p>${sizes}</div>
   <div class="panel"><h3>¿Fue parejo?</h3><p class="cap" style="font-size:.92rem;color:var(--ink)">En el ${pct(A.same_dir,0)} de los ${u} (ponderados por votos) la diferencia se movió en el mismo sentido que el total. ${art} ${rl} explica el ${pct(Math.max(0,A.r2_region),0)} de la variación del cambio entre ${u}; el resto es local.</p></div></div></div>
   <div class="two" style="margin-top:22px">${scat}${flipsTxt}</div>`;
}

/* ---------------- validación */
function methodView(d){
  if (d.backtest.cal === "EEUU") return methodViewOther(d);
  const bt = d.backtest, show = [0,1,2,4,6,8], names = {crudo:"Conteo crudo",swing_reg:"Swing regional",vecinos:"Vecinos",modelo:"Modelo jerárquico",ensamble:"Ensamble (esta página)"};
  const best = show.map(k => Math.min(...bt.methods.filter(m=>m!=="crudo").map(m=>bt.mae[m][k])));
  return `<h2 class="sec">Qué tan bien funciona</h2>
  <p>Para validar el método se re-escrutó la elección 2024 en ${bt.n_orders} órdenes de llegada distintos (algunos con sesgo fuerte: primero lo urbano, primero un partido, primero el este), usando sólo lo que se sabía en cada momento. La tabla muestra el error medio en el margen entre los dos primeros, en puntos, según cuánto se había contado. Los parámetros se eligieron con 2016→2020, sin mirar 2024.</p>
  <div class="tablewrap"><table><thead><tr><th>Método</th>${show.map(k=>`<th>${Math.round(bt.cuts[k]*100)}%</th>`).join("")}</tr></thead><tbody>
  ${bt.methods.map(m=>`<tr><td>${names[m]}</td>${show.map((k,j)=>{const v=bt.mae[m][k];return `<td class="${m!=="crudo"&&Math.abs(v-best[j])<1e-9?"best":""}">${v.toFixed(2).replace(".",",")}</td>`;}).join("")}</tr>`).join("")}
  </tbody></table></div>
  <p>En 2024 los cuatro métodos quedan muy cerca entre sí y ninguno domina. La diferencia aparece en las otras elecciones: en 2016→2020 el ensamble tuvo un error medio de ${(bt.mae_2020.ensamble).toFixed(2).replace(".",",")} puntos contra ${(bt.mae_2020.modelo).toFixed(2).replace(".",",")} del modelo solo y ${(bt.mae_2020.swing_reg).toFixed(2).replace(".",",")} del swing regional, y en Argentina 2019 el swing regional se equivocó el triple que el ensamble. Por eso la página usa modelo + vecinos: no es el mejor en cada elección, pero es el que nunca queda lejos del mejor. El ensamble acertó el ganador del colegio electoral en todas las corridas; el conteo crudo señalaba al equivocado en la mayoría de los casos hasta la mitad del escrutinio. Todos los métodos subestiman el margen de Trump en 2024, porque las grandes ciudades giraron más de lo que anticipaba la base.</p>
  <p>El intervalo es la parte más frágil. Calibrado con 2020, el intervalo del 90% contuvo el margen real ${pct(bt.coverage_global,0)} de las veces en 2024; calibrado con 2024, contuvo el de 2020 ${pct(bt.coverage_other,0)} de las veces. Esta repetición usa la calibración de 2020, así que sus bandas son más angostas de lo que deberían. Para elecciones futuras se usa una calibración conjunta de ambas.</p>`;
}

function methodViewOther(d){
  const bt = d.backtest, show = [0,1,2,4,6,8], names = {crudo:"Conteo crudo",swing_reg:"Swing regional",vecinos:"Vecinos",modelo:"Modelo jerárquico",ensamble:"Ensamble (esta página)"};
  const best = show.map(k => Math.min(...bt.methods.filter(m=>m!=="crudo").map(m=>bt.mae[m][k])));
  const ok = m => pct(bt.regla[m],0);
  return `<h2 class="sec">Qué tan bien funciona</h2>
  <p>Se re-escrutó ${esc(bt.eval)} en ${bt.n_orders} órdenes de llegada distintos (${bt.units.toLocaleString("es-AR")} unidades), con los parámetros y la calibración elegidos en Estados Unidos, sin ajustar nada para este país. Es una prueba fuera de muestra doble: otra elección y otro sistema político. La tabla muestra el error medio en el margen entre los dos primeros, en puntos.</p>
  <div class="tablewrap"><table><thead><tr><th>Método</th>${show.map(k=>`<th>${Math.round(bt.cuts[k]*100)}%</th>`).join("")}<th>Escenario correcto</th></tr></thead><tbody>
  ${bt.methods.map(m=>`<tr><td>${names[m]}</td>${show.map((k,j)=>{const v=bt.mae[m][k];return `<td class="${m!=="crudo"&&Math.abs(v-best[j])<1e-9?"best":""}">${v.toFixed(2).replace(".",",")}</td>`;}).join("")}<td>${ok(m)}</td></tr>`).join("")}
  </tbody></table></div>
  <p>"Escenario correcto" es la proporción de cortes en que el método anticipaba bien ${(d.config||{}).rule_kind==="runoff"?"al ganador":"si había o no segunda vuelta"}. Con la calibración traída de Estados Unidos, el intervalo del 90% contuvo el margen real el ${pct(bt.coverage_global,0)} de las veces. Para la noche electoral, este país usa un promedio de esa calibración y la que surge de su propio backtest.</p>`;
}

/* ---------------- sin datos / país nuevo */
function emptyView(e){
  const cfg = e.config || {};
  const pill = e.status === "upcoming" ? `<span class="pill replay">Próxima</span>` : `<span class="pill live">En vivo</span>`;
  return `<div class="kicker">${pill}<span>${esc(e.name)} · ${esc(e.office)} · ${fecha(e.date)}</span></div>
  <h1 class="hed">${esc(e.name)} ${e.year}: todavía sin datos</h1><p class="dek">${esc(cfg.note||"")}</p>
  <div class="empty"><h2>Para activar esta elección</h2><ol>${(e.setup||[]).map(s=>`<li>${s}</li>`).join("")}</ol>
  ${cfg.candidates?`<p>Candidatos configurados: ${Object.keys(cfg.candidates).map(esc).join(", ")}. Hasta tener un backtest propio, el país usa los parámetros y la calibración de Estados Unidos.</p>`:""}
  <p>La página se actualiza sola cada 2 minutos cuando aparecen los datos.</p></div>`;
}

function setupView(code){
  const p = STATE.paises.find(x => x[0] === code), name = p ? p[1] : code.toUpperCase();
  return `<div class="kicker"><span class="pill replay">Sin configurar</span><span>${esc(name)}</span></div>
  <h1 class="hed">${esc(name)}: todavía no está preparado</h1>
  <p class="dek">El motor es el mismo para cualquier país: proyecta el resultado final comparando lo que ya se contó con la elección anterior, unidad por unidad. Para lanzar una elección de ${esc(name)} hace falta esto:</p>
  <div class="empty"><ol>
    <li><strong>Base.</strong> Resultados de la elección anterior por unidad (municipio, distrito o circuito) en el formato de <code>adapters/canonical.py</code>: <code>unit, region, lat, lon</code> y una columna de votos por fuerza. Un adaptador <code>adapters/${esc(code)}.py</code> la arma desde la fuente oficial.</li>
    <li><strong>Configuración.</strong> <code>config/${esc(code)}.json</code>: candidatos y a qué fuerza de la base heredan, colores, regla electoral (<code>segunda_vuelta</code>, <code>brasil</code> para mayoría absoluta, <code>argentina</code>, colegio electoral, o una nueva en <code>engine/rules.py</code>) y el bloque <code>geo</code> del mapa.</li>
    <li><strong>Mapa.</strong> Un GeoJSON con un polígono por unidad y una función <code>prep_${esc(code)}</code> en <code>build_maps.py</code>; después <code>python build_maps.py ${esc(code)}</code>.</li>
    <li><strong>Escrutinio en vivo.</strong> <code>adapters/${esc(code)}_live.py</code> convierte el feed oficial a <code>unit, frac, &lt;candidatos&gt;</code>, y <code>python run_live.py ${esc(code)} data/${esc(code)}_actual.csv</code> publica cada corte.</li>
    <li><strong>Validación</strong> (recomendada): <code>python backtest_pais.py ${esc(code)}</code> re-escruta la elección anterior y calibra el intervalo.</li>
    <li><strong>Publicación.</strong> Una entrada en <code>site/elecciones.json</code> con la fecha, el cargo y el archivo de datos. Desde ahí aparece en el menú.</li>
  </ol></div>`;
}

/* ---------------- repetición y refresco */
function togglePlay(){
  if (STATE.playing) { stop(); update(); return; }
  const e = election(), d = STATE.data[e.id];
  if (STATE.idx[e.id] >= d.history.length-1) STATE.idx[e.id] = 0;
  STATE.playing = setInterval(() => { if (STATE.idx[e.id] >= d.history.length-1) stop(); else STATE.idx[e.id]++; update(); }, 600);
  update();
}
function stop(){ if (STATE.playing) { clearInterval(STATE.playing); STATE.playing = null; } }

async function init(){
  readPaper();
  STATE.reg = (window.__REG__) || await getJSON("elecciones.json");
  STATE.paises = (window.__PAISES__) || await getJSON("paises.json") || [];
  if (!STATE.reg) { $("#app").innerHTML = `<p class="loading">No se pudo leer elecciones.json.</p>`; return; }
  route(); render();
  window.addEventListener("hashchange", () => { menuOpen(false); route(); render(); scrollTo(0,0); });
  $("#menubtn").onclick = () => menuOpen($("#menu").hidden);
  $("#menuq").oninput = menuList;
  document.addEventListener("click", ev => { if (!$("#menu").hidden && !ev.target.closest(".menu")) menuOpen(false); });
  document.addEventListener("keydown", ev => { if (ev.key === "Escape") { menuOpen(false); tipHide(); } });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readPaper(); paint(); });
  let rz, lw = innerWidth; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (innerWidth !== lw) { lw = innerWidth; update(); } }, 150); });
  if (!window.__DATA__) setInterval(async () => {
    const e = election(); if (!e || e.status === "replay") return;
    // una elección en vivo se sigue pidiendo aunque por ahora muestre la repetición: cuando
    // run_live.py escribe el primer corte, la página pasa sola al modo en vivo
    const old = STATE.data[e.id];
    const d = await getJSON(e.data); if (!d) return;
    if (old && d.mode !== "live") return;
    const atEnd = !old || STATE.idx[e.id] === old.history.length-1;
    STATE.data[e.id] = d; delete STATE.cache[e.id];
    if (!old || old.mode !== d.mode) { STATE.idx[e.id] = d.history.length-1; render(); return; }
    if (atEnd) STATE.idx[e.id] = d.history.length-1;
    if ($("#slider")) $("#slider").max = d.history.length-1;
    update();
  }, 120000);
}
init();
