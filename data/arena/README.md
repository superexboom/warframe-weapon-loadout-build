# Arena scene package

`catalog.json` is the map/asset allowlist and provenance manifest. All JSON assets use deterministic gzip (`mtime=0`), each compressed and decompressed SHA-256 recorded in the catalog. The initial `corpus-ship-defense` authored tile is from local client2026.10.28.09.54; this is not a generated mission runtime capture.

Reimport audited artifacts:

```powershell
python tools/import_arena_scene.py --source <audited-arena-demo-directory>
```

The importer is standard-library only. It reads scene.json, navigation.json and visual-map files, never the game cache. Scene collision preserves original CSG/native NAV-floor barriers and adds a bounded static regular-wall triangle batch. Decorations, doors, pillars and guessed bounding-box solids are excluded. Every admitted triangle is sourced; candidate walls blocking native portal body routes are vetoed. This remains a visual/NAV proxy, not authoritative BSP. Native-derived and custom movement policy qualifications remain explicit. The weapon-geometry file is separately owned and is not overwritten by scene imports.

Python API (`wfarsenal.arena_scene`):

- `load_scene(map_id="corpus-ship-defense", native=True)` uses optional `wfarsenal.wfcore.SpatialIndex`, with standard-library BVH fallback.
- `scene.nodes/points`: XYZ tuples; graph/incoming contain directed Edge objects.
- `search(start, profile="player", reverse=False)`: SearchResult.d/prev/edges; reverse uses incoming graph with the original directed edge cost.
- `path/route(start,goal,profile)`: ordered Edge list; unreachable returns[]. Profiles: player, enemy, walking, drone. Only explicit enemy edges can be used by enemy/walking; drone follows the same geometry graph at5 source units/s.
- `raycast/first_hit(origin,direction,maxdist)`: RayHit or None; direction normalized internally, hit.t/distance is source distance. `trace_segment(a,b)` excludes tiny endpoint contacts; `visible` is boolean.
- `all_hits` returns sorted triangle hits, including coincident faces. This does not infer closed solids or penetration thickness; material/solid qualification remains unresolved.
- `check_motion(points,ground_step=False)`: sampled body-rail segments, not full capsule physics. For stairs ground_step checks the higher tread before horizontal motion; caller enforces supplied step/support policy.
- `ground_support(position,max_drop=2,max_rise=.5)`: downward proxy support ray only.
- `asset_bytes(map_id,name)` returns `(gzip_bytes,"application/json","gzip")` for HTTP Content-Type/Content-Encoding; `load_asset` provides decompressed dict. Names allowlisted by catalog: scene, navigation, visual-map, visual-map-collision-candidates.

Source-only verification was run with native=False: exact floor ray, two stacked deck nearest/all-hits behavior, forward/reverse enemy route-time parity and all native body-height portals unaffected by newly admitted walls. Native `cargo check` passed with CARGO_BUILD_JOBS=2; binary rebuild/parity test is delegated to the coordinated build. One necessary parity regression was appended to existing tests/test_native_core.py.

Root resolution uses `WF_RIVEN_ROOT`, then PyInstaller `sys._MEIPASS`, then the source-tree root. `list_maps()` returns map metadata with `default` flags. Asset names accept `scene`, `scene.json`, and `scene.json.gz` equivalents (same for visual-map/navigation), always catalog allowlisted.

`load_scene` caches expensive geometry. **Each sequential job must call `scene.reset_runtime()` before starting** to clear disabled links and metrics. Concurrent jobs must pass their own `disabled=set()` to `search` and keep metrics/job route state local; do not mutate the cached graph/raw/source metadata. Calling reset while another job is active is not isolation.

## Source EnemySpecs and node associations

`enemy-specs.json.gz` contains25 audited groups:21 current ground-node references,1 excluded Archwing source, and3 retained legacy selectable groups without a current matching-node reference.22 groups have ordinary runnable targets. Dropship EventResources are retained as source records and are never flattened into normal ground enemies. Nested/unsupported agents and Avatar paths absent from the frozen target catalog remain excluded with reasons.

Rows retain source agent/tier/probability/cap/weaponOverrides and declaring-type provenance. STANDARD avatar selection uses exact ancestor resolution. Optional scenario weighting normalizes positive runnable rows within the user-selected tier; it does not claim native observed spawn frequency or exact runtime tier progression.

### What source tier means

A source `tier` is an integer grouping/selection label on each EnemySpec row, not a wave number, enemy level, rarity or reward rotation. Current GrineerDefenseA has0-4; CorpusSquadDefenseB has0-4 plus9; CorpusShipPurgatorySquad uses90/95. Different rows of the same agent can have different tier/weight/cap. Current WaveDefend bytecode contains tier alongside enemySpec, probability, maxSimultaneous, mergeSymbol and spawn-schedule generation. This supports a source spawning partition; the full Director rule selecting tier from wave, level, elapsed time and mission state has not been recovered. Do not label tier0 as wave1 or tier3 as level3.

