import { test } from 'node:test';
import assert from 'node:assert/strict';
import { atlEvent, caveatsOf, delayText, filterFlights } from './flights.js';

const dep = { direction: 'dep', carrier: 'DL', status: 'delayed', atl_hour: 0, sched_dep_utc: 'S', actual_dep_utc: 'A', dep_delay_min: 30, metar_stale: true };
const arr = { direction: 'arr', carrier: '9E', status: 'on_time', atl_hour: 8, sched_arr_utc: 's', actual_arr_utc: 'a', arr_delay_min: -3, metar_stale: false };

test('the ATL event is the departure or the arrival', () => {
    assert.deepEqual(atlEvent(dep), { sched: 'S', actual: 'A', delay: 30 });
    assert.deepEqual(atlEvent(arr), { sched: 's', actual: 'a', delay: -3 });
});

test('filters combine, and hour 0 is a real filter', () => {
    assert.deepEqual(filterFlights([dep, arr], { hour: 0 }), [dep]);
    assert.deepEqual(filterFlights([dep, arr], { carrier: '9E', status: 'on_time' }), [arr]);
    assert.deepEqual(filterFlights([dep, arr], { caveat: 'metar_stale' }), [dep]);
    assert.deepEqual(filterFlights([dep, arr], {}), [dep, arr]);
});

test('lists the caveats a flight carries', () => {
    assert.deepEqual(caveatsOf(dep), ['metar_stale']);
    assert.deepEqual(caveatsOf(arr), []);
});

test('reads delay causes from the jsonb text', () => {
    assert.equal(delayText('{"carrier": 10, "late_aircraft": 20}'), 'carrier 10, late aircraft 20');
    assert.equal(delayText(null), '');
});
