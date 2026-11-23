<?php

// Pages render app.blade.php, whose @vite needs public/build; tests don't need real assets.
pest()->extend(Tests\TestCase::class)->beforeEach(fn () => $this->withoutVite())->in('Feature');

function n102dn(): int
{
    // DEN->ATL on July 19, 316 min late; looked up, since flight_id is a surrogate
    return Illuminate\Support\Facades\DB::selectOne("select flight_id from tail_legs where tail_number = 'N102DN' and leg_day = '2024-07-19' and origin = 'DEN'")->flight_id;
}
