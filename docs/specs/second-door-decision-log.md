# The Second Door — the complete decision log (2026-08-25)

**Status: built, tested, flown, in use.** ChatGPT created and read back a real
file on the operator's Windows machine through this path on 2026-08-25.

---

## 0. How to read this document

This is not a summary. It records **every decision made while building the
second door**, including the ones that were reversed, the ones that were wrong
first time, and the ones that look trivial. Each decision is written in the same
shape so nothing has to be inferred:

```
   Decided        what was chosen
   Instead of     the alternative that was actually on the table
   Why            the reasoning, in full
   Breaks if not  what would have gone wrong without it
   Lives in       where the decision is expressed in code
```

The reason for the "instead of" line: a conclusion on its own is worthless six
months later. *"We used HARNESS_PUBLIC_HOST"* tells you nothing. *"We used
HARNESS_PUBLIC_HOST instead of HARNESS_ALLOWED_HOSTS because the latter replaces
the default list and would have locked the operator out of their own Workbench"*
tells you why you must not "simplify" it later.

**If you have zero context, read §1 and §2 and stop.** The rest is for whoever
has to change this.

---

## 1. What was asked for, in the operator's words

> *"can we add ngrok alongside with tailscale... doesn't matter if I have to
> connect using ngrok with chatgpt I'm fine with it but we keep tailscale as it
> is working currently and we just add extra ngrok on top of it that's it."*

Two requirements, and both were treated as binding:

```
  1. ADD ngrok.
  2. DO NOT disturb Tailscale. It works. Leave it working.
```

Requirement 2 is why almost every decision below is shaped as *"additive, never
replacing"*. It is also a standing rule in [AGENTS.md](../../AGENTS.md) §3:
never change the Tailscale Funnel configuration.

---

## 2. The five-minute version, for someone with no context

**What problem does this solve?**

The harness lives on a laptop. ChatGPT lives on the internet. Something has to
connect them — a *tunnel*. Until now there was one tunnel: Tailscale.

Some networks — café wifi, hotel wifi, guest networks, some phone hotspots —
**block Tailscale on purpose**. They inspect the name inside the encrypted
handshake and silently drop anything heading for a VPN service. Nothing you can
configure fixes that. On those networks the harness was simply unreachable.

**What is the second door?**

A second tunnel, from a different company (ngrok), that those filters don't
recognise. Same harness underneath.

```
                       ChatGPT
                          |
          +---------------+---------------+
          |                               |
          v                               v
   Tailscale Funnel                     ngrok            <- TWO ROADS
          |                               |
          +---------------+---------------+
                          |
                          v
                   localhost:8848                        <- ONE ENGINE
                          |
        tasks · workspaces · evidence · git · your files  <- ONE SET OF STUFF
```

**The single most important thing to understand:** these are *not two
harnesses*. They are two entrances to one building. The task you started this
morning over Tailscale is the same task this afternoon over ngrok. Nothing
copies, nothing syncs, nothing migrates. There is only ever one of everything.

---

## 3. Part one — verifying the claim before agreeing with it

The operator arrived with an answer from ChatGPT, including a diagram, and asked:
*"confirm if ngrok solves it or not."*

### D1 — Check the claim against the source code, not against plausibility

```
   Decided        Read middleware.py and config.py before answering.
   Instead of     Agreeing, because the diagram was clearly correct in spirit.
   Why            A standing instruction on this project: verify every
                  ChatGPT/Codex/GPT claim against actual code before agreeing.
                  Also, "sounds right" is exactly how a 0.01% error enters and
                  compounds.
   Breaks if not  The operator would have installed ngrok, seen it report
                  "online", and got a 403 from the harness with no idea why.
   Lives in       (a process decision, not code)
```

**What the check found.** ChatGPT's claim was:

> *"So nothing underneath the tunnel changes."*

That is **true of state** — tasks, files, roots, database — and **false of
code**. `harness/middleware.py` inspects the `Host:` header of every request and
rejects anything it doesn't recognise:

```
   Request arrives claiming  Host: <something>.ngrok-free.dev
                    |
                    v
   _host_allowed()  is it localhost / 127.0.0.1 ?   no
                    is it *.ts.net ?                no   <- the funnel's wildcard
                    is it in allowed_hosts ?        no
                    |
                    v
              403 "host not allowed"     <- ngrok DEAD ON ARRIVAL
```

