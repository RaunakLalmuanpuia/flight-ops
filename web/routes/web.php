<?php

use App\Http\Controllers\DecisionController;
use App\Http\Controllers\FlightImpactController;
use App\Http\Controllers\HubDayController;
use App\Http\Controllers\LiveController;
use App\Http\Controllers\TailDayController;
use App\Support\Days;
use Illuminate\Support\Facades\Route;

Route::redirect('/', '/day/2024-07-19');
Route::get('/day/{date}', HubDayController::class)->where('date', '\d{4}-\d{2}-\d{2}');
Route::get('/tail/{tail}/{date}', TailDayController::class)
    ->where(['tail' => '[A-Za-z0-9]{1,6}', 'date' => '\d{4}-\d{2}-\d{2}']);
Route::get('/flights/{flight}', FlightImpactController::class)->where('flight', '\d+');
Route::post('/flights/{flight}/decisions', [DecisionController::class, 'store'])->where('flight', '\d+');
Route::get('/decisions', [DecisionController::class, 'index']);
Route::get('/decisions/{decision}', [DecisionController::class, 'show'])->where('decision', '\d+');
Route::get('/live', LiveController::class);

Route::fallback(fn () => Days::missing('No page at this address.'));
