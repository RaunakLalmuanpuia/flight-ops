<?php

namespace App\Http\Controllers;

use App\Support\Days;
use Illuminate\Support\Facades\DB;
use Inertia\Inertia;

class HubDayController
{
    public function __invoke(string $date)
    {
        if ($missing = Days::notFound($date)) {
            return $missing;
        }

        return Inertia::render('HubDay', [
            'day' => $date,
            'range' => Days::range(),
            'hourly' => DB::select(
                'select atl_hour, direction, scheduled, on_time, delayed, diverted, cancelled
                 from hub_day_hourly where atl_day = ? order by atl_hour, direction', [$date]),
            'weather' => DB::select(
                'select atl_hour, observed_at, adverse, raw_text from hub_day_weather where atl_day = ? order by observed_at', [$date]),
            'caveats' => DB::selectOne(
                'select metar_stale, rotation_break, aircraft_unresolved, aircraft_medium_confidence, block_mismatch, no_tail
                 from hub_day_caveats where atl_day = ?', [$date]),
            'flights' => DB::select(
                'select flight_id, atl_hour, direction, status, carrier, flight_number, other_station, landed_station, tail_number,
                        sched_dep_utc, sched_arr_utc, actual_dep_utc, actual_arr_utc, dep_delay_min, arr_delay_min,
                        cancellation_code, delays, metar_staleness_min, metar_adverse, metar_stale, rotation_break,
                        aircraft_unresolved, aircraft_medium_confidence, block_mismatch, no_tail, tail_day
                 from hub_day_flights where atl_day = ? order by atl_hour, direction, carrier, flight_number', [$date]),
        ]);
    }
}
