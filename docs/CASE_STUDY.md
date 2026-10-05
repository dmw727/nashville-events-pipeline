# Building a Trustworthy Local Events Data Pipeline

## Why I Built It

I built this project because I genuinely wanted a better way to find new things for my 10-year-old stepson to experience around Nashville. The same familiar activities appeared repeatedly in ordinary searches, while science programs, nature events, workshops, performances, volunteer opportunities, sports, and unusual local experiences were scattered across dozens of calendars and venue websites.

I did not begin with a portfolio checklist or a predetermined technical solution. I began with a practical question: **How can I consistently discover a wider variety of worthwhile activities without manually checking the same collection of websites every week?**

That question developed into an analytical process. First, I defined what a useful recommendation would need to establish: date, location, approximate travel, age suitability, cost, registration requirements, and activity type. I then investigated where those fields existed, how dependable they were, and which sources could be collected responsibly. The inconsistencies in those sources shaped the pipeline, its validation rules, and ultimately the report.

## Project Summary

Finding local activities initially looked like a search problem. It became a data-integration and data-quality problem: event information was distributed across APIs, calendar feeds, static pages, dynamic booking systems, sports schedules, and community aggregators. Dates, age rules, prices, locations, and cancellation signals were inconsistent or missing.

I researched the source landscape, defined the trust rules, and built a local Python pipeline that collects responsibly accessible sources, standardizes their records, rejects clearly unsuitable entries, preserves uncertainty, and generates a self-contained weekly HTML report.

The system focuses on public activities suitable for roughly age 10 within about an hour of Nashville. It deliberately avoids creating a child profile or tracking preferences, attendance, ratings, or engagement. The purpose is to expand opportunity, not measure the child.

## The Decision Problem

“Find something interesting to do” is meaningful to a parent, but it is not yet an analytical specification. I had to translate that goal into information that could support an actual decision.

The useful output was not simply a long event list. For each activity, I needed to answer:

| Human question | Analytical requirement |
|---|---|
| Is this something my child could realistically attend? | Date, time, cancellation status, public availability, age evidence, and registration requirements |
| Is it practical for us to reach? | Venue, city, usable location evidence, and a clearly labeled travel estimate |
| Does it broaden the experiences I am trying to find? | Consistent categories across science, nature, art, sports, music, history, technology, volunteering, and other activity types |
| What will it cost or require? | Explicit cost and registration fields without inferring missing values |
| Can I trust the listing? | Source identity, official-versus-aggregator status, retrieval health, and a direct link for confirmation |
| What remains uncertain? | Visible flags for missing age, price, location, schedule, or coverage evidence |

This translation changed the project from collecting pages into designing a decision-ready dataset. It also made uncertainty part of the output rather than something to hide during cleaning.

Missing source information is labeled rather than guessed. A family-oriented description is not treated as proof of age suitability. A mention of free parking is not treated as a free event. A successful web request is not treated as proof that a calendar is complete. A city-center estimate is not presented as an exact route.

Those rules sometimes reduce the number of confident recommendations, but they make the remaining information more honest and useful. That tradeoff became one of the project’s central analytical decisions.

## Source Discovery

I investigated 53 Nashville and Middle Tennessee sources before deciding what to automate. The registry documents each source's subject coverage, access method, evidence, limitations, and collection status.

Twelve sources received configured collectors. They span several input patterns:

- Public WordPress Tribe event APIs
- ICS calendar feeds, including recurrence exceptions and overrides
- Bedework calendar exports with recursive date-window handling
- NHL and MLB schedule endpoints
- Squarespace JSON responses
- Bounded HTML and JSON-LD extraction
- Manually verified records for sources without a dependable automated path

Blocked, login-dependent, incomplete, and booking-only sources remain visible as directory leads instead of being counted as automated coverage.

## Pipeline Design

The processing path is:

`source registry -> respectful retrieval and cache -> source adapters -> normalization -> audience and geography checks -> conservative deduplication -> JSON/CSV and HTML report`

