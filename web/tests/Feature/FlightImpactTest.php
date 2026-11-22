<?php

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use Inertia\Testing\AssertableInertia as Assert;

function n102dn(): int
{
    // DEN->ATL on July 19, 316 min late; looked up, since flight_id is a surrogate
    return DB::selectOne("select flight_id from tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and origin = 'DEN'")->flight_id;
}

it('shows the chain of a late arrival with cancelled legs in its gap', function () {
    $this->get('/flights/'.n102dn())->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('FlightImpact')
        ->where('flight.flight_number', '2341')
        ->where('flight.tail_number', 'N102DN')
        ->where('delay', 316)
        ->where('whatIf', false)
        ->where('stop', 'absorbed')
        ->where('legs', fn (Collection $legs) => $legs->map(fn ($l) => [$l['kind'], $l['flight_number']])->all() === [
            ['cancelled', '1487'], ['cancelled', '1487'], ['cancelled', '574'], ['flown', '2590'],
        ])
        ->where('legs.3.predicted_dep_delay', 0)
        ->where('legs.3.actual_dep_delay', 49));
});

it('propagates a what-if delay', function () {
    // 600 min instead of 316 eats ATL->BWI's 221 min of slack and 63 more; BWI->ATL absorbs it
    $this->get('/flights/'.n102dn().'?delay=600')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('delay', 600)
        ->where('whatIf', true)
        ->where('legs.3.predicted_dep_delay', 63)
        ->where('legs.3.at_risk', true)
        ->where('legs.4.flight_number', '2950')
        ->where('stop', 'absorbed'));
});

it('treats the actual delay given explicitly as not a what-if', function () {
    $this->get('/flights/'.n102dn().'?delay=316')->assertInertia(fn (Assert $page) => $page->where('whatIf', false));
});

it('rejects a delay that is not a whole number from 0 to 1440', function (string $delay) {
    $this->get('/flights/'.n102dn()."?delay={$delay}")->assertSessionHasErrors('delay');
})->with(['-1', '1441', 'abc', '1.5']);

it('starts a diverted flight from its actual landing, without a what-if', function () {
    $id = DB::selectOne('select t.flight_id from tail_legs t
        where t.diverted and t.actual_arr_utc is not null and exists (select 1 from tail_legs n where n.tail_number = t.tail_number and n.leg_seq = t.leg_seq + 1)
        order by t.flight_id limit 1')->flight_id;

    $this->get("/flights/{$id}")->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('flight.diverted', true)
        ->where('delay', null)
        ->where('legs', fn (Collection $legs) => $legs->isNotEmpty()));
    $this->get("/flights/{$id}?delay=30")->assertSessionHasErrors(['delay' => 'A diverted flight has no arrival delay to replace.']);
});

it('returns not found for a cancelled flight', function () {
    $id = DB::selectOne('select flight_id from tail_legs where cancelled order by flight_id limit 1')->flight_id;
    $this->get("/flights/{$id}")->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});

it('returns not found for an unknown flight', function () {
    $this->get('/flights/999999999')->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});
