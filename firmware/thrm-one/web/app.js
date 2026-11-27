// THRM ONE (Roost) - eigen webpagina. Leest alle toestanden via /events (SSE) en schrijft via
// de REST-API van ESPHome. Geen externe bestanden; taal volgt de browser (nl, anders en).
const NL = (navigator.language || "en").toLowerCase().startsWith("nl");
const T = NL ? {
  title: "Warmtepomp-regeling", offline: "Geen verbinding met het kastje", saved: "Opgeslagen", failed: "Niet gelukt",
  h: {
    home_assistant: "Home Assistant stuurt de aanvoertemperatuur",
    curve: "Het kastje stuurt zelf op de stooklijn",
    curve_ha_offline: "Terugval: Home Assistant is weg",
    curve_no_command: "Terugval: geen opdracht van Home Assistant",
    off: "Verwarming staat uit",
  },
  why: {
    home_assistant: c => `Laatste opdracht ${c}. Valt die langer dan de opdrachttijd weg, dan neemt de stooklijn het over.`,
    curve: () => "Stooklijn op de buitentemperatuur; aan/uit op de kamertemperatuur.",
    curve_ha_offline: () => "Het kastje stuurt zelf op de stooklijn tot Home Assistant terug is en weer een opdracht geeft.",
    curve_no_command: c => `Laatste opdracht ${c}. Het kastje stuurt zelf op de stooklijn tot er weer een opdracht komt.`,
    off: () => "Er gaat geen warmtevraag naar de warmtepomp. Warm water regelt de warmtepomp zelf.",
  },
  never: "nog niet sinds de start", ago: m => m < 1 ? "net" : `${m} min geleden`,
  t_req: "Aanvoer gevraagd", t_flow: "Aanvoer gemeten", t_ret: "Retour", t_out: "Buiten", t_room: "Kamer",
  src: {ot: "luchtinlaat warmtepomp", ha: "buitensensor", none: "onbekend: vaste aanvoer"},
  demand_on: "warmtevraag aan", demand_off: "geen warmtevraag", setp: "doel", setp_fb: "bij terugval",
  chips: {mod: "Modulatie", ch: "CV actief", comp: "Compressor", dhw: "Warm water", fault: "Storing", bus: "Geen OpenTherm"},
  c_control: "Regeling", c_curve: "Stooklijn bij terugval", c_room: "Temperaturen", c_safety: "Terugval en verbindingen", c_net: "Netwerk en kastje",
  mode: "Wie stuurt", m_ha: "Home Assistant", m_curve: "Stooklijn",
  tip_mode: "Home Assistant: Roost of een automatisering stuurt de aanvoertemperatuur (Flow Setpoint). Stooklijn: het kastje regelt zelf, ook zonder Home Assistant.",
  heating: "Verwarming", tip_heating: "Hoofdschakelaar. Uit = geen warmtevraag naar de warmtepomp. Warm water blijft werken.",
  fs: "Opdracht aanvoer", tip_fs: "De aanvoertemperatuur die Home Assistant of Roost vraagt; 0 = geen warmtevraag. Moet minstens elke paar minuten opnieuw gestuurd worden, anders neemt de stooklijn het over.",
  to: "Opdrachttijd", tip_to: "Zo lang mag een opdracht van Home Assistant oud zijn (of Home Assistant weg zijn) voordat het kastje zelf op de stooklijn gaat. Roost stuurt elke 5 minuten.",
  follow: "Volg Roost", tip_follow: "Neemt de stooklijn en de comforttemperatuur automatisch over van Roost (sensor Roost Heating curve advice). Zet uit om ze zelf te wijzigen.",
  points: "Punten", lg_curve: "stooklijn", lg_now: "nu", lg_req: "gevraagd door Home Assistant", lg_lim: "min/max", out: "Buiten °C", flow: "Aanvoer °C", add: "Punt toevoegen", save: "Stooklijn opslaan",
  roost_lock: "Roost houdt deze stooklijn bij. Zet Volg Roost uit om zelf te wijzigen.",
  now_pt: (o, f) => `Nu ${o} buiten → ${f} aanvoer`, now_none: f => `Geen buitentemperatuur → vaste aanvoer ${f}`,
  soft: "Zachte start vanaf", tip_soft: "Bij een start vraagt het kastje eerst retour + 2 °C, zodat de pomp meteen start. Is het verschil met de gewenste aanvoer groter dan dit, dan loopt het in stappen van 1 °C per minuut op, zodat de pomp niet lang op hoog toerental draait. Kleiner verschil = direct. 0 = altijd direct.",
  minon: "Minimaal aan", tip_minon: "Pendelbeveiliging: is de warmtevraag aangegaan, dan blijft hij minstens zo lang aan (op minimale aanvoer als de vraag eerder wegvalt). Geldt in elke stand; alleen Verwarming uit gaat er direct doorheen.",
  minoff: "Minimaal uit", tip_minoff: "Pendelbeveiliging: is de warmtevraag uitgegaan, dan blijft hij minstens zo lang uit. Beschermt de compressor tegen vaak starten.",
  lock_on: m => `pendelbeveiliging: nog ${m} min aan`, lock_off: m => `pendelbeveiliging: nog ${m} min uit`,
  infl: "Kamerinvloed", tip_infl: "Alleen als het kastje zelf stuurt. Per graad dat de kamer onder het doel zit gaat de aanvoer zoveel graden omhoog (en erboven omlaag), maximaal 5 °C. 0 = uit, alleen aan/uit. Begin met 2.",
  adj: a => ` (${a > 0 ? "+" : ""}${a.toLocaleString("nl-NL", {maximumFractionDigits: 1})} kamer)`,
  shift: "Hele lijn", tip_shift: "Verschuift alle punten tegelijk een halve graad omhoog of omlaag (warmer of kouder). Daarna opslaan.",
  copyr: "Lijn van Roost", copyr_btn: "Overnemen", tip_copyr: "Kopieert de stooklijn van Roost één keer; daarna pas je hem zelf aan.", lg_roost: "Roost",
  min: "Minimale aanvoer", tip_min: "Laagste aanvoer die het kastje vraagt. Ook het startpunt van een zachte start.",
  max: "Maximale aanvoer", tip_max: "Hoogste aanvoer, ook als grens naar de warmtepomp gestuurd (OpenTherm ID 57). Nooit hoger dan wat de warmtepomp zelf toestaat (ID 49; de Weheat staat 40 °C toe). Voor vloerverwarming 45 °C of lager.",
  fixed: "Vaste aanvoer", tip_fixed: "Gebruikt als er geen buitentemperatuur is (warmtepomp en Home Assistant allebei stil).",
  sensor: "Kamersensor", tip_sensor: "Entiteit in Home Assistant die de kamer meet, bijvoorbeeld sensor.kamer_temperatuur. Na opslaan herstart het kastje eenmalig.",
  osensor: "Buitensensor", tip_osensor: "Optioneel: entiteit in Home Assistant voor buiten, bijvoorbeeld sensor.buiten_temperatuur, of een attribuut zoals weather.buienradar.temperature. Leeg = niet gebruiken. Na opslaan herstart het kastje eenmalig.",
  oprio: "Buiten volgens", tip_oprio: "Welke buitentemperatuur de stooklijn gebruikt. De luchtinlaat van de warmtepomp kan afwijken door ontdooien, koude lucht die terugstroomt of zon op de unit. Valt de gekozen bron weg, dan neemt het kastje de andere.",
  p_ot: "Luchtinlaat", p_ha: "Buitensensor", inlet: "Luchtinlaat warmtepomp",
  apply: "Toepassen", restart_note: "Het kastje herstart na opslaan (enkele seconden).",
  rs: {ok: "ontvangen", stale: "verouderd", waiting: "wacht op Home Assistant", no_value: "geen geldige waarde", invalid: "ongeldige entiteit", not_set: "niet ingesteld", restarting: "herstart…"},
  rsp: "Kamer bij terugval", tip_rsp: "Alleen als het kastje zelf stuurt (stooklijn, of Home Assistant weg): de kamertemperatuur waarop het aan/uit schakelt. Zolang Roost stuurt doet dit niets; Roost mag de kamer dan ook warmer stoken om warmte op te slaan. Met Volg Roost is dit de comfort van Roost. Gaat ook als informatie naar de warmtepomp (ID 16).",
  hy: "Schakelmarge", tip_hy: "Warmtevraag gaat aan op het kamerdoel en uit vanaf kamerdoel + marge. Zo pendelt de warmtepomp niet.",
  s_ha: "Home Assistant", s_cmd: "Opdracht van Roost", s_bus: "Warmtepomp (OpenTherm)", s_out: "Buitentemperatuur", s_room: "Kamertemperatuur",
  w_ha: [ "verbonden", "weg" ], w_ha_do: "Weg langer dan de opdrachttijd → stooklijn.",
  w_cmd_do: "Geen opdracht binnen de opdrachttijd → stooklijn.", w_cmd_na: "Niet nodig in de stand Stooklijn.",
  w_bus: [ "antwoordt", "geen antwoord" ], errs: p => `${p} mislukt (10 min)`, w_bus_do: "Het kastje blijft sturen; de warmtepomp valt bij stilte zelf terug.",
  w_out_do: "Gekozen bron, dan de andere, dan de vaste aanvoer.",
  w_room_do: "Home Assistant langer dan 30 min weg of sensor niet beschikbaar → alleen stooklijn op buiten.",
  wifi: "Wifi", ip: "IP-adres", eth: "Ethernet", sig: "Signaal",
  wnew: "Ander wifi-netwerk", tip_wnew: "Het kastje probeert 30 seconden. Lukt dat niet, dan gaat het terug naar het vorige netwerk. Het IP-adres komt van je router.",
  ssid: "Netwerknaam", pw: "Wachtwoord", connect: "Verbinden",
  ws: {connecting: "verbinden…", connected: "verbonden", failed: "mislukt, terug op het vorige netwerk", invalid: "vul een netwerknaam in (wachtwoord leeg of minstens 8 tekens)"},
  defl: "Deze pagina gebruikt nog de standaardinlog (admin / Roost). Iedereen op je netwerk kan dan instellingen wijzigen.", defl_go: "Inlog wijzigen",
  login: "Inlog webpagina", tip_login: "Nieuwe gebruikersnaam en wachtwoord (minstens 8 tekens) voor deze pagina. Werkt direct; daarna log je opnieuw in. Vergeten? Druk in Home Assistant op Reset Web Login.",
  luser: "Gebruikersnaam", lpw: "Nieuw wachtwoord", lpw2: "Herhaal wachtwoord", lsave: "Inlog wijzigen",
  lmis: "De wachtwoorden zijn niet gelijk", lshort: "Gebruikersnaam nodig en wachtwoord van minstens 8 tekens", ldone: "Inlog gewijzigd, log opnieuw in",
  ls: {default: "standaard", custom: "eigen inlog", changed: "gewijzigd", invalid: "ongeldig", reset: "teruggezet"},
  c_log: "Log", log_none: "Nog geen logregels sinds het openen van de pagina.", log_clear: "Wissen", tip_log: "De laatste 200 logregels van het kastje (waarschuwingen en meldingen) sinds je deze pagina opende. Handig bij storingen, bijvoorbeeld \"Timeout while waiting for response\" als de warmtepomp niet antwoordt.",
  restart: "Herstarten", restart_q: "Kastje nu herstarten?", fw: "Firmware", up: "Aan sinds",
} : {
  title: "Heat pump control", offline: "No connection to the box", saved: "Saved", failed: "Failed",
  h: {
    home_assistant: "Home Assistant controls the flow temperature",
    curve: "The box runs its fallback curve",
    curve_ha_offline: "Fallback: Home Assistant is away",
    curve_no_command: "Fallback: no command from Home Assistant",
    off: "Heating is off",
  },
  why: {
    home_assistant: c => `Last command ${c}. If commands stop for longer than the command timeout, the heating curve takes over.`,
    curve: () => "Heating curve on outside temperature; on/off on room temperature.",
    curve_ha_offline: () => "The box runs its fallback curve until Home Assistant is back and sends a command.",
    curve_no_command: c => `Last command ${c}. The box runs its fallback curve until a command arrives.`,
    off: () => "No heat demand is sent to the heat pump. The heat pump handles hot water itself.",
  },
  never: "none since start", ago: m => m < 1 ? "just now" : `${m} min ago`,
  t_req: "Flow requested", t_flow: "Flow measured", t_ret: "Return", t_out: "Outside", t_room: "Room",
  src: {ot: "heat pump air inlet", ha: "outside sensor", none: "unknown: fixed flow"},
  demand_on: "heat demand on", demand_off: "no heat demand", setp: "target", setp_fb: "when falling back",
  chips: {mod: "Modulation", ch: "Heating active", comp: "Compressor", dhw: "Hot water", fault: "Fault", bus: "No OpenTherm"},
  c_control: "Control", c_curve: "Fallback curve", c_room: "Temperatures", c_safety: "Fallback and connections", c_net: "Network and box",
  mode: "Who controls", m_ha: "Home Assistant", m_curve: "Heating curve",
  tip_mode: "Home Assistant: Roost or an automation sets the flow temperature (Flow Setpoint). Heating curve: the box controls on its own, also without Home Assistant.",
  heating: "Heating", tip_heating: "Main switch. Off = no heat demand to the heat pump. Hot water keeps working.",
  fs: "Flow command", tip_fs: "The flow temperature Home Assistant or Roost asks for; 0 = no heat demand. Must be resent every few minutes, otherwise the heating curve takes over.",
  to: "Command timeout", tip_to: "How old a command may get (or how long Home Assistant may be away) before the box runs its fallback curve. Roost sends every 5 minutes.",
  follow: "Follow Roost", tip_follow: "Takes the heating curve and the comfort temperature from Roost automatically. Turn off to set them yourself.",
  points: "Points", lg_curve: "heating curve", lg_now: "now", lg_req: "requested by Home Assistant", lg_lim: "min/max", out: "Outside °C", flow: "Flow °C", add: "Add point", save: "Save heating curve",
  roost_lock: "Roost maintains this curve. Turn off Follow Roost to edit it.",
  now_pt: (o, f) => `Now ${o} outside → ${f} flow`, now_none: f => `No outside temperature → fixed flow ${f}`,
  soft: "Soft start above", tip_soft: "At a start the box first asks return + 2 °C so the pump starts at once. If the gap to the wanted flow is larger than this, it rises 1 °C per minute so the pump does not run at high speed for long. Smaller gap = straight away. 0 = always straight away.",
  minon: "Minimum on", tip_minon: "Anti-cycling: once heat demand starts it stays on at least this long (at minimum flow if the demand ends earlier). Applies in every mode; only Heating off overrides it.",
  minoff: "Minimum off", tip_minoff: "Anti-cycling: once heat demand stops it stays off at least this long. Protects the compressor against frequent starts.",
  lock_on: m => `anti-cycling: on for ${m} more min`, lock_off: m => `anti-cycling: off for ${m} more min`,
  infl: "Room influence", tip_infl: "Only when the box controls itself. For every degree the room is below target the flow rises this many degrees (and falls above it), at most 5 °C. 0 = off, on/off only. Start with 2.",
  adj: a => ` (${a > 0 ? "+" : ""}${a.toLocaleString("en-GB", {maximumFractionDigits: 1})} room)`,
  shift: "Whole curve", tip_shift: "Moves all points half a degree up or down (warmer or cooler). Save afterwards.",
  copyr: "Roost curve", copyr_btn: "Copy", tip_copyr: "Copies the Roost heating curve once; you then adjust it yourself.", lg_roost: "Roost",
  min: "Minimum flow", tip_min: "Lowest flow the box asks for; also where a soft start begins.",
  max: "Maximum flow", tip_max: "Highest flow, also sent to the heat pump as a limit (OpenTherm ID 57). Never above what the heat pump allows (ID 49; the Weheat allows 40 °C). 45 °C or lower for underfloor heating.",
  fixed: "Fixed flow", tip_fixed: "Used when there is no outside temperature (heat pump and Home Assistant both silent).",
  sensor: "Room sensor", tip_sensor: "Home Assistant entity that measures the room, for example sensor.living_room_temperature. The box restarts once after saving.",
  osensor: "Outside sensor", tip_osensor: "Optional: Home Assistant entity for outside, for example sensor.outside_temperature, or an attribute such as weather.home.temperature. Empty = not used. The box restarts once after saving.",
  oprio: "Outside from", tip_oprio: "Which outside temperature the heating curve uses. The heat pump air inlet can deviate through defrosting, recirculating cold air or sun on the unit. If the chosen source fails, the box uses the other.",
  p_ot: "Air inlet", p_ha: "Outside sensor", inlet: "Heat pump air inlet",
  apply: "Apply", restart_note: "The box restarts after saving (a few seconds).",
  rs: {ok: "received", stale: "stale", waiting: "waiting for Home Assistant", no_value: "no valid value", invalid: "invalid entity", not_set: "not set", restarting: "restarting…"},
  rsp: "Room when falling back", tip_rsp: "Only when the box steers itself (heating curve, or Home Assistant gone): the room temperature it switches on/off at. While Roost steers this does nothing; Roost may then heat the room warmer to store heat. With Follow Roost this is Roost's comfort. Also sent to the heat pump as information (ID 16).",
  hy: "Switching margin", tip_hy: "Heat demand turns on at the room target and off from target + margin, so the heat pump does not cycle.",
  s_ha: "Home Assistant", s_cmd: "Command from Roost", s_bus: "Heat pump (OpenTherm)", s_out: "Outside temperature", s_room: "Room temperature",
  w_ha: [ "connected", "away" ], w_ha_do: "Away longer than the command timeout → heating curve.",
  w_cmd_do: "No command within the command timeout → heating curve.", w_cmd_na: "Not needed in heating curve mode.",
  w_bus: [ "answering", "no answer" ], errs: p => `${p} failed (10 min)`, w_bus_do: "The box keeps controlling; the heat pump falls back on its own when the bus is silent.",
  w_out_do: "Chosen source, then the other, then fixed flow.",
  w_room_do: "Home Assistant away for over 30 min or sensor unavailable → heating curve on outside only.",
  wifi: "Wi-Fi", ip: "IP address", eth: "Ethernet", sig: "Signal",
  wnew: "Other Wi-Fi network", tip_wnew: "The box tries for 30 seconds and returns to the previous network if that fails. The IP address comes from your router.",
  ssid: "Network name", pw: "Password", connect: "Connect",
  ws: {connecting: "connecting…", connected: "connected", failed: "failed, back on the previous network", invalid: "enter a network name (password empty or at least 8 characters)"},
  defl: "This page still uses the default login (admin / Roost). Anyone on your network can change settings.", defl_go: "Change login",
  login: "Page login", tip_login: "New username and password (at least 8 characters) for this page. Takes effect at once; you then sign in again. Forgotten? Press Reset Web Login in Home Assistant.",
  luser: "Username", lpw: "New password", lpw2: "Repeat password", lsave: "Change login",
  lmis: "The passwords do not match", lshort: "Username needed and a password of at least 8 characters", ldone: "Login changed, sign in again",
  ls: {default: "default", custom: "own login", changed: "changed", invalid: "invalid", reset: "reset"},
  c_log: "Log", log_none: "No log lines since this page was opened.", log_clear: "Clear", tip_log: "The last 200 log lines of the box (warnings and messages) since you opened this page. Useful for faults, for example \"Timeout while waiting for response\" when the heat pump does not answer.",
  restart: "Restart", restart_q: "Restart the box now?", fw: "Firmware", up: "Up for",
};

