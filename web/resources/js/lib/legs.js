import { toDate } from './time.js';

export const REASONS = {
    no_faa_record: 'no FAA registration found for this tail',
    ambiguous_window: 'more than one registration covers the date',
    no_window_multiple_airframes: 'no registration covers the date, and the tail has had several airframes',
};

export function axis(legs) {
    const times = legs
        .flatMap((l) => [l.sched_dep_utc, l.sched_arr_utc, l.actual_dep_utc, l.actual_arr_utc])
        .filter(Boolean)
        .map((t) => toDate(t).getTime());
    return { start: Math.min(...times), end: Math.max(...times) };
}

// Left edge and width of a bar, in percent of the axis.
export function bar(from, to, { start, end }) {
    if (!from || !to) return null;
    const span = end - start || 1;
    const a = toDate(from).getTime();
    const b = toDate(to).getTime();
    return { left: ((a - start) / span) * 100, width: Math.max(((b - a) / span) * 100, 0.5) };
}

export function gapLabel(leg) {
    if (leg.connects !== false) return null;
    return `Next origin ${leg.origin} ≠ previous arrival ${leg.prev_station}: ${leg.break_label}`;
}

export function hoursMinutes(minutes) {
    if (Math.abs(minutes) < 60) return `${minutes}m`;
    return `${Math.trunc(minutes / 60)}h ${Math.abs(minutes % 60)}m`;
}
