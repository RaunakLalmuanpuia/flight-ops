<?php

namespace App\Http\Controllers;

use Illuminate\Database\QueryException;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;

class DecisionController
{
    // Same set as the check constraint on app.decision.action (migration 022)
    public const ACTIONS = ['accept_delay', 'hold_departure', 'swap_aircraft', 'cancel_leg', 'other'];

    public function store(Request $request, int $flight)
    {
        $given = $request->validate([
            'action' => ['required', Rule::in(self::ACTIONS)],
            'target' => ['nullable', 'integer', 'prohibited_if:action,accept_delay'],
            'delay' => ['nullable', 'integer', 'between:0,1440'],
            'reason' => ['required', 'string', 'max:2000'],
            'author' => ['required', 'string', 'max:100'],
        ]);
        $delay = $given['delay'] ?? null;

        try {
            // A savepoint when a transaction is already open, so a refusal leaves it usable
            DB::transaction(fn () => DB::selectOne('select record_decision(?, ?, ?, ?, ?, ?) as id', [
                $flight, $delay, $given['action'], $given['target'] ?? null, $given['reason'], $given['author'],
            ]));
        } catch (QueryException $e) {
            // record_decision refuses with a plain RAISE (P0001); anything else is a real error
            if ($e->getCode() !== 'P0001') {
                throw $e;
            }
            preg_match('/ERROR:\s+([^\n]+)/', $e->getMessage(), $m);
            throw ValidationException::withMessages(['decision' => $m[1] ?? 'The decision was refused.']);
        }

        return redirect("/flights/{$flight}".($delay !== null ? "?delay={$delay}" : ''));
    }
}