// ------------------------------------------------------------------ toestand en API -------
const S = {};
const LOG = []; // laatste 200 logregels {t, c}
let editingCurve = null, pointer = false;
const draft = {};
const v = id => S[id] ? S[id].value : undefined;
const num = id => { const x = parseFloat(v(id)); return Number.isFinite(x) ? x : null; };
const fmt = (x, d = 1, u = " °C") => x == null ? "–" : x.toLocaleString(NL ? "nl-NL" : "en-GB", {minimumFractionDigits: d, maximumFractionDigits: d}) + u;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
const tip = t => `<span class="tip" tabindex="0" role="button" aria-label="${esc(t)}" data-t="${esc(t)}">i</span>`;

async function call(id, action, params) {
  const q = params ? "?" + new URLSearchParams(params) : "";
  try {
    const r = await fetch(`/${id.split("/").map(encodeURIComponent).join("/")}/${action}${q}`, {method: "POST", body: ""});
    toast(r.ok ? T.saved : T.failed);
    return r.ok;
  } catch (e) { toast(T.failed); return false; }
}
const setNum = (id, x) => call(id, "set", {value: x});
const setText = (id, x) => call(id, "set", {value: x});
const setOpt = (id, x) => call(id, "set", {option: x});
const setSw = (id, on) => call(id, on ? "turn_on" : "turn_off");

