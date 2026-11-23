import { shiftDay, toDate, zonedMidnight } from './time.js';

export const REASONS = {
    no_faa_record: 'no US registration found for this aircraft',
    ambiguous_window: 'more than one registration covers the date',
    no_window_multiple_airframes: 'no registration covers the date, and the registration has been on several aircraft',
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
    return `Starts at ${leg.origin} but last landed at ${leg.prev_station}: ${leg.break_label}`;
}

export function hoursMinutes(minutes) {
    if (Math.abs(minutes) < 60) return `${minutes}m`;
    return `${Math.trunc(minutes / 60)}h ${Math.abs(minutes % 60)}m`;
}

// Local midnights strictly inside the span, as percent of it.
export function dayMarks({ start, end }, timeZone) {
    const marks = [];
    const length = end - start || 1;
    let day = new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date(start));
    for (let at = zonedMidnight(day, timeZone); at < end; day = shiftDay(day, 1), at = zonedMidnight(day, timeZone)) {
        if (at > start) marks.push({ day, left: ((at - start) / length) * 100 });
    }
    return marks;
}

// The part of the span covered by one local day, or null.
export function dayBand(day, { start, end }, timeZone) {
    const from = Math.max(zonedMidnight(day, timeZone), start);
    const to = Math.min(zonedMidnight(shiftDay(day, 1), timeZone), end);
    if (to <= from) return null;
    const length = end - start || 1;
    return { left: ((from - start) / length) * 100, width: ((to - from) / length) * 100 };
}

const signed = (n) => (n > 0 ? `+${n}` : `${n}`);

export function lateText(leg) {
    const dep = leg.dep_delay_min;
    const arr = leg.arr_delay_min;
    if (!(dep >= 15 || arr >= 15)) return null;
    return [dep != null && `left ${signed(dep)} min`, arr != null && `landed ${signed(arr)} min`].filter(Boolean).join(' · ');
}
