# Grimoire chain280 / expiry250 admission review — 2026-10-30

Case-only research. No production code, tests or imported mechanics data changed. Executable: `python .local/delivery/ranged-implementation-20261029/native-payloads/verify_grimoire_admission_review.py`. Output `grimoire-admission-review-native-results.json`: hash-pinned complete original Packages source gate,17 reused original-byte cases plus13 new cases;30 native/source cases pass. The three free-flight geometric counterexamples are explicitly analytical supplied scenes, not native world simulation.

## Admission conclusion

Both missing damage primitives are statically recoverable and real: selected chain recipient receives the AttackData-derived350*.80000001≈280 packet; valid launch expiry emits the separate250 electric radial. They are not live-only unknowns. Their unconditional addition to the current target on every shot is nevertheless unsupported. Selection and final-position overlap are inputs absent from the current positionless continuously-replaced-target model.

A legal next implementation can admit a declared spatial coverage policy or supplied scene, retain one orb identity with its launch clock, perform candidate selection afresh per attack, and evaluate expiry against the live recipient at the final orb position. Without those assumptions, keep chain/expiry excluded from default scoring while publishing their exact source contracts. This is an engine/model boundary, not a claim that only live gameplay can resolve native damage math.

| Component | Statically established | Required policy/input for score | Invalid shortcut |
| --- | --- | --- | --- |
| chain | source350*.8; source status/forced-electrocution packet;1s attack interval; first attack initially ready; per-attack identity dedup; root cap1, recursive MaxArcs2, shared budget3 | current eligible candidate(s) actually returned by the native8m root/arc query; target identities; world positions/overlap; event ordering when a kill immediately exposes a successor | unconditional280 each second on whichever target the score engine currently displays;3*2*280 on one enemy; scalar multishot copies |
| expiry | one scheduled launch+6s DieOfOldAge; source250Electricity,CC.2/CD2,SC.25999999,radius6/falloff.80000001 | surviving orb/lifecycle; final orb position; recipient overlap and distance/falloff at expiry; cover policy |250 at impact;250 six seconds after each hit; binding to first victim generation; always full250 to a replacement enemy |

## 1. Launch and lifetime

Native constructor141bddda0 initializes remaining attack clock1774=0 (executed suffix141bdde48..59). Therefore first eligible native update can attack immediately; source TimeBetweenAttacks1 is not a mandatory initial1s delay. Updater140d7fc60 requires valid owning weapon708 and projectile not dead, decrements a positive1774, resets attack dedup1798 and queries per-attack/depth budgets. Initial candidate discovery can occur before the orb directly contacts the victim.

141692c20 does the world query then filter. An empty candidate list returns before141693034..65, so an unsuccessful search does not arm a1s cooldown; the next eligible update can search again. After selected-target stage,141693034..65 arms remaining with interval+nonpositive remainder. Existing original-byte cases cover positive,zero,negative remainders. This is an update-driven scheduler; no universal six pulses or pulse exactly at6s is asserted. At the exact expiry boundary the external update/timer order matters; use a declared half-open lifetime rather than invent an extra boundary hit.

Actual launch suffix140f88871..88981: MaxLife6,variance0,positive lifetime6d8,ExplodeOnLifeExpired16d6=1 -> callback1409a8700 after6s;639 prevents a duplicate schedule. It is an orb launch clock independent of any victim's death. Expiry callback calls classDie then explicitly+7b8; normal death-property callback suppresses its own duplicate radial. Manually invoking expiry twice still emits two radials: once scheduling belongs to639/lifecycle, not solely the Die guard.

Straight uncollided declared scene speed6m/s,6s gives endpoint36m. Point recipients at0m or12m are outside radius6; one at35m overlaps. Same packet/lifetime source, different valid recipient outcomes. These are mathematical geometry counterexamples with explicitly supplied assumptions; collision slowdown,restitution,obstacles and script movement require their own supplied scene or native trajectory implementation.

## 2. Dedup and continuously replaced kill targets

Updater clears1798 per new attack via1401bc7d0. Full candidate filter140cccf60 rejects already-selected objects by weakref target identity at140ccd260..28e;1416932a8..2db appends each selected recipient. Thus a still-living same NPC gets at most one chain packet in that attack tree; it can be selected again next attack. Contact350 uses a separate prior-hit structure and cannot be equated with the chain list.

New full-filter case uses an old dedup handle to enemyA and a current candidate handle to enemyB: B survives the actual native filter. A kill-counter generation number is not itself an exclusion criterion. A source-owned orb must therefore survive target-generation changes until its own lifecycle ends; subsequent pulses may select a successor if the successor is geometrically eligible. A blanket generation-bound finite-field would wrongly drop this possibility.

