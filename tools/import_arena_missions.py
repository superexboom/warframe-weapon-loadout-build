"""Join official star-chart labels to current installed SolarMap/Proc resources.

Example (offline after source acquisition):
 python tools/import_arena_missions.py --source-root <case>/work/spawn/missions \
   --solar-map <case>/work/spawn/raw/Debug/Lotus/Types/Game/SolarMap/OriginSolarMapRedux_H \
   --cache-dir E:/warframe/Warframe/Downloaded/Public/Cache.Windows

--refresh downloads official hashed ExportRegions en/zh and extracts only the
45-node SolarMap's selected Proc headers with an explicit local exporter.
No tile meshes, navigation or visual assets are modified. Catalog edits own
only maps[*].missions and top-level missionCoverage/enemySpecSources metadata.
"""

from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import lzma
import re
import struct
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "portable-arena-mission-coverage/v1"
CANDIDATE_RULE = "Proc dependency closure; top authored level names containing Defense/Defence/Defend/Interception, excluding spawn/exit/prefab/connector/prop families. Not a decoded procedural room selector."


OFFICIAL_ARBITRATION_ADDITION = {
    "url": "https://www.warframe.com/en/patch-notes/pc/37-0-0",
    "date": "2024-10-02",
    "title": "Update 37: Koumei & the Five Fates",
    "section": "ARBITRATIONS ADDITIONS / Endless Mission Types Added",
    "nodeIds": ["SolNode450", "SolNode719"],
    "claim": "Mirror Defense at Tyana Pass and Munio was added to Arbitration Alerts.",
    "downloadSha256": "d70b38fbdf3c375831c6811fb00f6e1c52a339db0e4a4d6719abb4518f693bee",
    "evidenceType": "historical-official-affirmative-announcement",
    "currentWhitelistVerified": False,
}
REFERENCE_SITE_SNAPSHOT = {
    "url": "https://arbi.wf.wiki/maps/manifest.json",
    "downloadSha256": "e436210687bd3a09b21ba63ed1fa68ae725ca84b1aa4ca26bebcb8e9a5d7ca96",
    "retrievedDate": "2026-11-16",
    "authority": "community-map-asset-manifest",
    "counts": {
        "nodes": 43,
        "defense": 27,
        "interception": 13,
        "mirror": 2,
        "salvage": 1,
        "packs": 53,
    },
    "historicalComparison": {
        "ourNodeCount": 45,
        "matchingNodeCount": 42,
        "notListedNodeIds": ["SolNode907", "SolNode742", "SolNode858"],
        "additionalNodeIds": ["SolNode167"],
    },
    "qualificationEvidence": False,
    "warning": "Reference inclusion or omission does not establish official Arbitration eligibility.",
}


def arbitration_qualification(node_id):
    """Separate a historical official addition from a verified live whitelist."""
    if node_id in OFFICIAL_ARBITRATION_ADDITION["nodeIds"]:
        return {
            "status": "officially-added",
            "eligible": None,
            "date": OFFICIAL_ARBITRATION_ADDITION["date"],
            "url": OFFICIAL_ARBITRATION_ADDITION["url"],
            "currentWhitelistVerified": False,
            "evidenceType": OFFICIAL_ARBITRATION_ADDITION["evidenceType"],
            "reason": "Official Update 37 added this Mirror Defense node on October 2, 2024; the current server rotation whitelist was not verified.",
        }
    return {
        "status": "unverified",
        "eligible": None,
        "currentWhitelistVerified": False,
        "reason": "No authoritative current server node whitelist extracted; missionIndex and official drop table are not Arbitration qualification.",
    }


