---
name: harness-loops
description: Run bounded evidence-checked refinement passes through the chatgpt-code-harness LOOPS controls. Use when a confirmed Run Contract enables max_loops above zero.
---

# Harness LOOPS

1. Read the gates and current loop status. Stop immediately if the required gates
   already pass or the operator says stop.
2. Choose one target weakness and one directive: repair; challenge assumption;
   simplify; improve robustness; improve performance; or close a verification gap.
3. Call `begin_refinement_pass` with the weakness, directive, and exact planned
   verification. Do not repeat the same directive against unchanged state.
4. Match evidence to the declared kind: build defaults to machine; review, plan,
   and research default to source; use operator only for subjective judgment; mixed
   requires machine or source evidence.
5. Call `complete_refinement_pass` with `improved`, `no_gain`, or `worse`. Source
   passes also record the changed conclusion in `delta_summary`. Operator passes
   wait for the Workbench confirmation button.
6. Stop when gates pass, the locked maximum is reached, two consecutive passes find
   no gain, a pass is worse, credits are exhausted, or the operator says stop.
   Revert a worse pass to the previous best state and record that action.

Forbidden stopping rule: "loop until 100% confidence". A model can be 100%
confident and 100% wrong. Evidence-based stops only.

The laws (one stream; start_process for slow jobs; queue rule - never wait idle;
reality is the only judge) apply at every level.