let toastT;
function toast(t) {
  const el = document.getElementById("toast");
  el.textContent = t; el.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("show"), 1600);
}

// ------------------------------------------------------------------ bouwstenen ------------
function numberRow(id, label, help) {
  const e = S[id]; if (!e) return "";
  const step = e.step || 0.5, unit = e.uom || "";
  return `<div class="row"><div class="l">${label}${tip(help)}</div><div class="r">
    <input type="number" data-num="${esc(id)}" value="${esc(v(id))}" min="${e.min_value}" max="${e.max_value}" step="${step}">
    <span class="unit">${esc(unit)}</span></div></div>`;
}
function switchRow(id, label, help) {
  return `<div class="row"><div class="l">${label}${tip(help)}</div><div class="r">
    <label class="sw"><input type="checkbox" data-sw="${esc(id)}" ${v(id) ? "checked" : ""}><span></span></label></div></div>`;
}
function stateRow(cls, title, status, what) {
  const icon = {ok: "✓", warn: "!", bad: "×", na: "–"}[cls];
  return `<div class="row"><div class="l"><span class="state ${cls}">${icon}</span><div><div>${title} <span class="muted">· ${esc(status)}</span></div>
    <div class="what">${what}</div></div></div></div>`;
}
function bars(dbm) {
  const n = dbm == null ? 0 : dbm >= -55 ? 4 : dbm >= -65 ? 3 : dbm >= -75 ? 2 : 1;
  return `<span class="bars">${[6, 9, 12, 14].map((h, i) => `<i class="${i < n ? "f" : ""}" style="height:${h}px"></i>`).join("")}</span>`;
}
const curvePoints = () => String(v("text/Heating Curve") || "").split(",").map(p => p.split(":").map(Number)).filter(p => p.length === 2 && p.every(Number.isFinite));

