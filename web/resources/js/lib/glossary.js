// One place for every term the console uses. Screens show `plain` first, then `term` small.
export const GROUPS = [
    ['basics', 'The basics'],
    ['aircraft', 'Aircraft and their day'],
    ['delays', 'Delays and cancellations'],
    ['weather', 'Weather'],
    ['data', 'Where the data comes from'],
];

export const GLOSSARY = {
    ops_control: {
        plain: 'Operations control', term: 'OCC', group: 'basics',
        short: 'The airline team that watches every flight in real time and decides what to do when things go wrong.',
        deeper: 'Controllers balance aircraft, crews and passengers. When a storm or outage hits, they choose which flights to delay, swap or cancel so the rest of the day recovers.',
    },
    hub: {
        plain: 'Hub airport', term: null, group: 'basics',
        short: 'An airport where an airline concentrates its flights so passengers can connect. Atlanta (ATL) is Delta\'s largest.',
        deeper: 'Because so many flights pass through a hub, trouble there spreads across the whole network within hours.',
    },
    utc: {
        plain: 'Universal time', term: 'UTC', group: 'basics',
        short: 'One world clock with no time zones. The data is stored in it, and the screens show Atlanta or local time.',
        deeper: 'Atlanta is UTC−4 in summer. Hover a time to see its UTC value.',
    },
    tail: {
        plain: 'Aircraft registration', term: 'tail number', group: 'aircraft',
        short: 'The ID painted on the plane, like N102DN. It follows one physical aircraft all day.',
        deeper: 'US registrations start with N. A registration can move to a different airframe over the years, so the console matches it against the date of the flight.',
    },
    rotation: {
        plain: "Aircraft's day", term: 'rotation', group: 'aircraft',
        short: 'All the flights one aircraft flies, in order. Each flight should start where the last one landed.',
        deeper: 'Rotations are why delays spread: if the plane arrives late, its next flight cannot leave on time.',
    },
    rotation_break: {
        plain: "Gap in the aircraft's route", term: 'rotation break', group: 'aircraft',
        short: "The next flight starts somewhere other than where the last one landed, so some flying is missing from the data.",
        deeper: 'Usually an international or non-reporting flight that the US government data does not cover. It is labelled, not treated as an error.',
    },
    turn: {
        plain: 'Turnaround', term: 'turn', group: 'aircraft',
        short: 'The time on the ground between landing and the next departure: unloading, cleaning, fuelling, boarding.',
        deeper: 'Airlines schedule turns with some buffer. Short turns save money but leave no room to absorb delay.',
    },
    min_turn: {
        plain: 'Minimum turnaround', term: 'min turn', group: 'aircraft',
        short: 'The shortest ground time this airline actually managed in July 2024, used as the fastest realistic turn.',
        deeper: 'Measured per carrier from July data, at the 10th percentile: 9 out of 10 turns took longer.',
    },
    slack: {
        plain: 'Spare time', term: 'slack', group: 'aircraft',
        short: 'Scheduled ground time minus the minimum turnaround. Delay smaller than the slack is absorbed.',
        deeper: 'If slack is 20 min and the plane lands 50 min late, the next flight leaves about 30 min late.',
    },
    diversion: {
        plain: 'Diverted flight', term: 'diversion', group: 'aircraft',
        short: 'The flight landed at a different airport than planned, for example because of weather.',
        deeper: 'The data gives no arrival delay for a diversion, so the console starts from the actual landing time.',
    },
    callsign: {
        plain: 'Radio name', term: 'callsign', group: 'aircraft',
        short: 'The name a flight uses with air traffic control, like DAL123. It identifies a flight, not an aircraft.',
        deeper: 'Regional flights sold as Delta fly under the operator\'s own prefix, such as EDV for Endeavor.',
    },
    icao_hex: {
        plain: 'Transponder code', term: 'ICAO hex', group: 'aircraft',
        short: 'A six-character code the aircraft\'s radio broadcasts. It is linked to the registration.',
        deeper: 'The live page matches this code against the FAA registry to find which aircraft it is.',
    },
    delay_15: {
        plain: 'Delayed', term: '15+ min', group: 'delays',
        short: 'US government statistics count a flight as late when it is 15 minutes or more behind schedule.',
        deeper: 'Delay causes are only reported for these flights. A blank cause means not reported, not zero.',
    },
    propagation: {
        plain: 'Delay chain', term: 'propagation', group: 'delays',
        short: "How one late arrival pushes into the same aircraft's later flights, one after another.",
        deeper: 'The console predicts each next flight from the previous predicted arrival, the minimum turnaround and the schedule. It covers aircraft only: no crew or passenger connections.',
    },
    at_risk: {
        plain: 'At risk', term: null, group: 'delays',
        short: 'A later flight predicted to leave 15 minutes or more late because of this delay.',
        deeper: 'This is a prediction from the delay chain, compared against what actually happened in the "Actual" columns.',
    },
    late_aircraft: {
        plain: 'Late inbound aircraft', term: 'late-aircraft delay', group: 'delays',
        short: 'Delay caused because the plane arrived late from its previous flight.',
        deeper: 'Airlines report it as its own cause. It is the best check on whether the delay chain predicted well.',
    },
    nas: {
        plain: 'Air traffic system', term: 'NAS', group: 'delays',
        short: 'Delay from the national airspace system: air traffic control limits, airport congestion, non-extreme weather.',
        deeper: 'NAS stands for National Airspace System. It is one of five delay causes, with carrier, weather, security and late aircraft.',
    },
    delay_cause: {
        plain: 'Delay cause', term: null, group: 'delays',
        short: 'Minutes of delay assigned to a reason: airline, weather, air traffic system, security or late inbound aircraft.',
        deeper: 'One flight can have several causes. Only reported for flights 15 or more minutes late.',
    },
    cancellation_code: {
        plain: 'Cancellation reason', term: 'code A–D', group: 'delays',
        short: 'A: the airline. B: weather. C: the air traffic system. D: security.',
        deeper: 'Reported by the airline to the US Department of Transportation for every cancelled flight.',
    },
    cancel_risk: {
        plain: 'Chance of cancellation', term: 'cancel risk', group: 'delays',
        short: 'How often similar flights were cancelled in July 2024, given how late the aircraft is and how stressed the airline was.',
        deeper: 'Fitted on July and checked on August. The red badge marks the level that best balanced catching cancellations against false alarms. It mostly fires on outage-scale days.',
    },
    what_if: {
        plain: 'Try a different delay', term: 'what-if', group: 'delays',
        short: 'Enter any arrival delay to see what it would do to the later flights, instead of the delay that really happened.',
        deeper: 'In a what-if, the "Actual" columns are dimmed: they record what followed the real delay, not yours.',
    },
    decision_log: {
        plain: 'Decision log', term: null, group: 'delays',
        short: 'A record of what a controller chose to do (accept, hold, swap, cancel) and why.',
        deeper: 'Decisions are logged with the real outcome already visible, so it is an audit trail, not a test of foresight.',
    },
    metar: {
        plain: 'Weather report', term: 'METAR', group: 'weather',
        short: 'The standard airport weather observation, usually issued every hour: wind, visibility, cloud, rain.',
        deeper: 'Written in a compact code, for example "KATL 191652Z 27008KT 10SM FEW040". The console shows the raw text and its own reading.',
    },
    adverse_metar: {
        plain: 'Bad weather', term: 'adverse METAR', group: 'weather',
        short: 'A report with thunderstorms, heavy rain, fog, snow or ice, low cloud, poor visibility or strong gusts.',
        deeper: 'Exactly: ceiling under 1,000 ft, visibility under 3 miles, gusts of 30 knots or more, or one of those weather types.',
    },
    metar_stale: {
        plain: 'No recent weather report', term: null, group: 'weather',
        short: 'No weather report within 90 minutes of the flight, so its weather is unknown.',
        deeper: 'Flagged rather than guessed from an older report.',
    },
    taf: {
        plain: 'Weather forecast', term: 'TAF', group: 'weather',
        short: 'The airport forecast for the next 24 to 30 hours, in the same compact code as the weather report.',
        deeper: 'Stored separately from observations because it is a forecast, not something that happened.',
    },
    bts: {
        plain: 'US flight statistics', term: 'BTS', group: 'data',
        short: "The US government's record of every domestic flight by large airlines: times, delays, cancellations, aircraft.",
        deeper: 'Bureau of Transportation Statistics. Published monthly, months late, so it covers history, not today.',
    },
    faa_registry: {
        plain: 'US aircraft register', term: 'FAA registry', group: 'data',
        short: 'The official list of US aircraft: registration, transponder code, type and owner.',
        deeper: 'FAA is the Federal Aviation Administration. The console matches registrations against it for the date of each flight.',
    },
    opensky: {
        plain: 'Live aircraft positions', term: 'OpenSky', group: 'data',
        short: 'A network of volunteer receivers that pick up the position broadcasts aircraft send out.',
        deeper: 'Aircraft broadcast position by ADS-B. OpenSky collects it, and the live page polls it every minute.',
    },
    aircraft_unresolved: {
        plain: 'Aircraft not identified', term: null, group: 'data',
        short: 'The registration could not be matched to one physical aircraft on that date.',
        deeper: 'Each match records how it was made and how sure it is. Unmatched aircraft are flagged with a reason, never guessed.',
    },
    aircraft_medium_confidence: {
        plain: 'Aircraft match uncertain', term: 'medium confidence', group: 'data',
        short: 'The aircraft was identified, but the register needed interpreting, for example after a re-registration.',
        deeper: 'Filter to these flights with the data warning chip if you need to rely on which airframe flew.',
    },
    block_mismatch: {
        plain: 'Flight time disagrees', term: 'block time', group: 'data',
        short: 'The scheduled gate-to-gate time does not match the scheduled departure and arrival times.',
        deeper: 'The console trusts the clock times and only uses gate-to-gate time to pick the arrival date.',
    },
    no_tail: {
        plain: 'No aircraft reported', term: null, group: 'data',
        short: 'The airline did not report which aircraft flew this flight, so it cannot join an aircraft\'s day.',
        deeper: 'Mostly cancelled flights. Shown and counted, never dropped.',
    },
};
