"""Curated registry of Italian EV charge-point operators (CPOs) → their
official tariff pages.

**Why this exists instead of per-station prices.** pitstop parses OSM's `fee`
yes/no flag and no price field, so it has no per-kWh number to report. Rather
than guess one, it surfaces the **operator's own tariff page**, where the agent
or user can read authoritative numbers in one click."""

from __future__ import annotations

# Keyed by normalized operator substring (lowercased). Lookup is by substring
# match against the station's `operator` tag, so minor naming differences
# (e.g. "Alperia Smart Mobility" vs "Alperia") still resolve.
TARIFF_URLS: dict[str, str] = {
    "alperia":     "https://www.alperia.eu/it/elettrica-ricarica.html",
    "neogy":       "https://www.neogy.it/it/ricarica-pubblica.html",
    "enel x way":  "https://www.enelxway.com/it/it/privati/ricaricare-elettrica/pubblica",
    "enel x":      "https://www.enelxway.com/it/it/privati/ricaricare-elettrica/pubblica",
    "enel":        "https://www.enelxway.com/it/it/privati/ricaricare-elettrica/pubblica",
    "be charge":   "https://www.be-charge.com/it/tariffe/",
    "becharge":    "https://www.be-charge.com/it/tariffe/",
    "free to x":   "https://www.freetox.com/tariffe/",
    "freetox":     "https://www.freetox.com/tariffe/",
    "ionity":      "https://ionity.eu/it/charging/network/pricing",
    "tesla":       "https://www.tesla.com/it_it/supercharger",
    "plenitude":   "https://eniplenitude.com/mobilita-elettrica",
    "eni":         "https://eniplenitude.com/mobilita-elettrica",
    "atlante":     "https://www.atlante.energy/",
    "repower":     "https://www.repower.com/it/clienti-business/e-mobility/",
    "duferco":     "https://www.duferco.it/it/duferco-energia/mobilita-elettrica.html",
    "a2a":         "https://www.a2aenergia.eu/casa/mobilita-elettrica",
    "edison":      "https://www.edisonenergia.it/edison/mobilita-elettrica",
    "acea":        "https://www.acea.it/clienti-acea-energia/mobilita-elettrica",
    "evway":       "https://www.evway.net/it/",
    "ev-now":      "https://www.ev-now.it/",
    "movyon":      "https://www.movyon.com/",
    "bike-energy": "https://www.bike-energy.com/",  # for e-bike chargers
}


def lookup(operator: str) -> str | None:
    """Return the official tariff page URL for an operator, or None if unknown.

    Substring match (case-insensitive) so naming variants resolve."""
    if not operator:
        return None
    op = operator.strip().lower()
    # Try exact-substring matches in order of decreasing key length so that
    # "Enel X Way" wins over "Enel" when both would match.
    for key in sorted(TARIFF_URLS.keys(), key=len, reverse=True):
        if key in op:
            return TARIFF_URLS[key]
    return None
