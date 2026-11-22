<?php

namespace App\Http\Controllers;

use Illuminate\Support\Facades\DB;
use Inertia\Inertia;

class LiveController
{
    public function __invoke()
    {
        return Inertia::render('Live', [
            'status' => DB::selectOne('select states_loaded_at, snapshot_at, checked_at from live_status'),
            'aircraft' => DB::select('select * from live_aircraft order by distance_nm nulls last, hex'),
            'weather' => DB::select('select * from live_weather order by observed_at desc limit 3'),
            'taf' => DB::selectOne('select fetched_at, raw_text from live_taf'),
        ]);
    }
}
