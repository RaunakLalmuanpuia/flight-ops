import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CANCEL_RISK_CAVEAT, cancelRisk } from './risk.js';

test('a scored leg shows its rate to one decimal, its basis, and a flag at the threshold', () => {
    assert.deepEqual(cancelRisk({ cancel_risk: '0.49503', cancel_risk_basis: 'DL, 1309 samples' }, 0.183), {
        text: '49.5%', flagged: true, basis: 'DL, 1309 samples',
    });
    assert.equal(cancelRisk({ cancel_risk: '0.183', cancel_risk_basis: 'x' }, 0.183).flagged, true);
    assert.equal(cancelRisk({ cancel_risk: '0.1829', cancel_risk_basis: 'x' }, 0.183).flagged, false);
});

test('an unscored leg says why, or just not scored', () => {
    assert.deepEqual(cancelRisk({ cancel_risk: null, cancel_risk_basis: 'not scored: diverted' }, 0.183), {
        text: 'not scored: diverted', flagged: false, basis: null,
    });
    assert.deepEqual(cancelRisk({ cancel_risk: null, cancel_risk_basis: null }, 0.183), { text: 'not scored', flagged: false, basis: null });
});

test('the caveat names the fit, the holdout, the known-at proxy and the what-if limit', () => {
    assert.match(CANCEL_RISK_CAVEAT, /fitted on July 2024 and scored on August/);
    assert.match(CANCEL_RISK_CAVEAT, /scheduled departure/);
    assert.match(CANCEL_RISK_CAVEAT, /what-if changes only the delay band/);
});
