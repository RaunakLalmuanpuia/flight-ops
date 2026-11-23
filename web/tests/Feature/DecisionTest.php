<?php

use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Illuminate\Testing\TestResponse;
use Inertia\Testing\AssertableInertia as Assert;

// Every test rolls back, so the real decision log never holds test rows.
uses(DatabaseTransactions::class);

function bwi(): int
{
    // ATL->BWI 2590, the flown leg after N102DN's 316-min arrival
    return DB::selectOne("select flight_id from propagate(?) where kind = 'flown' and flight_number = '2590'", [n102dn()])->flight_id;
}

function decision(array $fields = []): TestResponse
{
    return test()->post('/flights/'.n102dn().'/decisions', array_merge(
        ['action' => 'cancel_leg', 'target' => bwi(), 'reason' => 'protect the BWI bank', 'author' => 'pest'],
        $fields,
    ));
}

function pestDecisions(): int
{
    return DB::selectOne("select count(*) as n from decision_review where author = 'pest'")->n;
}

it('records a decision with its frozen chain and opens it', function () {
    $response = decision();

    $d = DB::selectOne("select * from decision_review where author = 'pest'");
    $response->assertRedirect("/decisions/{$d->decision_id}");
    expect($d->action)->toBe('cancel_leg')
        ->and($d->target_flight_number)->toBe('2590')
        ->and($d->arr_delay_min)->toBe(316)
        ->and($d->what_if)->toBeFalse()
        ->and($d->match_label)->toBe('airline flew it, +49 min');
    expect(DB::selectOne('select count(*) as n from decision_legs where decision_id = ?', [$d->decision_id])->n)->toBe(5);
});

it('freezes a what-if delay', function () {
    $response = decision(['delay' => 600]);

    $d = DB::selectOne("select decision_id, arr_delay_min, what_if, target_predicted_dep_delay from decision_review where author = 'pest'");
    $response->assertRedirect("/decisions/{$d->decision_id}");
    expect([$d->arr_delay_min, $d->what_if, $d->target_predicted_dep_delay])->toBe([600, true, 63]);
});

it('rejects a form that fails validation, recording nothing', function (array $fields, string $field) {
    decision($fields)->assertSessionHasErrors($field);
    expect(pestDecisions())->toBe(0);
})->with([
    'blank reason' => [['reason' => '  '], 'reason'],
    'blank author' => [['author' => ''], 'author'],
    'unknown action' => [['action' => 'ground_stop'], 'action'],
    'target on accept' => [['action' => 'accept_delay'], 'target'],
    'delay out of range' => [['delay' => 1441], 'delay'],
]);

it('shows a database refusal as a form error, recording nothing', function () {
    decision(['target' => n102dn()])->assertSessionHasErrors(['decision' => 'The target is not a later leg in this chain.']);
    expect(pestDecisions())->toBe(0);
});

it('lists earlier decisions on the flight, newest first', function () {
    decision(['action' => 'hold_departure']);
    decision(['action' => 'swap_aircraft', 'reason' => 'second look']);

    $this->get('/flights/'.n102dn())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('FlightImpact')
        ->where('decisions.0.action', 'swap_aircraft')
        ->where('decisions.0.author', 'pest')
        ->where('decisions.0.target_flight_number', '2590')
        ->where('decisions.0.match_label', 'this tail flew it, +49 min (swap not visible)')
        ->where('decisions.1.action', 'hold_departure'));
});

function pestDecisionId(): int
{
    return DB::selectOne("select decision_id from decision_review where author = 'pest' order by decision_id desc limit 1")->decision_id;
}

it('lists decisions newest first with their outcome', function () {
    decision(['action' => 'hold_departure']);
    decision(['action' => 'accept_delay', 'target' => null]);

    $this->get('/decisions')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('Decisions')
        ->where('decisions.0.action', 'accept_delay')
        ->where('decisions.0.match_label', null)
        ->where('decisions.0.predicted_at_risk', 0)
        ->where('decisions.0.actually_late', 1)
        ->where('decisions.0.cancelled', 3)
        ->where('decisions.1.action', 'hold_departure')
        ->where('decisions.1.match_label', 'flown, +49 min vs predicted +0'));
});

it('shows a decision with its frozen chain beside the actuals', function () {
    decision();

    $this->get('/decisions/'.pestDecisionId())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('Decision')
        ->where('decision.flight_number', '2341')
        ->where('decision.reason', 'protect the BWI bank')
        ->where('decision.current_flight_id', n102dn())
        ->where('legs', fn ($legs) => collect($legs)->map(fn ($l) => [$l['kind'], $l['flight_number']])->all() === [
            ['selected', '2341'], ['cancelled', '1487'], ['cancelled', '1487'], ['cancelled', '574'], ['flown', '2590'],
        ])
        ->where('legs.4.is_target', true)
        ->where('legs.4.predicted_dep_delay', 0)
        ->where('legs.4.actual_dep_delay', 49)
        ->where('legs.4.origin_tz', 'America/New_York'));
});

it('shows a what-if decision with its longer chain', function () {
    decision(['delay' => 600, 'target' => null, 'action' => 'other']);

    $this->get('/decisions/'.pestDecisionId())->assertInertia(fn (Assert $page) => $page
        ->where('decision.what_if', true)
        ->where('decision.arr_delay_min', 600)
        ->where('legs.5.flight_number', '2950')
        ->where('legs.5.predicted_dep_delay', 0)
        ->where('legs.5.actual_dep_delay', 308));
});

it('returns not found for an unknown decision', function () {
    $this->get('/decisions/999999999')->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});