So ngrok needed a code change. Nobody would have guessed that from the outside,
and the resulting error looks exactly like a broken tunnel.

**Why the check exists at all** (worth knowing before anyone "simplifies" it
away): it defends against *DNS rebinding*, where a malicious web page makes your
own browser talk to a service on your own machine. The Host check and the Origin
check are the two halves of that defence.

---

## 4. Part two — the decision that had to come before any building

The operator's real requirement was *"I want connect and I'm done, nothing more
or less."* That made one property decisive.

### D2 — Refuse to build until it was known whether the ngrok URL is static

```
   Decided        Ask the operator to check their ngrok dashboard for a
                  RESERVED domain before writing any code.
   Instead of     Building it and letting them discover the problem in use.
   Why            ngrok's default gives a NEW random hostname on every start.
                  A ChatGPT connector is bound to one URL and caches its tool
                  menu per URL -- it cannot be re-pointed. So a rotating URL
                  means rebuilding the connector in ChatGPT EVERY DAY.
   Breaks if not  A feature that is technically working and practically
                  abandoned by day four -- and now a second half-working door
                  to maintain. Worse than not having it.
   Lives in       Documented as mandatory in scripts/ngrok.ps1 header,
                  .env.example, and README §2.
```

The two shapes, drawn out, because this is the part people get wrong:

```
 EPHEMERAL (ngrok's default)              RESERVED (what we need)
 ---------------------------              -----------------------
 Mon  a3f9-81-2-x.ngrok.app               Mon  yourname.ngrok-free.dev
 Tue  7c2e-81-2-x.ngrok.app   <- new!     Tue  yourname.ngrok-free.dev   <- same
 Wed  b81d-81-2-x.ngrok.app   <- new!     Wed  yourname.ngrok-free.dev   <- same

 = rebuild the ChatGPT connector daily    = set it up once, forever
```

**Outcome:** the operator already had a reserved domain, claimed roughly 11
months earlier and never used — `lyolytic-floria-indiscernible.ngrok-free.dev`,
free tier, permanent. Building proceeded.

**Why Tailscale never had this problem:** a tailnet name is tied to the machine
and is permanent by nature. It is "reserved" without anyone choosing it. That is
why the funnel was set up once and forgotten.

---

## 5. Part three — design decisions inside the harness

### D3 — A dedicated `HARNESS_PUBLIC_HOST`, not an `HARNESS_ALLOWED_HOSTS` entry

```
   Decided        Add a new, single-hostname setting that is ADDED to the
                  allowed hosts.
   Instead of     Telling the operator to put the ngrok domain in the existing
                  HARNESS_ALLOWED_HOSTS -- which needs no code at all.
   Why            HARNESS_ALLOWED_HOSTS *REPLACES* the default
                  ["localhost", "127.0.0.1"] rather than extending it
                  (config.py from_env). So the zero-code option silently
                  deletes localhost.
   Breaks if not  The operator adds their tunnel, restarts, and their own
                  Workbench at 127.0.0.1:8849 starts returning 403 -- an error
                  indistinguishable from a dead tunnel. They would debug the
                  tunnel for an hour. The tunnel would be fine.
   Lives in       harness/config.py  ->  Config.public_host
```

There is a second reason, which only became obvious later: `ALLOWED_HOSTS` is a
*list* with no notion of "which one is the public one". `PUBLIC_HOST` is a
single value, so `harness url` can turn it into an exact connector URL to paste,
and `doctor` can report it. A list could not do either.

### D4 — Loopback is allowed unconditionally, forever

```
   Decided        localhost and 127.0.0.1 always pass the Host check, no matter
                  what any setting says.
   Instead of     Leaving them as ordinary entries in the default list.
   Why            Closes D3's footgun permanently rather than documenting it.
                  A trap that a paragraph in a manual protects you from is
                  still a trap.
   Breaks if not  Anyone who ever overrides ALLOWED_HOSTS locks themselves out
                  of their own machine.
   Cost           None. The server binds loopback anyway, so it is already
                  reachable. Browser-driven rebinding is stopped by the ORIGIN
                  check, which is a separate gate and untouched.
   Lives in       harness/middleware.py  ->  SecurityMiddleware._LOOPBACK
```

### D5 — Exact hostname match, never a `*.ngrok-free.dev` wildcard