function chart(pts) {
  const W = 520, H = 230, L = 36, R = 12, Tp = 12, B = 26;
  const ub = num("sensor/Max Flow Limit (heat pump)"), lo = num("number/Min Flow") ?? 20, hi = Math.min(num("number/Max Flow") ?? 45, ub != null && ub >= 20 ? ub : 99);
  const xs = pts.map(p => p[0]), out = num("sensor/Outside Temperature (used)");
  const x0 = Math.min(-20, ...xs, out ?? 0) - 2, x1 = Math.max(25, ...xs, out ?? 0) + 2;
  const y0 = Math.floor(Math.min(lo, ...pts.map(p => p[1])) / 5) * 5 - 2, y1 = Math.ceil(Math.max(hi, ...pts.map(p => p[1])) / 5) * 5 + 2;
  const X = x => L + (x - x0) / (x1 - x0) * (W - L - R), Y = y => H - B - (y - y0) / (y1 - y0) * (H - Tp - B);
  let g = `<g class="grid">`;
  for (let x = Math.ceil(x0 / 5) * 5; x <= x1; x += 5) g += `<line x1="${X(x)}" x2="${X(x)}" y1="${Tp}" y2="${H - B}"/><text x="${X(x)}" y="${H - 8}" text-anchor="middle">${x}°</text>`;
  for (let y = Math.ceil(y0 / 5) * 5; y <= y1; y += 5) g += `<line x1="${L}" x2="${W - R}" y1="${Y(y)}" y2="${Y(y)}"/><text x="${L - 6}" y="${Y(y) + 4}" text-anchor="end">${y}°</text>`;
  g += `</g>`;
  const clamp = y => Math.max(lo, Math.min(hi, y));
  const line = [[x0, clamp(pts[0][1])], ...pts.map(p => [p[0], clamp(p[1])]), [x1, clamp(pts[pts.length - 1][1])]];
  let s = g + `<line class="lim" x1="${L}" x2="${W - R}" y1="${Y(hi)}" y2="${Y(hi)}"/><line class="lim" x1="${L}" x2="${W - R}" y1="${Y(lo)}" y2="${Y(lo)}"/>`;
  const rp = String(v("text_sensor/Roost Curve") || "").split(",").map(p => p.split(":").map(Number)).filter(p => p.length === 2 && p.every(Number.isFinite));
  const showRoost = rp.length >= 2 && rp.map(p => p.join(":")).join(",") !== pts.map(p => p.join(":")).join(",");
  if (showRoost) s += `<polyline class="roost" points="${rp.map(p => `${X(p[0])},${Y(clamp(p[1]))}`).join(" ")}"/>`;
  s += `<polyline class="curve" points="${line.map(p => `${X(p[0])},${Y(p[1])}`).join(" ")}"/>`;
  s += pts.map(p => `<circle class="pt" cx="${X(p[0])}" cy="${Y(clamp(p[1]))}" r="4"/>`).join("");
  const cf = num("sensor/Curve Flow"), ra = num("sensor/Room Adjustment") || 0;
  if (out != null && cf != null) s += `<circle class="now" cx="${X(out)}" cy="${Y(Math.max(lo, Math.min(hi, cf + ra)))}" r="6"/>`;
  const st = v("text_sensor/Control State"), req = num("sensor/Flow Setpoint Active");
  if (st === "home_assistant" && out != null && req != null && v("binary_sensor/Heat Demand")) s += `<circle class="req" cx="${X(out)}" cy="${Y(req)}" r="5"/>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(T.c_curve)}">${s}</svg>
    <div class="legend small muted"><span><i class="lg c"></i>${T.lg_curve}</span><span><i class="lg n"></i>${T.lg_now}</span>${st === "home_assistant" ? `<span><i class="lg r"></i>${T.lg_req}</span>` : ""}${showRoost ? `<span><i class="lg rr"></i>${T.lg_roost}</span>` : ""}<span><i class="lg l"></i>${T.lg_lim}</span></div>`;
}

