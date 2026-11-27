"""Looking after the user and the thermostat: notifications (only when the user chose where), a thermostat that cannot be
reached or set, the thermostat back to comfort when Roost stops steering, away, comfort from the card and the weekly
summary. Care (held by RoostManager as `care`) keeps its own state (when it last notified, since when the thermostat
is gone, failed changes in a row) and reaches the rest of Roost through the manager. The weekly summary's numbers are
worked out without the manager (weekly_summary)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import comfort
from .const import (
    AWAY_MIN,
    CONF_CONTROL,
    CONF_NOTIFY,
    CONF_OT_FLOW,
    CONF_OT_MAX_FLOW,
    CONF_OT_MAX_STARTS,
    CONF_OT_MIN_FLOW,
    CONF_OT_MODE,
    CONF_OT_QUIET,
    CONF_OT_QUIET_FROM,
    CONF_OT_QUIET_MAX,
    CONF_OT_QUIET_TO,
    CONF_OT_STATE,
    CONF_ROOM,
    CONF_SP_MIN,
    CONF_WEEKLY,
    CONTROLS,
    DOMAIN,
)
from .mgr_common import (  # the shared imports and constants  # noqa: F401
    _LOGGER,
    ATTR_ENTITY_ID,
    CONF_BATTERY_POWER,
    CONF_COMFORT,
    CONF_DAY_FROM,
    CONF_DAY_MIN,
    CONF_DAY_TO,
    CONF_GRID_POWER,
    CONF_GRID_SIGN,
    CONF_NIGHT_MIN,
    CONF_PV_POWER,
    CONF_STORE_MAX,
    CONF_THERMOSTAT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Context,
    _f,
    datetime,
    dt_util,
    schedule,
    time,
    timedelta,
    timezone,
)
from .value import source_split  # noqa: F401 - where the heat pump's power comes from

if TYPE_CHECKING:
    from .manager import (
        RoostManager,  # for the type checker only: no import cycle at run time
    )

THERMOSTAT_GONE_MIN = 15        # the thermostat unavailable this long: a notice (and Roost leaves it alone meanwhile)
SET_FAILS = 3                   # this many failed changes in a row: a notice
NOTIFY_AGAIN_H = 12             # the same notification at most this often

# Notifications in the user's language (Home Assistant's language; English when not one of these)
TEXTS = {
    "en": {"title": "Roost",
           "house_cold": "The room stays at {room} °C, below its minimum of {minimum} °C, while Roost steers. Check the heat pump and the thermostat.",
           "thermostat_unavailable": "The thermostat cannot be reached. Roost leaves it alone until it is back.",
           "set_failed": "Roost could not change the thermostat {n} times in a row: {error}",
           "steering_not_ready": "Roost steers with the model it had: the check of the house model did not pass. Look at it in the card.",
           "learning_failed": "Learning the house failed tonight; Roost goes on with the model it had.",
           "login": "Roost's Weheat login is needed again: Settings → Devices & services → Roost.",
           "weekly": "Last week: heating {kwh} kWh, cost {cost}, saving {saving} against a steady thermostat. {below} min below comfort, {hand} changes by hand.{sources}",
           "sources": " Heating electricity: {sun} % own solar, {bat} % battery, {grid} % grid."},
    "nl": {"title": "Roost",
           "house_cold": "De kamer blijft {room} °C, onder het minimum van {minimum} °C, terwijl Roost stuurt. Controleer warmtepomp en thermostaat.",
           "thermostat_unavailable": "De thermostaat is niet bereikbaar. Roost laat hem met rust tot hij terug is.",
           "set_failed": "Roost kon de thermostaat {n} keer achter elkaar niet wijzigen: {error}",
           "steering_not_ready": "Roost stuurt met het model dat het had: de controle van het huismodel is niet geslaagd. Kijk in de kaart.",
           "learning_failed": "Het huis leren is vannacht mislukt; Roost gaat door met het model dat het had.",
           "login": "Roosts Weheat-login is opnieuw nodig: Instellingen → Apparaten en diensten → Roost.",
           "weekly": "Afgelopen week: {kwh} kWh stroom voor verwarming, kosten {cost}, besparing {saving} tegenover een vaste thermostaat. {below} min onder comfort, {hand} wijzigingen met de hand.{sources}",
           "sources": " Stroom voor verwarming: {sun} % eigen zon, {bat} % accu, {grid} % net."},
    "de": {"title": "Roost",
           "house_cold": "Der Raum bleibt bei {room} °C, unter dem Minimum von {minimum} °C, während Roost steuert. Prüfe Wärmepumpe und Thermostat.",
           "thermostat_unavailable": "Das Thermostat ist nicht erreichbar. Roost lässt es in Ruhe, bis es zurück ist.",
           "set_failed": "Roost konnte das Thermostat {n}-mal nacheinander nicht ändern: {error}",
           "steering_not_ready": "Roost steuert mit dem bisherigen Modell: die Prüfung des Hausmodells ist nicht bestanden. Schau in die Karte.",
           "learning_failed": "Das Lernen des Hauses ist heute Nacht fehlgeschlagen; Roost macht mit dem bisherigen Modell weiter.",
           "login": "Roosts Weheat-Anmeldung ist wieder nötig: Einstellungen → Geräte & Dienste → Roost.",
           "weekly": "Letzte Woche: {kwh} kWh Heizstrom, Kosten {cost}, Ersparnis {saving} gegenüber einem festen Thermostat. {below} min unter Komfort, {hand} Änderungen von Hand.{sources}",
           "sources": " Heizstrom: {sun} % eigene Sonne, {bat} % Akku, {grid} % Netz."},
    "fr": {"title": "Roost",
           "house_cold": "La pièce reste à {room} °C, sous son minimum de {minimum} °C, alors que Roost pilote. Vérifiez la pompe à chaleur et le thermostat.",
           "thermostat_unavailable": "Le thermostat est injoignable. Roost le laisse tranquille jusqu'à son retour.",
           "set_failed": "Roost n'a pas pu changer le thermostat {n} fois de suite : {error}",
           "steering_not_ready": "Roost pilote avec le modèle qu'il avait : la vérification du modèle de la maison n'a pas réussi. Voir la carte.",
           "learning_failed": "L'apprentissage de la maison a échoué cette nuit ; Roost continue avec le modèle qu'il avait.",
           "login": "La connexion Weheat de Roost est de nouveau nécessaire : Paramètres → Appareils et services → Roost.",
           "weekly": "Semaine dernière : {kwh} kWh de chauffage, coût {cost}, économie {saving} par rapport à un thermostat fixe. {below} min sous le confort, {hand} changements à la main.{sources}",
           "sources": " Électricité de chauffage : {sun} % solaire, {bat} % batterie, {grid} % réseau."},
}


def weekly_summary(day_stats: dict[str, dict], hour_log: list[dict], today, texts: dict, currency: str) -> dict | None:
    """The numbers of the weekly notification (texts["weekly"]) for the seven days before today; None without any."""
    days = [(today - timedelta(days=i)).isoformat() for i in range(1, 8)]
    ds = [day_stats[d] for d in days if d in day_stats]
    if not ds:
        return None
    money = lambda v: f"{v:.2f} {currency}" if v is not None else "—"      # noqa: E731
    hrs = [e for e in hour_log if dt_util.as_local(datetime.fromtimestamp(e["ts"], tz=timezone.utc)).date().isoformat() in days]
    sun, bat, grid = (sum(e.get(k, 0.0) for e in hrs) for k in ("e_sun", "e_bat", "e_grid"))
    total = sun + bat + grid
    sources = texts["sources"].format(sun=round(100 * sun / total), bat=round(100 * bat / total), grid=round(100 * grid / total)) if total > 0.5 else ""
    return dict(kwh=round(sum(d.get("kwh") or 0.0 for d in ds), 1),
                cost=money(sum(d.get("cost") or 0.0 for d in ds)),
                saving=money(sum(d.get("saving") or 0.0 for d in ds) if any(d.get("saving") is not None for d in ds) else None),
                below=round(sum(d.get("below_min") or 0 for d in ds)), hand=sum(d.get("by_hand") or 0 for d in ds),
                sources=sources)


class Care:
    """Held by RoostManager as `care`; reaches the rest of Roost through the manager (self.h)."""
    def __init__(self, host: RoostManager) -> None:
        self.h = host
        self._notified: dict[str, float] = {}       # kind -> when last sent
        self._th_gone_since: float | None = None
        self._set_fails = 0

    # ------------------------------------------------------------ notifications (the user turns them on)
    def texts(self) -> dict:
        return TEXTS.get((self.h.hass.config.language or "en")[:2], TEXTS["en"])

    def notify_user(self, kind: str, force: bool = False, **fmt) -> None:
        target = str(self.h.conf.get(CONF_NOTIFY) or "").strip()
        if not target:
            return
        now = time.time()
        if not force and now - self._notified.get(kind, 0.0) < NOTIFY_AGAIN_H * 3600:
            return
        self._notified[kind] = now
        t = self.texts()
        msg = t[kind].format(**fmt)
        self.h.spawn(self.async_send(target, t["title"], msg), f"notify {kind}")

    async def async_send(self, target: str, title: str, message: str) -> None:
        try:
            if target.startswith("notify.") and self.h.hass.states.get(target) is not None:     # a notify entity
                await self.h.hass.services.async_call("notify", "send_message", {ATTR_ENTITY_ID: target, "title": title,
                                                                                "message": message}, blocking=True)
            else:                                                                           # a notify service
                name = target.removeprefix("notify.")
                await self.h.hass.services.async_call("notify", name, {"title": title, "message": message}, blocking=True)
            self.h.event("notified", target=target)
        except Exception as err:  # noqa: BLE001 - a notification never gets in the way
            _LOGGER.warning("Roost could not send a notification to %s: %s", target, err)
            self.h.event("notify_failed", target=target, error=str(err)[:200])

    # ------------------------------------------------------------ the thermostat
    def thermostat_reachable(self) -> bool:
        eid = self.h.conf.get(CONF_THERMOSTAT)
        st = self.h.hass.states.get(eid) if eid else None
        return st is not None and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    def watch_thermostat(self, t: float) -> None:
        """Unavailable for a while: a notice (and a notification when chosen); back: the notice goes."""
        if self.thermostat_reachable():
            back = self._th_gone_since is not None
            self._th_gone_since = None                  # first: the planning below runs this check again
            self.h.notices.issue("thermostat_unavailable", False)
            if back:
                self.h.event("thermostat_back")
                # plan again with what the thermostat really has (a plan made without it would be followed meanwhile)
                self.h.hass.async_create_background_task(self.h._async_tick(None, force_plan=True), "roost: plan after the thermostat is back")
            return
        if self._th_gone_since is None:
            self._th_gone_since = t
            self.h.event("thermostat_gone")
        if t - self._th_gone_since >= THERMOSTAT_GONE_MIN * 60 and self.h.mode == "active":
            if "thermostat_unavailable" not in self.h.health.issues:
                self.notify_user("thermostat_unavailable")
            self.h.notices.issue("thermostat_unavailable", True)

    def set_result(self, ok: bool, error: str = "") -> None:
        if ok:
            self._set_fails = 0
            self.h.notices.issue("set_failed", False)
            return
        self._set_fails += 1
        if self._set_fails >= SET_FAILS:
            if "set_failed" not in self.h.health.issues:
                self.notify_user("set_failed", n=self._set_fails, error=error[:120])
            self.h.notices.issue("set_failed", True, placeholders={"error": error[:120]})

    async def async_back_to_comfort(self, why: str) -> None:
        """Roost stops steering (off, shadow, removed): the thermostat back on the comfort temperature, not left at
        whatever the plan had (a low setting in an expensive hour)."""
        target = float(self.h.conf[CONF_COMFORT])
        if not self.thermostat_reachable() or self.h.thermostat_sp() == target:
            return
        ctx = Context()
        self.h._contexts[ctx.id] = time.time()
        try:
            await self.h.hass.services.async_call("climate", "set_temperature",
                                                {ATTR_ENTITY_ID: self.h.conf[CONF_THERMOSTAT], "temperature": self.h.read.c_to_sys(target)},
                                                blocking=True, context=ctx)
            self.h.event("back_to_comfort", why=why, new=target)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Roost could not set the thermostat back to comfort: %s", err)

    # ------------------------------------------------------------ away, comfort from the card
    async def async_away(self, until: float, minimum: float | None) -> None:
        self.h.mem.away_until = until
        self.h.mem.away_min = float(minimum) if minimum is not None else AWAY_MIN
        self.h.event("away", until=datetime.fromtimestamp(until, tz=timezone.utc).isoformat(timespec="minutes"),
                   minimum=self.h.mem.away_min)
        await self.h.async_save()
        await self.h._async_tick(None, force_plan=True)

    async def async_home(self) -> None:
        if self.h.mem.away_until:
            self.h.event("home")
        self.h.mem.away_until = None
        await self.h.async_save()
        await self.h._async_tick(None, force_plan=True)

    async def async_set_settings(self, **changes) -> None:
        """Temperatures and comfort hours from the card: Roost's own settings (not the thermostat), without a reload.
        The setting that was changed wins: the others follow it (comfort never below the day minimum, storing never
        below comfort, the lowest setpoint never above comfort); comfort hours must end after they start."""
        if changes.get("control") is not None:
            await self.async_set_control(str(changes["control"]))
            return
        if any(k.startswith("ot_") for k in changes):
            await self.async_set_ot_settings(changes)
            return
        keys = {"comfort": CONF_COMFORT, "day_min": CONF_DAY_MIN, "night_min": CONF_NIGHT_MIN, "store_max": CONF_STORE_MAX,
                "lowest_setpoint": CONF_SP_MIN, "day_from": CONF_DAY_FROM, "day_to": CONF_DAY_TO}
        from homeassistant.exceptions import ServiceValidationError
        c = {k: self.h.conf.get(v) for k, v in keys.items()}
        new = {k: v for k, v in changes.items() if k in keys and v is not None}
        weekly: dict[str, Any] = {}
        # the weekly comfort periods from the card: checked as in Configure > Comfort (quarter hours, no overlap)
        if changes.get("comfort_schedule") is not None:
            try:
                weekly[schedule.WEEK] = schedule.normalise(changes["comfort_schedule"])
            except ValueError as err:
                raise ServiceValidationError(f"Weekly comfort periods: {err}", translation_domain=DOMAIN, translation_key="weekly_invalid",
                                             translation_placeholders={"error": str(err)}) from err
        if changes.get("weekly_comfort") is not None:
            weekly[schedule.ENABLED] = bool(changes["weekly_comfort"])
            if weekly[schedule.ENABLED] and schedule.WEEK not in weekly and not self.h.conf.get(schedule.WEEK):
                # switched on without periods yet: every day the comfort hours it had
                a, b = int(self.h.conf[CONF_DAY_FROM]) * 60, int(self.h.conf[CONF_DAY_TO]) * 60
                weekly[schedule.WEEK] = schedule.normalise({d: [[a, b]] for d in schedule.DAYS})
        enabled = weekly.get(schedule.ENABLED, self.h.conf.get(schedule.ENABLED))
        if enabled and ({"day_from", "day_to"} & set(new)):
            raise ServiceValidationError("The weekly comfort periods are on: change those instead of the comfort hours",
                                         translation_domain=DOMAIN, translation_key="weekly_on")
        for k, v in new.items():
            c[k] = int(v) if k in ("day_from", "day_to") else round(float(v) * 2) / 2
        f = comfort.adjust_settings(c, set(new))
        if f is None:
            raise ServiceValidationError("The comfort hours must end after they start", translation_domain=DOMAIN, translation_key="hours_order")
        opts = {**self.h.entry.options, **{keys[k]: v for k, v in f.items()}, **weekly, **self.card_settings(changes)}
        from . import _conf_key
        # settings Roost takes as they are: no reload for them. Known before saving: the update listener may run
        # within async_update_entry (an eager task), and then saw the old key and reloaded Roost (card unavailable)
        self.h.conf_key = _conf_key(self.h.entry, opts)
        self.h.hass.config_entries.async_update_entry(self.h.entry, options=opts)
        self.h.event("settings", **{k: f[k] for k in new}, **({"weekly": weekly.get(schedule.ENABLED, enabled)} if weekly else {}),
                   **{k: changes[k] for k in ("pump_entities",) if k in changes})
        if "pump_entities" in changes:
            self.h._resolve_weheat()
        await self.h._async_tick(None, force_plan=True)

    # ------------------------------------------------------------ thermostat or OpenTherm, and the OpenTherm settings, from the card
    async def async_set_ot_settings(self, changes: dict) -> None:
        """OpenTherm settings from the card, without a reload (as comfort): flow limits, starts, quiet hours; relearn
        forgets what Roost learned of the heat pump."""
        from homeassistant.exceptions import ServiceValidationError
        keys = {"ot_min_flow": CONF_OT_MIN_FLOW, "ot_max_flow": CONF_OT_MAX_FLOW, "ot_max_starts": CONF_OT_MAX_STARTS,
                "ot_quiet": CONF_OT_QUIET, "ot_quiet_from": CONF_OT_QUIET_FROM, "ot_quiet_to": CONF_OT_QUIET_TO, "ot_quiet_max": CONF_OT_QUIET_MAX}
        if changes.get("ot_relearn"):
            self.h.otc.relearn()
            self.h.event("ot_relearn")
            await self.h._async_save_history()
        new = {keys[k]: v for k, v in changes.items() if k in keys and v is not None}
        if new:
            c = {**self.h.conf, **new}
            if float(c[CONF_OT_MIN_FLOW]) >= float(c[CONF_OT_MAX_FLOW]):
                raise ServiceValidationError("The lowest flow must be below the highest", translation_domain=DOMAIN, translation_key="flow_limits")
            for k in (CONF_OT_MAX_STARTS, CONF_OT_QUIET_FROM, CONF_OT_QUIET_TO):
                if k in new:
                    new[k] = int(new[k])
            if CONF_OT_QUIET in new:
                new[CONF_OT_QUIET] = bool(new[CONF_OT_QUIET])
            opts = {**self.h.entry.options, **new}
            from . import _conf_key
            self.h.conf_key = _conf_key(self.h.entry, opts)
            self.h.hass.config_entries.async_update_entry(self.h.entry, options=opts)
            self.h.event("settings", **new)
        await self.h.async_save()
        self.h._notify()          # the card shows the new setting at once; the plan with it follows in the background
        self.h.spawn(self.h._async_tick(None, force_plan=True), "plan with the new OpenTherm settings")


    def control_choices(self) -> dict:
        """What the card may offer: steering by thermostat needs a thermostat, over OpenTherm the master's entities
        and a room sensor (as the options check)."""
        c = self.h.conf
        return {"thermostat": bool(c.get(CONF_THERMOSTAT)),
                "opentherm": bool(c.get(CONF_OT_FLOW) and c.get(CONF_OT_STATE) and c.get(CONF_OT_MODE) and c.get(CONF_ROOM))}


    async def async_set_control(self, control: str) -> None:
        """Thermostat or OpenTherm, from the card. Changes the options, so Roost reloads (the master's control mode
        follows on the first round: back on its curve when Roost no longer steers it)."""
        from homeassistant.exceptions import ServiceValidationError
        if control not in CONTROLS:
            raise ServiceValidationError(f"control: one of {', '.join(CONTROLS)}", translation_domain=DOMAIN, translation_key="control_unknown",
                                         translation_placeholders={"options": ", ".join(CONTROLS)})
        if not self.control_choices()[control]:
            ot = control == "opentherm"
            raise ServiceValidationError("OpenTherm needs the master's entities and a room sensor (Configure > Steering)"
                                         if ot else "Steering by thermostat needs a thermostat (Configure > The house)",
                                         translation_domain=DOMAIN, translation_key="control_ot_missing" if ot else "control_thermostat_missing")
        if self.h.conf.get(CONF_CONTROL) == control:
            return
        self.h.event("control", new=control)
        self.h.hass.config_entries.async_update_entry(self.h.entry, options={**self.h.entry.options, CONF_CONTROL: control})


    def card_settings(self, changes: dict) -> dict:
        """The entities the card shows (cardstate.py); checked here, saved with the rest.
        A pump entity "" goes back to the one found on the device."""
        from homeassistant.exceptions import ServiceValidationError

        from .const import CONF_PUMP_ENTITIES, PUMP_ROLES
        out = {}
        if "pump_entities" in changes:
            given = changes["pump_entities"] or {}
            if not isinstance(given, dict) or any(k not in PUMP_ROLES for k in given):
                raise ServiceValidationError(f"pump_entities: a mapping of {', '.join(PUMP_ROLES)} to an entity",
                                             translation_domain=DOMAIN, translation_key="pump_entities", translation_placeholders={"roles": ", ".join(PUMP_ROLES)})
            cur = dict(self.h.conf.get(CONF_PUMP_ENTITIES) or {})
            for role, eid in given.items():
                if not eid:
                    cur.pop(role, None)
                elif not isinstance(eid, str) or self.h.hass.states.get(eid) is None:
                    raise ServiceValidationError(f"pump_entities: {role}: no such entity {eid}", translation_domain=DOMAIN, translation_key="pump_entity_missing",
                                                 translation_placeholders={"role": str(role), "entity": str(eid)})
                else:
                    cur[role] = eid
            out[CONF_PUMP_ENTITIES] = cur
        return out

    # ------------------------------------------------------------ the weekly summary (Monday morning, when chosen)
    async def async_weekly(self, _now: datetime) -> None:
        if not self.h.conf.get(CONF_WEEKLY) or dt_util.now().weekday() != 0:
            return
        fmt = weekly_summary(self.h.log.day_stats, self.h.log.hour_log, dt_util.now().date(), self.texts(), self.h.hass.config.currency or "EUR")
        if fmt is not None:
            self.notify_user("weekly", force=True, **fmt)
