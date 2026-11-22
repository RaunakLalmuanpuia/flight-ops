export const CAVEATS = {
    metar_stale: 'No METAR within 90 min',
    rotation_break: 'Rotation break',
    aircraft_unresolved: 'Aircraft not resolved',
    aircraft_medium_confidence: 'Medium-confidence aircraft',
    block_mismatch: 'Elapsed time disagrees with times',
    no_tail: 'No tail reported',
};

const CAUSES = { carrier: 'carrier', weather: 'weather', nas: 'NAS', security: 'security', late_aircraft: 'late aircraft' };

// The times and delay at ATL: departures leave ATL, arrivals land there.
export function atlEvent(f) {
    return f.direction === 'dep'
        ? { sched: f.sched_dep_utc, actual: f.actual_dep_utc, delay: f.dep_delay_min }
        : { sched: f.sched_arr_utc, actual: f.actual_arr_utc, delay: f.arr_delay_min };
}

export function caveatsOf(f) {
    return Object.keys(CAVEATS).filter((k) => f[k]);
}

export function filterFlights(flights, { direction = '', carrier = '', status = '', hour = null, caveat = '' }) {
    return flights.filter(
        (f) =>
            (!direction || f.direction === direction) &&
            (!carrier || f.carrier === carrier) &&
            (!status || f.status === status) &&
            (hour === null || f.atl_hour === hour) &&
            (!caveat || f[caveat]),
    );
}

// delays arrives as the jsonb text Postgres sends, e.g. '{"carrier": 10}'.
export function delayText(delays) {
    if (!delays) return '';
    return Object.entries(JSON.parse(delays))
        .map(([cause, minutes]) => `${CAUSES[cause] ?? cause} ${minutes}`)
        .join(', ');
}
