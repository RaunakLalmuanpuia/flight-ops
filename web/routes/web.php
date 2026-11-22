<?php

use App\Http\Controllers\HubDayController;
use App\Http\Controllers\TailDayController;
use Illuminate\Support\Facades\Route;

Route::redirect('/', '/day/2024-07-19');
Route::get('/day/{date}', HubDayController::class)->where('date', '\d{4}-\d{2}-\d{2}');
Route::get('/tail/{tail}/{date}', TailDayController::class)
    ->where(['tail' => '[A-Za-z0-9]{1,6}', 'date' => '\d{4}-\d{2}-\d{2}']);
