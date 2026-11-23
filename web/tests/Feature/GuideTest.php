<?php

use Inertia\Testing\AssertableInertia as Assert;

it('sends home to the guide', function () {
    $this->get('/')->assertRedirect('/guide');
});

it('renders the guide', function () {
    $this->get('/guide')->assertOk()->assertInertia(fn (Assert $page) => $page->component('Guide'));
});
