import { test } from 'node:test';
import assert from 'node:assert/strict';
import { axis, bar, dayBand, dayMarks, gapLabel, hoursMinutes, lateText } from './legs.js';

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
        'Starts at LGA but last landed at ATL: Likely flew legs BTS does not report',
    );
});

test('minutes read as hours and minutes', () => {
    assert.equal(hoursMinutes(275), '4h 35m');
    assert.equal(hoursMinutes(45), '45m');
    assert.equal(hoursMinutes(-20), '-20m');
});

const NY = 'America/New_York';
const wide = { start: Date.parse('2024-07-18T20:00:00Z'), end: Date.parse('2024-07-20T20:00:00Z') };

test('day marks sit at each local midnight inside the span', () => {
    const marks = dayMarks(wide, NY);
    assert.deepEqual(marks.map((m) => m.day), ['2024-07-19', '2024-07-20']);
    assert.ok(Math.abs(marks[0].left - (8 / 48) * 100) < 1e-9);
    assert.ok(Math.abs(marks[1].left - (32 / 48) * 100) < 1e-9);
});

test('day band covers the local day, clamped to the span', () => {
    const b = dayBand('2024-07-19', wide, NY);
    assert.ok(Math.abs(b.left - (8 / 48) * 100) < 1e-9);
    assert.ok(Math.abs(b.width - 50) < 1e-9);
    const c = dayBand('2024-07-20', wide, NY);
    assert.ok(Math.abs(c.left - (32 / 48) * 100) < 1e-9);
    assert.ok(Math.abs(c.width - (16 / 48) * 100) < 1e-9);
    assert.equal(dayBand('2024-07-25', wide, NY), null);
});

test('late text names the delayed parts, and is null on time', () => {
    assert.equal(lateText({ dep_delay_min: 31, arr_delay_min: 9 }), 'left +31 min · landed +9 min');
    assert.equal(lateText({ dep_delay_min: 316, arr_delay_min: 316 }), 'left +316 min · landed +316 min');
    assert.equal(lateText({ dep_delay_min: null, arr_delay_min: 20 }), 'landed +20 min');
    assert.equal(lateText({ dep_delay_min: -5, arr_delay_min: 29 }), 'left -5 min · landed +29 min');
    assert.equal(lateText({ dep_delay_min: 5, arr_delay_min: 14 }), null);
    assert.equal(lateText({ dep_delay_min: null, arr_delay_min: null }), null);
});
