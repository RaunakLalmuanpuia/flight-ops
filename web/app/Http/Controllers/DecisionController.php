<?php

namespace App\Http\Controllers;

use App\Support\Days;
use Illuminate\Database\QueryException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;
use Inertia\Inertia;

class DecisionController
{
    // Same set as the check constraint on app.decision.action (migration 022)
    public const ACTIONS = ['accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other'];

    public function index()
    {
        // shortcut: every decision on one page; paginate once the log holds a few hundred
        return Inertia::render('Decisions', [
            'decisions' => DB::select('select * from decision_review order by recorded_at desc, decision_id desc'),
        ]);
    }

    public function show(int $decision)
    {
        $d = DB::selectOne('select * from decision_review where decision_id = ?', [$decision]);
        if (! $d) {
            return Days::missing("No decision {$decision}.");
        }

        // The timezone comes from the flight as rebuilt; a leg no longer found has none and shows UTC
        $legs = DB::select(
            "select l.*, t.origin_tz from decision_legs l left join tail_legs t on t.flight_id = l.current_flight_id
             where l.decision_id = ? order by l.depth, l.kind = 'flown', l.sched_dep_utc",
            [$decision]);

        return Inertia::render('Decision', ['decision' => $d, 'legs' => $legs]);
    }

    public function store(Request $request, int $flight)
    {
        $given = $request->validate([
            'action' => ['required', Rule::in(self::ACTIONS)],
            'target' => ['nullable', 'integer', 'prohibited_if:action,accept_delay'],
            'delay' => ['nullable', 'integer', 'between:0,1440'],
            'reason' => ['required', 'string', 'max:2000'],
            'author' => ['required', 'string', 'max:100'],
        ]);

        try {
            // A savepoint when a transaction is already open, so a refusal leaves it usable
            $id = DB::transaction(fn () => DB::selectOne('select record_decision(?, ?, ?, ?, ?, ?) as id', [
                $flight, $given['delay'] ?? null, $given['action'], $given['target'] ?? null, $given['reason'], $given['author'],
            ])->id);
        } catch (QueryException $e) {
            // record_decision refuses with a plain RAISE (P0001); anything else is a real error
            if ($e->getCode() !== 'P0001') {
                throw $e;
            }
            preg_match('/ERROR:\s+([^\n]+)/', $e->getMessage(), $m);
            throw ValidationException::withMessages(['decision' => $m[1] ?? 'The decision was refused.']);
        }

        return redirect("/decisions/{$id}");
    }
}
