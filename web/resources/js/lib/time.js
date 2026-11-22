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
