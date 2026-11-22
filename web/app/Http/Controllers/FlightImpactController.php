<?php

namespace App\Http\Controllers;

use App\Support\Days;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Inertia\Inertia;

class FlightImpactController
{
    public function __invoke(Request $request, int $flight)
    {
        $leg = DB::selectOne('select cancelled, diverted, arr_delay_min from tail_legs where flight_id = ?', [$flight]);
        if (! $leg) {
            return Days::missing("No flight {$flight} on an aircraft that touched ATL.");
        }
        if ($leg->cancelled) {
            return Days::missing("Flight {$flight} was cancelled, so it has no arrival to propagate.");
        }

        // A diversion has no arrival delay, and propagate's override measures from the scheduled destination
        $given = $request->validate(
            ['delay' => $leg->diverted ? ['prohibited'] : ['nullable', 'integer', 'between:0,1440']],
            ['delay.prohibited' => 'A diverted flight has no arrival delay to replace.'],
        )['delay'] ?? null;
        $whatIf = $given !== null && (int) $given !== $leg->arr_delay_min;

        // The actual delay passes NULL, so the page matches the backtest, which uses the actual arrival time
        $rows = collect(DB::select(
            "select p.*, t.tail_number, t.leg_day, t.origin_tz, t.dest_tz, t.diverted, t.landed, t.landed_tz
             from propagate(?, ?) p join tail_legs t using (flight_id)
             order by p.depth, p.kind = 'flown', p.sched_dep_utc",
            [$flight, $whatIf ? (int) $given : null]));
        if ($rows->isEmpty()) {
            return Days::missing("Flight {$flight} has no arrival to propagate from.");
        }

        return Inertia::render('FlightImpact', [
            'flight' => $rows->first(),
            'legs' => $rows->slice(1)->values(),
            'delay' => $whatIf ? (int) $given : $leg->arr_delay_min,
            'whatIf' => $whatIf,
            'stop' => $rows->pluck('stop_reason')->filter()->last(),
        ]);
    }
}
