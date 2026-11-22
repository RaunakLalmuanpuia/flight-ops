import { toDate } from './time.js';

export const STALE_AFTER_MIN = 5; // the loop polls every 60 s, so 5 minutes means it stopped or keeps failing
const LEVEL_FPM = 300; // under this either way, call it level

export const LIVE_REASONS = {
    'hex not in FAA registry': 'Not in the FAA registry (foreign or military)',
    'ambiguous hex': 'Hex on more than one FAA registration',
    'general aviation callsign': 'Flying under its tail number',
    'unknown prefix': 'Callsign prefix not in our operator list',
    'no callsign': 'No callsign broadcast',
};

export function freshness(loadedAt, now) {
    if (!loadedAt) return { state: 'never', minutes: null };
    const minutes = Math.floor((toDate(now) - toDate(loadedAt)) / 60000);
    return { state: minutes > STALE_AFTER_MIN ? 'stale' : 'fresh', minutes };
}

export function motion({ on_ground, vertical_rate_fpm: v }) {
    if (on_ground) return 'on ground';
    if (v === null || v === undefined) return '—';
    return v >= LEVEL_FPM ? 'climbing' : v <= -LEVEL_FPM ? 'descending' : 'level';
}
