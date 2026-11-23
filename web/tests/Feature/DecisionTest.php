<?php

use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Illuminate\Testing\TestResponse;

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

it('records a decision with its frozen chain and returns to the flight', function () {
    decision()->assertRedirect('/flights/'.n102dn());

    $d = DB::selectOne("select * from decision_review where author = 'pest'");
    expect($d->action)->toBe('cancel_leg')
        ->and($d->target_flight_number)->toBe('2590')
        ->and($d->arr_delay_min)->toBe(316)
        ->and($d->what_if)->toBeFalse()
        ->and($d->match_label)->toBe('airline flew it, +49 min');
    expect(DB::selectOne('select count(*) as n from decision_legs where decision_id = ?', [$d->decision_id])->n)->toBe(5);
});

it('freezes a what-if delay and returns to the what-if', function () {
    decision(['delay' => 600])->assertRedirect('/flights/'.n102dn().'?delay=600');

    $d = DB::selectOne("select arr_delay_min, what_if, target_predicted_dep_delay from decision_review where author = 'pest'");
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
