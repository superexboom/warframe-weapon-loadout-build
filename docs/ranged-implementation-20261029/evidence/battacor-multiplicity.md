# Battacor radial multiplicity closure, 2026-10-29

The previous fixed-one-radial-per-trigger model is disproved for the exact Battacor source signature. Each accepted ray collision contributes its own 208 Radiation radial packet. MultiShotBuffsRadialDamage=false suppresses an additional multishot factor inside each packet; it does not suppress ray count. On the model assumption that all rays connect, no-crit/status/falloff direct+radial is 416*N*C, where N is ray count and C is pre-consumption charge snapshot 1/2/3.

Original EXE SHA256 eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d. Exact weapon and four ancestry records retain importer hash admission. Raw mode1 declares IgnoreFireIterations=0 and OnlyHitEnitiesOnce=1; both now receive semantic admission checks.

## Native chain

- 0x14133e7a4 calls 0x140f75d20; fire+118 resolves 0x1416a5ed0 and weapon+6e0 supplies the fire-iteration upgrade query. Full native count conversion gives 1/2/3 from integer multishot 1/2/3.
- 0x14133e8b1 passes that count to 0x140be1db0. Both zero-spread and spread loops submit 0x14185ca50 once per ray. The callback at 0x14185d044 binds thunk 0x1406e6d4c, which invokes fire+2a8 -> 0x1409b4480 -> 0x140ee5ca0.
- 0x140ee5ca0 initializes an empty hit-list at rbp+520 on EACH callback. Its 0x1409c6aa0 call receives that list. The unchanged 0x1409c70a1..0x1409c7278 consumer performs OnlyHitEnitiesOnce dedup and appends original 0xd0-byte result records. Repeated rays striking the same object have empty callback-local lists, so no cross-ray dedup occurs.
- Original collector finalization suffix 0x140581be1 calls weapon+650 -> 0x141550e40. Active mode1 impact+b8 resolves 0x140fc83e0 (a leaf thunk missed by unwind-root-only dumps) -> 0x14139b3b0. That function advances 0xd0 per record and calls impact+f8 -> 0x14140f600 -> 0x140e91ec0. The controlled native harness now executes this actual dispatcher; it does not manually rebuild result records before impact.
- 0x140e92204 checks MultiShotBuffsRadialDamage. Flag0 leaves each packet208 for queried multishot1/2/3. Counterfactual flag1 gives208/416/624 per packet.
- Existing charge proof remains intact: 0x141377160 -> 0x140164110 snapshots current count before consume/clear; state+268 -> 0x1403b99c0 multiplies cached1 by snapshot getter0x14176c6d0; both direct and radial read weapon+4a0/+4a8.

## Evidence and limits

verify_battacor_ray_multiplicity.py runs original EXE instructions with 26 cases:6 count/emission cases (N1/2/3 at spread0/.5),7 direct impact-list cases,7 actual collision collection plus collector/weapon/impact dispatch cases,6 packet-MS branch cases. Both hit/avatar and miss/non-avatar accepted collision cases produce N1/2/3 radial calls; mixed hit/miss/hit produces3. Repeated same-victim collisions remain distinct. The baseImpactCallbacks counter is base impact-builder invocation, not proof that a wall receives direct damage.

Scene collision acceptance, aim, numeric upgrade query results and owner/query scaffolding are controlled offline inputs. Constructors that only initialize/copy/refcount packets, unrelated scripts/status hooks and weapon+950 scoped notification are stubbed. Miss cases mean accepted non-avatar scene collisions, not an uncollided ray in empty space. No real-game firing, spread overlap, environmental ricochet, deep punch-through topology or live Arcane/CO dispatch acceptance is claimed. The source proof still exposes CO, radial notification, dynamic-buff snapshot and DoT-during-windup limitations.

## Files and validation

Changed only tools/import_battacor_radial.py and tests/test_battacor_radial.py. Root-owned chargeBeforeFire/selectableChargeCounts/configurationKey and timing diagnostics are preserved. takes_multishot=true now represents packet count; perPacketTakesMultishot=false explicitly records the independent payload branch. Removed only battacor-radial-per-trigger-multiplicity-unverified from multiplicity diagnostics.

Generated candidate is battacor-multiplicity-import.json. Production mechanics JSON was NOT written by this agent. verify_battacor_model_candidate.py regenerates the hash-gated candidate and injects it into this Python process's mechanics reference cache before testing; no mechanics files are changed. It passes67 tests across test_battacor_radial.py and test_kill_charged_windup.py. New18-case trajectory matrix checks N1/2/3 * C1/2/3 in both Python and enabled native paths, preserving base208 per packet and applying C exactly once. Dedicated MS3 expectation changes832 ->1248.

## Root merge commands (run from repository root)

```powershell
python tools/import_battacor_radial.py --packages .local/delivery/ranged-calibration-20261028/script-gaps/work/packages --parents .local/delivery/ranged-calibration-20261028/script-gaps/work/parents.json --native-image C:/Users/SuperExboom/Documents/WF_Rever/research/stug-detonation-20261026/artifacts/original/Warframe.x64.exe --evidence .local/delivery/ranged-implementation-20261029/trigger-routing/battacor-multiplicity-production-import.json
python -m pytest tests/test_battacor_radial.py tests/test_kill_charged_windup.py -q
python .local/delivery/ranged-implementation-20261029/trigger-routing/verify_battacor_ray_multiplicity.py
```

The importer preserves unrelated JSON records/line endings. Its evidence argument must be a new file. No commits, push, bake or shared-core edits.
