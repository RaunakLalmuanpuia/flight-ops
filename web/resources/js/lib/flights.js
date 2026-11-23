import { GLOSSARY } from './glossary.js';
import { toDate } from './time.js';

// Data warning keys match glossary keys, so the chip and its definition cannot drift
export const CAVEATS = Object.fromEntries(
    ['metar_stale', 'rotation_break', 'aircraft_unresolved', 'aircraft_medium_confidence', 'block_mismatch', 'no_tail'].map((k) => [k, GLOSSARY[k].plain]),
);

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

export const CANCELLATION = { A: 'carrier', B: 'weather', C: 'NAS', D: 'security' };

// Scheduled ATL time order; flight_id breaks ties so the order is stable.
export function byAtlTime(flights) {
    const t = (f) => toDate(atlEvent(f).sched).getTime();
    return [...flights].sort((a, b) => t(a) - t(b) || a.flight_id - b.flight_id);
}
