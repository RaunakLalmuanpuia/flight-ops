// shortcut: flight 371994 is N102DN's DEN->ATL by id, as in scripts/screenshots.sh; look it up if a rebuild renumbers flights
export const STEPS = [
    {
        href: '/day/2024-07-19',
        title: 'A bad day at the hub',
        look: 'This is every Atlanta flight on 19 July 2024, the day a software outage grounded Delta. Each bar is one hour: red is cancelled, amber is 15+ minutes late. The strip below is the weather.',
        click: 'Click a tall red hour to filter the table to it, then press Next.',
    },
    {
        href: '/tail/N102DN/2024-07-19',
        title: "One aircraft's day",
        look: 'An airline plans each plane to fly several flights in a row. These bars are aircraft N102DN: grey is the plan, dark is what happened. A late landing leaves less time for the next flight.',
        click: 'Find the flight from Denver (DEN) to Atlanta, then press Next.',
    },
    {
        href: '/flights/371994',
        title: 'How a delay spreads',
        look: 'This flight landed very late. Each row is a later flight of the same plane. "Spare time" is how much delay the schedule can soak up. When it runs out, the next flight is predicted late and marked at risk.',
        click: 'Type 60 into the delay box and press Try it to see a smaller delay. Then come back and press Next.',
    },
    {
        href: '/flights/371994',
        title: 'Should a flight be cancelled?',
        look: 'The "Chance of cancellation" column shows how often flights like each one were cancelled in July. A red badge means the risk is high enough to consider cancelling now, so the rest of the day can recover.',
        click: 'Scroll to "Log a decision" at the bottom. Pick an action, write why, and log it. Then press Next.',
    },
    {
        href: '/decisions',
        title: 'The decision log',
        look: 'Every decision is kept here with who made it, why, and how it compared with what really happened. That record is how a team learns from a bad day.',
        click: 'Open the "Cancel a leg" decision to see the full record. You have finished the tour.',
    },
];

export function stepFromQuery(search) {
    const n = Number(new URLSearchParams(search).get('tour') || NaN);
    return Number.isInteger(n) && n >= 1 && n <= STEPS.length ? n : null;
}

export const stepHref = (n) => (n >= 1 && n <= STEPS.length ? `${STEPS[n - 1].href}?tour=${n}` : null);
