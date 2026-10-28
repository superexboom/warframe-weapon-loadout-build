# Latest bridge closure evidence, read-only

## New verified facts

Controller +0x5f8 is serialized `mAGCEnabled` (descriptor0x14278d610, serializer0x141066f51->0x141066f64). Controller +0x5f9 is `mAGCEnabledDefault` (descriptor0x14278c1b0, serializer0x140129599->0x1401295ac). Constructor0x1412214a0 initializes+0x5f8=1 via word[+0x5f7]=0x10f at0x141221d54,then+0x5f9=1 at0x141221d5d. AGC acronym is retained without invented expansion.

`verify_native_damage_challenge_bridge.py` executes unchanged function0x14179b840 with explicit world/agent/source-owner/HP stubs.13cases pass. With AGCEnabled/Default1 and live victim,the SAME RADIAL event can notify challenge manager twice across two calls; projectile+d84=1 does not block this bridge. TRACE,PROJECTILE and DOT also pass bridge (effect conditions remain downstream). AGCEnabled0 suppresses both. AGCDefault0 skips first but is restored after a live event,so second invocation notifies. With HP0/injury byte11,first notifies and resets default0;second is suppressed. Thus this bridge is definitely not once per projectile, but it has a death/lifecycle gate.

## Static conditional route now linked

Zakti base projectile inherits native `/Lotus/Types/Weapon/BoltoProjectile`; Kompressa goes through `/Lotus/Types/Weapons/BoltoProjectile` to that same native class. Their class vtable0x14226a010 binds:
- +7380x140f25fa0 ->0x140c3ecb0,setting+c25=1.
- +7680x140163a60(death callback).
- +7b8 0x140f360f0(radial delivery).
- +6300x14160c5a0(radial plan builder),true+c25 selects EmbedDeathAttack+9c8.

Death callback0x140163a60,after its active/death-trigger gates, at0x140163b24..b34 calls+7b8. With default ExplodeOnImpact+16d0=0 and ExplodeOnLifeExpired+16d6=0,its+c25 flag does not veto that call. The script/controller world death trigger invokes this callback only when projectile+c10 is active;source setter0x1405ac8ee arms+c10. I have not separately emulated the full timer/world callback registration.

Inside radial delivery0x140f360f0:
- event ctor0x1402ee670,then0x140bc2730 copies plan's HitType to event+1bf at0x140bc28b0/b7.
- ctor at0x1402ee8f9 writes dword[event+254]=0x10000,so event+256=1. Plan-copy does not clear it.
- +21&7 false client/local branch at0x140f365d9 calls target-avatar+348(event); ordinary Avatar/LotusAvatar vtable binds+348 to0x140470f80.
-0x140470f80 at0x1404710e1 checks event+256. True ->victim DamageController+100 via0x1404710ea..110. Ordinary Lotus/ScaledLotus controller vtables bind+100 to0x141262dc0,which calls0x140524b60 at0x141262e11. That function'scompletion at0x140525293 calls0x14179b840.
- This explicit chain is distinct from the Projectile+d84 once-notice chain. The independently emulated bridge would accept repeated live radial packets if actually invoked through it.

This is a **conditional native route**, still not an unconditional Kompressa/Zakti delivery contract. The authoritative branch +21&7 true calls target-avatar+340->0x140d9c670->controller+f8(0x140d40ee0),which is a different receiver. It may rejoin via queues/controller processing but I have not proved or emulated that rejoin. The standard victim controller'senabled checks,scene identity,owner routing and actual death callback invocation remain dependencies. Do not declare exact 2 notifications per player projectile solely from the client route.

## Consequence for root

Strongly separate these outcomes:
1. `Projectile.SendEvents` is defaulttrue and once-per-projectile;this alone does NOT authorize delayed-radial event duplication.
2. Damage-controller AGC bridge can emit repeated radial event notifications, independent of projectile+d84.Therefore once-per-projectile notice does NOT prove current simulation's delayed notification omission is correct.
3. A concrete Bolto EmbedDeath->radial->client-avatar receiver->damage controller->AGC conditional call chain exists. Full gameplay-side host/authority delivery is not closed. Current `待资格验证` diagnosis remains accurate; no production correction requested in this pass.

Files:agc-fields.json,damage-challenge-flags.json,bolto-vtables.json,bolto-embed-and-die.json,avatar-submit-vtables.json,avatar-submit-functions.json,damage-controller-vtables.json,packet-256-path.json,native-damage-challenge-bridge-results.json. Exact assembly also saved as corresponding .asm files.

No production modifications,build,bake,push or game process work.

Additional original-byte dispatch proof: `verify_native_client_radial_dispatch.py` executes avatar suffix0x1404710e1..0x140471113 and actual native getter0x1400dace0. Flag256=1 dispatches controller+100(actual0x141262dc0);0 dispatches+108(actual0x1412cb3e0),with exact controller/event pointers preserved. Original constructor instruction0x1402ee8f9 independently initializes256=1. Both route cases pass. This proves this conditional receiver dispatch only,not authority/scene admission.

### Authoritative receiver extension

Further traced authoritative Avatar+340 ->0x140d9c670 ->controller+f8 ->Lotus0x140d40ee0. Its actual tail at0x140d41b48 calls base0x1402c3940,not0x140524b60. Base processor at0x1402c3baa..c08 calls controller+738(head),+768/770(damage),then+780,+788,+790. Current Lotus vtable binds these last slots to0x14102d2f0,0x1411ff680,0x1412dc050. They are separate from+100 completion path. Capture reveals no direct call to0x14179b840 in those base/slot paths;callback/queue-to+100 notification is not established. This is a precise remaining authority join,not proof of suppression. Authoritative hit handling cannot be replaced with the local/client path merely because both consume the same damage struct.

Caveat on exploratory disassembly: named raw regions such asauthority-receiver-tail.json were initially requested from an interior byte to inspect the tail;its first decoded instruction is misaligned and is not evidence. Conclusions use verified instruction boundaries from0x140d419e0 onward,matching predecessor full capture. No numeric claim relies on the malformed first instruction.
