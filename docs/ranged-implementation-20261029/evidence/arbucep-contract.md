# Arbucep sequence implementation ready for root admission

Engine shared-file edits are finished; no further engine edits pending from this agent.

New owned source: tools/import_arbucep_projectile_lanes.py, vendor/wfarsenal/projectile_lanes.py.
New regression: tests/test_arbucep_projectile_lanes.py (28 focused cases).
Narrow shared edits: manual_combat.py, combat_replay.py, native_replay.py, native/wfcore/src/replay.rs and lib.rs.
Preserved Battacor chargeBeforeFire/damageScale and delayed-radial event changes. No commit, push, bake or data merge performed.

Root integration:
- Merge `.local/delivery/ranged-implementation-20261029/native-payloads/arbucep-projectile-lanes-patch.json` using tools.import_native_secondary_payloads.merge_patch into current combat-reference.json (mode 0 belongs directly at auditedAttacks[path], not under modes[0]).
- Add projectile_lanes.py to app.py engine fingerprint list. This agent did not touch app.py or combat-reference.json.
- Rebuild native once if other agents change it further; tools/build_native.py already succeeded and installed wfcore.pyd for this revision.

Behavior:
- Cyclic six physical projectiles Blast, Corrosive, Gas, Magnetic, Radiation, Viral; extras continue current sequence, no Blast override.
- Each projectile independently resolves MOD coalescence, direct32 and radial228, raw SC2.0940001 / native6 (not modded count), crit0.1/2.9000001; final packet multishot1.
- Single pull ammo/cadence/on-fire; actual projectile count advances phase across reload and kill. Same-pull remaining packets cannot hit replacement victim.
- Legal fractional multishot remains operational via 16 deterministic stratified whole-trajectory branches (floor+Bernoulli each pull); explicit projectile-lanes-fractional-count-16-stratified-trajectories-approximation diagnostic. Branch results keep representative discrete lane/phase and expose phaseByBranch; no mean-phase state.
- First-round direct bonus applies to each actual direct packet. Native full-result shadow parity includes fractional counts, crit/status, first-shot bonus and kill generations.
- CO/head producer routing stays explicitly neutral pending proof; geometry/contact coverage idealized; mushroom/decor scripts remain diagnosed.

Evidence source hashes:
- EXE eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d
- Packages 00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06

Validation: native release build succeeded (two pre-existing unused warnings). Combined focused suite 153 passed, including 28 Arbucep cases plus delayed radial, kill windup, Battacor, secondary payload and Mutalist Cernos cases.