For example, GrineerDefenseA tier0 has6 raw rows and probability sum2.750000021; its tier3 has6 rows and sum0.425000013. CorpusSquadDefenseB tier9 has11 rows, each probability1, with separate simultaneous caps. These coefficients are not unconditional enemy composition percentages. The arena's explicitly selected-tier positive runnable-weight normalization and cap0-as-unlimited policy are workload choices. A node's exact primary/extra EnemySpec association does not establish that it uses every listed tier, or that a selected tier matches its current live mission phase. Source tier and the separately selected enemy level remain separate controls.


`mission-coverage.json` and catalog enemySpecSources join strictly consecutive current SolarMap MissionInfo fields: Proc, primary EnemySpec, advanced-spawner array, VIP agent, extra EnemySpec. This avoids absorbing unrelated hidden mission records. Each group carries Chinese names, missions/mapIds, source-match status, selectionEnabled and unsupportedReason. Same-map different-faction groups remain separate.

Rebuild explicit node-referenced groups with the existing importer using `--enemy-specs-only --mission-coverage data/arena/mission-coverage.json --packages-bin <Packages.bin_H> --enemy-specs-source <case>/evidence/spawn/enemy-specs.json`, then rerun import_arena_missions.py for the metadata join. Original enemy data probabilities and caps are not retuned by that join.

## Scoring cache isolation

`wfarsenal.cache_identity.score_source_bytes` provides narrow, fail-closed pre-arena identity compatibility. All existing score input files still participate in the legacy digest. Only app.py and parallel.py may map to exact pinned HEAD source bytes, after AST reversal of reviewed arena functions/routes/MIME support or external-slot scheduling hooks and complete equality of all retained source. Unknown statements, actual scorer changes and ordinary scheduler changes fall back to raw source bytes and invalidate the cache. Runtime data/arena assets and dedicated arena modules remain outside score input identity. This does not mask unrelated Python changes.

`score-identity-baseline.json.gz` is pinned by SHA256 in cache_identity.py. `score-identity-compatibility.json` records the67 actual dependencies, normalized byte hashes, proven pre-arena identity and unchanged old cache evidence. The current old cache identity differs from the reconstructed HEAD baseline, so **no unsafe cache identity rewrite was performed**; unmatched entries remain rejected. An original-byte backup was saved under .local/cache/riven-analysis-statics.pre-arena-identity-*.json. Scores and cached numeric entries were not edited. Arena-only updates can continue using an otherwise matching pre-arena cache; changed actual score dependencies still invalidate it.

## Second defense template

Map `grineer-galleon-defense`: source GrnDefenceTwo from current GrineerGalleonDefense Proc; Hydron/Helene shared-template candidates, not claimed current Arbitration roster.1653 NAV faces/192 authored spawn points/191 player-reachable candidates;40 source baked-art+CSG shared GLBs with50 exact transforms.6268 CSG+NAV proxy collision faces.40 ordinary supported step edges plus60 separately player-only arcs. Start `(0,4.3,0)` lies on isolated4-face platform: enemies cannot reach it, explicitly retained; player leaves platform to pursue. No ordinary-enemy ballistic jumps. Four compressed assets total about4.05MB. Original raw source hashes/alias evidence and parser qualifications are embedded in scene/catalog. Generic raw importer is implemented in tools/import_arena_scene.py; no full-cache unpack, no source textures or invented collision solids.

## Mission and map coverage

`mission-coverage.json` joins official English/Chinese ExportRegions labels to bounded length-prefixed node/Proc references in the installed SolarMap and exact current Proc level dependencies. Each node retains planet, mission type, level-resource candidates, matched imported maps, missing maps and source hashes. This is a candidate-template inventory, not a recovered procedural selector or current server Arbitration whitelist. Different nodes can share a tile; one node can reference multiple variants.

The first delivery's eight tiles were a partial import, not the complete Defense/Interception set. The new full inventory also records excluded Archwing and distinct Mirror Defense/1999 variants instead of silently conflating them with standard Defense. See the current manifest summary and the in-app coverage table for available, partial and missing nodes. `map-coverage.json` retains the original eight-map import history and format evidence; it is not the current star-chart inventory.

Rebuild node labels and coverage after adding a map:

```powershell
python tools/import_arena_missions.py --source-root <case>/work/spawn/missions --solar-map <case>/work/spawn/raw/Debug/Lotus/Types/Game/SolarMap/OriginSolarMapRedux_H --cache-dir <current Cache.Windows>
```

