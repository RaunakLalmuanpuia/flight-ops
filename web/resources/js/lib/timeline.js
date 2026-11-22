export const STATUSES = ['on_time', 'delayed', 'diverted', 'cancelled'];

const empty = () => Object.fromEntries(STATUSES.map((s) => [s, 0]));

// One entry per ATL local hour, with each direction's counts by status, zero-filled.
export function hourBuckets(hourly) {
    const hours = Array.from({ length: 24 }, (_, hour) => ({ hour, dep: empty(), arr: empty() }));
    for (const row of hourly) {
        for (const s of STATUSES) hours[row.atl_hour][row.direction][s] = Number(row[s]);
    }
    return hours;
}

export function total(counts) {
    return STATUSES.reduce((sum, s) => sum + counts[s], 0);
}

export function maxScheduled(hours) {
    return Math.max(1, ...hours.flatMap((h) => [total(h.dep), total(h.arr)]));
}

// Segments outward from the axis: on time nearest it, cancelled outermost.
export function stack(counts, scale) {
    let offset = 0;
    return STATUSES.filter((s) => counts[s] > 0).map((status) => {
        const segment = { status, offset, length: counts[status] * scale };
        offset += segment.length;
        return segment;
    });
}

export function weatherByHour(weather) {
    const hours = Array.from({ length: 24 }, (_, hour) => ({ hour, adverse: false, reports: [] }));
    for (const m of weather) {
        hours[m.atl_hour].adverse ||= m.adverse;
        hours[m.atl_hour].reports.push(m.raw_text);
    }
    return hours;
}