```
   Decided        host == config.public_host, exact string comparison.
   Instead of     host.endswith(".ngrok-free.dev") -- which is exactly how the
                  Tailscale rule works two lines above it, so it looks like the
                  consistent choice.
   Why            *.ts.net is YOUR tailnet. *.ngrok-free.dev is shared with
                  every other ngrok customer on earth. A wildcard there would
                  trust strangers' subdomains.
   Breaks if not  Any ngrok user's hostname passes the Host check. The secret
                  route still gates the request, so it is not an instant
                  breach -- but it removes a layer that exists precisely so a
                  single failure is not enough.
   Lives in       harness/middleware.py  ->  _host_allowed
   Pinned by      tests/test_second_door.py ->
                  test_a_neighbours_subdomain_on_the_same_suffix_is_refused
```

This is the decision most likely to be "cleaned up" by someone later who notices
the asymmetry with the `.ts.net` rule and makes them match. The test and the
in-code comment both exist to stop that.

### D6 — Normalize whatever the operator pastes into a bare hostname

```
   Decided        Strip scheme, path, port and case:
                    "  HTTPS://X.NGROK-FREE.DEV:443/mcp  "  ->  "x.ngrok-free.dev"
   Instead of     Requiring a bare hostname and documenting the requirement.
   Why            A Host header carries no scheme, no path, and (after the
                  middleware strips it) no port. So a pasted full URL can never
                  match -- and the failure is a 403, which reads as a broken
                  tunnel, not as a typo.
   Breaks if not  An hour lost to a trailing slash.
   Lives in       harness/config.py  ->  _normalize_host
   Pinned by      test_a_pasted_url_is_reduced_to_a_bare_hostname
```

### D7 — Surface the URL in `harness url`, and the door in `harness doctor`

```
   Decided        `url` prints the ngrok connector URL when configured, with a
                  note that it must be its OWN connector.
                  `doctor` prints the second door, and adds ngrok to the checked
                  binaries ONLY when a public host is set.
   Instead of     Leaving the operator to assemble the URL by hand from the
                  hostname plus the secret route.
   Why            The secret route is 43 characters of random. Hand-assembly is
                  a guaranteed typo, producing a 404 that looks like a tunnel
                  fault. And doctor is the project's "what is actually true"
                  command; a door it cannot see does not exist.
   Why conditional  Warning "ngrok: not found" on every machine that has no
                  second door would train people to ignore doctor warnings.
   Lives in       harness/__main__.py  ->  _cmd_url, _cmd_doctor
```

### D8 — Config is read at startup only; that stays true

```
   Decided        Do not add hot-reload for HARNESS_PUBLIC_HOST.
   Instead of     Watching .env so the operator doesn't have to restart.
   Why            Restart-required is a deliberate, pre-existing design rule on
                  this project (see roots: "restart to apply, by design"). A
                  watcher is a self-service escalation surface for a model that
                  can run shell commands.
   Consequence    Setting the variable while the engine is running produces a
                  403. This is the single most likely real-world failure, so it
                  is named explicitly by check-ngrok.ps1 rather than left to be
                  discovered.
   Lives in       (unchanged behaviour; documented in check-ngrok.ps1 exit 5)
```

---

## 6. Part four — script design decisions

### D9 — The script asks Python for the hostname; it never stores its own copy

```
   Decided        $publicHost = python -c "...Config.from_env().public_host"
   Instead of     A $publicHost = "lyolytic-..." line at the top of the script.
   Why            Two copies of one fact drift. The harness's opinion of which
                  hostname it will accept is the ONLY opinion that matters, so
                  the script asks it.
   Breaks if not  Operator changes .env, script keeps using the old name, and
                  the resulting 403 blames the wrong thing.
   Lives in       scripts/ngrok.ps1, scripts/check-ngrok.ps1
```

### D10 — Poll ngrok's local agent API instead of sleeping

```
   Decided        Poll http://127.0.0.1:4040/api/tunnels up to 20 times at
                  750ms until the expected public_url appears.
   Instead of     Start-Sleep 3, then assume.
   Why            Startup is usually ~1s but can be ~10s on cold or poor wifi.
                  A fixed sleep is either too slow every time or wrong
                  sometimes. The agent API reports the LIVE tunnel, which is
                  the only honest source.
   Note           This mirrors an existing lesson on this project: `tailscale
                  funnel status` reads local config and will happily report a
                  healthy funnel that routes nowhere. Same class of lie.
   Lives in       scripts/ngrok.ps1  ->  Get-NgrokTunnels
```

