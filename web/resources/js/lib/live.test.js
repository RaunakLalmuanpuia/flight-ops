import { test } from 'node:test';
import assert from 'node:assert/strict';
import { freshness, motion, LIVE_REASONS } from './live.js';

const now = '2026-11-22 18:00:00+00';

test('no poll ever loaded', () => {
    assert.deepEqual(freshness(null, now), { state: 'never', minutes: null });
});

test('a poll within five minutes is fresh', () => {
    assert.deepEqual(freshness('2026-11-22 17:56:00+00', now), { state: 'fresh', minutes: 4 });
});

test('a poll over five minutes old is stale', () => {
    assert.deepEqual(freshness('2026-11-22 17:42:30+00', now), { state: 'stale', minutes: 17 });
});

test('motion from the vertical rate, with ground first', () => {
    assert.equal(motion({ on_ground: true, vertical_rate_fpm: 1500 }), 'on ground');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: 1500 }), 'climbing');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: -800 }), 'descending');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: 100 }), 'level');
    assert.equal(motion({ on_ground: false, vertical_rate_fpm: null }), '—');
});

test('every reason the pipeline writes has a label', () => {
    for (const r of ['hex not in FAA registry', 'ambiguous hex', 'general aviation callsign', 'unknown prefix', 'no callsign']) {
        assert.ok(LIVE_REASONS[r], r);
    }
});