ENEMY_SPEC_NAMES_ZH = {
    "GrineerDefenseA": "Grineer 舰船防御编组 A",
    "GrineerDefenseAAsteroid": "Grineer 小行星防御编组 A",
    "GrineerShipyardsDefenseA": "Grineer 船坞防御编组 A",
    "InfestedDefenseA": "感染者防御编组 A",
    "InfestedDefenseB": "感染者防御编组 B",
    "CorpusSquadDefenseA": "Corpus 防御编组 A",
    "CorpusSquadDefenseB": "Corpus 防御编组 B",
    "CorpusGasRemasterDefenseSquad": "Corpus 木星天然气城防御编组",
    "SeaLabGrineerDefenseA": "Grineer 天王星海底实验室防御编组 A",
    "InfestedInterceptionA": "感染者拦截编组 A",
    "InfestedInterceptionB": "感染者拦截编组 B",
    "CorpusDropship": "Corpus 运输艇事件编组（非普通地面敌人）",
    "CorpusDropshipAmbulas": "Corpus Ambulas 运输艇事件编组（非普通地面敌人）",
    "CorpusGrineerDesertMix": "Corpus／沙漠 Grineer 混合编组",
    "CorpusShipPurgatorySquad": "Corpus 飞船特殊 Purgatory 编组",
    "CorpusShipSquadDefenseB": "Corpus 重制飞船防御编组 B",
    "DesertGrineerDefenseA": "沙漠 Grineer 防御编组 A",
    "EntratiMirrorDefenseSpec": "英择谛实验室镜像防御编组",
    "GrineerDefenseForest": "Grineer 地球森林防御编组",
    "GrineerDefenseFortress": "Grineer 赤毒要塞防御编组",
    "GrineerMoonDefense": "Grineer 月球防御编组",
    "OrokinDefenseSquad": "Orokin 虚空防御编组",
    "OrokinDefenseSquadB": "Orokin 虚空防御编组 B",
    "SpaceGrineerDefenseC": "Grineer 空战编组 C（范围外）",
    "DisruptionScaldraSpec": "1999 Scaldra 节点编组（源类型名 Disruption）",
}


def solar_enemy_specs(data, proc_offset, proc_path):
    """Decode only the consecutive native MissionInfo resource prefix.

    Proc and nonempty resources serialize as u32 byte length, ASCII path,
    u32 resource trailer. Empty resource is one u32 zero. Following Proc:
    enemySpec, u32 advanced-spawner count, that many resource references,
    vipAgent, extraEnemySpec. This prefix is validated on all45 selected
    nodes; no nearby-string scan or faction-based inference is used.
    """

    def read_resource(offset, family=None):
        if offset + 4 > len(data):
            raise ValueError("Truncated MissionInfo resource length")
        size = struct.unpack_from("<I", data, offset)[0]
        if size > 1024 or offset + 4 + size + (4 if size else 0) > len(data):
            raise ValueError("Unbounded MissionInfo resource")
        value = data[offset + 4 : offset + 4 + size].decode("ascii")
        if size and (
            not value.startswith("/Lotus/") or family and not value.startswith(family)
        ):
            raise ValueError("Unexpected MissionInfo resource: " + value)
        trailer = struct.unpack_from("<I", data, offset + 4 + size)[0] if size else None
        if size and trailer != 0:
            raise ValueError("Unknown MissionInfo resource trailer")
        evidence = dict(
            lengthOffset=offset,
            valueOffset=offset + 4,
            byteLength=size,
            resourceTrailer=trailer,
        )
        return value, offset + 4 + size + (4 if size else 0), evidence

    after = proc_offset + len(proc_path) + 4
    primary, after, primary_evidence = read_resource(
        after, "/Lotus/Types/Game/EnemySpecs/"
    )
    count_offset = after
    count = struct.unpack_from("<I", data, after)[0]
    after += 4
    if count > 64:
        raise ValueError("Unbounded MissionInfo advanced-spawner array")
    for _ in range(count):
        _, after, _ = read_resource(after, "/Lotus/Types/Enemies/AdvancedSpawners/")
    _, after, _ = read_resource(after)  # vipAgent, not an enemySpec
    extra, after, extra_evidence = read_resource(after, "/Lotus/Types/Game/EnemySpecs/")
    refs = (
        [dict(field="enemySpec", path=primary, **primary_evidence)] if primary else []
    )
    if extra:
        refs.append(dict(field="extraEnemySpec", path=extra, **extra_evidence))
    return dict(
        paths=[r["path"] for r in refs],
        references=refs,
        primaryPath=primary or None,
        extraPath=extra or None,
        qualification="validated-consecutive-MissionInfo-enemySpec-and-extraEnemySpec-resource-fields",
        prefixEndOffset=after,
        advancedSpawnerCount=count,
        advancedSpawnerCountOffset=count_offset,
        runtimeTierSelectionVerified=False,
    )