### D11 — Ask the binary which flag it supports; never assume

```
   Decided        Detect --url support by grepping `ngrok http --help`, and
                  fall back to --domain.
   Instead of     Hardcoding whichever flag the current docs show.
   Why            ngrok renamed --domain to --url across versions. Guessing
                  wrong produces an ARGUMENT error, which surfaces as "the
                  tunnel didn't come up" -- i.e. it looks like a network fault.
   Breaks if not  See below. This one actually paid off.
   Lives in       scripts/ngrok.ps1  ->  $supportsUrl
```

**This decision was validated the same day.** The build first installed was
3.3.1, which supports `--domain` and not `--url`. The build finally used was
3.39.11, which supports `--url` and **has removed `--domain` entirely**. The
script handled both with no edit. Had either flag been hardcoded, one of those
two versions would have failed with a misleading error.

### D12 — The check sends a real MCP `initialize` down the real public path

```
   Decided        A genuine JSON-RPC initialize POST to the public https URL,
                  and inspect status + content-type + body.
   Instead of     Trusting that ngrok printed "online".
   Why            "ngrok online" means the AGENT reached NGROK'S EDGE. It says
                  nothing about whether the harness accepts what arrives. The
                  two most likely failures -- a 403 from stale config, and the
                  free-tier HTML interstitial -- both look like "online".
   Breaks if not  The operator trusts a green light and debugs ChatGPT instead.
   Lives in       scripts/check-ngrok.ps1
```

### D13 — Deliberately do NOT send `ngrok-skip-browser-warning`

```
   Decided        Omit the header that suppresses ngrok's free-tier
                  interstitial, and say so in a comment.
   Instead of     Sending it, so the check is more likely to pass.
   Why            ChatGPT's MCP client does not send it. The entire purpose of
                  this check is to see WHAT CHATGPT SEES. A check that papers
                  over the failure it exists to detect is worse than no check.
   Lives in       scripts/check-ngrok.ps1 (comment in the Python block)
```

This is the same principle as the project's evidence rules: a gate you can
satisfy by being generous with yourself is not a gate.

### D14 — Distinct exit codes, each mapped to a named remedy

```
   Decided        0 = works, 3 = no answer, 4 = interstitial, 5 = harness 403,
                  6 = wrong secret route, 7 = unexpected. Each prints its own
                  fix.
   Instead of     Pass/fail.
   Why            Four failures look identical from ChatGPT ("can't connect").
                  Guessing between them costs more than checking. This mirrors
                  the existing troubleshooting table, which exists for exactly
                  that reason on the Tailscale side.
   Lives in       scripts/check-ngrok.ps1  ->  switch ($code)
```

### D15 — Refuse, rather than fight, an ngrok agent already on another URL

```
   Decided        If an agent is running on a DIFFERENT url, print what it is
                  serving and stop, pointing at stop-ngrok.ps1.
                  If it is already on OUR url, treat that as success, not error.
   Instead of     Killing whatever is running, or starting a second agent.
   Why            Free ngrok accounts allow one agent. Killing someone's other
                  tunnel is destructive and not ours to do. And re-running the
                  start script should be safe -- an idempotent no-op.
   Lives in       scripts/ngrok.ps1
```

### D16 — `stop-ngrok.ps1` closes only ngrok, never the funnel

```
   Decided        A separate stop script that touches nothing but ngrok
                  processes.
   Instead of     Extending stop-harness.bat.
   Why            Requirement 2: do not disturb Tailscale. Closing both doors
                  when the operator asked to close one is exactly that.
   Lives in       scripts/stop-ngrok.ps1
```

---

## 7. Part five — test decisions

### D17 — Seven tests, chosen by what would actually go wrong

```
   test_the_reserved_ngrok_domain_is_accepted_once_configured
       the happy path

   test_an_ngrok_host_is_refused_when_no_second_door_is_configured
       a default install must not accept ngrok traffic just because the
       hostname LOOKS like ngrok

   test_a_neighbours_subdomain_on_the_same_suffix_is_refused
       pins D5 against a future "consistency" cleanup

   test_loopback_survives_an_allowed_hosts_override
       pins D4 -- the footgun

   test_the_funnel_still_works_with_the_second_door_open
       pins requirement 2 mechanically instead of by good intentions

   test_public_url_is_the_connector_url_or_nothing
   test_a_pasted_url_is_reduced_to_a_bare_hostname
       pin D7 and D6
```