// ------------------------------------------------------------------ pagina ----------------
function render() {
  const st = v("text_sensor/Control State") || "off";
  const age = num("sensor/Command Age");
  const ageTxt = age == null ? T.never : T.ago(Math.floor(age / 60));
  const src = v("text_sensor/Outside Source") || "none";
  const demand = !!v("binary_sensor/Heat Demand");
  const commErr = !!v("binary_sensor/Communication Error"), fault = !!v("binary_sensor/Fault");
  const haMode = v("select/Control Mode") !== "Heating curve";
  const pts = curvePoints(), follow = !!v("switch/Follow Roost Curve");
  const out = num("sensor/Outside Temperature (used)"), cf = num("sensor/Curve Flow");
  const rstat = v("text_sensor/Room Sensor Status") || "";
  const haOn = !!v("binary_sensor/Home Assistant Connected");
  const timeoutMin = num("number/Command Timeout") ?? 15;
  const prioHa = v("select/Outside Temperature Source") === "Outside sensor";
  const ws = v("text_sensor/WiFi Setup Status");
  const tF = num("sensor/Flow Temperature"), tR = num("sensor/Return Temperature");
  const dT = tF != null && tR != null ? tF - tR : null; // alleen tonen; de Weheat regelt zijn eigen doorstroming
  const lockS = num("sensor/Demand Lock") || 0, ra = num("sensor/Room Adjustment") || 0;
  const lockTxt = lockS > 0 ? (demand ? T.lock_on : T.lock_off)(Math.ceil(lockS / 60)) : "";

  const hero = `<section class="card wide hero s-${esc(st)}">
    <p class="headline">${esc(T.h[st] || st)}</p><p class="why">${esc((T.why[st] || (() => ""))(ageTxt))}</p>
    <div class="tiles">
      <div class="tile"><div class="k">${T.t_req}</div><div class="v">${demand ? fmt(num("sensor/Flow Setpoint Active")) : "–"}</div><div class="s">${lockTxt || (demand ? T.demand_on : T.demand_off)}</div></div>
      <div class="tile"><div class="k">${T.t_flow}</div><div class="v">${fmt(num("sensor/Flow Temperature"))}</div><div class="s">${T.t_ret} ${fmt(num("sensor/Return Temperature"))}${dT != null ? ` · ΔT ${fmt(dT)}` : ""}</div></div>
      <div class="tile"><div class="k">${T.t_out}</div><div class="v">${fmt(out)}</div><div class="s">${esc(T.src[src])}</div></div>
      <div class="tile"><div class="k">${T.t_room}</div><div class="v">${fmt(num("sensor/Room Temperature"))}</div><div class="s">${v("text_sensor/Control State") === "home_assistant" ? T.setp_fb : T.setp} ${fmt(num("number/Fallback Room Setpoint"))}</div></div>
    </div>
    <div class="chips">
      <span class="chip ${v("binary_sensor/Heating Active") ? "on" : ""}">${T.chips.ch}</span>
      <span class="chip ${v("binary_sensor/Compressor Running") ? "on" : ""}">${T.chips.comp}</span>
      <span class="chip ${v("binary_sensor/Hot Water Active") ? "on" : ""}">${T.chips.dhw}</span>
      ${fault ? `<span class="chip bad">${T.chips.fault}</span>` : ""}
      ${commErr ? `<span class="chip bad">${T.chips.bus}</span>` : ""}
    </div></section>`
    + (v("text_sensor/Web Login Status") === "default" ? `<section class="card warnbar"><span>${T.defl}</span><button id="gologin">${T.defl_go}</button></section>` : "");

  const mode = `<div class="row"><div class="l">${T.mode}${tip(T.tip_mode)}</div><div class="r"><div class="seg">
      <button data-mode="Home Assistant" class="${haMode ? "sel" : ""}">${T.m_ha}</button>
      <button data-mode="Heating curve" class="${haMode ? "" : "sel"}">${T.m_curve}</button></div></div></div>`;
  const control = `<section class="card"><h2>${T.c_control}</h2>${mode}
    ${switchRow("switch/Heating", T.heating, T.tip_heating)}
    ${haMode ? numberRow("number/Flow Setpoint", T.fs, T.tip_fs) + numberRow("number/Command Timeout", T.to, T.tip_to) : ""}
    ${numberRow("number/Soft Start Above", T.soft, T.tip_soft)}${numberRow("number/Min Run Time", T.minon, T.tip_minon)}${numberRow("number/Min Off Time", T.minoff, T.tip_minoff)}
    ${lockTxt ? `<div class="note">${esc(lockTxt)}</div>` : ""}
    </section>`;

  const ed = editingCurve || pts;
  const curve = `<section class="card"><h2>${T.c_curve}</h2>
    ${pts.length >= 2 ? chart(pts) : ""}
    <p class="small muted">${out != null && cf != null ? esc(T.now_pt(fmt(out), fmt(cf)) + (ra ? T.adj(ra) : "")) : esc(T.now_none(fmt(num("number/Fixed Flow"))))}</p>
    ${switchRow("switch/Follow Roost Curve", T.follow, T.tip_follow)}
    <table><tr><th>${T.out}</th><th>${T.flow}</th><th></th></tr>
    ${ed.map((p, i) => `<tr><td><input type="number" step="0.5" data-pt="${i},0" value="${p[0]}" ${follow ? "disabled" : ""}></td>
      <td><div class="step">${follow ? "" : `<button class="x" data-bump="${i},-0.5" aria-label="-">−</button>`}<input type="number" step="0.5" data-pt="${i},1" value="${p[1]}" ${follow ? "disabled" : ""}>${follow ? "" : `<button class="x" data-bump="${i},0.5" aria-label="+">+</button>`}</div></td>
      <td>${follow || ed.length <= 2 ? "" : `<button class="x" data-del="${i}" aria-label="×">×</button>`}</td></tr>`).join("")}
    </table>
    ${follow ? `<div class="note">${T.roost_lock}</div>` : `
      <div class="row"><div class="l">${T.shift}${tip(T.tip_shift)}</div><div class="r"><button class="ghost" data-shift="-0.5">− 0,5</button><button class="ghost" data-shift="0.5">+ 0,5</button></div></div>
      ${v("text_sensor/Roost Curve") ? `<div class="row"><div class="l">${T.copyr}${tip(T.tip_copyr)}</div><div class="r"><button class="ghost" id="copyroost">${T.copyr_btn}</button></div></div>` : ""}
      <div class="row"><div class="l">${ed.length < 8 ? `<button class="ghost" id="addpt">${T.add}</button>` : ""}</div><div class="r"><button id="savecurve" ${editingCurve ? "" : "disabled"}>${T.save}</button></div></div>`}
    ${numberRow("number/Min Flow", T.min, T.tip_min)}${numberRow("number/Max Flow", T.max, T.tip_max)}${numberRow("number/Fixed Flow", T.fixed, T.tip_fixed)}
    </section>`;

  const ostat = v("text_sensor/Outside Sensor Status") || "";
  const room = `<section class="card"><h2>${T.c_room}</h2>
    <div class="row"><div class="l">${T.sensor}${tip(T.tip_sensor)}</div><div class="r small muted">${esc(T.rs[rstat] || rstat)} · ${fmt(num("sensor/Room Temperature"))}</div></div>
    <div class="row"><input type="text" id="roomsensor" value="${esc(draft.roomsensor ?? v("text/Room Sensor"))}" spellcheck="false" autocapitalize="off"><button data-save="roomsensor" data-ent="text/Room Sensor">${T.apply}</button></div>
    ${numberRow("number/Fallback Room Setpoint", T.rsp, T.tip_rsp)}${numberRow("number/Room Hysteresis", T.hy, T.tip_hy)}${numberRow("number/Room Influence", T.infl, T.tip_infl)}
    <div class="row"><div class="l">${T.oprio}${tip(T.tip_oprio)}</div><div class="r"><div class="seg">
      <button data-oprio="Heat pump air inlet" class="${prioHa ? "" : "sel"}">${T.p_ot}</button>
      <button data-oprio="Outside sensor" class="${prioHa ? "sel" : ""}">${T.p_ha}</button></div></div></div>
    <div class="row"><div class="l">${T.inlet}</div><div class="r">${fmt(num("sensor/Air Inlet Temperature"))}</div></div>
    <div class="row"><div class="l">${T.osensor}${tip(T.tip_osensor)}</div><div class="r small muted">${esc(T.rs[ostat] || ostat)} · ${fmt(num("sensor/Outside Temperature (sensor)"))}</div></div>
    <div class="row"><input type="text" id="outsensor" value="${esc(draft.outsensor ?? v("text/Outside Sensor"))}" spellcheck="false" autocapitalize="off"><button data-save="outsensor" data-ent="text/Outside Sensor">${T.apply}</button></div>
    </section>`;

  const busOk = !commErr, roomOk = rstat === "ok", errRate = num("sensor/OpenTherm Error Rate");
  const cmdCls = !haMode ? "na" : age != null && age < timeoutMin * 60 ? "ok" : "warn";
  const safety = `<section class="card safety"><h2>${T.c_safety}</h2>
    ${stateRow(haOn ? "ok" : "warn", T.s_ha, T.w_ha[haOn ? 0 : 1], T.w_ha_do)}
    ${stateRow(cmdCls, T.s_cmd, haMode ? ageTxt : "–", haMode ? T.w_cmd_do : T.w_cmd_na)}
    ${stateRow(busOk ? (errRate != null && errRate > 5 ? "warn" : "ok") : "bad", T.s_bus, T.w_bus[busOk ? 0 : 1] + (errRate != null ? ` · ${T.errs(fmt(errRate, 1, " %"))}` : ""), T.w_bus_do)}
    ${stateRow(src === "none" ? "bad" : src === (prioHa ? "ha" : "ot") ? "ok" : "warn", T.s_out, T.src[src], T.w_out_do)}
    ${stateRow(roomOk ? "ok" : "warn", T.s_room, T.rs[rstat] || "–", T.w_room_do)}
    </section>`;

  const sig = num("sensor/WiFi Signal");
  const net = `<section class="card"><h2>${T.c_net}</h2>
    <div class="row"><div class="l">${T.wifi}</div><div class="r">${esc(v("text_sensor/WiFi Connected Network") || "–")} ${bars(sig)} <span class="small muted">${sig == null ? "" : sig + " dBm"}</span></div></div>
    <div class="row"><div class="l">${T.ip}</div><div class="r">${esc(v("text_sensor/WiFi IP Address") || "–")}</div></div>
${S["text_sensor/Ethernet IP Address"] ? `    <div class="row"><div class="l">${T.eth}</div><div class="r">${esc(v("text_sensor/Ethernet IP Address") && v("text_sensor/Ethernet IP Address") !== "0.0.0.0" ? v("text_sensor/Ethernet IP Address") : "–")}</div></div>` : ""}
    <div class="row"><div class="l">${T.wnew}${tip(T.tip_wnew)}</div><div class="r small muted">${ws ? esc(T.ws[ws] || ws) : ""}</div></div>
    <div class="row"><input type="text" id="ssid" placeholder="${T.ssid}" autocapitalize="off" value="${esc(draft.ssid ?? "")}"></div>
    <div class="row"><input type="password" id="wpw" placeholder="${T.pw}" value="${esc(draft.wpw ?? "")}"><button id="wifigo">${T.connect}</button></div>
    <div class="row"><div class="l">${T.login}${tip(T.tip_login)}</div><div class="r small muted">${esc(T.ls[v("text_sensor/Web Login Status")] || "")}</div></div>
    <div class="row"><input type="text" id="luser" placeholder="${T.luser}" autocomplete="username" autocapitalize="off" value="${esc(draft.luser ?? "")}"></div>
    <div class="row"><input type="password" id="lpw" placeholder="${T.lpw}" autocomplete="new-password" value="${esc(draft.lpw ?? "")}"></div>
    <div class="row"><input type="password" id="lpw2" placeholder="${T.lpw2}" autocomplete="new-password" value="${esc(draft.lpw2 ?? "")}"><button id="loginset">${T.lsave}</button></div>
    <div class="row"><div class="l small muted">${T.fw} ${esc(v("text_sensor/Firmware") || "")}</div><div class="r"><button class="ghost" id="restart">${T.restart}</button></div></div>
    </section>`;

  const logc = `<section class="card"><h2>${T.c_log}${tip(T.tip_log)}</h2>
    <div class="row"><div class="l small muted">${LOG.length} / 200</div><div class="r"><button class="ghost" id="logclear">${T.log_clear}</button></div></div>
    <pre class="log">${LOG.length ? LOG.slice().reverse().map(l => `<span class="${l.c}">${esc(l.t)}</span>`).join("\n") : esc(T.log_none)}</pre></section>`;
  patch({hero, control, curve, room, safety, net, logc});
}

