<?php

// Pages render app.blade.php, whose @vite needs public/build; tests don't need real assets.
pest()->extend(Tests\TestCase::class)->beforeEach(fn () => $this->withoutVite())->in('Feature');