Key engineering choices include:

- Robots checks, crawl delays, response-size limits, timeouts, and bounded retries
- Conditional requests and local caching for repeatable offline runs
- Independent source execution so one failure does not erase successful results
- Timezone-aware normalization with daylight-saving handling
- Explicit rejection reasons for age mismatch, cancellations, closures, remote-only events, and out-of-window dates
- Conservative duplicate matching that preserves distinct sessions
- Preference for official-source facts when official and aggregator records overlap
- Formula-injection protection in CSV output and escaping of incoming HTML text
- Run locks, source-health records, manifests, request provenance, and dated snapshots

## Verified Run Results

The saved September 19, 2026 offline run covered a 42-day reporting window.

| Measure | Result |
|---|---:|
| Sources researched | 53 |
| Configured collectors | 12 |
| Raw records collected | 1,058 |
| Included before deduplication | 871 |
| Final event records | 870 |
| Rejected records | 187 |
| Events from official sources | 333 |
| Events with affirmative age evidence | 269 |
| Events with a stated cost | 382 |
| Events explicitly identified as free | 6 |
| Events with a stated registration requirement | 53 |
| Events with unknown distance | 40 |

The largest categories were art, music, STEM/science, festivals and cultures, and seasonal events. Nashville Parent contributed most records, while official venues and sports schedules supplied additional authoritative coverage.

Only one record was merged during deduplication. That low number is intentional: the rules favor leaving a possible duplicate visible over accidentally combining separate performances or sessions.

## What the Data Revealed

The pipeline produced a useful report, but it also exposed important limits in the source ecosystem.

**Age suitability is the largest decision-quality gap.** Only 269 of 870 final records contained affirmative age evidence. Unknown records remain visible with a confirmation flag rather than being promoted as suitable.

**Cost and registration data are inconsistent.** Cost was stated for 382 records, but only six were explicitly free. Registration information was stated for 53 records. The pipeline avoids inventing values, so the user still needs to check the original listing before booking.

**Coverage is uneven by category and source.** Broad aggregators provide volume, while some cooking, volunteering, state-park, performance, and physical-adventure sources require manual checks or dedicated adapters.

**Location precision varies.** Distance is estimated from public coordinates or configured city centers. It is labeled as a heuristic, not represented as live road routing or traffic time.

## Validation

The current test suite contains 11 passing tests covering:

- API pagination
- ICS recurrence exclusions, overrides, and exclusive end dates
- Bedework window splitting at feed limits
- Explicit failure when offline cache entries are missing
- Age-range acceptance and rejection
- Cancellation, closure, past-date, and online-only filtering
- Timezone and daylight-saving conversion
- Geographic filtering and unknown locations
- Conservative deduplication and official-source provenance
- False-free prevention
- Tracking-parameter removal and unsafe URL rejection

## Limitations

- This is a bounded source registry, not an exhaustive events database.
- The stored run is an offline replay and should not be presented as current event availability.
- Some collectors intentionally cover only the first listing page.
- Age and category extraction are heuristic.
- Drive time is an approximation, not route data.
- The test suite focuses on high-risk transformation rules; it does not yet provide full end-to-end coverage for every source adapter.
- The repository does not yet include a sanitized sample report, so readers must run a fresh collection to inspect the finished interface.

## Why This Project Matters

This project matters to me because it began with a real desire to give my stepson broader experiences, not with the desire to manufacture a portfolio entry. The technical work grew out of following that purpose through the analytical process: clarifying the decision, discovering the available evidence, confronting weak and inconsistent data, defining defensible rules, testing those rules, and delivering something we could actually use.

Professionally, it demonstrates the less glamorous but central work of data analysis: discovering sources, defining trustworthy fields, refusing unsupported assumptions, documenting coverage, preserving provenance, testing transformation rules, and producing an output that helps someone make a practical decision.

The strongest lesson was that data quality is not a cleanup step after collection. It begins with deciding what each source can actually support and keeping uncertainty visible all the way to the report.
