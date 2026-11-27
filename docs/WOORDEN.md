# Woordenlijst Roost (gebruikerstaal)

Vastgesteld op 22-11-2026. Gebruik deze woorden overal: op de kaart, in de opties, in meldingen, op de
webpagina van het kastje en in de documentatie. Entity-id's en ESPHome-namen blijven zoals ze zijn (bij ESPHome volgt
de id uit de naam, en Roost vindt het kastje daarop): alleen de zichtbare tekst verandert.

| Begrip | NL | EN | Niet meer gebruiken |
|---|---|---|---|
| Het apparaat tussen HA en de Weheat | OpenTherm-kastje (daarna: kastje) | OpenTherm box | gateway, master (hooguit één keer "(gateway)" als uitleg) |
| Roost stuurt niet, het kastje stookt zelf | terugval | fallback | vangnet, noodstand, "eigen stooklijn" als toestand |
| De stooklijn op het kastje | stooklijn bij terugval | fallback curve | terugvalstooklijn, curve |
| Roosts advies voor de Weheat-app | stooklijnadvies | heating curve advice | aanbevolen stooklijn |
| Doel voor de woonkamer | comfort | comfort | doel, kamerdoel (behalve "kamer bij terugval" op het kastje) |
| Wat Roost per uur vraagt bij OpenTherm | aanvoer (watertemperatuur) | flow (water temperature) | setpoint |
| Warmte vooruit stoken | warmte opslaan (in de vloer) | store heat (in the floor) | opladen |
| Rendement | rendement (COP) | efficiency (COP) | COP zonder uitleg op het hoofdscherm |

## Eigenaar van instellingen
Laagste en hoogste aanvoer en minimaal aan/uit horen bij **het kastje**: het bewaakt de pomp ook zonder Roost.
- Roost toont ze en verwijst naar de webpagina van het kastje.
- Roost wijzigt ze niet zelf; dubbele instellingen in de Roost-opties gaan weg (nog uit te voeren).
- Voor installaties zonder ons kastje (een andere OpenTherm-gateway): de waarden blijven in de Roost-opties, met de uitleg dat ze daar alleen gelden als het apparaat ze zelf niet heeft.