def enemy_spec_sources(nodes, spec_file):
    """Describe only actual selected-group references, never same-map factions."""
    selected = json.loads(gzip.decompress(spec_file.read_bytes()))["specs"]
    out = {}
    for group in selected:
        path = group["path"]
        missions = []
        for node in nodes:
            if path not in node["enemySpecPaths"]:
                continue
            fields = [
                r["field"]
                for r in node["enemySpecEvidence"]["references"]
                if r["path"] == path
            ]
            missions.append(
                {
                    **{
                        key: node[key]
                        for key in (
                            "nodeId",
                            "nodeName",
                            "nodeNameZh",
                            "planet",
                            "planetZh",
                            "missionType",
                            "missionTypeZh",
                            "sourceProc",
                            "inScope",
                            "mapIds",
                            "arbitrationQualification",
                        )
                    },
                    "sourceFields": fields,
                }
            )
        map_ids = sorted(
            {map_id for mission in missions for map_id in mission["mapIds"]}
        )
        short = path.rsplit("/", 1)[-1]
        out[path] = dict(
            path=path,
            nameZh=ENEMY_SPEC_NAMES_ZH[short],
            nameEn=short,
            runnable=bool(
                group.get(
                    "runnable", any(e.get("runnable") for e in group.get("enemies", []))
                )
            ),
            scopeIncluded=group.get("scopeIncluded", True),
            selectionEnabled=bool(
                group.get(
                    "runnable", any(e.get("runnable") for e in group.get("enemies", []))
                )
            )
            and group.get("scopeIncluded", True),
            sourceStatus=group.get("sourceStatus", "legacy"),
            unsupportedReason=group.get("unsupportedReason"),
            unsupportedSourceFields=group.get("unsupportedSourceFields", {}),
            tierAvailability=group.get("tiers", []),
            nameQualification="curated-Chinese-display-label-for-source-group-not-official-localization",
            sourceMatchStatus=(
                "node-reference-confirmed" if missions else "no-selected-node-reference"
            ),
            missions=missions,
            mapIds=map_ids,
            rawTiers=group.get("rawTiers", []),
            tierSelection=dict(
                status="source-defense-cumulative-or-custom",
                runtimeNodeTierVerified=False,
                reason="WaveDefend cumulative admission, quota and boss cadence are recovered for explicit Defense profiles. Node references do not choose runtime MissionInfo or an Interception director.",
            ),
            qualification="exact-current-SolarMap-MissionInfo-reference; same-tile or same-faction similarity is never a group match",
            noMatchReason=(
                None
                if missions
                else "No exact reference among the45 indexed Defense/Interception nodes. Group remains an optional workload source; no source planet/node is inferred from its name or matching geometry."
            ),
        )
    return out


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch_regions(source, lang):
    """Index may end in a malformed LZMA trailer; retain independently valid lines.

    Hashed JSON itself must download completely and parse; a partial index is
    never used as content evidence, only to locate the exact manifest filename.
    """
    url = "https://origin.warframe.com/PublicExport/index_" + lang + ".txt.lzma"
    raw = urllib.request.urlopen(url, timeout=30).read()
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    recovered = bytearray()
    for value in raw:
        try:
            recovered.extend(decoder.decompress(bytes([value])))
        except (lzma.LZMAError, EOFError):
            break
    name = next(
        line.strip()
        for line in recovered.decode("ascii").splitlines()
        if line.startswith("ExportRegions_" + lang + ".json!")
    )
    manifest = "https://content.warframe.com/PublicExport/Manifest/" + name
    data = urllib.request.urlopen(manifest, timeout=30).read()
    parsed = json.loads(data)
    if not isinstance(parsed.get("ExportRegions"), list):
        raise ValueError("Invalid ExportRegions payload")
    output = source / ("ExportRegions_" + lang + ".json")
    output.write_bytes(data)
    return dict(
        url=manifest,
        file=output.name,
        sha256=digest(output),
        bytes=len(data),
        retrievedUtc=datetime.now(timezone.utc).isoformat(),
        indexUrl=url,
        indexTrailerComplete=decoder.eof,
    )


