// cancel_risk arrives as a numeric string from Postgres; NULL keeps the basis as the reason
export function cancelRisk(leg, threshold) {
    if (leg.cancel_risk === null || leg.cancel_risk === undefined) {
        return { text: leg.cancel_risk_basis ?? 'not scored', flagged: false, basis: null };
    }
    const risk = Number(leg.cancel_risk);
    return { text: `${(100 * risk).toFixed(1)}%`, flagged: risk >= threshold, basis: leg.cancel_risk_basis };
}

export const CANCEL_RISK_CAVEAT =
    'Chance of cancellation is how often flights like this one were cancelled in July 2024. "Like this one" means the same airline, the same place among the aircraft\'s next three flights within 24 hours of this arrival, a similar arrival delay, and similar airline stress: the share of the airline\'s departures cancelled in the three hours before this flight left, other aircraft only. It is fitted on July 2024 and scored on August. A cancellation counts as known only from its scheduled departure, because US flight records (BTS) give no time it was announced. A what-if changes only the delay band. The red badge marks the July threshold that best balanced catching cancellations against false alarms, and it mostly fires on outage-scale days.';
