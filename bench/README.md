# Fixed Four-Controls Benchmark

Security note: the verifier imports and executes candidate fixture code. Run it
only on trusted code in a disposable local benchmark copy.

`fixture_seed/` is copied fresh for every run. `cases.json` locks five tasks and
the two contracts being compared. Exactly one contract field differs within each
comparison. Run the objective verifier with:

```powershell
python bench/verify.py --workspace <fresh-fixture-copy>
```

Do not repair the seed in place. Record both baseline and variant in `results.md`.
One run per arm (`n=1`) is only rough tuning evidence, never scientific proof.
Do not retune the 2/8/16/32/50 EFFORT profiles without completed measurements.
