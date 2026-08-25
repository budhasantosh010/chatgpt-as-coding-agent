# The ngrok second door: two blockers, both resolved (2026-08-25)

Status: **RESOLVED and flown.** A real MCP `initialize` crossed the public
ngrok path and returned `HTTP 200 application/json` with a valid
`protocolVersion` handshake.

Kept because the two blockers produced error messages that pointed at the wrong
causes, and because the second one is a security decision that deserves a
written record of *how* it was settled rather than just *that* it was.

## What looked like one problem was two

```
   BLOCKER 1 -- ngrok's account policy
   ───────────────────────────────────
   winget carries only ngrok 3.3.1.
   ngrok refuses free-tier agents below 3.20.0:

       ERROR: authentication failed: Your ngrok-agent version "3.3.1"
              is too old. The minimum supported agent version for your
              account is "3.20.0".   ERR_NGROK_121

   ^ It says AUTHENTICATION FAILED. The authtoken was correct and always
     had been. Nothing about the message points at the version unless you
     read past the first three words.

   BLOCKER 2 -- Windows Defender
   ─────────────────────────────
   Every build at or above the floor is flagged:

       Trojan:Win32/Kepavll!rfn   severity 5

   The official zip downloads (11.69 MB) but will not extract. An in-place
   `ngrok update` leaves the PATH shim pointing at a file Windows refuses to
   open, so even `ngrok version` fails with "the file contains a virus".

   Definitions were current (1.457.327.0, 2026-08-24) -- not stale-signature
   noise.
```

Each looks individually solvable. Together they read as a deadlock: the only
Defender-clean version is the one ngrok rejects.

## How blocker 2 was settled — the order matters

The tempting move is to exclude and move on. That would have left an unverified
binary running with AV coverage removed, which is strictly worse than the block.

What was done instead:

```
  1. operator adds a folder exclusion, scoped to ONE directory
       C:\Users\<user>\tools\ngrok
  2. download from bin.equinox.io  (ngrok's own CDN -- the same host the
     winget manifest fetches from, so the channel was never in question)
  3. THEN check the signature, now that the file is readable
  4. only then run it
```

Step 3 is the whole point. Before the exclusion, Defender blocked *reading* the
file, which is precisely why the detection could not be judged. The exclusion
did not prove the binary safe — it made the evidence obtainable.

**What the evidence said:**

| Field | Value |
|---|---|
| Status | `Valid` |
| Signed by | `CN="ngrok, Inc."`, **Private Organization**, Delaware, serial 4599079 |
| Issuer | DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1 |
| Validity | 2026-01-22 → 2029-01-25 (current) |
| Timestamp | countersigned, DigiCert SHA256 RSA4096 Timestamp Responder 2025 |
| SHA256 | `D339BCBD0713233337E860163F5249EEA679CF26750A5700510DBC241D201748` |

The `Private Organization` OID marks an **Extended Validation** code-signing
certificate — DigiCert verified ngrok, Inc. as a legal entity before issuing it.
On that basis the detection is a **false positive**, and that is now a finding
rather than the guess it was an hour earlier.

## The flight

```
 ngrok 3.39.11  ->  https://<reserved>.ngrok-free.dev  ->  127.0.0.1:8848

 check-ngrok.ps1:
   engine :8848 listening : True
   HTTP 200  application/json
   {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18", ...
```

Two open questions closed by that single run:

- **The free-tier browser interstitial did not fire.** It targets browser-like
  clients; a JSON POST goes straight through. The risk was real enough to flag
  in advance, and `check-ngrok.ps1` still detects it, but it did not occur here.
- **3.39.11 dropped `--domain` in favour of `--url`.** `ngrok.ps1` asks the
  binary which flag it supports instead of assuming, so it picked the right one
  with no edit. Had that been hardcoded, the failure would have been an
  argument error that reads like a network fault.

## Two things worth carrying forward

**An error message names the layer that noticed, not the layer that broke.**
"authentication failed" was emitted by ngrok's auth handshake, which is
genuinely where the rejection happened — the *cause* was a version floor checked
during that handshake. Reading only the first clause would have sent anyone
hunting a perfectly good authtoken.

**Green tests said this worked; a real attempt said it did not.** Seven tests,
all passing, all honest about what they covered — and none could reach either
blocker, because both live outside the process: one in ngrok's account policy,
one in the machine's antivirus. That is the fourth time on this project a green
suite missed what one flight caught (fork bug, F1/F2, F3, this). The pattern is
stable enough to plan around: **a suite proves the code does what it was written
to do; only a flight proves the thing works.**
