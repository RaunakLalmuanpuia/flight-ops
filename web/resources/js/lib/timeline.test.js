import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hourBuckets, maxScheduled, stack, total, weatherByHour } from './timeline.js';

const hourly = [
    { atl_hour: 8, direction: 'dep', on_time: 3, delayed: '2', diverted: 0, cancelled: 5 },
    { atl_hour: 8, direction: 'arr', on_time: 1, delayed: 0, diverted: 1, cancelled: 0 },
];

test('fills all 24 hours and both directions with zeros', () => {
    const hours = hourBuckets(hourly);
    assert.equal(hours.length, 24);
    assert.deepEqual(hours[0].dep, { on_time: 0, delayed: 0, diverted: 0, cancelled: 0 });
    assert.deepEqual(hours[8].dep, { on_time: 3, delayed: 2, diverted: 0, cancelled: 5 });
    assert.equal(total(hours[8].arr), 2);
});

test('the scale uses the busiest hour in either direction and is never zero', () => {
    assert.equal(maxScheduled(hourBuckets(hourly)), 10);
    assert.equal(maxScheduled(hourBuckets([])), 1);
});

test('stacks outward from the axis and skips empty statuses', () => {
    assert.deepEqual(stack({ on_time: 3, delayed: 2, diverted: 0, cancelled: 5 }, 2), [
        { status: 'on_time', offset: 0, length: 6 },
        { status: 'delayed', offset: 6, length: 4 },
        { status: 'cancelled', offset: 10, length: 10 },
    ]);
});

test('an hour is adverse if any METAR in it is', () => {
    const hours = weatherByHour([
        { atl_hour: 8, adverse: false, raw_text: 'A' },
        { atl_hour: 8, adverse: true, raw_text: 'B' },
    ]);
    assert.equal(hours[8].adverse, true);
    assert.deepEqual(hours[8].reports, ['A', 'B']);
    assert.equal(hours[9].adverse, false);
});