// Alleen kaarten vervangen die veranderd zijn, en nooit de kaart waarin iemand typt of klikt.
// Indeling: telefoon één kolom in leesvolgorde; breed scherm twee kolommen die elk hun eigen hoogte hebben.
const ORDER = {one: [["hero", "control", "curve", "room", "safety", "net", "logc"]], two: [["control", "room", "net"], ["curve", "safety", "logc"]]};
const wide = matchMedia("(min-width: 820px)");
function layout() {
  const app = document.getElementById("app"), cols = ORDER[wide.matches ? "two" : "one"];
  const nodes = {};
  for (const k of ORDER.one[0]) { nodes[k] = app.querySelector(`[data-k="${k}"]`); if (!nodes[k]) { nodes[k] = document.createElement("div"); nodes[k].className = "box"; nodes[k].dataset.k = k; } }
  app.replaceChildren();
  if (wide.matches) app.appendChild(nodes.hero);
  for (const list of cols) {
    const col = document.createElement("div"); col.className = "col";
    for (const k of list) if (k !== "hero" || !wide.matches) col.appendChild(nodes[k]);
    app.appendChild(col);
  }
}
wide.addEventListener("change", layout);

const shown = {};
function patch(parts) {
  const app = document.getElementById("app");
  for (const [key, html] of Object.entries(parts)) {
    const el = app.querySelector(`[data-k="${key}"]`);
    if (!el) continue;
    if (shown[key] === html) continue;
    // Niet vervangen terwijl iemand in een invulveld van deze kaart typt (knoppen en schakelaars tellen niet).
    const a = document.activeElement;
    const typing = a && el.contains(a) && a.matches("input[type=text], input[type=number], input[type=password]");
    if (typing || (pointer && el.matches(":hover"))) continue;
    el.innerHTML = html; shown[key] = html;
  }
}

