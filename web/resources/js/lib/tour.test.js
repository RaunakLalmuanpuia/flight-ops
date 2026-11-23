import { test } from 'node:test';
import assert from 'node:assert/strict';
import { STEPS, stepFromQuery, stepHref } from './tour.js';

test('five steps, each with a page, a title and what to look at and click', () => {
    assert.equal(STEPS.length, 5);
    for (const s of STEPS) assert.ok(s.href.startsWith('/') && !s.href.includes('?') && s.title && s.look && s.click, s.title);
});

test('reads the step from the query, null when missing or out of range', () => {
    assert.equal(stepFromQuery('tour=3'), 3);
    assert.equal(stepFromQuery('?tour=1&delay=60'), 1);
    for (const q of ['', 'tour=', 'tour=0', 'tour=6', 'tour=abc', 'tour=2.5']) assert.equal(stepFromQuery(q), null, q);
});

test('step links carry the step number and stop at the ends', () => {
    assert.equal(stepHref(1), '/day/2024-07-19?tour=1');
    assert.equal(stepHref(0), null);
    assert.equal(stepHref(6), null);
});
