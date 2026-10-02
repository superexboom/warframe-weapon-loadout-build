# Riven Analysis Audit - 2026-10-03

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

- [ ] Capture exact screenshot inputs and separate cold, cached, and repeated requests.
- [ ] Verify advanced traits by fixed-build ablation under actual trigger conditions.
- [ ] Keep objective KPM and quality windowed DPS attached to their own values.
- [ ] Restore Cannonade compatibility text and its native fire-rate lock description.
- [ ] Refresh valid published cache before solving and reduce repeated searches.
- [ ] Add an explicit authorization gate to full-roster bake entry points.
- [ ] Run focused engine, API, and browser regressions, including extra ranged weapons.
- [ ] Record measured timings, remaining limitations, and current calculation identity.

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
