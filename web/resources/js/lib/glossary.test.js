import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GLOSSARY, GROUPS } from './glossary.js';

const groups = GROUPS.map(([k]) => k);

test('every entry has a plain label, one-line meaning, deeper note and a known group', () => {
    for (const [key, e] of Object.entries(GLOSSARY)) {
        assert.match(key, /^[a-z0-9_]+$/, key);
        assert.ok(e.plain && e.short && e.deeper, key);
        assert.ok(e.term === null || typeof e.term === 'string', key);
        assert.ok(groups.includes(e.group), `${key}: ${e.group}`);
    }
});

test('every group has at least one entry', () => {
    for (const g of groups) assert.ok(Object.values(GLOSSARY).some((e) => e.group === g), g);
});

test('the terms the tour leans on are defined', () => {
    for (const k of ['tail', 'rotation', 'slack', 'min_turn', 'propagation', 'at_risk', 'cancel_risk', 'metar', 'what_if', 'decision_log']) {
        assert.ok(GLOSSARY[k], k);
    }
});
