// shortcut: one hub, so its timezone is fixed here; phase 6 should pass it from app_read
export const ATL_TZ = 'America/New_York';

// Postgres sends timestamptz as "2024-07-19 12:00:00+00"; Date wants ISO 8601.
export function toDate(value) {
    if (!value) return null;
    return new Date(value.replace(' ', 'T').replace(/([+-]\d{2})$/, '$1:00'));
}

export function localTime(value, timeZone) {
    const date = toDate(value);
    return date ? new Intl.DateTimeFormat('en-US', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(date) : '';
}

export function localDate(value, timeZone) {
    const date = toDate(value);
    return date ? new Intl.DateTimeFormat('en-US', { timeZone, month: 'short', day: 'numeric' }).format(date) : '';
}

export function utcTitle(value) {
    const date = toDate(value);
    return date ? `${date.toISOString().slice(0, 16).replace('T', ' ')}Z` : '';
}

export function shiftDay(day, days) {
    const date = new Date(`${day}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

export function shortDate(day) {
    return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' }).format(new Date(`${day}T00:00:00Z`));
}

// UTC instant of local midnight starting `day`: shift a UTC guess by the zone's offset at that instant.
export function zonedMidnight(day, timeZone) {
    const guess = Date.parse(`${day}T00:00:00Z`);
    const p = Object.fromEntries(
        new Intl.DateTimeFormat('en-US', { timeZone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric' })
            .formatToParts(new Date(guess)).map((x) => [x.type, +x.value]),
    );
    return guess - (Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - guess);
}
