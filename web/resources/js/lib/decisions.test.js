import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ACTIONS, rememberAuthor, rememberedAuthor, targetLabel } from './decisions.js';

test('actions match the database check constraint, in order', () => {
    assert.deepEqual(Object.keys(ACTIONS), ['accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other']);
});

test('the author round-trips through storage', () => {
    const map = new Map();
    const storage = { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v) };
    assert.equal(rememberedAuthor(storage), '');
    rememberAuthor('duty controller', storage);
    assert.equal(rememberedAuthor(storage), 'duty controller');
});

test('storage that throws or is missing leaves the author empty', () => {
    const blocked = {
        getItem() { throw new Error('blocked'); },
        setItem() { throw new Error('blocked'); },
    };
    assert.equal(rememberedAuthor(blocked), '');
    assert.doesNotThrow(() => rememberAuthor('x', blocked));
    assert.equal(rememberedAuthor(null), '');
    assert.doesNotThrow(() => rememberAuthor('x', null));
});

test('a target is labelled with its depth, route and local departure', () => {
    const leg = { depth: 2, kind: 'flown', carrier: 'DL', flight_number: '2590', origin: 'ATL', dest: 'BWI', sched_dep_utc: '2024-07-20 02:50:00+00', origin_tz: 'America/New_York' };
    assert.equal(targetLabel(leg), '2 · DL 2590 ATL → BWI · Jul 19 22:50');
    assert.equal(targetLabel({ ...leg, kind: 'cancelled' }), '2 · DL 2590 ATL → BWI · Jul 19 22:50 · cancelled');
});
