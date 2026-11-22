<?php

namespace App\Http\Controllers;

use App\Support\Days;
use Illuminate\Support\Facades\DB;
use Inertia\Inertia;

class TailDayController
{
    public function __invoke(string $tail, string $date)
    {
        // Allegiant reports tails without the N (320NV), as FAA's N-NUMBER does; the ontology stores N320NV
        $tail = strtoupper($tail);
        $tail = str_starts_with($tail, 'N') ? $tail : "N{$tail}";

        if ($missing = Days::notFound($date)) {
            return $missing;
        }
        if (! DB::selectOne('select 1 from tail_aircraft where tail_number = ? limit 1', [$tail])) {
            return Days::missing("No aircraft {$tail} touched ATL in the loaded data.");
        }

        return Inertia::render('TailDay', [
            'tail' => $tail,
            'day' => $date,
            'range' => Days::range(),
            'aircraft' => DB::select(
                'select manufacturer, model, method, confidence, unresolved_reason, flights from tail_aircraft
                 where tail_number = ? and first_day <= ? and last_day >= ? order by flights desc', [$tail, $date, $date]),
            'legs' => DB::select(
                'with day as (
                     select min(leg_order) as lo, max(leg_order) as hi from tail_legs where tail_number = ? and leg_day = ?
                 )
                 select t.* from tail_legs t, day
                 where t.tail_number = ? and t.leg_order between day.lo - 1 and day.hi + 1
                 order by t.leg_order', [$tail, $date, $tail]),
        ]);
    }
}