def lp_strings(data):
    """Only accept resource strings with matching preceding LE length."""
    out = []
    for m in re.finditer(rb"/Lotus/[A-Za-z0-9_/.-]+", data):
        if m.start() < 4:
            continue
        size = struct.unpack_from("<I", data, m.start() - 4)[0]
        value = data[m.start() : m.start() + size]
        if (
            5 <= size <= 1024
            and len(value) == size
            and re.fullmatch(rb"/Lotus/[A-Za-z0-9_/.-]+", value)
        ):
            out.append(dict(offset=m.start(), value=value.decode("ascii")))
    return out


def solar_nodes(data, regions):
    """Exact LP node+localization anchor; choose first Proc field after it.

    The SolarMap native schema is not claimed decoded in full. Hidden records
    can follow a public node; the first Proc matches the node's mission. Stop at
    that field rather than absorbing every subsequent hidden-record reference.
    """
    rows = []
    for q in regions:
        if q.get("missionIndex") not in (8, 13):
            continue
        key = q["uniqueName"].encode()
        needle = struct.pack("<I", len(key)) + key
        hits = []
        for match in re.finditer(re.escape(needle), data):
            off = match.end()
            if off + 4 > len(data):
                continue
            n = struct.unpack_from("<I", data, off)[0]
            tag = data[off + 4 : off + 4 + n]
            if tag.startswith(b"/Lotus/Language/") and len(tag) == n:
                hits.append((match.start(), off + 4 + n, tag.decode()))
        if len(hits) != 1:
            raise ValueError(
                "Expected one localization-anchored SolarMap node "
                + q["uniqueName"]
                + ": "
                + str(len(hits))
            )
        start, after, tag = hits[0]
        fields = lp_strings(data[after : after + 4096])
        proc = next(
            (x for x in fields if x["value"].startswith("/Lotus/Levels/Proc/")), None
        )
        if not proc:
            raise ValueError("Node has no bounded Proc reference " + q["uniqueName"])
        source_offset = after + proc["offset"]
        # All regular observed node Proc fields occur within <1 KiB of their name.
        if source_offset - start > 2048:
            raise ValueError("Unbounded node/Proc association")
        spec_evidence = solar_enemy_specs(data, source_offset, proc["value"])
        rows.append(
            dict(
                **q,
                locationTag=tag,
                sourceOffset=start,
                procOffset=source_offset,
                sourceProc=proc["value"],
                enemySpecs=spec_evidence["paths"],
                enemySpecEvidence=spec_evidence,
            )
        )
    return rows


def proc_path(source, proc):
    return source / "proc" / "Debug" / (proc.lstrip("/") + "_H")


def extract_procs(source, procs, args):
    for proc in procs:
        target = proc_path(source, proc)
        if target.exists():
            continue
        if not args.exporter:
            raise ValueError(
                "Missing Proc header " + str(target) + "; pass --refresh --exporter"
            )
        result = subprocess.run(
            [
                str(args.exporter),
                "--write-raw",
                "--game",
                "Warframe",
                "--cache-dir",
                str(args.cache_dir),
                "--package",
                "AnimRetarget",
                "--internal-path",
                proc,
                "--output-path",
                str(source / "proc"),
            ],
            capture_output=True,
            timeout=120,
        )
        if result.returncode or not target.exists():
            raise ValueError(
                "Proc extraction failed "
                + proc
                + ": "
                + result.stdout.decode("utf8", "replace")[-500:]
            )


def candidates(refs):
    out = []
    for value in refs:
        if not value.endswith(".level"):
            continue
        tile = value[:-6]
        relative = tile.removeprefix("/Lotus/Levels/")
        if relative.count("/") != 1:
            continue
        name = relative.rsplit("/", 1)[-1]
        if not re.search("Defen[cs]e|Defend|Interception", name, re.I):
            continue
        if re.search(
            "Spawn|Exit|Shrine|Crystal|Connector|Backdrop|Fitting", name, re.I
        ):
            continue
        out.append(tile)
    return sorted(set(out))