The through-line: every test corresponds to a decision above, so if someone
reverses a decision, a test tells them which one and why.

### D18 — A bug in the first version of the tests, and its fix

```
   Symptom        test_loopback_survives_an_allowed_hosts_override failed with
                  "StreamableHTTPSessionManager .run() can only be called once
                  per instance".
   Cause          MY test helper reused one app across two probes, and the MCP
                  session manager refuses a second lifespan.
   Not            a bug in the harness.
   Fix            Build a fresh app per probe.
   Kept as        a comment in the helper, because the failure mode is silent
                  for any test that only probes once -- it would have quietly
                  limited every future test in this file to a single request.
   Lives in       tests/test_second_door.py  ->  _reaches_harness
```

---

## 8. Part six — a gap that was created and then caught

### D19 — `start-ngrok.bat` had a backwards dependency

This is worth reading carefully, because it was a genuine design error, caught
before it cost a session.

```
   THE BUG
   -------
   start-ngrok.bat  required the engine to already be running.
   The only launcher that starts the engine is start-harness.bat.
   start-harness.bat  step 1/4 is:  `tailscale status` -- and it STOPS if
                      Tailscale is not logged in.

   So:

     network blocks Tailscale
            |
            v
     start-harness.bat refuses at step 1  ->  engine never starts
            |
            v
     start-ngrok.bat sees no engine        ->  refuses
            |
            v
     THE DOOR BUILT FOR THIS EXACT SITUATION CANNOT BE OPENED
```

```
   Decided        start-ngrok.bat starts the engine itself if it isn't
                  listening, reuses it if it is, and never calls Tailscale.
   Instead of     (a) Making start-harness.bat continue past a Tailscale
                      failure -- invasive surgery on a file that works.
                  (b) A third launcher -- more things to explain.
   Why            It makes the ngrok path genuinely standalone, which is what
                  the operator asked for ("instead of tailscale"). Running both
                  launchers still gives both doors on a good network.
   Lives in       start-ngrok.bat
```

**How it was caught:** not by a test. By checking the actual machine state
(`Get-NetTCPConnection` on 8848) before telling the operator to run something,
and noticing the engine was not running and that the only way to start it went
through Tailscale. Tests cannot catch this class of bug — it lives between two
`.bat` files.

---

## 9. Part seven — installation, where the real trouble was

Everything above is the code. The code was correct on the first flight. **Both
real blockers were outside the repository entirely**, which is the single most
important fact in this document.

### D20 — winget package IDs are case-sensitive with `--exact`

```
   Symptom        winget install --id ngrok.ngrok --exact
                  -> "No package found matching input criteria"
   Cause          The real ID is Ngrok.Ngrok (capital N).
   Lesson         `winget search` before `winget install --exact`.
```

Small, but recorded because it costs five minutes and reads like "ngrok isn't
in winget", which is false.

### D21 — Running `ngrok update` broke the installation

```
   What happened  winget installs 3.3.1. `ngrok update` fetched 3.39.11.
                  Windows Defender flagged the downloaded file as
                  Trojan:Win32/Kepavll!rfn (severity 5) and quarantined it
                  MID-SWAP. The updater had already replaced the PATH shim, so
                  `ngrok.exe` on PATH now pointed at a file Windows refuses to
                  open. Even `ngrok version` failed.
   Decided        Repair by reinstalling the signed build:
                    winget install --id Ngrok.Ngrok --exact --force
   Instead of     Adding a Defender exclusion at that moment.
   Why            At that point there was NO EVIDENCE about the flagged binary
                  either way, because Defender blocks reading it. Excluding
                  first and asking questions later is how you install malware.
```

### D22 — Stopping, rather than working around an antivirus block

```
   Decided        Report the block to the operator. Do not disable Defender,
                  do not add an exclusion, do not extract with a different tool
                  to dodge the on-access scanner.
   Why            Two reasons, both independently sufficient:
                  (1) Changing security settings is not something an assistant
                      should do on someone's machine, even when asked.
                  (2) Bypassing an AV block on a binary whose signature could
                      not be checked is the actual definition of the thing AV
                      exists to prevent.
   Outcome        The operator made the call and applied the exclusion
                  themselves.
```

### D23 — The discovery that changed everything: `ERR_NGROK_121`

Before the Defender question could even be answered, running the tunnel by hand
produced this:

```
   ERROR: authentication failed: Your ngrok-agent version "3.3.1" is too old.
          The minimum supported agent version for your account is "3.20.0".
          Paid accounts are currently excluded from minimum agent version
          requirements.
   ERROR: ERR_NGROK_121
```

**Read the first two words: "authentication failed".** The authtoken was
correct, and had been all along. Anyone reading only the first clause would
spend the evening regenerating tokens.

```
   Decided        Capture ngrok's real stderr by running it in the foreground
                  with --log=stdout and a timeout, rather than reasoning about
                  why it didn't come up.
   Instead of     Guessing from the script's generic "did not come up" message.
   Why            The script deliberately lists the three COMMON causes
                  (4018 no authtoken / 313 wrong domain / 108 agent running).
                  This was a fourth cause, and no amount of staring at a list
                  of three would have produced it.
   Lesson         An error message names the layer that NOTICED, not the layer
                  that BROKE. ngrok's auth handshake is genuinely where the
                  rejection happened; the cause was a version floor checked
                  during that handshake.
```

**And this created an apparent deadlock:**

```
   ngrok 3.3.1  (Defender-clean, validly signed)  ->  ngrok REFUSES it: too old
   ngrok 3.20+  (required by ngrok)               ->  DEFENDER refuses it

   winget's newest is 3.3.1. Chocolatey had 3.39.9. Neither helps if 3.20+ is
   always quarantined.
```

### D24 — Establishing whether the Defender detection was real, in the right order

This is the most transferable decision in the document.

```
   The tempting move   Add the exclusion, install it, move on. It works.
   Why that is wrong   You would then be running an UNVERIFIED binary with AV
                       coverage removed. Strictly worse than the block.

   What was done instead:

     1. operator adds a folder exclusion, scoped to ONE directory
          C:\Users\<user>\tools\ngrok
     2. download from bin.equinox.io
          (ngrok's OWN CDN -- the same host the winget manifest fetches from,
           so the channel was never in question; only the contents were)
     3. THEN read the Authenticode signature, now that the file is readable
     4. ONLY THEN run it

   The point of step 1 is not "make it safe". It is "make the evidence
   obtainable". Defender blocking the READ was the exact reason the detection
   could not be judged.
```

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
certificate: DigiCert verified ngrok, Inc. as a real legal entity, with a
registered company number, before issuing it. That is the strongest provenance
a Windows binary can carry.

**Verdict: the detection is a false positive** — and that is now a *finding*
backed by evidence, not the *guess* it was an hour earlier. Defender routinely
classifies tunnelling tools as riskware because attackers abuse them, and the
`!rfn` suffix marks a machine-learning/reputation hit rather than a signature
match. But none of that reasoning was allowed to count until the certificate
was actually read.

### D25 — Scope the exclusion to one folder, not the whole machine

```
   Decided        Create C:\Users\Lenovo\tools\ngrok and exclude only that.
   Instead of     Disabling Defender, or excluding a broad path like the whole
                  user profile or WinGet\Links.
   Why            Same outcome -- ngrok runs -- with a far smaller hole. The
                  excluded folder holds exactly one known, signature-verified
                  tool.
   Note           WinGet\Links would have been a bad choice specifically: it is
                  a shared shim directory for EVERY winget-installed program,
                  so excluding it would quietly cover future installs too.
```

### D26 — Remove the old build so PATH cannot resolve to it

```
   Decided        winget uninstall Ngrok.Ngrok, then put the tools folder FIRST
                  on the user PATH.
   Instead of     Leaving 3.3.1 installed and relying on PATH order alone.
   Why            Two ngrok binaries where only one can work is a trap. If PATH
                  order ever changed, the failure would be ERR_NGROK_121 again
                  -- an "authentication failed" that isn't.
   Verified       ngrok resolves to C:\Users\Lenovo\tools\ngrok\ngrok.exe
                  ngrok version -> 3.39.11
```

---

## 10. Part eight — the flight

```
   ngrok 3.39.11  ->  https://<reserved>.ngrok-free.dev  ->  127.0.0.1:8848

   scripts\check-ngrok.ps1:
     engine :8848 listening : True
     ngrok public path      :
       HTTP 200  application/json
       {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18", ...

   Reachable. ChatGPT can connect through ngrok.
```

Then the operator connected ChatGPT and asked it to create a file. It did:

```
   C:\Users\Lenovo\Music\testing projects\chatgpt_harness_test.txt
   -> created through the harness, and read back through the harness
```

**Two risks that had been flagged in advance were closed by that single run:**

```
   ? free-tier browser interstitial   ->  did NOT fire. It targets browser-like
                                          clients; a JSON POST goes straight
                                          through. check-ngrok.ps1 still
                                          detects it if it ever does.

   ? --domain vs --url                ->  3.39.11 has REMOVED --domain. The
                                          script picked --url by asking the
                                          binary (D11). No edit needed.
```

---

## 11. Every file touched, and why

| File | New? | Why it exists |
|---|---|---|
| `harness/config.py` | edited | `public_host` field (D3), `_normalize_host` (D6), `public_url()` (D7), doctor output |
| `harness/middleware.py` | edited | unconditional loopback (D4), exact-match second door (D5) |
| `harness/__main__.py` | edited | `url` prints the connector URL, `doctor` shows the door and checks the binary (D7) |
| `scripts/ngrok.ps1` | **new** | opens the door: config lookup (D9), agent-API polling (D10), flag detection (D11), idempotent re-run (D15) |
| `scripts/stop-ngrok.ps1` | **new** | closes only ngrok (D16) |
| `scripts/check-ngrok.ps1` | **new** | real MCP probe (D12), no interstitial-skip header (D13), named remedies per exit code (D14) |
| `start-ngrok.bat` | **new** | standalone double-click path (D19) |
| `tests/test_second_door.py` | **new** | seven tests, one per decision (D17, D18) |
| `.env` | **new** (gitignored) | the operator's reserved domain |
| `.env.example` | edited | documents `HARNESS_PUBLIC_HOST` and why it is not `ALLOWED_HOSTS` |
| `README.md` | edited | §2 "The second door", troubleshooting rows ⑤⑥⑦⑧, quickstart |
| `docs/USING-THE-HARNESS.md` | edited | §4 second-door setup, §6 daily loop, §13 failures ⑤⑥ |
| `AGENTS.md` | edited | the additive rule, the launcher note, the ALLOWED_HOSTS trap |
| `docs/specs/ngrok-defender-deadlock.md` | **new** | the two blockers and how they were settled |
| `docs/specs/second-door-decision-log.md` | **new** | this document |

## 12. Commits, in order

```
   cfde223  feat(net): a second door, so a hostile network stops being unfixable
   e77ef7a  docs(ngrok): pin the version, because `ngrok update` bricks the install
   bcf729d  fix(ngrok): the second door needed Tailscale to open, which defeats it
   c3c2f52  docs(ngrok): the door is code-complete and externally blocked, both true
   58c3a0e  docs(ngrok): the door is open, and the record says how it was proven
```

## 13. Commands worth keeping

```bash
# install ngrok CORRECTLY (winget's build is too old to connect)
#   download https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip
#   extract to C:\Users\<you>\tools\ngrok
#   VERIFY BEFORE RUNNING:
Get-AuthenticodeSignature "C:\Users\<you>\tools\ngrok\ngrok.exe"
#   expect: Status=Valid, CN="ngrok, Inc.", issuer DigiCert

ngrok config add-authtoken <token>     # operator only; never automate a credential
python -m harness url                  # prints BOTH connector URLs
python -m harness doctor               # look for "second public door"
.\scripts\check-ngrok.ps1              # the only check that proves the real path
```

---

## 14. What is still NOT true — read before claiming anything

```
 [x] The second door works on this machine, over the real internet, verified
     by a real MCP handshake and a real file created by ChatGPT.

 [ ] It has NOT been tested on a network that actually blocks Tailscale.
     The whole reason it exists is still unexercised. It was proven on a
     working network, which proves the plumbing, not the use case.

 [ ] The free-tier interstitial has not been RULED OUT, only not observed.
     ngrok can change free-tier behaviour whenever they like.

 [ ] Nothing here is a security improvement. A second public entrance is a
     second public entrance. The secret route, the Host check, the Origin
     check and the permission modes are unchanged and do all the same work
     they did before -- no more.

 [ ] The Defender exclusion is a real reduction in coverage for one folder.
     It is justified by a verified EV signature on the one binary in it.
     That justification does not extend to anything else placed there later.
```

---

## 15. The lessons, stated plainly

**1. An error message names the layer that noticed, not the layer that broke.**
`ERR_NGROK_121` says "authentication failed" because ngrok's auth handshake is
where the rejection happened. The cause was a version floor. Read past the first
clause.

