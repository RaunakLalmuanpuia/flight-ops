<?php

use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use Inertia\Testing\AssertableInertia as Assert;

it('shows a day of only cancelled legs between its flown neighbours', function () {
    // N103DY flew on July 18 and 20; all three of its July 19 legs were cancelled
    $this->get('/tail/N103DY/2024-07-19')->assertOk()->assertInertia(fn (Assert $page) => $page
        ->component('TailDay')
        ->where('tail', 'N103DY')
        ->where('legs', fn (Collection $legs) => $legs->pluck('flight_number')->all() === ['694', '458', '393', '2297', '783']));
});

it('normalizes the tail to the full N-number', function (string $given) {
    $this->get("/tail/{$given}/2024-07-19")->assertOk()->assertInertia(fn (Assert $page) => $page->where('tail', 'N103DY'));
})->with(['103DY', 'n103dy']);

it('gives the aircraft links that cover the day', function () {
    $this->get('/tail/N103DY/2024-07-19')->assertInertia(fn (Assert $page) => $page
        ->where('aircraft', fn (Collection $rows) => $rows->isNotEmpty() && $rows->every(fn ($r) => array_key_exists('confidence', $r))));
});

it('shows a labelled break when the rotation does not connect', function () {
    $break = DB::selectOne("select tail_number, leg_day from tail_legs where connects = false and leg_day = '2024-07-19' order by tail_number limit 1");

    $this->get("/tail/{$break->tail_number}/{$break->leg_day}")->assertOk()->assertInertia(fn (Assert $page) => $page
        ->where('legs', fn (Collection $legs) => $legs->contains(fn ($l) => $l['connects'] === false && $l['break_label'] !== null)));
});

it('returns not found for a tail that never touched ATL', function () {
    $this->get('/tail/N0000X/2024-07-19')->assertNotFound()->assertInertia(fn (Assert $page) => $page->component('NotFound'));
});

it('returns not found for a day outside the range', function () {
    $this->get('/tail/N103DY/2024-08-01')->assertNotFound();
});
