# The ngrok second door is blocked by a version deadlock (2026-08-25)

Status: **unresolved, and not resolvable from inside this repository.**
The code is finished, tested and correct. The blocker is entirely external.

Recorded here because the two halves of it produce completely different error
messages, days apart, and each looks individually solvable. Together they are
not.

## The deadlock

```
   ngrok 3.3.1                         ngrok 3.20.0+
   (the winget build)                  (ngrok update / official zip)
        |                                     |
        | valid Authenticode signature        | Windows Defender:
        | CN="ngrok, Inc."                    |   Trojan:Win32/Kepavll!rfn
        | DigiCert, Status=Valid              |   severity 5
        | runs fine                           |   QUARANTINED
        |                                     |
        v                                     v
   ngrok's servers REFUSE it:            the zip downloads (11.69 MB)
   ERR_NGROK_121                         but will NOT extract.
   "agent version 3.3.1 is too old,      An in-place `ngrok update` leaves
    the minimum supported agent          the PATH shim pointing at a file
    version for your account is          Windows refuses to open, so even
    3.20.0"                              `ngrok version` fails.
        |                                     |
        +------------------+------------------+
                           v
              NO VERSION SATISFIES BOTH
```

## Verified facts, and what stayed unverified

| Claim | Status | How |
|---|---|---|
| 3.3.1 is genuine ngrok | **verified** | `Get-AuthenticodeSignature` → `Valid`, `CN="ngrok, Inc."`, issuer DigiCert G4 Code Signing |
| 3.3.1 runs on this machine | **verified** | `ngrok version` → `3.3.1` |
| ngrok refuses 3.3.1 | **verified** | live run → `ERR_NGROK_121`, quoted above |
| Paid plans are exempt from the minimum | **reported by ngrok** | stated in the ERR_NGROK_121 text itself |
| Defender flags 3.39.x | **verified** | `Get-MpThreat` → `Trojan:Win32/Kepavll!rfn`, severity 5; extraction of the official zip fails |
| Defender definitions are current | **verified** | `1.457.327.0`, updated 2026-08-24 — not a stale-signature artefact |
| **The detection is a false positive** | **UNVERIFIED** | Defender blocks reading the binary, so its signature cannot be checked. Plausible — Defender routinely classifies tunnelling tools as riskware, and `!rfn` is an ML/reputation hit rather than a signature match — but plausible is not verified, and this project does not let plausible count. |

The official download host is `bin.equinox.io`, which is ngrok's own CDN — the
same host the winget manifest fetches 3.3.1 from. So the download channel is
not in question; only the binary's contents are, and those could not be read.

## What this does NOT block

The harness-side work is complete and independently correct:

- `HARNESS_PUBLIC_HOST` is accepted, normalized, and additive to the host
  allowlist (`tests/test_second_door.py`, 7 tests).
- `harness url` and `harness doctor` surface the second door.
- `start-ngrok.bat` is a standalone path that never calls Tailscale.
- `check-ngrok.ps1` separates the four ngrok-specific failure modes.

None of that depends on which ngrok version is installed. If the operator
resolves the blocker, the door works with no code change.

## The options, stated without a recommendation

| Option | Cost | What it changes |
|---|---|---|
| Defender exclusion for the ngrok binary | £0 | Lowers the machine's AV coverage for one path, on a detection that could not be verified either way. A security posture decision, and the operator's alone. |
| Paid ngrok plan | ~£8+/mo | Paid accounts are exempt from the agent minimum, so the Defender-clean, validly signed 3.3.1 would connect. Breaks the project's £0 principle. |
| Cloudflare Tunnel instead | ~£10/yr for a domain | `cloudflared` is not flagged. A *named* tunnel needs a domain you own; the free `trycloudflare.com` URLs rotate, which is useless here — a ChatGPT connector is bound to one URL and caches its tool menu per URL. |
| Stay on Tailscale only | £0 | Everything keeps working exactly as it does today, except on networks that filter Tailscale by TLS SNI — which is the case the second door was built for. |

## The lesson worth keeping

Green tests said the second door worked. Seven of them, all passing, all
honest about what they tested — and not one could have caught this, because
every one of them is a fake request inside pytest and the blocker lives in two
places no test reaches: ngrok's account policy and the machine's antivirus.

That is the fourth time on this project that a green suite missed what one real
attempt caught (fork bug, F1/F2, F3, this). The pattern is stable enough to
plan around: **a suite proves the code does what it was written to do; only a
flight proves the thing works.**
