# Zymos candidate filter and actual carrier creator callback, 2026-10-30

Production/source freeze respected: only this new case directory written. Preserved client SHA256 eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d, Packages SHA256 00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06; declared snapshot2026.10.22.13.12. No running process/game used.

## Actual classes and defaults

Hash-pinned raw package ancestry gives EmbedDeathKillClusterProj -> /Lotus/Types/Game/ClusterBombProjectile; guided child -> /EE/Types/Engine/GuidedProjectile. The real carrier table is14226ff00, creator slot778 is1412ffd10 ->1405699b0, registration slot10 is140e4e1e0. Existing progress note tables1422c2128 and1423c9e28 are GroundAlignedGuidedProjectile and StickyGuidedProjectile subclasses, respectively, not ClusterBombProjectile. Their inherited crit path is related, but they should not stand in for the exact carrier identity.

Carrier constructor141babfb0 writes table14226ff00 and qword[+1780]=0 at141bac05a. Actual original-byte execution, with only base Projectile ctor stubbed and destination prefilledff, confirms SeekDistance0, SeekUseClusterArc(+1784)0, SeekRandom(+1785)0, SeekThroughWalls(+1786)0. Serializer1401250cd binds these names/offsets. Current raw carrier overrides SeekDistance20, ClusterArc100/Shift15, and does not override the three seek flags. Therefore default selection is sequential, LOS-enabled, and NOT restricted by the cluster launch arc. Do not infer host exclusion merely because cluster launch directions point upward.

## Candidate identity and filtering

Actual filter1412d9b60..1412da195 takes carrier, output vector, direction. It contains no candidate==originalHost comparison, no per-host blacklist, and no unique-target removal after assignment. Native predicates reject nonpositive encrypted HP(+50c), state byte518, matching faction(candidate688 vs carrier778), optional angular miss, and raycast occlusion. SeekDistance20 is supplied into the region avatar query; no host argument is passed in its query call signature. Unknown avatar/helper flag behavior is retained as fixture control, not renamed as a proven gameplay state.

11original-byte cases in probe.py: eligible living hostile candidate retained with LOS clear; HP0/dead flag/same faction/occlusion rejected; ThroughWalls skips LOS rejection; angular gate comparison rejects only when enabled; toggling the fixture raycast-ignore handle does not create an identity rejection. The region enumeration itself is a controlled one-candidate stub, so this does not prove every map/geometry includes the original victim in its region query. It proves that if a surviving original victim is in the candidate list and passes those predicates, this filter does not remove it because it was the host. Dead original hosts fail the ordinary HP/state predicate.

## How often can one target be assigned?

Original14121a5af..14121a652 executed for0/1/2/3 candidate pools, both sequential and LCG paths.0pool -> no target setter.1candidate -> same actor passed to child virtual5d0 on each of5invocations, with part selector6; no uniqueness restriction. Sequential2pool -> A,B,A,B,A;3pool -> A,B,C,A,B. Both random and sequential1pool yield A,A,A,A,A. This closes target assignment reuse only: five invocation harness is NOT by itself proof that the weapon emitted5children. Native raw carrier NumClusterProjectiles1 must still be combined with Lua creation/count overrides from prior source work. Neither assignment nor a target setter proves arrival, five impacts, radial overlap, or5x333damage.

## Creator callback queries

creator_order.py executes original140e4e1e0 registration, original1405efa30 setter, actual callback functor dispatch/14045add8 leaf, true carrier vtable778->1412ffd10->1405699b0. It counts actual CC/CD query call IDs at1401413d0, while the query's bucket arithmetic remains the earlier independent24case proof.

Registration before first source: register produces0queries; first W setter queriesf4/f8 once each; sameW setter adds0; changedW2 adds onef4/f8 pair. Source before registration: firstW setter0 because notifydisabled; registration itself0; sameW setter0; changedW2 adds onepair. Thus registration is not a retroactive source query, and same-handle Lua SetCreator cannot be counted again. Two query calls are two different fields, not two CC or two CD applications.

Full gameplay carrier query count remains unresolved because actual CreateEntity startup ordering of virtual10 registration versus source708 assignment has not been fully followed. This is a specific static-analysis gap, not a claim that only live tests can answer it. Next route: actual ClusterBomb factory141babfb0 -> region CreateEntity path, find virtual10 dispatch relative to708 setter/property replication. Generic CreateParams initializer141261710 is a leaf copying params18->context8 (progenitor) and does not touch projectile708; do not conflate that with creator crit notification. Old automatic unwind dump141261580 does NOT cover the requested141261710 leaf; exact bytes separately captured141261710-exact.asm.

Existing cluster child order14121a3c8 sets creator before copies14121a54d(CC)/14121a55c(CD), preserving prior finding: initial child's own query can be overwritten by copied carrier buckets, and transfer then queries again. Whole carrier creation must close before any final exponent/query count is admitted.

## Reproduction

python .local/delivery/ranged-implementation-20261029/root/zymos-target-filter-20261030/probe.py
python .local/delivery/ranged-implementation-20261029/root/zymos-target-filter-20261030/creator_order.py

Both execute the hash-gated preserved EXE and only write case evidence. They explicitly list region/LOS/angle/query scaffolding. No production changes or additional default child damage admitted.
