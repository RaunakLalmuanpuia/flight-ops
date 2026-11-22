import { test } from 'node:test';
import assert from 'node:assert/strict';
import { axis, bar, gapLabel, hoursMinutes } from './legs.js';

const legs = [
    { sched_dep_utc: '2024-07-19 12:00:00+00', sched_arr_utc: '2024-07-19 14:00:00+00', actual_dep_utc: null, actual_arr_utc: null },
    { sched_dep_utc: '2024-07-19 15:00:00+00', sched_arr_utc: '2024-07-19 15:30:00+00', actual_dep_utc: '2024-07-19 15:10:00+00', actual_arr_utc: '2024-07-19 16:00:00+00' },
];

test('the axis spans every known time', () => {
    assert.deepEqual(axis(legs), { start: Date.parse('2024-07-19T12:00:00Z'), end: Date.parse('2024-07-19T16:00:00Z') });
});

test('a bar is placed in percent of the axis', () => {
    const a = axis(legs);
    assert.deepEqual(bar('2024-07-19 13:00:00+00', '2024-07-19 14:00:00+00', a), { left: 25, width: 25 });
    assert.equal(bar(null, '2024-07-19 14:00:00+00', a), null);
});

test('a gap label appears only where the rotation breaks', () => {
    assert.equal(gapLabel({ connects: true }), null);
    assert.equal(gapLabel({ connects: null }), null);
    assert.equal(
        gapLabel({ connects: false, origin: 'LGA', prev_station: 'ATL', break_label: 'Likely flew legs BTS does not report' }),
        'Next origin LGA ≠ previous arrival ATL: Likely flew legs BTS does not report',
    );
});

test('minutes read as hours and minutes', () => {
    assert.equal(hoursMinutes(275), '4h 35m');
    assert.equal(hoursMinutes(45), '45m');
    assert.equal(hoursMinutes(-20), '-20m');
});
