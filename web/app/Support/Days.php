<?php

namespace App\Support;

use Illuminate\Support\Facades\DB;
use Inertia\Inertia;
use Symfony\Component\HttpFoundation\Response;

class Days
{
    /** @return array{first_day: string, last_day: string} */
    public static function range(): array
    {
        // day_range scans every flight, so read it once per request
        return once(fn () => (array) DB::selectOne('select first_day, last_day from day_range'));
    }

    /** A 404 page naming the loaded range, or null when the day can be shown. */
    public static function notFound(string $day): ?Response
    {
        [$y, $m, $d] = array_map('intval', explode('-', $day));
        $range = self::range();

        if (checkdate($m, $d, $y) && $day >= $range['first_day'] && $day <= $range['last_day']) {
            return null;
        }

        return self::missing("No data for {$day}.");
    }

    public static function missing(string $message): Response
    {
        return Inertia::render('NotFound', ['message' => $message, 'range' => self::range()])
            ->toResponse(request())
            ->setStatusCode(404);
    }
}
