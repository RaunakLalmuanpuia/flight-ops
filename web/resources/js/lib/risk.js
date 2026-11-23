// cancel_risk arrives as a numeric string from Postgres; NULL keeps the basis as the reason
export function cancelRisk(leg, threshold) {
    if (leg.cancel_risk === null || leg.cancel_risk === undefined) {
        return { text: leg.cancel_risk_basis ?? 'not scored', flagged: false, basis: null };
    }
    const risk = Number(leg.cancel_risk);
    return { text: `${(100 * risk).toFixed(1)}%`, flagged: risk >= threshold, basis: leg.cancel_risk_basis };
}

export const CANCEL_RISK_CAVEAT =
    "Cancel risk is how often legs like this one were cancelled in July 2024: the tail's next three scheduled legs within 24 h of this arrival, by carrier, place in the schedule, arrival-delay band and carrier stress (the share of the carrier's departures cancelled in the three clock hours before this flight left, other aircraft only). It is fitted on July 2024 and scored on August. A cancellation counts as known only from its scheduled departure, because BTS gives no announcement time. A what-if changes only the delay band. The badge marks the July threshold that best balanced catching cancellations against false alarms, which mostly fires on outage-scale days.";