The converse is also important: the synthetic next target does not automatically exist inside every native query merely because the benchmark replaces a dead target. If an explicit policy says only one recipient is exposed to a given attack tree, that is at most one280 packet for that tree. If successors become real eligible objects during recursion after a kill, native identity dedup alone does not prohibit them; remaining depth/arc/shared budget applies. Do not introduce instantaneous same-pulse multi-generation kills without modelling or explicitly declaring that exposure policy.

## 3. Candidate selection, geometry and counts

141692cf4..d39 chooses DirectHitChainLength1748 at depth0 and ArcLength174c for recursion; both raw source8. It queries weapon upgrade enum384; new original-byte counterfactual sets arc4 and confirms distinct root8/recursive4 paths. 141692d4b..dd2 derives query origin from the projectile/root entity or the recursion avatar's body/bounds position;141692dfc..e21 submits a typed world query with that origin/radius. Candidates are then filtered, measured by squared point-to-AABB distance141692f1f..f49, ordered, and trimmed.

Full140cccf60 new cases execute faction/owner compatibility, candidate invalid-state virtual6e0, ChainableTypes class records, ignore-type/dedup checks. Supplied class IDs and valid owner weakref are fixture inputs; the world query is not fabricated as universally successful. Cases show one accepted enemy retained, a friendly removed, a native-invalid candidate removed, and a previously-selected enemy removed.

New source/constructor proof: property metadata142866f78 points to mMaxDirectHits; serializer140161cc2 binds1728; constructor141bddde1 writes1 and exact resolved Grimoire source has no MaxDirectHits override. Root selection cap is1. mMaxArcs1730 has source2 and governs recursive recipient count. MaxTargetsPerAttack1758 source3 is queried into shared remaining1750;141693090..a3 decrements it before each recipient. New original-byte cases3->2,1->0,0->no recipient confirm the common budget. MaxChainDepth1718 source2 is an independent depth bound, not a damage multiplicity. Existing nativeMS proof locks one orb while updater routes upgrade queries to budgets; more budget cannot bypass a single living recipient's identity dedup.

## 4. Hit-source inheritance and remaining static work

140d7fdb4..fde8 calls the exact selected projectile+6281416373e0 using projectileAttackData4d0. This is the normal native packet builder, not a hand-authored280 secondary packet. It applies source amount stages (14116ac70 and projectile7b8) and source ownership. Updater140d7ff5c..82 additionally calls140cbc9b0 with projectile538/570 to combine the packet's CC/CD modifier buckets. Source forcedElectrocution/status are on AttackData; expiry uses distinctExplosiveAttack without that forced-proc declaration.

At141693103 the full native packet copy140c43220 preserves source handles and metadata. New full-copy+actualscalar case verifies source350 remains350, copied packet becomes280 at amount+78, copied first80 bytes/sourcehandle108/25c25d metadata remain as supplied. This proves inheritance and route-local scaling; it does not falsely interpret arbitrary supplied metadata markers as new semantic field mappings. Recursive call14169332a..33a receives the original packet, not the already-scaled child, so no .8^depth progression.

Selected chain recipient is installed into copied packet170 at14169313a..162 and delivered by140907cb0 at141693283. That dispatcher resolves current target weakref and selects native target+340 or+348 according to source/avatar authority. This supports targeting a newly selected live enemy, rather than irrevocably attributing all future packets to launch-contact victim. It does not by itself prove that every chain tick produces every ordinary direct-shot head/crit/on-hit/CO/arcane event in the existing simulator. Detailed +340/+348 consumers and dynamic buff/source snapshot timing can be resolved by further static/original-byte work; classify them as bounded or unresolved native routing, not live-only requirements.

## Minimal implementable contracts after freeze

For a declared single-recipient coverage scenario with no dynamic-buff/event uncertainty: retain orb token,launchTime,expiryTime=launch+6; initial attackRemaining0; execute native-style search/filter/dedup and remaining-budget rules; when exactly one eligible current enemy is selected, emit one source-inherited280 packet. Retain attack clock across kills, but recompute candidate inclusion for each new victim. Do not silently retarget a packet already issued to a dead old victim.

At expiry, evaluate one250 radial at orb's then-current position with radius6 and native falloff against then-live recipients, independently of initial victim generation. The source primitives and clock are sufficiently evidenced; current default lacks the spatial/lifecycle contract to guarantee any recipient. It is legitimate to expose the conditional packets now or implement an explicit coverage/trajectory mode later; it is not legitimate to merge unconditional280/250 into the frozen default.

No production admission or test edits in this pass. Only case scripts, disassembly and results under native-payloads were written.