def toc_inventory(cache, tiles):
    """96-byte current cache TOC; parent ids are one-based. No decompression."""
    wanted = {}
    sources = []
    expected = {tile + ".level" for tile in tiles} | {
        tile + "/" + name
        for tile in tiles
        for name in ("0.nav", "0.level", "0.csg", "0.bsp")
    }
    for filename in ("H.AnimRetarget.toc", "B.Misc.toc", "H.Misc.toc"):
        path = cache / filename
        data = path.read_bytes()
        if (len(data) - 8) % 96:
            raise ValueError("Unsupported TOC stride " + filename)
        paths = []
        accepted = {}
        for i in range((len(data) - 8) // 96):
            off = 8 + 96 * i
            parent = struct.unpack_from("<I", data, off + 28)[0]
            name = data[off + 32 : off + 96].split(b"\0")[0].decode("utf8")
            if parent > len(paths):
                raise ValueError("TOC forward parent " + filename)
            current = (paths[parent - 1] + "/" if parent else "/") + name
            paths.append(current)
            if current in expected:
                accepted[current] = dict(
                    offset=struct.unpack_from("<Q", data, off)[0],
                    packedBytes=struct.unpack_from("<I", data, off + 16)[0],
                    unpackedBytes=struct.unpack_from("<I", data, off + 20)[0],
                )
        sources.append(dict(file=filename, sha256=digest(path), bytes=len(data)))
        for resource, info in accepted.items():
            wanted.setdefault(resource, {})[filename] = info
    return wanted, sources


def build(args):
    source = args.source_root
    source.mkdir(parents=True, exist_ok=True)
    provenance_path = source / "official-provenance.json"
    provenance = (
        json.loads(provenance_path.read_text(encoding="utf8"))
        if provenance_path.exists()
        else {}
    )
    if args.refresh:
        for lang in ("en", "zh"):
            provenance[lang] = fetch_regions(source, lang)
        provenance_path.write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf8"
        )
    regions = json.loads((source / "ExportRegions_en.json").read_bytes())[
        "ExportRegions"
    ]
    zh = {
        r["uniqueName"]: r
        for r in json.loads((source / "ExportRegions_zh.json").read_bytes())[
            "ExportRegions"
        ]
    }
    solar = args.solar_map.read_bytes()
    nodes = solar_nodes(solar, regions)
    procs = sorted({n["sourceProc"] for n in nodes})
    extract_procs(source, procs, args)
    proc_rows = []
    tile_set = set()
    for proc in procs:
        path = proc_path(source, proc)
        refs = [
            s["value"]
            for s in lp_strings(path.read_bytes())
            if s["value"].startswith("/Lotus/Levels/")
        ]
        refs = sorted(set(refs))
        selected = candidates(refs)
        tile_set.update(selected)
        proc_rows.append(
            dict(
                sourceProc=proc,
                sha256=digest(path),
                bytes=path.stat().st_size,
                levelReferences=refs,
                candidateTiles=selected,
                candidateRule=CANDIDATE_RULE,
            )
        )
    resources, toc_sources = toc_inventory(args.cache_dir, sorted(tile_set))
    catalog_path = args.output / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf8"))
    by_proc = {p["sourceProc"]: p for p in proc_rows}
    map_tiles = {k: v["sourceTile"] for k, v in catalog["maps"].items()}
    import_status_path = args.output / "map-import-status.json"
    import_status = (
        json.loads(import_status_path.read_text(encoding="utf8"))["tiles"]
        if import_status_path.exists()
        else {}
    )
    tiles = []
    for tile in sorted(tile_set):
        available = {
            p: v
            for p, v in resources.items()
            if p == tile + ".level" or p.startswith(tile + "/")
        }
        headers = available.get(tile + "/0.nav", {})
        bodies = available.get(tile + "/0.nav", {})
        imported = [k for k, v in map_tiles.items() if v == tile]
        nav = "H.Misc.toc" in headers and "B.Misc.toc" in bodies
        if imported:
            status = "imported"
        elif nav:
            status = "source-resources-present-not-imported"
        else:
            status = "source-nav-missing"
        tiles.append(
            dict(
                tile=tile,
                mapIds=imported,
                status=status,
                importBlockReason=(
                    import_status.get(tile, {}).get("importBlockReason")
                    if not imported
                    else None
                ),
                importStatus=import_status.get(tile, {}).get("status"),
                extractableResourcePresent=bool(available),
                navHeaderPresent="H.Misc.toc" in headers,
                navBodyPresent="B.Misc.toc" in bodies,
                resourceEvidence=available,
                sourceProcs=[
                    p["sourceProc"] for p in proc_rows if tile in p["candidateTiles"]
                ],
            )
        )
    by_tile = {x["tile"]: x for x in tiles}
    result_nodes = []
    for row in nodes:
        q = zh.get(row["uniqueName"], {})
        pr = by_proc[row["sourceProc"]]
        imported = [
            key
            for key, tile in map_tiles.items()
            if tile + ".level" in pr["levelReferences"]
        ]
        missing = [t for t in pr["candidateTiles"] if not by_tile[t]["mapIds"]]
        coverage = (
            "missing"
            if not imported
            else "partial" if missing else "candidate-tiles-imported"
        )
        variant = "standard"
        p = row["sourceProc"]
        if "MirrorDefense" in p or "LastWishDefense" in p:
            variant = "mirror-defense"
        elif "/Space/" in p:
            variant = "archwing"
        elif "/Vania/" in p:
            variant = "1999-defense"
        included = variant != "archwing"
        node = dict(
            nodeId=row["uniqueName"],
            nodeName=row["name"],
            nodeNameZh=q.get("name", row["name"]),
            planet=row["systemName"],
            planetZh=q.get("systemName", row["systemName"]),
            systemIndex=row["systemIndex"],
            missionType="Defense" if row["missionIndex"] == 8 else "Interception",
            missionTypeZh="防御" if row["missionIndex"] == 8 else "拦截",
            missionIndex=row["missionIndex"],
            variant=variant,
            inScope=included,
            scope=dict(
                included=included,
                exclusion=None if included else "archwing",
                reason=(
                    None
                    if included
                    else "User scope excludes aerial/Archwing missions; retained only for inventory transparency."
                ),
            ),
            minEnemyLevel=row["minEnemyLevel"],
            maxEnemyLevel=row["maxEnemyLevel"],
            factionIndex=row["factionIndex"],
            sourceProc=p,
            enemySpecPaths=row["enemySpecs"],
            enemySpecEvidence=row["enemySpecEvidence"],
            qualification="official-export-node-label + current-installed-solar-node-first-proc + exact-proc-resource-dependency",
            arbitrationQualification=arbitration_qualification(row["uniqueName"]),
            coverage=coverage if included else "excluded",
            coverageStatus=(
                ("available" if coverage == "candidate-tiles-imported" else coverage)
                if included
                else "excluded"
            ),
            coverageLabel=(
                (
                    "候选tile已接入"
                    if coverage == "candidate-tiles-imported"
                    else "部分候选tile已接入" if coverage == "partial" else "未接入"
                )
                if included
                else "空战任务（范围外）"
            ),
            mapIds=imported,
            candidateTiles=pr["candidateTiles"],
            missingTiles=missing,
            missingMapReasons=[
                dict(
                    tile=tile,
                    reason=by_tile[tile].get("importBlockReason")
                    or (
                        "来源缺少导航资源"
                        if by_tile[tile]["status"] == "source-nav-missing"
                        else "待接入"
                    ),
                )
                for tile in missing
            ],
            evidence=dict(
                solarMapSha256=hashlib.sha256(solar).hexdigest(),
                nodeOffset=row["sourceOffset"],
                procOffset=row["procOffset"],
                localizationTag=row["locationTag"],
                procSha256=pr["sha256"],
                tileSelection=CANDIDATE_RULE,
            ),
        )
        result_nodes.append(node)
    spec_sources = enemy_spec_sources(result_nodes, args.output / "enemy-specs.json.gz")
    summary = dict(
        nodes=len(result_nodes),
        enemySpecGroups=len(spec_sources),
        enemySpecGroupsWithNodeReference=sum(
            bool(s["missions"]) for s in spec_sources.values()
        ),
        enemySpecGroupsWithoutNodeReference=sum(
            not s["missions"] for s in spec_sources.values()
        ),
        defense=sum(x["missionIndex"] == 8 for x in result_nodes),
        interception=sum(x["missionIndex"] == 13 for x in result_nodes),
        uniqueProcs=len(procs),
        candidateTiles=len(tiles),
        importedTiles=sum(x["status"] == "imported" for x in tiles),
        catalogMaps=len(map_tiles),
        nodesWithImportedTile=sum(bool(x["mapIds"]) for x in result_nodes),
        nodesWithNoImportedTile=sum(not x["mapIds"] for x in result_nodes),
        partialNodes=sum(x["coverage"] == "partial" for x in result_nodes),
        missingTiles=sum(x["status"] != "imported" for x in tiles),
        missingTilesWithNav=sum(
            x["status"] == "source-resources-present-not-imported" for x in tiles
        ),
        missingTilesWithoutNav=sum(x["status"] == "source-nav-missing" for x in tiles),
        arbitrationVerifiedNodes=0,
        arbitrationHistoricallyAddedNodes=sum(
            n["arbitrationQualification"]["status"] == "officially-added"
            for n in result_nodes
        ),
        currentWhitelistVerified=False,
        inScopeNodes=sum(n["inScope"] for n in result_nodes),
        inScopeDefense=sum(
            n["inScope"] and n["missionIndex"] == 8 for n in result_nodes
        ),
        inScopeInterception=sum(
            n["inScope"] and n["missionIndex"] == 13 for n in result_nodes
        ),
        excludedNodes=sum(not n["inScope"] for n in result_nodes),
        excludedArchwing=sum(n["variant"] == "archwing" for n in result_nodes),
        inScopeNodesWithNoImportedTile=sum(
            n["inScope"] and not n["mapIds"] for n in result_nodes
        ),
    )
    result = dict(
        schema=SCHEMA,
        gameVersion=args.game_version,
        summary=summary,
        qualification=[
            CANDIDATE_RULE,
            "45 official missionIndex8/13 nodes include Mirror Defense, Archwing and1999 variants; inScope excludes Archwing. Salacia missionIndex9 and Railjack missions outside these two indices are not counted. Only Tyana Pass and Munio have a historical official affirmative announcement recorded here; no live server whitelist or current rotation was verified.",
            "Imported tile matches preserve shared nodes; they do not reproduce a full generated mission seed.",
        ],
        sources=dict(
            official=provenance,
            arbitrationOfficialAddition=OFFICIAL_ARBITRATION_ADDITION,
            referenceSiteSnapshot=REFERENCE_SITE_SNAPSHOT,
            solarMap=dict(sha256=hashlib.sha256(solar).hexdigest(), bytes=len(solar)),
            cacheTocs=toc_sources,
            enemySpecCatalog=dict(
                file="enemy-specs.json.gz",
                sha256=digest(args.output / "enemy-specs.json.gz"),
                qualification="Display/source metadata only; original group weights, tiers and runnable entries unchanged.",
            ),
        ),
        nodes=result_nodes,
        enemySpecSources=spec_sources,
        procs=proc_rows,
        tiles=tiles,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "mission-coverage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    # Re-read immediately before patching to preserve geometry agent's other fields.
    catalog = json.loads(catalog_path.read_text(encoding="utf8"))
    for map_id, map_row in catalog["maps"].items():
        map_row["missions"] = [n for n in result_nodes if map_id in n["mapIds"]]
    catalog["enemySpecSources"] = spec_sources
    catalog["missionCoverage"] = dict(
        schema=SCHEMA, file="mission-coverage.json", summary=summary
    )
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--solar-map", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "data/arena")
    parser.add_argument("--game-version", default="2026.10.28.09.54")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
