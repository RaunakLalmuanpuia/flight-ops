import { localDate, localTime } from './time.js';

// Same set and order as app.decision's check constraint (migration 022)
export const ACTIONS = {
    accept_delay: 'Accept the delay',
    hold_departure: 'Hold a departure',
    swap_aircraft: 'Swap aircraft',
    cancel_leg: 'Cancel a leg',
    other: 'Other',
};

const KEY = 'flightops.author';

// Storage can be missing or throw (private window, blocked site data); the field then starts empty.
export function rememberedAuthor(storage = globalThis.localStorage) {
    try {
        return storage?.getItem(KEY) ?? '';
    } catch {
        return '';
    }
}

export function rememberAuthor(author, storage = globalThis.localStorage) {
    try {
        storage?.setItem(KEY, author);
    } catch {
        // not remembered; the form still works
    }
}

export function targetLabel(leg) {
    const when = `${localDate(leg.sched_dep_utc, leg.origin_tz)} ${localTime(leg.sched_dep_utc, leg.origin_tz)}`;
    return `${leg.depth} · ${leg.carrier} ${leg.flight_number} ${leg.origin} → ${leg.dest} · ${when}${leg.kind === 'cancelled' ? ' · cancelled' : ''}`;
}
