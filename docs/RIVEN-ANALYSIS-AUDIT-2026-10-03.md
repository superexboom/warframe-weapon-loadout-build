# Riven Analysis Audit - 2026-10-03

Historical first-pass notes. The checkmarks below overstated complete standard
workflow and browser acceptance; they did not prove the reported Burston card
finished. See [the subsequent stall investigation](RIVEN-ANALYSIS-STALL-2026-10-03.md)
for the corrected root causes, complete request timings and actual browser/API
evidence. The fingerprints and timings below describe that earlier revision.

## Scope

Reproduce the supplied Vectis Prime and Burston Prime cards, then repair the
Riven analysis workflow, contribution conditions, metric units, card metadata,
and slow searches. Preserve unrelated work and existing evidence.

Full-roster cache generation requires a new, explicit user instruction. This
round must not start a full bake, resume the previous supervisor, or enable the
old automation. Use targeted requests and focused regression only. Keep total
calculation concurrency at eight or fewer. Spread remains disabled and Duelist
remains deferred.

## Checklist

- [x] Capture exact screenshot inputs and separate cold, cached, and repeated requests.
- [x] Verify advanced traits by fixed-build ablation under actual trigger conditions.
- [x] Keep objective KPM and quality windowed DPS attached to their own values.
- [x] Restore Cannonade compatibility text and its native fire-rate lock description.
- [x] Refresh valid published cache before solving and reduce repeated searches.
- [x] Add an explicit authorization gate to full-roster bake entry points.
- [x] Run focused engine, API, and browser regressions, including extra ranged weapons.
- [x] Record measured timings, remaining limitations, and current calculation identity.

## Confirmed Starting Findings

- `objectiveScore` is KPM, while the frontend labels it from `scoreMetric`, which
  can be windowed DPS. The screenshot's 11.21 KPM therefore appears under DPS.
- Analysis currently supplies a zero-headshot default and has no analysis-side
  target control. Weakpoint trait contribution must be tested against that
  context and an explicitly nonzero weakpoint-hit context.
- Every non-bake KPM analysis currently starts continuous-metric search, even
  when KPM distinguishes the candidate builds.
- A live server merges a newer disk cache at persistence time, after solving.
- Cannonade runtime behavior is present. Its official localized effect lines
  omit the fire-rate lock note, and build-card metadata needs inspection.
- The targeted fast profile must not launch the expensive continuous-DPS quality
  rerank; it is a bounded ranking pass and stays on KPM when the pressure probe
  saturates. Standard/deep keep the continuous quality path.
- Fixed-build affix ablation is now the default contribution result. The separate
  remove-and-reoptimize estimate is opt-in through
  `includeReoptimizedContributions`; this prevents each displayed affix from
  launching another combinatorial search and keeps the main contribution metric
  explainable.

## Current Fixes

- The analysis page now exposes weakpoint hit rate as an explicit 0–100% input.
  A weakpoint fusion trait reports `inactive` with a body-only target and a
  concrete ablation when the target context includes weakpoint hits. This keeps
  “zero contribution because the target never receives a weakpoint hit” separate
  from “fusion trait was not modeled”.
- Build metric cards read `objectiveMetric` from each build payload. KPM remains
  labelled KPM, while a windowed-DPS result is labelled DPS. The score quality
  metric no longer changes the unit of the build's objective value.
- Expanded MOD cards now include category, compatibility and official fixed text.
  Semi-Rifle Cannonade shows its semi-auto rifle classification and the native
  “fire rate cannot be modified” text; its runtime adapter remains the source of
  the actual lock.
- A live app process refreshes a newer compatible disk cache before an analysis
  request. It never accepts a different fingerprint.
- Full-roster baking now requires `--allow-full-bake` on every supervisor and
  direct bake entry point. The flag is an explicit authorization gate and has
  not been enabled in this audit.

## Validation

The focused regression report `.local/reports/riven-ui-audit-focused-20261003.xml`
contains 21 passing tests. The serial targeted Vectis probe took 75.77 seconds on
the first run and 62.89 seconds on the repeated run before the contribution
parallelization change; it confirmed the expensive stages were calibration,
quality/payload contribution work rather than cache loading. Interactive worker
pool fan-out is now capped at eight, and fixed ablation jobs can run in that pool.

The current engine fingerprint is `c87fc70541a7dcac`. The previously baked cache
has a different identity and is intentionally ignored by the live server until a
new, explicitly authorized bake is performed. No full-roster bake was started by
this audit.