**2. Verify first, then decide — even when the decision seems obvious.**
The exclusion was going to happen either way. Doing it *before* reading the
signature would have produced the same working tunnel and zero knowledge. Doing
it after produced a working tunnel *and* a verified answer. Same actions,
different order, completely different epistemic result.

**3. Green tests prove the code does what it was written to do. Only a flight
proves the thing works.**
Seven tests passed. Neither blocker was reachable by any of them, because both
lived outside the process — one in ngrok's account policy, one in the machine's
antivirus. This is now the **fourth** time on this project that a green suite
missed what a single real attempt caught:

```
   2026-07-24   the fork bug
   2026-07-28   F1 / F2
   2026-07-29   F3
   2026-08-25   the ngrok version floor + Defender          <- this one
```

Four out of four. That is not bad luck; it is the shape of the system. Plan for
it: **after any change to how the outside world reaches this harness, fly it.**

**4. "Nothing underneath changes" is almost always false somewhere.**
ChatGPT's diagram was right about state and wrong about code, and the wrong part
was invisible until someone read `middleware.py`. When a claim says nothing
changes, that is the moment to go and look.

---

## 16. Addendum — CI had been red for a month, and nobody knew

Found on 2026-08-25 while confirming that pushing a side branch costs no CI
minutes. It is recorded here because it is the same lesson as §15.3 wearing a
different hat.

### D27 — Bound the `mcp` dependency, rather than trusting a floor

```
   The symptom     Every GitHub Actions run since 2026-07-28 FAILED. Six in a
                   row, both OS matrix legs, always in under a minute:
                       ModuleNotFoundError: No module named 'mcp.server.fastmcp'
                   Meanwhile `pytest tests -q` was green on the laptop, every
                   single time, all 484 of them.

   The cause       pyproject declared  "mcp>=1.26"  with NO UPPER BOUND.
                   mcp 2.0 REMOVED mcp.server.fastmcp, which harness/server.py
                   imports. So:
                       laptop  -> already had 1.26.0 installed -> green
                       CI      -> clean install -> resolves 2.x -> everything dies

                   The local venv was correct by accident. Nothing pinned it;
                   it simply had not been upgraded.

   Decided         "mcp>=1.26,<2" in pyproject.toml and requirements.txt, with
                   the reason written in-line so the bound is not "tidied up"
                   by someone who reads upper bounds as timidity.
   Instead of      (a) mcp==1.26.0 exactly -- needlessly rigid; 1.27-1.29 are
                       fine and proven so below.
                   (b) Porting server.py to the mcp 2.x API -- a real piece of
                       work, and not one to start while confirming a push.
   Verified        By bisect in a throwaway venv, not by reading changelogs:
                       mcp 1.27.0  -> fastmcp OK
                       mcp 1.29.1  -> fastmcp OK
                       mcp 2.1.0   -> ModuleNotFoundError
                   Then by simulating CI exactly: fresh venv, `pip install -e
                   .[dev]`, `python -m pytest tests -q`.
                       resolved mcp == 1.29.1   (NEWER than the laptop's 1.26.0)
                       484 passed
                   That second step mattered: the pin moves the project onto a
                   version it had never actually run on. Pinning without running
                   the suite would have swapped one unknown for another.
   Lives in        pyproject.toml, requirements.txt
```

### Why this went unnoticed for a month

```
   The laptop is the place work happens, and it was green.
   CI is the place truth happens, and nobody looked.

   Both were honest. They disagreed because they were installing
   DIFFERENT SOFTWARE, and nothing in the repo forced them to agree.
```

### The lesson, which is §15.3 again in a new costume

**"It works on my machine" and "it works" differ by whatever your environment
happens to be pinned to.** An unbounded dependency means your laptop and your CI
are running different programs, and the one you never look at is the one telling
the truth.

Same shape as the flight lesson: a green signal proves whatever it actually
measured, which is never quite the thing you assumed. The fix in both cases is
the same — **go and look at the real thing**.

```
   2026-07-24   the fork bug          green suite, broken in flight
   2026-07-28   F1 / F2               green suite, broken in flight
   2026-07-29   F3                    green suite, broken in flight
   2026-08-25   ngrok version + AV    green suite, blocked outside the process
   2026-08-25   mcp 2.0 unpinned      green LAPTOP, red CI, for a month   <- new
```
