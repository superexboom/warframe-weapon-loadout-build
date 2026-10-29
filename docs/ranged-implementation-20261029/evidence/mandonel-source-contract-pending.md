# Mandonel charged radiation field static handoff

Current source identities: preserved client SHA256 eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d; Packages SHA256 00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06; script TnConcreteArchgun.lua SHA256 40beef56fe6efe97c4cd8cd43534b712613383a6161a6a46308e185f7a3ca6f0.

## Payload and activation

Export mode1 is ground Heavy charged1800 direct. Weapon HeavyBehaviors[1] RadialOnMissImpactBehavior has OnHitScriptEnabled1 and OnHit callback using AltFireDamageHeavyTrigger. Its own AttackData is50radiation, ProcChance0.34999999, DHT_DOT; DamageOnEnter1, DamageOverTimeInterval.2, capsule radius1.1. Archwing alternate declaration is25radiation/radius3 and is retained as provenance only.

OnHit P5 checks valid creator/owner and stores actor-keyed cncrtHitPt. First callback starts ProcessLastHit; later callbacks in the pending batch only update the furthest hit. P4 pc0..7 yields twice with sleep0, invokes captured shared P0 exactly once pc35..39, then deletes its actor metadata entry pc51..54. P0 pc84..93 creates trigger at segment center, sets dimensions via wrapper141989700 ->140cebbb0 and calls14196aa50 ->14133d890. There is no previous-field destroy or replacement map in P0/P4. Field multiplicity is per coalesced segment, not a parent multishot factor. Collapse the two frame yields to hit time for continuous event scoring, with timing diagnostic.

## Source routing

CreateEntity wrapper141a240b0 parses fifth argument into CreateParams+0x18 and sixth into+0x10. Mandonel P0 passes fifth only, so it has a progenitor, no native owner-registration child.141261710 copies CreateParams+0x18 into creation-context+8. DamageTrigger actual vtable1421635e0 slot1f0=1403106d0 writes it to entity+0x378. This is not damage source+0x400.

Entity constructor1405299a0 initializes+0x400 empty. DamageTrigger constructor keeps it empty. P0 contains no source+0x400/actor+0x3f8 setter. Actual source branch140e5fd6b..7f selects trigger itself when+0x400 resolves null.140aa9240 writes this source to packet+0x270;140447aa0 reads it;140e5fde3..fe36 checks LotusWeapon descriptor1428c9770 and rejects DamageTrigger. Thus r14zero skips weapon base0xfd/innate0x1a1 and ordinary element0x166 source routes.

reproduce_mandonel_source.py executes this unchanged source branch and packet converter: both25and50 remain constant under injected source weapon multipliers1/2/3, SC float32.349999994, resolvedWeapon0, no source upgrade callbacks. Negative class descriptor/neutral actor scaffolding substitutes initialized class ordinals because raw EXE descriptors have not run runtime registration. The weapon-source control reproduction still produces3/6/9 for Mutalist. This proves routing under the established class/source contract; downstream avatar/faction/target modifiers and event ownership are not modeled by this harness.

## Lifetime and clock

Both trigger resources have independent ScriptInstance={TnConcreteArchgun.lua,Destroy,_lifetime7}; the caller OnHit instance has _lifetime10 and must not override the spawned entity instance. Destroy is P3. Its only non-function imported scalar is private atom0x80b9db7f atpc8, passed to sleep pc6..10; after rechecking entity, pc17..22 invokes Region destroy wrapper141a26380 ->1402201a0 ->140185a50. Mapping this scalar to the metadata lifetime is recovered by script usage and independent instance metadata; the general private-name hash algorithm is not recovered. Native Region removal marks+0x20bit1 and queues removal.

The shared DamageTrigger update141463ae0 has initial remaining0 and dispatches once on first update, then resets to.2 without dt catchup. DamageOnEnter is separate and additional. Model t0enter + first periodic t0, then.2 steps strictly before7s. Frame-order phase is an explicit approximation.

## Production interface

Tools/import_mandonel_field.py returns a standalone periodicTriggers field for mode1. Default enable under existing centered-target assumption. Raw50radiation, SC.34999999, CC0, interval.2, lifetime7, independent finite fields per coalesced OnHit segment, no parent crit/status/base/element/MS inheritance. DamageOnEnter and first periodic separate. No shared replay/manual/data edited. candidate_merge only demonstrates mode1 placement; root owns final engine schema integration.

Tests: python -m pytest tests/test_mandonel_field.py tests/test_mutalist_cernos_swarm.py -q =>14passed. Importer ran against source-hashed original Packages/client/script and produced mandonel-native-periodic-field.json. Original source-router reproduction6cases passed.
