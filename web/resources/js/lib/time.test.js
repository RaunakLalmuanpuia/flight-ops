import { test } from 'node:test';
import assert from 'node:assert/strict';
import { localDate, localTime, shiftDay, toDate, utcTitle } from './time.js';

test('parses Postgres timestamptz with short and long offsets', () => {
    assert.equal(toDate('2024-07-19 12:00:00+00').toISOString(), '2024-07-19T12:00:00.000Z');
    assert.equal(toDate('2024-07-19 17:30:00+05:30').toISOString(), '2024-07-19T12:00:00.000Z');
    assert.equal(toDate(null), null);
});

test('formats the time in the station timezone', () => {
    assert.equal(localTime('2024-07-19 12:00:00+00', 'America/New_York'), '08:00');
    assert.equal(localTime('2024-07-19 12:00:00+00', 'America/Los_Angeles'), '05:00');
    assert.equal(localTime(null, 'America/New_York'), '');
});

test('the local date follows the station timezone', () => {
    assert.equal(localDate('2024-07-20 02:30:00+00', 'America/New_York'), 'Jul 19');
});

test('UTC title for hover', () => {
    assert.equal(utcTitle('2024-07-19 12:05:00+00'), '2024-07-19 12:05Z');
    assert.equal(utcTitle(null), '');
});

test('shiftDay crosses month ends', () => {
    assert.equal(shiftDay('2024-07-31', 1), '2024-08-01');
    assert.equal(shiftDay('2024-07-01', -1), '2024-06-30');
});
