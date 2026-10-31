# Main explosion consumers and variant closure — 2026-10-31

Scope: ordinary player weapon source without a Powersuit/PowerSuitAbility parent, selected contact victim under the existing single-target body/centre policy. EXE SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`; Packages SHA256 `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`. New original-byte dumps, source projections and controlled results: `.local/delivery/projectile-continuation-20261031/main-consumers/`.

## Final contracts

| Exact source family | Contact explosion | CO / Shiver in this packet | Explicit recipient type / victim crit | Notifications / location |
|---|---:|---|---|---|
| Larkspur / Prime heavy |1600|Excluded for ordinary source|c24 default2; Puncture/Cold allowed|Generic hit/crit; independent proxy location|
| Phantasma / Prime parent|73|Excluded for ordinary source|c24 default2; Puncture/Cold allowed|Generic hit/crit; independent proxy location|
| Acceltra|44, armed >=6m|Excluded for ordinary source|c24 default2; Puncture/Cold allowed|Generic hit/crit; independent proxy location|
| Acceltra Prime|53, armed >=6m|Excluded for ordinary source|c24 default2; Puncture/Cold allowed|Generic hit/crit; independent proxy location|
| EFV-8 Mars fullcharge|313|Excluded for ordinary source|c24 default2; Puncture/Cold allowed|Generic hit/crit; independent proxy location|

This table describes the explicit supplied contact target, not every Scene recipient. Current selected body policy produces no extra head/weakpoint events, but that is a location input rather than native HitType rejection. None gains an ordinary head damage multiplier: the separate event+25c remains1.

## CO closure includes the victim-side back door

The main +7b8 callback140f360f0 calls actual +63014160c5a0 -> +638141234720. That builder queries the projectile DamageUpgradeTypes array; constructor140fbadf9 installs253 and these source chains do not override it. It performs normal damage/element/status construction. Neither common main callback nor its builder routes this new explosion through the contact +790 -> weapon+818/+820 stage. The source contact packet preceding it is separate, even when DealDamageThroughImpactBehavior=1.

It would be insufficient to stop at the absence of +818: victim LotusDamageController +738141482900 also calls +75814111fa60 at1414829d3, and the latter has a genuine CO-core call14111fd86. Its decisive gate14111fd11..1d invokes complete141baa200 with argument0 and skips this call when false. The damage source is packet270 ->140447aa0 ->140b14fa0 -> controller+6e8. Actual table1422588d8+6e8 is leaf1400e2070; it can unwrap an intermediate, then140a7ba40 unwraps Projectile+708 and recursively normalizes; an ordinary weapon returns itself. This is not a guessed arbitrary projectile pointer.

Reused unchanged `verify_target_co_routing.py` in memory, redirected only its output path. `ordinary-source-co-control.json` records full helper+actual IsAbilityWeapon/parent getter execution: ordinary LotusWeapon/WeaponEx, IsAbilityWeapon0, null parent gives helper0 and zero CO calls. A normal weapon parented to Powersuit or PowerSuitAbility is the positive control and reaches the CO entry with callerBase73. Therefore rejection is established only for the selected ordinary source scope; abilities and injected parent/source contexts remain separate support inputs. Both259 and261 are queried by the same CO core, so Shiver is excluded on the same ordinary main explosion path. This does not revoke the independently proved CO/Shiver of a separate direct or attached packet.

## Head / weakpoint event chain and the genuine scene boundary

140f360f0 constructs a fresh event1402ee670 -> converter140bc2730, then overwrites event+1bf from Projectile+c24 at140f36343..34a. The c24 constructor default2 is independent of falloff+634. The converter unconditionally sets event25c1; this suppresses the ordinary head damage uplift at141482dc5 but does not clear hit part210.

The new event does not inherit the direct packet's head proxy. Common140f364e4..140f36582 asks the actual recipient's +908 controller to find a subentity with +160140caa7c0. It calls +450140dee1c0 for a found index, otherwise +4481402d2560. These populate the new event hit-result at+130, including subentity+158 and proxy handle+170. At victim +740140e49e10, a valid subentity also installs proxy+200. Subsequent +748140d9d930 fills event210 from proxy530, or the hit-chain proxy530, or a body/subentity fallback. No read of25c occurs in that full leaf.

`head-proxy-controls.json` executes the entire original140d9d930 with synthetic packet/proxy storage: initial2107 plus25c1 and proxy5301 produces HEAD1; proxy5300 produces body0; absent proxy with invalid subentity produces body0. There are no modified instruction bytes or forced eligibility results. This proves suppression alone cannot reject head notices. It does not simulate proxy selection or actual collision geometry.

GenericChallenge14051d790 separately reads final HitType at14051da09..4d, and head part at14051dc3c..54 (condition PartHEAD1 versus packet210). PROJECTILE2 passes the recovered head/weakpoint hit-type filters, whereas ordinary RADIAL4 fails relevant filters. Weakpoint Lua/weakness and injury/kill ownership remain independent. Thus the former '*weakpoint-events-neutral-fallback-unverified' wording is replaced by an explicit 'proxy-geometry-body-policy' boundary. No unconditional HEAD is admitted from a direct head aim setting, and no false universal 'main explosions cannot head-notify' statement remains.

## Exact variant census and corrections

`source-census.json`, `source-contracts.json` and `acceltra-prime-source.json` come from the hash-pinned package reader. Both selected Larkspur and Phantasma variants already use their distinct real paths. EFV-8 fullcharge has Engine Projectile ancestry, ExplodeOnImpact1, Embed0, direct35 and independent313 Corrosive. Ordinary1410e2120 contact calls +7b8 with the accepted current victim at1410e364c..59; common delivery then reaches Avatar+340/+348 and the already audited authority generic challenge chain. Its absent type is c24 default2 for that explicit target, not the plan's default4. This admits the missing generic notifications and independent victim-crit qualification for that exact313 source.

Acceltra Prime was genuinely omitted from SPECS and its producer registry. Its exact PrimeAcceltraProjectile inherits the audited base SapientPrimaryProjectile and does not alter the relevant class, arming6, death, embedding or callback route. Native differences are direct44 Impact, radial53 split(.80000001 Puncture/.19999999 Slash), CC.34/CD3, status.18000001, radius5. Its selected fire behavior uses PrimeAcceltraProjectile and a two-entry same-payload cosmetic sequence, fireIterations1, advanceProjectileSequenceOnFire0. Neither sequence entry is an extra emitted shot. Its old combat-reference row had correct nominal53 but stale reference/arming provenance and lacked explicit target victim-crit/generic contract.

## Implemented importer change and root merge proposal

Owned source edits: `tools/import_native_secondary_payloads.py`, `tools/import_larkspur_contact_radial.py`, existing `tests/test_native_secondary_payloads_20261029.py`. Added exact Prime SPECS and source-driven direct/status verification. Main source profiles now retain an explicit CO rejection proof and location policy; merge retires only the exact superseded source-family warnings when the incoming component carries that proof. No shared JSON/core files were edited by this worker.

Root integration artifacts:

- `mode-patch.json`: seven modes, generated from real current native sources and current exported rows; contains existing Phantasma lifecycle and Larkspur contact contracts, not a partial replacement losing them. Use normal `merge_patch` so unrelated existing fields survive.
- `producer-patch.json`: two new exact source/ExplosiveAttack rows for PrimeAcceltraProjectile and EFV-8 fullcharge. GenericHit/CriticalHit true; takes_victim_crit true; directRecipientHitType PROJECTILE; takes_condition_overload false. headHit false is the selected body policy; enervate grouping remains unchanged.
- Merge producer rows before future reimport, so apply_native_contract reproduces these overrides. The review mode-patch already includes proposed overrides without touching production registry.

Existing importer regression suite:29 passed3.29s. Replaced five base-only distance cases by base5.999/base6/Prime6, while the generic SPECS contract gains the exact Prime source. No new test module. Native CO controls5 and head-proxy controls3 are reused/inline evidence, not new project test files. Actual game scene acquisition/trajectory/LOS and arbitrary ability parent contexts were not executed. No bake/Bot/release.
