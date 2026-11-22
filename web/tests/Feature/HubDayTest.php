<?php

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use Inertia\Testing\AssertableInertia as Assert;

it('sends home to the first outage day', function () {
    $this->get('/')->assertRedirect('/day/2024-07-19');
});

it('shows every ATL flight of the ATL local day', function () {
    $metars = DB::selectOne("select count(*) as n from hub_day_weather where atl_day = '2024-07-19'")->n;

    $this->get('/day/2024-07-19')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('HubDay')
        ->where('day', '2024-07-19')
        ->where('range', ['first_day' => '2024-07-01', 'last_day' => '2024-07-31'])
        ->has('flights', 2078)
        ->has('hourly')
        ->has('weather', $metars)
        ->where('caveats.no_tail', 25));
});

it('counts 899 cancellations on July 19 by ATL day, as measured in app_read', function () {
    $this->get('/day/2024-07-19')->assertInertia(fn (Assert $page) => $page
        ->where('hourly', fn (Collection $rows) => $rows->sum('cancelled') === 899));
});

it('names the loaded range for a day outside it', function (string $day) {
    $this->get("/day/{$day}")->assertNotFound()->assertInertia(fn (Assert $page) => $page
        ->component('NotFound')
        ->where('range.first_day', '2024-07-01'));
})->with(['2024-08-01', '2024-06-30', '2024-07-32', '2024-02-30']);

it('rejects a malformed date with the range page', function () {
    $this->get('/day/july-19')->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});

it('gives every tailed flight a tail_day', function () {
    $this->get('/day/2024-07-10')->assertInertia(fn (Assert $page) => $page
        ->where('flights', fn (Collection $flights) => $flights->whereNotNull('tail_number')->every(fn ($f) => ! empty($f['tail_day']))));
});
