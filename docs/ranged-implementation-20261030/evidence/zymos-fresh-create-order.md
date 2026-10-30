# Exact Zymos Lua/CreateEntity source-registration order

This supplements FINDINGS.md and resolves its specific pending registration-order question for fresh construction. Production source remains frozen.

## Exact Lua arguments

Pinned InfUziWeapon Lua body SHA25647a343ce7d22c4948178bb11067b2532e082729b310853438a64c647ad1e7751. P3 pc106/108 NAMECALL A12,CALL B7 passes self+five user arguments: clusterType, pos, rot, r5, r5. Therefore Lua wrapper receives argument5=r5 and argument6=r5; optional argument7 is absent. This is NOT the no-owner Mandonel call shape. The native wrapper141a240b0 parses fifth141a2415d into rdi, sixth141a24181 into rsi, optional seventh defaults0, and passes all through1400ef550. That function places sixth at CreateParams+10, fifth at+18; these are distinct from projectile creator property708. Do not name both fields708 creator.

After return, Lua P3 pc110 atom a22f3ac5 maps native method table14207f330 ->1419790c0 ->carrier virtual580=140f84b40, which updates738 parent projectile from r0. P3 pc114 atom439095b8 maps table14207f340 ->141979270 ->1405efa30, which updates708 creator fromr5. P3 pc118 e287773d maps14197a960 ->140b936b0 (hit-type/damage classification member4e4), not an extra crit query. Native method-table pointers and wrappers captured in case.

## Fresh allocation and registration sequence

1. PrivateCreate140cb68f0 calls140181260 at140cb6f1f.
2. Fresh branch140181356..37b ->140d61b30 ->native descriptor factory140baf2a0 ->descriptor virtual58=14100cd70.
3. Descriptor registration14008e340 binds ClusterBombProjectile constructor141babfb0, size1790;14169a960 stores ctor atdescriptor78. Factory14100cdc1 invokes it. Base Projectile constructor140fba500 writes708empty handle,718null callback,730disabled; Cluster constructor preserves that.
4. Factory returns and type/prototype state is deserialized. PrivateCreate sets entity replication role via1413e1280 at140cb70f7 while fresh21zero. This handler dispatches carrier virtual10=140e4e1e0 at1413e1332/1359 or1413e13b1. Registration precedes later OnCreated1400f6730 at140cb72ae, then creation returns to Lua.
5. Carrier OnCreated slot1f0 is Entity base1403106d0. Its CreateParams conversion141261710 copies fifth/progenitor throughparam18 intocontext8 and handles parent attachment via90/98; this is not a708 setter. Sixth parameter also affects owner/group bookkeeping140cb72b3.., after registration. Neither argument's presence selects a source-before-registration branch on this fresh path.
6. Lua parent assignment then explicit creator assignment occur after registration. Enabled first creator transition queriesf4/f8 once each; same-source repeats do not query again. Parent setter's additional141548510 context has queries127/12a/dd and a virtual908-derived flat CC add, but no further ordinaryf4/f8 query in that function. Do not silently treat it as a second ordinary CC/CD bucket application.

## Concrete conditions, not a universal role assumption

Registration ordering is resolved; callback enable is role-dependent. verify_create_order.py executes original1413e1280, actual ClusterBomb virtual10 registration, then actual SetCreator/callback;10explicit numeric cases pass. ObjectType replication enum initializer140022570 confirms UNDEFINED0,REPLICATED1,AUTONOMOUS2,SERVER_ONLY3,CLIENT_ONLY4. The package's ProjectileReplication is a separate enum, so its string is NOT silently equated with ObjectType1. Omitted Lua arg7 selects class virtual80 getter14117a9e0: base class flag bits plus entity2fa mask can choose replication1/2. Both tested.

For regionMode!=2, global role flag0 resolves entity20, flag1 resolves10; both enable callback and produce onef4/f8 pair. For regionMode2 with replication1, globalflag0 yields entity1 and callbackdisabled ->zero pair; globalflag1 enables the same entity1 callback, or relay-condition yields entity2; onepair. For replication2, the controlled regionMode2 cases yield entity4 and onepair. Inputs and exact globals are saved in create-order-branches-original-bytes.json. These are original-code feasible branches; no claim every matrix combination is a live-game startup state. Lua's earlier authority predicate atomce228771 ->141909cf0 tests region21lowbits7; that alone does not identify every unrelated global/regionMode relation, so this report does not relabel all matrix cases as host/client.

## Last remaining boundary

For fresh path and enabled source transition: ordinary carrier f4/f8 query once each is closed. This does not yet prove a universal live-game effective crit formula. Generic pooled-object retrieval1401812c3..342 can bypass fresh construction when engine global/type-pool conditions permit. Whether this specific carrier type ever enters that pool, its cleared708 state, and applicable actual startup-role branch are still static pending. They do not reverse the fresh constructor order. The existing child copy ordering still overwrites initial child buckets before transfer adds its own query. Keep original24case bucket arithmetic as a primitive; do not convert this report into5x333 default damage, flight overlap, or final gameplay CC/CD.

## Reproduce

python .local/delivery/ranged-implementation-20261029/root/zymos-target-filter-20261030/verify_create_order.py

It reuses the hash-gated original registration/setter harness, validates raw Lua five-argument shape, and writes case-only JSON. Full allocation/serialization is statically traced, not falsely claimed as emulated. Registration/role dispatch and actual callback/setter execute original bytes.
