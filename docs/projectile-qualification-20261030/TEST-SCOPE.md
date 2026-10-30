# Projectile qualification test scope (2026-10-30)

This pass changes tests only. Baseline is `ed2319c`; the specified eleven modules collected **205 expanded cases**. Their retained contracts now occupy **29 expanded cases in seven modules**. Four duplicate source/replay modules were merged into existing weapon modules. The rest of the engine suite was not rewritten.

## Case budget

A fix normally gets one regression; a feature normally gets no more than three cases, counting parametrization expansion. Prefer assertions in an existing case and an existing module. A before/after boundary replay is one behavior check, not a replacement loop over a removed numerical grid. Separate bugs and integration boundaries may share a file. Do not hide a matrix in a loop to meet the budget.

| Existing responsibility | Before | After | Retained file |
| --- | ---: | ---: | --- |
| Swapping-charge extraction + Mandonel charged cadence | 9 + 27 | 5 | `tests/test_mandonel_cadence.py` |
| Grimoire source gate + selected-mode replay | 10 + 17 | 2 | `tests/test_grimoire_fire_gate_20261030.py` |
| Mandonel finite fields | 24 | 7 | `tests/test_mandonel_finite_fields.py` |
| Native projectile emission lock | 15 | 4 | `tests/test_native_fire_iteration_locks.py` |
| Scourge contact source + explicit throw cycle | 16 + 20 | 2 | `tests/test_scourge_contact_radial_20261030.py` |
| Tenet Plinx source + runtime | 20 + 44 | 6 | `tests/test_tenet_plinx_runtime.py` |
| Nox non-damage script audit | 3 | 3 | `tests/test_nox_script_audit.py` |
| Total | 205 / 11 files | 29 / 7 files | |

## Retained contracts

- Mandonel: source-local charge versus release charge; charge versus fire-rate cadence; reload/death cannot grant free charge; buffs are read at charge completion; old native capability rejection.
- Finite fields: independent overlapping instances, exclusive expiry, neutral modifier context, primary-mode isolation, generation-bound coverage after direct or field kills, actual manual/search/native batch integration, and old-core Python fallback. Empowered and Encumber each keep one regression with a parent-status positive control, ensuring neutral field status cannot trigger weapon-status arcanes.
- Grimoire: source contract excludes unsupported spatial payloads; actual selected alternate waits 45 seconds despite fire-rate/multishot, primary has no gate. Native execution is asserted and SHADOW checks the same scenario against Python.
- Native emission: selected mode and independent preview retain the lock while ordinary primary scales; source extraction/import preserves it and defers missing damage; old MOD core is rejected. No 13-weapon by bonus by engine expansion.
- Scourge: source admits one accepted contact55 packet under the explicit reload policy; actual replay crosses the second-throw boundary with extra multishot and still emits one spear. The limitation remains visible.
- Plinx: single-projectile full-clip source contract and unresolved-clock scoring boundary; a one-round magazine cannot bypass configured waiting; fractional real Galvanized Shot CO preserves capacity and damage scale for direct and radial packets; battery query effects control actual charge cadence; production manual/search/native health batch agreement and old-core fallback.
- Nox: source audit preserves unrelated Grakata and cannot fabricate a damaging field; changed trigger damage rejects the old contract; production exposes unresolved timing.

Source tests use committed JSON fixtures or in-memory packages. Lightweight mock packages explicitly stub provenance extraction where they lack an attribute reader; no `.local` package dump is required. Reusable fixtures remain in their existing weapon modules.

## Removed duplication

Removed per-field source drift grids, impossible swap-state shapes, repeated internal flag/float assertions, repeated capacities/fractional CO values, and Python/native Cartesian products. Native SHADOW now validates a representative real replay contract without doubling each value. Removed separate parity-only tests where the retained production integration already checks both engines. Removed no production behavior to make a test pass.

Deleted modules were consolidated as follows:

- `test_charge_route_extraction_20261030.py` into `test_mandonel_cadence.py`.
- `test_grimoire_fire_gate_replay_20261030.py` into `test_grimoire_fire_gate_20261030.py`.
- `test_scourge_contact_contract_20261029.py` fixture into `test_scourge_contact_radial_20261030.py`.
- `test_tenet_plinx_cycle.py` into `test_tenet_plinx_runtime.py`.

## Focused verification

```powershell
python -m pytest -q tests/test_grimoire_fire_gate_20261030.py tests/test_mandonel_cadence.py tests/test_mandonel_finite_fields.py tests/test_native_fire_iteration_locks.py tests/test_scourge_contact_radial_20261030.py tests/test_tenet_plinx_runtime.py tests/test_nox_script_audit.py
```

Result: **29 passed** (3.35 seconds on the current built native core). All 29 executed; none skipped. No full-suite or large parity-matrix run was started by this pass. Future packet regressions owned by the main task are outside this count. The main task subsequently updated the existing `tests/test_delayed_radial_events_20261028.py`; its additions and deletions are recorded below.

## Later candidates, not changed

A static inventory suggests reviewing `test_initial_combo_contract_20261028.py` (~75 expanded cases), `test_charge_volley_runtime_20261028.py` (~64), and `test_alternox_embed_lifecycle_20261028.py` (~52). These are candidate matrices, not findings that their contracts are redundant. Review against actual bugs and existing integration coverage before deleting anything.

