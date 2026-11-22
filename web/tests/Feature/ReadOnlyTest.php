<?php

use Illuminate\Database\QueryException;
use Illuminate\Support\Facades\DB;

it('reads app_read views', function () {
    expect(DB::selectOne('select first_day, last_day from day_range')->first_day)->toBe('2024-07-01');
});

it('cannot write to ontology', function () {
    expect(fn () => DB::statement("insert into ontology.carrier (code) values ('XX')"))->toThrow(QueryException::class);
});

it('cannot create tables in app_read', function () {
    expect(fn () => DB::statement('create table app_read.scratch (i int)'))->toThrow(QueryException::class);
});
