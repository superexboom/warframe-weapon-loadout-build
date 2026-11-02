# Deconstructor / Prime: active-projectile and recall native continuation

Preserved build 2026.10.22.13.12. EXE SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`; Packages SHA256 `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`. Original game files remain read-only. No game process, bake or publication used.

This continuation traces new consumers rather than interpreting field names. It closes a finite count-state contract and the bounded recall-request predicate. It does **not** provide a fixed flight/return duration to the production replay.

## State class and actual count consumers

The weapon declares `/EE/Types/Game/WeaponGrenadeStateBehavior`. Its table `0x14218c230` has serializer `+0x50=0x141691320`, count-availability callback `+0x428=0x14113fc80`, transition router `+0x168=0x140592870`, limit predicate `+0x330=0x14173efc0`, new-projectile consumer `+0x328=0x141561250`, and removal consumer `+0x300=0x141050a70`.

Registration `0x140655790` maps TrackProjectiles to state+0x60, MaxNumProjectiles to state+0x68, PvpMaxNumProjectiles to state+0x70. `0x141691320` maps ResetRefireWhenActiveProjectiles to state+0x160. The actual strings are `mTrackProjectiles`, `mMaxNumProjectiles`, and `mResetRefireWhenActiveProjectiles`; searching the prefix-free interior strings misses descriptor pointers. Both source weapons set true/3/true respectively.

`0x140844210` returns state+0x108 (qword active count). The ordinary non-PvP predicate `0x14173efc0` returns `max != 0 && active >= max`. Its PvP override path is separate and is not used by this bounded contract.

`0x140592870`: requested state0 or1 first audits weak handles. If max is nonzero and count>=max, ordinary non-automatic state (state+0x61 false) routes to state20. Otherwise it forwards the requested state. `0x14003f4c0` registers enum20=WS_FIRE_DISABLED and7=WS_REFIRE_WAIT. This reuses the independently preserved Mausolon enum evidence and freshly captures the same original function bytes.

`0x14113fc80`: while active>=max it makes no state transition; when active<max it calls the state transition virtual with7 if ResetRefireWhenActiveProjectiles is true, otherwise0. This proves a slot opening does not by itself authorize an immediate shot. Recovery consumers are closed below; flight/catch and frame order still need replay inputs.

## Projectile registration and removal

Actual launch `0x14126d1f0`, at `0x14126e473`, calls `0x140cf3ed0` to obtain a byte slot ID and stores it to new projectile+0xf88 at `0x14126e47b`. TrackProjectiles admits non-grenade projectiles to slot allocation; free slots are reused before the next ID is allocated.

New-projectile consumer `0x141561250` uses the same projectile+0xf88 and state weak-handle slots at+0x50; its append/reuse paths increment state+0x108 at `0x14156157d/59f/5c1`. A valid matched removal in `0x141050a70` clears the matching slot and decrements state+0x108 at `0x141050ae9`. It checks weapon existence and matching slot identity, so target death is not a substitute for this projectile lifecycle callback.

Projectile teardown `0x1415ff440` checks+0xf88!=255, resolves its weapon from+0x708, decodes behavior ID, invokes weapon virtual+0x8a8 with the projectile, then marks slot255. The weapon forwarding is now closed: original `0x140ef2970` decodes the projectile-saved behavior ID at+0xd88, checks it against weapon+0x7d8 /96, loads behavior bank+0x7d0 +96*id +0x58 and tailcalls state+0x300. It uses the saved projectile behavior ID rather than the weapon current active bank. Original-byte execution with initialized objects forwards the exact projectile pointer to the exact saved state. Bulk clear `0x140e2b790` also decrements actual occupied handles. There is no basis to decrement the count on every damage hit or reset IPS phase on target death.

## Recall is a gated request, not a fixed return time

Projectile class constructor `0x140b1e4f0` installs table `0x1422b5648`; serializer `0x14129c160` maps AutoRecallTimer to projectile+0x1a08, NoAutoRecall to+0x1d19, CatchRadius to+0x19cc, MinFlightDistance to+0x1d20, and MinFlightDistancePerReflect to+0x1d28. The source MeleePetProjectile has timer1, both distance thresholds29.5, speed40, CatchRadius2.5, MaxLife15, DestructionTimer0.60000002.

Actual update `0x1416a9a40`, at `0x1416a9d2f/38`, advances elapsed+0x1a04. For ordinary mode0, bounded block `0x1416a9db3..0x1416a9e53` requests `0x1417f0030(projectile,0,1)` only if:

- elapsed **strictly exceeds** timer1;
- NoAutoRecall is false and virtual+0x608 is false;
- an original source reference exists;
- accumulated+0x1d1c >=29.5 and accumulated+0x1d24 >=29.5;
- the parent type getter is valid and parent+0x4c0 is false.

`0x1411e1e00`, at `0x1411e20ae..0x1411e2100`, adds the same movement-distance increment to both accumulators. Reflection reset and every movement branch were not fully traced, so the second accumulator is not treated as a derived constant-time clock. Constructor initializes mode+0x1d48 to0; separate mode1/mode2 paths are outside this bounded predicate.

Consequently AutoRecallTimer1 does not establish a return at1 second, nor a fixed1-second/1.6-second reattack period. Recall request, physical return/catch, destruction fallback and active-count release are distinct events. Actual victim hits/reflects and motion affect the future accumulator and catch events.

## Original-byte verification

Evidence directory: `.local/delivery/mechanics-static-completion-20261028/companion-followthrough/`.

- `active-fields-v2-20261103.json`: descriptor references.
- `active-state-vtable-20261103.json`, `active-owner-routing-20261103.json`: tables and mutation/owner references.
- `flight-accumulators-20261103.json`: time/distance consumers.
- Complete chained-unwind disassembly and original code bytes are retained as address-named asm/json files.
- `prove_active_gate_20261103.py` asserts the full original EXE hash, maps original bytes and executes the complete native limit predicate, availability callback, transition router, and bounded recall-request branch. 10 count/availability rows +12 transition rows +6 recall rows pass. Initial recall scaffold lacked the initialized source weak handle+0x738; corrected fixture includes it. Game decisions and original branches were not patched.

Synthetic callbacks: valid initialized weapon/parent objects, no-op diagnostic and+0x608 eligibility, valid parent type getter, and record-only final state apply / recall request. No collision, physical catch, actual game frame or full weapon state timer is emulated. Unicorn was installed only under ignored `.local/tools/native-python` for this run.

Reproduce from Portable root in PowerShell:

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) '.local/tools/native-python')
python .local/delivery/mechanics-static-completion-20261028/companion-followthrough/prove_active_gate_20261103.py
```