## Main-task packet changes

- Reused `test_delayed_radial_events_20261028.py`; added three contact-event contracts (ordinary packet, real Arcane consumer, unarmed exclusion) and replaced the old repeated weapon/critical-probability grid and per-validator mutation tests with representatives.
- Added one Trumna Prime direct-impact regression in `test_projectile_headshot_rule.py`; changed the existing inventory auxiliary-mode assertion to the actual Pox export.
- Reused `test_phantasma_packet_audit.py` for one real cold MOD build that compares the admitted PROJECTILE-typed area packet with its former excluded behavior under native/Python SHADOW; kept head suppression and old-core fallback assertions. Removed the superseded no-runtime-payload importer tests and duplicate variant expansion.
- Whole repository collection is **2247**, down from **2443** (net **-196**); four test modules removed and no test modules added. Collection succeeds, including imports after consolidation. This is a collection result, not a claim of running all2247.
- Final validation intentionally targets changed event/field/mode/native contracts. Full bake, full optimizer suite and whole-game parity were not required for this scoped change.

Final integrated result: **100 passed**, plus **20** existing selected-mode parity scenarios with zero mismatches/fallbacks. These are targeted checks, not an all2247 execution. Exact engine/native identity is in `evidence/validation.json`.


## R1–R8 continuation after dd78e98

The completed continuation collects **2248 tests**, versus2247 at its own baseline (net+1); no new test modules. Do not combine this baseline with the earlier2443→2247 reduction.

- Existing spread tests now assert actual per-child contact→blast order and Bramma native187/49 CO; removed the obsolete source-string assertion that every area packet rejects Cold/Puncture.
- Existing delayed-event tests cover corrected explicit-recipient crit, independent body multiplier exclusion and one attached-Pox contract. That Pox case exercises actual Galvanized/Merciless expiry and retained Crosshairs crit through the same field/replay; no per-weapon coefficient matrix was introduced.
- Phantasma remains3 cases: source axis independence, full-clip/extra-MS/low-health paired order, and real cold MOD native SHADOW. Five obsolete duplicate runtime cases were removed from the older secondary-payload module.
- Quanta adds exactly3 expanded cases across real variants. They verify paid ammo/time, no enemy damage from the detonating beam, separate seed/sibling terminal events, actual native invocation and manual/optimizer selected-mode parity.
- Zymos remains3 existing cases. Ordered bucket math is paired with actual carrier/spawn/contact replay, original-host death, contact-only Shiver and Enervate snapshots; unsupported source effects do not abort the parent build. No new per-feature file or one-off acceptance script.
- Stug adds1 real regression in its existing module: lethal packets notify hit/crit before target retirement, using full-victim and actual body/head probabilities, under native SHADOW.

Final focused execution: **137 passed**, no failures/errors/skips. Includes the strengthened Pox Crosshairs expiry/retained-crit assertion and final Zymos source-identity gate; these are not additional unique cases. Selected-mode existing audit: **28 scenarios** across5 representative weapons, zero differences/fallbacks and stable input identity. Optional Quanta/Zymos policies are separately exercised by the retained feature cases; the28 default scenarios are not misrepresented as those opt-in policies.

No full-suite execution, no full bake and no gameplay-measurement claim. Exact native/input identity is in `evidence/validation-r1-r8.json`.


## S1–S5 continuation after f47ef0b

Real source cases were added only in existing modules: one Pox live/forced Shiver contract, one Arbucep exact-source CO/event contract, one Battacor additive-radial contract and one cross-mode status-source regression. Grimoire reuses two existing cases plus one new full policy case (3total), including actual API/static/optimizer/native paths. Scourge extends its two existing cases. Lenz/Sporothrix replace the two old unadmitted assertions in place. Crepuscular extends the existing Zymos operation case.

Removed redundant Arbucep integer matrices, retaining native6-lane boundary6/7 and fractional7.25 where the path differs. Deleted obsolete `test_proc_crit_contract.py` (3cases): it asserted the now-disproved absence of all Puncture/Cold bonuses with broad35% tolerances, and one case depended on an untracked absolute `.local` path and skipped if absent. These claims are superseded by the original-byte type-mask/source proof and precise current packet regressions, not a removal to make the current test results appear green. No replacement test module was created.

Final counts and execution evidence will be recorded after the active native/source changes are frozen. No routine full-suite or whole-game correctness claim.


Final S1–S5 verification: **260passed**, no failures/errors/skips. The selected search audit covers9 distinct catalog records /56 scenarios, exact Python/native equality, zero fallback and stable inputs. Existing Grimoire feature tests separately exercise its optional strategy and static/API/mod-gains paths. Whole repository collection is **2239**, versus2248 at f47ef0b (net-9);0new modules,1obsolete module removed. Banked-charge cases keep1/2/3 withSHADOW rather than doublingPython/native parameters. A single additional original-byte-derived fraction/CD tie regression lives in the existing Scourge file. Exact source/native fingerprint is in`evidence/validation-s1-s5.json`; no entire2239 execution or live-game claim.
