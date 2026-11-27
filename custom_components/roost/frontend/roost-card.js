/* Roost card - served by the roost integration. */
(() => {   // own scope: safe if the file is loaded twice as a classic script (legacy frontend + a manual resource)
const CARD_VERSION = "0.9.0";

// Plain ES2017 on purpose (no ?. / ??), ASCII only (\u escapes): wall tablets often run an older browser.
const nn = (a, b) => (a === null || a === undefined ? b : a);
const DEG = "\u00b0C";

// A redraw brings the card's DOM in line with the new HTML and touches only what differs. The nodes stay, so their
// scroll position, focus, a half-typed value and the page around the card keep where they were (a redraw used to
// replace everything: the card collapsed for a moment and a phone's page jumped). Blocks with data-k are matched by
// that key, the rest by position and tag.
const keyOf = (n) => (n.nodeType === 1 ? n.getAttribute("data-k") : null);
const sameNode = (a, b) => a.nodeType === b.nodeType && a.nodeName === b.nodeName && keyOf(a) === keyOf(b);
const patchNode = (a, b) => {
  if (a.nodeType !== 1) { if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue; return; }
  const busy = a.tagName === "INPUT" && a.getRootNode && a.getRootNode().activeElement === a;
  for (let i = 0; i < b.attributes.length; i++) {
    const at = b.attributes[i];
    if (a.getAttribute(at.name) !== at.value) a.setAttribute(at.name, at.value);
  }
  for (let i = a.attributes.length - 1; i >= 0; i--) {
    const name = a.attributes[i].name;
    if (!b.hasAttribute(name)) a.removeAttribute(name);
  }
  if (a.tagName === "INPUT") {
    // the value someone is typing stays; otherwise the field shows what the card knows now
    const v = b.getAttribute("value") || "";
    if (!busy && a.value !== v) a.value = v;
    return;
  }
  if (a.tagName === "DETAILS") a.open = b.hasAttribute("open");
  morphChildren(a, b);
};
const morphChildren = (from, to) => {
  let a = from.firstChild, b = to.firstChild;
  while (b) {
    const next = b.nextSibling, k = keyOf(b);
    if (a && sameNode(a, b)) { patchNode(a, b); a = a.nextSibling; b = next; continue; }
    let match = null;
    if (k !== null) {        // a keyed block further on: move it here (a block before it was removed or added)
      for (let c = a; c; c = c.nextSibling) if (keyOf(c) === k && c.nodeName === b.nodeName) { match = c; break; }
    } else if (a && a.nextSibling && sameNode(a.nextSibling, b) && !(next && sameNode(a, next))) {
      match = a.nextSibling;   // one node less than before
    }
    if (match) {
      while (a && a !== match && k === null) { const n = a.nextSibling; from.removeChild(a); a = n; }
      if (a !== match) from.insertBefore(match, a);
      else a = a.nextSibling;
      patchNode(match, b);
    } else if (a && !(next && sameNode(a, next)) && keyOf(a) === null && k === null) {
      const n = a.nextSibling; from.replaceChild(b, a); a = n;
    } else {
      from.insertBefore(b, a);
    }
    b = next;
  }
  while (a) { const n = a.nextSibling; from.removeChild(a); a = n; }
};
const morph = (el, html) => {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  morphChildren(el, tpl.content);
};
// A number typed the local way ("20,5" or "20.5"); NaN when it is not one
const parseNum = (s) => {
  const t = String(s === null || s === undefined ? "" : s).trim().replace(/\s/g, "").replace(",", ".").replace(/[^0-9.+-]/g, "");
  return t === "" || t === "." || t === "-" ? NaN : Number(t);
};
// Number and time formats, made once per language and kind (a redraw formats a few hundred numbers and times; making
// the format each time was about a third of the drawing work on a slow tablet). Same results as toLocaleString.
const FMTS = {};
const numFmt = (loc, d) => {
  const k = "n|" + loc + "|" + d;
  return FMTS[k] || (FMTS[k] = new Intl.NumberFormat(loc, { minimumFractionDigits: d, maximumFractionDigits: d }));
};
const cashFmt = (loc, cur, digits) => {   // digits: undefined = the currency's own
  const k = "c|" + loc + "|" + cur + "|" + digits, opts = { style: "currency", currency: cur };
  if (digits !== undefined) { opts.minimumFractionDigits = digits; opts.maximumFractionDigits = digits; }
  return FMTS[k] || (FMTS[k] = new Intl.NumberFormat(loc, opts));
};
const timeFmt = (loc, h12) => {   // h12: true, false or undefined (the locale's own)
  const k = "t|" + loc + "|" + h12, opts = { hour: "2-digit", minute: "2-digit" };
  if (h12 !== undefined) opts.hour12 = h12;
  return FMTS[k] || (FMTS[k] = new Intl.DateTimeFormat(loc, opts));
};
const dayFmt = (loc) => FMTS["d|" + loc] || (FMTS["d|" + loc] = new Intl.DateTimeFormat(loc, { weekday: "short" }));
// Snaps a value to the setting's step and limits
const snap = (v, lo, hi, step) => {
  const s = step || 1, r = Math.round(v / s) * s;
  return Math.min(hi, Math.max(lo, Math.round(r * 1000) / 1000));
};

const T = {
  en: { title: "Roost", room: "Room", thermostat: "Thermostat", next24: "Next 24 hours",
        setpoint: "setpoint", expected: "room expected", price: "tariff", guessed: "estimated", uses: "plan uses", comfort: "comfort hours", now: "now",
        night: "night", yesterday: "yesterday", ready: "ready to steer", min: "min", steer: "Let Roost steer", sure: "Sure? Click again", importing: "Weheat import", months: "months", done_at: "done", eta: { heating: "after more heating hours", check: "maybe at the next check", following: "not yet (heat pump not following)" },
        active: "ACTIVE", shadow: "SHADOW", off: "OFF", paused: "PAUSED", scrub: "slide over the graph",
        stored: "stored", unavailable: "Not available", pick: "Pick the 'Planned setpoint' sensor of the Roost integration.",
        noplan: "no plan yet", heating: "heat pump heating", e_entity: "Sensor", e_title: "Title", e_language: "Language",
        e_time_format: "Time format", e_auto: "Like Home Assistant", e_show_tiles: "Tiles", e_show_chart: "24-hour plan",
        e_show_footer: "Saving", e_show_curve: "Heating curve advice", e_compact: "Compact (e.g. a wall tablet)", e_history: "Look back (button)", e_view: "Opens in",
        v_plan: "Overview", v_history: "Look back", v_curve: "Heating curve advice", go_integration: "Open Roost in Settings", tab_table: "Table", t_time: "Time", t_why: "Why", t_back7: "Last 7 days", t_today: "Today", t_exp: "exp.", t_set: "Setting", t_room: "Room", mo_off: "Off", mo_shadow: "Shadow", mo_active: "Active", mh_off: "Roost does nothing", mh_shadow: "Roost plans along, but steers nothing", mh_active: "Roost sets the thermostat", mo_resume: "Resume now", mo_sure: "Sure? Tap again", v_table: "Table", s_comfort: "Comfort: at least", s_day_min: "Hard floor (comfort hours)", s_night_min: "Eco: at least", s_lowest: "Lowest setpoint", s_store: "Comfort: may warm up to", mo_away: "Away", away_1: "1 day", away_3: "3 days", away_7: "1 week", mh_away: "only the minimum ({min} \u00b0C), warm again on time", mo_home: "Home again", mh_home: "the comfort hours count again", st_away: "AWAY", src_title: "Heating electricity", src_sun: "solar", src_bat: "battery", src_grid: "grid", t_loss_store: "{h} hours labelled as heat storage; highest measured room {max} \u00b0C. This does not establish which hours were unnecessary.", t_loss_other: "The model estimate is negative; its cause has not been established.", mo_pause: "Pause 2 h", mh_pause: "Roost leaves the thermostat alone for 2 hours", warn_notready: "Roost steers with the model it had: the check of the house model has not passed (yet).",
        ahead: "Overview", back: "Look back", h_cost: "Electricity cost", h_saving: "Estimated saving", h_pred: "Forecast 6 h", h_largest: "largest",
        h_below: "Below comfort", h_lowest: "lowest", h_changes: "Changes", h_byhand: "by hand", h_byroost: "Roost",
        h_log: "Log", h_report: "Report", h_loading: "Loading the last days\u2026",
        h_nodata: "No history yet: Roost keeps every hour from now on.", h_sp_t: "thermostat setpoint", h_sp_p: "planned",
        h_room: "room measured", h_pred6: "room predicted 6 h before", h_heat: "heat kWh", 
        h_expected: "expected", h_dev: "deviation", h_room_after: "room", h_set_hand: "by hand, Roost pauses {h} h",
        h_pause_ev: "paused {h} h", h_resume: "resumed", h_mode: "mode", h_learned: "learned the house again",
        h_window: "window open", h_window_end: "window closed, room back", h_win_mark: "W", h_period: "Period", h_day: "Day", h_kwh: "kWh", h_cop: "COP", h_deficit: "\u00b0C\u00b7h below",
        p_title: "The saving in parts", p_less: "Less electricity (waiting for the sun, no overheating, warmer hours)", p_sun: "of which in hours with sun", p_cheap: "Heating in cheaper hours", p_end: "Heat left at the end", r_sav: "Hourly model comparison with a weather-adjusted comfort reference", r_yday: "Yesterday", r_next: "Next 24 hours (plan)", r_hour: "Hour", r_out: "Outdoor", r_roost: "Roost", r_steady: "Comfort reference", r_diff: "Saved", r_sp: "setpoint", r_room: "room", r_cost: "cost", r_sum: "Total", r_end: "What the state at the end still costs (heat short of comfort bought back later, or heat left over)", r_total: "Saving", r_note: "Both costs are simulated with the same house model, weather and prices. The reference changes its setpoint with the weather. Main-room comfort shortfall: Roost {a}, reference {b} degree-hours. See the quality assessment above.", r_uses_note: "\u201cPlan uses\u201d is what Roost counts per kWh from the grid or the home battery in that hour: the tariff of that hour, or less where your own solar covers it (plus the preference for own energy, if set). With a home battery, solar counts as free once the battery is full enough.", r_none: "Not available yet: a day is replayed after midnight.", r_changes: "Plan changes", r_ch_sp: "Setpoint this hour", r_ch_sav: "Expected saving 24 h", r_nochg: "No changes in this period.", c_prices_published: "new prices published ({n} h)", c_prices_changed: "prices changed ({n} h)", c_forecast: "weather forecast changed", c_room: "room {r} \u00b0C, expected {e} \u00b0C", c_correction: "correction from the last hours changed", c_settings: "settings changed", c_learned: "what Roost learned of the heat pump moved", c_estimated: "estimated prices (not published yet) left out", c_new_hour: "a new hour: the 24 hours moved on", c_other: "recalculated with the latest readings" },
  nl: { title: "Roost", room: "Kamer", thermostat: "Thermostaat", next24: "Komende 24 uur",
        setpoint: "setpoint", expected: "kamer verwacht", price: "tarief", guessed: "geschat", uses: "rekent met", comfort: "comforturen", now: "nu",
        night: "nacht", yesterday: "gisteren", ready: "klaar om te sturen", min: "min", steer: "Laat Roost sturen", sure: "Zeker? Klik nogmaals", importing: "Weheat-import", months: "maanden", done_at: "klaar", eta: { heating: "na meer stookuren", check: "mogelijk bij de volgende controle", following: "nog niet (warmtepomp volgt niet)" },
        active: "ACTIEF", shadow: "MEEKIJKEN", off: "UIT", paused: "GEPAUZEERD", scrub: "schuif over de grafiek",
        stored: "opgeslagen", unavailable: "Niet beschikbaar", pick: "Kies de sensor 'Roost-opdracht' van de integratie Roost.",
        noplan: "nog geen plan", heating: "warmtepomp stookt", e_entity: "Sensor", e_title: "Titel", e_language: "Taal",
        e_time_format: "Tijdnotatie", e_auto: "Zoals Home Assistant", e_show_tiles: "Tegels", e_show_chart: "24-uursplan",
        e_show_footer: "Besparing", e_show_curve: "Stooklijnadvies", e_compact: "Compact (bijv. een wandtablet)", e_history: "Terugblik (knop)", e_view: "Opent in",
        v_plan: "Overzicht", v_history: "Terugblik", v_curve: "Stooklijnadvies", go_integration: "Roost openen in Instellingen", tab_table: "Tabel", t_time: "Tijd", t_why: "Waarom", t_back7: "Afgelopen 7 dagen", t_today: "Vandaag", t_exp: "verw.", t_set: "Setpoint", t_room: "Kamer", mo_off: "Uit", mo_shadow: "Meekijken", mo_active: "Actief", mh_off: "Roost doet niets", mh_shadow: "Roost rekent mee, maar stuurt niets", mh_active: "Roost zet de thermostaat", mo_resume: "Nu hervatten", mo_sure: "Zeker? Tik nogmaals", v_table: "Tabel", s_comfort: "Comfort: minstens", s_day_min: "Harde ondergrens (comforturen)", s_night_min: "Eco: minstens", s_lowest: "Laagste setpoint", s_store: "Comfort: mag opwarmen tot", mo_away: "Afwezig", away_1: "1 dag", away_3: "3 dagen", away_7: "1 week", mh_away: "alleen het minimum ({min} \u00b0C), op tijd weer warm", mo_home: "Weer thuis", mh_home: "de comforturen tellen weer", st_away: "AFWEZIG", src_title: "Stroom voor verwarming", src_sun: "zon", src_bat: "accu", src_grid: "net", t_loss_store: "{h} uur met een voorverwarmingslabel; hoogste gemeten kamer {max} \u00b0C. Dit bepaalt niet welke uren onnodig waren.", t_loss_other: "De modelschatting is negatief; de oorzaak is niet vastgesteld.", mo_pause: "2 uur pauze", mh_pause: "Roost laat de thermostaat 2 uur met rust", warn_notready: "Roost stuurt met het model dat het had: de controle van het huismodel is (nog) niet geslaagd.",
        ahead: "Overzicht", back: "Terugblik", h_cost: "Stroomkosten", h_saving: "Geschatte besparing", h_pred: "Voorspelling 6 u", h_largest: "grootst",
        h_below: "Onder comfort", h_lowest: "laagst", h_changes: "Wijzigingen", h_byhand: "met de hand", h_byroost: "Roost",
        h_log: "Logboek", h_report: "Rapport", h_loading: "De laatste dagen laden\u2026",
        h_nodata: "Nog geen geschiedenis: Roost bewaart vanaf nu elk uur.", h_sp_t: "setpoint thermostaat", h_sp_p: "gepland",
        h_room: "kamer gemeten", h_pred6: "kamer voorspeld 6 u eerder", h_heat: "warmte kWh", 
        h_expected: "verw.", h_dev: "afwijking", h_room_after: "kamer", h_set_hand: "met de hand, Roost pauzeert {h} u",
        h_pause_ev: "gepauzeerd {h} u", h_resume: "hervat", h_mode: "modus", h_learned: "huis opnieuw geleerd",
        h_window: "raam open", h_window_end: "raam dicht, kamer terug", h_win_mark: "R", h_period: "Periode", h_day: "Dag", h_kwh: "kWh", h_cop: "COP", h_deficit: "\u00b0C\u00b7u onder",
        p_title: "De besparing in delen", p_less: "Minder stroom (wachten op de zon, niet te warm, warmere uren)", p_sun: "waarvan in uren met zon", p_cheap: "Stoken in goedkopere uren", p_end: "Warmte over aan het eind", r_sav: "Modelvergelijking per uur met een weersafhankelijke comfortreferentie", r_yday: "Gisteren", r_next: "Komende 24 uur (plan)", r_hour: "Uur", r_out: "Buiten", r_roost: "Roost", r_steady: "Comfortreferentie", r_diff: "Bespaard", r_sp: "setpoint", r_room: "kamer", r_cost: "kosten", r_sum: "Totaal", r_end: "Wat de stand aan het eind nog kost (warmte onder comfort later terugkopen, of warmte over)", r_total: "Besparing", r_note: "Beide kosten zijn gesimuleerd met hetzelfde huismodel, weer en dezelfde prijzen. De referentie past haar setpoint aan het weer aan. Comforttekort hoofdruimte: Roost {a}, referentie {b} graaduren. Zie de kwaliteitsbeoordeling hierboven.", r_uses_note: "\u201cRekent met\u201d is wat Roost per kWh uit het net of de thuisaccu telt in dat uur: het tarief van dat uur, of minder waar eigen zon het dekt (plus de voorkeur voor eigen energie, als ingesteld). Met een thuisaccu telt zon als gratis zodra de accu vol genoeg is.", r_none: "Nog niet beschikbaar: een dag wordt na middernacht nagespeeld.", r_changes: "Planwijzigingen", r_ch_sp: "Setpoint dit uur", r_ch_sav: "Verwachte besparing 24 u", r_nochg: "Geen wijzigingen in deze periode.", c_prices_published: "nieuwe prijzen gepubliceerd ({n} u)", c_prices_changed: "prijzen gewijzigd ({n} u)", c_forecast: "weersverwachting gewijzigd", c_room: "kamer {r} \u00b0C, verwacht {e} \u00b0C", c_correction: "correctie uit de laatste uren gewijzigd", c_settings: "instellingen gewijzigd", c_learned: "wat Roost van de warmtepomp leerde schoof op", c_estimated: "geschatte prijzen (nog niet gepubliceerd) buiten beschouwing", c_new_hour: "nieuw uur: de 24 uur schuiven door", c_other: "opnieuw berekend met de laatste metingen" },
  de: { title: "Roost", room: "Raum", thermostat: "Thermostat", next24: "N\u00e4chste 24 Stunden",
        setpoint: "Sollwert", expected: "Raum erwartet", price: "Tarif", guessed: "gesch\u00e4tzt", uses: "Plan rechnet mit", comfort: "Komfortstunden", now: "jetzt",
        night: "Nacht", yesterday: "gestern", ready: "bereit zum Steuern", min: "Min", steer: "Roost steuern lassen", sure: "Sicher? Nochmal klicken", importing: "Weheat-Import", months: "Monate", done_at: "fertig", eta: { heating: "nach mehr Heizstunden", check: "vielleicht bei der n\u00e4chsten Pr\u00fcfung", following: "noch nicht (W\u00e4rmepumpe folgt nicht)" },
        active: "AKTIV", shadow: "MITLESEN", off: "AUS", paused: "PAUSIERT", scrub: "\u00fcber die Grafik streichen",
        stored: "gespeichert", unavailable: "Nicht verf\u00fcgbar", pick: "W\u00e4hle den Sensor 'Roost-Vorgabe' der Roost-Integration.",
        noplan: "noch kein Plan", heating: "W\u00e4rmepumpe heizt", e_entity: "Sensor", e_title: "Titel", e_language: "Sprache",
        e_time_format: "Zeitformat", e_auto: "Wie Home Assistant", e_show_tiles: "Kacheln", e_show_chart: "24-Stunden-Plan",
        e_show_footer: "Ersparnis", e_show_curve: "Heizkurven-Empfehlung", e_compact: "Kompakt (z. B. ein Wandtablet)", e_history: "R\u00fcckblick (Schalter)", e_view: "\u00d6ffnet in",
        v_plan: "\u00dcbersicht", v_history: "R\u00fcckblick", v_curve: "Heizkurven-Empfehlung", go_integration: "Roost in den Einstellungen \u00f6ffnen", tab_table: "Tabelle", t_time: "Zeit", t_why: "Warum", t_back7: "Letzte 7 Tage", t_today: "Heute", t_exp: "erw.", t_set: "Sollwert", t_room: "Raum", mo_off: "Aus", mo_shadow: "Mitschauen", mo_active: "Aktiv", mh_off: "Roost tut nichts", mh_shadow: "Roost plant mit, steuert aber nichts", mh_active: "Roost stellt das Thermostat", mo_resume: "Jetzt fortsetzen", mo_sure: "Sicher? Nochmals tippen", v_table: "Tabelle", s_comfort: "Komfort: mindestens", s_day_min: "Feste Untergrenze (Komfortzeiten)", s_night_min: "Eco: mindestens", s_lowest: "Niedrigster Sollwert", s_store: "Komfort: darf aufw\u00e4rmen bis", mo_away: "Abwesend", away_1: "1 Tag", away_3: "3 Tage", away_7: "1 Woche", mh_away: "nur das Minimum ({min} \u00b0C), rechtzeitig wieder warm", mo_home: "Wieder zu Hause", mh_home: "die Komfortstunden z\u00e4hlen wieder", st_away: "ABWESEND", src_title: "Heizstrom", src_sun: "Sonne", src_bat: "Akku", src_grid: "Netz", t_loss_store: "{h} Stunden als W\u00e4rmespeicherung markiert; h\u00f6chste Raumtemperatur {max} \u00b0C. Daraus folgt nicht, welche Stunden unn\u00f6tig waren.", t_loss_other: "Die Modellsch\u00e4tzung ist negativ; die Ursache ist nicht ermittelt.", mo_pause: "2 Std. Pause", mh_pause: "Roost l\u00e4sst das Thermostat 2 Stunden in Ruhe", warn_notready: "Roost steuert mit dem bisherigen Modell: die Pr\u00fcfung des Hausmodells ist (noch) nicht bestanden.",
        ahead: "\u00dcbersicht", back: "R\u00fcckblick", h_cost: "Stroomkosten", h_saving: "Gesch\u00e4tzte Ersparnis", h_pred: "Vorhersage 6 h", h_largest: "gr\u00f6\u00dfte",
        h_below: "Unter Komfort", h_lowest: "niedrigste", h_changes: "\u00c4nderungen", h_byhand: "von Hand", h_byroost: "Roost",
        h_log: "Protokoll", h_report: "Bericht", h_loading: "Die letzten Tage werden geladen\u2026",
        h_nodata: "Noch kein Verlauf: Roost speichert ab jetzt jede Stunde.", h_sp_t: "Sollwert Thermostat", h_sp_p: "geplant",
        h_room: "Raum gemessen", h_pred6: "Raum 6 h vorher vorhergesagt", h_heat: "W\u00e4rme kWh", 
        h_expected: "erw.", h_dev: "Abweichung", h_room_after: "Raum", h_set_hand: "von Hand, Roost pausiert {h} h",
        h_pause_ev: "pausiert {h} h", h_resume: "fortgesetzt", h_mode: "Modus", h_learned: "Haus neu gelernt",
        h_window: "Fenster offen", h_window_end: "Fenster zu, Raum zur\u00fcck", h_win_mark: "F", h_period: "Zeitraum", h_day: "Tag", h_kwh: "kWh", h_cop: "COP", h_deficit: "\u00b0C\u00b7h darunter",
        p_title: "Die Ersparnis in Teilen", p_less: "Weniger Strom (auf die Sonne warten, nicht \u00fcberheizen, w\u00e4rmere Stunden)", p_sun: "davon in Stunden mit Sonne", p_cheap: "Heizen in g\u00fcnstigeren Stunden", p_end: "W\u00e4rme \u00fcbrig am Ende", r_sav: "St\u00fcndlicher Modellvergleich mit einer wetterabh\u00e4ngigen Komfortreferenz", r_yday: "Gestern", r_next: "N\u00e4chste 24 Stunden (Plan)", r_hour: "Stunde", r_out: "Au\u00dfen", r_roost: "Roost", r_steady: "Komfortreferenz", r_diff: "Gespart", r_sp: "Sollwert", r_room: "Raum", r_cost: "Kosten", r_sum: "Summe", r_end: "Was der Zustand am Ende noch kostet (W\u00e4rme unter Komfort sp\u00e4ter nachkaufen, oder \u00fcbrige W\u00e4rme)", r_total: "Ersparnis", r_note: "Beide Kosten sind mit demselben Modell, Wetter und Preisen simuliert. Die Referenz passt den Sollwert dem Wetter an. Komfortdefizit im Hauptraum: Roost {a}, Referenz {b} Gradstunden. Siehe Qualit\u00e4tsbewertung oben.", r_uses_note: "\u201ePlan rechnet mit\u201c ist, was Roost pro kWh aus dem Netz oder dem Hausspeicher in dieser Stunde ansetzt: den Tarif dieser Stunde oder weniger, wo eigener Solarstrom sie deckt (plus den Vorzug f\u00fcr eigene Energie, falls eingestellt). Mit Hausspeicher gilt Solarstrom als kostenlos, sobald der Speicher voll genug ist.", r_none: "Noch nicht verf\u00fcgbar: ein Tag wird nach Mitternacht nachgespielt.", r_changes: "Plan\u00e4nderungen", r_ch_sp: "Sollwert diese Stunde", r_ch_sav: "Erwartete Ersparnis 24 h", r_nochg: "Keine \u00c4nderungen in diesem Zeitraum.", c_prices_published: "neue Preise ver\u00f6ffentlicht ({n} h)", c_prices_changed: "Preise ge\u00e4ndert ({n} h)", c_forecast: "Wettervorhersage ge\u00e4ndert", c_room: "Raum {r} \u00b0C, erwartet {e} \u00b0C", c_correction: "Korrektur aus den letzten Stunden ge\u00e4ndert", c_settings: "Einstellungen ge\u00e4ndert", c_learned: "was Roost \u00fcber die W\u00e4rmepumpe gelernt hat, hat sich verschoben", c_estimated: "gesch\u00e4tzte Preise (noch nicht ver\u00f6ffentlicht) au\u00dfer Acht gelassen", c_new_hour: "neue Stunde: die 24 Stunden r\u00fccken weiter", c_other: "neu berechnet mit den letzten Messwerten" },
  fr: { title: "Roost", room: "Pi\u00e8ce", thermostat: "Thermostat", next24: "24 prochaines heures",
        setpoint: "consigne", expected: "pi\u00e8ce pr\u00e9vue", price: "tarif", guessed: "estim\u00e9", uses: "le plan compte", comfort: "heures de confort", now: "maint.",
        night: "nuit", yesterday: "hier", ready: "pr\u00eat \u00e0 piloter", min: "min", steer: "Laisser Roost piloter", sure: "S\u00fbr ? Cliquez encore", importing: "Import Weheat", months: "mois", done_at: "fini", eta: { heating: "apr\u00e8s plus d'heures de chauffe", check: "peut-\u00eatre au prochain contr\u00f4le", following: "pas encore (la pompe ne suit pas)" },
        active: "ACTIF", shadow: "OBSERVATION", off: "ARR\u00caT", paused: "EN PAUSE", scrub: "glissez sur le graphique",
        stored: "stock\u00e9", unavailable: "Indisponible", pick: "Choisissez le capteur 'Consigne de Roost' de l'int\u00e9gration Roost.",
        noplan: "pas encore de plan", heating: "la pompe chauffe", e_entity: "Capteur", e_title: "Titre", e_language: "Langue",
        e_time_format: "Format de l'heure", e_auto: "Comme Home Assistant", e_show_tiles: "Tuiles", e_show_chart: "Plan sur 24 heures",
        e_show_footer: "\u00c9conomie", e_show_curve: "Conseil de courbe de chauffe", e_compact: "Compact (p. ex. une tablette murale)", e_history: "R\u00e9trospective (bouton)", e_view: "S'ouvre sur",
        v_plan: "Aper\u00e7u", v_history: "R\u00e9trospective", v_curve: "Conseil de courbe", go_integration: "Ouvrir Roost dans les param\u00e8tres", tab_table: "Tableau", t_time: "Heure", t_why: "Pourquoi", t_back7: "7 derniers jours", t_today: "Aujourd'hui", t_exp: "pr\u00e9vu", t_set: "Consigne", t_room: "Pi\u00e8ce", mo_off: "Arr\u00eat", mo_shadow: "Observation", mo_active: "Actif", mh_off: "Roost ne fait rien", mh_shadow: "Roost planifie sans rien piloter", mh_active: "Roost r\u00e8gle le thermostat", mo_resume: "Reprendre maintenant", mo_sure: "S\u00fbr ? Touchez encore", v_table: "Tableau", s_comfort: "Confort : au moins", s_day_min: "Plancher strict (heures de confort)", s_night_min: "\u00c9co : au moins", s_lowest: "Consigne la plus basse", s_store: "Confort : peut chauffer jusqu'\u00e0", mo_away: "Absent", away_1: "1 jour", away_3: "3 jours", away_7: "1 semaine", mh_away: "seulement le minimum ({min} \u00b0C), de nouveau chaud \u00e0 temps", mo_home: "De retour", mh_home: "les heures de confort comptent de nouveau", st_away: "ABSENT", src_title: "\u00c9lectricit\u00e9 de chauffage", src_sun: "solaire", src_bat: "batterie", src_grid: "r\u00e9seau", t_loss_store: "{h} heures marqu\u00e9es comme stockage ; maximum mesur\u00e9 {max} \u00b0C. Cela ne prouve pas quelles heures \u00e9taient inutiles.", t_loss_other: "L'estimation du mod\u00e8le est n\u00e9gative ; la cause n'est pas \u00e9tablie.", mo_pause: "Pause 2 h", mh_pause: "Roost laisse le thermostat tranquille 2 heures", warn_notready: "Roost pilote avec le mod\u00e8le qu'il avait : la v\u00e9rification du mod\u00e8le de la maison n'est pas (encore) r\u00e9ussie.",
        ahead: "Aper\u00e7u", back: "R\u00e9trospective", h_cost: "Co\u00fbt", h_saving: "\u00c9conomie estim\u00e9e", h_pred: "Pr\u00e9vision 6 h", h_largest: "max.",
        h_below: "Sous le confort", h_lowest: "minimum", h_changes: "Changements", h_byhand: "\u00e0 la main", h_byroost: "Roost",
        h_log: "Journal", h_report: "Rapport", h_loading: "Chargement des derniers jours\u2026",
        h_nodata: "Pas encore d'historique : Roost garde chaque heure \u00e0 partir de maintenant.", h_sp_t: "consigne thermostat", h_sp_p: "pr\u00e9vue",
        h_room: "pi\u00e8ce mesur\u00e9e", h_pred6: "pi\u00e8ce pr\u00e9vue 6 h avant", h_heat: "chaleur kWh", 
        h_expected: "pr\u00e9vu", h_dev: "\u00e9cart", h_room_after: "pi\u00e8ce", h_set_hand: "\u00e0 la main, Roost en pause {h} h",
        h_pause_ev: "en pause {h} h", h_resume: "reprise", h_mode: "mode", h_learned: "maison r\u00e9apprise",
        h_window: "fen\u00eatre ouverte", h_window_end: "fen\u00eatre ferm\u00e9e, pi\u00e8ce revenue", h_win_mark: "F", h_period: "P\u00e9riode", h_day: "Jour", h_kwh: "kWh", h_cop: "COP", h_deficit: "\u00b0C\u00b7h en dessous",
        p_title: "L'\u00e9conomie en parts", p_less: "Moins d'\u00e9lectricit\u00e9 (attendre le soleil, pas de surchauffe, heures plus douces)", p_sun: "dont dans les heures de soleil", p_cheap: "Chauffer aux heures moins ch\u00e8res", p_end: "Chaleur restante \u00e0 la fin", r_sav: "Comparaison horaire du mod\u00e8le avec une r\u00e9f\u00e9rence de confort selon la m\u00e9t\u00e9o", r_yday: "Hier", r_next: "Prochaines 24 heures (plan)", r_hour: "Heure", r_out: "Ext\u00e9rieur", r_roost: "Roost", r_steady: "R\u00e9f\u00e9rence de confort", r_diff: "\u00c9conomis\u00e9", r_sp: "consigne", r_room: "pi\u00e8ce", r_cost: "co\u00fbt", r_sum: "Total", r_end: "Ce que l'\u00e9tat final co\u00fbte encore (chaleur sous le confort rachet\u00e9e plus tard, ou chaleur en trop)", r_total: "\u00c9conomie", r_note: "Les deux co\u00fbts sont simul\u00e9s avec les m\u00eames mod\u00e8le, m\u00e9t\u00e9o et prix. La r\u00e9f\u00e9rence adapte sa consigne \u00e0 la m\u00e9t\u00e9o. D\u00e9ficit de confort principal : Roost {a}, r\u00e9f\u00e9rence {b} degr\u00e9s-heures. Voir la qualit\u00e9 ci-dessus.", r_uses_note: "\u00ab\u00a0Le plan compte\u00a0\u00bb est ce que Roost compte par kWh du r\u00e9seau ou de la batterie domestique dans cette heure\u00a0: le tarif de cette heure, ou moins l\u00e0 o\u00f9 votre solaire la couvre (plus la pr\u00e9f\u00e9rence pour l'\u00e9nergie propre, si r\u00e9gl\u00e9e). Avec une batterie, le solaire compte comme gratuit d\u00e8s qu'elle est assez pleine.", r_none: "Pas encore disponible : une journ\u00e9e est rejou\u00e9e apr\u00e8s minuit.", r_changes: "Changements du plan", r_ch_sp: "Consigne cette heure", r_ch_sav: "\u00c9conomie pr\u00e9vue 24 h", r_nochg: "Aucun changement sur cette p\u00e9riode.", c_prices_published: "nouveaux prix publi\u00e9s ({n} h)", c_prices_changed: "prix modifi\u00e9s ({n} h)", c_forecast: "pr\u00e9visions m\u00e9t\u00e9o modifi\u00e9es", c_room: "pi\u00e8ce {r} \u00b0C, attendu {e} \u00b0C", c_correction: "correction des derni\u00e8res heures modifi\u00e9e", c_settings: "r\u00e9glages modifi\u00e9s", c_learned: "ce que Roost a appris de la pompe \u00e0 chaleur a boug\u00e9", c_estimated: "prix estim\u00e9s (pas encore publi\u00e9s) laiss\u00e9s de c\u00f4t\u00e9", c_new_hour: "nouvelle heure : les 24 heures avancent", c_other: "recalcul\u00e9 avec les derni\u00e8res mesures" } };

for (const [lang, words] of Object.entries({"en": {"s_weekly": "Weekly schedule active", "s_weekly_edit": "Edit weekly comfort periods"}, "nl": {"s_weekly": "Weekplanning actief", "s_weekly_edit": "Comforttijden per weekdag instellen"}, "de": {"s_weekly": "Wochenplan aktiv", "s_weekly_edit": "Komfortzeiten je Wochentag bearbeiten"}, "fr": {"s_weekly": "Planning hebdomadaire actif", "s_weekly_edit": "Modifier les heures par jour"}})) Object.assign(T[lang], words);

for (const [lang, words] of Object.entries({"en": {"e_show_status": "Status line", "e_show_pumps": "Heat pump runs", "cal_hint": "Since v0.8.0 a day only counts once it is checked against the measurements; the first complete day counts after midnight.", "st_held": "Plan held since {t}", "st_next": "next change {t} \u2192 {sp}", "st_nochange": "no change in the coming hours", "st_prices": "prices until {t}", "fb_no_price": "simple plan: no price", "fb_schedule": "simple plan: comfort schedule", "pump_on": "heat pump heating", "pr_starts": "Heat pump starts today", "pr_yday": "yesterday {n}", "pr_run": "Mean run today", "pr_was": "yesterday {m}", "pr_month": "Saving this month", "pr_days": "{n} of {m} days", "pr_sun": "own solar", "w_title": "Comfort per weekday", "w_on": "Per weekday", "w_off": "Same every day", "w_add": "+ period", "w_del": "Remove", "w_copy_wd": "Copy to weekdays", "w_copy_we": "Copy to weekend", "w_copy_all": "Copy to all days", "w_save": "Save", "w_saved": "Saved", "w_err": "Not saved: {e}", "w_empty": "no comfort hours", "w_tap": "Tap a day to change its periods", "w_days": "Mo,Tu,We,Th,Fr,Sa,Su", "cal_title": "Saving per day this month", "cal_ok": "counted", "cal_bad": "not counted", "cal_none": "no data", "why_first": "first plan", "why_forced": "planned again", "why_prices": "new prices", "why_room": "room off the plan", "why_weather": "weather changed", "why_sun": "sun changed", "why_solar": "solar changed", "why_age": "plan refreshed", "why_horizon": "plan ran out", "why_window": "window closed", "why_fallback": "simple plan"}, "nl": {"e_show_status": "Statusbalk", "e_show_pumps": "Pompruns", "cal_hint": "Sinds v0.8.0 telt een dag pas als hij tegen de metingen is gecontroleerd; de eerste volledige dag telt na middernacht.", "st_held": "Vast plan sinds {t}", "st_next": "volgende wijziging {t} \u2192 {sp}", "st_nochange": "geen wijziging de komende uren", "st_prices": "prijzen tot {t}", "fb_no_price": "eenvoudig plan: geen prijs", "fb_schedule": "eenvoudig plan: comfortschema", "pump_on": "warmtepomp stookt", "pr_starts": "Pompstarts vandaag", "pr_yday": "gisteren {n}", "pr_run": "Gem. looptijd vandaag", "pr_was": "gisteren {m}", "pr_month": "Besparing deze maand", "pr_days": "{n} van {m} dagen", "pr_sun": "eigen zon", "w_title": "Comfort per weekdag", "w_on": "Per weekdag", "w_off": "Elke dag gelijk", "w_add": "+ periode", "w_del": "Verwijderen", "w_copy_wd": "Kopieer naar werkdagen", "w_copy_we": "Kopieer naar weekend", "w_copy_all": "Kopieer naar alle dagen", "w_save": "Opslaan", "w_saved": "Opgeslagen", "w_err": "Niet opgeslagen: {e}", "w_empty": "geen comforturen", "w_tap": "Tik op een dag om de perioden te wijzigen", "w_days": "ma,di,wo,do,vr,za,zo", "cal_title": "Besparing per dag deze maand", "cal_ok": "geteld", "cal_bad": "niet geteld", "cal_none": "geen gegevens", "why_first": "eerste plan", "why_forced": "opnieuw gepland", "why_prices": "nieuwe prijzen", "why_room": "kamer week af", "why_weather": "weer veranderd", "why_sun": "zon veranderd", "why_solar": "zonnestroom veranderd", "why_age": "plan ververst", "why_horizon": "plan liep af", "why_window": "raam dicht", "why_fallback": "eenvoudig plan"}, "de": {"e_show_status": "Statuszeile", "e_show_pumps": "Pumpenl\u00e4ufe", "cal_hint": "Seit v0.8.0 z\u00e4hlt ein Tag erst, wenn er mit den Messungen gepr\u00fcft ist; der erste vollst\u00e4ndige Tag z\u00e4hlt nach Mitternacht.", "st_held": "Plan fest seit {t}", "st_next": "n\u00e4chste \u00c4nderung {t} \u2192 {sp}", "st_nochange": "keine \u00c4nderung in den n\u00e4chsten Stunden", "st_prices": "Preise bis {t}", "fb_no_price": "einfacher Plan: kein Preis", "fb_schedule": "einfacher Plan: Komfortplan", "pump_on": "W\u00e4rmepumpe heizt", "pr_starts": "Pumpenstarts heute", "pr_yday": "gestern {n}", "pr_run": "Mittlere Laufzeit heute", "pr_was": "gestern {m}", "pr_month": "Ersparnis diesen Monat", "pr_days": "{n} von {m} Tagen", "pr_sun": "eigene Sonne", "w_title": "Komfort je Wochentag", "w_on": "Je Wochentag", "w_off": "Jeden Tag gleich", "w_add": "+ Zeitraum", "w_del": "Entfernen", "w_copy_wd": "Auf Werktage kopieren", "w_copy_we": "Aufs Wochenende kopieren", "w_copy_all": "Auf alle Tage kopieren", "w_save": "Speichern", "w_saved": "Gespeichert", "w_err": "Nicht gespeichert: {e}", "w_empty": "keine Komfortzeiten", "w_tap": "Tippe auf einen Tag, um seine Zeitr\u00e4ume zu \u00e4ndern", "w_days": "Mo,Di,Mi,Do,Fr,Sa,So", "cal_title": "Ersparnis je Tag diesen Monat", "cal_ok": "gez\u00e4hlt", "cal_bad": "nicht gez\u00e4hlt", "cal_none": "keine Daten", "why_first": "erster Plan", "why_forced": "neu geplant", "why_prices": "neue Preise", "why_room": "Raum wich ab", "why_weather": "Wetter ge\u00e4ndert", "why_sun": "Sonne ge\u00e4ndert", "why_solar": "Solarstrom ge\u00e4ndert", "why_age": "Plan erneuert", "why_horizon": "Plan lief aus", "why_window": "Fenster zu", "why_fallback": "einfacher Plan"}, "fr": {"e_show_status": "Ligne d'\u00e9tat", "e_show_pumps": "Cycles de la pompe", "cal_hint": "Depuis la v0.8.0 un jour ne compte qu'une fois v\u00e9rifi\u00e9 avec les mesures ; le premier jour complet compte apr\u00e8s minuit.", "st_held": "Plan fixe depuis {t}", "st_next": "prochain changement {t} \u2192 {sp}", "st_nochange": "aucun changement dans les prochaines heures", "st_prices": "prix jusqu'\u00e0 {t}", "fb_no_price": "plan simple : pas de prix", "fb_schedule": "plan simple : programme de confort", "pump_on": "la pompe \u00e0 chaleur chauffe", "pr_starts": "D\u00e9marrages aujourd'hui", "pr_yday": "hier {n}", "pr_run": "Dur\u00e9e moyenne aujourd'hui", "pr_was": "hier {m}", "pr_month": "\u00c9conomie ce mois", "pr_days": "{n} sur {m} jours", "pr_sun": "solaire", "w_title": "Confort par jour", "w_on": "Par jour", "w_off": "Chaque jour pareil", "w_add": "+ p\u00e9riode", "w_del": "Supprimer", "w_copy_wd": "Copier vers la semaine", "w_copy_we": "Copier vers le week-end", "w_copy_all": "Copier vers tous les jours", "w_save": "Enregistrer", "w_saved": "Enregistr\u00e9", "w_err": "Non enregistr\u00e9 : {e}", "w_empty": "pas d'heures de confort", "w_tap": "Touchez un jour pour modifier ses p\u00e9riodes", "w_days": "lu,ma,me,je,ve,sa,di", "cal_title": "\u00c9conomie par jour ce mois", "cal_ok": "compt\u00e9", "cal_bad": "non compt\u00e9", "cal_none": "pas de donn\u00e9es", "why_first": "premier plan", "why_forced": "replanifi\u00e9", "why_prices": "nouveaux prix", "why_room": "pi\u00e8ce \u00e9cart\u00e9e", "why_weather": "m\u00e9t\u00e9o chang\u00e9e", "why_sun": "soleil chang\u00e9", "why_solar": "solaire chang\u00e9", "why_age": "plan renouvel\u00e9", "why_horizon": "plan \u00e9puis\u00e9", "why_window": "fen\u00eatre ferm\u00e9e", "why_fallback": "plan simple"}})) Object.assign(T[lang], words);
// 25-11-2026: the comfort range in one line above the settings (at least .. may warm up to, warm at, eco outside)
for (const [lang, words] of Object.entries({
  en: { r_adv: "Last {n} days, per week", r_store: "storing heat saved {v}", r_top: "up to {t}", r_eco1: "eco {t}", r_more: "costs {v} more", r_less: "saves {v}", r_same: "makes no difference", r_colder: "a little colder", r_line: "Comfort {lo}\u2013{hi}", r_at: "warm at {t}", r_week: "per weekday", r_eco: "outside that at least {v}", r_box: "box on fallback {v}" },
  nl: { r_adv: "Afgelopen {n} dagen, per week", r_store: "opslaan bracht {v}", r_top: "tot {t}", r_eco1: "eco {t}", r_more: "kost {v} meer", r_less: "scheelt {v}", r_same: "maakt niets uit", r_colder: "iets kouder", r_line: "Comfort {lo}\u2013{hi}", r_at: "warm om {t}", r_week: "per weekdag", r_eco: "daarbuiten minstens {v}", r_box: "kastje bij terugval {v}" },
  de: { r_adv: "Letzte {n} Tage, pro Woche", r_store: "Speichern brachte {v}", r_top: "bis {t}", r_eco1: "Eco {t}", r_more: "kostet {v} mehr", r_less: "spart {v}", r_same: "macht nichts aus", r_colder: "etwas k\u00e4lter", r_line: "Komfort {lo}\u2013{hi}", r_at: "warm um {t}", r_week: "je Wochentag", r_eco: "sonst mindestens {v}", r_box: "Box im Ersatzbetrieb {v}" },
  fr: { r_adv: "{n} derniers jours, par semaine", r_store: "le stockage a rapport\u00e9 {v}", r_top: "jusqu\u2019\u00e0 {t}", r_eco1: "\u00e9co {t}", r_more: "co\u00fbte {v} de plus", r_less: "\u00e9conomise {v}", r_same: "ne change rien", r_colder: "un peu plus froid", r_line: "Confort {lo}\u2013{hi}", r_at: "chaud \u00e0 {t}", r_week: "par jour", r_eco: "sinon au moins {v}", r_box: "bo\u00eetier en secours {v}" },
})) Object.assign(T[lang], words);
// defrosting (v0.9): expected per plan hour (defrost_min), and what was seen in the last 48 h (defrost_seen)
for (const [lang, words] of Object.entries({
  en: { df_exp: "defrosting expected ~{m} min", df_leg: "one defrost expected", df_one: "about one defrost around this hour", df_seen: "Defrosted, last 48 h: {l}" },
  nl: { df_exp: "ontdooien verwacht ~{m} min", df_leg: "1\u00d7 ontdooien verwacht", df_one: "rond dit uur ongeveer 1\u00d7 ontdooien", df_seen: "Ontdooid, laatste 48 u: {l}" },
  de: { df_exp: "Abtauen erwartet ~{m} min", df_leg: "1\u00d7 Abtauen erwartet", df_one: "um diese Stunde etwa 1\u00d7 Abtauen", df_seen: "Abgetaut, letzte 48 h: {l}" },
  fr: { df_exp: "d\u00e9givrage pr\u00e9vu ~{m} min", df_leg: "1 d\u00e9givrage pr\u00e9vu", df_one: "environ 1 d\u00e9givrage vers cette heure", df_seen: "D\u00e9givr\u00e9, 48 derni\u00e8res h : {l}" },
})) Object.assign(T[lang], words);
for (const [lang, words] of Object.entries({"en": {"n_sav_unknown": "Saving not known yet", "sv_partial": "not representative yet", "sv_unsure": "not reliable enough", "store_hint": "room may rise to {max}: the floor keeps the heat for later"}, "nl": {"n_sav_unknown": "Besparing nog onbekend", "sv_partial": "nog niet representatief", "sv_unsure": "niet betrouwbaar genoeg", "store_hint": "kamer mag tot {max}: de vloer bewaart de warmte voor later"}, "de": {"n_sav_unknown": "Ersparnis noch unbekannt", "sv_partial": "noch nicht aussagekr\u00e4ftig", "sv_unsure": "nicht verl\u00e4sslich genug", "store_hint": "Raum darf bis {max}: der Boden speichert die W\u00e4rme f\u00fcr sp\u00e4ter"}, "fr": {"n_sav_unknown": "\u00c9conomie pas encore connue", "sv_partial": "pas encore repr\u00e9sentatif", "sv_unsure": "pas assez fiable", "store_hint": "la pi\u00e8ce peut monter \u00e0 {max} : le sol garde la chaleur pour plus tard"}})) Object.assign(T[lang], words);

// Why Roost plans or does something: the integration sends a code with values (reason_code/_args,
// decision_code/_args); the card words it. Unknown codes fall back to the English text of the integration.
const WHY = {
  en: { ot_bridge: "the plan heats again next hour: running on at the lowest output (a stop costs an hour of rest)", ot_below_min: "the house needs {kw} kW, below the heat pump's lowest output ({q_min} kW): heating in whole hours", ot_low_long: "running long and low ({kw} kW) while it is cheap", ot_wait_hour: "switching the heat pump on or off at the turn of the hour", ot_fallback: "the OpenTherm box heats on its fallback curve, not on Roost's plan ({state})", ot_set_failed: "could not write the flow setpoint: trying again at the next round",
        starting: "starting", window_open: "window open: Roost waits until the room is back", no_price: "no price", no_room: "no room temperature",
        no_weather: "no weather forecast and no outdoor temperature", no_plan: "no plan", off: "Roost is off",
        store_solar: "charging the floor on own solar (up to {sp} \u00b0C)",
        store_cheap: "charging the floor now ({ct} ct) before more expensive hours",
        expensive: "expensive hour ({ct} ct): living off the heat in the floor",
        store_solar_house: "storing heat in the house on own solar (up to {sp} \u00b0C)",
        store_cheap_house: "storing heat in the house now ({ct} ct) before more expensive hours",
        expensive_house: "expensive hour ({ct} ct): living off the heat in the house",
        store_ahead: "warming the floor ahead of dearer hours ({ct} ct from {at}:00)",
        store_ahead_house: "warming the house ahead of dearer hours ({ct} ct from {at}:00)",
        warm_enough: "warm enough ({room} \u00b0C): no heat needed", holding: "keeping the room at temperature",
        paused: "changed by hand: leaving the thermostat alone for {min} more min",
        already_right: "thermostat already right", wait: "next change allowed in {min} min",
        urgent: "room below the minimum: correcting now", hold_ahead: "room above the setpoint: keeping {sp} \u00b0C ahead of dearer hours ({ct} ct from {at}:00); the heat pump waits", following: "following the plan",
        airing: "window open: thermostat at its lowest until it closes", fallback_no_price: "no price: planned on one flat price", fallback_schedule: "no full plan: comfort schedule", min_run: "the heat pump just started: lowering in {min} min", set_failed: "could not set the thermostat: trying again in {min} min" },
  nl: { ot_bridge: "het plan stookt het volgende uur weer: doordraaien op het laagste vermogen (een stop kost een uur rust)", ot_below_min: "het huis vraagt {kw} kW, minder dan het laagste vermogen van de warmtepomp ({q_min} kW): stoken in hele uren", ot_low_long: "lang en laag draaien ({kw} kW) zolang het goedkoop is", ot_wait_hour: "de warmtepomp gaat aan of uit op het hele uur", ot_fallback: "het OpenTherm-kastje stookt op de stooklijn bij terugval, niet op het plan van Roost ({state})", ot_set_failed: "de aanvoertemperatuur kon niet worden geschreven: volgende ronde opnieuw",
        starting: "opstarten", window_open: "raam open: Roost wacht tot de kamer terug is", no_price: "geen prijs", no_room: "geen kamertemperatuur",
        no_weather: "geen weersverwachting en geen buitentemperatuur", no_plan: "geen plan", off: "Roost staat uit",
        store_solar: "vloer opladen met eigen zonnestroom (tot {sp} \u00b0C)",
        store_cheap: "vloer opladen ({ct} ct), straks wordt het duurder",
        expensive: "duur uur ({ct} ct): teert op de vloerbuffer",
        store_solar_house: "warmte opslaan in het huis met eigen zonnestroom (tot {sp} \u00b0C)",
        store_cheap_house: "warmte opslaan in het huis ({ct} ct), straks wordt het duurder",
        expensive_house: "duur uur ({ct} ct): teert op de warmte in het huis",
        store_ahead: "vloer alvast opwarmen voor duurdere uren ({ct} ct vanaf {at}:00)",
        store_ahead_house: "huis alvast opwarmen voor duurdere uren ({ct} ct vanaf {at}:00)",
        warm_enough: "warm genoeg ({room} \u00b0C): geen warmte nodig", holding: "kamer op temperatuur houden",
        paused: "met de hand gewijzigd: thermostaat nog {min} min met rust gelaten",
        already_right: "thermostaat staat al goed", wait: "volgende wijziging over {min} min",
        urgent: "kamer onder het minimum: nu bijsturen", hold_ahead: "kamer boven het setpoint: houdt {sp} \u00b0C aan v\u00f3\u00f3r duurdere uren ({ct} ct vanaf {at}:00); de warmtepomp wacht", following: "volgt het plan",
        airing: "raam open: thermostaat op de laagste stand tot het dicht is", fallback_no_price: "geen prijs: gepland op \u00e9\u00e9n vlakke prijs", fallback_schedule: "geen volledig plan: comfortschema", min_run: "warmtepomp is net gestart: verlagen over {min} min", set_failed: "thermostaat niet gelukt: opnieuw over {min} min" },
  de: { ot_bridge: "der Plan heizt n\u00e4chste Stunde wieder: weiter auf kleinster Leistung (ein Stopp kostet eine Stunde Pause)", ot_below_min: "das Haus braucht {kw} kW, weniger als die kleinste Leistung der W\u00e4rmepumpe ({q_min} kW): Heizen in ganzen Stunden", ot_low_long: "lang und niedrig laufen ({kw} kW), solange es g\u00fcnstig ist", ot_wait_hour: "die W\u00e4rmepumpe geht zur vollen Stunde an oder aus", ot_fallback: "die OpenTherm-Box heizt nach der Ersatzheizkurve, nicht nach Roosts Plan ({state})", ot_set_failed: "die Vorlauftemperatur konnte nicht geschrieben werden: n\u00e4chste Runde erneut",
        starting: "startet", window_open: "Fenster offen: Roost wartet, bis der Raum zur\u00fcck ist", no_price: "kein Preis", no_room: "keine Raumtemperatur",
        no_weather: "keine Wettervorhersage und keine Au\u00dfentemperatur", no_plan: "kein Plan", off: "Roost ist aus",
        store_solar: "l\u00e4dt den Boden mit eigenem Solarstrom (bis {sp} \u00b0C)",
        store_cheap: "l\u00e4dt den Boden jetzt ({ct} ct) vor teureren Stunden",
        expensive: "teure Stunde ({ct} ct): lebt von der W\u00e4rme im Boden",
        store_solar_house: "speichert W\u00e4rme im Haus mit eigenem Solarstrom (bis {sp} \u00b0C)",
        store_cheap_house: "speichert W\u00e4rme im Haus jetzt ({ct} ct) vor teureren Stunden",
        expensive_house: "teure Stunde ({ct} ct): lebt von der W\u00e4rme im Haus",
        store_ahead: "w\u00e4rmt den Boden vor teureren Stunden vor ({ct} ct ab {at}:00)",
        store_ahead_house: "w\u00e4rmt das Haus vor teureren Stunden vor ({ct} ct ab {at}:00)",
        warm_enough: "warm genug ({room} \u00b0C): keine W\u00e4rme n\u00f6tig", holding: "h\u00e4lt den Raum auf Temperatur",
        paused: "von Hand ge\u00e4ndert: l\u00e4sst das Thermostat noch {min} min in Ruhe",
        already_right: "Thermostat steht schon richtig", wait: "n\u00e4chste \u00c4nderung in {min} min erlaubt",
        urgent: "Raum unter dem Minimum: korrigiert jetzt", hold_ahead: "Raum \u00fcber dem Sollwert: h\u00e4lt {sp} \u00b0C vor teureren Stunden ({ct} ct ab {at}:00); die W\u00e4rmepumpe wartet", following: "folgt dem Plan",
        airing: "Fenster offen: Thermostat auf niedrigster Stufe bis es zu ist", fallback_no_price: "kein Preis: mit einem festen Preis geplant", fallback_schedule: "kein vollst\u00e4ndiger Plan: Komfortplan", min_run: "W\u00e4rmepumpe gerade gestartet: senken in {min} min", set_failed: "Thermostat nicht gesetzt: neuer Versuch in {min} min" },
  fr: { ot_bridge: "le plan chauffe de nouveau l\u2019heure suivante : on continue \u00e0 la puissance minimale (un arr\u00eat co\u00fbte une heure de repos)", ot_below_min: "la maison demande {kw} kW, moins que la puissance minimale de la pompe ({q_min} kW) : chauffe par heures enti\u00e8res", ot_low_long: "marche longue et basse ({kw} kW) tant que c'est bon march\u00e9", ot_wait_hour: "la pompe s'allume ou s'\u00e9teint \u00e0 l'heure pile", ot_fallback: "le bo\u00eetier OpenTherm chauffe sur la courbe de secours, pas sur le plan de Roost ({state})", ot_set_failed: "la temp\u00e9rature de d\u00e9part n'a pas pu \u00eatre \u00e9crite : nouvel essai au prochain tour",
        starting: "d\u00e9marrage", window_open: "fen\u00eatre ouverte : Roost attend que la pi\u00e8ce revienne", no_price: "pas de prix", no_room: "pas de temp\u00e9rature de pi\u00e8ce",
        no_weather: "pas de pr\u00e9visions m\u00e9t\u00e9o ni de temp\u00e9rature ext\u00e9rieure", no_plan: "pas de plan", off: "Roost est arr\u00eat\u00e9",
        store_solar: "charge le sol avec le solaire (jusqu'\u00e0 {sp} \u00b0C)",
        store_cheap: "charge le sol maintenant ({ct} ct) avant des heures plus ch\u00e8res",
        expensive: "heure ch\u00e8re ({ct} ct) : vit de la chaleur du sol",
        store_solar_house: "stocke de la chaleur dans la maison avec le solaire (jusqu'\u00e0 {sp} \u00b0C)",
        store_cheap_house: "stocke de la chaleur dans la maison maintenant ({ct} ct) avant des heures plus ch\u00e8res",
        expensive_house: "heure ch\u00e8re ({ct} ct) : vit de la chaleur de la maison",
        store_ahead: "pr\u00e9chauffe le sol avant des heures plus ch\u00e8res ({ct} ct d\u00e8s {at} h)",
        store_ahead_house: "pr\u00e9chauffe la maison avant des heures plus ch\u00e8res ({ct} ct d\u00e8s {at} h)",
        warm_enough: "assez chaud ({room} \u00b0C) : pas besoin de chaleur", holding: "maintient la pi\u00e8ce \u00e0 temp\u00e9rature",
        paused: "chang\u00e9 \u00e0 la main : laisse le thermostat encore {min} min",
        already_right: "thermostat d\u00e9j\u00e0 bien r\u00e9gl\u00e9", wait: "prochain changement possible dans {min} min",
        urgent: "pi\u00e8ce sous le minimum : correction maintenant", hold_ahead: "pi\u00e8ce au-dessus de la consigne : garde {sp} \u00b0C avant des heures plus ch\u00e8res ({ct} ct d\u00e8s {at}:00) ; la pompe \u00e0 chaleur attend", following: "suit le plan",
        airing: "fen\u00eatre ouverte : thermostat au plus bas jusqu'\u00e0 fermeture", fallback_no_price: "pas de prix : planifi\u00e9 sur un prix fixe", fallback_schedule: "pas de plan complet : programme de confort", min_run: "la pompe \u00e0 chaleur vient de d\u00e9marrer : baisse dans {min} min", set_failed: "thermostat non r\u00e9gl\u00e9 : nouvel essai dans {min} min" },
};
const WHY_DECIMALS = { sp: 1, room: 1, ct: 0, min: 0, at: 0, kw: 1, q_min: 1 };
// The heating curve advice (sensor heating_curve): a folded table under the plan.
const CURVE_T = {
  en: { none_needed: "none", n_none: "None: at this outdoor temperature your house needs no heat.", wi_label: "Indoor temperature", wi_note: "what if: changes neither Roost nor the thermostat", lg_cloud_ot: "Measured under OpenTherm: each dot is an hour the heat pump ran the whole hour", lg_cloud_curve: "Measured on its heating curve: each dot is an hour the heat pump ran the whole hour", lg_cloud: "Measured: each dot is an hour the heat pump ran the whole hour", lg_dash: "Dashed: calculated (colder than measured) or in the cycling zone", need: "Needed", meas_ot: "Measured (OT)", meas_curve: "Measured (curve)", n_need: "Needed: the least your house asks for at that outdoor temperature, without margin.", n_meas_ot: "Measured (OT): the flow by the heat pump's own sensor, in hours it ran the whole hour while the OpenTherm thermostat set the water temperature.", n_meas_curve: "Measured (curve): the flow by the heat pump's own sensor, in hours it ran the whole hour on its own heating curve.", title: "Heating curve advice", out: "Outdoor", now: "Now", adv: "Advice", meas: "Measured", cz: "cycling zone", at0: "At 0 \u00b0C outside", loss: "Heat loss", cyc: "Cycles above", flow: "flow temperature", outside: "outdoor", x_axis: "outdoor temperature", y_axis: "flow \u00b0C", lg_adv: "Advice: the heating curve to set in the Weheat app", lg_need: "Needed: the least your house asks for (without margin)", lg_cyc: "Cycling zone: here the heat pump switches on and off anyway", n_for: "For {room} \u00b0C indoors, from {days} heating days and {hours} hours of steady heating.", n_rough: "Still rough: little data yet.", n_cycles: "Above about {t} \u00b0C outside the heat pump switches on and off anyway; the points there (grey) matter little.", n_extra: "{x} \u00b0C is calculated: colder than any day measured (coldest {min} \u00b0C).", n_meas: "Measured: the flow temperature in hours the heat pump ran the whole hour, near that outdoor temperature.", n_thermostat: "Your heat pump follows the thermostat now; the advice applies when it runs on its heating curve.", n_oncurve: "Your heat pump runs on its heating curve.", n_set: "Set the points in the Weheat app (heating curve).", none: "No advice yet: Roost needs about 20 heating days and 30 hours of steady heating with the flow temperature from the Weheat logs." },
  nl: { none_needed: "geen", n_none: "Geen: bij deze buitentemperatuur vraagt je huis geen warmte.", wi_label: "Binnentemperatuur", wi_note: "wat als: verandert Roost en de thermostaat niet", lg_cloud_ot: "Gemeten onder OpenTherm: elke stip is een uur waarin de warmtepomp het hele uur draaide", lg_cloud_curve: "Gemeten op de stooklijn: elke stip is een uur waarin de warmtepomp het hele uur draaide", lg_cloud: "Gemeten: elke stip is een uur waarin de warmtepomp het hele uur draaide", lg_dash: "Gestippeld: doorgerekend (kouder dan gemeten) of in de pendelzone", need: "Nodig", meas_ot: "Gemeten (OT)", meas_curve: "Gemeten (stooklijn)", n_need: "Nodig: wat je huis minimaal vraagt bij die buitentemperatuur, zonder marge.", n_meas_ot: "Gemeten (OT): de aanvoer volgens de sensor van de warmtepomp zelf, in uren dat hij het hele uur draaide terwijl de OpenTherm-thermostaat de watertemperatuur bepaalde.", n_meas_curve: "Gemeten (stooklijn): de aanvoer volgens de sensor van de warmtepomp zelf, in uren dat hij het hele uur op zijn eigen stooklijn draaide.", title: "Stooklijnadvies", out: "Buiten", now: "Nu", adv: "Advies", meas: "Gemeten", cz: "pendelzone", at0: "Bij 0 \u00b0C buiten", loss: "Warmteverlies", cyc: "Pendelt boven", flow: "aanvoertemperatuur", outside: "buiten", x_axis: "buitentemperatuur", y_axis: "aanvoer \u00b0C", lg_adv: "Advies: de stooklijn om in te stellen in de Weheat-app", lg_need: "Nodig: wat je huis minimaal vraagt (zonder marge)", lg_cyc: "Pendelzone: hier slaat de warmtepomp toch af en aan", n_for: "Voor {room} \u00b0C binnen, uit {days} stookdagen en {hours} uur rustig stoken.", n_rough: "Nog grof: nog weinig data.", n_cycles: "Boven ongeveer {t} \u00b0C buiten slaat de warmtepomp toch af en aan; de punten daar (grijs) maken weinig uit.", n_extra: "{x} \u00b0C is doorgerekend: kouder dan elke gemeten dag (koudste {min} \u00b0C).", n_meas: "Gemeten: de aanvoertemperatuur in uren dat de warmtepomp het hele uur draaide, rond die buitentemperatuur.", n_thermostat: "Je warmtepomp volgt nu de thermostaat; het advies geldt zodra hij op zijn stooklijn draait.", n_oncurve: "Je warmtepomp draait op zijn stooklijn.", n_set: "Stel de punten in in de Weheat-app (stooklijn).", none: "Nog geen advies: Roost heeft ongeveer 20 stookdagen en 30 uur rustig stoken nodig, met de aanvoertemperatuur uit de Weheat-logs." },
  de: { none_needed: "keine", n_none: "Keine: bei dieser Au\u00dfentemperatur braucht dein Haus keine W\u00e4rme.", wi_label: "Innentemperatur", wi_note: "Was w\u00e4re wenn: \u00e4ndert weder Roost noch das Thermostat", lg_cloud_ot: "Gemessen unter OpenTherm: jeder Punkt ist eine Stunde, in der die W\u00e4rmepumpe durchlief", lg_cloud_curve: "Gemessen nach der Heizkurve: jeder Punkt ist eine Stunde, in der die W\u00e4rmepumpe durchlief", lg_cloud: "Gemessen: jeder Punkt ist eine Stunde, in der die W\u00e4rmepumpe durchlief", lg_dash: "Gestrichelt: berechnet (k\u00e4lter als gemessen) oder in der Taktzone", need: "N\u00f6tig", meas_ot: "Gemessen (OT)", meas_curve: "Gemessen (Kurve)", n_need: "N\u00f6tig: was dein Haus bei dieser Au\u00dfentemperatur mindestens braucht, ohne Reserve.", n_meas_ot: "Gemessen (OT): der Vorlauf laut dem eigenen F\u00fchler der W\u00e4rmepumpe, in Stunden, in denen sie die ganze Stunde lief, w\u00e4hrend das OpenTherm-Thermostat die Wassertemperatur vorgab.", n_meas_curve: "Gemessen (Kurve): der Vorlauf laut dem eigenen F\u00fchler der W\u00e4rmepumpe, in Stunden, in denen sie die ganze Stunde nach ihrer Heizkurve lief.", title: "Heizkurven-Empfehlung", out: "Au\u00dfen", now: "Jetzt", adv: "Empfehlung", meas: "Gemessen", cz: "Taktzone", at0: "Bei 0 \u00b0C au\u00dfen", loss: "W\u00e4rmeverlust", cyc: "Taktet \u00fcber", flow: "Vorlauftemperatur", outside: "au\u00dfen", x_axis: "Au\u00dfentemperatur", y_axis: "Vorlauf \u00b0C", lg_adv: "Empfehlung: die Heizkurve f\u00fcr die Weheat-App", lg_need: "N\u00f6tig: was dein Haus mindestens braucht (ohne Reserve)", lg_cyc: "Taktzone: hier taktet die W\u00e4rmepumpe ohnehin", n_for: "F\u00fcr {room} \u00b0C innen, aus {days} Heiztagen und {hours} Stunden ruhigem Heizen.", n_rough: "Noch grob: noch wenige Daten.", n_cycles: "Oberhalb von etwa {t} \u00b0C au\u00dfen taktet die W\u00e4rmepumpe ohnehin; die Punkte dort (grau) sind kaum wichtig.", n_extra: "{x} \u00b0C ist berechnet: k\u00e4lter als jeder gemessene Tag (k\u00e4ltester {min} \u00b0C).", n_meas: "Gemessen: die Vorlauftemperatur in Stunden, in denen die W\u00e4rmepumpe die ganze Stunde lief, bei dieser Au\u00dfentemperatur.", n_thermostat: "Deine W\u00e4rmepumpe folgt jetzt dem Thermostat; die Empfehlung gilt, sobald sie nach ihrer Heizkurve l\u00e4uft.", n_oncurve: "Deine W\u00e4rmepumpe l\u00e4uft nach ihrer Heizkurve.", n_set: "Stelle die Punkte in der Weheat-App ein (Heizkurve).", none: "Noch keine Empfehlung: Roost braucht etwa 20 Heiztage und 30 Stunden ruhiges Heizen mit der Vorlauftemperatur aus den Weheat-Logs." },
  fr: { none_needed: "aucune", n_none: "Aucune : \u00e0 cette temp\u00e9rature ext\u00e9rieure, votre maison n'a pas besoin de chaleur.", wi_label: "Temp\u00e9rature int\u00e9rieure", wi_note: "et si : ne change ni Roost ni le thermostat", lg_cloud_ot: "Mesur\u00e9 sous OpenTherm : chaque point est une heure o\u00f9 la pompe a tourn\u00e9 toute l'heure", lg_cloud_curve: "Mesur\u00e9 sur sa courbe : chaque point est une heure o\u00f9 la pompe a tourn\u00e9 toute l'heure", lg_cloud: "Mesur\u00e9 : chaque point est une heure o\u00f9 la pompe a tourn\u00e9 toute l'heure", lg_dash: "Pointill\u00e9 : calcul\u00e9 (plus froid que mesur\u00e9) ou dans la zone de cycles", need: "N\u00e9cessaire", meas_ot: "Mesur\u00e9 (OT)", meas_curve: "Mesur\u00e9 (courbe)", n_need: "N\u00e9cessaire : le minimum que demande la maison \u00e0 cette temp\u00e9rature ext\u00e9rieure, sans marge.", n_meas_ot: "Mesur\u00e9 (OT) : le d\u00e9part selon la sonde de la pompe elle-m\u00eame, pendant les heures o\u00f9 elle a tourn\u00e9 toute l'heure pendant que le thermostat OpenTherm fixait la temp\u00e9rature de l'eau.", n_meas_curve: "Mesur\u00e9 (courbe) : le d\u00e9part selon la sonde de la pompe elle-m\u00eame, pendant les heures o\u00f9 elle a tourn\u00e9 toute l'heure sur sa propre courbe de chauffe.", title: "Conseil de courbe de chauffe", out: "Ext\u00e9rieur", now: "Actuel", adv: "Conseil", meas: "Mesur\u00e9", cz: "zone de cycles", at0: "\u00c0 0 \u00b0C dehors", loss: "D\u00e9perditions", cyc: "Cycle au-dessus de", flow: "temp\u00e9rature de d\u00e9part", outside: "ext\u00e9rieur", x_axis: "temp\u00e9rature ext\u00e9rieure", y_axis: "d\u00e9part \u00b0C", lg_adv: "Conseil : la courbe \u00e0 r\u00e9gler dans l'app Weheat", lg_need: "N\u00e9cessaire : le minimum que demande la maison (sans marge)", lg_cyc: "Zone de cycles : ici la pompe s'allume et s'\u00e9teint de toute fa\u00e7on", n_for: "Pour {room} \u00b0C \u00e0 l'int\u00e9rieur, d'apr\u00e8s {days} jours de chauffe et {hours} heures de chauffe stable.", n_rough: "Encore approximatif : peu de donn\u00e9es.", n_cycles: "Au-dessus d'environ {t} \u00b0C dehors la pompe s'allume et s'\u00e9teint de toute fa\u00e7on ; les points y (en gris) comptent peu.", n_extra: "{x} \u00b0C est calcul\u00e9 : plus froid que tout jour mesur\u00e9 (le plus froid {min} \u00b0C).", n_meas: "Mesur\u00e9 : la temp\u00e9rature de d\u00e9part pendant les heures o\u00f9 la pompe a tourn\u00e9 toute l'heure, autour de cette temp\u00e9rature ext\u00e9rieure.", n_thermostat: "Votre pompe \u00e0 chaleur suit le thermostat ; le conseil vaut quand elle fonctionne sur sa courbe de chauffe.", n_oncurve: "Votre pompe \u00e0 chaleur fonctionne sur sa courbe de chauffe.", n_set: "R\u00e9glez les points dans l'app Weheat (courbe de chauffe).", none: "Pas encore de conseil : Roost a besoin d'environ 20 jours de chauffe et 30 heures de chauffe stable avec la temp\u00e9rature de d\u00e9part des logs Weheat." } };

// Parts of the card that can be hidden with show_<part>: false. "compact: true" hides the chart and the saving and
// keeps the header and the tiles; a show_<part> set explicitly always wins (e.g. compact with show_chart: true).
const PARTS = ["status", "tiles", "chart", "pumps", "curve", "footer"];
const COMPACT_HIDES = ["chart", "pumps", "curve", "footer"];
const showDefault = (config, part) => !(config && config.compact && COMPACT_HIDES.indexOf(part) >= 0);
const shows = (config, part) => {
  const v = config ? config["show_" + part] : undefined;
  return v === undefined || v === null ? showDefault(config, part) : !!v;
};
const lang2 = (hass) => ((hass && ((hass.locale && hass.locale.language) || hass.language)) || "en").slice(0, 2);
const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const fmt = (v, d) => (v === null || v === undefined || isNaN(v)) ? "\u2014" : Number(v).toFixed(d === undefined ? 0 : d);

const SAVING_QUALITY = {
  "en": {
    "partial_hours": "Home Assistant was restarted during an hour, so part of that hour was not measured.",
    "checked": "Model estimate checked against measured heating electricity and room temperatures; not a measured bill saving.",
    "forecast": "Expected model estimate; not a measured saving.",
    "unreliable": "No accepted saving estimate.",
    "extra_rooms": "The reference does not yet account for the extra rooms.",
    "comfort_mismatch": "The reference and Roost do not meet the same comfort.",
    "missing_context": "The original daily model and settings are missing.",
    "incomplete_day": "This local day is incomplete.",
    "incomplete_forecast": "A complete 24-hour plan is not available yet.",
    "missing_measurements": "Too few complete measurements.",
    "energy_mismatch": "Modelled heating electricity differs too much from the meter.",
    "temperature_mismatch": "The replayed room temperature differs too much from measurements.",
    "settings_changed": "Comfort settings changed during this day."
  },
  "nl": {
    "partial_hours": "Home Assistant is tijdens een uur herstart, waardoor een deel van dat uur niet is gemeten.",
    "checked": "Modelraming getoetst aan gemeten verwarmingsstroom en kamertemperaturen; geen gemeten besparing op de rekening.",
    "forecast": "Verwachte modelraming; geen gemeten besparing.",
    "unreliable": "Geen voldoende betrouwbare besparingsschatting.",
    "extra_rooms": "De referentie houdt nog geen rekening met de extra kamers.",
    "comfort_mismatch": "De referentie en Roost leveren niet hetzelfde comfort.",
    "missing_context": "Het oorspronkelijke dagmodel en de instellingen ontbreken.",
    "incomplete_day": "Deze lokale dag is onvolledig.",
    "incomplete_forecast": "Er is nog geen volledige planning voor 24 uur.",
    "missing_measurements": "Er zijn te weinig volledige metingen.",
    "energy_mismatch": "Het gesimuleerde verwarmingsverbruik wijkt te veel af van de meter.",
    "temperature_mismatch": "De gesimuleerde kamertemperatuur wijkt te veel af van de metingen.",
    "settings_changed": "De comfortinstellingen zijn tijdens deze dag veranderd."
  },
  "de": {
    "partial_hours": "Home Assistant wurde w\u00e4hrend einer Stunde neu gestartet; ein Teil dieser Stunde wurde nicht gemessen.",
    "incomplete_forecast": "Ein vollst\u00e4ndiger 24-Stunden-Plan ist noch nicht verf\u00fcgbar.",
    "checked": "Modellsch\u00e4tzung mit gemessenem Heizstrom und Raumtemperaturen gepr\u00fcft; keine gemessene Rechnungsersparnis.",
    "forecast": "Erwartete Modellsch\u00e4tzung; keine gemessene Ersparnis.",
    "unreliable": "Keine ausreichend zuverl\u00e4ssige Sparsch\u00e4tzung.",
    "extra_rooms": "Die Referenz ber\u00fccksichtigt die zus\u00e4tzlichen R\u00e4ume noch nicht.",
    "comfort_mismatch": "Die Referenz und Roost bieten nicht denselben Komfort.",
    "missing_context": "Das urspr\u00fcngliche Tagesmodell und die Einstellungen fehlen.",
    "incomplete_day": "Dieser lokale Tag ist unvollst\u00e4ndig.",
    "missing_measurements": "Zu wenige vollst\u00e4ndige Messungen.",
    "energy_mismatch": "Der simulierte Heizstrom weicht zu stark vom Z\u00e4hler ab.",
    "temperature_mismatch": "Die simulierte Raumtemperatur weicht zu stark von Messungen ab.",
    "settings_changed": "Die Komforteinstellungen wurden im Tagesverlauf ge\u00e4ndert."
  },
  "fr": {
    "partial_hours": "Home Assistant a red\u00e9marr\u00e9 pendant une heure ; une partie de cette heure n'a pas \u00e9t\u00e9 mesur\u00e9e.",
    "incomplete_forecast": "Le plan complet sur 24 heures n'est pas encore disponible.",
    "checked": "Estimation v\u00e9rifi\u00e9e avec la consommation de chauffage et les temp\u00e9ratures mesur\u00e9es ; pas une \u00e9conomie mesur\u00e9e sur la facture.",
    "forecast": "Estimation pr\u00e9vue par le mod\u00e8le ; pas une \u00e9conomie mesur\u00e9e.",
    "unreliable": "Pas d'estimation suffisamment fiable.",
    "extra_rooms": "La r\u00e9f\u00e9rence ne tient pas encore compte des pi\u00e8ces suppl\u00e9mentaires.",
    "comfort_mismatch": "La r\u00e9f\u00e9rence et Roost n'offrent pas le m\u00eame confort.",
    "missing_context": "Le mod\u00e8le initial du jour et ses r\u00e9glages manquent.",
    "incomplete_day": "Cette journ\u00e9e locale est incompl\u00e8te.",
    "missing_measurements": "Trop peu de mesures compl\u00e8tes.",
    "energy_mismatch": "La consommation simul\u00e9e diff\u00e8re trop du compteur.",
    "temperature_mismatch": "La temp\u00e9rature simul\u00e9e diff\u00e8re trop des mesures.",
    "settings_changed": "Les r\u00e9glages de confort ont chang\u00e9 pendant cette journ\u00e9e."
  }
};

// The saving in parts: measured (meters and tariffs, no model) and worked out (with the house model)
const SV_T = {
  en: { parts: "This month, in parts", timing: "Heating in cheaper hours (measured)", timing_sub: "{p} ct per kWh paid, {f} ct when spread evenly",
        sun: "Own solar used (measured)", sun_sub: "worth more used than exported", sun_net: "with net metering worth the same as from the grid",
        battery: "From the home battery (measured)", bat_sub: "counted at what refilling it costs",
        model: "Less electricity (worked out)", model_shadow: "Would have saved (worked out, shadow mode)",
        model_sub: "the model against a steady thermostat at equal comfort; \u00b1 how far its energy was off this week",
        no_meas: "No measured days yet this month.",
        how: "Measured parts come from the meters and your tariff, without a model. The worked-out part cannot be measured: a day's heating varies too much with the weather and the house." },
  nl: { parts: "Deze maand, in delen", timing: "Stoken in goedkopere uren (gemeten)", timing_sub: "{p} ct per kWh betaald, {f} ct bij gelijkmatig stoken",
        sun: "Eigen zon gebruikt (gemeten)", sun_sub: "meer waard gebruikt dan teruggeleverd", sun_net: "met saldering evenveel waard als netstroom",
        battery: "Uit de thuisaccu (gemeten)", bat_sub: "gerekend tegen wat bijladen kost",
        model: "Minder stroom (berekend)", model_shadow: "Zou besparen (berekend, meekijken)",
        model_sub: "het model tegen een vaste thermostaat bij gelijk comfort; \u00b1 hoeveel zijn energie deze week afweek",
        no_meas: "Nog geen gemeten dagen deze maand.",
        how: "Gemeten delen komen uit de meters en je tarief, zonder model. Het berekende deel is niet te meten: de stookstroom per dag wisselt te veel met weer en huis." },
  de: { parts: "Dieser Monat, in Teilen", timing: "Heizen in g\u00fcnstigeren Stunden (gemessen)", timing_sub: "{p} ct pro kWh bezahlt, {f} ct bei gleichm\u00e4\u00dfigem Heizen",
        sun: "Eigener Solarstrom genutzt (gemessen)", sun_sub: "genutzt mehr wert als eingespeist", sun_net: "mit Saldierung so viel wert wie Netzstrom",
        battery: "Aus dem Hausspeicher (gemessen)", bat_sub: "zum Preis des Nachladens gerechnet",
        model: "Weniger Strom (berechnet)", model_shadow: "W\u00fcrde sparen (berechnet, Mitschauen)",
        model_sub: "das Modell gegen ein festes Thermostat bei gleichem Komfort; \u00b1 wie weit seine Energie diese Woche abwich",
        no_meas: "Diesen Monat noch keine gemessenen Tage.",
        how: "Gemessene Teile stammen aus den Z\u00e4hlern und Ihrem Tarif, ohne Modell. Der berechnete Teil ist nicht messbar: der Heizstrom pro Tag schwankt zu stark mit Wetter und Haus." },
  fr: { parts: "Ce mois, en parties", timing: "Chauffer aux heures moins ch\u00e8res (mesur\u00e9)", timing_sub: "{p} ct par kWh pay\u00e9, {f} ct en chauffant uniform\u00e9ment",
        sun: "Solaire propre utilis\u00e9 (mesur\u00e9)", sun_sub: "vaut plus utilis\u00e9 qu'inject\u00e9", sun_net: "avec la compensation, vaut autant que le r\u00e9seau",
        battery: "Depuis la batterie (mesur\u00e9)", bat_sub: "compt\u00e9 au co\u00fbt de la recharge",
        model: "Moins d'\u00e9lectricit\u00e9 (calcul\u00e9)", model_shadow: "\u00c9conomiserait (calcul\u00e9, observation)",
        model_sub: "le mod\u00e8le contre un thermostat fixe \u00e0 confort \u00e9gal ; \u00b1 l'\u00e9cart de son \u00e9nergie cette semaine",
        no_meas: "Pas encore de jour mesur\u00e9 ce mois.",
        how: "Les parties mesur\u00e9es viennent des compteurs et de votre tarif, sans mod\u00e8le. La partie calcul\u00e9e ne se mesure pas : le chauffage d'un jour varie trop avec la m\u00e9t\u00e9o et la maison." }
};

// OpenTherm steering: the plan is a flow temperature (0 = off) on its own scale, not a room setpoint
// The Energy tab (websocket roost/energy, energy_table.py)
const EN_T = {
  en: { tab: "Energy", hour: "Hour", day: "Day", week: "Week", month: "Month", per: "Period", out: "Outdoor", kwh: "kWh", cop: "COP", idx: "Performance", cost: "Cost", flow: "Flow", heat: "Heat", dfr: "Defrost", run: "Heating hours", sun: "Own sun", room: "Room", total: "Total", csv: "CSV", none: "No data from the heat pump's meters yet.", loading: "Loading\u2026", catch: "* the Weheat cloud caught up on missed hours here: left out of the index", idx_help: "Performance: the heating COP as a share of what Roost learned this heat pump does at the same outdoor temperature and output. 100% = as expected; clearly lower for weeks points at the unit (evaporator, pump setting), not the weather. \u2248 = defrosts estimated from the defrost meter (Home Assistant keeps the unit's states for some days only).", st_heating: "heating", st_dhw: "hot water", st_defrost: "defrosting", st_idle: "idle", heat_sp: "space heating", heat_dhw: "hot water", heat_def: "lost to defrosting", el_heat: "heating", el_dhw: "hot water", el_ind: "indoor unit", el_rest: "standby", cop_heat: "heating", cop_dhw: "hot water", cop_all: "with the indoor unit", dd: "Degree days", per_dd: "kWh per degree day", vs: "vs the period before", lowest: "lowest", hours_run: "{h} hours with heating", wk: "wk", status: "Status", elec: "Electricity", hu: "h", of_exp: "of what Roost expects of this heat pump", dfr_n: "{n} times", dfr_heat: "{q} kWh of heat", cop_pump: "heat pump (as Weheat counts it)", scope: "Everything the heat pump uses: heating, hot water, indoor unit and standby.", tot: "total", cost_tot: "Total cost", elec_tot: "Total electricity", bat: "battery", heat_only: "Heating electricity", c_heat: "heating", c_dhw: "hot water", c_ind: "indoor unit", c_rest: "standby", sun_note: "own sun counts at the export price", cost_today: "Heating + indoor unit" },
  nl: { tab: "Energie", hour: "Uur", day: "Dag", week: "Week", month: "Maand", per: "Periode", out: "Buiten", kwh: "kWh", cop: "COP", idx: "Prestatie", cost: "Kosten", flow: "Aanvoer", heat: "Warmte", dfr: "Ontdooien", run: "Stookuren", sun: "Eigen zon", room: "Kamer", total: "Totaal", csv: "CSV", none: "Nog geen gegevens van de meters van de warmtepomp.", loading: "Laden\u2026", catch: "* hier haalde de Weheat-cloud gemiste uren in: niet meegeteld in de index", idx_help: "Prestatie: de COP bij verwarmen als deel van wat Roost heeft geleerd dat deze warmtepomp haalt bij dezelfde buitentemperatuur en hetzelfde vermogen. 100% = zoals verwacht; weken duidelijk lager wijst op de pomp (verdamper, pompstand), niet op het weer. \u2248 = aantal keer ontdooien geschat uit de ontdooimeter (Home Assistant bewaart de status van de pomp maar een paar dagen).", st_heating: "stoken", st_dhw: "warm water", st_defrost: "ontdooien", st_idle: "rust", heat_sp: "verwarming", heat_dhw: "warm water", heat_def: "kwijt aan ontdooien", el_heat: "verwarming", el_dhw: "warm water", el_ind: "binnenunit", el_rest: "standby", cop_heat: "verwarming", cop_dhw: "warm water", cop_all: "met de binnenunit", dd: "Graaddagen", per_dd: "kWh per graaddag", vs: "t.o.v. de periode ervoor", lowest: "laagst", hours_run: "{h} uur met stoken", wk: "wk", status: "Status", elec: "Stroom", hu: "u", of_exp: "van wat Roost van deze warmtepomp verwacht", dfr_n: "{n} keer", dfr_heat: "{q} kWh warmte", cop_pump: "warmtepomp (zoals Weheat telt)", scope: "Alles wat de warmtepomp gebruikt: verwarming, warm water, binnenunit en standby.", tot: "totaal", cost_tot: "Kosten totaal", elec_tot: "Stroom totaal", bat: "accu", heat_only: "Stroom verwarming", c_heat: "verwarming", c_dhw: "warm water", c_ind: "binnenunit", c_rest: "standby", sun_note: "eigen zon telt tegen de terugleverprijs", cost_today: "Verwarming + binnenunit" },
  de: { tab: "Energie", hour: "Stunde", day: "Tag", week: "Woche", month: "Monat", per: "Zeitraum", out: "Au\u00dfen", kwh: "kWh", cop: "COP", idx: "Leistung", cost: "Kosten", flow: "Vorlauf", heat: "W\u00e4rme", dfr: "Abtauen", run: "Heizstunden", sun: "Eigene Sonne", room: "Raum", total: "Gesamt", csv: "CSV", none: "Noch keine Daten von den Z\u00e4hlern der W\u00e4rmepumpe.", loading: "Laden\u2026", catch: "* hier hat die Weheat-Cloud verpasste Stunden nachgeholt: nicht im Index", idx_help: "Leistung: der Heiz-COP als Anteil dessen, was Roost f\u00fcr diese W\u00e4rmepumpe bei gleicher Au\u00dfentemperatur und Leistung gelernt hat. 100% = wie erwartet; wochenlang deutlich niedriger deutet auf das Ger\u00e4t (Verdampfer, Pumpenstufe), nicht auf das Wetter. \u2248 = Abtauvorg\u00e4nge aus dem Abtauz\u00e4hler gesch\u00e4tzt (Home Assistant beh\u00e4lt die Zust\u00e4nde nur einige Tage).", st_heating: "heizt", st_dhw: "Warmwasser", st_defrost: "taut ab", st_idle: "Ruhe", heat_sp: "Heizung", heat_dhw: "Warmwasser", heat_def: "durch Abtauen verloren", el_heat: "Heizung", el_dhw: "Warmwasser", el_ind: "Inneneinheit", el_rest: "Standby", cop_heat: "Heizung", cop_dhw: "Warmwasser", cop_all: "mit der Inneneinheit", dd: "Gradtage", per_dd: "kWh pro Gradtag", vs: "gegen\u00fcber dem Zeitraum davor", lowest: "niedrigste", hours_run: "{h} Stunden mit Heizen", wk: "KW", status: "Status", elec: "Strom", hu: "h", of_exp: "dessen, was Roost von dieser W\u00e4rmepumpe erwartet", dfr_n: "{n}-mal", dfr_heat: "{q} kWh W\u00e4rme", cop_pump: "W\u00e4rmepumpe (wie Weheat z\u00e4hlt)", scope: "Alles, was die W\u00e4rmepumpe verbraucht: Heizung, Warmwasser, Inneneinheit und Standby.", tot: "gesamt", cost_tot: "Kosten gesamt", elec_tot: "Strom gesamt", bat: "Akku", heat_only: "Heizstrom", c_heat: "Heizung", c_dhw: "Warmwasser", c_ind: "Inneneinheit", c_rest: "Standby", sun_note: "eigene Sonne z\u00e4hlt zum Einspeisepreis", cost_today: "Heizung + Inneneinheit" },
  fr: { tab: "\u00c9nergie", hour: "Heure", day: "Jour", week: "Semaine", month: "Mois", per: "P\u00e9riode", out: "Ext\u00e9rieur", kwh: "kWh", cop: "COP", idx: "Performance", cost: "Co\u00fbt", flow: "D\u00e9part", heat: "Chaleur", dfr: "D\u00e9givrage", run: "Heures de chauffe", sun: "Soleil propre", room: "Pi\u00e8ce", total: "Total", csv: "CSV", none: "Pas encore de donn\u00e9es des compteurs de la pompe \u00e0 chaleur.", loading: "Chargement\u2026", catch: "* ici le cloud Weheat a rattrap\u00e9 des heures manqu\u00e9es : hors de l'indice", idx_help: "Performance : le COP de chauffage en part de ce que Roost a appris de cette pompe \u00e0 chaleur \u00e0 m\u00eame temp\u00e9rature ext\u00e9rieure et puissance. 100 % = comme pr\u00e9vu ; nettement plus bas pendant des semaines indique l'appareil (\u00e9vaporateur, r\u00e9glage de la pompe), pas la m\u00e9t\u00e9o. \u2248 = d\u00e9givrages estim\u00e9s d'apr\u00e8s le compteur de d\u00e9givrage (Home Assistant ne garde les \u00e9tats que quelques jours).", st_heating: "chauffe", st_dhw: "eau chaude", st_defrost: "d\u00e9givre", st_idle: "repos", heat_sp: "chauffage", heat_dhw: "eau chaude", heat_def: "perdu au d\u00e9givrage", el_heat: "chauffage", el_dhw: "eau chaude", el_ind: "unit\u00e9 int\u00e9rieure", el_rest: "veille", cop_heat: "chauffage", cop_dhw: "eau chaude", cop_all: "avec l'unit\u00e9 int\u00e9rieure", dd: "Degr\u00e9s-jours", per_dd: "kWh par degr\u00e9-jour", vs: "par rapport \u00e0 la p\u00e9riode pr\u00e9c\u00e9dente", lowest: "minimum", hours_run: "{h} heures de chauffe", wk: "sem.", status: "\u00c9tat", elec: "\u00c9lectricit\u00e9", hu: "h", of_exp: "de ce que Roost attend de cette pompe \u00e0 chaleur", dfr_n: "{n} fois", dfr_heat: "{q} kWh de chaleur", cop_pump: "pompe \u00e0 chaleur (comme Weheat la compte)", scope: "Tout ce que la pompe \u00e0 chaleur consomme : chauffage, eau chaude, unit\u00e9 int\u00e9rieure et veille.", tot: "total", cost_tot: "Co\u00fbt total", elec_tot: "\u00c9lectricit\u00e9 totale", bat: "batterie", heat_only: "\u00c9lectricit\u00e9 chauffage", c_heat: "chauffage", c_dhw: "eau chaude", c_ind: "unit\u00e9 int\u00e9rieure", c_rest: "veille", sun_note: "le soleil propre compte au prix de r\u00e9injection", cost_today: "Chauffage + unit\u00e9 int\u00e9rieure" },
};

const OT_T = {
  en: { req_by: "by the OpenTherm box", box: "box {v}", progress: "{s} of {S} steady samples \u00b7 {n} of {N} starts", sum: "Shadow, last {r}: Roost would heat {a} h ({b} kWh heat); the heat pump heated {c} h ({d} kWh)",
        h_would: "Roost would ask (flow)", h_meas: "flow measured", h_heat: "heat made", h_heat_would: "heat Roost would ask", h_off: "Roost: off", pump: "heat pump",
        flow: "flow", off: "off", sets: "Roost asks (flow)", trim: "plan {p}, {d}: the heat pump makes {m} of {l} kW", now: "heat pump now {v}", dhw: "heat pump makes hot water", steer: "Steering",
        th: "Thermostat", ot: "OpenTherm", th_h: "room setpoint on the thermostat", ot_h: "flow temperature through the OpenTherm box",
        flow_axis: "flow \u00b0C" , flow_word: "flow", bs_curve: "set to it by hand", bs_curve_ha_offline: "Home Assistant is away", bs_curve_no_command: "no command from Roost", bs_off: "heating switched off", ot_set: "OpenTherm", fmin: "Lowest flow", fmax: "Highest flow", mrun: "Minimum on", moff: "Minimum off", starts: "Starts per 24 h", nolimit: "no limit", quiet: "Quiet hours", qmax: "Output then", q_on: "on", qoff: "off", learned: "Learned from the heat pump", lq: "lowest output", lk: "heat output of the emitters", lstart: "start", lcop: "efficiency (COP) gained per kW lower", lrest: "rest after a stop", samples: "{n} samples", setting: "setting {v}", relearn: "Learn again", relearn_sure: "Sure? Tap again", st_master: "OpenTherm box", st_steered: "steered by Roost", st_curve: "in fallback (fallback curve)", st_written: "last written {t}", st_follow: "without Roost it heats on Roost's curve to {room}", st_nofollow: "fallback curve does NOT follow Roost", planned_starts: "{n} starts planned (24 h)" },
  nl: { req_by: "door het kastje (OpenTherm)", box: "kastje {v}", progress: "{s} van {S} stabiele metingen \u00b7 {n} van {N} starts", sum: "Meekijken, laatste {r}: Roost zou {a} u stoken ({b} kWh warmte); de pomp stookte {c} u ({d} kWh)",
        h_would: "Roost zou vragen (aanvoer)", h_meas: "aanvoer gemeten", h_heat: "warmte geleverd", h_heat_would: "warmte die Roost zou vragen", h_off: "Roost: uit", pump: "pomp",
        flow: "aanvoer", off: "uit", sets: "Roost vraagt (aanvoer)", trim: "plan {p}, {d}: de pomp levert {m} van {l} kW", now: "pomp nu {v}", dhw: "pomp maakt warm water", steer: "Sturing",
        th: "Thermostaat", ot: "OpenTherm", th_h: "kamersetpoint op de thermostaat", ot_h: "aanvoertemperatuur via het OpenTherm-kastje",
        flow_axis: "aanvoer \u00b0C" , flow_word: "aanvoer", bs_curve: "met de hand zo ingesteld", bs_curve_ha_offline: "Home Assistant is weg", bs_curve_no_command: "geen opdracht van Roost", bs_off: "verwarming staat uit", ot_set: "OpenTherm", fmin: "Laagste aanvoer", fmax: "Hoogste aanvoer", mrun: "Minimaal aan", moff: "Minimaal uit", starts: "Starts per 24 u", nolimit: "geen grens", quiet: "Stille uren", qmax: "Vermogen dan", q_on: "aan", qoff: "uit", learned: "Geleerd van de warmtepomp", lq: "laagste vermogen", lk: "warmteafgifte vloer/radiatoren", lstart: "start", lcop: "rendement (COP) erbij per kW lager", lrest: "rust na een stop", samples: "{n} metingen", setting: "instelling {v}", relearn: "Opnieuw leren", relearn_sure: "Zeker? Tik nogmaals", st_master: "OpenTherm-kastje", st_steered: "gestuurd door Roost", st_curve: "op terugval (stooklijn bij terugval)", st_written: "laatst geschreven {t}", st_follow: "valt Roost weg, dan stookt hij op de stooklijn van Roost naar {room}", st_nofollow: "stooklijn bij terugval volgt Roost NIET", planned_starts: "{n} starts gepland (24 u)" },
  de: { req_by: "von der OpenTherm-Box", box: "Box {v}", progress: "{s} von {S} stabilen Messungen \u00b7 {n} von {N} Starts", sum: "Mitlaufen, letzte {r}: Roost w\u00fcrde {a} h heizen ({b} kWh W\u00e4rme); die W\u00e4rmepumpe heizte {c} h ({d} kWh)",
        h_would: "Roost w\u00fcrde fordern (Vorlauf)", h_meas: "Vorlauf gemessen", h_heat: "W\u00e4rme geliefert", h_heat_would: "W\u00e4rme, die Roost fordern w\u00fcrde", h_off: "Roost: aus", pump: "W\u00e4rmepumpe",
        flow: "Vorlauf", off: "aus", sets: "Roost fordert (Vorlauf)", trim: "Plan {p}, {d}: die W\u00e4rmepumpe liefert {m} von {l} kW", now: "W\u00e4rmepumpe jetzt {v}", dhw: "W\u00e4rmepumpe macht Warmwasser", steer: "Steuerung",
        th: "Thermostat", ot: "OpenTherm", th_h: "Raumsollwert am Thermostat", ot_h: "Vorlauftemperatur \u00fcber die OpenTherm-Box",
        flow_axis: "Vorlauf \u00b0C" , flow_word: "Vorlauf", bs_curve: "von Hand so eingestellt", bs_curve_ha_offline: "Home Assistant ist weg", bs_curve_no_command: "kein Befehl von Roost", bs_off: "Heizen ausgeschaltet", ot_set: "OpenTherm", fmin: "Niedrigster Vorlauf", fmax: "H\u00f6chster Vorlauf", mrun: "Mindestens an", moff: "Mindestens aus", starts: "Starts pro 24 h", nolimit: "keine Grenze", quiet: "Ruhezeit", qmax: "Leistung dann", q_on: "an", qoff: "aus", learned: "Von der W\u00e4rmepumpe gelernt", lq: "niedrigste Leistung", lk: "W\u00e4rmeabgabe", lstart: "Start", lcop: "Wirkungsgrad (COP) je kW weniger", lrest: "Pause nach einem Stopp", samples: "{n} Messungen", setting: "Einstellung {v}", relearn: "Neu lernen", relearn_sure: "Sicher? Nochmals tippen", st_master: "OpenTherm-Box", st_steered: "von Roost gesteuert", st_curve: "im Ersatzbetrieb (Ersatzheizkurve)", st_written: "zuletzt geschrieben {t}", st_follow: "f\u00e4llt Roost aus, heizt sie nach Roosts Kurve auf {room}", st_nofollow: "Ersatzheizkurve folgt Roost NICHT", planned_starts: "{n} Starts geplant (24 h)" },
  fr: { req_by: "par le bo\u00eetier OpenTherm", box: "bo\u00eetier {v}", progress: "{s} sur {S} mesures stables \u00b7 {n} sur {N} d\u00e9marrages", sum: "Observation, derni\u00e8res {r} : Roost chaufferait {a} h ({b} kWh de chaleur) ; la pompe a chauff\u00e9 {c} h ({d} kWh)",
        h_would: "Roost demanderait (d\u00e9part)", h_meas: "d\u00e9part mesur\u00e9", h_heat: "chaleur fournie", h_heat_would: "chaleur que Roost demanderait", h_off: "Roost : arr\u00eat", pump: "pompe",
        flow: "d\u00e9part", off: "arr\u00eat", sets: "Roost demande (d\u00e9part)", trim: "plan {p}, {d} : la pompe fournit {m} sur {l} kW", now: "pompe maintenant {v}", dhw: "la pompe fait l'eau chaude", steer: "Pilotage",
        th: "Thermostat", ot: "OpenTherm", th_h: "consigne de la pi\u00e8ce sur le thermostat", ot_h: "temp\u00e9rature de d\u00e9part via le bo\u00eetier OpenTherm",
        flow_axis: "d\u00e9part \u00b0C" , flow_word: "d\u00e9part", bs_curve: "r\u00e9gl\u00e9 ainsi \u00e0 la main", bs_curve_ha_offline: "Home Assistant est absent", bs_curve_no_command: "aucun ordre de Roost", bs_off: "chauffage coup\u00e9", ot_set: "OpenTherm", fmin: "D\u00e9part minimal", fmax: "D\u00e9part maximal", mrun: "Marche minimale", moff: "Arr\u00eat minimal", starts: "D\u00e9marrages par 24 h", nolimit: "pas de limite", quiet: "Heures calmes", qmax: "Puissance alors", q_on: "activ\u00e9es", qoff: "arr\u00eat", learned: "Appris de la pompe", lq: "puissance minimale", lk: "\u00e9mission de chaleur", lstart: "d\u00e9marrage", lcop: "rendement (COP) par kW en moins", lrest: "repos apr\u00e8s un arr\u00eat", samples: "{n} mesures", setting: "r\u00e9glage {v}", relearn: "R\u00e9apprendre", relearn_sure: "S\u00fbr ? Touchez encore", st_master: "Bo\u00eetier OpenTherm", st_steered: "pilot\u00e9e par Roost", st_curve: "en secours (courbe de secours)", st_written: "\u00e9crit {t}", st_follow: "sans Roost, elle chauffe sur la courbe de Roost jusqu\u2019\u00e0 {room}", st_nofollow: "la courbe de secours ne suit PAS Roost", planned_starts: "{n} d\u00e9marrages pr\u00e9vus (24 h)" }
};

// Every number the card edits. lo/hi match the roost.set_settings schema (__init__.py); unit: deg, h (whole hours),
// min, kW or a count. ot: a field of the OpenTherm block; ent: an entity of the master itself (its min/max/step win).
const SETS = {
  comfort: { lo: 15, hi: 25, step: 0.5, dec: 1, unit: "deg" },
  day_min: { lo: 10, hi: 25, step: 0.5, dec: 1, unit: "deg" },
  night_min: { lo: 5, hi: 25, step: 0.5, dec: 1, unit: "deg" },
  store_max: { lo: 15, hi: 28, step: 0.5, dec: 1, unit: "deg" },
  lowest_setpoint: { lo: 5, hi: 25, step: 0.5, dec: 1, unit: "deg" },
  day_from: { lo: 0, hi: 23, step: 1, dec: 0, unit: "h" },
  day_to: { lo: 1, hi: 24, step: 1, dec: 0, unit: "h" },
  ot_min_flow: { ent: "min_flow_entity", ot: "min_flow", lo: 10, hi: 40, step: 0.5, dec: 1, unit: "deg" },   // the box owns it when it has one
  ot_max_flow: { ent: "max_flow_entity", ot: "max_flow", lo: 25, hi: 50, step: 0.5, dec: 1, unit: "deg" },
  ot_max_starts: { ot: "max_starts", lo: 0, hi: 24, step: 1, dec: 0, unit: "" },
  ot_quiet_from: { ot: "quiet_from", lo: 0, hi: 23, step: 1, dec: 0, unit: "h", wrap: 24 },
  ot_quiet_to: { ot: "quiet_to", lo: 0, hi: 23, step: 1, dec: 0, unit: "h", wrap: 24 },
  ot_quiet_max: { ot: "quiet_max", lo: 0.5, hi: 10, step: 0.5, dec: 1, unit: "kW" },
  ot_min_run: { ent: "min_run_entity", lo: 0, hi: 120, step: 5, dec: 0, unit: "min" },
  ot_min_off: { ent: "min_off_entity", lo: 0, hi: 120, step: 5, dec: 0, unit: "min" }
};
const SET_T = {
  en: { bad: "not a number", order_from: "must be before the end", order_to: "must be after the start", unconfirmed: "not confirmed: shown as it is",
        from: "Comfort from", to: "Comfort until", q_from: "Quiet from", q_to: "Quiet until", failed: "Not done" },
  nl: { bad: "geen getal", order_from: "moet v\u00f3\u00f3r het einde liggen", order_to: "moet na het begin liggen", unconfirmed: "niet bevestigd: dit is de huidige stand",
        from: "Comfort vanaf", to: "Comfort tot", q_from: "Stil vanaf", q_to: "Stil tot", failed: "Niet gelukt" },
  de: { bad: "keine Zahl", order_from: "muss vor dem Ende liegen", order_to: "muss nach dem Beginn liegen", unconfirmed: "nicht best\u00e4tigt: aktueller Stand",
        from: "Komfort ab", to: "Komfort bis", q_from: "Ruhe ab", q_to: "Ruhe bis", failed: "Nicht geklappt" },
  fr: { bad: "pas un nombre", order_from: "doit pr\u00e9c\u00e9der la fin", order_to: "doit suivre le d\u00e9but", unconfirmed: "non confirm\u00e9 : valeur actuelle",
        from: "Confort d\u00e8s", to: "Confort jusqu'\u00e0", q_from: "Calme d\u00e8s", q_to: "Calme jusqu'\u00e0", failed: "\u00c9chec" }
};

// v0.9 card (pills, panels, settings): texts in English and Dutch; other languages fall back to English per key.
const T2 = {
  en: { n_settings: "Settings", n_ready: "ready", n_learning: "learning", n_left: "{t} left", n_until: "until {t}",
        n_heating: "Heating", n_hotwater: "Hot water", n_defrost: "Defrosting", n_idle: "Idle", n_lastran: "last ran {t}", n_pump: "Pump",
        n_saves: "Saves", n_costs: "Costs more", n_requested: "Requested", n_req_by: "by the thermostat", n_supply: "Out (supply)",
        n_return: "In (return)", n_dt: "\u0394T", n_above_req: "{d} above request", n_below_req: "{d} below request", n_back: "back from the house",
        n_power: "{i} in \u2192 {o} heat", n_today: "Today", n_yday: "Yesterday", n_planned24: "Planned 24 h", n_runs: "{n} starts \u00b7 {m}",
        n_ready_t: "Ready to steer.", n_ready_x: "Roost plans in shadow and does not touch the thermostat yet. Last night's self-check passed.",
        n_sets: "Roost sets", n_therm_now: "thermostat now {v}", n_next: "Next change", n_nochange: "no change planned",
        n_from: "from {t}", n_in6: "\u2192 {v} in 6 h",
        c_heating_curve: "Heating curve", c_opentherm: "OpenTherm", c_opentherm_smart: "OpenTherm smart", c_roost: "Roost via OpenTherm",
        c_on_off: "On/off thermostat", c_cloud_thermostat: "Cloud thermostat", c_manual_power: "Manual power", c_auto_input_select: "Automatic input",
        c_manual_setpoint: "Manual setpoint",
        cp_heating_curve: "Curve", cp_opentherm: "OpenTherm", cp_opentherm_smart: "OT smart", cp_on_off: "On/off", cp_cloud_thermostat: "Cloud",
        cl_on_off: "The thermostat only switches the pump on and off; the pump picks its water temperature itself.",
        cl_cloud_thermostat: "Weheat's own thermostat in the app steers the pump.",
        c_weheat: "Reported by the pump itself", c_weheat_at: "reported by the pump {t}", c_app: "Change it in the Weheat app (or the installer menu).",
        c_noreport: "Not known yet: the pump has not reported it (Weheat login or cloud).",
        n_curve: "Heating curve", n_curve_at: "{v} at 0\u00b0",
        cl_heating_curve: "The pump picks its water temperature from the outside temperature; Roost decides when it heats.",
        cl_opentherm: "The thermostat asks for a water temperature and the pump follows it; Roost moves the room setpoint.",
        cl_opentherm_smart: "",
        cl_roost: "Roost plans the water temperature itself and falls back to its learned heating curve.",
        c_checked: "checked, {d} days", c_unknown: "Not checked yet: too few jumps in the thermostat's request ({n} of 10).",
        c_nocheck: "Roost can only check the heating curve and OpenTherm against how the pump answers.",
        c_mis_head: "Set to {s}, but the pump acts like {d}",
        c_mis_line: "When the thermostat's request jumped ({n}\u00d7), the supply temperature {how}. Switched in the Weheat app?",
        c_followed: "followed within 20 minutes", c_notfollowed: "did not follow", c_use: "Use {d}", c_change: "Change",
        c_title: "How the heat pump is controlled", c_intro: "Tell Roost how your Weheat is set (you switch it in the Weheat app). Roost checks this against the pump's data.",
        c_set: "SET", c_soon: "SOON", c_data: "DATA SAYS THIS", c_none: "Not set",
        sv_intro: "Same house model, prices and weather for both: a steady thermostat versus Roost's plan.",
        sv_steady: "Steady thermostat", sv_plan: "\u2212 Roost's plan", sv_end: "Heat left at the end", sv_total: "Expected saving",
        sv_month: "This month", sv_yday: "Yesterday", sv_days: "days that count",
        a_set_failed: "Could not set the thermostat.", ax_set_failed: "Roost tries again in {min} min; check that the thermostat is online.",
        a_weheat_missing: "No heat pump data since {t}.", ax_weheat_missing: "Pump values show \u2014 until it is back; Roost keeps planning.",
        a_weheat_login: "Roost's Weheat login has expired.", ax_weheat_login: "Re-authenticate Roost in Settings \u2192 Devices & services. Until then no Weheat history and no control method; Roost keeps planning.",
        a_fallback_no_price: "No prices to plan on.", ax_fallback_no_price: "Roost plans with a flat price; this day does not count for the saving.",
        a_fallback_schedule: "No prices or weather.", ax_fallback_schedule: "Roost follows your comfort hours until they are back.",
        g_comfort: "comfort", g_store: "stores", g_hold: "holds", g_coast: "coasts", g_skip: "skips",
        gl_store: "stores heat", gl_hold: "holds", gl_coast: "coasts", gl_skip: "skips an expensive hour",
        gx_store: "heats extra while energy is cheap, so the floor holds warmth.", gx_hold: "keeps the room at the setpoint.",
        gx_coast: "the room is warm enough, the pump can rest.", gx_skip: "expensive hour, lives off stored heat.",
        gx_bars: "Bar height is the price Roost counts for that hour: the tariff, lower where your own solar covers it. The strip below marks comfort hours and night.",
        g_bars: "bars: price Roost counts ({r} ct) \u00b7 tap an hour", g_acc: "plan \u00b1{v} \u00b0C (6 h)", g_explain: "Explain the chart",
        h_counts: "counts {c} ct", h_tariff: "tariff {t} ct", h_costs: "cost {e}", h_pumpk: "pump {k} kWh", h_close: "Close",
        n_sensors_t: "Heat pump sensors", n_sensors_ok: "Found on the heat pump: water in/out, thermostat request, power. Other sensors can be set with the roost.set_settings action (pump_entities).",
        n_sensors_none: "No heat pump sensors found: the card only shows whether the pump runs.",
        n_configure: "Prices, house sensors, notifications", n_open: "Configure", n_done: "Done", s_comfort_t: "Comfort" },
  nl: { n_settings: "Instellingen", n_ready: "klaar", n_learning: "leert", n_left: "nog {t}", n_until: "tot {t}",
        n_heating: "Verwarmt", n_hotwater: "Warm water", n_defrost: "Ontdooit", n_idle: "Rust", n_lastran: "draaide {t}", n_pump: "Pomp",
        n_saves: "Bespaart", n_costs: "Duurder", n_requested: "Gevraagd", n_req_by: "door de thermostaat", n_supply: "Aanvoer",
        n_return: "Retour", n_dt: "\u0394T", n_above_req: "{d} boven de vraag", n_below_req: "{d} onder de vraag", n_back: "terug uit het huis",
        n_power: "{i} erin \u2192 {o} warmte", n_today: "Vandaag", n_yday: "Gisteren", n_planned24: "Gepland 24 u", n_runs: "{n} starts \u00b7 {m}",
        n_ready_t: "Klaar om te sturen.", n_ready_x: "Roost plant in schaduw en raakt de thermostaat nog niet aan. De zelftoets van vannacht is geslaagd.",
        n_sets: "Roost zet", n_therm_now: "thermostaat nu {v}", n_next: "Volgende wijziging", n_nochange: "geen wijziging gepland",
        n_from: "vanaf {t}", n_in6: "\u2192 {v} over 6 u",
        c_heating_curve: "Stooklijn", c_opentherm: "OpenTherm", c_opentherm_smart: "OpenTherm smart", c_roost: "Roost via OpenTherm",
        c_on_off: "Aan/uit-thermostaat", c_cloud_thermostat: "Cloud-thermostaat", c_manual_power: "Handmatig vermogen", c_auto_input_select: "Automatische ingang",
        c_manual_setpoint: "Handmatig setpoint",
        cp_heating_curve: "Stooklijn", cp_opentherm: "OpenTherm", cp_opentherm_smart: "OT smart", cp_on_off: "Aan/uit", cp_cloud_thermostat: "Cloud",
        cl_on_off: "De thermostaat zet de pomp alleen aan en uit; de pomp kiest zelf de watertemperatuur.",
        cl_cloud_thermostat: "De eigen thermostaat van Weheat in de app stuurt de pomp.",
        c_weheat: "Gemeld door de pomp zelf", c_weheat_at: "gemeld door de pomp {t}", c_app: "Wijzigen kan in de Weheat-app (of het installateursmenu).",
        c_noreport: "Nog niet bekend: de pomp heeft het niet gemeld (Weheat-login of cloud).",
        n_curve: "Stooklijn", n_curve_at: "{v} bij 0\u00b0",
        cl_heating_curve: "De pomp kiest de watertemperatuur op de buitentemperatuur; Roost bepaalt wanneer hij stookt.",
        cl_opentherm: "De thermostaat vraagt een watertemperatuur en de pomp volgt die; Roost verschuift het kamersetpoint.",
        cl_opentherm_smart: "",
        cl_roost: "Roost plant zelf de watertemperatuur en valt terug op zijn geleerde stooklijn.",
        c_checked: "getoetst, {d} dagen", c_unknown: "Nog niet getoetst: te weinig sprongen in de vraag van de thermostaat ({n} van 10).",
        c_nocheck: "Roost kan alleen stooklijn en OpenTherm toetsen aan hoe de pomp reageert.",
        c_mis_head: "Ingesteld op {s}, maar de pomp gedraagt zich als {d}",
        c_mis_line: "Toen de vraag van de thermostaat sprong ({n}\u00d7), {how} de aanvoertemperatuur. Omgezet in de Weheat-app?",
        c_followed: "volgde binnen 20 minuten", c_notfollowed: "volgde niet", c_use: "Gebruik {d}", c_change: "Wijzigen",
        c_title: "Hoe de warmtepomp wordt gestuurd", c_intro: "Vertel Roost hoe je Weheat staat (dat zet je in de Weheat-app). Roost toetst dit aan de data van de pomp.",
        c_set: "INGESTELD", c_soon: "BINNENKORT", c_data: "DATA ZEGT DIT", c_none: "Niet ingesteld",
        sv_intro: "Hetzelfde huismodel, dezelfde prijzen en hetzelfde weer voor beide: een vaste thermostaat tegenover het plan van Roost.",
        sv_steady: "Vaste thermostaat", sv_plan: "\u2212 plan van Roost", sv_end: "Warmte over aan het eind", sv_total: "Verwachte besparing",
        sv_month: "Deze maand", sv_yday: "Gisteren", sv_days: "dagen die tellen",
        a_set_failed: "Kon de thermostaat niet instellen.", ax_set_failed: "Roost probeert het over {min} min opnieuw; kijk of de thermostaat online is.",
        a_weheat_missing: "Geen warmtepompdata sinds {t}.", ax_weheat_missing: "Pompwaarden tonen \u2014 tot hij terug is; Roost blijft plannen.",
        a_weheat_login: "De Weheat-login van Roost is verlopen.", ax_weheat_login: "Verifieer Roost opnieuw via Instellingen \u2192 Apparaten en diensten. Tot dan geen Weheat-historie en geen stuurwijze; Roost blijft plannen.",
        a_fallback_no_price: "Geen prijzen om op te plannen.", ax_fallback_no_price: "Roost plant met een vlakke prijs; deze dag telt niet mee voor de besparing.",
        a_fallback_schedule: "Geen prijzen of weer.", ax_fallback_schedule: "Roost volgt je comforturen tot ze terug zijn.",
        g_comfort: "comfort", g_store: "slaat op", g_hold: "houdt", g_coast: "rust", g_skip: "slaat over",
        gl_store: "slaat warmte op", gl_hold: "houdt vast", gl_coast: "rust", gl_skip: "slaat een duur uur over",
        gx_store: "stookt extra terwijl energie goedkoop is, zodat de vloer warmte vasthoudt.", gx_hold: "houdt de kamer op het setpoint.",
        gx_coast: "de kamer is warm genoeg, de pomp kan rusten.", gx_skip: "duur uur, leeft op opgeslagen warmte.",
        gx_bars: "De hoogte is de prijs waar Roost dat uur mee rekent: het tarief, lager waar eigen zon het dekt. De strook eronder toont comforturen en nacht.",
        g_bars: "staven: prijs waar Roost mee rekent ({r} ct) \u00b7 tik op een uur", g_acc: "plan \u00b1{v} \u00b0C (6 u)", g_explain: "Uitleg bij de grafiek",
        h_counts: "rekent {c} ct", h_tariff: "tarief {t} ct", h_costs: "kost {e}", h_pumpk: "pomp {k} kWh", h_close: "Sluiten",
        n_sensors_t: "Warmtepompsensoren", n_sensors_ok: "Gevonden op de warmtepomp: aanvoer/retour, vraag van de thermostaat, vermogen. Andere sensoren kun je kiezen met de actie roost.set_settings (pump_entities).",
        n_sensors_none: "Geen warmtepompsensoren gevonden: de kaart toont alleen of de pomp draait.",
        n_configure: "Prijzen, huissensoren, meldingen", n_open: "Configureren", n_done: "Klaar", s_comfort_t: "Comfort" }
};
Object.keys(T2).forEach((l) => { T[l] = Object.assign(T[l] || {}, T2[l]); });
// what the planner does in an hour, by its reason: the colour and word in the plan graph
const CAT = { store_cheap: "store", store_cheap_house: "store", store_ahead: "store", store_ahead_house: "store", store_solar: "store",
  store_solar_house: "store", expensive: "skip", expensive_house: "skip", wait: "skip", warm_enough: "coast", hold_ahead: "coast" };
const cat = (code) => CAT[code] || "hold";

class RoostCard extends HTMLElement {
  static getConfigElement() { return document.createElement("roost-card-editor"); }

  static getStubConfig(hass) {
    const ent = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && hass.states[e].attributes &&
      hass.states[e].attributes.plan !== undefined && hass.states[e].attributes.store_max !== undefined);
    return { entity: ent || "" };
  }

  setConfig(config) {
    if (!config.entity) throw new Error("entity is required (the 'Planned setpoint' sensor)");
    this._config = Object.assign({}, config);
    if (this._view === undefined) this._view = ["history", "table", "curve", "energy"].indexOf(config.view) >= 0 ? config.view : "plan";
    if (this._range === undefined) this._range = 24;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  // Home Assistant hands every state change in the house to every card: redraw only when something this card shows
  // changed (the sensor, its sibling entities, the OpenTherm master's entities it reads)
  set hass(hass) {
    this._hass = hass;
    const st = this._config && hass.states[this._config.entity];
    const parts = [st ? st.last_updated : "none", hass.locale && hass.locale.language];
    this._watched().forEach((eid) => { const s = hass.states[eid]; parts.push(s ? s.last_updated : ""); });
    const key = parts.join("|");
    if (key !== this._key) { this._key = key; this._render(); }
  }
  // The other entities the card reads: the Roost siblings and, with OpenTherm, the master's minimum on/off numbers and
  // its own curve flow
  _watched() {
    const sib = this._siblings(), out = Object.keys(sib).map((k) => sib[k]);
    const st = this._hass && this._config && this._hass.states[this._config.entity];
    const o = st && st.attributes && st.attributes.opentherm;
    if (o) {
      [o.min_run_entity, o.min_off_entity, o.curve_flow_entity].forEach((e) => { if (e) out.push(e); });
    }
    return out;
  }

  getCardSize() { return 2 + (this._show("tiles") ? 1 : 0) + (this._show("chart") ? 3 : 0); }
  getGridOptions() { return { columns: 12, min_columns: 6 }; }

  _show(part) { return shows(this._config, part); }
  _lang() { const own = this._config && this._config.language; return own && T[own] ? own : lang2(this._hass); }
  _t(k) { const own = (T[this._lang()] || T.en)[k]; return own === undefined ? T.en[k] : own; }
  _ot(k) { const own = (OT_T[this._lang()] || OT_T.en)[k]; return own === undefined ? OT_T.en[k] : own; }
  _et(k) { const own = (EN_T[this._lang()] || EN_T.en)[k]; return own === undefined ? EN_T.en[k] : own; }
  _why(code, args, text) {
    const tpl = code && ((WHY[this._lang()] || WHY.en)[code] || WHY.en[code]);
    if (!tpl) return text || "";
    return tpl.replace(/\{(\w+)\}/g, (m, k) => {
      if (!args || args[k] === undefined || args[k] === null) return m;
      // the OpenTherm box's state code in words (curve_ha_offline -> "Home Assistant is away"); unknown codes as they are
      if (k === "state" && code === "ot_fallback") { const w = this._ot("bs_" + args[k]); if (w) return w; }
      return typeof args[k] === "number" ? this._num(args[k], nn(WHY_DECIMALS[k], 1)) : this._esc(args[k]);   // a state is text
    });
  }
  _locale() {
    const user = (this._hass && ((this._hass.locale && this._hass.locale.language) || this._hass.language)) || undefined;
    const own = this._config && this._config.language;
    if (own && T[own]) return user && user.slice(0, 2) === own ? user : own;
    return user;
  }
  _hour(date) {
    const own = this._config && this._config.time_format;
    const profile = this._hass && this._hass.locale && this._hass.locale.time_format;
    const choice = own === "24" || own === "12" ? own : profile;
    const h12 = choice === "24" ? false : choice === "12" ? true : undefined;
    return timeFmt(choice === "system" ? undefined : this._locale(), h12).format(date);
  }
  _num(v, d) {
    if (v === null || v === undefined || isNaN(v)) return "\u2014";
    const x = Number(v), f = Math.pow(10, d || 0);
    return numFmt(this._locale(), d).format(Math.round(x * f) === 0 ? 0 : x);   // no "-0,0" for a value just below zero
  }
  _money(v, digits) {
    if (v === null || v === undefined || isNaN(v)) return "\u2014";
    const cur = (this._hass && this._hass.config && this._hass.config.currency) || "EUR";
    try { return cashFmt(this._locale(), cur, digits).format(Number(v)); } catch (e) { return fmt(v, digits === undefined ? 2 : digits); }
  }

  // The other Roost entities of the same entry, found through the entity registry by their translation key.
  // Looked up once per entity registry (hass.entities is a new object only when the registry changes), not at every
  // state change in the house
  _siblings() {
    const hass = this._hass;
    if (!hass || !hass.entities || !this._config) return {};
    if (this._sibOf === hass.entities && this._sibFor === this._config.entity) return this._sibCache;
    const out = {}, me = hass.entities[this._config.entity];
    if (me && me.device_id) {
      Object.keys(hass.entities).forEach((eid) => {
        const e = hass.entities[eid];
        if (e.device_id === me.device_id && e.platform === "roost" && e.translation_key) out[e.translation_key] = eid;
      });
    }
    this._sibOf = hass.entities; this._sibFor = this._config.entity; this._sibCache = out;
    return out;
  }
  _hm(d) {   // a time, with the weekday when it is not today
    return (d.toDateString() === new Date().toDateString() ? "" : dayFmt(this._lang()).format(d) + " ") +
      timeFmt(this._lang(), undefined).format(d);
  }
  _sib(key) { const s = this._siblings(); const st = s[key] && this._hass.states[s[key]]; return st ? st : null; }

  _shell() {
    if (this._card && this._card.parentNode === this.shadowRoot) return this._card;
    this.shadowRoot.innerHTML = `${this._style()}<ha-card></ha-card>`;
    this._card = this.shadowRoot.querySelector("ha-card");
    // the plan graph is drawn in the card's own pixels (text stays its size on a wide dashboard): draw again when the
    // width changes clearly
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver((es) => {
        const w = Math.round(es[0].contentRect.width);
        if (w && Math.abs(w - (this._chartW || 0)) > 24) { this._chartW = w; if (this._clickable) this._render(); }
      }).observe(this._card);
    }
    // one listener per kind of event for the whole card (the DOM stays between redraws, so no listeners per node)
    const c = this._card;
    c.addEventListener("click", (ev) => this._onTap(ev));
    c.addEventListener("keydown", (ev) => this._onKey(ev));
    c.addEventListener("change", (ev) => this._onChange(ev));
    c.addEventListener("focusout", (ev) => this._onBlur(ev));
    c.addEventListener("toggle", (ev) => this._onToggle(ev), true);       // <details>: does not bubble
    c.addEventListener("pointermove", (ev) => this._onScrub(ev));
    c.addEventListener("pointerdown", (ev) => this._onScrub(ev));
    c.addEventListener("touchmove", (ev) => this._onScrub(ev), { passive: true });
    return c;
  }

  // Redraws come in bursts (a tap, then the sensor, then its siblings): one per frame
  _render() {
    if (this._raf) return;
    if (typeof requestAnimationFrame !== "function") { this._paint(); return; }
    this._raf = requestAnimationFrame(() => { this._raf = null; this._paint(); });
  }

  _paint() {
    if (!this.shadowRoot || !this._config || !this._hass) return;
    const st = this._hass.states[this._config.entity];
    if (!st || st.state === "unavailable" || st.state === "unknown") {
      this._clickable = false;
      morph(this._shell(), `<div class="na" data-k="na">${st ? this._t("unavailable") : this._t("pick")}</div>`);
      return;
    }
    const a = st.attributes;
    this._settle(a);
    const mode = a.mode || "shadow";
    const paused = a.paused_until && new Date(a.paused_until) > new Date();
    const canMode = !!this._siblings().mode;
    const away = a.away_until && new Date(a.away_until) > new Date();
    const title = this._config.title || this._t("title");
    let reason = this._why(a.reason_code, a.reason_args, a.reason) || this._t("noplan");
    // storing heat: say why the room may go above comfort (people expect it to stay at the comfort temperature)
    if (CAT[a.reason_code] === "store" && a.store_max > a.comfort + 0.05) reason += ` \u00b7 ${this._t("store_hint").replace("{max}", this._num(a.store_max, 1) + DEG)}`;
    const hist = this._histOn();
    const segv = (v, l) => `<span data-v="${v}" class="${this._view === v ? "on" : ""}" role="button" tabindex="0">${this._t(l)}</span>`;
    const seg = hist ? `<div class="seg tabs" data-k="seg">${segv("plan", "ahead")}${segv("table", "tab_table")}${segv("history", "back")}<span data-v="energy" class="${this._view === "energy" ? "on" : ""}" role="button" tabindex="0">${this._et("tab")}</span></div>` : "";
    const gear = `<button class="setgear${this._open === "settings" ? " on" : ""}" aria-label="${this._t("n_settings")}" title="${this._t("n_settings")}" aria-expanded="${this._open === "settings"}"><ha-icon icon="mdi:tune-variant"></ha-icon></button>`;
    let html = `<div class="head" data-k="head"><div class="ico" title="${this._t("go_integration")}"><ha-icon icon="mdi:bird"></ha-icon></div>` +
      `<div class="ht"><div class="tt">${title}</div><div class="sub">${reason}</div></div>${gear}</div>`;
    const ready = this._sib("ready");
    html += this._alerts(a);
    if (this._err) html += `<div class="alert red" role="alert" data-k="err"><ha-icon icon="mdi:alert-outline"></ha-icon><span><b>${this._st("failed")}</b> ${this._esc(this._err.text)}</span></div>`;
    if (mode === "active" && ready && ready.state === "off") html += `<div class="warnline" data-k="notready"><ha-icon icon="mdi:alert-outline"></ha-icon>${this._t("warn_notready")}</div>`;
    if (this._show("status")) html += this._pills(a, mode, paused, away, ready, canMode);
    html += this._panel(a, mode, paused, away, ready, canMode);
    let inner = "";
    if (hist && this._view === "curve") inner = seg + `<div data-k="v-curve">${this._curveView()}</div>`;
    else if (hist && this._view === "table") inner = seg + `<div data-k="v-table">${this._tableBody(a)}</div>`;
    else if (hist && this._view === "history") inner = seg + `<div data-k="v-hist">${this._histBody()}</div>`;
    else if (hist && this._view === "energy") inner = seg + `<div data-k="v-energy">${this._energyBody()}</div>`;
    else {
      if (this._show("tiles")) inner += this._tiles(st, a);
      if (a.rooms && a.rooms.length) inner += this._rooms(a.rooms);
      inner += seg;
      if (this._show("chart") && a.plan && a.plan.length) inner += this._chart(a) + this._hourPanel(a);
      if (this._show("footer")) inner += this._footer(a);
    }
    this._clickable = true;
    morph(this._shell(), html + inner);
  }

  _ct(k, args) {
    const tpl = (CURVE_T[this._lang()] || CURVE_T.en)[k] || CURVE_T.en[k];
    return tpl.replace(/\{(\w+)\}/g, (m, x) => (args && args[x] !== undefined ? args[x] : m));
  }

  // The curve view: three numbers, the curve in a graph (advice, the curve now, what the house needs, what the unit
  // made, the zone where it cycles), the five points and the notes
  // The advice for another indoor temperature ("what if"): the same steps as Roost's curve.py, on its learned numbers
  _curveFor(a, room) {
    const ua = nn(a.ua_kw, (a.heat_loss_w_per_k || 0) / 1000), k = nn(a.k_kw, (a.emitter_w_per_k || 0) / 1000), n = a.n || 1.1;
    const base = nn(a.base_kw, 0), margin = nn(a.margin_kw, 0);
    if (!(ua > 0 && k > 0)) return a;
    const up = (v) => Math.ceil(v * 2 - 1e-9) / 2;
    const flow = (t) => { const q = ua * (room - t) + base + margin; return q > 0 ? room + Math.pow(q / k, 1 / n) : null; };
    const top = room + (base + margin) / ua;
    let prev = null;
    const points = a.points.map((p) => {
      const x = p[0];
      let y;
      if (!prev) { const f0 = flow(x); y = f0 !== null && x < top ? up(f0) : up(room); }
      else if (prev[0] >= top) y = up(room);
      else {
        const x0 = prev[0], y0 = prev[1], end = Math.min(x, top), steps = Math.max(2, Math.floor((end - x0) * 4));
        let yy = null;
        for (let i = 1; i <= steps; i++) {
          const t = x0 + (end - x0) * i / steps, f = flow(t);
          if (f === null) continue;
          const ny = y0 + (f - y0) * (x - x0) / (t - x0);
          yy = yy === null ? ny : Math.max(yy, ny);
        }
        y = yy !== null ? up(Math.max(room, Math.min(yy, y0))) : up(room);
      }
      prev = [x, y];
      return [x, y, p[2]];
    });
    return Object.assign({}, a, { room, points });
  }

  _curveView() {
    const s = this._sib("heating_curve"), a0 = s && s.attributes;
    if (!a0 || !a0.points || !a0.points.length) return `<div class="cview"><div class="na">${this._ct("none")}</div></div>`;
    const room = this._curveRoom !== undefined ? this._curveRoom : nn(a0.room, 20);
    const a = Math.abs(room - nn(a0.room, 20)) < 0.01 ? a0 : this._curveFor(a0, room);
    const tile = (label, v, unit, sub) => `<div class="tile htile"><div class="tl">${label}</div><div class="tv">${v}<span>${unit}</span></div><div class="ts">${sub}</div></div>`;
    const pts = a.points.filter((p) => p[1] !== null && p[1] !== undefined);
    let at0 = parseFloat(s.state);
    if (a !== a0 && pts.length > 1) {        // 0 degrees on the line between the points around it
      const i = pts.findIndex((p) => p[0] >= 0);
      at0 = i > 0 ? pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * (0 - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]) : pts[0][1];
    }
    const cyc = a.cycling_from;
    return `<div class="cview"><div class="tiles">` +
      tile(this._ct("at0"), isNaN(at0) ? "\u2014" : this._num(at0, 1), DEG, this._ct("flow")) +
      tile(this._ct("loss"), a.heat_loss_w_per_k !== undefined ? this._num(a.heat_loss_w_per_k, 0) : "\u2014", "W/K", `${a.days} d \u00b7 ${a.hours} h`) +
      tile(this._ct("cyc"), cyc !== null && cyc !== undefined ? this._num(cyc, 0) : "\u2014", DEG, this._ct("outside")) +
      `</div><div class="mrow wirow"><b>${this._ct("wi_label")}</b><span><button class="mini" data-room="-0.5">\u2212</button>` +
      `<b class="sv">${this._num(room, 1)}${DEG}</b><button class="mini" data-room="0.5">+</button></span><small>${this._ct("wi_note")}</small></div>` +
      `${this._curveChart(a)}${this._curveTable(a)}</div>`;
  }

  // Flow temperature against outdoor temperature: the advice (orange, its five points with their values), the curve
  // the heat pump has now (grey, when Weheat gives it), what the house needs without margin (blue, dashed), what the
  // heat pump really made (white dots with their values), the cycling zone (shaded)
  _curveChart(a) {
    const VW = 440, VH = 230, L = 34, R = 14, TOP = 22, B = 34;
    const xs = a.points.map((p) => p[0]).sort((p, q) => p - q), X0 = xs[0], X1 = xs[xs.length - 1];
    const pts = a.points.filter((p) => p[1] !== null && p[1] !== undefined);
    const cloud = (a.cloud || []).filter((c) => c[0] >= X0 && c[0] <= X1);
    const room = nn(a.room, 20), ua = nn(a.ua_kw, (a.heat_loss_w_per_k || 0) / 1000), k = nn(a.k_kw, (a.emitter_w_per_k || 0) / 1000), n = a.n || 1.1;
    const base = nn(a.base_kw, 0), cyc = a.cycling_from !== null && a.cycling_from !== undefined ? a.cycling_from : X1;
    const cold = a.cold_hour !== null && a.cold_hour !== undefined ? Math.max(X0, a.cold_hour) : X0;
    const need = (t) => { const q = ua * (room - t) + base; return q > 0 && k > 0 ? room + Math.pow(q / k, 1 / n) : null; };
    const adv = (t) => {        // the advice line: the five points, straight between them
      if (t <= pts[0][0]) return pts[0][1];
      for (let i = 1; i < pts.length; i++) if (t <= pts[i][0]) return pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * (t - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]);
      return pts[pts.length - 1][1];
    };
    const needPts = [];        // what the house needs, up to where it needs no heat at all
    for (let t = X0; t <= X1 + 1e-9; t += 0.25) { const v = need(t); if (v === null) break; needPts.push([t, v]); }
    const ys = [room].concat(pts.map((p) => p[1]), cloud.map((c) => c[1]), needPts.map((p) => p[1]));
    const lo = Math.floor((Math.min.apply(null, ys) - 2) / 5) * 5, hi = Math.ceil((Math.max.apply(null, ys) + 3) / 5) * 5;
    // the five points of the app evenly over the width; straight between them (each stretch on its own scale)
    const x = (t) => {
      if (t <= X0) return L;
      let i = 0;
      while (i < xs.length - 2 && t > xs[i + 1]) i++;
      const f = Math.min(1, (t - xs[i]) / (xs[i + 1] - xs[i]));
      return L + (i + f) / (xs.length - 1) * (VW - L - R);
    };
    const y = (v) => TOP + (hi - v) / (hi - lo) * (VH - TOP - B);
    const path = (list) => list.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
    let g = "";
    if (cyc < X1) {
      g += `<rect x="${x(Math.max(X0, cyc)).toFixed(1)}" y="${TOP}" width="${(x(X1) - x(Math.max(X0, cyc))).toFixed(1)}" height="${VH - TOP - B}" class="czone"/>` +
        `<text x="${(x(X1) - 4).toFixed(1)}" y="${TOP + 11}" text-anchor="end" class="axis">${this._ct("cz")}</text>`;
    }
    for (let v = lo; v <= hi; v += 5) g += `<line x1="${L}" x2="${VW - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/><text x="${L - 5}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis">${v}\u00b0</text>`;
    a.points.forEach((p) => {       // the x axis on the five points of the app
      g += `<line x1="${x(p[0]).toFixed(1)}" x2="${x(p[0]).toFixed(1)}" y1="${TOP}" y2="${VH - B}" class="grid vgrid"/>` +
        `<text x="${x(p[0]).toFixed(1)}" y="${VH - 18}" text-anchor="${p[0] <= X0 ? "start" : (p[0] >= X1 ? "end" : "middle")}" class="axis">${this._num(p[0], 0)}\u00b0</text>`;
    });
    g += `<text x="${((L + VW - R) / 2).toFixed(1)}" y="${VH - 3}" text-anchor="middle" class="axis">${this._ct("x_axis")} \u2192</text>` +
      `<text x="${L}" y="${TOP - 10}" class="axis">${this._ct("y_axis")}</text>`;
    cloud.forEach((c) => { g += `<circle cx="${x(c[0]).toFixed(1)}" cy="${y(c[1]).toFixed(1)}" r="1.7" class="ccloud"/>`; });
    const needIn = needPts.filter((p) => p[0] <= cyc + 1e-9), needOut = needPts.filter((p) => p[0] >= cyc - 0.25);
    if (needIn.length > 1) g += `<path d="${path(needIn)}" class="cneed"/>`;
    if (needOut.length > 1 && cyc < X1) g += `<path d="${path(needOut)}" class="cneed soft"/>`;
    if (pts.length > 1) {           // solid where it rests on measurements, dashed where calculated or in the cycling zone
      const seg = (t0, t1) => { const xs = [t0].concat(pts.map((p) => p[0]).filter((t) => t > t0 && t < t1), [t1]); return path(xs.map((t) => [t, adv(t)])); };
      const end = Math.min(X1, Math.max(cold, cyc));
      if (cold > X0) g += `<path d="${seg(X0, cold)}" class="cadv dash"/>`;
      if (end > cold) g += `<path d="${seg(cold, end)}" class="cadv"/>`;
      if (end < X1) g += `<path d="${seg(end, X1)}" class="cadv dash"/>`;
    }
    pts.forEach((p) => {
      const soft = p[0] > cyc;
      g += `<circle cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="4" class="cdot${soft ? " soft" : ""}"/>` +
        `<text x="${x(p[0]).toFixed(1)}" y="${(p[0] <= X0 ? y(p[1]) - 8 : y(p[1]) + 16).toFixed(1)}" text-anchor="${p[0] <= X0 ? "start" : (p[0] >= X1 ? "end" : "middle")}" class="cval${soft ? " soft" : ""}">${this._num(p[1], 1)}</text>`;
    });
    const leg = (cls, txt) => `<div><b class="l ${cls}"></b>${txt}</div>`;
    const cl = a.measured_by === "opentherm" ? "lg_cloud_ot" : (a.measured_by === "heating_curve" ? "lg_cloud_curve" : "lg_cloud");
    return `<div class="chart"><svg viewBox="0 0 ${VW} ${VH}">${g}</svg><div class="cleg">` +
      leg("sp", this._ct("lg_adv")) + leg("cneedl", this._ct("lg_need")) + (cloud.length ? leg("ccl", this._ct(cl)) : "") +
      leg("cdashl", this._ct("lg_dash")) + (cyc < X1 ? leg("czl", this._ct("lg_cyc")) : "") + `</div></div>`;
  }

  _curveTable(a) {
    const cur = {};
    (a.current || []).forEach((p) => { cur[p[0]] = p[1]; });
    const hasCur = Object.keys(cur).length > 0, hasMeas = a.points.some((p) => p[2] !== null && p[2] !== undefined);
    const cyc = a.cycling_from;
    const c = (v) => (v === null || v === undefined ? "\u2014" : this._num(v, 1));
    const room = nn(a.room, 20), ua = nn(a.ua_kw, (a.heat_loss_w_per_k || 0) / 1000), k = nn(a.k_kw, (a.emitter_w_per_k || 0) / 1000), n = a.n || 1.1;
    const need = (t) => { const q = ua * (room - t) + nn(a.base_kw, 0); return q > 0 && k > 0 ? room + Math.pow(q / k, 1 / n) : null; };
    const hasNeed = k > 0 && ua > 0;
    const mk = a.measured_by === "opentherm" ? "meas_ot" : (a.measured_by === "heating_curve" ? "meas_curve" : "meas");
    let rows = "";
    a.points.forEach((p) => {
      const inCz = cyc !== null && cyc !== undefined && p[0] > cyc;
      rows += `<tr${inCz ? ' class="cz"' : ""}><td>${this._num(p[0], 0)}\u00b0</td>${hasCur ? `<td>${c(cur[p[0]])}</td>` : ""}` +
        `<td><b>${c(p[1])}</b></td>${hasNeed ? `<td>${need(p[0]) === null ? `<i>${this._ct("none_needed")}</i>` : c(need(p[0]))}</td>` : ""}` +
        `${hasMeas ? `<td>${c(p[2])}</td>` : ""}</tr>`;
    });
    const notes = [this._ct("n_for", { room: this._num(a.room, 1), days: a.days, hours: a.hours })];
    if (a.control === "heating_curve") notes.push(this._ct("n_oncurve"));
    else if (a.control) notes.push(this._ct("n_thermostat"));
    if (!a.reliable) notes.push(this._ct("n_rough"));
    if (cyc !== null && cyc !== undefined) notes.push(this._ct("n_cycles", { t: this._num(cyc, 0) }));
    (a.extrapolated || []).forEach((x) => notes.push(this._ct("n_extra", { x: this._num(x, 0), min: this._num(a.out_min, 1) })));
    if (hasNeed) notes.push(this._ct("n_need"));
    if (hasNeed && a.points.some((p) => need(p[0]) === null)) notes.push(this._ct("n_none"));
    if (hasMeas) notes.push(this._ct(mk === "meas" ? "n_meas" : "n_" + mk));
    notes.push(this._ct("n_set"));
    return `<div class="curve"><table><tr><th>${this._ct("out")}</th>${hasCur ? `<th>${this._ct("now")}</th>` : ""}<th>${this._ct("adv")}</th>` +
      `${hasNeed ? `<th>${this._ct("need")}</th>` : ""}${hasMeas ? `<th>${this._ct(mk)}</th>` : ""}</tr>${rows}</table>` +
      `<ul class="cnote">${notes.map((t) => `<li>${t}</li>`).join("")}</ul></div>`;
  }

  // Extra rooms (radiators upstairs, a bedroom): temperature, minimum and its hours; orange when below it in its hours
  _rooms(list) {
    const chips = list.map((r) => {
      const cold = r.active_now && r.temperature < r.minimum;
      return `<span class="room${cold ? " cold" : ""}" title="${r.from}:00\u2013${r.to}:00"><b>${r.name}</b> ${this._num(r.temperature, 1)}${DEG}` +
        ` \u00b7 ${this._t("min")} ${this._num(r.minimum, 1)} <i>(${r.from}\u2013${r.to})</i></span>`;
    });
    return `<div class="rooms" data-k="rooms">${chips.join("")}</div>`;
  }

  // ---------------------------------------------------------------- v0.9: status lines, pills and their panels
  _esc(s) { return String(s === null || s === undefined ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]); }
  _dur(m) { return m === null || m === undefined ? "\u2014" : (m >= 60 ? `${Math.floor(m / 60)}\u00a0h\u00a0${String(m % 60).padStart(2, "0")}` : `${m}\u00a0min`); }
  _left(iso) {
    const ms = Date.parse(iso) - Date.now();
    return isNaN(ms) ? "\u2014" : this._dur(Math.max(0, Math.round(ms / 60000)));
  }
  _when(iso) { const d = iso ? new Date(iso) : null; return d && !isNaN(d) ? this._hm(d) : "\u2014"; }
  // A line only when something needs attention: amber = Roost works around it, red = it could not do its job.
  // paused / away / a control mismatch show in their pill instead.
  _alerts(a) {
    const list = (a.status || []).filter((s) => s.level === "red" || (s.level === "amber" && s.code !== "control_mismatch"));
    return list.map((s) => {
      const args = s.args || {}, f = { min: nn(args.retry_min, "\u2014"), t: this._when(args.since) };
      return `<div class="alert ${s.level}" role="status" data-k="al-${s.code}"><ha-icon icon="mdi:alert-outline"></ha-icon><span><b>${this._fill("a_" + s.code, f) || s.code}</b> ` +
        `${this._fill("ax_" + s.code, f) || ""}</span></div>`;
    }).join("");
  }
  _ctrlState(a) {
    // what the pump runs on: reported by the pump itself (Weheat), else the user's setting; checked by the steps
    const set = a.control_method || null, det = a.control_detected || "unknown";
    const checkable = set === "heating_curve" || set === "opentherm";
    return { set, det, at: a.control_reported_at || null, mis: !!a.control_mismatch, ok: checkable && set === det, checkable,
      check: a.control_check || {} };
  }
  _savingNow(a) {
    if (a.saving_calc && a.saving_calc.saving !== null && a.saving_calc.saving !== undefined) return a.saving_calc.saving;
    const s = this._sib("saving_next_24h"), v = s ? parseFloat(s.state) : NaN;
    return isNaN(v) ? null : v;
  }
  _pills(a, mode, paused, away, ready, canMode) {
    const pl = (key, cls, inner, label) => `<button class="pl ${cls}${this._open === key ? " on" : ""}" data-open="${key}" aria-expanded="${this._open === key}"` +
      `${label ? ` aria-label="${this._esc(label)}"` : ""}>${inner}</button>`;
    const out = [];
    // mode, with what matters about it: ready / learning, time left of a pause, until when away
    let tag = "", tcls = "";
    if (paused) { tag = this._fill("n_left", { t: this._left(a.paused_until) }); tcls = "amber"; }
    else if (away) { tag = this._fill("n_until", { t: this._when(a.away_until) }); tcls = "info"; }
    else if (mode === "shadow" && ready) { tag = this._t(ready.state === "on" ? "n_ready" : "n_learning"); tcls = ready.state === "on" ? "good" : "mute"; }
    const ml = this._t(paused ? "paused" : (away ? "st_away" : mode));
    out.push(pl("mode", "mode", `<span class="ml">${ml}</span>${tag ? `<span class="tag ${tcls}"><i></i>${tag}</span>` : ""}` +
      (canMode ? `<ha-icon icon="mdi:menu-down"></ha-icon>` : ""), `${ml} ${tag}`));
    // the heat pump now
    const pu = a.pump, miss = (a.status || []).some((s) => s.code === "weheat_missing");
    if (pu || a.pump_runs) {
      let lab, cls;
      if (miss) { lab = `${this._t("n_pump")} \u2014`; cls = "mute"; }
      else if (pu && pu.state === "heating") { lab = `${this._t("n_heating")} ${this._num(pu.supply, 1)}\u00b0 \u2192 ${this._num(pu.return, 1)}\u00b0`; cls = "heat"; }
      else if (pu && pu.state === "hot_water") { lab = this._t("n_hotwater"); cls = "water"; }
      else if (pu && pu.state === "defrost") { lab = this._t("n_defrost"); cls = "water"; }
      else if (pu && pu.state === "idle") { lab = this._t("n_idle") + (pu.last_ran ? ` \u00b7 ${this._fill("n_lastran", { t: this._when(pu.last_ran) })}` : ""); cls = "mute"; }
      else if (pu) { lab = this._esc(pu.raw); cls = "mute"; }
      else { lab = this._t(a.pump_runs.heating ? "n_heating" : "n_idle"); cls = a.pump_runs.heating ? "heat" : "mute"; }
      out.push(pl("pump", "pump " + cls, `<i class="pdot"></i>${lab}`));
    }
    // how the unit is controlled: set, and checked against the data
    const c = this._ctrlState(a);
    if (c.set || c.det !== "unknown") {
      const k = c.set || c.det, name = this._t("cp_" + k) || this._t("c_" + k) || k;
      const mark = c.mis ? " ?" : (c.ok ? " \u2713" : "");
      out.push(pl("ctrl", "ctrl" + (c.mis ? " amber" : ""), `<ha-icon icon="mdi:thermostat"></ha-icon>${name}<b>${mark}</b>`));
    }
    // the heating curve the house needs (Roost's advice), its own pill: the value at 0 degrees outside
    const cs = this._sib("heating_curve");
    if (cs && cs.attributes && cs.attributes.points && cs.attributes.points.length) {
      const v0 = parseFloat(cs.state);
      out.push(pl("curve", "pcurve", `<ha-icon icon="mdi:chart-bell-curve-cumulative"></ha-icon>${this._t("n_curve")}` +
        `${isNaN(v0) ? "" : ` <b>${this._fill("n_curve_at", { v: this._num(v0, 1) + "\u00b0" })}</b>`}`));
    }
    // the expected saving of the next 24 hours (unknown: a dash, never 0)
    const sv = this._savingNow(a);
    if (sv !== null || this._sib("saving_next_24h") || a.saving_calc !== undefined) {
      // unknown is said in words: a lone dash read as "saves nothing"; a negative saving is a plan that costs more
      out.push(pl("saving", "saving", sv === null ? `<span class="mute">${this._t("n_sav_unknown")}</span>` :
        `${this._t(sv < 0 ? "n_costs" : "n_saves")} <b class="${sv < 0 ? "bad" : "good"}">${this._money(Math.abs(sv))}</b>`));
    }
    return `<div class="pills" data-k="pills">${out.join("")}</div>`;
  }
  _panel(a, mode, paused, away, ready, canMode) {
    const html = this._panelHtml(a, mode, paused, away, ready, canMode);
    return html ? html.replace(/^<div class="/, `<div data-k="panel-${this._open}" class="`) : "";
  }
  _panelHtml(a, mode, paused, away, ready, canMode) {
    const o = this._open;
    if (o === "mode" && canMode) {
      const rb = mode === "shadow" && ready && ready.state === "on" ?
        `<div class="readyb"><span><b>${this._t("n_ready_t")}</b> ${this._t("n_ready_x")}</span><button class="steer">${this._t(this._armed === "steer" ? "sure" : "steer")}</button></div>` : "";
      return `<div class="panel">${rb}${this._modeMenu(mode, paused, away, a)}${this._etaLine(a)}</div>`;
    }
    if (o === "pump") return this._pumpPanel(a);
    if (o === "ctrl") return this._ctrlPanel(a);
    if (o === "saving") return this._savingPanel(a);
    if (o === "curve") return `<div class="panel">${this._curveView()}</div>`;
    if (o === "settings") return this._settingsAll(a);
    return "";
  }
  _etaLine(a) {
    const ready = this._sib("ready");
    const code = ready && ready.state !== "on" && a.mode === "shadow" ? ready.attributes.waiting_for : null;
    const eta = code ? (this._t("eta") || {})[code] : null;
    if (!eta) return "";
    const when = ready.attributes.expected ? new Date(ready.attributes.expected) : null;
    return `<div class="pline">${this._t("ready")}: ${eta}${when && !isNaN(when) ? ` ~${this._hm(when)}` : ""}</div>`;
  }
  _pumpPanel(a) {
    const pu = a.pump, r = a.pump_runs || {}, t = r.today || {}, y = r.yesterday || {}, cost = this._sib("cost_today");
    const box = (l, v, s, cls) => `<div class="bx"><div class="bl">${l}</div><div class="bv ${cls || ""}">${v}</div><div class="bs">${s}</div></div>`;
    const deg = (v) => (v === null || v === undefined ? "\u2014" : `${this._num(v, 1)}\u00b0`);
    let html = "";
    if (pu) {
      const above = pu.supply !== null && pu.supply !== undefined && pu.requested !== null && pu.requested !== undefined ? pu.supply - pu.requested : null;
      html += `<div class="bx4">` +
        box(this._t("n_requested"), deg(pu.requested), a.opentherm ? this._ot("req_by") : this._t("n_req_by")) +
        box(this._t("n_supply"), deg(pu.supply), above === null ? "" : this._fill(above >= 0 ? "n_above_req" : "n_below_req", { d: (above >= 0 ? "+" : "") + this._num(Math.abs(above), 1) }), "heat") +
        box(this._t("n_return"), deg(pu.return), this._t("n_back"), "water") +
        box(this._t("n_dt"), pu.delta_t === null || pu.delta_t === undefined ? "\u2014" : `${this._num(pu.delta_t, 1)} K`,
          pu.supply !== null && pu.return !== null && pu.supply !== undefined ? `${this._num(pu.supply, 1)} \u2212 ${this._num(pu.return, 1)}` : "") + `</div>`;
      if (pu.in_kw !== null && pu.in_kw !== undefined) {
        html += `<div class="pline">${this._fill("n_power", { i: `<b>${this._num(pu.in_kw * 1000, 0)} W</b>`, o: `<b>${this._num(pu.out_kw, 2)} kW</b>` })}` +
          `${pu.cop !== null && pu.cop !== undefined ? ` (COP ${this._num(pu.cop, 1)})` : ""}</div>`;
      }
    }
    html += `<div class="bx3">` +
      `<div><div class="bl">${this._t("n_today")}</div><div class="bm">${this._fill("n_runs", { n: nn(t.starts, 0), m: this._dur(t.minutes) })}` +
      `</div>${cost && !isNaN(parseFloat(cost.state)) ? `<div class="bs">${this._et("cost_today")} ${this._money(parseFloat(cost.state))}</div>` : ""}</div>` +
      `<div><div class="bl">${this._t("n_yday")}</div><div class="bm">${this._fill("n_runs", { n: nn(y.starts, "\u2014"), m: this._dur(y.minutes) })}</div></div>` +
      `<div><div class="bl">${this._t("n_planned24")}</div><div class="bm">${a.kwh_24h === null || a.kwh_24h === undefined ? "\u2014" : this._num(a.kwh_24h, 1) + " kWh"}</div></div></div>`;
    return `<div class="panel heat">${html}</div>`;
  }
  _ctrlPanel(a) {
    const c = this._ctrlState(a), ch = c.check || {};
    const nm = (k) => this._t("c_" + k) || k;
    let head, line, cls = "info", icon = "mdi:check";
    if (c.mis) {
      cls = "amber"; icon = "mdi:alert-outline";
      head = this._fill("c_mis_head", { s: nm(c.set), d: nm(c.det).toLowerCase() });
      line = this._fill("c_mis_line", { n: nn(ch.steps, "\u2014"), how: this._t(c.det === "opentherm" ? "c_followed" : "c_notfollowed") });
    } else {
      const k = c.set || c.det;
      head = `${nm(k)} <span class="mute">${c.ok ? "\u00b7 " + this._fill("c_checked", { d: nn(ch.days, 7) }) : ""}</span>`;
      line = this._t("cl_" + k) || "";
      if (!c.ok) { icon = "mdi:help-circle-outline"; line += " " + (!c.checkable ? this._t("c_nocheck") : this._fill("c_unknown", { n: nn(ch.steps, 0) })); }
    }
    if (c.set) line += ` <span class="mute">(${this._fill("c_weheat_at", { t: this._when(c.at) })})</span>`;
    // only the Weheat app changes it: no buttons here, just where to do it
    return `<div class="panel ${cls}"><div class="prow"><ha-icon icon="${icon}"></ha-icon><div class="phead">${head}</div></div>` +
      `<div class="pline">${line}</div>${c.mis ? `<div class="pline">${this._t("c_app")}</div>` : ""}</div>`;
  }
  _savingPanel(a) {
    const sc = a.saving_calc, s24 = this._sib("saving_next_24h");
    let html = "";
    if (sc) {
      const endv = sc.saving - (sc.steady - sc.plan);
      const row = (l, v, cls) => `<span class="${cls || ""}">${l}</span><span class="r ${cls || ""}">${v}</span>`;
      html += `<div class="pline">${this._t("sv_intro")}</div><div class="calc">` +
        row(this._t("sv_steady"), this._money(sc.steady)) + row(this._t("sv_plan"), this._money(sc.plan)) +
        row(this._t("sv_end"), (endv >= 0 ? "+" : "\u2212") + this._money(Math.abs(endv))) +
        row(this._t("sv_total"), this._money(sc.saving), "tot " + (sc.saving < 0 ? "bad" : "good")) + `</div>`;
    } else if (s24) {
      html += `<div class="pline">${this._savingQuality(s24.attributes && s24.attributes.quality) || this._t("sv_total") + ": \u2014"}</div>`;
    }
    const sm = this._sib("saving_month"), sy = this._sib("saving_yesterday"), bits = [];
    if (sm) {
      const at = sm.attributes || {}, v = parseFloat(sm.state), inc = (at.included_days || []).length;
      bits.push(`${this._t("sv_month")} <b class="${isNaN(v) ? "" : (v < 0 ? "bad" : "good")}">${isNaN(v) ? "\u2014" : this._money(v)}</b>` +
        ` <button class="chip calpill${this._calOpen ? " on" : ""}"><ha-icon icon="mdi:calendar-check"></ha-icon>${inc}/${nn(at.days_expected, inc)} ${this._t("sv_days")}</button>` +
        (at.partial ? ` <small class="mute">${this._t("sv_partial")}</small>` : ""));
    }
    if (sy && !isNaN(parseFloat(sy.state))) bits.push(`${this._t("sv_yday")} <b>${this._money(parseFloat(sy.state))}</b>`);
    else if (sy) bits.push(`${this._t("sv_yday")} <b>\u2014</b> <small class="mute">${this._t("sv_unsure")}</small>`);
    if (bits.length) html += `<div class="pline">${bits.join(" \u00b7 ")}</div>`;
    if (sm) html += this._savingParts(sm.attributes || {}, parseFloat(sm.state));
    if (this._calOpen) html += this._calendar();
    return `<div class="panel good">${html}</div>`;
  }
  // The month in three parts: two measured (no model), one worked out with the model (with how far it may be off)
  _savingParts(at, model) {
    const m = at.measured, t = (k) => this._sv(k);
    const row = (label, val, cls, sub) => `<div class="svr"><span>${label}${sub ? `<small>${sub}</small>` : ""}</span><b class="${cls || ""}">${val}</b></div>`;
    let h = `<div class="sec">${t("parts")}</div><div class="svp">`;
    if (m && m.kwh > 0) {
      h += row(t("timing"), (m.timing >= 0 ? "" : "\u2212") + this._money(Math.abs(m.timing)), m.timing >= 0 ? "good" : "bad",
        t("timing_sub").replace("{p}", this._num(m.ct_paid, 1)).replace("{f}", this._num(m.ct_flat, 1)));
      if (m.sun_kwh > 0.05) h += row(t("sun"), this._num(m.sun_kwh, 1) + " kWh" + (m.sun_value > 0.005 ? ` \u00b7 ${this._money(m.sun_value)}` : ""), "",
        m.sun_value > 0.005 ? t("sun_sub") : t("sun_net"));
      if (m.bat_kwh > 0.05) h += row(t("battery"), this._num(m.bat_kwh, 1) + " kWh" + (m.bat_value > 0.005 ? ` \u00b7 ${this._money(m.bat_value)}` : ""), "", t("bat_sub"));
    } else h += `<div class="pline">${t("no_meas")}</div>`;
    if (!isNaN(model)) {
      const band = at.model_band, pm = band !== null && band !== undefined && m ? Math.abs(m.paid || 0) * band : null;
      const shadow = (at.shadow_days || []).length;
      h += row(t(shadow ? "model_shadow" : "model"), this._money(model) + (pm !== null ? ` \u00b1 ${this._money(pm)}` : ""), model >= 0 ? "good" : "bad",
        t("model_sub"));
    }
    return h + `<div class="pline note">${t("how")}</div></div>`;
  }
  _sv(k) { const own = (SV_T[this._lang()] || SV_T.en)[k]; return own === undefined ? SV_T.en[k] : own; }

  _settingsAll(a) {
    const c = this._ctrlState(a);
    // how the pump is controlled: as it reports it; only the Weheat app changes it
    const ctrl = `<div class="sec">${this._t("c_title")}</div>` + (c.set ?
      `<div class="pline"><b>${this._t("c_" + c.set) || this._esc(c.set)}</b> \u00b7 ${this._fill("c_weheat_at", { t: this._when(c.at) })}</div>` :
      `<div class="pline">${this._t("c_noreport")}</div>`) + `<div class="pline mute">${this._t("c_app")}</div>`;
    const sensors = `<div class="sec">${this._t("n_sensors_t")}</div><div class="pline">${this._t(a.pump ? "n_sensors_ok" : "n_sensors_none")}</div>`;
    const conf = `<div class="prow sep"><span class="pline grow">${this._t("n_configure")}</span><button class="pbtn ghost week-settings">${this._t("n_open")}</button></div>`;
    return `<div class="panel set"><div class="prow"><div class="phead big">${this._t("n_settings")}</div><button class="pbtn" data-open="settings">${this._t("n_done")}</button></div>` +
      `<div class="sec">${this._t("s_comfort_t")}</div>${this._settingsPanel(a)}${ctrl}${sensors}${conf}</div>`;
  }
  _hourPanel(a) {
    const i = this._sel;
    if (i === null || i === undefined || !a.plan || !a.plan[i]) return "";
    const p = a.plan[i], why = (a.plan_why || [])[i], k = cat(why && why[0]);
    const t = i === 0 ? this._t("now") : this._hour(new Date((a.start ? Date.parse(a.start) : Date.now()) + i * 3600000));
    const tariff = nn(p[4], p[3]);
    return `<div class="hpanel" data-k="hpanel"><div class="prow"><div class="phead">${t} \u00b7 <span class="k-${k}">${this._t("gl_" + k)}</span></div>` +
      `<button class="pbtn round" data-hclose="1" aria-label="${this._t("h_close")}">\u00d7</button></div>` +
      `<div class="pline strong">${why ? this._why(why[0], why[1], "") : ""}</div><div class="pline">` +
      [`${a.opentherm ? this._ot("flow") : this._t("setpoint")} <b class="o">${a.opentherm && !(p[0] > 0) ? this._ot("off") : this._num(p[0], 1) + "\u00b0"}</b>`, `${this._t("expected")} <b>${this._num(p[1], 1)}\u00b0</b>`,
        this._fill("h_pumpk", { k: `<b>${this._num(p[2], 2)}</b>` }), this._fill("h_counts", { c: `<b>${this._num(p[3], 1)}</b>` }) +
        (Math.abs(p[3] - tariff) >= 0.5 ? ` (${this._fill("h_tariff", { t: this._num(tariff, 1) })})` : ""),
        this._fill("h_costs", { e: `<b>${this._money((p[2] || 0) * p[3] / 100)}</b>` })].join(" \u00b7 ") + `</div>` +
      ((a.defrost_min || [])[i] >= 1 ? `<div class="pline">\u2744 ${this._fill("df_exp", { m: a.defrost_min[i] })}</div>` : "") + `</div>`;
  }

  // ---------------------------------------------------------------- v0.8.0: status line, tiles, pump runs, calendar
  _fill(k, args) {
    let t = this._t(k) || "";
    Object.keys(args || {}).forEach((a) => { t = t.replace("{" + a + "}", args[a]); });
    return t;
  }
  _clock(min) { return `${String(Math.floor(min / 60) % 24).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`; }
  _nextChange(a) {
    const p = a.plan;
    if (!p || !p.length) return null;
    const i = p.findIndex((x, j) => j > 0 && Math.abs(x[0] - p[0][0]) >= 0.25);
    if (i <= 0) return null;
    const t0 = a.start ? new Date(a.start).getTime() : Date.now();
    return { t: new Date(t0 + i * 3600000), sp: p[i][0], up: p[i][0] > p[0][0] };
  }
  // The room the last hours (measured) and the next six (expected), a small line in the room tile
  _spark(a) {
    const past = (a.room_recent || []).map((r) => r[1]);
    const ahead = (a.plan || []).slice(0, 6).map((p) => p[1]);
    const now = nn(a.room, past.length ? past[past.length - 1] : null);
    if (now === null || (!past.length && !ahead.length)) return "";
    const pts = past.concat([now]), fut = [now].concat(ahead), all = pts.concat(fut);
    const lo = Math.min.apply(null, all) - 0.1, hi = Math.max.apply(null, all) + 0.1, W = 120, H = 24, n = pts.length + fut.length - 2;
    const X = (i) => (i / Math.max(1, n) * W).toFixed(1), Y = (v) => (H - 2 - (v - lo) / Math.max(0.2, hi - lo) * (H - 4)).toFixed(1);
    const p1 = pts.map((v, i) => `${i ? "L" : "M"}${X(i)} ${Y(v)}`).join(" ");
    const o = pts.length - 1, p2 = fut.map((v, i) => `${i ? "L" : "M"}${X(o + i)} ${Y(v)}`).join(" ");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${p1}" class="sp1"/><path d="${p2}" class="sp2"/>` +
      `<line x1="${X(o)}" x2="${X(o)}" y1="0" y2="${H}" class="spn"/></svg>`;
  }
  // Under "Roost asks": while Roost only looks along, what the master's own curve asks now (the comparison the shadow
  // days are for), and the flow the unit makes
  _otNow(a, asked) {
    const o = a.opentherm;
    if (o.hot_water) return this._ot("dhw");
    // Roost asks other than the plan's flow for this hour: its correction within the hour on the heat the unit makes
    const plan = a.plan && a.plan[0] ? a.plan[0][0] : null;
    const trim = a.mode === "active" && asked > 0 && plan > 0 && Math.abs(asked - plan) >= 0.25 && typeof o.level === "number" &&
      a.pump && typeof a.pump.out_kw === "number" ? this._ot("trim").replace("{p}", this._num(plan, 1) + "\u00b0")
        .replace("{d}", (asked > plan ? "+" : "\u2212") + this._num(Math.abs(asked - plan), 1) + "\u00b0")
        .replace("{m}", this._num(a.pump.out_kw, 1)).replace("{l}", this._num(o.level, 1)) : "";
    const ce = o.curve_flow_entity && this._hass.states[o.curve_flow_entity], cv = ce ? parseFloat(ce.state) : o.curve_flow;
    const box = a.mode !== "active" && typeof cv === "number" && !isNaN(cv) ? this._ot("box").replace("{v}", this._num(cv, 1) + "\u00b0") : "";
    // the unit's COP now (its own power meters, as in the pump detail): only while it heats
    const cop = a.pump && typeof a.pump.cop === "number" ? `, COP ${this._num(a.pump.cop, 1)}` : "";
    const pump = o.flow_now === null || o.flow_now === undefined ? "" : this._ot("now").replace("{v}", this._num(o.flow_now, 1) + "\u00b0") + cop;
    return [trim, box, pump].filter(Boolean).join(" \u00b7 ");
  }
  _tiles(st, a) {
    const nx = this._nextChange(a), r6 = a.plan && a.plan[6] ? a.plan[6][1] : null;
    const warm = a.room !== null && a.room !== undefined && a.comfort !== undefined ? (a.room >= a.comfort ? "warm" : "cool") : "";
    let nxt = `<div class="tv">\u2014</div><div class="ts">${this._t("n_nochange")}</div>`;
    if (nx) {
      const i = Math.round((nx.t.getTime() - (a.start ? Date.parse(a.start) : Date.now())) / 3600000), w = (a.plan_why || [])[i];
      nxt = `<div class="tv">${a.opentherm && !(nx.sp > 0) ? this._ot("off") : `${a.opentherm ? `<small>${this._ot("flow_word")}</small> ` : ""}${this._num(nx.sp, 1)}<span>${DEG}</span>`}</div><div class="ts">${this._fill("n_from", { t: this._hour(nx.t) })}` +
        `${w ? " \u00b7 " + this._t("gl_" + cat(w[0])) : ""}</div>`;
    }
    return `<div class="tiles" data-k="tiles">
      <div class="tile rtile ${warm}"><div class="tl"><ha-icon icon="mdi:home-thermometer-outline"></ha-icon>${this._t("room")}</div>
        <div class="tv big">${this._num(a.room, 1)}<span>${DEG}</span></div>${this._spark(a)}
        <div class="ts">${r6 === null ? `${this._t("stored")} ${fmt(a.storage_kwh, 1)} kWh` : this._fill("n_in6", { v: this._num(r6, 1) + "\u00b0" })}</div></div>
      ${a.opentherm ? `<div class="tile plan therm nolink"><div class="tl"><ha-icon icon="mdi:bird"></ha-icon>${this._ot("sets")}</div>
        <div class="tv big">${parseFloat(st.state) > 0 ? `${this._num(parseFloat(st.state), 1)}<span>${DEG}</span>` : this._ot("off")}</div>
        ${this._otNow(a, parseFloat(st.state)).split(" \u00b7 ").map((x) => `<div class="ts">${x}</div>`).join("")}</div>` :
      `<div class="tile plan therm${a.thermostat_entity ? "" : " nolink"}"><div class="tl"><ha-icon icon="mdi:bird"></ha-icon>${this._t("n_sets")}</div>
        <div class="tv big">${this._num(parseFloat(st.state), 1)}<span>${DEG}</span></div>
        <div class="ts">${this._fill("n_therm_now", { v: this._num(a.thermostat, 1) + "\u00b0" })}</div></div>`}
      <div class="tile nxt"><div class="tl"><ha-icon icon="mdi:clock-outline"></ha-icon>${this._t("n_next")}</div>${nxt}</div>
    </div>`;
  }
  // One dot per day of the month: counted, not counted (tap for why), no data
  _calendar() {
    const sm = this._sib("saving_month");
    if (!sm) return "";
    const at = sm.attributes || {}, inc = at.included_days || [], exc = at.excluded_days || [], reasons = at.day_reasons || {};
    const today = new Date(), y = today.getFullYear(), m = today.getMonth(), days = new Date(y, m + 1, 0).getDate();
    const lang = String(this._locale()).split("-")[0], q = SAVING_QUALITY[lang] || SAVING_QUALITY.en;
    const names = this._t("w_days").split(",");
    let cells = names.map((d) => `<span class="cwd">${d}</span>`).join("");
    for (let i = 0, lead = (new Date(y, m, 1).getDay() + 6) % 7; i < lead; i++) cells += "<span></span>";
    for (let d = 1; d <= days; d++) {
      const key = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const cls = inc.indexOf(key) >= 0 ? "ok" : (exc.indexOf(key) >= 0 ? "bad" : (d >= today.getDate() ? "future" : "none"));
      const why = cls === "bad" ? (reasons[key] || []).map((r) => q[r] || r).join(" ") : "";
      const sel = this._calDay && this._calDay.day === key ? " sel" : "";
      cells += `<span class="cd ${cls}${sel}" data-day="${key}" data-why="${why.replace(/"/g, "&quot;")}">${d}</span>`;
    }
    const pick = this._calDay ? `<div class="cwhy"><b>${this._calDay.day.slice(8)}</b> \u00b7 ${this._calDay.why || this._t("cal_bad")}</div>` : "";
    const hint = inc.length ? "" : `<div class="cwhy">${this._t("cal_hint")}</div>`;
    return `<div class="cal"><div class="ch"><span>${this._t("cal_title")}</span></div><div class="cgrid">${cells}</div>` +
      `<div class="calleg"><span><i class="ok"></i>${this._t("cal_ok")}</span><span><i class="bad"></i>${this._t("cal_bad")}</span>` +
      `<span><i class="none"></i>${this._t("cal_none")}</span></div>${pick}${hint}</div>`;
  }
  // ---------------------------------------------------------------- the weekly comfort periods, edited in the card
  _weekDraft(a) {
    if (!this._wk) {
      const src = a.comfort_week || {}, from = nn(a.day_from, 7) * 60, to = nn(a.day_to, 22) * 60;
      this._wk = {};
      WEEKDAYS.forEach((d) => {
        const v = src[d];
        this._wk[d] = Array.isArray(v) ? v.map((p) => [p[0], p[1]]) : (a.comfort_week ? [] : [[from, to]]);
      });
      this._wkDay = nn(this._wkDay, (new Date().getDay() + 6) % 7);
    }
    return this._wk;
  }
  _weekEditor(a) {
    const on = !!a.weekly_comfort, wk = this._weekDraft(a), names = this._t("w_days").split(",");
    const seg = (s, e, cls) => `<i class="${cls}" style="left:${(s / 14.4).toFixed(2)}%;width:${((e - s) / 14.4).toFixed(2)}%"></i>`;
    let rows = "";
    WEEKDAYS.forEach((d, i) => {
      let bars = "";
      wk[d].forEach((p) => { bars += p[1] > p[0] ? seg(p[0], p[1], "blk") : seg(p[0], 1440, "blk"); });
      wk[WEEKDAYS[(i + 6) % 7]].forEach((p) => { if (p[1] < p[0] && p[1] > 0) bars += seg(0, p[1], "blk over"); });
      rows += `<div class="wrow${i === this._wkDay ? " sel" : ""}" data-wd="${i}"><span>${names[i]}</span><div class="wbar">${bars}</div></div>`;
    });
    const day = WEEKDAYS[this._wkDay], list = wk[day];
    // the times typed (a time field: the phone's own wheel), in quarter hours; an end at midnight shows as 00:00
    const tf = (j, k, m) => `<input class="tm" type="time" step="900" data-wt="${j}:${k}" value="${this._clock(m % 1440)}" aria-label="${this._t("w_title")}">`;
    let edit = list.map((p, j) => `<div class="wper" data-k="wp-${this._wkDay}-${j}">${tf(j, 0, p[0])} \u2013 ${tf(j, 1, p[1])}` +
      `<button class="mini del" data-wdel="${j}" title="${this._t("w_del")}" aria-label="${this._t("w_del")}">\u00d7</button></div>`).join("");
    if (!list.length) edit = `<div class="ts">${this._t("w_empty")}</div>`;
    const msg = this._wkMsg ? `<div class="wmsg ${this._wkMsg.ok ? "ok" : "err"}">${this._wkMsg.text}</div>` : "";
    return `<div class="week"><div class="srow"><span>${this._t("w_title")}</span><span class="wtog">` +
      `<button class="mini${on ? "" : " on"}" data-wmode="0">${this._t("w_off")}</button><button class="mini${on ? " on" : ""}" data-wmode="1">${this._t("w_on")}</button></span></div>` +
      (on || this._wkOpen ? `<div class="wgrid">${rows}<div class="waxis"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div></div>` +
        `<div class="wedit"><div class="ts">${this._t("w_tap")}</div><div class="wday">${names[this._wkDay]}</div>${edit}` +
        `<div class="wbtns"><button class="mini" data-wadd="1">${this._t("w_add")}</button><button class="mini" data-wcopy="wd">${this._t("w_copy_wd")}</button>` +
        `<button class="mini" data-wcopy="we">${this._t("w_copy_we")}</button><button class="mini" data-wcopy="all">${this._t("w_copy_all")}</button>` +
        `<button class="mini save" data-wsave="1">${this._t("w_save")}</button></div>${msg}</div>` : "") + `</div>`;
  }
  _saveWeek(data) {
    const done = (ok, e) => { this._wkMsg = { ok, text: ok ? this._t("w_saved") : this._fill("w_err", { e: (e && e.message) || e || "" }) }; this._render(); };
    Promise.resolve(this._hass.callService("roost", "set_settings", data)).then(() => { this._wk = null; this._wkOpen = false; done(true); }, (e) => done(false, e));
  }

  _chart(a) {
    const plan = a.plan, n = plan.length;
    // bars: the price Roost counts (p[3]: the tariff, lower where own solar or the battery covers it; the tariff p[4] is in
    // the hour panel), coloured by what the planner does that hour; p[5] = 1: not known yet, guessed
    const sp = plan.map((p) => p[0]), kt = plan.map((p) => p[1]), pr = plan.map((p) => p[3]);
    const cats = plan.map((p, i) => cat(((a.plan_why || [])[i] || [])[0]));
    const guess = plan.map((p) => !!p[5]);
    const day = a.day_hours || plan.map(() => 1);
    const start = a.start ? new Date(a.start) : new Date();
    // one unit is one pixel of the card (fixed text size, a height that does not grow with a wide dashboard)
    const VW = Math.max(300, Math.min(1600, (this._chartW || 472) - 32)), VH = 172, L = 28, R = 6, TOP = 8, B = 46, PB = 26, w = (VW - L - R) / n;
    const ot = !!a.opentherm;
    const vals = (ot ? kt : sp.concat(kt)).filter((v) => !isNaN(v));
    const lo = Math.min(nn(a.night_min, 19) - 0.5, Math.floor(Math.min.apply(null, vals) - 0.3));
    const hi = Math.max(nn(a.store_max, 22.5) + 0.3, Math.ceil(Math.max.apply(null, vals) + 0.3));
    const y = (v) => TOP + (hi - v) / (hi - lo) * (VH - TOP - B), x = (i) => L + i * w;
    // OpenTherm: the flow on its own scale (labels on the right). Off is no temperature: a hatched column and a gap in
    // the line, not a line at the bottom (which read as "very low")
    const on = sp.filter((v) => v > 0), flo = on.length ? Math.floor(Math.min.apply(null, on) - 3) : 20,
      fhi = on.length ? Math.ceil(Math.max.apply(null, on) + 2) : 35;
    const yf = (v) => TOP + (fhi - v) / Math.max(1, fhi - flo) * (VH - TOP - B);
    const ys = ot ? yf : y, off = (v) => ot && !(v > 0);
    const pmin = Math.min.apply(null, pr), pmax = Math.max.apply(null, pr), pb = VH - 18;
    const tone = (p) => { const r = (p - pmin) / Math.max(0.01, pmax - pmin); return r < 0.33 ? "var(--rc-cheap)" : (r < 0.66 ? "var(--rc-mid)" : "var(--rc-dear)"); };
    let g = "";
    const cl = nn(a.day_min, 20), ch = nn(a.comfort, 20.5);
    for (let i = 0; i < n; i++) {
      const mask = a.comfort_masks && a.comfort_masks[i];
      if (mask) {
        for (let q = 0; q < 4; q++) if (mask[q]) g += `<rect x="${(x(i) + q * w / 4).toFixed(1)}" y="${y(ch).toFixed(1)}" width="${(w / 4 + 0.2).toFixed(1)}" height="${Math.max(1, y(cl) - y(ch)).toFixed(1)}" class="band"/>`;
      } else if (day[i]) g += `<rect x="${x(i).toFixed(1)}" y="${y(ch).toFixed(1)}" width="${(w + 0.2).toFixed(1)}" height="${Math.max(1, y(cl) - y(ch)).toFixed(1)}" class="band"/>`;
    }
    const ystep = Math.max(1, Math.ceil((hi - lo) / 6));        // at most ~6 labels: never a pile of them
    for (let v = Math.ceil(lo); v <= hi; v += ystep) {
      g += `<line x1="${L}" x2="${VW - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/>` +
        `<text x="${L - 5}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis">${v}\u00b0</text>`;
    }
    if (ot) {
      const fstep = Math.max(1, Math.ceil((fhi - flo) / 4));
      for (let v = Math.ceil(flo / fstep) * fstep; v <= fhi; v += fstep)
        g += `<text x="${VW - R - 2}" y="${(yf(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis faxis">${v}\u00b0</text>`;
    }
    // defrosting expected: one snowflake per defrost (its minutes added up hour by hour, a flake each time they make
    // one defrost of ~defrost_each_min), not one per hour with a few minutes: 56 minutes in a night is about 3 defrosts
    const dfm = a.defrost_min || [], each = nn(a.defrost_each_min, 17), dfi = [];
    let dfacc = each / 2;
    dfm.forEach((m, i) => { dfacc += m; if (dfacc >= each && i < n) { dfi.push(i); dfacc -= each; } });
    dfi.forEach((i) => {
      g += `<text x="${(x(i) + w / 2).toFixed(1)}" y="${TOP + 9}" text-anchor="middle" class="dfm"><title>${this._t("df_one")}</title>\u2744</text>`;
    });
    const own = a.own_kw || [], omax = Math.max(1, Math.max.apply(null, own.concat([0])));
    own.forEach((o, i) => {          // own solar to use: a yellow wash behind the price bars
      if (o > 0.05 && i < n) g += `<rect x="${x(i).toFixed(1)}" y="${(pb - o / omax * PB).toFixed(1)}" width="${(w + 0.2).toFixed(1)}" height="${(o / omax * PB).toFixed(1)}" class="sun"/>`;
    });
    pr.forEach((p, i) => {
      const r = (p - pmin) / Math.max(0.01, pmax - pmin), hgt = 4 + r * (PB - 8);
      g += `<rect x="${(x(i) + 1).toFixed(1)}" y="${(pb - hgt).toFixed(1)}" width="${(w - 2).toFixed(1)}" height="${hgt.toFixed(1)}" rx="1.5" class="price k-${cats[i]}${guess[i] ? " guess" : ""}${i === this._sel ? " sel" : ""}"/>`;
    });
    if (ot) sp.forEach((v, i) => { if (off(v)) g += `<rect x="${x(i).toFixed(1)}" y="${TOP}" width="${(w + 0.2).toFixed(1)}" height="${(VH - B - TOP).toFixed(1)}" class="offcol"/>`; });
    if (this._sel !== null && this._sel !== undefined && this._sel < n) g = `<rect x="${x(this._sel).toFixed(1)}" y="${TOP}" width="${w.toFixed(1)}" height="${(pb - TOP).toFixed(1)}" class="selcol"/>` + g;
    let d = "";
    sp.forEach((v, i) => {
      if (off(v)) return;
      d += `${i && !off(sp[i - 1]) ? " L" : " M"}${x(i).toFixed(1)} ${ys(v).toFixed(1)} L${x(i + 1).toFixed(1)} ${ys(v).toFixed(1)}`;
    });
    let k = "";
    kt.forEach((v, i) => { k += `${i ? " L" : "M"}${(x(i) + w / 2).toFixed(1)} ${y(v).toFixed(1)}`; });
    const area = `${k} L${(x(n - 1) + w / 2).toFixed(1)} ${VH - B} L${(x(0) + w / 2).toFixed(1)} ${VH - B} Z`;
    g = `<path d="${area}" class="area"/>` + g + `<path d="${d}" class="sp"/><path d="${k}" class="room"/>` +
      `<line x1="${x(0).toFixed(1)}" x2="${x(0).toFixed(1)}" y1="${TOP}" y2="${pb}" class="nowl"/>`;
    for (let i = 0; i <= n; i += 6) {
      const t = new Date(start.getTime() + i * 3600000);
      g += `<text x="${x(i).toFixed(1)}" y="${VH - 4}" text-anchor="${i === 0 ? "start" : (i === n ? "end" : "middle")}" class="axis${i === 0 ? " nowt" : ""}">${i === 0 ? this._t("now") : this._hour(t)}</text>`;
    }
    g += `<line class="cur" x1="0" x2="0" y1="${TOP}" y2="${pb}"/><circle class="dot2" r="3.5"/><circle class="dot" r="4"/>` +
      `<rect class="hit" x="${L}" y="${TOP}" width="${VW - L - R}" height="${pb - TOP}"/>`;
    this._geo = { n, L, w, ot, sp: sp.map((v) => (off(v) ? null : ys(v))), kt: kt.map((v) => y(v)), start: start.getTime(), plan, day, why: a.plan_why || [] };
    // under the graph, on the bars' columns: what Roost does per block of hours, then comfort / night
    const runs = (arr) => { const o = []; arr.forEach((v, i) => { const r = o[o.length - 1]; if (r && r.v === v) r.n++; else o.push({ v, s: i, n: 1 }); }); return o; };
    const lm = (L / VW * 100).toFixed(2), rm = (R / VW * 100).toFixed(2), cols = `grid-template-columns:repeat(${n},minmax(0,1fr));margin-left:${lm}%;margin-right:${rm}%`;
    const fits = (r, text) => r.n * w >= String(text).length * 6.5 + 6;      // ~6.5 px per letter at 11 px
    const glab = runs(cats).map((r) => { const t = this._t("g_" + r.v); return `<span class="k-${r.v}" style="grid-column:${r.s + 1} / span ${r.n}">${fits(r, t) ? t : ""}</span>`; }).join("");
    const dlab = runs(day.map((d) => (d ? 1 : 0))).map((r) => { const t = this._t(r.v ? "g_comfort" : "night"); return `<span class="${r.v ? "dc" : "dn"}" style="grid-column:${r.s + 1} / span ${r.n}">${fits(r, t) ? t : ""}</span>`; }).join("");
    const acc = this._sib("plan_accuracy"), av = acc ? parseFloat(acc.state) : NaN;
    const legx = this._legOpen ? `<div class="legx">${["store", "hold", "coast", "skip"].map((k) => `<span><b class="k-${k}">${this._t("gl_" + k)}</b>: ${this._t("gx_" + k)}</span>`).join("")}` +
      `<span>${this._t("gx_bars")}</span></div>` : "";
    return `<div class="chart" data-k="chart"><div class="ch"><span>${this._t("next24")}</span><span class="info">${this._info(0)} \u00b7 <i>${this._t("scrub")}</i></span></div>
      <svg viewBox="0 0 ${VW} ${VH}">${g}</svg><div class="glab" style="${cols}">${glab}</div><div class="dstrip" style="${cols}">${dlab}</div>
      <div class="leg"><span><b class="l sp"></b>${ot ? this._ot("flow_axis") : this._t("setpoint")}</span>${ot && sp.some(off) ? `<span><b class="l offcol"></b>${this._ot("off")}</span>` : ""}<span><b class="l room"></b>${this._t("expected")}</span>
      <span>${this._fill("g_bars", { r: `${Math.round(pmin)}\u2013${Math.round(pmax)}` })}</span>${guess.some((q) => q) ? `<span><b class="l price guess"></b>${this._t("guessed")}</span>` : ""}` +
      `${own.some((o) => o > 0.05) ? `<span><b class="l sun"></b>${this._t("pr_sun")}</span>` : ""}` +
      `${isNaN(av) ? "" : `<span class="accp">${this._fill("g_acc", { v: this._num(av, 2) })}</span>`}` +
      `${dfi.length ? `<span><b class="dfm">\u2744</b> ${this._t("df_leg")}</span>` : ""}` +
      `<button class="qbtn" aria-label="${this._t("g_explain")}" aria-expanded="${!!this._legOpen}">?</button></div>${legx}` +
      `${(a.defrost_seen || []).length ? `<div class="pline mute dfseen">\u2744 ${this._fill("df_seen", { l: a.defrost_seen.map((d) => `${this._hour(new Date(d[0]))} ${d[1]} min`).join(", ") })}</div>` : ""}</div>`;
  }

  _info(i) {
    const p = this._geo && this._geo.plan[i];
    if (!p) return "";
    const t = i === 0 ? this._t("now") : this._hour(new Date(this._geo.start + i * 3600000));
    const tariff = nn(p[4], p[3]);
    // the planner may count another price: the battery's refill cost, or own solar
    const uses = Math.abs(p[3] - tariff) >= 0.5 ? ` (${this._t("uses")} ${this._num(p[3], 0)} ct)` : "";
    const ot = this._geo && this._geo.ot;
    return `<b>${t}</b> \u00b7 ${ot ? this._ot("flow") : this._t("setpoint")} <b class="o">${ot && !(p[0] > 0) ? this._ot("off") : `${this._num(p[0], 1)}${DEG}`}</b> \u00b7 ${this._t("room")} <b>${this._num(p[1], 1)}${DEG}</b>` +
      ` \u00b7 <b>${this._num(tariff, 0)} ct</b>${p[5] ? " " + this._t("guessed") : ""}${uses}${this._geo.day[i] ? "" : " \u00b7 " + this._t("night")}`;
  }

  // ---------------------------------------------------------------- taps, keys and typed values (one listener each)
  // Where a tap lands decides what it does: the first matching selector wins. A tap outside all of them opens the
  // sensor's more-info dialog, as a card tap does in Home Assistant.
  _taps() {
    const st = () => this._hass.states[this._config.entity], at = () => (st() ? st().attributes : {});
    const draw = () => this._render();
    return [
      [".seg.tabs span[data-v]", (el) => { this._view = el.dataset.v; draw(); }],
      [".rng span[data-r]", (el) => { this._range = parseInt(el.dataset.r, 10); draw(); }],
      [".erng span[data-ep]", (el) => { this._ePer = el.dataset.ep; this._eOpen = null; draw(); }],
      [".etab .er[data-es]", (el) => { const k = el.dataset.es; this._eOpen = this._eOpen === k ? null : k; draw(); }],
      [".ecsv", () => this._energyCsv()],
      [".lhead", () => { this._logOpen = !this._logOpen; draw(); }],
      [".rep", () => this._report()],
      ["[data-open]", (el) => { const k = el.dataset.open; this._open = this._open === k ? null : k; this._armed = null; draw(); }],
      [".setgear", () => { this._open = this._open === "settings" ? null : "settings"; draw(); }],
      ["[data-hclose]", () => { this._sel = null; draw(); }],
      [".qbtn", () => { this._legOpen = !this._legOpen; draw(); }],
      [".steer", (el) => {
        if (this._armed !== "steer") {           // twice, so it never happens by accident
          this._armed = "steer"; draw();
          setTimeout(() => { if (this._armed === "steer") { this._armed = null; draw(); } }, 5000);
          return;
        }
        this._armed = null; this._open = null;
        this._call("select", "select_option", { entity_id: this._siblings().mode, option: "active" });
        draw();
      }],
      [".mopt[data-m]", (el) => {
        const m = el.dataset.m;
        if (m === "active" && this._armed !== "active") { this._armed = "active"; draw(); return; }
        if (m === "resume") this._call("roost", "resume", {});
        else if (m === "pause") this._call("roost", "pause", { hours: 2 });
        else if (m === "home") this._call("roost", "home", {});
        else this._call("select", "select_option", { entity_id: this._siblings().mode, option: m });
        this._open = null; this._armed = null; draw();
      }],
      [".head .ico, .week-settings", () => {
        window.history.pushState(null, "", "/config/integrations/integration/roost");
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      }],
      [".tile.therm:not(.nolink)", () => this._moreInfo(at().thermostat_entity)],   // the thermostat's own dialog
      [".mini[data-away]", (el) => { this._call("roost", "away", { days: parseFloat(el.dataset.away) }); this._open = null; draw(); }],
      [".calpill", () => { this._calOpen = !this._calOpen; this._calDay = null; draw(); }],
      [".cd[data-day]", (el) => {
        if (!el.classList.contains("bad")) return;
        this._calDay = !(this._calDay && this._calDay.day === el.dataset.day) ? { day: el.dataset.day, why: el.dataset.why } : null;
        draw();
      }],
      ["[data-step]", (el) => this._step(el.dataset.step, parseFloat(el.dataset.d))],
      [".mini[data-otquiet]", () => {
        const o = at().opentherm, p = this._pend && this._pend.ot_quiet;
        if (o) this._setTo("ot_quiet", !(p && !p.err ? p.v : !!o.quiet_on), true);
      }],
      [".mini[data-otrelearn]", () => {
        if (this._armed !== "relearn") {
          this._armed = "relearn"; draw();
          setTimeout(() => { if (this._armed === "relearn") { this._armed = null; draw(); } }, 4000);
          return;
        }
        this._armed = null; draw();
        this._call("roost", "set_settings", { ot_relearn: true });
      }],
      [".mini[data-control]", (el) => {
        if (at().control !== el.dataset.control) this._setTo("control", el.dataset.control, true);
      }],
      [".mini[data-room]", (el) => {        // the curve advice for another indoor temperature: nothing is saved
        const cs = this._sib("heating_curve"), base = cs && parseFloat(cs.attributes.room);
        const cur = this._curveRoom !== undefined ? this._curveRoom : base;
        if (!isNaN(cur)) { this._curveRoom = Math.min(24, Math.max(16, cur + parseFloat(el.dataset.room))); draw(); }
      }],
      // the weekly comfort periods: a draft in the card until Save
      [".wrow[data-wd]", (el) => { this._wkDay = parseInt(el.dataset.wd, 10); draw(); }],
      ["[data-wdel]", (el) => { this._weekDraft(at())[WEEKDAYS[this._wkDay]].splice(parseInt(el.dataset.wdel, 10), 1); this._wkMsg = null; draw(); }],
      ["[data-wadd]", () => {
        const list = this._weekDraft(at())[WEEKDAYS[this._wkDay]];
        const last = list.length ? Math.max.apply(null, list.map((p) => (p[1] > p[0] ? p[1] : 1440))) : 7 * 60;
        const s = Math.min(1380, last + 60);
        list.push([s, Math.min(1440, s + 120)]); list.sort((x, y) => x[0] - y[0]); this._wkMsg = null; draw();
      }],
      ["[data-wcopy]", (el) => {
        const wk = this._weekDraft(at()), src = wk[WEEKDAYS[this._wkDay]], to = { wd: [0, 1, 2, 3, 4], we: [5, 6], all: [0, 1, 2, 3, 4, 5, 6] }[el.dataset.wcopy];
        to.forEach((i) => { if (i !== this._wkDay) wk[WEEKDAYS[i]] = src.map((p) => [p[0], p[1]]); });
        this._wkMsg = null; draw();
      }],
      ["[data-wmode]", (el) => {
        const on = el.dataset.wmode === "1", a = at();
        if (on && !a.weekly_comfort) { this._wkOpen = true; draw(); return; }     // first set the periods, then save
        if (!on && a.weekly_comfort) this._saveWeek({ weekly_comfort: false });
        if (!on) { this._wkOpen = false; draw(); }
      }],
      ["[data-wsave]", () => this._saveWeek({ weekly_comfort: true, comfort_schedule: this._weekDraft(at()) })],
      [".chart:not(.hchart) .hit", (el, ev) => {     // tap an hour: why Roost does what it does then (again: close)
        const i = this._scrubPlan(ev);
        if (i !== null) { this._sel = this._sel === i ? null : i; draw(); }
      }],
    ];
  }
  // Parts of the card that do something of their own: a tap there never opens the more-info dialog
  _onTap(ev) {
    const t = ev.target;
    if (!t || !t.closest || !this._hass) return;
    for (const r of this._taps()) {
      const el = t.closest(r[0]);
      if (el && this._card.contains(el)) { ev.stopPropagation(); r[1](el, ev); return; }
    }
    if (!this._clickable || t.closest(".chart, .seg, .hlog, .rep, .curve, .cview, .ico, .mmenu, .ptable, .tile.plan, .tile.therm, " +
        "button, input, label, .cal, .week, .pills, .panel, .alert, .hpanel")) return;
    this._moreInfo(this._config.entity);
  }
  _moreInfo(entityId) {
    if (!entityId) return;
    const e = new Event("hass-more-info", { bubbles: true, composed: true });
    e.detail = { entityId };
    this.dispatchEvent(e);
  }
  _onKey(ev) {
    const t = ev.target;
    if (t && t.matches && t.matches(".seg span[data-v], .rng span[data-r], .erng span[data-ep], .etab .er[data-es]") && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault(); this._onTap(ev); return;
    }
    if (t && t.matches && t.matches("input.num")) {
      if (ev.key === "Enter") { ev.preventDefault(); t.blur(); }              // blur saves (change)
      else if (ev.key === "Escape") { t.dataset.cancel = "1"; t.blur(); }
      else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
        ev.preventDefault();
        this._step(t.dataset.num, ev.key === "ArrowUp" ? 1 : -1);
        // the field has the focus, so a redraw leaves its text alone: write the stepped value into it here
        const st = this._hass.states[this._config.entity], a = st ? st.attributes : {}, sp = this._spec(t.dataset.num, a), v = this._val(t.dataset.num, a);
        if (sp && typeof v === "number") t.value = sp.dec ? this._num(v, sp.dec) : String(Math.round(v));
      }
    }
  }
  _onChange(ev) {
    const t = ev.target;
    if (!t || !t.matches) return;
    if (t.matches("input.num")) {
      if (t.dataset.cancel) return;
      this._setTo(t.dataset.num, parseNum(t.value), true);
    } else if (t.matches("input[data-wt]")) {          // a time in the weekly periods (HH:MM, quarter hours)
      const [j, k] = t.dataset.wt.split(":").map((x) => parseInt(x, 10)), m = /^(\d{1,2}):(\d{2})/.exec(t.value || "");
      const st = this._hass.states[this._config.entity], p = m && this._weekDraft(st ? st.attributes : {})[WEEKDAYS[this._wkDay]][j];
      if (!p) return;
      let v = Math.round((parseInt(m[1], 10) * 60 + parseInt(m[2], 10)) / 15) * 15;
      if (k === 1 && v === 0) v = 1440;                // until midnight
      if (v !== p[1 - k] % 1440 && !(k === 1 && v === p[0])) p[k] = v % (k === 0 ? 1440 : 1441);
      this._wkMsg = null; this._render();
    }
  }
  _onBlur(ev) {
    const t = ev.target;
    // Escape: back to the value the card knows; a redraw after the blur puts it in the field
    if (t && t.matches && t.matches("input.num") && t.dataset.cancel) { delete t.dataset.cancel; t.value = ""; this._render(); }
    else if (t && t.matches && t.matches("input.num")) this._render();
  }
  _onToggle(ev) {
    const d = ev.target;
    if (!d || d.tagName !== "DETAILS") return;
    if (d.classList.contains("tday")) this._tblOpen = Object.assign({}, this._tblOpen, { [d.dataset.day]: d.open });
  }
  _onScrub(ev) {
    const t = ev.target;
    if (!t || !t.closest || !t.closest(".hit")) return;
    // a finger or mouse sends many moves per frame: handle only the last one of each frame
    const hist = !!t.closest(".hchart"), x = ev.touches && ev.touches.length ? ev.touches[0].clientX : ev.clientX;
    this._scrubAt = { hist, clientX: x };
    if (this._scrubRaf) return;
    const run = () => { this._scrubRaf = null; const e = this._scrubAt; if (e.hist) this._scrubHist(e); else this._scrubPlan(e); };
    if (typeof requestAnimationFrame !== "function") { run(); return; }
    this._scrubRaf = requestAnimationFrame(run);
  }
  _scrubPlan(ev) {
    const root = this.shadowRoot, hit = root.querySelector(".chart:not(.hchart) .hit"), g = this._geo;
    if (!hit || !g) return null;
    const r = hit.getBoundingClientRect(), cx = ev.touches && ev.touches.length ? ev.touches[0].clientX : ev.clientX;
    const i = Math.max(0, Math.min(g.n - 1, Math.floor((cx - r.left) / r.width * g.n))), xx = g.L + (i + 0.5) * g.w;
    const cur = root.querySelector(".chart:not(.hchart) .cur"), dot = root.querySelector(".dot"), dot2 = root.querySelector(".dot2");
    cur.setAttribute("x1", xx); cur.setAttribute("x2", xx);
    dot.setAttribute("cx", xx); dot.setAttribute("cy", g.kt[i]);
    dot2.setAttribute("cx", xx); dot2.setAttribute("cy", g.sp[i] === null ? -20 : g.sp[i]);
    root.querySelector(".chart:not(.hchart)").classList.add("on");
    // the same hour as the last move: the panel already says it (a redraw drops data-i, so it is filled again then)
    const info = root.querySelector(".chart:not(.hchart) .info");
    if (info.getAttribute("data-i") !== String(i)) { info.innerHTML = this._info(i); info.setAttribute("data-i", String(i)); }
    return i;
  }
  _scrubHist(ev) {
    const root = this.shadowRoot, hit = root.querySelector(".hchart .hit"), g = this._hgeo;
    if (!hit || !g) return;
    const r = hit.getBoundingClientRect(), cx = ev.touches && ev.touches.length ? ev.touches[0].clientX : ev.clientX;
    const i = Math.max(0, Math.min(g.n - 1, Math.floor((cx - r.left) / r.width * g.n)));
    const h = g.by[g.t0 + i * 3600], xx = g.L + (i + 0.5) * g.w, cur = root.querySelector(".hchart .cur");
    cur.setAttribute("x1", xx); cur.setAttribute("x2", xx);
    root.querySelector(".hchart").classList.add("on");
    const info = root.querySelector(".hchart .info");
    if (h && info.getAttribute("data-i") !== String(i)) { info.innerHTML = this._hinfo(h); info.setAttribute("data-i", String(i)); }
  }
  // A service call whose failure shows in the card instead of vanishing (an unhandled rejection)
  _call(domain, service, data) {
    return Promise.resolve(this._hass.callService(domain, service, data)).catch((e) => {
      this._err = { text: (e && e.message) || String(e), t: Date.now() }; this._render();
      setTimeout(() => { if (this._err && Date.now() - this._err.t >= 6000) { this._err = null; this._render(); } }, 6100);
    });
  }

  // ---------------------------------------------------------------- the settings: typed or stepped, shown at once
  // What each setting is: where its value is (a Roost attribute, the OpenTherm block, or an entity on the master),
  // its limits and step. Limits match the service schema (__init__.py); an entity's own min/max/step win.
  _spec(key, a) {
    const S = SETS[key];
    if (!S) return null;
    const o = a.opentherm || {};
    if (S.ent) {
      const eid = o[S.ent], e = eid && this._hass.states[eid];
      if (!e && S.ot) return a.opentherm ? Object.assign({}, S, { ent: undefined, cur: o[S.ot] }) : null;   // no such entity: Roost's own setting
      if (!e) return null;
      const at = e.attributes || {};
      // a tap moves by the card's step; a typed value only snaps to the entity's own precision
      return Object.assign({}, S, { eid, lo: nn(at.min, S.lo), hi: nn(at.max, S.hi), tap: S.step, step: nn(at.step, S.step), cur: parseFloat(e.state) });
    }
    if (S.ot) return a.opentherm ? Object.assign({}, S, { cur: o[S.ot] }) : null;
    return Object.assign({}, S, { cur: a[key] });
  }
  // The value to show: what was just set (until the sensor says the same), else what the sensor says
  _val(key, a) {
    const p = this._pend && this._pend[key], sp = this._spec(key, a);
    return p && !p.err ? p.v : (sp ? sp.cur : undefined);
  }
  _step(key, dir) {
    const st = this._hass.states[this._config.entity], a = st ? st.attributes : {}, sp = this._spec(key, a);
    if (!sp) return;
    const cur = parseFloat(this._val(key, a));
    if (isNaN(cur)) return;
    this._setTo(key, cur + dir * (sp.tap || sp.step), false);
  }
  // A new value: shown at once; saved after a short pause (taps in a row are one change, one plan) or at once when typed
  _setTo(key, v, now) {
    const st = this._hass.states[this._config.entity], a = st ? st.attributes : {};
    this._pend = this._pend || {}; this._timers = this._timers || {};
    const sp = SETS[key] && this._spec(key, a);
    if (sp) {
      if (typeof v !== "number" || isNaN(v)) return this._fail(key, this._st("bad"));
      if (sp.wrap) v = ((Math.round(v) % sp.wrap) + sp.wrap) % sp.wrap;
      v = snap(v, sp.lo, sp.hi, sp.step);
      if (key === "day_from" && v >= parseFloat(this._val("day_to", a))) return this._fail(key, this._st("order_from"));
      if (key === "day_to" && v <= parseFloat(this._val("day_from", a))) return this._fail(key, this._st("order_to"));
      if (sp.cur === v && !this._pend[key]) { this._render(); return; }
    }
    this._pend[key] = { v, t: Date.now(), sent: false };
    clearTimeout(this._timers[key]);
    this._timers[key] = setTimeout(() => this._send(key), now ? 0 : 650);
    this._render();
  }
  _fail(key, text) {
    this._pend = this._pend || {};
    const p = { err: text, t: Date.now() };
    this._pend[key] = p;
    this._render();
    setTimeout(() => { if (this._pend[key] === p) { delete this._pend[key]; this._render(); } }, 5000);
  }
  _send(key) {
    const p = this._pend && this._pend[key];
    if (!p || p.err) return;
    const st = this._hass.states[this._config.entity], a = st ? st.attributes : {}, sp = this._spec(key, a);
    p.sent = true; p.at = Date.now();
    let call;
    if (sp && sp.eid) call = this._hass.callService("number", "set_value", { entity_id: sp.eid, value: p.v });
    else call = this._hass.callService("roost", "set_settings", { [key]: p.v });
    Promise.resolve(call).then(() => this._render(), (e) => {
      if (this._pend[key] === p) this._fail(key, (e && e.message) || String(e));
    });
  }
  // A value that was just set goes once the sensor shows it; one that never shows is reported, not kept forever
  _settle(a) {
    const pend = this._pend || {};
    Object.keys(pend).forEach((k) => {
      const p = pend[k];
      if (p.err || !p.sent) return;
      const cur = k === "ot_quiet" ? !!(a.opentherm && a.opentherm.quiet_on) : (k === "control" ? a.control : (this._spec(k, a) || {}).cur);
      if (cur === p.v || (typeof cur === "number" && Math.abs(cur - p.v) < 1e-6)) delete pend[k];
      else if (Date.now() - p.at > 20000) {
        this._fail(k, this._st("unconfirmed"));
      } else if (!this._settleTimer) {           // look again when no update comes
        this._settleTimer = setTimeout(() => { this._settleTimer = null; this._render(); }, 2000);
      }
    });
  }
  _st(k) { const own = (SET_T[this._lang()] || SET_T.en)[k]; return own === undefined ? SET_T.en[k] : own; }
  // One number the user can type or step: - [ value unit ] +
  _numRow(key, a, label) {
    const sp = this._spec(key, a);
    if (!sp) return "";
    const p = this._pend && this._pend[key], v = this._val(key, a);
    const shown = v === null || v === undefined || isNaN(v) ? "" : (sp.dec ? this._num(v, sp.dec) : String(Math.round(v)));
    const unit = sp.unit === "deg" ? DEG : (sp.unit === "h" ? ":00" : sp.unit);
    const cls = p ? (p.err ? " err" : " pend") : "";
    const lab = this._esc(label);
    return `<div class="srow${cls}" data-k="s-${key}"><span class="sl">${lab}${p && p.err ? `<small class="serr">${this._esc(p.err)}</small>` : ""}</span>` +
      `<span class="stp"><button class="mini" data-step="${key}" data-d="-1" aria-label="${lab} \u2212">\u2212</button>` +
      `<label class="nf"><input class="num" data-num="${key}" type="text" inputmode="${sp.dec ? "decimal" : "numeric"}" enterkeyhint="done" ` +
      `autocomplete="off" spellcheck="false" value="${shown}" aria-label="${lab}"><span class="u">${unit}</span></label>` +
      `<button class="mini" data-step="${key}" data-d="1" aria-label="${lab} +">+</button></span></div>`;
  }

  _footer(a) {
    const imp = this._sib("weheat_import"), prog = this._sib("import_progress");
    if (!(imp && imp.state === "importing" && prog)) return "";
    const pa = prog.attributes, end = pa.expected_done ? new Date(pa.expected_done) : null;
    return `<div class="foot" data-k="foot">${this._t("importing")} <b>${pa.months_done}/${pa.months}</b> ${this._t("months")}` +
      (end && !isNaN(end) ? `, ${this._t("done_at")} ~${this._hm(end)}` : "") + `</div>`;
  }

  // ---------------------------------------------------------------- mode menu (tap the mode label)
  _modeMenu(mode, paused, away, a) {
    const opt = (m) => `<button class="mopt${m === mode ? " on" : ""}" data-m="${m}"><b>${this._t("mo_" + m)}</b>` +
      `<small>${this._armed === m ? this._t("mo_sure") : this._t("mh_" + m)}</small></button>`;
    return `<div class="mmenu">${paused ? `<button class="mopt" data-m="resume"><b>${this._t("mo_resume")}</b><small>&nbsp;</small></button>` : ""}` +
      `${opt("off")}${opt("shadow")}${opt("active")}${mode === "active" && !paused ? opt("pause") : ""}` +
      (mode === "active" ? (away ? `<button class="mopt" data-m="home"><b>${this._t("mo_home")}</b><small>${this._t("mh_home")}</small></button>`
        : `<div class="mrow"><b>${this._t("mo_away")}</b><span>${[1, 3, 7].map((d) => `<button class="mini" data-away="${d}">${this._t("away_" + d)}</button>`).join("")}</span>` +
          `<small>${this._t("mh_away").replace("{min}", this._num(16, 0))}</small></div>`) : "") +
      `</div>`;
  }

  // All of Roost's own settings (the same as Configure -> Comfort): each typed or stepped, saved at once
  _settingsPanel(a) {
    const pc = this._pend && this._pend.control, control = pc && !pc.err ? pc.v : a.control;
    const cc = a.control_choices || {};
    const steer = cc.opentherm && cc.thermostat ? `<div class="srow" data-k="s-control"><span class="sl">${this._ot("steer")}` +
      `${pc && pc.err ? `<small class="serr">${this._esc(pc.err)}</small>` : ""}</span><span class="stp">` +
      ["thermostat", "opentherm"].map((c) => `<button class="mini wide${control === c ? " on" : ""}" data-control="${c}" title="${this._ot(c === "opentherm" ? "ot_h" : "th_h")}">` +
        `${this._ot(c === "opentherm" ? "ot" : "th")}</button>`).join("") + `</span></div>` : "";
    const hours = a.weekly_comfort ? "" : this._numRow("day_from", a, this._st("from")) + this._numRow("day_to", a, this._st("to"));
    // the comfort range first (at least, may warm up to), then eco outside the comfort hours, the hours, and the hard
    // floor last: it follows comfort down by itself (comfort.normalise)
    return `<div class="spanel" data-k="spanel">` + steer + this._otSettings(a) + this._rangeLine(a, control) +
      this._numRow("comfort", a, this._t("s_comfort")) + this._numRow("store_max", a, this._t("s_store")) +
      this._numRow("night_min", a, this._t("s_night_min")) + hours + this._weekEditor(a) + this._numRow("day_min", a, this._t("s_day_min")) +
      // the lowest thermostat setting does nothing over OpenTherm (no thermostat is set): only shown for the thermostat
      (control === "opentherm" ? "" : this._numRow("lowest_setpoint", a, this._t("s_lowest"))) + `</div>`;
  }

  // "Comfort 20-22  degC | warm at 07:00 | outside that at least 18  degC | box on fallback 20  degC": the range in one line
  _rangeLine(a, control) {
    if (a.comfort === undefined || a.comfort === null) return "";
    const lo = Number(a.comfort), hi = Math.max(lo, Number(nn(a.store_max, lo))), deg = (v) => this._num(v, 1) + DEG;
    const when = a.weekly_comfort ? this._t("r_week") : this._t("r_at").replace("{t}", String(nn(a.day_from, 7)).padStart(2, "0") + ":00");
    const o = a.opentherm, box = control === "opentherm" && o && o.follow_curve ? ` \u00b7 ${this._t("r_box").replace("{v}", deg(lo))}` : "";
    return `<div class="ots" data-k="s-range"><b>${this._t("r_line").replace("{lo}", this._num(lo, 1)).replace("{hi}", deg(hi))}</b> \u00b7 ${when} \u00b7 ` +
      `${this._t("r_eco").replace("{v}", deg(nn(a.night_min, 18)))}${box}</div>` + this._adviceLine(a);
  }

  // What the last days would have cost with eco a degree lower and the top a degree lower (planner.what_if_day,
  // replayed each night): "Last 7 days, per week: storing heat saved EUR 2.80 | up to 22  degC costs EUR 0.10 more | eco 17  degC
  // saves EUR 0.35, a little colder". Only once there are a few days with the settings in force.
  _adviceLine(a) {
    const v = a.comfort_advice;
    if (!v || !v.days) return "";
    const deg = (x) => this._num(x, 1) + DEG;
    const diff = (d) => Math.abs(d.week) < 0.05 ? this._t("r_same") : this._t(d.week > 0 ? "r_more" : "r_less").replace("{v}", this._money(Math.abs(d.week)));
    const parts = [];
    if (v.top_off && v.top_off.week >= 0.05) parts.push(this._t("r_store").replace("{v}", this._money(v.top_off.week)));
    if (v.top_down) parts.push(`${this._t("r_top").replace("{t}", deg(v.store_max - 1))} ${diff(v.top_down)}`);
    if (v.eco_down) parts.push(`${this._t("r_eco1").replace("{t}", deg(v.night_min - 1))} ${diff(v.eco_down)}` +
      (v.eco_down.short >= 0.5 ? `, ${this._t("r_colder")}` : ""));
    return parts.length ? `<div class="ots" data-k="s-advice"><small>${this._t("r_adv").replace("{n}", v.days)}: ${parts.join(" \u00b7 ")}</small></div>` : "";
  }

  // How far the learning from the unit is: steady samples and starts against what it needs (otlearn.MIN_*)
  _learnProgress(o) {
    const L = o.learned || {}, need = o.learn_need;
    if (!need) return this._ot("samples").replace("{n}", o.samples || 0);
    return this._ot("progress").replace("{s}", nn(L.steady, 0)).replace("{S}", need.steady).replace("{n}", nn(L.starts, 0)).replace("{N}", need.starts);
  }
  // OpenTherm: the gateway's state, flow limits, minimum on/off (on the gateway), starts, quiet hours, what was learned
  _otSettings(a) {
    const o = a.opentherm;
    if (!o) return "";
    const pq = this._pend && this._pend.ot_quiet, quiet = pq && !pq.err ? pq.v : !!o.quiet_on;
    const t = o.last_write ? this._hour(new Date(o.last_write)) : "\u2013";
    const stat = `${o.steering ? this._ot("st_steered") : this._ot("st_curve")} \u00b7 ${this._ot("st_written").replace("{t}", t)}` +
      (o.follow_curve === null || o.follow_curve === undefined ? "" : ` \u00b7 ${o.follow_curve ? this._ot("st_follow").replace("{room}", this._num(a.comfort, 1) + DEG) : this._ot("st_nofollow")}`) +
      (o.starts_planned === null || o.starts_planned === undefined ? "" : ` \u00b7 ${this._ot("planned_starts").replace("{n}", o.starts_planned)}`);
    const L = o.learned || {}, lr = (k, v, unit, setv) => `<span>${this._ot(k)} <b>${v === null || v === undefined ? "\u2013" : this._num(v, 2) + unit}</b>` +
      `${setv !== undefined && (v === null || v === undefined) ? ` <small>(${this._ot("setting").replace("{v}", this._num(setv, 1) + unit)})</small>` : ""}</span>`;
    return `<div class="otset" data-k="otset"><div class="ots"><b>${this._ot("ot_set")}</b> \u00b7 ${this._ot("st_master")}: ${stat}</div>` +
      this._numRow("ot_min_flow", a, this._ot("fmin")) + this._numRow("ot_max_flow", a, this._ot("fmax")) +
      this._numRow("ot_min_run", a, this._ot("mrun")) + this._numRow("ot_min_off", a, this._ot("moff")) +
      this._numRow("ot_max_starts", a, `${this._ot("starts")} (0 = ${this._ot("nolimit")})`) +
      `<div class="srow" data-k="s-ot_quiet"><span class="sl">${this._ot("quiet")}${pq && pq.err ? `<small class="serr">${this._esc(pq.err)}</small>` : ""}</span>` +
      `<span class="stp"><button class="mini wide${quiet ? " on" : ""}" data-otquiet="1" aria-pressed="${!!quiet}">${quiet ? this._ot("q_on") : this._ot("qoff")}</button></span></div>` +
      (quiet ? this._numRow("ot_quiet_from", a, this._st("q_from")) + this._numRow("ot_quiet_to", a, this._st("q_to")) +
        this._numRow("ot_quiet_max", a, this._ot("qmax")) : "") +
      `<div class="otl"><div>${this._ot("learned")} <small>(${this._learnProgress(o)})</small></div>` +
      `<div class="otlv">${lr("lq", L.q_min, " kW", o.q_min_setting)}${lr("lk", L.k, " kW/\u00b0C")}${lr("lstart", L.start_kwh, " kWh", o.start_kwh_setting)}` +
      `${lr("lrest", L.rest_min, " min")}</div>` +
      `<button class="mini wide" data-otrelearn="1">${this._armed === "relearn" ? this._ot("relearn_sure") : this._ot("relearn")}</button></div></div>`;
  }

  // ---------------------------------------------------------------- table: the plan ahead and the last 7 days per hour
  _savingQuality(q) {
    if (!q) return "";
    const lang = String(this._locale()).split("-")[0];
    const text = SAVING_QUALITY[lang] || SAVING_QUALITY.en;
    if (q.valid) return q.status === "validated_estimate" ? text.checked : text.forecast;
    return text.unreliable + " " + (q.reasons || []).map((r) => text[r] || text.unreliable).join(" ");
  }

  // Hours in a row with the same setting and the same reason are one line, so the table stays short.
  _runs(list, same) {
    const out = [];
    list.forEach((x) => { const r = out[out.length - 1]; if (r && same(r.items[r.items.length - 1], x)) r.items.push(x); else out.push({ items: [x] }); });
    return out;
  }
  _span(t0, n) {
    const a = this._hour(new Date(t0 * 1000));
    return n > 1 ? `${a}\u2013${this._hour(new Date((t0 + n * 3600) * 1000))}` : a;
  }
  _range2(a, b, d) {    // "20,7" or "20,7\u2192 20,3"
    return a === null || a === undefined ? "\u2014" : (b === null || b === undefined || Math.abs(a - b) < 0.05 ? this._num(a, d) : `${this._num(a, d)}\u2192${this._num(b, d)}`);
  }
  // Where the heat pump's electricity came from (own solar, battery, grid), over the given hours of the log
  _srcLine(hours) {
    const sum = (k) => hours.reduce((t, h) => t + (h[k] || 0), 0);
    const sun = sum("e_sun"), bat = sum("e_bat"), grid = sum("e_grid"), tot = sun + bat + grid;
    if (tot < 0.05) return "";
    const pc = (v) => `${this._num(100 * v / tot, 0)}%`;
    return `<div class="srcl"><span class="sbar"><i class="ss" style="width:${100 * sun / tot}%"></i><i class="sb" style="width:${100 * bat / tot}%"></i>` +
      `<i class="sg" style="width:${100 * grid / tot}%"></i></span>${this._t("src_title")} ${this._num(tot, 1)} kWh: ` +
      `<b class="ss">${this._t("src_sun")} ${pc(sun)}</b> \u00b7 <b class="sb">${this._t("src_bat")} ${pc(bat)}</b> \u00b7 <b class="sg">${this._t("src_grid")} ${pc(grid)}</b></div>`;
  }

  _tableBody(a) {
    return `<div class="ptable">${this._tableAhead(a)}${this._tableBack()}</div>`;
  }
  _tableAhead(a) {
    const plan = a.plan || [], why = a.plan_why || [];
    if (!plan.length) return `<div class="na">${this._t("noplan")}</div>`;
    const start = Math.floor((a.start ? new Date(a.start).getTime() : Date.now()) / 1000);
    const hrs = plan.map((p, i) => ({ ts: start + i * 3600, sp: p[0], room: p[1], kwh: p[2], tariff: nn(p[4], p[3]), guess: !!p[5], why: why[i] || null }));
    const tar = hrs.map((h) => h.tariff).sort((x, y) => x - y), lo = tar[Math.floor(tar.length / 3)], hi = tar[Math.floor(2 * tar.length / 3)];
    const tone = (v) => (v <= lo ? "cheap" : (v >= hi ? "dear" : "mid"));
    const runs = this._runs(hrs, (x, y) => x.sp === y.sp && (x.why && x.why[0]) === (y.why && y.why[0]));
    let prev = null, rows = "";
    runs.forEach((r, k) => {
      const f = r.items[0], l = r.items[r.items.length - 1], n = r.items.length;
      const avg = r.items.reduce((t, h) => t + h.tariff, 0) / n, kwh = r.items.reduce((t, h) => t + (h.kwh || 0), 0);
      const arrow = prev === null || f.sp === prev ? "" : (f.sp > prev ? " \u2191" : " \u2193");
      const t = k === 0 ? `${this._t("now")} ${this._span(f.ts, n)}` : this._span(f.ts, n);
      rows += `<div class="tr${k === 0 ? " now" : ""}"><span>${t}</span><b class="o">${a.opentherm && !(f.sp > 0) ? this._ot("off") : this._num(f.sp, 1)}${arrow}</b>` +
        `<span>${this._range2(f.room, l.room, 1)}</span><span class="pr ${tone(avg)}${f.guess ? " guess" : ""}">${this._num(avg, 0)} ct</span>` +
        `<span>${kwh >= 0.05 ? this._num(kwh, 1) : "\u2013"}</span>` +
        `<div class="tw">${f.why ? this._why(f.why[0], f.why[1], "") : ""}</div></div>`;
      prev = f.sp;
    });
    return `<div class="tsec">${this._t("next24")}</div><div class="tr th"><span>${this._t("t_time")}</span><span>${this._t("t_set")}</span>` +
      `<span>${this._t("t_room")} ${this._t("t_exp")}</span><span>${this._t("price")}</span><span>kWh</span></div>${rows}`;
  }
  _tableBack() {
    if (!this._hist || Date.now() - (this._histAt || 0) > 300000) this._fetchHist();
    if (!this._hist) return `<div class="tsec">${this._t("t_back7")}</div><div class="na">${this._histErr || this._t("h_loading")}</div>`;
    const d = this._hist, hours = (d.hours || []).slice().sort((x, y) => y.ts - x.ts);
    if (!hours.length) return "";
    const key = (ts) => { const t = new Date(ts * 1000); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };
    const hand = new Set((d.events || []).filter((e) => e.kind === "by_hand").map((e) => Math.floor(new Date(e.t).getTime() / 3600000) * 3600));
    const byDay = {};
    hours.forEach((h) => { (byDay[key(h.ts)] = byDay[key(h.ts)] || []).push(h); });
    const today = key(Date.now() / 1000);
    let html = `<div class="tsec">${this._t("t_back7")}</div>`;
    Object.keys(byDay).sort().reverse().forEach((day) => {
      const hs = byDay[day].slice().sort((x, y) => x.ts - y.ts);
      const ds = (d.days || {})[day];
      const open = this._tblOpen && this._tblOpen[day] !== undefined ? this._tblOpen[day] : day === today;
      const label = day === today ? this._t("t_today") : new Date(day + "T12:00:00").toLocaleDateString(this._locale(), { weekday: "short", day: "numeric", month: "short" });
      const sum = ds ? ` <span>${this._money(ds.cost)}${ds.saving !== undefined && ds.saving !== null ? ` \u00b7 ${this._t("h_saving")} ${this._money(ds.saving)}` : ""}` +
        `${ds.pred_mae !== null && ds.pred_mae !== undefined ? ` \u00b7 ${this._t("h_pred")} \u00b1${this._num(ds.pred_mae, 1)}` : ""}</span>` : "";
      let loss = "";
      if (ds && ds.quality && !ds.quality.valid) {
        loss = `<div class="tloss">${this._savingQuality(ds.quality)}</div>`;
      } else if (ds && ds.saving !== undefined && ds.saving !== null && ds.saving < -0.05) {      // why a day cost more than a steady thermostat
        const stored = hs.filter((h) => String(h.reason || "").startsWith("store_")).length;
        const top = Math.max.apply(null, hs.map((h) => h.T));
        loss = `<div class="tloss">${stored ? this._t("t_loss_store").replace("{h}", stored).replace("{max}", this._num(top, 1)) : this._t("t_loss_other")}</div>`;
      }
      const runs = this._runs(hs, (x, y) => this._hset(x) === this._hset(y) && x.sp_plan === y.sp_plan && x.reason === y.reason && !hand.has(y.ts) &&
        !!x.window === !!y.window && !x.ot === !y.ot);
      let rows = "";
      runs.forEach((r) => {
        const f = r.items[0], l = r.items[r.items.length - 1], n = r.items.length;
        // electricity, as in the plan above (not the heat delivered: three to four times as much, not comparable)
        const price = r.items.reduce((t, h) => t + (h.p_grid || 0), 0) / n * 100, elec = r.items.reduce((t, h) => t + (h.e || 0), 0);
        const set = f.ot ? this._hsetTxt(f) : (f.sp_plan !== null && f.sp_plan !== undefined && Math.abs(f.sp_plan - f.sp_t) >= 0.25
          ? `${this._num(f.sp_plan, 1)}\u2192${this._num(f.sp_t, 1)}` : this._num(f.sp_t, 1));
        const marks = (hand.has(f.ts) ? ` <i class="mk">${this._t("h_byhand")}</i>` : "") + (f.window ? ` <i class="mk">${this._t("h_window")}</i>` : "");
        const pred = f.p6 !== null && f.p6 !== undefined ? ` <small>(${this._t("t_exp")} ${this._num(f.p6, 1)})</small>` : "";
        rows += `<div class="tr"><span>${this._span(f.ts, n)}</span><b class="o">${set}</b><span>${this._range2(f.T, l.T, 1)}${pred}</span>` +
          `<span class="pr">${this._num(price, 0)} ct</span><span>${elec >= 0.05 ? this._num(elec, 1) : "\u2013"}</span>` +
          `<div class="tw">${f.reason ? this._why(f.reason, f.args || {}, "") : ""}${marks}</div></div>`;
      });
      html += `<details class="tday" data-day="${day}"${open ? " open" : ""}><summary><b>${label}</b>${sum}</summary>${loss}${this._srcLine(hs)}` +
        `<div class="tr th"><span>${this._t("t_time")}</span><span>${this._t("t_set")}</span><span>${this._t("t_room")}</span>` +
        `<span>${this._t("price")}</span><span>kWh</span></div>${rows}</details>`;
    });
    return html;
  }

  // ---------------------------------------------------------------- energy (websocket roost/energy)
  // What the heat pump took and gave per hour, day, week or month, from Home Assistant's long-term statistics. A row
  // opens to the details; the totals, the comparison per degree day and a CSV for a spreadsheet. Phone: the columns
  // that matter most, a wide card all of them.
  _fetchEnergy(per) {
    this._eData = this._eData || {};
    if (this._eLoading === per || !this._hass) return;
    this._eLoading = per;
    this._hass.callWS({ type: "roost/energy", entity_id: this._config.entity, period: per }).then((d) => {
      this._eData[per] = { d, at: Date.now() }; this._eErr = null; this._eLoading = null; this._render();
    }).catch((e) => { this._eErr = String((e && e.message) || e); this._eLoading = null; this._render(); });
  }
  _eLabel(r, per, first) {
    const t = new Date(r.start * 1000), loc = this._locale();
    // hours: the weekday only where a day starts (and on top), so the time fits a phone's first column
    if (per === "hour") return (first || t.getHours() === 0 ? dayFmt(this._lang()).format(t) + " " : "") + this._hour(t);
    if (per === "day") return dayFmt(this._lang()).format(t) + " " + t.getDate() + "-" + (t.getMonth() + 1);
    if (per === "week") {   // ISO week number of the Monday
      const d = new Date(Date.UTC(t.getFullYear(), t.getMonth(), t.getDate() + 3));
      const y0 = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
      return `${this._et("wk")} ${1 + Math.round(((d - y0) / 86400000 - 3 + ((y0.getUTCDay() + 6) % 7)) / 7)}`;
    }
    return t.toLocaleDateString(loc, { month: "short", year: "numeric" });
  }
  // defrosts: counted (from the unit's state history) or estimated from the defrost meter (\u2248)
  _eTimes(r, words) {
    const v = r.defrosts || 0;
    if (v < 0.2) return "\u2013";
    const k = Math.max(1, Math.round(v)), est = r.defrosts_est ? "\u2248" : "";
    return words ? est + this._et("dfr_n").replace("{n}", this._num(k, 0)) : `${est}${this._num(k, 0)}\u00d7`;
  }
  _eTone(idx) { return idx === null || idx === undefined ? "" : idx >= 97 ? "good" : idx < 90 ? "bad" : "mid"; }
  _eSum(rows) {   // the totals of the rows shown (the index: heat-weighted from the rows' own)
    const s = { defrosts: 0, bat: 0, cost_heat: 0, cost_dhw: 0, cost_ind: 0, cost_rest: 0, q_heat: 0, q_def: 0, q_dhw: 0, e_heat: 0, e_dhw: 0, e_ind: 0, e_rest: 0, cost: 0, priced: 0, sun: 0, run_h: 0, dd: 0, hours: 0 };
    let tw = 0, tn = 0, lo = null, iw = 0, ix = 0, costed = false, fw = 0, fn = 0, rw = 0, rn = 0;
    rows.forEach((r) => {
      Object.keys(s).forEach((k) => { if (k !== "cost") s[k] += r[k] || 0; });
      if (r.cost !== null && r.cost !== undefined) { s.cost += r.cost; costed = true; }
      if (r.defrosts_est) s.defrosts_est = true;
      if (r.t_out !== null) { tw += r.t_out * r.hours; tn += r.hours; }
      if (r.t_min !== null && (lo === null || r.t_min < lo)) lo = r.t_min;
      if (r.flow !== null && r.run_h > 0) { fw += r.flow * r.run_h; fn += r.run_h; }
      if (r.room !== null && r.room !== undefined) { rw += r.room * r.hours; rn += r.hours; }
      if (r.index !== null && r.q_heat > 0) { iw += r.q_heat; ix += r.index * r.q_heat; }
    });
    const qn = s.q_heat - s.q_def, e = s.e_heat + s.e_dhw + s.e_ind + s.e_rest;
    return Object.assign(s, { t_out: tn ? tw / tn : null, t_min: lo, cost: costed ? s.cost : null, flow: fn ? fw / fn : null, room: rn ? rw / rn : null,
      cop_heat: s.e_heat >= 0.05 && qn > 0 ? qn / s.e_heat : null, cop_dhw: s.e_dhw >= 0.05 ? s.q_dhw / s.e_dhw : null,
      cop_pump: s.e_heat + s.e_dhw >= 0.05 ? (qn + s.q_dhw) / (s.e_heat + s.e_dhw) : null,
      cop_all: e >= 0.05 ? (qn + s.q_dhw) / e : null, index: iw > 0 ? Math.round(ix / iw) : null });
  }
  _eDetail(r, prev) {
    const n = (v, d) => this._num(v, d), kwh = (v) => `${n(v, 1)} kWh`;
    const e = r.e_heat + r.e_dhw + r.e_ind + r.e_rest;
    const pdd = r.dd >= 0.5 ? e / r.dd : null, qdd = prev && prev.dd >= 0.5 ? (prev.e_heat + prev.e_dhw + prev.e_ind + prev.e_rest) / prev.dd : null;
    const vs = pdd !== null && qdd ? ` (${pdd >= qdd ? "+" : ""}${n(100 * (pdd / qdd - 1), 0)}% ${this._et("vs")})` : "";
    const line = (l, v) => `<div><span>${l}</span><b>${v}</b></div>`;
    let h = "";
    if (r.status) h += line(this._et("status"), this._et("st_" + r.status) + (r.reason ? ` \u00b7 ${this._why(r.reason, r.args || {}, "")}` : ""));
    h += line(this._et("out"), `${n(r.t_out, 1)}${DEG}${r.t_min !== null ? ` \u00b7 ${this._et("lowest")} ${n(r.t_min, 1)}${DEG}` : ""}`);
    if (r.flow !== null && r.flow !== undefined) h += line(this._et("flow"), `${n(r.flow, 1)}${DEG}`);
    if (r.room !== null && r.room !== undefined) h += line(this._et("room"), `${n(r.room, 1)}${DEG}`);
    h += line(this._et("heat"), `${kwh(r.q_heat - r.q_def)} ${this._et("heat_sp")} \u00b7 ${kwh(r.q_dhw)} ${this._et("heat_dhw")}` +
      "");
    h += line(this._et("elec"), `${kwh(r.e_heat)} ${this._et("el_heat")} \u00b7 ${kwh(r.e_dhw)} ${this._et("el_dhw")} \u00b7 ${kwh(r.e_ind)} ${this._et("el_ind")}` +
      (r.e_rest >= 0.05 ? ` \u00b7 ${kwh(r.e_rest)} ${this._et("el_rest")}` : ""));
    h += line(this._et("cop"), [["cop_pump", r.cop_pump], ["cop_heat", r.cop_heat], ["cop_dhw", r.cop_dhw], ["cop_all", r.cop_all]]
      .filter((x) => x[1] !== null && x[1] !== undefined).map((x) => `${n(x[1], 1)} ${this._et(x[0])}`).join(" \u00b7 ") || "\u2014");
    if (r.index !== null && r.index !== undefined) h += line(this._et("idx"), `<span class="ix ${this._eTone(r.index)}">${n(r.index, 0)}%</span> ${this._et("of_exp")}`);
    if (r.defrosts > 0.2 || r.q_def >= 0.05) h += line(this._et("dfr"), `${this._eTimes(r, true)} \u00b7 ${this._et("dfr_heat").replace("{q}", n(r.q_def, 1))}`);
    h += line(this._et("run"), this._et("hours_run").replace("{h}", n(r.run_h, 0)));
    if (r.sun >= 0.05 || r.bat >= 0.05) h += line(this._et("sun"), kwh(r.sun) + (r.bat >= 0.05 ? ` \u00b7 ${kwh(r.bat)} ${this._et("bat")}` : "") + ` <small>(${this._et("sun_note")})</small>`);
    if (r.dd >= 0.5) h += line(this._et("dd"), `${n(r.dd, 1)} \u00b7 ${n(pdd, 2)} ${this._et("per_dd")}${vs}`);
    if (r.cost !== null && r.cost !== undefined) {
      const part = [["c_heat", r.cost_heat], ["c_dhw", r.cost_dhw], ["c_ind", r.cost_ind], ["c_rest", r.cost_rest]]
        .filter((x) => x[1] >= 0.005).map((x) => `${this._et(x[0])} ${this._money(x[1])}`).join(" \u00b7 ");
      h += line(this._et("cost"), `${this._money(r.cost)} ${this._et("tot")}${part ? ` \u00b7 ${part}` : ""}${r.priced > 0.05 ? ` \u00b7 ${n(100 * r.cost / r.priced, 0)} ct/kWh` : ""}`);
    }
    return `<div class="edet">${h}</div>`;
  }
  _energyBody() {
    const per = this._ePer || "day", got = this._eData && this._eData[per];
    if ((!got || Date.now() - got.at > 300000) && this._eLoading !== per) this._fetchEnergy(per);
    const p = (v) => `<span data-ep="${v}" class="${per === v ? "on" : ""}" role="button" tabindex="0">${this._et(v)}</span>`;
    let html = `<div class="hbar"><div class="seg erng">${p("hour")}${p("day")}${p("week")}${p("month")}</div>` +
      `<button class="ecsv"${got ? "" : " disabled"}><ha-icon icon="mdi:file-delimited-outline"></ha-icon>${this._et("csv")}</button></div>`;
    if (!got) return html + `<div class="na">${this._eErr || this._et("loading")}</div>`;
    const d = got.d;
    const rows = (d.rows || []).filter((r) => r.e_heat + r.e_dhw + r.e_ind + r.e_rest + r.q_heat > 0.005);
    if (!rows.length) return html + `<div class="na">${this._et("none")}</div>`;
    const wide = (this._chartW || 0) >= 640, n = (v, k) => (v === null || v === undefined ? "\u2014" : this._num(v, k));
    const cols = (r, lab) => {
      const e = r.e_heat + r.e_dhw + r.e_ind + r.e_rest;
      let c = `<span>${lab}</span><span>${n(r.t_out, 1)}\u00b0</span>`;
      if (wide) c += `<span>${n(r.flow, 1)}\u00b0</span><span>${n(r.q_heat - r.q_def + r.q_dhw, 1)}</span>`;
      c += `<span>${n(e, e >= 10 ? 0 : 1)}</span><span class="ix ${this._eTone(r.index)}">${n(r.cop_pump, 1)}</span>` +
        `<span class="ix ${this._eTone(r.index)}">${r.index === null || r.index === undefined ? "\u2014" : n(r.index, 0) + "%"}</span>`;
      if (wide) c += `<span>${this._eTimes(r)}</span><span>${n(r.run_h, 0)} ${this._et("hu")}</span><span>${r.sun >= 0.05 ? n(r.sun, 1) : "\u2013"}</span>`;
      return c + `<span>${r.cost === null || r.cost === undefined ? "\u2014" : this._money(r.cost, Math.abs(r.cost) >= 100 ? 0 : 2)}</span>`;
    };
    const head = `<div class="tr eh th"><span>${this._et("per")}</span><span>${this._et("out")}</span>` +
      (wide ? `<span>${this._et("flow")}</span><span>${this._et("heat")} <small>kWh</small></span>` : "") +
      `<span>${wide ? this._et("elec_tot") + " <small>kWh</small>" : this._et("kwh")}</span><span>${this._et("cop")}</span><span>${this._et("idx")}</span>` +
      (wide ? `<span>${this._et("dfr")}</span><span>${this._et("run")}</span><span>${this._et("sun")} <small>kWh</small></span>` : "") +
      `<span>${wide ? this._et("cost_tot") : this._et("cost")}</span></div>`;
    const sum = this._eSum(rows);
    let body = `<div class="tr er tot" data-es="tot" role="button" tabindex="0">${cols(sum, `<b>${this._et("total")}</b>`)}</div>` +
      (this._eOpen === "tot" ? this._eDetail(sum, null) : "");
    const list = rows.slice().reverse();          // newest first
    let catchUp = false;
    list.forEach((r, i) => {
      const k = String(r.start), prev = list[i + 1] || null;
      if (r.catch_up) catchUp = true;
      // what the unit did that hour: a coloured dot (no emoji: wall tablets often lack the font), a flake for defrosting
      const g = r.status && r.status !== "idle" ? `<i class="eg ${r.status}" title="${this._et("st_" + r.status)}">${r.status === "defrost" ? "\u2744" : "\u25cf"}</i>` : "";
      const lab = g + this._eLabel(r, per, i === 0) + (r.catch_up ? "*" : "");
      body += `<div class="tr er${this._eOpen === k ? " open" : ""}" data-es="${k}" role="button" tabindex="0">${cols(r, lab)}</div>` +
        (this._eOpen === k ? this._eDetail(r, prev) : "");
    });
    const notes = `<div class="enote">${this._et("idx_help")}` +
      `${catchUp ? `<br>${this._et("catch")}` : ""}</div>`;
    return html + `<div class="escope">${this._et("scope")}</div><div class="ptable etab${wide ? " wide" : ""}">${head}${body}</div>${notes}`;
  }
  _energyCsv() {
    const per = this._ePer || "day", got = this._eData && this._eData[per];
    if (!got) return;
    const keys = ["t_out", "t_min", "flow", "room", "q_heat", "q_def", "q_dhw", "e_heat", "e_dhw", "e_ind", "e_rest", "cop_pump", "cop_heat", "cop_dhw", "cop_all", "index", "defrosts", "run_h", "sun", "dd", "cost", "status"];
    const nl = this._lang() !== "en", sep = nl ? ";" : ",";
    const v = (x) => (x === null || x === undefined ? "" : typeof x === "number" ? (nl ? String(x).replace(".", ",") : String(x)) : String(x));
    const lines = [["start"].concat(keys).join(sep)];
    got.d.rows.forEach((r) => {
      const t = new Date(r.start * 1000), iso = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")} ${String(t.getHours()).padStart(2, "0")}:00`;
      lines.push([iso].concat(keys.map((k) => v(r[k]))).join(sep));
    });
    this._download("\ufeff" + lines.join("\r\n"), `roost-energy-${per}-${new Date().toISOString().slice(0, 10)}.csv`);
  }

  // ---------------------------------------------------------------- look back (websocket roost/history)
  _histOn() { return this._config.history !== false && !this._config.compact; }

  _fetchHist() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    this._hass.callWS({ type: "roost/history", entity_id: this._config.entity, days: 7 }).then((d) => {
      this._hist = d; this._histAt = Date.now(); this._histErr = null; this._loading = false; this._render();
    }).catch((e) => { this._histErr = String((e && e.message) || e); this._loading = false; this._render(); });
  }

  _histSlice() {
    const d = this._hist || { hours: [], events: [], days: {} };
    const t1 = Math.floor(Date.now() / 3600000) * 3600 + 3600, t0 = t1 - this._range * 3600;
    const hours = d.hours.filter((h) => h.ts >= t0 && h.ts < t1);
    const evTs = (e) => new Date(e.t).getTime() / 1000;
    const events = d.events.filter((e) => evTs(e) >= t0 && evTs(e) < t1).map((e) => Object.assign({ ts: evTs(e) }, e));
    return { d, t0, t1, hours, events };
  }

  _histBody() {
    if (!this._hist || Date.now() - (this._histAt || 0) > 300000) this._fetchHist();
    if (!this._hist) return `<div class="na">${this._histErr || this._t("h_loading")}</div>`;
    const s = this._histSlice();
    if (!s.hours.length) return this._rangeBar() + `<div class="na">${this._t("h_nodata")}</div>`;
    return this._rangeBar() + this._histTiles(s) + this._shadowSum(s) + this._srcLine(s.hours) + this._histChart(s) + this._histLog(s);
  }

  // OpenTherm in shadow mode, the period in two lines of numbers: the hours and heat Roost would have asked against
  // what the unit did (on its own curve)
  _shadowSum(s) {
    const hs = s.hours.filter((h) => h.ot && h.mode === "shadow");
    if (!hs.length) return "";
    const wouldH = hs.filter((h) => h.flow > 0).length, wouldKwh = hs.reduce((t, h) => t + (h.flow > 0 ? h.sp_t || 0 : 0), 0);
    const didH = hs.filter((h) => (h.q || 0) >= 0.2).length, didKwh = hs.reduce((t, h) => t + (h.q || 0), 0);
    const r = { 24: "24 h", 48: "48 h", 168: "7 d" }[this._range] || `${this._range} h`;
    return `<div class="pline shsum" data-k="shsum">${this._ot("sum").replace("{r}", r).replace("{a}", wouldH).replace("{b}", this._num(wouldKwh, 1))
      .replace("{c}", didH).replace("{d}", this._num(didKwh, 1))}</div>`;
  }
  _rangeBar() {
    const r = (v, l) => `<span data-r="${v}" class="${this._range === v ? "on" : ""}">${l}</span>`;
    return `<div class="hbar"><div class="seg rng">${r(24, "24 h")}${r(48, "48 h")}${r(168, "7 d")}</div>` +
      `<button class="rep"><ha-icon icon="mdi:file-download-outline"></ha-icon>${this._t("h_report")}</button></div>`;
  }

  _histStats(s) {
    const comfort = nn(s.d.comfort, 20.5);
    const costed = s.hours.filter((h) => h.cost !== undefined && h.cost !== null);
    const cost = costed.length ? costed.reduce((t, h) => t + h.cost, 0) : null;
    const days = Object.keys(s.d.days || {}).filter((k) => new Date(k + "T12:00:00").getTime() / 1000 >= s.t0);
    const sav = days.map((k) => s.d.days[k].saving).filter((v) => v !== undefined && v !== null);
    const errs = s.hours.filter((h) => h.p6 !== null && h.p6 !== undefined).map((h) => ({ ts: h.ts, e: h.T - h.p6 }));
    const mae = errs.length ? errs.reduce((t, x) => t + Math.abs(x.e), 0) / errs.length : null;
    const worst = errs.reduce((m, x) => (!m || Math.abs(x.e) > Math.abs(m.e) ? x : m), null);
    const dayH = s.hours.filter((h) => h.day);
    const below = dayH.filter((h) => !h.away && h.T < comfort - 0.3)
      .reduce((n, h) => n + (h.comfort_mask ? 15 * h.comfort_mask.filter(Boolean).length : 60), 0);
    const low = s.hours.length ? Math.min.apply(null, s.hours.map((h) => h.T)) : null;
    let roost = 0;
    for (let i = 1; i < s.hours.length; i++) {
      const a = this._hset(s.hours[i - 1]), b = this._hset(s.hours[i]);
      if (a !== null && b !== null && a !== undefined && b !== undefined && Math.abs(a - b) >= 0.25) roost++;
    }
    const hand = s.events.filter((e) => e.kind === "by_hand").length;
    return { cost, sav: sav.length ? sav.reduce((t, v) => t + v, 0) : null, mae, worst, below, low, roost: Math.max(0, roost - hand), hand };
  }

  _histTiles(s) {
    const st = this._histStats(s);
    const tile = (label, value, sub) => `<div class="tile htile"><div class="tl">${label}</div><div class="tv">${value}</div><div class="ts">${sub}</div></div>`;
    return `<div class="tiles four">` +
      tile(this._et("heat_only"), st.cost !== null ? this._money(st.cost) : "\u2014", st.sav !== null ? `${this._t("h_saving")} ${this._money(st.sav)}` : "&nbsp;") +
      tile(this._t("h_pred"), st.mae !== null ? `\u00b1 ${this._num(st.mae, 1)}<span>${DEG}</span>` : "\u2014",
        st.worst ? `${this._t("h_largest")} ${this._num(Math.abs(st.worst.e), 1)} (${this._hour(new Date(st.worst.ts * 1000))})` : "&nbsp;") +
      tile(this._t("h_below"), `${st.below}<span>min</span>`, st.low !== null ? `${this._t("h_lowest")} ${this._num(st.low, 1)} ${DEG}` : "&nbsp;") +
      tile(this._t("h_changes"), `${st.roost} + ${st.hand}`, `${this._t("h_byroost")} \u00b7 ${this._t("h_byhand")}`) + `</div>`;
  }

  // The setting of a logged hour as a value to compare: a thermostat setting (degC), or under OpenTherm the flow
  // Roost asked or would have asked (0: off). An OpenTherm hour's sp_t / sp_plan are heat outputs (kW), never
  // temperatures: they must not land on the degC scale.
  _hset(h) { return h.ot ? nn(h.flow, null) : nn(h.sp_t, null); }
  _hsetTxt(h) { const v = this._hset(h); return h.ot && v !== null && !(v > 0) ? this._ot("off") : (v === null ? "\u2014" : `${this._num(v, 1)}\u00b0`); }

  _histChart(s) {
    // drawn in the card's own pixels, like the plan: text keeps its size on a wide dashboard
    const VW = Math.max(300, Math.min(1600, (this._chartW || 472) - 32)), VH = 190, L = 28, R = 26, TOP = 14, B = 58, n = this._range;
    const w = (VW - L - R) / n, x = (ts) => L + (ts - s.t0) / 3600 * w;
    const by = {}; s.hours.forEach((h) => { by[h.ts] = h; });
    const ot = s.hours.some((h) => h.ot);
    const vals = [];
    s.hours.forEach((h) => { [h.T, h.p6].concat(h.ot ? [] : [h.sp_t, h.sp_plan]).forEach((v) => { if (v !== null && v !== undefined && !isNaN(v)) vals.push(v); }); });
    const lo = Math.floor(Math.min.apply(null, vals) - 0.3), hi = Math.ceil(Math.max.apply(null, vals) + 0.3);
    const y = (v) => TOP + (hi - v) / Math.max(0.5, hi - lo) * (VH - TOP - B);
    // OpenTherm: the flows on their own scale (right), what Roost would ask against what the unit made
    const flows = [];
    s.hours.forEach((h) => { if (h.ot) [h.flow, h.flow_meas].forEach((v) => { if (v > 0) flows.push(v); }); });
    const flo = flows.length ? Math.floor(Math.min.apply(null, flows) - 2) : 20, fhi = flows.length ? Math.ceil(Math.max.apply(null, flows) + 2) : 40;
    const yf = (v) => TOP + (fhi - v) / Math.max(1, fhi - flo) * (VH - TOP - B);
    const pb = VH - 18, ph = 30;
    const pmax = Math.max(0.01, Math.max.apply(null, s.hours.map((h) => h.p_grid || 0)));
    // heat per hour: what the unit made, and under OpenTherm the output Roost would have asked (same scale)
    const qmax = Math.max(0.5, Math.max.apply(null, s.hours.map((h) => Math.max(h.q || 0, h.ot ? (h.sp_t || 0) : 0))));
    const pmin = Math.min.apply(null, s.hours.map((h) => h.p_grid || 0));
    const tone = (p) => { const r = (p - pmin) / Math.max(0.01, pmax - pmin); return r < 0.33 ? "var(--rc-cheap)" : (r < 0.66 ? "var(--rc-mid)" : "var(--rc-dear)"); };
    let g = "";
    for (let v = Math.ceil(lo); v <= hi; v++) {
      g += `<line x1="${L}" x2="${VW - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/>` +
        `<text x="${L - 5}" y="${(y(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis">${v}\u00b0</text>`;
    }
    if (ot) {
      const fstep = Math.max(1, Math.ceil((fhi - flo) / 4));
      for (let v = Math.ceil(flo / fstep) * fstep; v <= fhi; v += fstep)
        g += `<text x="${VW - 2}" y="${(yf(v) + 3.5).toFixed(1)}" text-anchor="end" class="axis faxis">${v}\u00b0</text>`;
    }
    s.hours.forEach((h) => {
      const x0 = x(h.ts);
      if (h.paused) g += `<rect x="${x0.toFixed(1)}" y="${TOP}" width="${(w + 0.2).toFixed(1)}" height="${(pb - TOP).toFixed(1)}" class="hpause"/>`;
      if (h.ot && !(h.flow > 0)) g += `<rect x="${x0.toFixed(1)}" y="${TOP}" width="${(w + 0.2).toFixed(1)}" height="${(VH - B - TOP).toFixed(1)}" class="offcol"/>`;
      const p = h.p_grid || 0, q = h.q || 0, bw = Math.max(0.6, w / 2 - 0.6);
      const hp = 3 + p / pmax * (ph - 3), hq = q / qmax * (ph - 3);
      g += `<rect x="${(x0 + 0.3).toFixed(1)}" y="${(pb - hp).toFixed(1)}" width="${bw.toFixed(1)}" height="${hp.toFixed(1)}" style="fill:${tone(p)}" class="price"/>`;
      if (hq > 0.2) g += `<rect x="${(x0 + w / 2).toFixed(1)}" y="${(pb - hq).toFixed(1)}" width="${bw.toFixed(1)}" height="${hq.toFixed(1)}" class="hheat"/>`;
      const lv = h.ot ? (h.sp_t || 0) / qmax * (ph - 3) : 0;
      if (lv > 0.2) g += `<rect x="${(x0 + w / 2).toFixed(1)}" y="${(pb - lv).toFixed(1)}" width="${bw.toFixed(1)}" height="${lv.toFixed(1)}" class="hwould"/>`;
    });
    // a step line per hour; a gap where the value is missing (or, for a flow, off)
    const path = (get, Y, step) => {
      let d = "", pen = false;
      s.hours.forEach((h) => {
        const v = get(h);
        if (v === null || v === undefined || isNaN(v)) { pen = false; return; }
        d += step ? `${pen ? " L" : " M"}${x(h.ts).toFixed(1)} ${Y(v).toFixed(1)} L${(x(h.ts) + w).toFixed(1)} ${Y(v).toFixed(1)}`
          : `${pen ? " L" : " M"}${(x(h.ts) + w / 2).toFixed(1)} ${Y(v).toFixed(1)}`;
        pen = !!by[h.ts + 3600];
      });
      return d;
    };
    const temp = (k) => (h) => (h.ot ? null : h[k]);
    g += `<path d="${path(temp("sp_plan"), y, true)}" class="hplan"/><path d="${path(temp("sp_t"), y, true)}" class="sp"/>`;
    if (ot) g += `<path d="${path((h) => (h.ot && h.flow > 0 ? h.flow : null), yf, true)}" class="sp"/>` +
      `<path d="${path((h) => (h.ot && h.flow_meas > 0 ? h.flow_meas : null), yf, false)}" class="hmeas"/>`;
    g += `<path d="${path((h) => h.p6, y, false)}" class="hpred"/><path d="${path((h) => h.T, y, false)}" class="hroom"/>`;
    s.events.forEach((e) => {
      const tag = e.kind === "by_hand" ? "H" : (e.kind === "mode" ? "M" : (e.kind === "window" && e.phase === "open" ? this._t("h_win_mark") : ""));
      if (!tag) return;
      const xx = Math.max(L + 6, Math.min(VW - R - 6, x(e.ts)));
      g += `<circle cx="${xx.toFixed(1)}" cy="${TOP - 5}" r="5.5" class="hmark"/><text x="${xx.toFixed(1)}" y="${TOP - 2}" text-anchor="middle" class="hmt">${tag}</text>`;
    });
    s.hours.forEach((h) => {
      if (h.p6 !== null && h.p6 !== undefined && Math.abs(h.T - h.p6) >= 0.5) {
        g += `<circle cx="${(x(h.ts) + w / 2).toFixed(1)}" cy="${y(h.T).toFixed(1)}" r="3" class="hdev"/>`;
      }
    });
    const every = n <= 24 ? 6 : (n <= 48 ? 12 : 24);
    for (let i = 0; i <= n; i += every) {
      const t = new Date((s.t0 + i * 3600) * 1000);
      const lab = n > 48 ? t.toLocaleDateString(this._lang(), { weekday: "short" }) : this._hour(t);
      g += `<text x="${(L + i * w).toFixed(1)}" y="${VH - 4}" text-anchor="${i === 0 ? "start" : (i === n ? "end" : "middle")}" class="axis">${lab}</text>`;
    }
    g += `<line class="cur" x1="0" x2="0" y1="${TOP}" y2="${pb}"/><rect class="hit" x="${L}" y="${TOP}" width="${VW - L - R}" height="${pb - TOP}"/>`;
    this._hgeo = { L, w, n, t0: s.t0, by };
    const last = s.hours[s.hours.length - 1];
    // the legend names what is drawn: a period can hold thermostat hours and OpenTherm hours
    const th = s.hours.some((h) => !h.ot), item = (cls, text) => `<span><b class="l ${cls}"></b>${text}</span>`;
    const leg = (th ? item("sp", this._t("h_sp_t")) + item("hplan", this._t("h_sp_p")) : "") +
      (ot ? item("sp", this._ot("h_would")) + (s.hours.some((h) => h.flow_meas > 0) ? item("hmeas", this._ot("h_meas")) : "") : "") +
      item("hroom", this._t("h_room")) + item("hpred", this._t("h_pred6")) + item("price", this._t("price")) +
      item("hheat", ot ? this._ot("h_heat") : this._t("h_heat")) + (ot ? item("hwould", this._ot("h_heat_would")) + item("offcol", this._ot("h_off")) : "");
    return `<div class="chart hchart" data-k="hchart"><div class="ch"><span>${this._t("back")}</span><span class="info">${this._hinfo(last)} \u00b7 <i>${this._t("scrub")}</i></span></div>` +
      `<svg viewBox="0 0 ${VW} ${VH}">${g}</svg><div class="leg">${leg}</div></div>`;
  }

  _hinfo(h) {
    if (!h) return "";
    const t = this._hour(new Date(h.ts * 1000));
    const why = h.reason ? this._why(h.reason, h.args || {}, "") : "";
    const pred = h.p6 !== null && h.p6 !== undefined ? ` (${this._t("h_expected")} ${this._num(h.p6, 1)})` : "";
    const set = h.ot
      ? `${this._ot("sets")} <b class="o">${this._hsetTxt(h)}</b>${h.sp_t > 0 ? ` (${this._num(h.sp_t, 1)} kW)` : ""}` +
        ` \u00b7 ${this._ot("pump")} ${h.flow_meas > 0 ? `<b>${this._num(h.flow_meas, 1)}\u00b0</b>, ` : ""}<b>${this._num(h.q || 0, 1)} kWh</b>`
      : `${this._t("h_sp_p")} <b class="o">${this._num(h.sp_plan, 1)}${DEG}</b> / ${this._num(h.sp_t, 1)}${DEG}`;
    return `<b>${t}</b> \u00b7 ${set} \u00b7 ${this._t("room")} <b>${this._num(h.T, 1)}${DEG}</b>${pred} \u00b7 <b>${this._num((h.p_grid || 0) * 100, 0)} ct</b>` +
      `${h.ot ? "" : ` \u00b7 ${this._num(h.q || 0, 1)} kWh`}${why ? " \u00b7 " + why : ""}`;
  }

  _histItems(s) {
    const items = [];
    const by = {}; s.hours.forEach((h) => { by[h.ts] = h; });
    // what happened next: the room an hour later against what the plan expected for it
    const outcome = (ts) => {
      const nx = by[Math.floor(ts / 3600) * 3600 + 3600];
      if (!nx || nx.p1 === null || nx.p1 === undefined) return { out: "", cls: "" };
      const ok = Math.abs(nx.T - nx.p1) <= 0.3;
      return { out: `${this._t("h_room_after")} ${this._num(nx.T, 1)} (${this._t("h_expected")} ${this._num(nx.p1, 1)}) ${ok ? "\u2713" : "\u00b7 " + this._t("h_dev")}`,
               cls: ok ? "ok" : "warn" };
    };
    // shadow mode: what Roost would have set (the plan changed); active mode: what it did set (below)
    for (let i = 1; i < s.hours.length; i++) {
      const a = s.hours[i - 1], h = s.hours[i];
      if (h.mode !== "shadow") continue;
      const va = a.ot ? this._hset(a) : a.sp_plan, vh = h.ot ? this._hset(h) : h.sp_plan;
      if (va === null || vh === null || va === undefined || vh === undefined || Math.abs(va - vh) < 0.25) continue;
      items.push(Object.assign({ ts: h.ts, what: `\u2192 ${h.ot ? this._hsetTxt(h) : this._num(vh, 1) + DEG}`, why: this._why(h.reason, h.args || {}, "") }, outcome(h.ts)));
    }
    s.events.forEach((e) => {
      if (e.kind === "set") {
        // older events have no values for the reason: leave the parts that need them out
        const why = e.args ? this._why(e.reason, e.args, "") : this._why(e.reason, {}, "").replace(/\s*\([^()]*\{\w+\}[^()]*\)|\s*\{\w+\}\S*/g, "");
        items.push(Object.assign({ ts: e.ts, what: `\u2192 ${this._num(e.new, 1)}${DEG}`, why }, outcome(e.ts)));
      }
      else if (e.kind === "by_hand") items.push({ ts: e.ts, what: `\u2192 ${this._num(e.new, 1)}${DEG}`, why: this._t("h_set_hand").replace("{h}", this._num(e.pause_h || 2, 0)), out: "", cls: "", hand: true });
      else if (e.kind === "pause") items.push({ ts: e.ts, what: "", why: this._t("h_pause_ev").replace("{h}", this._num(e.hours, 1)), out: "", cls: "", hand: true });
      else if (e.kind === "window") items.push({ ts: e.ts, what: "", why: this._t(e.phase === "open" ? "h_window" : "h_window_end") +
        (e.phase === "open" && e.before !== undefined && e.before !== null && e.room !== null && e.room !== undefined ?
          ` (${this._num(e.before, 1)} \u2192 ${this._num(e.room, 1)}${DEG})` : ""), out: "", cls: "", hand: e.phase === "open" });
      else if (e.kind === "resume") items.push({ ts: e.ts, what: "", why: this._t("h_resume"), out: "", cls: "" });
      else if (e.kind === "mode") items.push({ ts: e.ts, what: "", why: `${this._t("h_mode")}: ${this._t(e.new) || e.new}`, out: "", cls: "" });
      else if (e.kind === "learned" && String(e.house || "").indexOf("adopted") >= 0) items.push({ ts: e.ts, what: "", why: this._t("h_learned"), out: "", cls: "" });
    });
    return items.sort((a, b) => b.ts - a.ts);
  }

  _histLog(s) {
    const items = this._histItems(s);
    const when = (ts) => {
      const d = new Date(ts * 1000);
      return (this._range > 24 && d.toDateString() !== new Date().toDateString() ? d.toLocaleDateString(this._lang(), { weekday: "short" }) + " " : "") + this._hour(d);
    };
    const rows = this._logOpen ? items.slice(0, 60).map((it) => `<div class="lrow"><span>${when(it.ts)}</span><span>${it.what}</span>` +
      `<span class="${it.hand ? "warn" : "mut"}">${it.why}</span><span class="${it.cls}">${it.out}</span></div>`).join("") : "";
    return `<div class="hlog"><div class="lhead">${this._t("h_log")} (${items.length}) ${this._logOpen ? "\u25be" : "\u25b8"}</div>${rows}</div>`;
  }

  // A page to keep or share: the period's numbers, the graph, the log and the days (built here, nothing is sent)
  _report() {
    const html = this._reportHtml();
    const name = `roost-${new Date().toISOString().slice(0, 10)}.html`;
    // a phone or tablet: the share sheet (save to Files, mail, AirDrop). Safari on iOS ignored the download link
    // (issue #7); a computer keeps the download
    const touch = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    if (touch && navigator.canShare && navigator.share && typeof File === "function") {
      const file = new File([html], name, { type: "text/html" });
      if (navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: name }).catch((e) => { if (!e || e.name !== "AbortError") this._download(html, name); });
        return;
      }
    }
    this._download(html, name);
  }

  _download(html, name) {
    const a = document.createElement("a");
    // as a file, not a page: Safari would rather show a page than save it. Removed later: removing the link at once
    // can cancel a download Safari has not started yet
    a.href = URL.createObjectURL(new Blob([html], { type: "application/octet-stream" }));
    a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { a.remove(); URL.revokeObjectURL(a.href); }, 10000);
  }

  _reportHtml() {
    const s = this._histSlice(), st = this._histStats(s);
    const svg = this.shadowRoot.querySelector(".hchart svg");
    const esc = (v) => String(v === undefined || v === null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const strip = (h) => String(h).replace(/<[^>]+>/g, "");
    const fromTo = `${new Date(s.t0 * 1000).toLocaleString(this._locale())} \u2013 ${new Date(s.t1 * 1000).toLocaleString(this._locale())}`;
    const days = Object.keys(s.d.days || {}).sort().reverse().slice(0, 62);
    const dayRows = days.map((k) => {
      const v = s.d.days[k];
      return `<tr><td>${k}</td><td>${this._num(v.kwh, 1)}</td><td>${this._num(v.heat_kwh, 1)}</td><td>${v.cop ? this._num(v.cop, 1) : "\u2014"}</td>` +
        `<td>${this._money(v.cost)}</td><td>${v.saving !== undefined ? this._money(v.saving) : "\u2014"}</td><td>${this._num(v.deficit_ch, 1)}</td>` +
        `<td>${v.changes} + ${v.by_hand}</td><td>${v.pred_mae !== null && v.pred_mae !== undefined ? "\u00b1" + this._num(v.pred_mae, 2) : "\u2014"}</td></tr>`;
    }).join("");
    const logRows = this._histItems(s).map((it) => `<tr><td>${new Date(it.ts * 1000).toLocaleString(this._locale())}</td><td>${esc(strip(it.what))}</td>` +
      `<td>${esc(strip(it.why))}</td><td>${esc(strip(it.out))}</td></tr>`).join("");
    // where the saving comes from, hour by hour (planner.breakdown), and why the plan changed (replan.py)
    const m3 = (v) => {
      if (v === null || v === undefined || isNaN(v)) return "\u2014";
      const cur = (this._hass && this._hass.config && this._hass.config.currency) || "EUR";
      try { return Number(v).toLocaleString(this._locale(), { style: "currency", currency: cur, minimumFractionDigits: 3, maximumFractionDigits: 3 }); } catch (e) { return this._num(v, 3); }
    };
    const sd = s.d.saving_detail || {};
    const lastDay = Object.keys(sd).sort().pop();
    const savTable = (bd, title) => {
      if (!bd || !bd.hours || !bd.hours.length) return `<h3>${esc(title)}</h3><p>${esc(this._t("r_none"))}</p>`;
      const th = (k) => `<th>${esc(this._t(k))}</th>`;
      // the tariff (price sensor, formula or contract) and what the plan counts: they differ while a home battery
      // supplies the house (the price of buying that kWh back later); hours logged by older versions have no tariff
      const tar = (r) => (r.tariff === null || r.tariff === undefined ? "\u2014" : m3(r.tariff)) + (r.guess ? " (" + esc(this._t("guessed")) + ")" : "");
      const differs = bd.hours.some((r) => r.tariff === null || r.tariff === undefined || Math.abs(r.tariff - r.price) >= 0.0005);
      const rows = bd.hours.map((r) => `<tr><td>${r.ts ? esc(this._hour(new Date(r.ts * 1000))) : esc(r.hour)}${r.sun ? " \u2600" : ""}</td><td>${this._num(r.t_out, 1)}</td><td>${tar(r)}</td><td>${m3(r.price)}</td>` +
        `<td>${this._num(r.sp, 1)}</td><td>${this._num(r.t, 1)}</td><td>${this._num(r.kwh, 2)}</td><td>${m3(r.cost)}</td>` +
        `<td>${this._num(r.b_sp, 1)}</td><td>${this._num(r.b_t, 1)}</td><td>${this._num(r.b_kwh, 2)}</td><td>${m3(r.b_cost)}</td><td><b>${m3(r.save)}</b></td></tr>`).join("");
      const note = this._t("r_note").replace("{a}", this._num(bd.short, 1)).replace("{b}", this._num(bd.b_short, 1));
      return `<h3>${esc(title)}</h3><p>${esc(this._savingQuality(bd.quality))}</p><table><tr><th></th><th></th><th></th><th></th><th colspan="4">${esc(this._t("r_roost"))}</th><th colspan="4">${esc(this._t("r_steady"))}</th><th></th></tr>` +
        `<tr>${th("r_hour")}${th("r_out")}${th("price")}${th("uses")}${th("r_sp")}${th("r_room")}${th("h_kwh")}${th("r_cost")}${th("r_sp")}${th("r_room")}${th("h_kwh")}${th("r_cost")}${th("r_diff")}</tr>${rows}` +
        `<tr><td><b>${esc(this._t("r_sum"))}</b></td><td></td><td></td><td></td><td></td><td></td><td>${this._num(bd.kwh, 1)}</td><td>${m3(bd.cost)}</td><td></td><td></td><td>${this._num(bd.b_kwh, 1)}</td><td>${m3(bd.b_cost)}</td><td>${m3(bd.b_cost - bd.cost)}</td></tr>` +
        `<tr><td colspan="7">${esc(this._t("r_end"))}</td><td>${m3(bd.end)}</td><td colspan="3"></td><td>${m3(bd.b_end)}</td><td>${m3(bd.b_end - bd.end)}</td></tr>` +
        `<tr><td colspan="12"><b>${esc(this._t("r_total"))}</b></td><td><b>${this._money(bd.saving)}</b></td></tr></table>` +
        (bd.parts ? `<table><tr><th colspan="2">${esc(this._t("p_title"))}</th></tr>` +
          `<tr><td>${esc(this._t("p_less"))}</td><td>${m3(bd.parts.less_kwh)}</td></tr>` +
          `<tr><td>\u2003\u2600 ${esc(this._t("p_sun"))}</td><td>${m3(bd.parts.sun)}</td></tr>` +
          `<tr><td>${esc(this._t("p_cheap"))}</td><td>${m3(bd.parts.cheaper_hours)}</td></tr>` +
          `<tr><td>${esc(this._t("p_end"))}</td><td>${m3(bd.parts.end)}</td></tr>` +
          `<tr><td><b>${esc(this._t("r_total"))}</b></td><td><b>${this._money(bd.saving)}</b></td></tr></table>` : "") +
        `<p>${esc(note)}</p>` + (differs ? `<p>${esc(this._t("r_uses_note"))}</p>` : "");
    };
    const cause = (c, dt) => {
      const n = dt[c] !== undefined ? dt[c] : 0;
      return (this._t("c_" + c) || c).replace("{n}", n).replace("{r}", this._num(dt.room, 1)).replace("{e}", this._num(dt.room_expected, 1));
    };
    const chg = (s.d.plan_changes || []).filter((c) => c.ts >= s.t0).slice().reverse();
    const chgRows = chg.map((c) => `<tr><td>${new Date(c.ts * 1000).toLocaleString(this._locale())}</td>` +
      `<td>${this._num(c.sp[0], 1)} \u2192 ${this._num(c.sp[1], 1)}${DEG}</td><td>${this._money(c.saving[0])} \u2192 ${this._money(c.saving[1])}</td>` +
      `<td>${esc(c.why.map((w) => cause(w, c.detail || {})).join("; "))}</td></tr>`).join("");
    const savHtml = `<h2>${esc(this._t("r_sav"))}</h2>` + savTable(lastDay ? sd[lastDay] : null, `${this._t("r_yday")}${lastDay ? " (" + lastDay + ")" : ""}`) +
      savTable(s.d.next, this._t("r_next")) +
      `<h2>${esc(this._t("r_changes"))}</h2>` + (chgRows ? `<table><tr><th>${esc(this._t("t_time"))}</th><th>${esc(this._t("r_ch_sp"))}</th><th>${esc(this._t("r_ch_sav"))}</th><th>${esc(this._t("t_why"))}</th></tr>${chgRows}</table>`
        : `<p>${esc(this._t("r_nochg"))}</p>`);
    const css = `body{font-family:system-ui,sans-serif;margin:24px;color:#222}h1{font-size:20px}table{border-collapse:collapse;font-size:13px;margin:8px 0 20px}
      td,th{border-bottom:1px solid #ddd;padding:4px 8px;text-align:left}svg{max-width:760px;width:100%}
      .grid{stroke:#e5e5e5}.axis{fill:#777;font-size:10px}.sp{fill:none;stroke:#fb923c;stroke-width:2.2}.hplan{fill:none;stroke:#fb923c;stroke-width:1.5;stroke-dasharray:4 3}
      .hroom{fill:none;stroke:#222;stroke-width:2}.hpred{fill:none;stroke:#378add;stroke-width:1.5;stroke-dasharray:4 3}.price{opacity:.55}
      .hheat{fill:#f0997b;opacity:.8}.hpause{fill:#f5a524;opacity:.12}.hmark{fill:#fde7c2;stroke:#ba7517}.hmt{fill:#7a4a06;font-size:8px}.hdev{fill:#e5484d}
      .cur,.hit{display:none}:root{--rc-cheap:#30a46c;--rc-mid:#f5a524;--rc-dear:#e5484d}`;
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Roost \u2013 ${esc(this._t("back"))}</title><style>${css}</style></head><body>
      <h1>Roost \u2013 ${esc(this._t("back"))}</h1><p>${esc(this._t("h_period"))}: ${esc(fromTo)}</p>
      <table><tr><th>${esc(this._t("h_cost"))}</th><th>${esc(this._t("h_saving"))}</th><th>${esc(this._t("h_pred"))}</th><th>${esc(this._t("h_below"))}</th><th>${esc(this._t("h_changes"))}</th></tr>
      <tr><td>${st.cost !== null ? this._money(st.cost) : "\u2014"}</td><td>${st.sav !== null ? this._money(st.sav) : "\u2014"}</td><td>${st.mae !== null ? "\u00b1" + this._num(st.mae, 2) + " \u00b0C" : "\u2014"}</td>
      <td>${st.below} min</td><td>${st.roost} + ${st.hand}</td></tr></table>
      ${svg ? svg.outerHTML : ""}
      <h2>${esc(this._t("h_log"))}</h2><table>${logRows}</table>
      <h2>${esc(this._t("h_day"))}</h2><table><tr><th>${esc(this._t("h_day"))}</th><th>${esc(this._t("h_kwh"))}</th><th>${esc(this._t("h_heat"))}</th><th>${esc(this._t("h_cop"))}</th>
      <th>${esc(this._t("h_cost"))}</th><th>${esc(this._t("h_saving"))}</th><th>${esc(this._t("h_deficit"))}</th><th>${esc(this._t("h_changes"))}</th><th>${esc(this._t("h_pred"))}</th></tr>${dayRows}</table>
      ${savHtml}
      </body></html>`;
    return html;
  }

  _style() {
    return `<style>
      :host { --rc-sp: #fb923c; --rc-cheap: var(--success-color, #30a46c); --rc-mid: var(--warning-color, #f5a524); --rc-dear: var(--error-color, #e5484d);
              --rc-band: var(--success-color, #30a46c); --rc-room: var(--primary-text-color); }
      ha-card { display: block; padding: 16px; cursor: pointer; container-type: inline-size; }
      .na { color: var(--secondary-text-color); padding: 8px 0; }
      .head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
      @container (max-width: 520px) { .head .seg { order: 5; flex: 1 1 100%; } .head .seg span { flex: 1; text-align: center; } }
      .ico { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: none;
             background: color-mix(in srgb, var(--rc-sp) 18%, transparent); color: var(--rc-sp); }
      .ht { flex: 1; min-width: 0; } .tt { font-size: 16px; font-weight: 600; }
      .sub { font-size: 12px; color: var(--secondary-text-color); overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
      
      
      .tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
        
      .chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; display: inline-flex; align-items: center; gap: 3px; }
      .chip ha-icon { --mdc-icon-size: 13px; color: inherit; }
      
      .chip.calpill { cursor: pointer; background: color-mix(in srgb, var(--success-color, #30a46c) 16%, transparent); color: var(--success-color, #30a46c); }
      .chip.calpill.on { outline: 1px solid var(--success-color, #30a46c); }
      .tile.rtile.warm { background: linear-gradient(160deg, color-mix(in srgb, var(--rc-sp) 12%, transparent), transparent 70%); }
      .tile.rtile.cool { background: linear-gradient(160deg, color-mix(in srgb, var(--info-color, #3b82f6) 12%, transparent), transparent 70%); }
      .spark { width: 100%; height: 22px; display: block; margin: 2px 0; } .spark path { fill: none; stroke-width: 1.6; stroke: var(--rc-room); }
      .spark .sp2 { stroke-dasharray: 3 3; opacity: .7; } .spark .spn { stroke: var(--divider-color); stroke-width: 1; }
      .nx { display: inline-flex; align-items: center; gap: 2px; font-size: 11px; font-weight: 600; } .nx ha-icon { --mdc-icon-size: 14px; }
      .nx.up { color: var(--rc-sp); } .nx.dn { color: var(--info-color, #3b82f6); }
      .tl i.hot { width: 7px; height: 7px; border-radius: 50%; background: var(--rc-sp); margin-left: auto; }
      rect.sun { fill: #f5c542; opacity: .28; } .l.sun { background: #f5c542; opacity: .6; } .l.pump { background: var(--rc-sp); }
      
      
      .cal { margin: -4px 0 10px; padding: 8px 10px; border: 1px solid var(--divider-color); border-radius: 10px; } .cgrid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 3px; max-width: 260px; }
      .cwd { font-size: 10.5px; color: var(--secondary-text-color); text-align: center; }
      .cd { height: 20px; border-radius: 5px; font-size: 10.5px; display: flex; align-items: center; justify-content: center;
        color: var(--secondary-text-color); border: 1px solid var(--divider-color); }
      .cd.ok { background: var(--success-color, #30a46c); border-color: transparent; color: #fff; font-weight: 600; }
      .cd.bad { background: color-mix(in srgb, var(--secondary-text-color) 30%, transparent); border-color: transparent; color: var(--primary-text-color); cursor: pointer; }
      .cd.future { border-style: dashed; opacity: .45; } .cd.sel { outline: 2px solid var(--rc-sp); }
      .calleg { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px; font-size: 11px; color: var(--secondary-text-color); }
      .calleg span { display: inline-flex; align-items: center; gap: 5px; }
      .calleg i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; border: 1px solid var(--divider-color); }
      .calleg i.ok { background: var(--success-color, #30a46c); border-color: transparent; }
      .calleg i.bad { background: color-mix(in srgb, var(--secondary-text-color) 30%, transparent); border-color: transparent; }
      .cwhy { font-size: 11.5px; color: var(--secondary-text-color); margin-top: 4px; }
      .week { flex: 1 1 100%; } .wtog { display: inline-flex; gap: 4px; } .mini.on { border-color: var(--rc-sp); color: var(--rc-sp); }
      .wgrid { margin: 6px 0; } .wrow { display: flex; align-items: center; gap: 8px; margin: 3px 0; cursor: pointer; font-size: 12px; }
      .wrow > span { width: 22px; color: var(--secondary-text-color); } .wrow.sel > span { color: var(--rc-sp); font-weight: 700; }
      .wbar { position: relative; flex: 1; height: 16px; border-radius: 4px; background: color-mix(in srgb, var(--secondary-text-color) 12%, transparent); }
      .wrow.sel .wbar { outline: 1px solid var(--rc-sp); }
      .wbar i { position: absolute; top: 2px; bottom: 2px; border-radius: 3px; background: linear-gradient(90deg, var(--rc-band), color-mix(in srgb, var(--rc-band) 70%, transparent)); }
      .wbar i.over { opacity: .55; }
      .waxis { display: flex; justify-content: space-between; margin-left: 30px; font-size: 10.5px; color: var(--secondary-text-color); }
      .wedit { border: 1px solid var(--divider-color); border-radius: 10px; padding: 8px 10px; } .wday { font-weight: 700; margin: 4px 0; }
      .wper { display: flex; align-items: center; gap: 4px; margin: 3px 0; font-size: 13px; } .wper .del { margin-left: auto; }
      .wbtns { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; } .mini.save { border-color: var(--rc-sp); color: var(--rc-sp); font-weight: 700; }
      .wmsg { font-size: 12px; margin-top: 6px; } .wmsg.ok { color: var(--success-color, #30a46c); } .wmsg.err { color: var(--error-color, #e5484d); }
      .tile { border: 1px solid var(--divider-color); border-radius: 12px; padding: 9px 11px; min-width: 0; }
      .rooms { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
      .room { font-size: 11.5px; color: var(--secondary-text-color); border: 1px solid var(--divider-color); border-radius: 999px; padding: 3px 9px; }
      .room b { color: var(--primary-text-color); font-weight: 600; } .room i { font-style: normal; opacity: .75; }
      .room.cold { border-color: var(--warning-color, #f5a524); color: var(--warning-color, #f5a524); }
      .tl { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--secondary-text-color); }
      .tl ha-icon { --mdc-icon-size: 15px; }
      .tv { font-size: 21px; font-weight: 700; margin-top: 3px; white-space: nowrap; } .tv.big { font-size: 25px; }
      .tv span { font-size: .55em; font-weight: 500; color: var(--secondary-text-color); margin-left: 2px; }
      .tile.plan .tv { color: var(--rc-sp); }
      .ts { font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .chart { margin-top: 14px; cursor: default; touch-action: pan-y; user-select: none; -webkit-user-select: none; }
      .ch { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
      .ch > span:first-child { flex: none; white-space: nowrap; }
      @container (max-width: 520px) { .tile .ts { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; } }
      .info { font-weight: 400; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      /* a phone: the hour's line under the title, two lines high whatever it says (scrubbing never moves the graph) */
      @container (max-width: 520px) {
        .ch { flex-direction: column; gap: 2px; }
        .ch .info { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; min-height: 2.7em; line-height: 1.35; }
      }
      .info b.o { color: var(--rc-sp); } .info i { font-style: normal; opacity: .8; }
      .chart.on .info i { display: none; }
      
      .mmenu { display: flex; gap: 6px; flex-wrap: wrap; margin: 2px 0 8px; }
      .mopt { flex: 1 1 120px; text-align: left; border: 1px solid var(--divider-color); border-radius: 10px; padding: 6px 9px;
        background: none; color: var(--primary-text-color); font: inherit; cursor: pointer; }
      .mopt.on { border-color: var(--rc-sp); } .mopt b { display: block; font-size: 13px; }
      .mopt small { color: var(--secondary-text-color); font-size: 11px; }
      .tile.plan, .tile.therm { cursor: pointer; }
      .mrow { flex: 1 1 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; border: 1px solid var(--divider-color);
        border-radius: 10px; padding: 6px 9px; font-size: 13px; } .mrow > span { display: inline-flex; gap: 6px; align-items: center; }
      .mrow small { flex: 1 1 100%; color: var(--secondary-text-color); font-size: 11px; }
      .spanel { flex: 1 1 100%; border: 1px solid var(--divider-color); border-radius: 10px; padding: 4px 9px; }
      .srow { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; }
      .srow + .srow { border-top: 1px solid var(--divider-color); } .srow > span:last-child { display: inline-flex; gap: 6px; align-items: center; }
      .sv { min-width: 3.6em; text-align: center; font-weight: 600; }
      .mini { border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); border-radius: 8px; padding: 3px 9px;
        font: inherit; font-size: 12px; cursor: pointer; } 
      .srcl { font-size: 12px; color: var(--secondary-text-color); margin: 4px 0 8px; }
      .sbar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; margin-bottom: 4px; background: var(--divider-color); }
      .sbar i { display: block; height: 100%; } i.ss { background: #f5b301; } i.sb { background: #22a06b; } i.sg { background: #8a8f98; }
      .srcl b.ss { color: #d99a00; font-weight: 500; } .srcl b.sb { color: #22a06b; font-weight: 500; } .srcl b.sg { font-weight: 500; }
      .tloss { font-size: 12px; color: var(--warning-color, #f59e0b); margin: 0 0 4px; }
      .warnline { display: flex; gap: 6px; align-items: flex-start; font-size: 12px; margin: -4px 0 10px; padding: 6px 9px; border-radius: 8px;
        color: var(--warning-color, #f59e0b); background: color-mix(in srgb, var(--warning-color, #f59e0b) 12%, transparent); }
      .warnline ha-icon { --mdc-icon-size: 16px; flex: none; } .head .ico { cursor: pointer; }
      .czone { fill: var(--secondary-text-color); opacity: .05; } .vgrid { opacity: .5; }
      .ccloud { fill: var(--primary-text-color); opacity: .22; } .cadv.dash { stroke-dasharray: 6 4; opacity: .7; }
      .l.ccl { background: var(--primary-text-color); opacity: .5; border-radius: 50%; width: 6px !important; height: 6px !important; }
      .l.cdashl { background: none; border-top: 2px dashed var(--rc-sp); height: 0; }
      .cadv { fill: none; stroke: var(--rc-sp); stroke-width: 2.5; } .cdot { fill: var(--rc-sp); }
      .cval { fill: var(--rc-sp); font-size: 11px; font-weight: 600; } .cval.soft, .cdot.soft { opacity: .55; }
      .cleg { display: grid; gap: 3px; margin: 6px 0 2px; font-size: 12px; color: var(--secondary-text-color); }
      .cleg .l { display: inline-block; width: 14px; height: 3px; margin-right: 7px; vertical-align: middle; }
      .l.czl { background: var(--secondary-text-color); opacity: .25; height: 9px; }
      .curve tr.cz td { color: var(--secondary-text-color); } .curve tr.cz td b { color: var(--secondary-text-color); font-weight: 500; }
      .curve small { font-size: 10.5px; color: var(--secondary-text-color); }
      ul.cnote { margin: 6px 0 0; padding-left: 16px; }
      .cneed { fill: none; stroke: var(--info-color, #378add); stroke-width: 1.5; stroke-dasharray: 4 3; } .cneed.soft { opacity: .45; }
       .l.cneedl { background: none; border-top: 2px dashed var(--info-color, #378add); height: 0; }
      .ptable { font-size: 12.5px; font-variant-numeric: tabular-nums; }
      .etab .tr { grid-template-columns: minmax(5.2em, 1.4fr) repeat(5, minmax(0, 1fr)); cursor: pointer; }
      .etab.wide .tr { grid-template-columns: minmax(6em, 1.4fr) repeat(10, minmax(0, 1fr)); }
      .etab .tr.tot { font-weight: 600; } .etab .tr.open { background: color-mix(in srgb, var(--rc-sp) 7%, transparent); }
      .etab .tr.th { cursor: default; }
      .ix.good { color: var(--success-color, #43a047); } .ix.bad { color: var(--error-color, #db4437); } .ix.mid { color: var(--warning-color, #f59e0b); }
      .edet { display: grid; gap: 3px; padding: 6px 4px 8px; font-size: 12px; border-top: 1px dashed var(--divider-color); }
      .edet > div { display: grid; grid-template-columns: 7.5em 1fr; gap: 8px; } .edet span { color: var(--secondary-text-color); }
      .edet b { font-weight: 500; } .eg { font-style: normal; font-size: 9px; margin-right: 4px; vertical-align: 1px; }
      .eg.heating { color: var(--rc-sp); } .eg.dhw { color: var(--info-color, #378add); } .eg.defrost { color: #5aa9e6; }
      .etab .tr > span:first-child { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .escope { font-size: 12px; color: var(--secondary-text-color); margin: 6px 0 0; }
      .enote { font-size: 11.5px; color: var(--secondary-text-color); margin: 8px 0 2px; line-height: 1.4; }
      .ecsv { display: inline-flex; align-items: center; gap: 4px; background: none; border: 1px solid var(--divider-color);
        border-radius: 14px; padding: 3px 10px; color: var(--primary-text-color); font: inherit; font-size: 12px; cursor: pointer; }
      .ecsv ha-icon { --mdc-icon-size: 16px; } .ecsv[disabled] { opacity: .4; cursor: default; }
      .tsec { font-size: 12px; font-weight: 600; margin: 10px 0 2px; }
      .tr { display: grid; grid-template-columns: minmax(6.5em, 1.3fr) 1fr 1.2fr 0.8fr 0.6fr; gap: 0 8px; padding: 4px 0;
        border-top: 1px solid var(--divider-color); align-items: baseline; }
      .tr > :nth-child(n+2) { text-align: right; } .tr.th { color: var(--secondary-text-color); font-size: 11px; border-top: 0; }
      .tr.now { background: color-mix(in srgb, var(--rc-sp) 7%, transparent); }
      .tr b.o { color: var(--rc-sp); font-weight: 600; } .tr small { color: var(--secondary-text-color); }
      .tw { grid-column: 1 / -1; text-align: left !important; color: var(--secondary-text-color); font-size: 12px; }
      .pr.cheap { color: var(--rc-cheap); } .pr.dear { color: var(--rc-dear); } .pr.guess { opacity: .55; }
      .mk { font-style: normal; font-size: 11px; padding: 0 5px; border-radius: 6px; background: color-mix(in srgb, var(--warning-color, #f59e0b) 22%, transparent); }
      .tday summary { cursor: pointer; padding: 6px 0; font-size: 12.5px; } .tday summary span { color: var(--secondary-text-color); }
      
      .curve { margin: 8px 0 2px; font-size: 13px; } .curve summary { cursor: pointer; font-weight: 600; font-size: 12px; }
      .curve summary span { font-weight: 400; color: var(--secondary-text-color); }
      .curve table { border-collapse: collapse; margin: 6px 0; } .curve th, .curve td { padding: 2px 12px 2px 0; text-align: right; }
      .curve th { font-weight: 400; color: var(--secondary-text-color); font-size: 12px; } .curve td b { color: var(--rc-sp); }
      .curve td i { font-style: normal; color: var(--secondary-text-color); }
      .cnote { font-size: 12px; color: var(--secondary-text-color); line-height: 1.4; }
      svg { width: 100%; display: block; touch-action: pan-y; }
      .band { fill: var(--rc-band); opacity: .07; } .grid { stroke: var(--divider-color); stroke-width: 1; }
      .axis { fill: var(--secondary-text-color); font-size: 10px; } .nowt { fill: var(--rc-sp); }
      .price { opacity: .55; } .price.guess { opacity: .2; } .area { fill: var(--rc-room); opacity: .06; }
      .sp { fill: none; stroke: var(--rc-sp); stroke-width: 2.2; stroke-linejoin: round; }
      .room { fill: none; stroke: var(--rc-room); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
      .nowl { stroke: var(--rc-sp); stroke-width: 1.5; opacity: .6; }
      .cur { stroke: var(--secondary-text-color); stroke-dasharray: 2 2; opacity: 0; } .dot { fill: var(--rc-room); opacity: 0; }
      .dot2 { fill: var(--rc-sp); opacity: 0; } .chart.on .cur, .chart.on .dot, .chart.on .dot2 { opacity: 1; }
      .hit { fill: transparent; cursor: crosshair; }
      .leg { display: flex; flex-wrap: wrap; gap: 12px; font-size: 11px; color: var(--secondary-text-color); margin-top: 4px; }
      .leg span { display: inline-flex; align-items: center; gap: 5px; }
      .l { display: inline-block; width: 14px; height: 3px; border-radius: 2px; } .l.sp { background: var(--rc-sp); } .faxis { fill: var(--rc-sp); }
      .mini.wide { width: auto; padding: 3px 10px; }
      .svp { display: grid; gap: 6px; } .svr { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
      .svr span { display: grid; min-width: 0; } .svr small { color: var(--secondary-text-color); font-size: 11.5px; }
      .svr b { font-variant-numeric: tabular-nums; white-space: nowrap; } .pline.note { font-size: 11.5px; color: var(--secondary-text-color); }
      .otset { border: 1px solid var(--divider-color); border-radius: 10px; padding: 6px 10px; margin: 4px 0 8px; }
      .ots { font-size: 12px; color: var(--secondary-text-color); padding: 2px 0 4px; }
      .shsum { font-size: 12px; margin: 6px 0 2px; padding: 6px 9px; border-radius: 8px; background: color-mix(in srgb, var(--rc-sp) 9%, transparent); }
      /* a setting: label left, - [value] + right; 44 px targets, 16 px text (iOS zooms the page into smaller fields) */
      .srow .sl { min-width: 0; flex: 1 1 auto; } .serr { display: block; color: var(--rc-dear); font-size: 11px; }
      .stp { display: inline-flex; align-items: center; gap: 4px; flex: none; }
      .stp .mini { min-width: 36px; min-height: 36px; padding: 0 8px; font-size: 16px; line-height: 1; touch-action: manipulation; }
      .stp .mini.wide { font-size: 13px; }
      .nf { display: inline-flex; align-items: baseline; gap: 2px; border: 1px solid var(--divider-color); border-radius: 8px;
            padding: 0 8px; min-height: 36px; width: 6.6em; justify-content: flex-end; box-sizing: border-box; background: var(--card-background-color, transparent); cursor: text; }
      .nf:focus-within { border-color: var(--rc-sp); }
      .nf input { width: 3.2em; border: 0; outline: 0; background: none; color: var(--primary-text-color); font: inherit; font-size: 16px;
                  font-weight: 600; text-align: right; padding: 7px 0; font-variant-numeric: tabular-nums; }
      .nf .u { font-size: 12px; color: var(--secondary-text-color); min-width: 1.7em; }
      .srow.pend .nf { border-color: color-mix(in srgb, var(--rc-sp) 60%, transparent); }
      .srow.pend .nf input { color: var(--rc-sp); }
      .srow.err .nf { border-color: var(--rc-dear); }
      input.tm { font: inherit; font-size: 16px; color: var(--primary-text-color); background: none; border: 1px solid var(--divider-color);
                 border-radius: 8px; padding: 4px 6px; min-height: 36px; box-sizing: border-box; color-scheme: light dark; }
      .otl { font-size: 12px; color: var(--secondary-text-color); margin-top: 6px; } .otlv { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 4px 0; } .mini.on { background: var(--rc-sp); color: #fff; border-color: var(--rc-sp); }
      .l.room { background: var(--rc-room); } .l.price { height: 8px; background: linear-gradient(90deg, var(--rc-cheap), var(--rc-mid), var(--rc-dear)); opacity: .6; }
      .l.price.guess { opacity: .2; }
      .l.band { height: 8px; background: var(--rc-band); opacity: .25; }
      .foot { font-size: 12px; color: var(--secondary-text-color); margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--divider-color); }
      .seg { display: flex; border: 1px solid var(--divider-color); border-radius: 8px; overflow: hidden; font-size: 11.5px; flex: none; cursor: pointer; }
      .seg span { padding: 3px 8px; color: var(--secondary-text-color); } .seg span.on { background: color-mix(in srgb, var(--rc-sp) 18%, transparent); color: var(--rc-sp); font-weight: 600; }
      .hbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
      .rep { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; padding: 3px 9px; border-radius: 8px; border: 1px solid var(--divider-color);
             background: none; color: var(--secondary-text-color); cursor: pointer; } .rep ha-icon { --mdc-icon-size: 15px; }
      .tiles.four { grid-template-columns: repeat(4, minmax(0, 1fr)); } .htile .tv { font-size: 18px; }
      .cview .tile .ts { white-space: normal; overflow-wrap: anywhere; }
      .hplan { fill: none; stroke: var(--rc-sp); stroke-width: 1.5; stroke-dasharray: 4 3; }
      .dfm { fill: #5aa9e6; color: #5aa9e6; font-size: 10px; font-weight: 600; } .dfseen { margin-top: 4px; font-size: 12px; }
      .offcol { fill: color-mix(in srgb, var(--secondary-text-color) 10%, transparent); }
      .l.offcol { height: 8px; background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--secondary-text-color) 35%, transparent) 0 2px, transparent 2px 5px); }
      .hmeas { fill: none; stroke: var(--info-color, #378add); stroke-width: 1.8; stroke-linejoin: round; } .l.hmeas { background: var(--info-color, #378add); }
      .hwould { fill: none; stroke: var(--rc-sp); stroke-width: 1; stroke-dasharray: 2 2; }
      .l.hwould { height: 8px; border: 1px dashed var(--rc-sp); background: none; box-sizing: border-box; }
      .hroom { fill: none; stroke: var(--rc-room); stroke-width: 2; stroke-linejoin: round; }
      .hpred { fill: none; stroke: var(--info-color, #378add); stroke-width: 1.5; stroke-dasharray: 4 3; }
      .hheat { fill: #f0997b; opacity: .8; } .hpause { fill: var(--warning-color, #f5a524); opacity: .12; }
      .hmark { fill: color-mix(in srgb, var(--warning-color, #f5a524) 25%, var(--card-background-color, #fff)); stroke: var(--warning-color, #f5a524); stroke-width: .7; }
      .hmt { fill: var(--primary-text-color); font-size: 8px; font-weight: 600; } .hdev { fill: var(--error-color, #e5484d); }
      .l.hplan { background: none; border-top: 2px dashed var(--rc-sp); height: 0; } .l.hroom { background: var(--rc-room); }
      .l.hpred { background: none; border-top: 2px dashed var(--info-color, #378add); height: 0; } .l.hheat { height: 8px; background: #f0997b; }
      .hlog { margin-top: 10px; font-size: 12px; } .lhead { cursor: pointer; color: var(--secondary-text-color); font-weight: 600; padding: 4px 0; }
      .lrow { display: grid; grid-template-columns: 70px 62px minmax(0, 1fr) auto; gap: 8px; padding: 5px 0; border-top: 1px solid var(--divider-color); }
      .lrow .mut { color: var(--secondary-text-color); } .lrow .warn { color: var(--warning-color, #f5a524); } .lrow .ok { color: var(--success-color, #30a46c); }
      .foot b { color: var(--primary-text-color); }
      .steer { margin-top: 10px; width: 100%; padding: 9px; border-radius: 10px; border: 1px solid var(--success-color, #30a46c);
               background: color-mix(in srgb, var(--success-color, #30a46c) 15%, transparent); color: var(--success-color, #30a46c);
               font-weight: 600; font-size: 13px; cursor: pointer; } .foot b.ok { color: var(--success-color, #30a46c); }

      /* v0.9: sliders button, alert lines, one row of pills, their panels, the plan's labels and the hour panel */
      :host { --rc-good: var(--success-color, #30a46c); --rc-amber: var(--warning-color, #f5a524); --rc-red: var(--error-color, #e5484d);
              --rc-info: var(--info-color, #3b82f6); --rc-k-store: var(--rc-sp); --rc-k-skip: var(--error-color, #e5484d);
              --rc-k-hold: color-mix(in srgb, var(--primary-text-color) 55%, transparent); --rc-k-coast: color-mix(in srgb, var(--secondary-text-color) 45%, transparent); }
      .setgear { margin-left: auto; width: 44px; height: 44px; flex: none; border-radius: 50%; border: 1px solid var(--divider-color); background: none;
                 color: var(--primary-text-color); display: flex; align-items: center; justify-content: center; cursor: pointer; }
      .setgear.on { border-color: var(--rc-sp); color: var(--rc-sp); } .setgear ha-icon { --mdc-icon-size: 20px; }
      .alert { display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px; line-height: 1.4; margin: -2px 0 10px; padding: 8px 10px; border-radius: 10px;
               border: 1px solid color-mix(in srgb, var(--rc-amber) 40%, transparent); background: color-mix(in srgb, var(--rc-amber) 10%, transparent); }
      .alert ha-icon { --mdc-icon-size: 17px; color: var(--rc-amber); flex: none; }
      .alert.red { border-color: color-mix(in srgb, var(--rc-red) 45%, transparent); background: color-mix(in srgb, var(--rc-red) 10%, transparent); }
      .alert.red ha-icon { color: var(--rc-red); }
      .pills { display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin: 0 -2px 10px; padding: 0 2px; }
      .pills::-webkit-scrollbar { display: none; }
      .pl { flex: none; white-space: nowrap; height: 38px; padding: 0 11px; border-radius: 999px; display: inline-flex; align-items: center; gap: 6px;
            font: inherit; font-size: 12px; font-weight: 600; color: var(--primary-text-color); cursor: pointer;
            border: 1px solid var(--divider-color); background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
      .pl.on { background: color-mix(in srgb, var(--primary-text-color) 12%, transparent); }
      .pl ha-icon { --mdc-icon-size: 16px; } .pl .ml { letter-spacing: .4px; }
      .pl .tag { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; color: var(--secondary-text-color); }
      .pl .tag i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
      .pl .tag.good { color: var(--rc-good); } .pl .tag.amber { color: var(--rc-amber); } .pl .tag.info { color: var(--rc-info); }
      .pl .pdot { width: 8px; height: 8px; border-radius: 50%; background: var(--secondary-text-color); flex: none; }
      .pl.heat { border-color: color-mix(in srgb, var(--rc-sp) 45%, transparent); } .pl.heat .pdot { background: var(--rc-sp); }
      .pl.water { border-color: color-mix(in srgb, var(--rc-info) 45%, transparent); } .pl.water .pdot { background: var(--rc-info); }
      .pl.ctrl { border-color: color-mix(in srgb, var(--rc-info) 45%, transparent); } .pl.ctrl ha-icon, .pl.ctrl b { color: var(--rc-info); }
      .pl.ctrl.amber { border-color: color-mix(in srgb, var(--rc-amber) 55%, transparent); background: color-mix(in srgb, var(--rc-amber) 12%, transparent); }
      .pl.ctrl.amber ha-icon, .pl.ctrl.amber b { color: var(--rc-amber); }
      .pl.saving { border-color: color-mix(in srgb, var(--rc-good) 45%, transparent); }
      .pl b.good, .panel b.good, .calc .good { color: var(--rc-good); } .pl b.bad, .panel b.bad, .calc .bad { color: var(--rc-red); }
      .panel, .hpanel { display: flex; flex-direction: column; gap: 6px; margin: 0 0 10px; padding: 10px 12px; border-radius: 12px; cursor: default;
               border: 1px solid var(--divider-color); background: color-mix(in srgb, var(--primary-text-color) 3%, transparent); }
      .panel.heat { border-color: color-mix(in srgb, var(--rc-sp) 35%, transparent); background: color-mix(in srgb, var(--rc-sp) 7%, transparent); }
      .panel.info { border-color: color-mix(in srgb, var(--rc-info) 35%, transparent); background: color-mix(in srgb, var(--rc-info) 7%, transparent); }
      .panel.amber { border-color: color-mix(in srgb, var(--rc-amber) 45%, transparent); background: color-mix(in srgb, var(--rc-amber) 8%, transparent); }
      .panel.good { border-color: color-mix(in srgb, var(--rc-good) 35%, transparent); background: color-mix(in srgb, var(--rc-good) 7%, transparent); }
      .panel.set { border-color: color-mix(in srgb, var(--rc-sp) 35%, transparent); }
      .panel .mmenu { margin: 0; } .panel .spanel { border: 0; padding: 0; }
      .prow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .prow.sep { border-top: 1px solid var(--divider-color); padding-top: 8px; }
      .prow > ha-icon { --mdc-icon-size: 16px; flex: none; } .panel.info .prow > ha-icon { color: var(--rc-info); } .panel.amber .prow > ha-icon { color: var(--rc-amber); }
      .phead { flex: 1 1 auto; min-width: 0; font-size: 13px; font-weight: 600; } .phead.big { font-size: 15px; } .phead .mute { font-weight: 400; color: var(--secondary-text-color); }
      .pline { font-size: 12px; line-height: 1.45; color: var(--secondary-text-color); } .pline b { color: var(--primary-text-color); font-weight: 600; }
      .pline.strong { color: var(--primary-text-color); } .pline.grow { flex: 1 1 auto; } .pline b.o { color: var(--rc-sp); }
      .pbtn { flex: none; min-height: 36px; padding: 0 14px; border-radius: 999px; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer;
              border: 1px solid var(--divider-color); background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); color: var(--primary-text-color); }
      .pbtn.ghost { background: none; border-color: transparent; color: var(--secondary-text-color); }
      .pbtn.amber { border-color: color-mix(in srgb, var(--rc-amber) 55%, transparent); background: color-mix(in srgb, var(--rc-amber) 14%, transparent); }
      .pbtn.round { width: 36px; padding: 0; font-size: 16px; }
      .readyb { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px; font-size: 12.5px; line-height: 1.4;
                border: 1px solid color-mix(in srgb, var(--rc-good) 40%, transparent); background: color-mix(in srgb, var(--rc-good) 9%, transparent); }
      .readyb > span { flex: 1 1 220px; } .readyb .steer { margin: 0; width: auto; flex: none; min-height: 44px; padding: 0 18px; }
      .bx4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
      @container (max-width: 420px) { .bx4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
      .bx { padding: 7px 9px; border-radius: 10px; background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); min-width: 0; }
      .bl { font-size: 11px; color: var(--secondary-text-color); } .bv { font-size: 16px; font-weight: 700; } .bv.heat { color: var(--rc-sp); } .bv.water { color: var(--rc-info); }
      .bs { font-size: 10.5px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .bx3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding-top: 6px; border-top: 1px solid var(--divider-color); }
      .bm { font-size: 13px; font-weight: 600; }
      .calc { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 14px; font-size: 12.5px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
      .calc .r { text-align: right; color: var(--primary-text-color); } .calc .tot { font-weight: 700; padding-top: 3px; border-top: 1px solid var(--divider-color); }
      .panel .chip.calpill { border: 0; font: inherit; font-size: 11px; }
      .sec { font-size: 11px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .5px; margin-top: 6px; }
       
      
       
       
      .seg.tabs { display: flex; margin: 12px 0 0; border-radius: 999px; padding: 3px; gap: 4px; }
      .seg.tabs span { flex: 1; text-align: center; padding: 7px 8px; border-radius: 999px; font-size: 12.5px; }
      .tile.nxt .tv { color: var(--primary-text-color); }
      .price.k-store { fill: var(--rc-k-store); } .price.k-skip { fill: var(--rc-k-skip); } .price.k-hold { fill: var(--rc-k-hold); } .price.k-coast { fill: var(--rc-k-coast); }
      .selcol { fill: color-mix(in srgb, var(--rc-sp) 12%, transparent); } .hit { cursor: pointer; }
      .glab, .dstrip { display: grid; gap: 1px; font-size: 10px; line-height: 14px; text-align: center; }
      .glab span { white-space: nowrap; overflow: hidden; font-weight: 600; } .glab .k-store { color: var(--rc-sp); } .glab .k-skip { color: var(--rc-red); }
      .glab .k-hold { color: var(--primary-text-color); } .glab .k-coast { color: var(--secondary-text-color); }
      .dstrip { margin-top: 2px; } .dstrip span { border-radius: 4px; white-space: nowrap; overflow: hidden; }
      .dstrip .dc { background: color-mix(in srgb, var(--rc-band) 18%, transparent); color: var(--rc-band); }
      .dstrip .dn { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); color: var(--secondary-text-color); }
      .leg { align-items: center; } .leg .accp { margin-left: auto; } .qbtn { width: 30px; height: 30px; border-radius: 50%; border: 1px solid var(--divider-color);
              background: none; color: var(--primary-text-color); font: inherit; font-weight: 700; cursor: pointer; }
      .legx { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; padding: 8px 10px; border-radius: 10px; font-size: 11.5px; line-height: 1.4;
              color: var(--secondary-text-color); background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
      .legx .k-store { color: var(--rc-sp); } .legx .k-skip { color: var(--rc-red); } .legx .k-hold, .legx .k-coast { color: var(--primary-text-color); }
      .hpanel { margin-top: 10px; border-color: color-mix(in srgb, var(--rc-sp) 35%, transparent); }
      .hpanel .k-store { color: var(--rc-sp); } .hpanel .k-skip { color: var(--rc-red); } .hpanel .k-coast { color: var(--secondary-text-color); }
    </style>`;
  }
}

class RoostCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }

  // The toggles show what the card really shows. Switching "compact" resets the parts to its preset, and a part
  // that matches the preset is left out of the YAML, so the configuration stays short.
  _changed(value) {
    const prev = this._config || {};
    const v = Object.assign({}, value);
    if (!!v.compact !== !!prev.compact) PARTS.forEach((p) => { delete v["show_" + p]; });
    else PARTS.forEach((p) => { if (v["show_" + p] === showDefault(v, p)) delete v["show_" + p]; });
    if (!v.compact) delete v.compact;
    if (!v.title) delete v.title;
    if (!v.language || v.language === "auto") delete v.language;
    if (!v.time_format || v.time_format === "auto") delete v.time_format;
    if (v.history !== false) delete v.history;
    if (!v.view || v.view === "plan") delete v.view;
    this._config = v;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: v }, bubbles: true, composed: true }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = T[lang2(this._hass)] || T.en;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => t["e_" + s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => this._changed(ev.detail.value));
      this.appendChild(this._form);
    }
    const data = Object.assign({}, this._config, { compact: !!this._config.compact,
      language: this._config.language || "auto", time_format: this._config.time_format || "auto",
      history: this._config.history !== false, view: this._config.view || "plan" });
    PARTS.forEach((p) => { data["show_" + p] = shows(this._config, p); });
    this._form.hass = this._hass;
    this._form.data = data;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { filter: { integration: "roost", domain: "sensor" } } } },
      { name: "title", selector: { text: {} } },
      { name: "compact", selector: { boolean: {} } },
      { type: "grid", name: "", schema: [
        { name: "view", selector: { select: { mode: "dropdown", options: [
          { value: "plan", label: t.v_plan }, { value: "table", label: t.v_table }, { value: "curve", label: t.v_curve },
          { value: "history", label: t.v_history }, { value: "energy", label: (EN_T[lang2(this._hass)] || EN_T.en).tab }] } } },
        { name: "history", selector: { boolean: {} } }] },
      { type: "grid", name: "", schema: [
        { name: "language", selector: { select: { mode: "dropdown", options: [
          { value: "auto", label: t.e_auto }, { value: "en", label: "English" }, { value: "nl", label: "Nederlands" },
          { value: "de", label: "Deutsch" }, { value: "fr", label: "Fran\u00e7ais" }] } } },
        { name: "time_format", selector: { select: { mode: "dropdown", options: [
          { value: "auto", label: t.e_auto }, { value: "24", label: "24h (13:45)" }, { value: "12", label: "12h (1:45 PM)" }] } } }] },
      { type: "grid", name: "", schema: PARTS.map((p) => ({ name: "show_" + p, selector: { boolean: {} } })) },
    ];
  }
}

// Home Assistant 2026.9+ swaps window.customElements for a scoped registry while it starts: define in the registry
// that is there now, and again in the new one as soon as it appears (lesson from the Shower Time card).
const ELEMENTS = [["roost-card", RoostCard], ["roost-card-editor", RoostCardEditor]];
const defineIn = (registry) => {
  for (const pair of ELEMENTS) {
    try { if (!registry.get(pair[0])) registry.define(pair[0], pair[1]); } catch (e) { /* defined meanwhile */ }
  }
};
let registry = window.customElements;
defineIn(registry);
const recheck = () => { if (window.customElements !== registry) { registry = window.customElements; defineIn(registry); } };
if (registry.whenDefined) registry.whenDefined("home-assistant").then(recheck);
let checks = 0;
const timer = setInterval(() => { recheck(); if (++checks >= 120) clearInterval(timer); }, 250);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "roost-card")) {
  window.customCards.push({ type: "roost-card", name: "Roost", preview: true,
    description: "The 24-hour heating plan of your Weheat heat pump." });
}
console.info(`%c ROOST-CARD %c ${CARD_VERSION} `, "background:#fb923c;color:#fff;border-radius:3px 0 0 3px",
  "background:#222;color:#fff;border-radius:0 3px 3px 0");
})();
