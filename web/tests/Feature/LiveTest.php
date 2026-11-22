<?php

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use Inertia\Testing\AssertableInertia as Assert;

// Read-only against whatever the last `live` run left. Empty and stale states are covered in resources/js/lib/live.test.js.

it('renders the live page with status, aircraft, weather and taf', function () {
    $this->get('/live')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('Live')
        ->has('status.checked_at')
        ->has('aircraft')
        ->has('weather')
        ->has('taf'));
});

it('lists aircraft nearest first', function () {
    $this->get('/live')->assertInertia(fn (Assert $page) => $page
        ->where('aircraft', function (Collection $rows) {
            $d = $rows->pluck('distance_nm')->filter(fn ($v) => $v !== null)->map(fn ($v) => (float) $v)->values();
            return $d->all() === $d->sort()->values()->all();
        }));
});

it('gives every aircraft a tail or a reason', function () {
    $this->get('/live')->assertInertia(fn (Assert $page) => $page
        ->where('aircraft', fn (Collection $rows) => $rows->every(fn ($r) => $r['tail_number'] !== null || $r['unresolved_reason'] !== null)));
});

it('links only to tail days the tail page can show', function () {
    $row = DB::selectOne('select tail_number, july_day from live_aircraft where july_day is not null limit 1');
    if (! $row) {
        $this->markTestSkipped('no live aircraft with a July link; run `python -m flightops live` first');
    }
    $this->get("/tail/{$row->tail_number}/{$row->july_day}")->assertOk();
});

it('shows at most three metars, newest first', function () {
    $this->get('/live')->assertInertia(fn (Assert $page) => $page
        ->where('weather', fn (Collection $rows) => $rows->count() <= 3
            && $rows->pluck('observed_at')->all() === $rows->pluck('observed_at')->sortDesc()->values()->all()));
});