The offline inputs are hashed. `--refresh --exporter <path>` reacquires official bilingual ExportRegions and missing current Proc headers. The tool updates only map mission metadata and the mission coverage manifest, preserving geometry hashes.

## Source polygon NAV support

`corpus-outpost-defense-one` is now available.2521 source n-gons expand to3376 runtime triangles only after exact source ring ordering, simple boundary, Newell plane tolerance0.002, positive3D normals, projected signed-area conservation and exact boundary/incidence checks.855 internal split edges are explicitly distinguished from3203 native shared-source portals. `nav.sourcePolygons` and `nav.fromFaceMap` preserve original face identity; existing runtime triangle API remains unchanged. SourceDefenseThree still has no0.nav and stays blocked. At the initial polygon-import milestone, the catalog reached8 authored maps; those entries include `nameZh`, `architectureFaction`, `templateLabelZh`, with architecture faction explicitly separate from mission enemy selection.


## Visual completeness repair

The initial generic raw importer assembled only tile-local meshes. This omitted shared floors, stairs and other architecture; it was not evidence that those objects were absent from the game. The completion pass now resolves full explicit and inherited Mesh references, including actual `.tmesh` terrain, and uses exact LEVEL transforms. It preserves original mesh IDs used by the collision-candidate sidecar. Source meshes, material groups, simplified material colors, source hashes and an instance omission ledger are included.

```powershell
python tools/import_arena_scene.py --complete-visuals --case-root <case> --cache-dir <current Cache.Windows> --exporter <path> --packages-bin <Packages.bin_H>
```

`metadata.visualCoverage` distinguishes successfully assembled instances, missing resources, unsupported rigged geometry and excluded authored hidden/dynamic/attached states. `metadata.worldBounds` covers real visual geometry; the viewer defaults to no clipping and lets the user choose a section height. Switching to detailed geometry does not substitute NAV for missing visual floors. NAV/collision remain separate from display geometry; source textures and dynamic object animation are not reproduced.

A shared resource extraction cache avoids repeatedly decoding identical structural meshes between maps. Browser rendering shares indexed geometry across instance groups, and switching maps releases GPU geometry, instance buffers and materials.


## Degenerate source NAV face

The ice-planet template contains one legitimate serialized but geometrically degenerate face: source face4953 has three exactly collinear vertices. The importer now quarantines only a valid ring whose vertices are exactly collinear, retaining all original vertices, source face IDs and rejected native portals. It does not replace that face, reconnect the two sides or generate step/jump shortcuts through its adjacent faces. Self-intersecting/nonplanar/unsupported source geometry is still rejected. `nav.sourceFaceToTriangles`, `quarantinedSourceFaces`, `excludedSourcePortals` and `quarantineDerivedLinkExcludedFaces` record the decision.


## Navigation runtime and fixed stance

Arena-world-v2 uses current directed ground-graph strongly connected components for unreachable staging, including admitted stairs/steps. Opponents approach source-qualified visible staging nodes; reverse flows are reused. A crowded moving actor can make a short supported, wall-checked and continuously separated detour from its actual feet. It cannot teleport to its previous graph node. If a target's floor is unreachable but a legal firing position is reachable, the player can use that firing position without inventing an inter-component edge.

Fixed-position requests explicitly identify a source triangle and XYZ point. Validation allows small vertical projection onto that triangle only, with support and body-clearance checks. The mode suppresses all player navigation and returns ordinary-enemy spawn reachability as a qualification, not a promise of universal line of sight. Missing native offmesh/ladder information remains an accuracy limitation.


## Source-qualified open doors

`door-geometry.json.gz` is a separate versioned asset (`arena-source-doors/v1`) with compressed/decompressed SHA256 in `catalog.doorGeometry`. Every current map has an audit record. Door admission joins a real NpcDoorHint, authored scope, moving or attached leaves, trigger, explicit dimensions and compatible doorway anchors; unconfirmed variants stay in rejectedHints. Each admitted crossing links real opposite-side NAV faces and passes bounded ground/body checks. The finite threshold slab follows source door anchors. No ordinary wall triangle is removed or globally ignored.

Movement is always open by scenario policy. `doorSight=open|closed` applies separately to finite source aperture planes for sight/hit/proc-neighbor/protection queries. Ground/support/body-motion queries remain open. Source state is not a claim about native lock animation or faction permissions. Job-local query copies prevent UI standing-point validation from changing a running world's door state or disabled links.

`visual-ground-geometry.json.gz` contains only exact source floor/stair triangles used as witnesses for admitted local ground connections, with mesh hashes and triangle IDs. It is not a wholesale conversion of decoration to collision. Both sidecars are recorded in exported result sources.

