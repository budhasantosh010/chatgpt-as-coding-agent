# Four-Controls Benchmark Results

Status: benchmark pack verified; controlled ChatGPT comparison runs not yet
performed. `n=1` per arm will be rough tuning, not science. No EFFORT profile has
been retuned from missing data.

| Case / arm | Correct | Tests | Credits by tier | Wall clock | Continue nudges | Defects introduced |
|---|---:|---:|---|---:|---:|---:|
| B01 baseline / variant | Not run | Not run | Not measured | Not measured | Not measured | Not inspected |
| B02 baseline / variant | Not run | Not run | Not measured | Not measured | Not measured | Not inspected |
| B03 baseline / variant | Not run | Not run | Not measured | Not measured | Not measured | Not inspected |
| B04 baseline / variant | Not run | Not run | Not measured | Not measured | Not measured | Not inspected |
| B05 baseline / variant | Not run | Not run | Not measured | Not measured | Not measured | Not inspected |

## Seed integrity

The objective verifier must report all five cases failing on an untouched seed.
That proves each case starts unsolved; it does not measure either contract arm.

## First flight

The separate Medium contracted flight is recorded in
`docs/specs/four-controls-first-flight.md`. Backend/API, ledger, receipt, gate,
audit, and process checks passed. Visual browser completion and the operator's
personal belief gate remain pending, so final acceptance is not claimed.