// ------------------------------------------------------------------ invoer ----------------
let timer;
function schedule() { clearTimeout(timer); timer = setTimeout(render, 150); }
function forceRender(key) { delete shown[key]; const el = document.querySelector(`[data-k="${key}"]`); if (el) el.innerHTML = ""; pointer = false; document.activeElement?.blur?.(); render(); }
document.addEventListener("pointerdown", () => { pointer = true; });
document.addEventListener("pointerup", () => { setTimeout(() => { pointer = false; schedule(); }, 300); });
document.addEventListener("focusout", () => setTimeout(schedule, 300));
document.addEventListener("input", e => { if (["roomsensor", "outsensor", "ssid", "wpw", "luser", "lpw", "lpw2"].includes(e.target.id)) draft[e.target.id] = e.target.value; });
document.addEventListener("change", e => {
  const t = e.target;
  if (t.dataset.num) setNum(t.dataset.num, t.value);
  else if (t.dataset.sw) setSw(t.dataset.sw, t.checked);
  else if (t.dataset.pt) {
    const [i, k] = t.dataset.pt.split(",").map(Number);
    editingCurve = (editingCurve || curvePoints()).map(p => p.slice());
    editingCurve[i][k] = parseFloat(t.value);
    document.getElementById("savecurve")?.removeAttribute("disabled");
  }
});
document.addEventListener("click", async e => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.dataset.mode) setOpt("select/Control Mode", t.dataset.mode);
  else if (t.dataset.del) { editingCurve = (editingCurve || curvePoints()).filter((_, i) => i !== +t.dataset.del); forceRender("curve"); }
  else if (t.dataset.bump) {
    const [i, d] = t.dataset.bump.split(",").map(Number);
    editingCurve = (editingCurve || curvePoints()).map(q => q.slice());
    editingCurve[i][1] = Math.max(10, Math.min(60, Math.round((editingCurve[i][1] + d) * 2) / 2)); forceRender("curve");
  } else if (t.dataset.shift) {
    const d = Number(t.dataset.shift);
    editingCurve = (editingCurve || curvePoints()).map(q => [q[0], Math.max(10, Math.min(60, Math.round((q[1] + d) * 2) / 2))]); forceRender("curve");
  } else if (t.id === "copyroost") { if (await call("button/Copy Roost Curve", "press")) { editingCurve = null; forceRender("curve"); } }
  else if (t.id === "addpt") {
    const p = (editingCurve || curvePoints()).map(q => q.slice()), last = p[p.length - 1];
    p.push([Math.min(40, last[0] + 5), last[1]]); editingCurve = p; forceRender("curve");
  } else if (t.id === "savecurve" && editingCurve) {
    const p = editingCurve.filter(q => q.every(Number.isFinite)).sort((a, b) => a[0] - b[0]);
    if (await setText("text/Heating Curve", p.map(q => `${q[0]}:${q[1]}`).join(","))) { editingCurve = null; forceRender("curve"); }
  } else if (t.dataset.oprio) setOpt("select/Outside Temperature Source", t.dataset.oprio);
  else if (t.dataset.save) { if (await setText(t.dataset.ent, document.getElementById(t.dataset.save).value.trim())) delete draft[t.dataset.save]; }
  else if (t.id === "wifigo") {
    if (await setText("text/WiFi Network", document.getElementById("ssid").value.trim()) &&
        await setText("text/WiFi Password", document.getElementById("wpw").value)) { delete draft.wpw; call("button/Apply WiFi", "press"); }
  } else if (t.id === "gologin") {
    const el = document.getElementById("luser"); el.scrollIntoView({behavior: "smooth", block: "center"}); setTimeout(() => el.focus(), 400);
  } else if (t.id === "loginset") {
    const u = document.getElementById("luser").value.trim(), p = document.getElementById("lpw").value, p2 = document.getElementById("lpw2").value;
    if (p !== p2) return toast(T.lmis);
    if (!u || p.length < 8 || /[\s:"]/.test(u)) return toast(T.lshort);
    if (await setText("text/Web Username", u) && await setText("text/Web Password", p) && await call("button/Apply Web Login", "press")) {
      for (const k of ["luser", "lpw", "lpw2"]) delete draft[k];
      toast(T.ldone); setTimeout(() => location.reload(), 1500);
    }
  } else if (t.id === "logclear") { LOG.length = 0; forceRender("logc"); }
  else if (t.id === "restart" && confirm(T.restart_q)) call("button/Restart", "press");
});

