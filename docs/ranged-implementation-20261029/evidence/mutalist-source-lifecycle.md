# Mutalist Cernos independent swarm field: native closure 2026-10-29

Weapon `/Lotus/Weapons/Infested/Bow/InfCernosBow/InfCernos`, exported mode 0, charged projectile `/Lotus/Weapons/Infested/Bow/InfCernosBow/ChargeInfCernosArrowProjectile` (410 direct). The existing 5-toxin EmbedAttack remains independent.

## Source identity

- Preserved EXE SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`.
- Packages SHA256 `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`, build 2026.10.22.13.12.
- `/Lotus/Scripts/WeaponAttachments/InfCernos.lua` body SHA256 `869c8fe4e1acba195c9703e63fa5aa8d0314e770ba04589f125240f825249666`.
- Trigger `/Lotus/Weapons/Infested/Bow/InfCernosBow/InfCernosSwarmDamageTrigger` raw text SHA256 `196a2628dcc8ddedc2fda341dc4016351f6273a3d60b84376f55dddcc6c1c40e`.
- Embed FX `/Lotus/Fx/Weapons/Infested/Cernos/InfCernosEmbed` raw text SHA256 `60f9675cd73d053c7036512485d383280f4ccef34604072dabea6fe5d7d9f688`.
- Source extraction and exact resolved/raw resources in `mutalist-sources.json`, `raw-resolved.json`, `resources/`.

## Actual dispatch, not declaration alone

InfCernos Lua P0 `OnProjectileStopped` pc85..98 creates the trigger at the arrow position on the host, pc105..110 attaches it, pc111..116 copies the arrow source actor into trigger+0x3f8, pc117..122 copies the arrow creator into trigger+0x400. WeaponUtil metadata uses the creator as key and replaces the previous projectile at pc37..83. This prevents assigning one independently surviving swarm to every multishot ray.

The exact source setter Lua wrapper 0x141972340 calls native 0x140570710, which copies argumentEntity+0x10's handle into trigger+0x400. `reproduce_trigger_clock.py` executes these unchanged bytes and verifies the resulting handle and resolved entity. Receiver/argument VM accessors are controlled stubs; setter behavior is native.

DamageTrigger source enum values are PLAYER_AVATAR=0, ATTACHED_PARENT=1, SELF=2. 0x140e5f58f selects enum0; 0x140e5fd6b reads trigger+0x400, writes DamageInfo source, then 0x140e5fde3..0x140e5fe34 checks LotusWeapon descriptor0x1428c9770. This is a weapon-source path despite its PLAYER_AVATAR label.

0x140e5fe58 ->0x140451710 applies weapon forced-proc modifiers0x119, then 0x140e5fe68 converts the trigger's own AttackData. 0x140e5fee7 invokes innate per-type damage0x1a1. 0x140e5ff7b gets source weapon upgrade categories via+0xaa0, 0x140e5ffbb ->0x1401413d0 applies them using the actual source weapon. Source InfCernos impact categories resolve to `[WEAPON_DAMAGE_AMOUNT]` (0xfd). 0x140e60081..0x140e600c5 calls0x1403a6ea0 ->0x14171a350 for ordinary element0x166.

`reproduce_trigger_source.py` executes the original source router, packet converter, forced-proc helper, innate helper, and packet modifier router. Controlled neutral actor/controller scaffolding and an upgrade callback multiplying0xfd by1/2/3 produce original packet amounts3/6/9 and preserve procChance1.0. The0x166 dispatcher is counted with the correct source weapon and ordinal; the elemental conversion function is stubbed here, so no specific combination/order result is claimed. A reused harness initializes synthetic vtables; it does not prove actual live field count, target ownership, or event dispatch.

## Active clock

The actual DamageTrigger vtable is0x1421635e0, **not** the derived Lotus table found by naive name scanning. Slot+0x230 ->0x141319fd0 ->0x141463ae0 receives dt. Native timer at0x141463c1a checks interval+0x6b0>0,0x141463c24 subtracts dt from remaining+0x6c0, and at<=0 calls slot+0x660. Actual+0x660=0x1410f1e50, which enumerates inside entities and calls damage0x140e5f490 at0x1410f1f4b or0x1410f1fb8. Finally0x141463c4b..52 resets remaining to interval, without carrying overshoot or catching up multiple ticks.

Native constructor0x14024444c initializes remaining0. Thus the periodic branch can fire on the first authoritative update after spawning, independently of DamageOnEnter. DamageOnEnter1 is separately consumed0x14132ac78..0x14132ac9d. The exact first overlap/enter/update order is not replaced by an invented0.5-second initial delay.

Unchanged original update bytes are executed by `reproduce_trigger_clock.py`: interval.5 with initial0 dispatches at first update; initial.5 dispatches when remaining expires; dt1.2 dispatches once; interval0 dispatches none. Native authority and base trigger update are stubbed, and damage enumeration is counted. `trigger-clock-reproduction.json` preserves outputs.

`DamageDuration=2` maps+0x6b4 but is only read by the separate positive InitialDamagePercent+0x6b8 interpolation branch (0x140e600ca). Default initial percent0 leaves this path inactive. It is **not trigger lifetime2**. FX AutoDelayRange5 is also not established as activation delay.

## Scoring handoff

`mutalist-native-periodic-field.json` / `tools/import_mutalist_cernos_swarm.py` supply independent `periodicTriggers`, requiring explicit single-active-field coverage admission. Native steady coverage contribution is3toxin each.5s (6base damage/s), plus distinct DamageOnEnter when an actual entry is supplied. Apply weapon base and ordinary elemental source routes; do not reuse arrow crit/status, directly multiply the field by weapon multishot, or add speculative ten-second per-arrow field stacks.

Required interface: active field coverage with a single source weapon replacement key, separate periodic clock and source modifier route, independent from existing `_lingering`5toxin EmbedAttack. Until lifecycle/phase is represented, an explicit already-active single-field condition can admit steady coverage; do not turn missing lifetime into unbounded default fire-and-forget damage.

Still not calibrated: first enter/update phase, attachment destruction/expiry clock, shared-source multishot replacement ordering, special source controller/ability/innate/CO queries, status/kill Arcane dispatch. Neither generic hit type acceptance nor source-category declaration proves these consumers. These remain warnings, not blanket claims that game testing is the only possible route.

## Verification

`python -m pytest tests/test_mutalist_cernos_swarm.py -q`:7 passed. Both offline native reproductions pass. The importer also ran against exact original Packages/EXE/script and produced the final field profile. No shared production data or replay files were edited, and no commit was made.

## Parent lifecycle follow-up

The attachment wrapper is0x14196c880, actual trigger+0x298=0x141662640. It registers the trigger handle in arrow+0x3b0 and stores the arrow parent in trigger+0x3a0. Entity constructor0x140529b6d/74 sets dead/live parent-inheritance selectors to2, not0. The current resolved trigger supplies no inheritance override.

`reproduce_parent_inheritance.py` executes original0x1406d6d40 with one synthetic registered child: default packed0x4a reattaches for both alive/dead cases, rule0 requests removal, and packed2 distinguishes dead reattach versus live removal. External child attachment, service removal, notification and cookie callbacks are stubs; primitive control flow is native. Thus attachment/default inheritance alone cannot prove that arrow expiry destroys the trigger.

Arrow Die Lua binding0x14196e520 invokes+0x418=0x140414330; embedded route schedules0x1402e1be0 and projectile finalizer0x1405ac4a0, whose final removal callback0x140f4f1a0 forwards to Entity service+0x1f8. The exact service implementation/owner cleanup from this final removal remains open. The source-aware5toxin EmbedAttack's10s declaration must not be promoted to independent3toxin field lifetime.

Profile now explicitly sets defaultEnabled=false, coverageRequired=true, maxConcurrentFieldsPerSource=1 and sourceModifierAllowlist=[weapon-base-damage,ordinary-weapon-elements]. This is a supported active-coverage condition for production integration; it is not a default unlimited field or an invented per-shot lifetime.

## Owner cleanup closure (supersedes the open service statement above)

InfCernos P0 pc94/95 passes arrow as both fifth and sixth CreateEntity arguments. Lua wrapper0x141a240b0 parses fifth at0x141a2415d into rdi, sixth at0x141a24181 into rsi; generic0x1400ef550 puts sixth into CreateParams+0x10. The actual Entity service vtable0x1421a0a28 has create+0x1f0=0x14137d040 and remove+0x1f8=0x1402201a0. Native create0x140cb72b3..0x140cb72fd keys its owner map+0x1f0 by that arrow+0x10 handle, and appends the trigger handle.

The remove wrapper tailcalls0x140185a50. Before removing the source,0x140185c9b..0x140185cf5 recursively removes all registered owner children, independently of Entity parent-transfer inheritance selectors.0x140185e35..76 marks entity+0x20 bit1 and appends its handle to removal queue. `reproduce_owner_cleanup.py` executes unchanged registration and deletion bytes using a prepared owner tree/vector. It verifies registered child and removal order `[trigger,arrow]`, both marked removed. Tree lookup/erase and thread check are controlled stubs; queueing/recursion/membership/flags are original native instructions. Evidence is owner-cleanup-reproduction.json.

EmbedTime serializer0x140da1fc1 maps arrow+0x8ec..0x8f0. Both resolve10. At0x140c3f156..0x140c3f1a4, native embed picks this fixed duration and schedules0x1402e1be0. This invokes projectile finalizer0x1405ac4a0; its queued0x140f4f1a0 forwards to Entity service removal. Therefore swarm expiry is bounded by source arrow's10seconds after embedding and is truncated when WeaponUtil replacement kills it. There is no independently surviving per-multishot swarm. Activation/enter/update/removal frame ordering and spatial coverage are still excluded; production may safely use explicit active coverage with the owner bound represented.

## Production integration contract (supersedes earlier opt-in admission)

After owner recursion closure, the field can use the existing centered-target assumption without a new user checkbox. Importer v4 sets defaultEnabled=true, activation_event=source-projectile-embed, duration_seconds=10, maxConcurrentFieldsPerSource=1. Each effective embed replaces old source arrow/field, creates new field, and resets its clock to0. Collapse first authoritative update to activation time with a timing warning. DamageOnEnter is a separate additional3toxin packet. Model native first-tick and enter as two same-time packets when centered overlap admits enter; then periodic packets each.5seconds strictly before owner expiry/removal.

Do not implement it as only6base DPS during repeated firing: new fields reset the initial-zero clock, so replacement can add first-update packets each shot. The steady field rate6/s describes an unchanged field. Simultaneous multishot source replacement must not multiply surviving fields; exact intermediate overlap/enter ordering remains a diagnostic. Source modifier allowlist stays ordinary base damage and ordinary elements, SC1 CC0, no parent status/crit/MS blanket inheritance. Root owns production replay integration.