## Refire timer and state update glue

`0x140aa3a60` uses the actual state switch table at RVA0xaa41a4. State20 dispatches at `0x140aa4105` directly to virtual+0x428, the proven count-availability callback. State7 dispatches at `0x140aa3c9d` to virtual+0x3f0=`0x140338300`; that consumer first reads weapon+0x3c0 remaining clock, waits while positive, then routes READY (or EMPTY/reload according to actual ammo/input gates). Thus the count callback runs from FIRE_DISABLED, not as an unconditional every-frame reset of the refire wait.

Weapon transition `0x140f67b40` calls selected state+0x160=`0x141386060` for state duration. For ordinary source settings UseReloadTimeBetweenShots=false and DoPreFire=false, state7 calls+0x338=`0x14126b520` and returns `1 / effectiveFireRate`; state20 falls through zero duration. Source fireRate80/minute means neutral effective80/60, duration0.75s. The calculation uses the live effective fire-rate upgrade getter; do not cache0.75 across MOD changes.

`0x140f67c2a..0x140f67c58` writes new duration to weapon+0xcf0, then sets+0xcec to duration when old clock>0, otherwise to duration+old clock. It preserves negative frame overshoot. Actual weapon clock update `0x1412678a0`, at `0x141267c2c..0x141267d39`, subtracts elapsed dt for state7 and20 through `0x141267d2d`; state20 can accumulate negative wait time before a slot opens. Therefore the exact condition is not always a fresh full0.75s after a return: it is the source duration plus nonpositive carried clock, followed by actual update/event order. No production fixed extra0.75s penalty is introduced.

The existing proof script now adds only three small controls: original behavior-index removal forwarding; original full state7 duration0.75 under controlled80/60 getter; original timer-entry negative carry -.125 +.75 =.625. It retains the previous28 representative controls and does not add test matrices or modules.

## Production integration boundary

A replay with explicit projectile-created and projectile-removed events can implement count admission and recovery routing from this contract. Existing ordinary replay has no flight/catch event source, so fabricating removal at1 second would replace a disclosed unknown with an incorrect source claim. Keep its lifecycle diagnostic and current IPS model until root chooses explicit trajectory/contact inputs or traces a bounded no-reflection movement/catch policy. Production source metadata now exposes `lifecycleContract` in `data/mechanics/companion-projectile-sequences.json`, reproduced by `tools/import_companion_projectile_sequences.py`: exact max3/count unit/removal consumer, FIRE_DISABLED and REFIRE_WAIT states, live fire-rate reciprocal plus negative clock carry, source addresses, `returnSeconds:null`, and missing flight/catch/frame inputs. Importer and committed-data metadata match in the existing source fixture.

Diagnostics now explicitly say `companion-projectile-flight-catch-schedule-unmodeled` and `companion-active-count-gate-and-refire-recovery-not-replayed`, replacing the generic limit/unverified wording without claiming replay coverage. Existing tests only update these diagnostics and extend their current source contract assertions; no new test file, damage or production replay change. Focused sequence/mechanics/unmodeled regressions:42passed.