// ------------------------------------------------------------------ uitleg (i) -----------
// Eén zwevend vak, altijd binnen het scherm: muis (hover), toetsenbord (focus) en tikken.
let tipFor = null;
function showTip(el) {
  const box = document.getElementById("tipbox");
  box.textContent = el.dataset.t; box.classList.add("show"); tipFor = el;
  const r = el.getBoundingClientRect(), b = box.getBoundingClientRect(), m = 8;
  const left = Math.max(m, Math.min(innerWidth - b.width - m, r.left + r.width / 2 - b.width / 2));
  const top = r.top - b.height - m >= m ? r.top - b.height - m : r.bottom + m;
  box.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
}
function hideTip() { document.getElementById("tipbox").classList.remove("show"); tipFor = null; }
document.addEventListener("pointerover", e => { const t = e.target.closest?.(".tip"); if (t && e.pointerType === "mouse") showTip(t); });
document.addEventListener("pointerout", e => { if (e.target.closest?.(".tip") && e.pointerType === "mouse") hideTip(); });
document.addEventListener("focusin", e => { if (e.target.matches?.(".tip")) showTip(e.target); });
document.addEventListener("focusout", e => { if (e.target.matches?.(".tip")) hideTip(); });
document.addEventListener("click", e => { const t = e.target.closest?.(".tip"); if (t) { tipFor === t ? hideTip() : showTip(t); } else if (tipFor) hideTip(); }, true);
addEventListener("scroll", hideTip, {passive: true});

// ------------------------------------------------------------------ start -----------------
function start() {
  // ESPHome levert geen viewport-meta; zonder dit toont een telefoon een verkleinde desktoppagina.
  document.head.insertAdjacentHTML("beforeend", '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">');
  document.documentElement.lang = NL ? "nl" : "en";
  document.title = "THRM ONE";
  document.body.insertAdjacentHTML("afterbegin", `<main><header><span class="dot" id="dot"></span><div><h1>THRM ONE</h1>
    <div class="sub" id="sub">${T.title}</div></div></header><div class="grid" id="app"></div><footer id="foot"></footer></main><div class="toast" id="toast"></div><div id="tipbox" role="tooltip"></div>`);
  layout();
  let title = "";
  const es = new EventSource("/events");
  es.addEventListener("ping", e => {
    try { const d = JSON.parse(e.data); if (d.title) { title = d.title; document.getElementById("sub").textContent = `${title} · ${T.title}`; } } catch (_) {}
  });
  es.addEventListener("log", e => {
    const t = String(e.data).replace(/\x1b\[[0-9;]*m/g, "");
    const c = /\[E\]/.test(t) ? "le" : /\[W\]/.test(t) ? "lw" : "";
    LOG.push({t, c}); if (LOG.length > 200) LOG.shift(); schedule();
  });
  es.addEventListener("state", e => { try { const d = JSON.parse(e.data); S[d.id] = Object.assign(S[d.id] || {}, d); schedule(); } catch (_) {} });
  es.onopen = () => { document.getElementById("dot").className = "dot on"; document.getElementById("sub").textContent = title ? `${title} · ${T.title}` : T.title; };
  es.onerror = () => { document.getElementById("dot").className = "dot"; document.getElementById("sub").textContent = T.offline; };
}
start();