Rebuild with `tools/import_arena_scene.py --source-doors --case-root <case> --packages-bin <Packages.bin_H>` and `--source-ground` for the bounded witnessed ground pass. Complete raw source geometry is kept in the research case, not copied into the runtime as unclassified collision.


## NPC traversal sidecar and source Hover classification

`npc-gap-geometry.json.gz` (`arena-npc-gaps/v1`, `catalog.npcGapGeometry`) has two distinct route kinds. `source-surface-walk` uses fully supported existing scene CSG/NAV triangles, with scene/hash and collision triangle provenance; it adds no collision and is always eligible. `npc-short-gap` is an explicit conservative scenario approximation, enabled only for the `enemy-gap` runtime profile; strict `enemy` and player routes exclude it. Source NPC jump capability does not prove these endpoints or timing are native offmesh. Rebuild with `python tools/import_arena_scene.py --source-npc-gaps --packages-bin <Packages.bin_H>`; `--visual-map-id` limits a repair.

EnemySpecs `movement` metadata comes from resolved locomotion type/follower and Avatar physics attributes (`Flyer=1`), including per-variant evidence. Only `smallHoverCompatible` rows use the current small flying proxy. Classification does not imply arbitrary free flight or affect Arbitration-specific gameplay. The original source still uses a Ground pathfinder. Re-running `import_enemy_specs` regenerates these fields.


GasCity Door4969 uses `gas-door4969-source-route.json`, a reviewed source-triangle recipe. Reproduce with `--source-ground --visual-map-id corpus-gas-city-defense --ground-surface-face 2062 --ground-support-entity 4955 --ground-support-entity 4956 --ground-support-entity 2681 --ground-support-recipe data/arena/gas-door4969-source-route.json`, plus the extracted `--case-root` and `--packages-bin`. The importer rechecks static physics, mesh SHA and exact source triangles; only dense-route witnesses are admitted. The two Trim entities with disabled physics are not included. The route uses the established center-foot support policy, not a claim of full-footprint support.


`--source-npc-actions --case-root <case> --packages-bin <Packages.bin_H> --visual-map-id <map>` extends the same sidecar with transitions for admitted source-spawn islands. Continuous supported ground links remain always eligible. Airborne actions stay behind the NPC traversal scenario switch and record their own bounds and evidence separately from the original0.8m narrow-gap policy; they do not convert every player bullet-jump into enemy movement. Explicit authored JumpAction endpoint references, when available, are preserved as source identity; trajectory and timing remain scenario approximations.

The reviewed island-action pass covers `grineer-fortress-defense`, `lastwish-corpus-mirror-defense`, `corpus-outpost-defense-one`, `corpus-ice-defense`, `grineer-forest-defense`, `infested-corpus-defense`, `orokin-moon-defense` and `1999-temple-defense-underground`. Run one map per invocation. Infested Corpus additionally needs `--npc-repair-walk 1665:1667`; Moon additionally needs `--npc-action-pair 1172:1203 --npc-action-pair 1202:896`. These explicit pairs retain separate review provenance. Every action pass records `actionModelInputHashes` for its current scene, navigation, door/ground assets, Packages and LEVEL inputs; the older narrow-gap `inputHashes` remain intact.

Runtime local avoidance can reuse steep faces already admitted by its native source walk. Eligibility requires an exact hit on the verified NAV tail of the collision asset and membership in the current/planned native-walk faces. It does not alter source normals, wall collisions, step-height/body checks or user standing-point validation.


## LEVELSTATIC architecture

The visual completion importer also follows each unique `StaticLevel` resource referenced by the LEVEL. The current Temple uses `LEVELSTATIC30`, stored in AnimRetarget; its placements are absent from the normal LEVEL entity list. The reader accepts the matching 29/30 layout, validates full header/body consumption and model indices, and records source hashes, original object indices, XYZ, quaternion and uniform scale. Coordinates are already in current source/NAV units: do not apply a historical exporter half-scale conversion. Static objects reuse the ordinary mesh decoder and shared geometry instancing. Editor decal projector meshes and water/effect surfaces requiring unsupported material behavior remain in the omission ledger.

Reproduce just this correction with the existing `--complete-visuals --visual-map-id 1999-temple-defense-underground` command and source arguments above. Referenced raw static resources are reused under the research case's `work/geometry/complete-visuals/static-resources/`; no whole-cache extraction is required. `metadata.staticLevelSources` and `visualCoverage.assembledStaticLevelInstances` distinguish these resources from ordinary entity coverage. This pass does not rewrite any scene/navigation/physical collision asset.
