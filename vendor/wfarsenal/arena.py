"""Independent, bounded spatial arena. No optimizer calls or baked-score writes."""

from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache
import gzip
import hashlib
import heapq
import json
import math
import threading
import time
import uuid
from . import parallel
from .arena_scene import load_scene, distance, Edge, ROOT
from .arena_combat import ArenaCombat, UnsupportedArenaCombat

MODEL = "arena-world-v3"
VITUS_DROP_CHANCE = 0.06
DRONE = "/Lotus/Types/Enemies/Corpus/Drones/AIWeek/CorpusEliteShieldDroneAvatar"
EPS = 1e-8


def defaults(enemy=""):
    return dict(
        mapId="corpus-ship-defense",
        region="focus",
        mode="waves",
        waves=20,
        seconds=1800.0,
        enemies=60,
        aliveCap=64,
        spawnEvery=1.0,
        spawnBatch=3,
        waveWait=3.0,
        maxWave=180.0,
        noKill=60.0,
        wallSeconds=30.0,
        seed=20261116,
        level=160,
        enemy=enemy,
        headshots=True,
        movement="parkour",
        doorSight="open",
        enemySpec="single",
        tier=0,
        droneEvery=7,
        rangeAssumption=150.0,
        movementStep=0.1,
    )


def normalize_scenario(value):
    if not isinstance(value, dict):
        raise ValueError("scenario must be an object")
    c = {**defaults(), **value}
    c["mapId"] = str(c.get("mapId") or c.get("map") or "corpus-ship-defense")
    for key, low, high in [
        ("waves", 1, 20),
        ("enemies", 1, 128),
        ("aliveCap", 1, 128),
        ("spawnBatch", 1, 16),
        ("level", 1, 9999),
        ("seed", 0, 2147483647),
        ("droneEvery", 0, 128),
        ("tier", 0, 99),
    ]:
        n = c[key]
        if (
            isinstance(n, bool)
            or not isinstance(n, (int, float))
            or int(n) != n
            or not low <= n <= high
        ):
            raise ValueError(f"{key} outside {low}..{high}")
        c[key] = int(n)
    for key, low, high in [
        ("seconds", 0.1, 1800),
        ("spawnEvery", 0.05, 60),
        ("waveWait", 0, 60),
        ("maxWave", 1, 600),
        ("noKill", 1, 180),
        ("wallSeconds", 1, 120),
        ("rangeAssumption", 1, 500),
        ("movementStep", 0.02, 0.1),
    ]:
        n = float(c[key])
        if not math.isfinite(n) or not low <= n <= high:
            raise ValueError(f"{key} outside {low}..{high}")
        c[key] = n
    if (
        c["mode"] not in ("waves", "time")
        or c["region"] not in ("focus", "full")
        or c["movement"] not in ("parkour", "walking", "fixed")
    ):
        raise ValueError("invalid arena mode/region/movement")
    if c["doorSight"] not in ("open", "closed"):
        raise ValueError("invalid doorSight")
    if c["movement"] == "fixed":
        point = c.get("fixedPosition")
        if (
            not isinstance(point, dict)
            or isinstance(point.get("face"), bool)
            or not isinstance(point.get("face"), int)
            or not isinstance(point.get("position"), (list, tuple))
            or len(point["position"]) != 3
        ):
            raise ValueError(
                "fixed mode requires fixedPosition={face:int,position:[x,y,z]}"
            )
    if not isinstance(c["headshots"], bool):
        raise ValueError("headshots must be boolean")
    return c


@lru_cache(maxsize=1)
def spatial_weapons():
    with gzip.open(
        ROOT / "data/arena/weapon-geometry.json.gz", "rt", encoding="utf-8"
    ) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def enemy_specs():
    with gzip.open(
        ROOT / "data/arena/enemy-specs.json.gz", "rt", encoding="utf-8"
    ) as stream:
        return json.load(stream)


def add(p, y):
    return (p[0], p[1] + y, p[2])


def mix(a, b, k):
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def random_at(seed, id, stream=0):
    x = (seed ^ ((id + 1) * 0x9E3779B1) ^ ((stream + 1) * 0x85EBCA6B)) & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967296.0


def route(search, node, limit=None):
    answer = []
    while search.prev[node] >= 0:
        answer.append(search.edges[node])
        node = search.prev[node]
        if search.reverse and limit and len(answer) >= limit:
            break
    return answer if search.reverse else answer[::-1]


@dataclass
class Actor:
    id: int
    node: int
    pos: tuple
    drone: bool = False
    route: list = field(default_factory=list)
    edge: dict | None = None
    tape: dict | None = None
    dead: bool = False
    unreachable: bool = False
    travelled: float = 0.0


class World:
    def __init__(self, context, cancelled=lambda: False, progress=lambda p: None):
        self.context = context
        self.c = context["scenario"]
        self.cancelled = cancelled
        self.progress = progress
        self.scene = load_scene(self.c["mapId"]).with_door_sight(
            self.c.get("doorSight", "open")
        )
        self.scene.reset_runtime()
        if self.cancelled():
            raise InterruptedError("已取消")
        self.combat = ArenaCombat(
            context["engine"],
            context["mod_records"],
            context["arcane_records"],
            {
                **context["common_options"],
                "delivery_kinds": [
                    "lingering",
                    "stackable",
                    "manualDetonation",
                    "sourceOwned",
                    "finiteField",
                    "ownedEmbed",
                    "embedded",
                    "noxAvatarLifecycle",
                    "zymosChildren",
                    "quantaStrategy",
                    "grimoireStrategy",
                    "reloadProjectiles",
                ],
            },
            context["incarnon_choices"],
            context["cycle_enabled"],
        )
        self.combat.nearby = self.nearby
        self.combat.syndicate_targets = lambda radius, t: [
            a.id
            for a in self.live
            if not a.dead
            and distance(a.pos, self.player.pos) <= radius
            and self.scene.visible(add(self.player.pos, 1), add(a.pos, 1))
        ]
        self.player = Actor(
            -1, self.scene.start["face"], tuple(self.scene.start["position"])
        )
        if self.c["movement"] == "fixed":
            point = self.c.get("fixedPosition")
            if not isinstance(point, dict):
                raise ValueError("fixed mode requires an explicit validated position")
            standing = self.scene.validate_standing(
                point.get("position"), point.get("face")
            )
            self.c["fixedPosition"] = standing
            self.player.node = standing["face"]
            self.player.pos = tuple(standing["position"])
        self.actors = {}
        self.live = []
        self.events = []
        self.sequence = 0
        self.t = 0.0
        self.wave = 0
        self.wave_start = 0.0
        self.generated = 0
        self.next_spawn = 0.0
        self.next_plan = 0.0
        self.next_frame = 0.0
        self.next_fire = 0.0
        self.last_kill = 0.0
        self.wait_until = 0.0
        self.wave_pending = False
        self.flow_node = -1
        self.flows = {}
        self.fallback = {}
        self.motion_cache = {}
        self.shot_geometry = {}
        self.committed = {}
        self.replay = {
            k: []
            for k in ("actors", "player", "shots", "kills", "waves", "moves", "combat")
        }
        self.stats = dict(
            shots=0,
            kills=0,
            waves=0,
            maxGroupKill=0,
            peakAlive=0,
            jumps=0,
            failedPathPlans=0,
            playerTravelSeconds=0.0,
            vitusExpected=0.0,
            vitusSample=0,
            droneKills=0,
            vitusDropChance=VITUS_DROP_CHANCE,
            bulletJumps=0,
            drops=0,
            upwardJumps=0,
            enemyDistance=0.0,
            crowdWaitSeconds=0.0,
            spawnQueued=0,
            enemyUnreachableSeconds=0.0,
            confirmedDoors=len(self.scene.doors),
            doorLinks=sum(
                edge.kind == "door" for edges in self.scene.graph for edge in edges
            ),
            doorSight=self.scene.door_sight,
        )
        self.diagnostics = [
            "生成数量/无人机频率为可复现场景参数，尚未还原原生Director",
            "战甲移动速度与跳跃为经过几何检查的场景策略，非完整游戏运动学",
            "精细外观与碰撞分开；静态墙板已纳入，未恢复原生BSP材质",
            "无扩散、瞬时瞄准；敌人身体与弱点采用固定几何代理",
            "精华按无人机击杀与公开表6%统计，不代表真实任务每分钟收益",
            "确认门口按常开通行；视线可独立选择，门槛仅在源门洞内抽象衔接，不开放普通墙体",
        ]
        if self.cancelled():
            raise InterruptedError("已取消")
        if self.combat.unsupported:
            raise UnsupportedArenaCombat(
                "当前场景尚未接入：" + ", ".join(self.combat.unsupported)
            )
        self.enemies = context["enemies"]
        self.enemy = self.enemies.get(self.c["enemy"])
        self.enemy_pool = []
        if self.c.get("enemySpec") not in (None, "", "single"):
            spec = next(
                (s for s in enemy_specs()["specs"] if s["path"] == self.c["enemySpec"]),
                None,
            )
            if spec is None:
                raise ValueError("敌人规格不存在")
            self.enemy_pool = [
                r
                for r in spec["enemies"]
                if r.get("runnable")
                and r.get("tier") == self.c["tier"]
                and r.get("probability", 0) > 0
            ]
            if not self.enemy_pool:
                raise ValueError("选定tier没有可映射敌人")
            self.diagnostics.append(
                "源敌人表按指定tier内权重抽取；cap=0在本场景中视为未设上限，均非已还原原生Director语义"
            )
        if self.enemy is None:
            raise ValueError("请选择可用敌人")
        focus = set(self.scene.raw.get("focusRegion", {}).get("faces", []))
        if self.c["region"] == "focus" and not focus:
            self.c["region"] = "full"
            self.diagnostics.append("此地图未单独划定中心子区，本次使用全部已接入区域")
        self.spawn_points = [
            s
            for s in self.scene.spawns
            if s.get("accepted") and (self.c["region"] == "full" or s["face"] in focus)
        ]
        if not self.spawn_points:
            raise ValueError("场景没有可用出生点")
        self.record(self.player, 0.0)

    def record(self, actor, t):
        row = [round(t, 6), *[round(v, 5) for v in actor.pos]]
        rows = self.replay["player"] if actor.id == -1 else actor.tape["path"]
        if rows and abs(rows[-1][0] - row[0]) < EPS:
            rows[-1] = row
        else:
            rows.append(row)

    def enqueue(self, t, kind, data):
        self.sequence += 1
        heapq.heappush(self.events, (max(self.t, t), self.sequence, kind, data))

    def nearby(self, id, radius, t):
        origin = self.combat.targets[id].position
        return [
            a.id
            for a in self.live
            if not a.dead
            and a.id != id
            and distance(a.pos, origin) <= radius
            and self.scene.visible(add(origin, 0.8), add(a.pos, 0.8))
        ]

    def protection(self):
        drones = [a for a in self.live if a.drone and not a.dead]
        for actor in self.live:
            target = self.combat.targets[actor.id]
            target.position = actor.pos
            target.protected = not actor.drone and any(
                distance(d.pos, actor.pos) <= 10
                and self.scene.visible(add(d.pos, 1), add(actor.pos, 1))
                for d in drones
            )
        self.combat.protected_ids = frozenset(
            a.id for a in self.live if self.combat.targets[a.id].protected
        )

    def drain(self, events=None):
        for event in events if events is not None else self.combat.drain_events():
            kind = event.get("kind")
            if kind == "kill":
                actor = self.actors[event["targetId"]]
                if actor.dead:
                    continue
                actor.dead = True
                when = event["time"]
                self.record(actor, when)
                actor.tape.update(death=round(when, 6), deathPosition=list(actor.pos))
                self.stats["kills"] += 1
                self.last_kill = when
                self.replay["kills"].append([round(when, 6), actor.id, *actor.pos])
                if actor.drone:
                    self.stats["droneKills"] += 1
                    self.stats["vitusExpected"] = (
                        self.stats["droneKills"] * VITUS_DROP_CHANCE
                    )
                    if random_at(self.c["seed"], actor.id, 3) < VITUS_DROP_CHANCE:
                        self.stats["vitusSample"] += 1
            else:
                self.replay["combat"].append(event)
        self.live = [a for a in self.live if not a.dead]

    def start_wave(self):
        self.wave += 1
        self.generated = 0
        self.wave_start = self.t
        self.last_kill = self.t
        self.next_spawn = self.t
        self.wave_pending = False
        self.replay["waves"].append(
            dict(wave=self.wave, start=round(self.t, 6), end=None)
        )

    def spawn(self):
        if self.generated >= self.c["enemies"]:
            self.next_spawn = math.inf
            return
        for _ in range(min(self.c["spawnBatch"], self.c["enemies"] - self.generated)):
            if len(self.live) >= self.c["aliveCap"]:
                break
            id = len(self.actors)
            offset = int(random_at(self.c["seed"], id) * len(self.spawn_points))
            point = None
            for n in range(len(self.spawn_points)):
                candidate = self.spawn_points[(offset + n) % len(self.spawn_points)]
                pos = tuple(self.scene.nodes[candidate["face"]])
                if all(distance(pos, a.pos) >= 1.1 for a in self.live):
                    point = candidate
                    break
            if point is None:
                self.stats["spawnQueued"] += 1
                break
            drone = bool(self.c["droneEvery"] and id % self.c["droneEvery"] == 0)
            enemy = self.enemies.get(DRONE, self.enemy) if drone else self.enemy
            if not drone and self.enemy_pool:
                available = [
                    r
                    for r in self.enemy_pool
                    if not r.get("maxSimultaneous")
                    or sum(
                        self.combat.targets[a.id].record["path"]
                        == r["resolvedAvatarPath"]
                        for a in self.live
                    )
                    < r["maxSimultaneous"]
                ]
                if not available:
                    break
                roll = random_at(self.c["seed"], id, 1) * sum(
                    r["probability"] for r in available
                )
                row = available[-1]
                for candidate in available:
                    roll -= candidate["probability"]
                    if roll <= 0:
                        row = candidate
                        break
                enemy = self.enemies[row["resolvedAvatarPath"]]
            pos = tuple(self.scene.nodes[point["face"]])
            actor = Actor(id, point["face"], pos, drone)
            target = self.combat.add_target(id, enemy, self.c["level"], pos)
            actor.tape = dict(
                id=id,
                type="drone" if drone else "normal",
                name=enemy.get("name") or enemy.get("nameEn"),
                enemyPath=enemy["path"],
                level=self.c["level"],
                birth=round(self.t, 6),
                death=None,
                hp=sum(target.full),
                path=[],
            )
            self.actors[id] = actor
            self.live.append(actor)
            self.replay["actors"].append(actor.tape)
            self.record(actor, self.t)
            self.generated += 1
        self.stats["peakAlive"] = max(self.stats["peakAlive"], len(self.live))
        self.next_spawn = self.t + self.c["spawnEvery"]

    def geometry(self, shot):
        engine = self.context["engine"]
        weapon = engine["weapon"]
        selected = int(weapon.get("__selectedFireMode__", engine["fire_mode"]))
        source_index = getattr(shot, "source_mode_index", None)
        index = (
            source_index
            if source_index is not None
            else (0 if shot.form == "base" else selected)
        )
        lane = getattr(shot, "physical_profile", None)
        if not lane and getattr(shot, "physical_lanes", ()):
            return self.geometry(shot.physical_lanes[0])
        key = (shot.form, index, getattr(shot, "lane_index", None))
        if key in self.shot_geometry:
            return self.shot_geometry[key]
        record = (spatial_weapons()["weapons"].get(weapon["path"]) or {}).get(
            str(index), {}
        )
        fire = record.get("fire") or {}
        projectile = record.get("projectile") or {}
        modes = weapon.get("__baseFireModes__") or weapon["fireModes"]
        mode = (
            modes[index]
            if index < len(modes)
            else weapon["fireModes"][engine["fire_mode"]]
        )
        from .event_profiles import base_profile

        profile_index = 0 if shot.form == "base" else engine["fire_mode"]
        profile = base_profile(weapon, profile_index)
        if lane:
            mode = {
                **mode,
                "damage": {
                    **(mode.get("damage") or {}),
                    "projectile": lane["projectile"],
                },
            }
            profile = {"radials": [lane["radial"]], "projectile": lane["projectile"]}
            projectile = (
                spatial_weapons()
                .get("projectileRecords", {})
                .get(lane["projectile"], {})
            )
        stackable = profile.get("stackable")
        if stackable and stackable.get("kind") not in ("stug", "simulor", "mq"):
            raise UnsupportedArenaCombat(
                "未识别球体融合契约：" + str(stackable.get("kind"))
            )
        if any("cortege-firefield" in item for item in profile.get("unmodeled", ())):
            self.diagnostics.append(
                "Cortege来源field路由/时钟尚未闭环：仅已有直接/死亡爆炸，不生成虚构火场"
            )
        chain = record.get("chain") or {}
        if chain.get("ChainableTypes"):
            raise UnsupportedArenaCombat(
                "链式目标类型过滤器尚未解析，不能对任意敌人连锁"
            )
        # MultiBeam is also inherited by ordinary RadialOnMissTraceFireBehavior
        # (Tenet Plinx base). It is not itself a damage-radius declaration.
        if (
            shot.stats.continuous
            and fire.get("MultiBeam")
            and not chain.get("NumChains")
        ):
            self.diagnostics.append(
                "无扩散多束沿同一瞄准方向：束数由现有continuous伤害/多重公式计算一次，MultiBeam外观数量不重复乘伤害"
            )
        clusters = profile.get("clusters") or []
        if len(clusters) > 1:
            raise UnsupportedArenaCombat("多种子弹族映射尚未接入")
        if clusters:
            self.c.setdefault("clusterGravity", 9.81)
            self.c.setdefault("clusterSpeedAssumption", 8.0)
            self.c.setdefault("clusterDirectionAssumption", [0.0, 0.5, 1.0])
            if (
                not math.isfinite(float(self.c["clusterGravity"]))
                or float(self.c["clusterGravity"]) < 0
                or not math.isfinite(float(self.c["clusterSpeedAssumption"]))
                or float(self.c["clusterSpeedAssumption"]) <= 0
            ):
                raise ValueError("invalid explicit cluster scene policy")
            child = record.get("clusterChild") or {}
            fields = child.get("fields") or {}
            if child.get("path") != clusters[0].get("nativeChild") or not fields.get(
                "MaxLife"
            ):
                raise UnsupportedArenaCombat("集群子弹身份/初速/寿命缺少当前来源")
            if int(projectile.get("NumClusterProjectiles") or 0) != int(
                clusters[0]["count"]
            ):
                raise UnsupportedArenaCombat("集群子弹来源数量与伤害组件不一致")
            self.diagnostics.append(
                "集群分裂保留原生数量/弧角/寿命；轴向取入射水平方向，分裂相位由seed固定；重力采用显式场景clusterGravity=9.81近似，未还原原生换算"
            )
            if not fields.get("KinematicInitialSpeed"):
                self.diagnostics.append(
                    "子弹缺少原生初速：使用显式场景clusterSpeedAssumption=8（原生最大速度仅作上限），不把最大速度冒充初速"
                )
            if not projectile.get("ClusterDirection"):
                self.diagnostics.append(
                    "子弹原生分裂轴向未声明：使用场景ClusterDirection=[0,0.5,1]，非射手扩散"
                )
        from .damage import _combine, _qualifier_rejection

        types = {str(v).rstrip("/") for v in weapon.get("ancestry") or ()} | {
            weapon["path"].rstrip("/")
        }
        terms = {}
        for effect in engine["effects"]:
            if effect.upgrade_type not in ("WEAPON_PUNCTURE_DEPTH", "WEAPON_RANGE"):
                continue
            if effect.valid_type and effect.valid_type.rstrip("/") not in types:
                continue
            if _qualifier_rejection(effect, weapon, engine["scenario"]):
                continue
            terms.setdefault(effect.upgrade_type, []).append(effect)
        # A current audited adapter may replace the historical source mode (Nox,
        # explicit heavy/charged routes). Do not borrow another projectile's motion.
        projectile_path = (mode.get("damage") or {}).get("projectile") or record.get(
            "projectilePath"
        )
        if projectile_path and record.get("projectilePath") != projectile_path:
            projectile = {}
        projectile = {
            **spatial_weapons().get("projectileRecords", {}).get(projectile_path, {}),
            **projectile,
        }
        speed = projectile.get(
            "KinematicInitialSpeed", (mode.get("damage") or {}).get("flightSpeed")
        )
        if projectile_path and (speed is None or float(speed) <= 0):
            raise UnsupportedArenaCombat("弹体缺少正的原生初速，不能回退为瞬时命中")
        range_value = fire.get("traceDistance")
        if range_value is None:
            range_value = self.c["rangeAssumption"]
            self.diagnostics.append(
                "弹体/射线硬射程未知：使用显式场景射程上限；寿命独立限制飞行距离"
            )
        range_value = _combine(float(range_value), terms.get("WEAPON_RANGE", []))
        base_depth = (
            projectile.get("PunctureDepth")
            if projectile_path
            else fire.get("tracePunctureDepth")
        )
        if base_depth is None:
            base_depth = mode.get("puncture") or 0.0
        puncture = _combine(float(base_depth), terms.get("WEAPON_PUNCTURE_DEPTH", []))
        life = projectile.get("MaxLife")
        lifetime = float(life) if life is not None and float(life) > 0 else math.inf
        if projectile_path and not math.isfinite(lifetime):
            self.diagnostics.append(
                "弹体寿命未知：只使用显式场景射程上限，不推定无限飞行"
            )
        result = dict(
            range=max(0.0, range_value),
            speed=float(speed) if projectile_path else math.inf,
            projectile=projectile_path,
            lifetime=lifetime,
            puncture=max(0.0, puncture),
            infinitePuncture=bool(
                projectile.get(
                    "InfinitePunctureDepth", fire.get("InfinitePunctureDepth", False)
                )
            ),
            ignoresAvatars=bool(fire.get("PunchthroughIgnoresAvatars")),
            traceRadius=max(0.0, float(fire.get("TraceRadius") or 0.0)),
            beamRadius=(
                max(0.0, float(fire.get("Radius") or 0.0))
                if shot.stats.continuous
                else 0.0
            ),
            checksCover=bool(fire.get("RadialChecksCover", True)),
            minCoverDistance=max(0.0, float(fire.get("RadialMinCoverDistance") or 0.0)),
            mode=mode,
            chain=chain,
            clusters=clusters,
            clusterSource=record.get("clusterChild"),
            nativeProjectile=projectile,
            lifecycleProfile=profile,
            grimoire=bool(self.combat.combat.get("grimoireStrategy")),
            quanta=getattr(shot.stats, "_quanta_strategy", None),
            stackable=stackable,
            manual=self.combat.combat.get("manualDetonation"),
        )
        if projectile.get("KinematicGravity"):
            self.diagnostics.append(
                "弹体重力原生换算未校准：直线首碰与有限步移动目标扫掠，保留实际飞行时间"
            )
        if puncture > 0:
            self.diagnostics.append(
                "目标穿透按几何代理厚度扣除；墙体材质厚度未闭环，静态障碍保守阻断"
            )
        self.shot_geometry[key] = result
        return result

    def aimpoint(self, actor):
        target = self.combat.targets[actor.id]
        has_head = any(
            p.get("part") == "HEAD" for p in target.record.get("hitProxies", ())
        )
        head = self.c["headshots"] and has_head and not actor.drone
        return add(actor.pos, 1.65 if head else 0.85), head

    def shot_hits(self, origin, point, shot, geometry, *, preview=False):
        # Trace once from launch or planning origin. Collision selects actual head/body
        # proxies, never grants head eligibility merely because the aiming switch is on.
        length = distance(origin, point)
        if length < EPS:
            return [], tuple(point)
        direction = tuple((point[i] - origin[i]) / length for i in range(3))
        maximum = geometry["range"]
        wall = self.scene.raycast(origin, direction, maximum)
        limit = wall.distance if wall else maximum
        hits = []
        for actor in self.live:
            if actor.dead:
                continue
            target = self.combat.targets[actor.id]
            proxies = (
                [(0.85, 0.45, False)]
                if actor.drone
                else [(0.45, 0.38, False), (0.95, 0.38, False), (1.25, 0.30, False)]
            )
            if not actor.drone and any(
                p.get("part") == "HEAD" for p in target.record.get("hitProxies", ())
            ):
                proxies.append((1.65, 0.23, True))
            entries = []
            for height, radius, head in proxies:
                center = add(actor.pos, height)
                r = radius + geometry["traceRadius"]
                offset = tuple(center[i] - origin[i] for i in range(3))
                along = sum(offset[i] * direction[i] for i in range(3))
                perp = sum(x * x for x in offset) - along * along
                if perp > r * r:
                    continue
                width = math.sqrt(max(0.0, r * r - perp))
                entry = max(0.0, along - width)
                exit = along + width
                if exit < 0 or entry > limit - EPS:
                    continue
                entries.append((entry, exit, head))
            if entries:
                first = min(entries, key=lambda x: (x[0], x[2]))
                hits.append(
                    (
                        first[0],
                        actor.id,
                        actor,
                        first[2],
                        max(x[1] for x in entries) - first[0],
                    )
                )
        hits.sort(key=lambda row: (row[0], row[1]))
        contacts = []
        remaining = geometry["puncture"]
        impact = tuple(origin[i] + direction[i] * limit for i in range(3))
        for at, _, actor, head, thickness in hits:
            contacts.append((actor, head, at))
            impact = tuple(origin[i] + direction[i] * at for i in range(3))
            if shot.radials and geometry["projectile"]:
                break
            if not geometry["infinitePuncture"] and not geometry["ignoresAvatars"]:
                if remaining + EPS < thickness:
                    break
                remaining -= thickness
        # A trace without contacts reaches its physical wall/range endpoint. For
        # a beam ignoring avatars the endpoint is also independent of their order.
        if not contacts or geometry["ignoresAvatars"] or geometry["infinitePuncture"]:
            impact = tuple(origin[i] + direction[i] * limit for i in range(3))
        if not geometry["projectile"] and shot.radials and not contacts:
            impact = (
                tuple(point) if not wall or length < wall.distance else wall.position
            )
        return contacts, impact

    def radial_specs(self, shot):
        if hasattr(shot, "_arena_special_radial"):
            return [
                dict(
                    component=1,
                    radius=shot._arena_special_radial,
                    falloff=0.0,
                    start=0.0,
                    checksCover=True,
                    child=None,
                    contact=False,
                    delay=0.0,
                    headOnly=False,
                    bodyOnly=False,
                )
            ]
        from .event_profiles import base_profile

        if getattr(shot, "physical_lanes", ()):
            return [
                row for lane in shot.physical_lanes for row in self.radial_specs(lane)
            ]
        weapon = self.context["engine"]["weapon"]
        index = 0 if shot.form == "base" else self.context["engine"]["fire_mode"]
        lane = getattr(shot, "physical_profile", None)
        source_index = getattr(shot, "source_mode_index", None)
        if lane:
            profile = {"radials": [lane["radial"]]}
        elif source_index is not None and self.combat.combat.get("onosCharge"):
            # Onos' selected power mode still emits eight beam quanta first.
            # Match the emitted source mode, not the UI's requested mode.
            profile = base_profile(
                {**weapon, "__selectedFireMode__": source_index}, source_index
            )
        else:
            profile = base_profile(weapon, index)
        from .projectile_events import grimoire_strategy

        orb = grimoire_strategy(
            weapon, index, self.context["engine"]["scenario"].combat_state
        )
        if orb:
            rows = orb["parts"]
            if len(rows) != len(shot.radials):
                raise UnsupportedArenaCombat("Grimoire策略包与解析组件不一致")
            return [
                dict(
                    component=i + 1,
                    radius=float(row.get("radius_m", 0.0)),
                    falloff=float(row.get("falloff_reduction", 0.0)),
                    start=0.0,
                    checksCover=True,
                    child=None,
                    contact=False,
                    delay=float(row["impact_delay_seconds"]),
                    headOnly=False,
                    bodyOnly=False,
                    orbChain=bool(row.get("__grimoireChain")),
                )
                for i, row in enumerate(rows)
            ]
        rows = list(profile.get("radials") or ())
        if not rows and profile.get("radial"):
            rows = [profile["radial"]]
        if not rows and shot.form != "base" and len(shot.radials) == 1:
            # manual_combat creates these two terminal Incarnon packets from
            # reference.incarnon, independently of auditedAttacks/base_profile.
            from .manual_combat import reference

            incarnon = reference().get("incarnon", {}).get(weapon["path"], {})
            if incarnon.get("referenceId") in (
                "burston_incarnon",
                "burston_prime_incarnon",
            ):
                if not incarnon.get("radial"):
                    raise UnsupportedArenaCombat("Burston灵化终端包缺少原始径向来源")
                rows = [incarnon["radial"]]
        if self.combat.combat.get("onosCharge"):
            # The same explicit switch is used by manual_combat when admitting
            # Onos' optional power radial. Do not invent it when no part exists.
            enabled = self.context["engine"]["scenario"].combat_state.get(
                "onosRadialHit"
            )
            rows = [
                row for row in rows if not row.get("requiresOnosRadialHit") or enabled
            ]
        mappings = [(row, None, False) for row in rows]
        if getattr(shot.stats, "_quanta_strategy", None) and len(rows) == 1:
            # The audited paid-cube adapter emits one seed blast plus a sibling
            # chain packet; both share geometry but retain their own MS and delay.
            mappings = [(rows[0], None, False) for _ in shot.radials]
        clusters = profile.get("clusters") or []
        if clusters:
            # manual_combat emits each child's contact/radial pair individually,
            # including the final fractional expected multishot pair.
            if len(clusters) != 1 or (len(shot.radials) - len(rows)) % 2:
                raise UnsupportedArenaCombat("无法一一映射集群子弹接触/爆炸组件")
            for child in range((len(shot.radials) - len(rows)) // 2):
                mappings.extend(
                    [
                        (clusters[0]["direct"], child, True),
                        (clusters[0]["radial"], child, False),
                    ]
                )
        if len(mappings) != len(shot.radials):
            raise UnsupportedArenaCombat("范围伤害组件与几何来源不能一一对应")
        out = []
        for i, (part, (row, child, contact)) in enumerate(zip(shot.radials, mappings)):
            radius = 0.0 if contact else row.get("radius_m", row.get("radius"))
            if radius is None:
                strategy = getattr(shot.stats, "_quanta_strategy", None)
                if strategy:
                    radius = 6.0
                else:
                    radius = self.geometry(shot)["nativeProjectile"].get("DamageRadius")
            if radius is None:
                raise UnsupportedArenaCombat("范围组件缺少可核对半径")
            if row.get("takes_blast_radius_mods", row.get("takesRadiusMods", False)):
                radius *= part.explosion_radius_multiplier
            delay = max(
                0.0,
                float(
                    getattr(part, "_impact_delay", row.get("impact_delay_seconds", 0.0))
                    or 0.0
                ),
            )
            out.append(
                dict(
                    component=i + 1,
                    radius=max(0.0, float(radius)),
                    falloff=float(
                        row.get("falloff_reduction", row.get("falloff", 0.0))
                    ),
                    start=float(row.get("falloff_start_m", 0.0)),
                    checksCover=row.get("checksCover", True),
                    child=child,
                    contact=contact,
                    delay=delay,
                    headOnly=bool(row.get("headOnly")),
                    bodyOnly=bool(row.get("bodyOnly")),
                )
            )
        return out

    def recipients(
        self, shot, origin, point, geometry, *, direct=None, impact=None, planning=False
    ):
        # Explicit direct/impact means a frozen forward flight contact, not a new ray.
        if direct is None:
            direct, impact = self.shot_hits(origin, point, shot, geometry)
        found = [
            (
                actor,
                geometry.get("directComponent", 0),
                head and geometry.get("directComponent", 0) == 0,
                1.0,
                at,
            )
            for actor, head, at in direct
            if not actor.dead
        ]
        seen = {a.id for a, _, _, _, _ in found}
        if geometry["beamRadius"] > 0:
            for actor in self.live:
                d = distance(add(actor.pos, 0.85), impact)
                if actor.dead or actor.id in seen or d > geometry["beamRadius"]:
                    continue
                if (
                    geometry["checksCover"]
                    and d > geometry["minCoverDistance"]
                    and not self.scene.visible(impact, add(actor.pos, 0.85))
                ):
                    continue
                found.append((actor, 0, False, 1.0, distance(origin, impact)))
                seen.add(actor.id)
        chain = geometry.get("chain") or {}
        if direct and chain.get("NumChains") and not geometry.get("childFlight"):
            used = set(seen)
            seed = direct[0][0]
            current = seed
            for hop in range(int(chain["NumChains"])):
                source = current if chain.get("SequentialChains") else seed
                choices = [
                    a
                    for a in self.live
                    if not a.dead
                    and a.id not in used
                    and distance(a.pos, source.pos)
                    <= float(chain.get("ChainDistance") or 0.0)
                    and self.scene.visible(add(source.pos, 0.85), add(a.pos, 0.85))
                ]
                if not choices:
                    break
                current = min(
                    choices, key=lambda a: (distance(a.pos, source.pos), a.id)
                )
                used.add(current.id)
                scale = float(chain.get("ChainDamageMultiplier", 1.0)) ** (
                    hop + 1 if chain.get("SequentialChains") else 1
                )
                found.append(
                    (current, 0, False, scale, distance(origin, add(seed.pos, 0.85)))
                )
        if planning and (geometry.get("quanta") or geometry.get("grimoire")):
            impact = tuple(point)
        for radial in self.radial_specs(shot):
            selected = geometry.get("radialComponents")
            if selected is not None:
                if radial["component"] not in selected:
                    continue
            elif radial["child"] is not None or (
                radial["delay"] > EPS and not planning
            ):
                continue
            if radial["contact"]:
                continue
            for actor in self.live:
                if actor.dead:
                    continue
                d = distance(add(actor.pos, 0.85), impact)
                if d > radial["radius"]:
                    continue
                if radial["checksCover"] and not self.scene.visible(
                    impact, add(actor.pos, 0.85)
                ):
                    continue
                fraction = max(
                    0.0,
                    min(
                        1.0,
                        (d - radial["start"])
                        / max(EPS, radial["radius"] - radial["start"]),
                    ),
                )
                found.append(
                    (
                        actor,
                        radial["component"],
                        False,
                        max(0.0, 1.0 - radial["falloff"] * fraction),
                        distance(origin, impact),
                    )
                )
        return found, impact

    def choose(self):
        if not self.live:
            return None
        preview = self.combat.preview(self.t)
        if preview is None:
            return None
        geometry = self.geometry(preview)
        origin = add(self.player.pos, 1.55)
        # A shortlist must be drawn from shootable targets. Cutting by distance
        # first can hide every visible target behind sixteen nearby occluded
        # enemies, while the movement planner correctly decides to stay put.
        targets = []
        candidates = []
        for actor in sorted(
            self.live, key=lambda a: (distance(a.pos, self.player.pos), a.id)
        ):
            if self.combat.targets[actor.id].protected:
                continue
            point, _ = self.aimpoint(actor)
            if distance(origin, point) <= geometry["range"] and self.scene.visible(
                origin, point
            ):
                targets.append(actor)
                candidates.append(point)
                if len(targets) == 16:
                    break
        radials = self.radial_specs(preview)
        if radials:
            radius = max(r["radius"] for r in radials)
            for i, a in enumerate(targets[:8]):
                for b in targets[i + 1 : 8]:
                    if (
                        distance(a.pos, b.pos) > 2 * radius
                        or abs(a.pos[1] - b.pos[1]) > 1.5
                    ):
                        continue
                    midpoint = mix(a.pos, b.pos, 0.5)
                    support = self.scene.ground_support(
                        midpoint, max_drop=2, max_rise=1
                    )
                    if support:
                        point = add(support.position, 0.04)
                        if distance(origin, point) <= geometry[
                            "range"
                        ] and self.scene.visible(origin, point):
                            candidates.append(point)
        ranked = []
        for point in candidates[:40]:
            damages = {}
            impact = point
            for packet in preview.physical_lanes or (preview,):
                packet_geometry = self.geometry(packet)
                recipients, impact = self.recipients(
                    packet, origin, point, packet_geometry, planning=True
                )
                for actor, component, head, scale, d in recipients:
                    target = self.combat.targets[actor.id]
                    if target.protected:
                        continue
                    amount = self.combat.estimate(
                        packet, actor.id, component, head, scale, d
                    )
                    damages[actor.id] = damages.get(actor.id, 0.0) + amount
            kills = 0
            effective = 0.0
            for id, amount in damages.items():
                target = self.combat.targets[id]
                remaining = max(
                    0.0,
                    sum(target.pools)
                    - sum(row.get(id, 0.0) for row in self.committed.values()),
                )
                effective += min(remaining, amount)
                if remaining > EPS and amount >= remaining - EPS:
                    kills += 1
            if effective > 0:
                ranked.append((kills, effective, point, damages, impact))
        if not ranked:
            return None
        ranked.sort(key=lambda x: (-x[0], -x[1], x[2]))
        best = ranked[0]
        best_score = -math.inf
        # Limited two-shot coverage, with residual health rather than raw overkill.
        for first in ranked[:8]:
            for second in ranked[:8]:
                kills = 0
                effective = 0.0
                for id in first[3].keys() | second[3].keys():
                    remaining = max(
                        0.0,
                        sum(self.combat.targets[id].pools)
                        - sum(row.get(id, 0.0) for row in self.committed.values()),
                    )
                    amount = first[3].get(id, 0) + second[3].get(id, 0)
                    kills += remaining > EPS and amount >= remaining - EPS
                    effective += min(amount, remaining)
                score = first[0] * 1e12 + kills * 1e9 + effective
                if score > best_score:
                    best_score = score
                    best = first
        return dict(point=best[2], preview=preview, geometry=geometry, impact=best[4])

    def _entities(self):
        if not hasattr(self, "entities"):
            self.entities = {}
            self.entity_serial = 0
            self.manual_throws = 0
        self.replay.setdefault("fields", [])
        return self.entities

    def _entity_point(self, entity):
        host = self.actors.get(entity.get("host"))
        if host is not None and not host.dead:
            entity["point"] = tuple(host.pos[i] + entity["offset"][i] for i in range(3))
        elif host is not None and host.dead:
            if entity.get("hostOnly"):
                entity["alive"] = False
                return None
            entity["host"] = None  # World source persists at its last supported pose.
        return entity["point"]

    def _field_record(self, entity, kind):
        point = self._entity_point(entity)
        self.replay["fields"].append(
            dict(
                time=round(self.t, 6),
                id=entity["id"],
                kind=kind,
                position=list(point) if point else None,
                host=entity.get("host"),
                radius=entity.get("radius", 0.0),
                stacks=entity.get("stacks", 1.0),
                expires=entity["end"] if math.isfinite(entity["end"]) else None,
                entityType=entity["kind"],
                sourceShot=entity["shot"].id,
                token=entity["token"],
                alive=entity["alive"],
            )
        )

    def _new_entity(self, shot, point, host, **values):
        entities = self._entities()
        self.entity_serial += 1
        offset = (
            tuple(point[i] - host.pos[i] for i in range(3)) if host else (0.0, 0.0, 0.0)
        )
        entity = dict(
            id=self.entity_serial,
            shot=shot,
            point=tuple(point),
            host=host.id if host else None,
            offset=offset,
            alive=True,
            token=0,
            **values,
        )
        entities[entity["id"]] = entity
        self._field_record(entity, "spawn")
        return entity

    def _entity_event(self, entity, action, when):
        self.enqueue(
            when,
            "impact",
            dict(
                kind="entity", entity=entity["id"], token=entity["token"], action=action
            ),
        )

    def _entity_damage(
        self, entity, part, *, scale=1.0, host_only=False, radius=None, only_id=None
    ):
        point = self._entity_point(entity)
        if point is None:
            return
        parent = entity["shot"]
        r = entity.get("radius", 0.0) if radius is None else radius
        victims = []
        for actor in self.live:
            if (
                actor.dead
                or (host_only and actor.id != entity.get("host"))
                or (only_id is not None and actor.id != only_id)
            ):
                continue
            d = distance(add(actor.pos, 0.85), point)
            if actor.id != entity.get("host") and d > r:
                continue
            if (
                entity.get("checksCover", True)
                and actor.id != entity.get("host")
                and not self.scene.visible(point, add(actor.pos, 0.85))
            ):
                continue
            start = entity.get("falloffStart", 0.0)
            reduction = entity.get("falloff", 0.0)
            factor = (
                1.0
                if host_only
                else max(
                    0.0,
                    1.0
                    - reduction * max(0.0, min(1.0, (d - start) / max(EPS, r - start))),
                )
            )
            victims.append((actor, factor))
        self.protection()
        before = self.stats["kills"]
        # fork_part_shot owns detached-part damage and per-victim CO, while the world
        # freezes protection once for this component's simultaneous recipients.
        batch = self.combat.fork_part_shot(
            parent, part, self.t, entity.get("refresh", "snapshot")
        )
        self.combat.begin_impact(batch, self.t)
        for actor, factor in victims:
            self.combat.hit(
                batch,
                actor.id,
                0,
                t=self.t,
                radial_scale=scale * factor,
                distance=distance(entity.get("origin", point), point),
                head=False,
            )
        self.combat.finish_impact(batch, self.t)
        self.drain()
        self.stats["maxGroupKill"] = max(
            self.stats["maxGroupKill"], self.stats["kills"] - before
        )

    def _orb_place(self, shot, point, origin, spec, parts, geometry):
        entities = self._entities()
        self.c.setdefault("orbMergeDistance", 2.0)
        self.diagnostics.append(
            "融合球按独立世界落点与视线合并；orbMergeDistance为显式场景接触近似，未把全场球视为同一点"
        )
        whole = int(max(0.0, shot.stats.multishot))
        weights = [1.0] * whole + (
            [shot.stats.multishot - whole] if shot.stats.multishot > whole + EPS else []
        )
        for weight in weights:
            group = next(
                (
                    e
                    for e in entities.values()
                    if e["alive"]
                    and e["kind"] == "orb"
                    and e["form"] == shot.form
                    and e["spec"]["kind"] == spec["kind"]
                    and distance(e["point"], point) <= self.c["orbMergeDistance"]
                    and self.scene.visible(e["point"], point)
                ),
                None,
            )
            if group is None:
                group = self._new_entity(
                    shot,
                    point,
                    None,
                    kind="orb",
                    form=shot.form,
                    spec=spec,
                    parts=parts,
                    stacks=weight * spec.get("initialStack", 1),
                    end=max(self.t, shot.time + float(spec["maxLife"])),
                    radius=float(
                        geometry["nativeProjectile"].get("DamageRadius")
                        or geometry["lifecycleProfile"]
                        .get("compression", {})
                        .get("radius")
                        or 0.0
                    ),
                    falloff=0.0,
                    origin=origin,
                    singularity=False,
                )
                self._entity_event(group, "expire", group["end"])
            else:
                old = group["stacks"]
                group["stacks"] = min(
                    float(spec["maxStack"]), old + weight * spec.get("initialStack", 1)
                )
                added = group["stacks"] - old
                group["token"] += 1
                group["end"] = self.t + float(spec["stackedLife"])
                self._entity_event(group, "expire", group["end"])
                if added > EPS and "merge" in parts:
                    low, high = spec.get("mergeDamage", (0.0, 0.0))
                    native = sum(spec["merge"]["damage"].values())
                    override = low + (high - low) * added / spec["maxStack"]
                    factor = override / native if override > 0 and native else 1.0
                    group["mergeScale"] = factor
                    self._entity_event(group, "merge", self.t)
                if spec.get("singularity") and group["stacks"] >= spec.get(
                    "attachAtStack", spec["maxStack"]
                ):
                    group["singularity"] = True
                    group["radius"] = 6.0
                    self._entity_event(
                        group,
                        "singularity",
                        self.t + float(spec["singularity"]["interval"]),
                    )
                self._field_record(group, "merge")
            state = self.context["engine"]["scenario"].combat_state
            if (
                state.get("projectileMode") == "manual"
                and self.stats["shots"]
                % max(1, int(state.get("detonateAfterShots") or 1))
                == 0
            ):
                self._entity_event(
                    group,
                    "expire",
                    self.t + float(state.get("detonationWaitSeconds") or 0.0),
                )
        return True

    def _place_lifecycle(self, shot, geometry, point, contacts, origin):
        st = shot.stats
        profile = geometry["lifecycleProfile"]
        host = contacts[0][0] if contacts else None
        stackable = getattr(st, "_stackable", None)
        if stackable:
            spec, parts = stackable
            if spec["kind"] in ("simulor", "mq"):
                return self._orb_place(shot, point, origin, spec, parts, geometry)
            entities = self._entities()
            self.c.setdefault("stugMergeRadius", 0.5)
            self.diagnostics.append(
                "Stug同宿主/相邻静态落点融合；静态融合距离为显式场景stugMergeRadius，非已恢复原生触碰体积"
            )
            remaining = max(0.0, st.multishot) * float(spec.get("initialStack", 1.0))
            while remaining > EPS:
                amount = min(float(spec["maxStack"]), remaining)
                remaining -= amount
                found = next(
                    (
                        e
                        for e in entities.values()
                        if e["alive"]
                        and e["kind"] == "stug"
                        and e["form"] == shot.form
                        and e.get("host") == (host.id if host else None)
                        and distance(self._entity_point(e) or point, point)
                        <= self.c["stugMergeRadius"]
                        and self.scene.visible(self._entity_point(e) or point, point)
                    ),
                    None,
                )
                if found:
                    old = found["stacks"]
                    found["stacks"] = min(float(spec["maxStack"]), old + amount)
                    found["token"] += 1
                    found["end"] = self.t + float(spec["stackedLife"])
                    self._field_record(found, "merge")
                    self._entity_event(found, "expire", found["end"])
                    if found["nextTick"] < found["end"]:
                        self._entity_event(
                            found, "tick", max(self.t, found["nextTick"])
                        )
                else:
                    radius = float(
                        geometry["nativeProjectile"].get("EmbedDamageRadius") or 0.0
                    )
                    if radius <= 0:
                        raise UnsupportedArenaCombat("Stug缺少EmbedDamageRadius来源")
                    found = self._new_entity(
                        shot,
                        point,
                        host,
                        kind="stug",
                        form=shot.form,
                        end=self.t + float(spec["embedSeconds"]),
                        stacks=amount,
                        spec=spec,
                        parts=parts,
                        radius=radius,
                        explosionRadius=float(
                            geometry["nativeProjectile"].get("DamageRadius") or radius
                        ),
                        falloff=0.0,
                        refresh="snapshot",
                        nextTick=self.t + float(spec["embedInterval"]),
                        origin=origin,
                        hostOnly=False,
                    )
                    found["nextTick"] = self.t
                    self._entity_event(found, "expire", found["end"])
                    self._entity_event(found, "tick", self.t)
                if found["stacks"] >= spec["maxStack"] - EPS:
                    self._entity_event(found, "expire", self.t)
            return True
        manual = geometry.get("manual")
        if manual:
            entities = self._entities()
            limit = int(manual.get("maxProjectiles", 8))
            active = [
                e for e in entities.values() if e["alive"] and e["kind"] == "mine"
            ]
            if sum(e.get("quantity", 1.0) for e in active) >= limit:
                for entity in active:
                    self._entity_event(entity, "expire", self.t)
            specs = self.radial_specs(shot)
            blast = []
            if st.radial_only:
                radius = geometry["nativeProjectile"].get("DamageRadius")
                if radius is None:
                    raise UnsupportedArenaCombat("手动爆炸主包缺少半径来源")
                blast.append(
                    (
                        st,
                        float(radius),
                        float(
                            geometry["nativeProjectile"].get("ExplosionFallOff") or 0.0
                        ),
                    )
                )
            blast.extend(
                (shot.components[r["component"]], r["radius"], r["falloff"])
                for r in specs
                if r["child"] is None
            )
            if not blast:
                raise UnsupportedArenaCombat("手动引爆缺少可核对爆炸包")
            mine = self._new_entity(
                shot,
                point,
                host,
                kind="mine",
                form=shot.form,
                end=self.t + geometry["lifetime"],
                radius=max(r for _, r, _ in blast),
                blast=blast,
                quantity=max(0.0, st.multishot),
                origin=origin,
                hostOnly=False,
            )
            if math.isfinite(mine["end"]):
                self._entity_event(mine, "expire", mine["end"])
            self.manual_throws += 1
            batch = max(1, int(manual.get("batchSize") or 1))
            delay = max(0.0, float(manual.get("delaySeconds") or 0.0))
            # Capacity is per expected physical mine, not per target hit.
            if (
                self.manual_throws >= batch
                or sum(e.get("quantity", 1.0) for e in active) + mine["quantity"]
                >= limit
            ):
                self.manual_throws = 0
                for entity in [
                    e for e in entities.values() if e["alive"] and e["kind"] == "mine"
                ]:
                    self._entity_event(entity, "expire", self.t + delay)
            return True
        placed = False
        if getattr(st, "_zymos_children", None) and host and contacts[0][1]:
            entity = self._new_entity(
                shot,
                point,
                host,
                kind="zymos-carrier",
                end=self.t + 1.1,
                radius=0.0,
                hostOnly=True,
            )
            self._entity_event(
                entity,
                "zymos",
                self.t + 1.1 + float(st._zymos_policy.get("frameSeconds", 1.0 / 60.0)),
            )
            placed = True
        owned = getattr(st, "_owned_embed", None)
        if owned and host:
            row = profile.get("attachedTicks") or {}
            part, rate, duration = owned
            entity = self._new_entity(
                shot,
                point,
                host,
                kind="owned-embed",
                form=shot.form,
                end=self.t + duration,
                part=part,
                rate=rate,
                nextTick=self.t,
                radius=0.0,
                falloff=0.0,
                hostOnly=True,
                refresh="liveSource",
                origin=origin,
                sourceDestroyOnNextFire=bool(row.get("sourceDestroyOnNextFire")),
            )
            self._entity_event(entity, "tick", self.t)
            placed = True
        embedded = getattr(st, "_embedded", None)
        if embedded and host and not geometry.get("manual"):
            part, rate, duration = embedded
            row = profile.get("embedded") or {}
            entity = self._new_entity(
                shot,
                point,
                host,
                kind="embedded",
                form=shot.form,
                end=self.t + duration,
                part=part,
                rate=rate,
                nextTick=self.t,
                radius=0.0,
                falloff=0.0,
                hostOnly=True,
                refresh="liveVictimCO",
                origin=origin,
            )
            self._entity_event(entity, "tick", self.t)
            placed = True
        nox = getattr(st, "_nox_projectile", None)
        if nox and host:
            policy = profile["noxAvatarLifecycle"]
            tick, blast = nox
            rule = policy["attachedTicks"]
            delay = float(policy["radial"]["impact_delay_seconds"])
            entity = self._new_entity(
                shot,
                point,
                host,
                kind="nox",
                form=shot.form,
                end=self.t + delay,
                part=tick,
                blast=blast,
                radius=policy["radial"]["radius_m"],
                falloff=0.0,
                hostOnly=True,
                refresh="liveSource",
                origin=origin,
                tickAges=list(rule["tickAgesSeconds"]),
                tickWeights=list(rule["tickSurvivalWeights"]),
                born=self.t,
            )
            for age, weight in zip(
                rule["tickAgesSeconds"], rule["tickSurvivalWeights"]
            ):
                self.enqueue(
                    self.t + age,
                    "impact",
                    dict(
                        kind="entity",
                        entity=entity["id"],
                        token=0,
                        action="nox-tick",
                        weight=weight,
                    ),
                )
            self._entity_event(entity, "expire", entity["end"])
            placed = True
        lingering = getattr(st, "_lingering", None)
        if lingering:
            part, rate, duration = lingering
            row = profile.get("lingering") or {}
            host_only = (
                row.get("recipientPolicy")
                == "projectile-physically-attached-to-current-selected-victim"
            )
            (
                self.diagnostics.append(
                    "Torid EmbedAttack只对已证实宿主资格结算；来源半径用于实体显示/区域查询，不推定邻体同包全伤害"
                )
                if host_only
                else None
            )
            entity = self._new_entity(
                shot,
                point,
                host,
                kind="field",
                end=self.t + duration,
                part=part,
                rate=rate,
                nextTick=self.t,
                radius=float(row.get("radius_m") or 0.0),
                falloff=float(row.get("falloff_reduction") or 0.0),
                hostOnly=host_only,
                refresh="liveVictimCO" if row.get("liveVictimCO") else "snapshot",
                origin=origin,
            )
            self._entity_event(entity, "tick", self.t)
            placed = True
        periodic = profile.get("periodicTriggers") or []
        for attr, owned in [("_source_owned_fields", True), ("_finite_fields", False)]:
            packets = getattr(st, attr, ())
            rows = [
                r
                for r in periodic
                if r.get("defaultEnabled")
                and (
                    bool(r.get("expiresWithSourceOwner"))
                    if owned
                    else r.get("refreshPolicy")
                    == "independent-finite-fields-no-source-replacement"
                )
            ]
            if owned and len(packets) == len(rows) + 1 and profile.get("lingering"):
                rows = [profile["lingering"], *rows]
            if len(packets) != len(rows) and packets:
                raise UnsupportedArenaCombat("周期场部件与半径来源未一一对应")
            if owned:
                for old in self._entities().values():
                    if (
                        old["alive"]
                        and old["kind"] == "source-field"
                        and old["form"] == shot.form
                    ):
                        old["alive"] = False
                        self._field_record(old, "replace")
            for packet, row in zip(packets, rows):
                part, rate, duration, initial = packet
                radius = row.get("radius_m", row.get("radius"))
                if radius is None:
                    raise UnsupportedArenaCombat("周期场缺少半径来源")
                entity = self._new_entity(
                    shot,
                    point,
                    host if owned else None,
                    kind="source-field" if owned else "field",
                    form=shot.form,
                    end=self.t + duration,
                    part=part,
                    rate=rate,
                    nextTick=self.t,
                    initial=initial,
                    radius=float(radius),
                    falloff=float(row.get("falloff_reduction") or 0.0),
                    hostOnly=False,
                    refresh="liveSource" if owned else "snapshot",
                    origin=origin,
                )
                self._entity_event(entity, "tick", self.t)
                placed = True
        return placed

    def _zymos_spawn(self, entity):
        source = entity["shot"].stats
        host = self.actors.get(entity.get("host"))
        point = self._entity_point(entity)
        if host is None or host.dead or point is None:
            return
        state = {q["id"]: q["stacks"] for q in self.combat.sources}
        marginal = (
            self.combat.enervate.damage_marginal() if self.combat.enervate else {0: 1.0}
        )
        snapshot = source._zymos_carrier(state, marginal)
        packets = source._zymos_children(
            snapshot, state, max(0.0, source.multishot), marginal
        )
        from .event_profiles import base_profile

        profile = base_profile(
            self.context["engine"]["weapon"], self.context["engine"]["fire_mode"]
        )
        childpath = (profile.get("childSpawnAudit") or {}).get("child")
        native = spatial_weapons().get("projectileRecords", {}).get(childpath, {})
        speed = float(
            native.get("KinematicInitialSpeed")
            or self.c.setdefault("zymosChildSpeedAssumption", 30.0)
        )
        self.diagnostics.append(
            "Zymos子弹按已解析carrier/child有序暴击快照；选最近可见目标并朝其当前身体位置直线飞行，不保证原宿主存活或全部子弹命中"
        )
        for slot, (contact, blast, delay) in enumerate(packets):
            choices = sorted(
                (
                    a
                    for a in self.live
                    if not a.dead and self.scene.visible(point, add(a.pos, 0.85))
                ),
                key=lambda a: (distance(a.pos, point), a.id),
            )
            if not choices:
                break
            target = choices[slot % len(choices)]
            aim = add(target.pos, 0.85)
            dist = distance(point, aim)
            # Each child's finalized packet gets an independent shot without ammo.
            child = self.combat.fork_part_shot(
                entity["shot"], contact, self.t, "liveVictimCO"
            )
            child.radials = (blast,)
            child._arena_special_radial = float(
                native.get("DamageRadius")
                or self.c.setdefault("zymosChildRadiusAssumption", 3.3)
            )
            geo = {
                **self.geometry(entity["shot"]),
                "projectile": childpath,
                "speed": speed,
                "lifetime": float(native.get("MaxLife") or 3.0),
                "clusters": [],
                "chain": {},
                "stackable": None,
                "manual": None,
                "specialParts": (contact, blast),
                "radialComponents": {1},
                "directComponent": 0,
                "specialRadius": float(
                    native.get("DamageRadius")
                    or self.c.setdefault("zymosChildRadiusAssumption", 3.3)
                ),
            }
            self._launch_flight(
                child,
                point,
                tuple((aim[i] - point[i]) / max(EPS, dist) for i in range(3)),
                geo,
            )

    def _stug_children(self, entity):
        spec = entity["spec"]
        part = entity["parts"].get("child")
        if part is None:
            return
        parent_geometry = self.geometry(entity["shot"])
        source = parent_geometry.get("clusterSource") or {}
        native = source.get("fields") or {}
        speed = native.get("KinematicInitialSpeed")
        radius = native.get("DamageRadius")
        script = (
            parent_geometry["nativeProjectile"].get("OnProjectileDeathScript") or {}
        )
        if speed is None or radius is None:
            raise UnsupportedArenaCombat("Stug派生弹缺少当前速度/半径来源")
        active = sum(
            1
            for e in self._entities().values()
            if e["alive"] and e["kind"] == "stug-child"
        )
        limit = min(
            int(spec.get("childMaxCount", 5)),
            max(0, int(spec.get("childActiveLimit", 70)) - active),
        )
        count = (
            max(
                int(spec.get("childMinCount", 2)),
                int(limit * entity["stacks"] / spec["maxStack"]),
            )
            if limit > 1
            else limit
        )
        count = min(count, limit)
        point = self._entity_point(entity)
        self.c.setdefault(
            "stugChildGravity",
            9.81 * float(native.get("KinematicGravityMultiplier", 1.25)),
        )
        for i in range(count):
            phase = random_at(self.c["seed"], entity["id"] * 31 + i, 21)
            yaw = phase * math.tau
            low = float(script.get("_minLaunchPitch", 15))
            high = float(script.get("_maxLaunchPitch", 75))
            pitch = math.radians(
                low
                + (high - low) * random_at(self.c["seed"], entity["id"] * 31 + i, 22)
            )
            magnitude = float(speed) * (
                1.0
                + (float(script.get("_maxLaunchSpeedMult", 2)) - 1.0)
                * random_at(self.c["seed"], entity["id"] * 31 + i, 23)
            )
            velocity = (
                math.cos(yaw) * math.cos(pitch) * magnitude,
                math.sin(pitch) * magnitude,
                math.sin(yaw) * math.cos(pitch) * magnitude,
            )
            child = self._new_entity(
                entity["shot"],
                add(point, 0.08),
                None,
                kind="stug-child",
                end=self.t + float(spec["childLife"]),
                part=part,
                radius=float(radius),
                falloff=0.0,
                velocity=velocity,
                last=self.t,
                bounces=0,
                maxBounces=int(spec["childBounceCount"]),
                deathMultiplier=float(spec["childDeathMultiplier"]),
                restitution=float(native.get("KinematicRestitution", 0.75)),
                gravity=float(self.c["stugChildGravity"]),
                refresh="snapshot",
                origin=point,
            )
            self._entity_event(
                child,
                "flight",
                self.t + min(self.c["movementStep"], float(spec["childLife"])),
            )
        self.diagnostics.append(
            "Stug派生弹按原生速度/脚本pitch/寿命/2次爆炸反弹/死亡2.5倍与70活跃上限；重力换算为显式场景近似，非全部脚下命中"
        )

    def _process_entity(self, data):
        entity = self._entities().get(data["entity"])
        if entity is None or not entity["alive"] or entity["token"] != data["token"]:
            return
        if self._entity_point(entity) is None:
            return
        if data["action"] == "reload-impact":
            if self.scene.visible(entity["origin"], entity["point"]):
                for actor in list(self.live):
                    if (
                        not actor.dead
                        and distance(add(actor.pos, 0.85), entity["point"]) <= 0.45
                    ):
                        self._entity_damage(
                            entity, entity["parts"][0], only_id=actor.id, radius=0.45
                        )
                self._entity_damage(entity, entity["parts"][1])
            entity["alive"] = False
            self._field_record(entity, "explode")
        elif data["action"] == "grimoire":
            age = max(0.0, self.t - entity["last"])
            begin = entity["point"]
            travel = entity["speed"] * age
            hit = (
                self.scene.raycast(begin, entity["direction"], travel)
                if travel > EPS
                else None
            )
            entity["point"] = (
                hit.position
                if hit
                else tuple(begin[i] + entity["direction"][i] * travel for i in range(3))
            )
            entity["last"] = self.t
            part = entity["shot"].components[data["component"]]
            if data["chain"]:
                target = self.actors.get(entity["recipient"])
                point = entity["point"]
                if (
                    target
                    and not target.dead
                    and distance(add(target.pos, 0.85), point) <= 8.0
                    and self.scene.visible(point, add(target.pos, 0.85))
                ):
                    self._entity_damage(entity, part, only_id=target.id, radius=8.0)
            else:
                self._entity_damage(entity, part, radius=6.0)
            self._field_record(entity, "tick" if data["chain"] else "explode")
        elif data["action"] == "quanta-primary":
            point = entity["point"]
            origin = add(self.player.pos, 1.55)
            entity["paid"] = (
                self.scene.visible(origin, point)
                and self.combat.ammo + EPS >= data["cost"]
            )
            if entity["paid"]:
                self.combat.ammo = max(0.0, self.combat.ammo - data["cost"])
                self.combat._signal("on-fire", self.t)
        elif data["action"] == "quanta-explode":
            if entity.get("paid"):
                self._entity_damage(
                    entity, entity["shot"].components[data["component"]], radius=6.0
                )
            self._field_record(entity, "explode")
        elif data["action"] == "zymos":
            self._zymos_spawn(entity)
            entity["alive"] = False
            self._field_record(entity, "spawn-children")
        elif data["action"] == "merge":
            spec = entity["spec"]
            part = entity["parts"]["merge"]
            radius = (spec.get("mergeRadius") or [0, entity["radius"]])[-1]
            self._entity_damage(
                entity, part, scale=entity.pop("mergeScale", 1.0), radius=float(radius)
            )
        elif data["action"] == "singularity":
            interval = float(entity["spec"]["singularity"]["interval"])
            if self.t < entity["end"] - EPS:
                self._entity_damage(
                    entity, entity["parts"]["singularity"], scale=interval
                )
                self._entity_event(entity, "singularity", self.t + interval)
        elif data["action"] == "nox-tick":
            self._entity_damage(
                entity, entity["part"], scale=data["weight"], host_only=True
            )
        elif data["action"] == "flight":
            dt = self.t - entity["last"]
            start = entity["point"]
            velocity = entity["velocity"]
            end = tuple(
                start[i]
                + velocity[i] * dt
                - (0.5 * entity["gravity"] * dt * dt if i == 1 else 0.0)
                for i in range(3)
            )
            length = distance(start, end)
            direction = tuple((end[i] - start[i]) / max(EPS, length) for i in range(3))
            hit = self.scene.raycast(start, direction, length) if length > EPS else None
            entity["velocity"] = (
                velocity[0],
                velocity[1] - entity["gravity"] * dt,
                velocity[2],
            )
            entity["last"] = self.t
            # Spherical avatar proxy collision, separately from static triangle collision.
            avatar = None
            nearest = hit.distance if hit else length + EPS
            for actor in self.live:
                center = add(actor.pos, 0.85)
                offset = tuple(center[i] - start[i] for i in range(3))
                along = sum(offset[i] * direction[i] for i in range(3))
                perp = sum(v * v for v in offset) - along * along
                if perp > 0.45**2:
                    continue
                at = along - math.sqrt(max(0.0, 0.45**2 - perp))
                if EPS < at < nearest:
                    nearest = at
                    avatar = actor
            if hit or avatar:
                entity["point"] = tuple(
                    start[i] + direction[i] * nearest for i in range(3)
                )
                normal = (
                    hit.normal
                    if avatar is None
                    else tuple(
                        (entity["point"][i] - add(avatar.pos, 0.85)[i]) / 0.45
                        for i in range(3)
                    )
                )
                if entity["bounces"] < entity["maxBounces"]:
                    self._entity_damage(entity, entity["part"])
                    entity["bounces"] += 1
                v = entity["velocity"]
                dot = sum(v[i] * normal[i] for i in range(3))
                entity["velocity"] = tuple(
                    (v[i] - 2 * dot * normal[i]) * entity["restitution"]
                    for i in range(3)
                )
                entity["point"] = tuple(
                    entity["point"][i] + normal[i] * 0.04 for i in range(3)
                )
                self._field_record(entity, "bounce")
            else:
                entity["point"] = end
            if self.t >= entity["end"] - EPS:
                self._entity_damage(
                    entity, entity["part"], scale=entity["deathMultiplier"]
                )
                entity["alive"] = False
                self._field_record(entity, "explode")
            else:
                self._entity_event(
                    entity,
                    "flight",
                    min(entity["end"], self.t + self.c["movementStep"]),
                )
        elif data["action"] == "tick":
            if self.t >= entity["end"] - EPS:
                entity["alive"] = False
                self._field_record(entity, "expire")
                return
            if entity["kind"] == "stug":
                part = entity["parts"]["embed"]
                scale = 1.0 + (entity["stacks"] - 1.0) * part.stack_native_fraction
                self._entity_damage(entity, part, scale=scale)
                interval = float(entity["spec"]["embedInterval"])
            else:
                for _ in range(int(entity.pop("initial", 1))):
                    self._entity_damage(
                        entity, entity["part"], host_only=entity.get("hostOnly", False)
                    )
                interval = 1.0 / entity["rate"]
            entity["nextTick"] = self.t + interval
            self._field_record(entity, "tick")
            self._entity_event(entity, "tick", entity["nextTick"])
        elif data["action"] == "expire":
            if entity["kind"] == "stug":
                part = entity["parts"]["explosion"]
                scale = 1.0 + (entity["stacks"] - 1.0) * part.stack_native_fraction
                self._entity_damage(
                    entity, part, scale=scale, radius=entity.get("explosionRadius")
                )
                if entity["spec"].get("child"):
                    self._stug_children(entity)
            elif entity["kind"] == "orb":
                self._entity_damage(
                    entity, entity["parts"]["explosion"], scale=entity["stacks"]
                )
            elif entity["kind"] == "nox":
                self._entity_damage(entity, entity["blast"], host_only=True)
            elif entity["kind"] == "mine":
                for part, radius, falloff in entity["blast"]:
                    entity["falloff"] = falloff
                    self._entity_damage(entity, part, radius=radius)
            entity["alive"] = False
            self._field_record(entity, "explode")

    def _launch_flight(
        self, shot, origin, direction, geometry, *, lifetime=None, child=False
    ):
        speed = geometry["speed"] * max(EPS, shot.stats.projectile_speed_multiplier)
        life = geometry["lifetime"] if lifetime is None else lifetime
        cap = min(geometry["range"], speed * life)
        # Curved children sweep their own next segment, not a launch ray past a floor.
        wall = None if child else self.scene.raycast(origin, direction, cap)
        maximum = wall.distance if wall else cap
        endpoint = tuple(origin[i] + direction[i] * maximum for i in range(3))
        flight = dict(
            shot=shot,
            origin=origin,
            point=endpoint,
            geometry=geometry,
            direction=direction,
            speed=speed,
            maximum=maximum,
            wall=wall is not None,
            replayIndex=len(self.replay["shots"]),
            travelled=0.0,
            remaining=geometry["puncture"],
            hit=set(),
            previous={a.id: a.pos for a in self.live},
            last=self.t,
            launchedAt=self.t,
        )
        if child:
            flight.update(
                gravity=float(self.c.get("clusterGravity", 9.81)),
                life=life,
                velocity=tuple(speed * v for v in direction),
                position=origin,
            )
        self.replay["shots"].append(
            [round(self.t, 6), *origin, *endpoint, round(maximum / speed, 6)]
        )
        shot._arena_branches = getattr(shot, "_arena_branches", 0) + 1
        self.enqueue(
            self.t + min(self.c["movementStep"], maximum / speed), "impact", flight
        )
        return flight

    def _spawn_children(self, shot, data, point):
        geometry = data["geometry"]
        clusters = geometry.get("clusters") or []
        if not clusters or geometry.get("childFlight"):
            return
        source = geometry["nativeProjectile"]
        child = geometry["clusterSource"]
        native = child["fields"]
        specs = self.radial_specs(shot)
        count = len(
            [spec for spec in specs if spec["child"] is not None and spec["contact"]]
        )
        forward = data.get("direction", (0.0, 0.0, 1.0))
        horizontal = math.hypot(forward[0], forward[2])
        forward = (
            (forward[0] / horizontal, 0.0, forward[2] / horizontal)
            if horizontal > EPS
            else (0.0, 0.0, 1.0)
        )
        side = (forward[2], 0.0, -forward[0])
        base = source.get("ClusterDirection") or self.c["clusterDirectionAssumption"]
        elevation = math.atan2(
            float(base[1]), max(EPS, math.hypot(float(base[0]), float(base[2])))
        )
        arc = math.radians(float(source.get("ClusterArc", 0.0)))
        shift = math.radians(float(source.get("ClusterArcShift", 0.0)))
        # Native arc coordinate frame is not recovered. This explicit deterministic
        # fan is a scene policy and never suppressed by no weapon aim spread.
        phase = random_at(self.c["seed"], shot.id, 11)
        for index in range(count):
            fraction = (index + phase) / max(1, count)
            yaw = shift + (fraction - 0.5) * arc
            direction = tuple(
                math.cos(elevation)
                * (forward[i] * math.cos(yaw) + side[i] * math.sin(yaw))
                + (math.sin(elevation) if i == 1 else 0.0)
                for i in range(3)
            )
            components = [s for s in specs if s["child"] == index]
            contact = next(s for s in components if s["contact"])
            radial = next(s for s in components if not s["contact"])
            life = float(native["MaxLife"]) + (
                random_at(self.c["seed"], shot.id * 257 + index, 12) * 2 - 1
            ) * float(native.get("MaxLifeVariance") or 0.0)
            childspeed = float(
                native.get("KinematicInitialSpeed")
                or self.c.get("clusterSpeedAssumption", 8.0)
            )
            if native.get("KinematicMaxSpeed"):
                childspeed = min(childspeed, float(native["KinematicMaxSpeed"]))
            if childspeed <= 0:
                raise UnsupportedArenaCombat("场景子弹初速必须为正")
            childgeo = {
                **geometry,
                "projectile": child["path"],
                "speed": childspeed,
                "lifetime": max(0.01, life),
                "puncture": float(native.get("PunctureDepth") or 0.0),
                "infinitePuncture": bool(native.get("InfinitePunctureDepth")),
                "ignoresAvatars": False,
                "traceRadius": 0.0,
                "beamRadius": 0.0,
                "childFlight": True,
                "directComponent": contact["component"],
                "radialComponents": {radial["component"]},
                "chain": {},
                "clusters": [],
            }
            self._launch_flight(
                shot,
                add(point, 0.08),
                direction,
                childgeo,
                lifetime=max(0.01, life),
                child=True,
            )
        if native.get("KinematicNoise"):
            self.diagnostics.append(
                "集群子弹KinematicNoise未恢复原生运动学；固定seed弧扇和场景重力替代，未把子弹全部归到同一命中点"
            )

    def _special_launch(self, shot, geometry, origin, aim):
        if geometry.get("grimoire"):
            specs = self.radial_specs(shot)
            if not specs:
                self.diagnostics.append(
                    "Grimoire未选择single-occupant资格窗口：仅发射一枚无接触球，不假设周期命中"
                )
                return False
            choices = sorted(
                (a for a in self.live if not a.dead),
                key=lambda a: (distance(self.aimpoint(a)[0], aim["point"]), a.id),
            )
            recipient = choices[0].id if choices else None
            delta = tuple(aim["point"][i] - origin[i] for i in range(3))
            length = distance(origin, aim["point"])
            direction = tuple(x / max(EPS, length) for x in delta)
            entity = self._new_entity(
                shot,
                origin,
                None,
                kind="grimoire",
                end=self.t + 6.0,
                born=self.t,
                radius=6.0,
                falloff=0.8,
                origin=origin,
                direction=direction,
                speed=geometry["speed"],
                recipient=recipient,
                refresh="liveSource",
                last=self.t,
            )
            for spec in specs:
                self.enqueue(
                    self.t + spec["delay"],
                    "impact",
                    dict(
                        kind="entity",
                        entity=entity["id"],
                        token=0,
                        action="grimoire",
                        component=spec["component"],
                        chain=spec.get("orbChain", False),
                    ),
                )
            self._entity_event(entity, "expire", entity["end"] + 0.000001)
            self.diagnostics.append(
                "Grimoire单球沿合法世界射线移动；single-occupant只查询原选中受害者的当前距离/视线，过期区域只生成一次"
            )
            return True
        strategy = geometry.get("quanta")
        if strategy:
            point = aim["point"]
            entity = self._new_entity(
                shot,
                point,
                None,
                kind="quanta",
                end=self.t + float(strategy["impactDelaySeconds"]),
                radius=6.0,
                origin=origin,
                falloff=0.0,
                refresh="snapshot",
            )
            # Launch action and the paid primary pulse are separate source events.
            self.enqueue(
                self.t + float(strategy["primaryFireSeconds"]),
                "impact",
                dict(
                    kind="entity",
                    entity=entity["id"],
                    token=0,
                    action="quanta-primary",
                    cost=float(strategy["primaryAmmoCost"]),
                ),
            )
            for spec in self.radial_specs(shot):
                self.enqueue(
                    self.t + spec["delay"],
                    "impact",
                    dict(
                        kind="entity",
                        entity=entity["id"],
                        token=0,
                        action="quanta-explode",
                        component=spec["component"],
                    ),
                )
            self._entity_event(
                entity,
                "expire",
                self.t + max(s["delay"] for s in self.radial_specs(shot)) + 0.000001,
            )
            self.diagnostics.append(
                "Quanta shoot为显式定点cube放置/主脉冲策略；额外主脉冲付费且检查射线，爆炸仅实际半径内受害者，不复用全部目标重叠假设"
            )
            return True
        return False

    def _reload_delivery(self, preview, reload_state, aim):
        thrown = getattr(preview.stats, "_reload_projectiles", None)
        if not thrown:
            return
        from .event_profiles import reload_projectiles

        source = reload_projectiles(self.context["engine"]["weapon"])
        empty = bool(reload_state[1])
        key = "empty" if empty else "partial"
        parts = thrown.get(key, ())
        rule = (source or {}).get(key, {})
        if len(parts) != 2 or not rule.get("explosion"):
            raise UnsupportedArenaCombat("装填投射物缺少已解析接触/爆炸对子")
        origin = add(self.player.pos, 1.55)
        point = tuple(aim["point"])
        radius = float(rule["explosion"]["radius"])
        falloff = float(rule["explosion"]["falloff"])
        at = self.t + (reload_state[0] - self.t) * float(thrown["landsAt"])
        entity = self._new_entity(
            preview,
            point,
            None,
            kind="reload-grenade",
            end=at,
            radius=radius,
            falloff=falloff,
            parts=parts,
            origin=origin,
            refresh="snapshot",
        )
        self._entity_event(entity, "reload-impact", at)
        self.replay["shots"].append(
            [round(self.t, 6), *origin, *point, round(at - self.t, 6)]
        )
        self.diagnostics.append(
            "Catabolyst换弹弹体按empty/partial快照与landsAt装填时钟；落点取投掷时瞄点并检查遮挡，接触仅实际身体代理范围，不继承主武器多重"
        )

    def fire(self, aim):
        preview = self.combat.preview(self.t)
        previous_reload = self.combat._reload
        shot = self.combat.prepare_shot(self.t, self.c["headshots"])
        self.drain()
        if shot is None:
            if preview and self.combat._reload is not None and previous_reload is None:
                self._reload_delivery(preview, self.combat._reload, aim)
            self.next_fire = max(self.t + 0.001, self.combat.next_attack_time(self.t))
            return
        for entity in self._entities().values():
            if entity["alive"] and entity.get("sourceDestroyOnNextFire"):
                entity["alive"] = False
                self._field_record(entity, "replace")
        origin = add(self.player.pos, 1.55)
        geometry = self.geometry(shot)
        if shot.physical_lanes:
            self.combat.fire_shot(shot, self.t)
            self.stats["shots"] += 1
            for ordinal, lane in enumerate(shot.physical_lanes):
                lane_geometry = self.geometry(lane)
                expected, _ = self.recipients(
                    lane, origin, aim["point"], lane_geometry, planning=True
                )
                key = (shot.id, ordinal)
                lane._arena_commit_key = key
                damage = {}
                for actor, component, head, scale, at in expected:
                    damage[actor.id] = damage.get(actor.id, 0.0) + self.combat.estimate(
                        lane, actor.id, component, head, scale, at
                    )
                self.committed[key] = damage
                delta = tuple(aim["point"][i] - origin[i] for i in range(3))
                length = distance(origin, aim["point"])
                self._launch_flight(
                    lane,
                    origin,
                    tuple(v / max(EPS, length) for v in delta),
                    lane_geometry,
                )
            shot.finished = True
            self.next_fire = max(self.t + 0.001, self.combat.next_attack_time(self.t))
            return
        expected, _ = self.recipients(
            shot, origin, aim["point"], geometry, planning=True
        )
        committed = {}
        for actor, component, head, scale, at in expected:
            committed[actor.id] = committed.get(actor.id, 0.0) + self.combat.estimate(
                shot, actor.id, component, head, scale, at
            )
        self.committed[shot.id] = committed
        self.radial_specs(
            shot
        )  # fail explicitly before paying ammo for unsupported geometry
        self.combat.fire_shot(shot, self.t)
        self.stats["shots"] += 1
        if self._special_launch(shot, geometry, origin, aim):
            self.next_fire = max(self.t + 0.001, self.combat.next_attack_time(self.t))
            return
        if not geometry["projectile"]:
            contacts, point = self.shot_hits(origin, aim["point"], shot, geometry)
            self.replay["shots"].append([round(self.t, 6), *origin, *point, 0.0])
            shot._arena_branches = 1
            self.enqueue(
                self.t,
                "impact",
                dict(
                    shot=shot,
                    origin=origin,
                    point=point,
                    geometry=geometry,
                    direct=contacts,
                ),
            )
        else:
            length = distance(origin, aim["point"])
            if length < EPS:
                raise UnsupportedArenaCombat("弹体发射方向长度为零")
            direction = tuple((aim["point"][i] - origin[i]) / length for i in range(3))
            self._launch_flight(shot, origin, direction, geometry)
            self.diagnostics.append(
                "弹体移动目标碰撞采用不超过movementStep的相对线段扫掠；不在命中时重放发射射线"
            )
        self.next_fire = max(self.t + 0.001, self.combat.next_attack_time(self.t))

    def impact(self, data):
        if data.get("kind") == "entity":
            self._process_entity(data)
            return
        shot = data["shot"]
        origin = data["origin"]
        geometry = data["geometry"]
        before = self.stats["kills"]
        self.protection()
        retire = True
        contacts = data.get("direct")
        point = data["point"]
        if data.get("delayHost") is not None:
            host = self.actors.get(data["delayHost"])
            if host and not host.dead:
                point = tuple(host.pos[i] + data["delayOffset"][i] for i in range(3))
            else:
                geometry = {**geometry, "radialComponents": set()}
        if "direction" in data:
            direction = data["direction"]
            start_distance = data["travelled"]
            end_distance = min(
                data["maximum"],
                start_distance + data["speed"] * max(0.0, self.t - data["last"]),
            )
            begin = tuple(origin[i] + direction[i] * start_distance for i in range(3))
            end = tuple(origin[i] + direction[i] * end_distance for i in range(3))
            if "gravity" in data:
                age = min(data["life"], self.t - data["launchedAt"])
                begin = data["position"]
                end = tuple(
                    origin[i]
                    + data["velocity"][i] * age
                    - (0.5 * data["gravity"] * age * age if i == 1 else 0.0)
                    for i in range(3)
                )
                length = distance(begin, end)
                if length > EPS:
                    wall = self.scene.raycast(
                        begin,
                        tuple((end[i] - begin[i]) / length for i in range(3)),
                        length,
                    )
                    if wall:
                        end = wall.position
                        data["wall"] = True
                        data["maximum"] = end_distance
                data["position"] = end
            span = distance(begin, end)
            ordered = []
            for actor in self.live:
                if actor.dead or actor.id in data["hit"]:
                    continue
                target = self.combat.targets[actor.id]
                old = data["previous"].get(actor.id, actor.pos)
                born = (actor.tape or {}).get("birth", data["last"])
                active_from = max(
                    0.0,
                    min(1.0, (born - data["last"]) / max(EPS, self.t - data["last"])),
                )
                proxies = (
                    [(0.85, 0.45, False)]
                    if actor.drone
                    else [(0.45, 0.38, False), (0.95, 0.38, False), (1.25, 0.30, False)]
                )
                if not actor.drone and any(
                    p.get("part") == "HEAD" for p in target.record.get("hitProxies", ())
                ):
                    proxies.append((1.65, 0.23, True))
                candidates = []
                for height, radius, head in proxies:
                    a = add(old, height)
                    b = add(actor.pos, height)
                    relative = tuple(begin[i] - a[i] for i in range(3))
                    velocity = tuple(
                        (end[i] - begin[i]) - (b[i] - a[i]) for i in range(3)
                    )
                    r = radius + geometry["traceRadius"]
                    aa = sum(x * x for x in velocity)
                    bb = 2 * sum(relative[i] * velocity[i] for i in range(3))
                    cc = sum(x * x for x in relative) - r * r
                    if aa < EPS:
                        if cc <= 0:
                            candidates.append((active_from, 1.0, head))
                        continue
                    discriminant = bb * bb - 4 * aa * cc
                    if discriminant < 0:
                        continue
                    root = math.sqrt(discriminant)
                    entry = max(active_from, (-bb - root) / (2 * aa))
                    exit = min(1.0, (-bb + root) / (2 * aa))
                    if entry <= exit and entry <= 1.0:
                        candidates.append((entry, (-bb + root) / (2 * aa), head))
                if candidates:
                    first = min(candidates, key=lambda x: (x[0], x[2]))
                    ordered.append(
                        (
                            first[0],
                            actor.id,
                            actor,
                            first[2],
                            max(
                                0.001, (max(x[1] for x in candidates) - first[0]) * span
                            ),
                        )
                    )
            ordered.sort(key=lambda row: (row[0], row[1]))
            contacts = []
            retire = end_distance >= data["maximum"] - EPS
            point = end
            for fraction, _, actor, head, thickness in ordered:
                contacts.append((actor, head, start_distance + span * fraction))
                data["hit"].add(actor.id)
                if (
                    shot.radials
                    or geometry.get("stackable")
                    or geometry.get("manual")
                    or getattr(shot.stats, "_lingering", None)
                    or (
                        not geometry["infinitePuncture"]
                        and not geometry["ignoresAvatars"]
                        and data["remaining"] + EPS < thickness
                    )
                ):
                    point = mix(begin, end, fraction)
                    retire = True
                    break
                if not geometry["infinitePuncture"] and not geometry["ignoresAvatars"]:
                    data["remaining"] -= thickness
            data["travelled"] = end_distance
            data["last"] = self.t
            data["previous"] = {a.id: a.pos for a in self.live}
        self.combat.begin_impact(shot, self.t)
        if "direction" in data and not retire:
            recipients = [
                (
                    actor,
                    geometry.get("directComponent", 0),
                    head and geometry.get("directComponent", 0) == 0,
                    1.0,
                    at,
                )
                for actor, head, at in contacts
            ]
        elif (
            "direction" in data
            and not contacts
            and not data["wall"]
            and not geometry.get("childFlight")
        ):
            recipients = []
            if shot.radials:
                self.diagnostics.append(
                    "范围弹体寿命/场景射程到期但未首碰：未证明到期引爆策略，不生成虚构爆炸"
                )
        else:
            recipients, _ = self.recipients(
                shot, origin, point, geometry, direct=contacts, impact=point
            )
        if geometry.get("stackable") or geometry.get("manual"):
            recipients = []
        for actor, component, head, scale, d in recipients:
            self.combat.hit(
                shot,
                actor.id,
                component,
                head=head,
                distance=d,
                radial_scale=scale,
                t=self.t,
            )
        # Delayed components are explicit future area queries at the fixed impact
        # point. Child branches retain their original component indices and shooter.
        held = False
        if retire and not data.get("delayed"):
            if (
                contacts
                or data.get("wall")
                or geometry.get("childFlight")
                or geometry.get("stackable")
                or not geometry.get("projectile")
            ):
                held = self._place_lifecycle(shot, geometry, point, contacts, origin)
                self._spawn_children(shot, data, point)
                for spec in self.radial_specs(shot):
                    selected = geometry.get("radialComponents")
                    if (
                        spec.get("headOnly")
                        and not any(head for _, head, _ in contacts)
                    ) or (
                        spec.get("bodyOnly") and any(head for _, head, _ in contacts)
                    ):
                        continue
                    if (
                        spec["child"] is not None
                        or spec["contact"]
                        or spec["delay"] <= EPS
                        or (selected is not None and spec["component"] not in selected)
                    ):
                        continue
                    shot._arena_branches = getattr(shot, "_arena_branches", 1) + 1
                    future = {
                        **geometry,
                        "radialComponents": {spec["component"]},
                        "beamRadius": 0.0,
                        "clusters": [],
                        "chain": {},
                    }
                    delayed = dict(
                        shot=shot,
                        origin=origin,
                        point=point,
                        geometry=future,
                        direct=[],
                        delayed=True,
                    )
                    if spec.get("headOnly") and contacts:
                        host = contacts[0][0]
                        delayed.update(
                            delayHost=host.id,
                            delayOffset=tuple(point[i] - host.pos[i] for i in range(3)),
                        )
                    self.enqueue(self.t + spec["delay"], "impact", delayed)
        if retire:
            shot._arena_branches = max(0, getattr(shot, "_arena_branches", 1) - 1)
        self.combat.finish_impact(
            shot, self.t, retire=retire and shot._arena_branches == 0 and not held
        )
        self.drain()
        if retire and shot._arena_branches == 0:
            self.committed.pop(getattr(shot, "_arena_commit_key", shot.id), None)
        if retire and "direction" in data:
            self.replay["shots"][data["replayIndex"]] = [
                round(data["launchedAt"], 6),
                *origin,
                *point,
                round(self.t - data["launchedAt"], 6),
            ]
        self.stats["maxGroupKill"] = max(
            self.stats["maxGroupKill"], self.stats["kills"] - before
        )
        if not retire:
            self.enqueue(
                self.t
                + min(
                    self.c["movementStep"],
                    (data["maximum"] - data["travelled"]) / data["speed"],
                ),
                "impact",
                data,
            )

    def plan(self):
        if self.flow_node != self.player.node or not self.flows:
            self.flows = {
                "enemy": self.scene.search(self.player.node, "enemy", reverse=True)
            }
            self.flow_node = self.player.node
        if any(actor.drone for actor in self.live) and "drone" not in self.flows:
            self.flows["drone"] = self.scene.search(
                self.player.node, "drone", reverse=True
            )
        if not hasattr(self, "fallback_staging"):
            self.fallback_staging = {}
        ground_components = self.scene.movement_components("enemy")
        for actor in self.live:
            if actor.edge:
                continue
            flow = self.flows["drone" if actor.drone else "enemy"]
            actor.unreachable = not math.isfinite(flow.d[actor.node])
            if actor.node == self.player.node:
                d = distance(actor.pos, self.player.pos)
                actor.route = []
                if d > 1.4:
                    actor.route = [
                        self.local_edge(actor, mix(self.player.pos, actor.pos, 1.3 / d))
                    ]
            elif not actor.unreachable:
                actor.route = route(flow, actor.node, 4)
            else:
                component = ground_components[actor.node]
                staged = self.fallback_staging.get(component)
                if (
                    staged is None
                    or distance(staged["playerPosition"], self.player.pos) > 6.0
                ):
                    candidates = sorted(
                        (i for i, c in enumerate(ground_components) if c == component),
                        key=lambda i: (
                            distance(self.scene.nodes[i], self.player.pos),
                            i,
                        ),
                    )
                    visible = [
                        i
                        for i in candidates[:48]
                        if self.scene.visible(
                            add(self.scene.nodes[i], 0.85), add(self.player.pos, 1.55)
                        )
                    ]
                    lanes = []
                    for node in visible or candidates:
                        if all(
                            distance(self.scene.nodes[node], self.scene.nodes[old])
                            >= 0.8
                            for old in lanes
                        ):
                            lanes.append(node)
                            if len(lanes) >= 4:
                                break
                    staged = {
                        "playerPosition": self.player.pos,
                        "lanes": lanes or [actor.node],
                    }
                    self.fallback_staging[component] = staged
                # Cache reverse ground flows by actual source component/goal,
                # not moving player's triangle. No collision check is skipped.
                lanes = staged["lanes"]
                offset = actor.id % len(lanes)
                choices = lanes[offset:] + lanes[:offset]
                nearest = next(
                    (
                        node
                        for node in choices
                        if all(
                            other is actor
                            or other.dead
                            or distance(self.scene.nodes[node], other.pos) >= 0.8
                            for other in self.live
                        )
                    ),
                    choices[0],
                )
                key = (component, nearest)
                if key not in self.fallback:
                    self.fallback[key] = self.scene.search(
                        nearest, "enemy", reverse=True
                    )
                    if len(self.fallback) > 128:
                        self.fallback.pop(next(iter(self.fallback)))
                actor.route = route(self.fallback[key], actor.node, 4)
        if (
            self.c["movement"] != "fixed"
            and not self.player.edge
            and not self.player.route
            and self.live
        ):
            current = self.combat.preview(self.t)
            effective_range = (
                self.geometry(current)["range"]
                if current
                else self.c["rangeAssumption"]
            )
            if not any(
                not self.combat.targets[a.id].protected
                and distance(a.pos, self.player.pos) <= effective_range
                and self.scene.visible(add(self.player.pos, 1.55), self.aimpoint(a)[0])
                for a in self.live
            ):
                search = self.scene.search(
                    self.player.node,
                    "walking" if self.c["movement"] == "walking" else "player",
                )
                candidates = [a for a in self.live if math.isfinite(search.d[a.node])]
                if candidates:
                    target = min(
                        candidates,
                        key=lambda a: (
                            search.d[a.node] * (0.65 if a.drone else 1.0),
                            a.id,
                        ),
                    )
                    paths = route(search, target.node)
                    for i, edge in enumerate(paths):
                        if distance(
                            self.scene.nodes[edge.node], target.pos
                        ) <= effective_range and self.scene.visible(
                            add(self.scene.nodes[edge.node], 1.55),
                            self.aimpoint(target)[0],
                        ):
                            paths = paths[: i + 1]
                            break
                    self.player.route = paths or (
                        [self.local_edge(self.player, target.pos)]
                        if distance(self.player.pos, target.pos) > 1
                        else []
                    )
                else:
                    # An enemy's floor can remain source-unreachable while a
                    # legal firing position is reachable. Search only existing
                    # player nodes; never add an edge across the blocked floor.
                    reachable = sorted(
                        (i for i, cost in enumerate(search.d) if math.isfinite(cost)),
                        key=lambda i: (search.d[i], i),
                    )
                    vantage = None
                    targets = sorted(
                        (
                            actor
                            for actor in self.live
                            if not self.combat.targets[actor.id].protected
                        ),
                        key=lambda actor: (
                            distance(actor.pos, self.player.pos),
                            actor.id,
                        ),
                    )
                    for node in reachable:
                        if node == self.player.node:
                            continue
                        position = self.scene.nodes[node]
                        if any(
                            distance(position, target.pos) <= effective_range
                            and self.scene.visible(
                                add(position, 1.55), self.aimpoint(target)[0]
                            )
                            for target in targets
                        ):
                            vantage = node
                            break
                    if vantage is not None:
                        self.player.route = route(search, vantage)
                        self.stats["firingPositionPlans"] = (
                            self.stats.get("firingPositionPlans", 0) + 1
                        )
                    else:
                        self.stats["failedPathPlans"] += 1
        self.next_plan = self.t + 0.5

    def local_edge(self, actor, end):
        length = distance(actor.pos, end)
        return Edge(
            actor.node,
            actor.node,
            (actor.pos, tuple(end)),
            "walk",
            length / 6,
            True,
            length / 3.6,
            length,
            key="local:" + str(actor.node) + ":" + ",".join(f"{v:.4f}" for v in end),
        )

    def _crowd_segment_clear(self, actor, begin, end, *, priority_only=False):
        """Continuous source-space actor separation, allowing an overlap escape."""
        delta = tuple(end[i] - begin[i] for i in range(3))
        squared = sum(v * v for v in delta)
        for other in self.live:
            if other is actor or other.dead or (priority_only and other.id >= actor.id):
                continue
            old = distance(begin, other.pos)
            ratio = (
                max(
                    0.0,
                    min(
                        1.0,
                        sum((other.pos[i] - begin[i]) * delta[i] for i in range(3))
                        / squared,
                    ),
                )
                if squared > EPS
                else 0.0
            )
            near = mix(begin, end, ratio)
            minimum = distance(near, other.pos)
            # Already overlapping actors may move strictly outward; they may
            # never move closer or use an overlap as permission to cross.
            required = min(0.6, old)
            if minimum < required - 1e-6 or (
                old < 0.6 and distance(end, other.pos) < old + 1e-6
            ):
                return False
        return True

    def _yield_crowded_edge(self, actor, now):
        """Replace a blocked ground edge only with a fully checked local walk.

        Starts at actual feet, never teleports to actor.node (which can be the
        old endpoint while mid-edge). No retreat exists => keep the source edge
        and retry later. This is collision-qualified local avoidance, not a new
        inter-component route or ordinary-enemy parkour.
        """
        if (
            actor.drone
            or actor.edge is None
            or actor.edge["kind"]
            not in (
                "walk",
                "stairs",
                "step",
                "step-down",
                "crowd-yield",
                "door",
                "source-floor-step",
            )
        ):
            return False
        actor.crowd_retry_after = now + 1.0
        components = self.scene.movement_components("enemy")
        component = components[actor.node]
        origin = actor.pos
        candidates = sorted(
            (
                i
                for i, point in enumerate(self.scene.nodes)
                if components[i] == component
                and 0.45 <= distance(origin, point) <= 2.5
                and abs(origin[1] - point[1]) <= 0.6
                and all(
                    other is actor or other.dead or distance(point, other.pos) >= 0.75
                    for other in self.live
                )
            ),
            key=lambda i: (distance(origin, self.scene.nodes[i]), i),
        )[:12]
        for node in candidates:
            target = self.scene.nodes[node]
            count = max(2, int(distance(origin, target) / 0.12) + 1)
            points = [origin]
            valid = True
            for index in range(1, count + 1):
                expected = mix(origin, target, index / count)
                support = self.scene.ground_support(
                    expected, max_drop=0.5, max_rise=0.25
                )
                if (
                    support is None
                    or abs(support.position[1] - expected[1]) > 0.35
                    or abs(support.normal[1]) < 0.5
                ):
                    valid = False
                    break
                point = tuple(support.position)
                if abs(
                    point[1] - points[-1][1]
                ) > 0.35 or not self._crowd_segment_clear(actor, points[-1], point):
                    valid = False
                    break
                points.append(point)
            if (
                not valid
                or not self.scene.check_motion(points, ground_step=True)["clear"]
            ):
                continue
            length = sum(distance(a, b) for a, b in zip(points, points[1:]))
            if length <= EPS:
                continue
            actor.edge = {
                "points": points,
                "index": 1,
                "node": node,
                "speed": 3.6,
                "kind": "crowd-yield",
            }
            actor.route = []
            actor.crowd_blocked_seconds = 0.0
            self.stats["crowdDetours"] = self.stats.get("crowdDetours", 0) + 1
            return True
        return False

    def move_actor(self, actor, dt, start):
        if actor.id == -1 and self.c["movement"] == "fixed":
            actor.route.clear()
            actor.edge = None
            return 0.0
        remaining = dt
        elapsed = 0.0
        while remaining > EPS:
            if actor.edge is None:
                if not actor.route:
                    break
                link = actor.route.pop(0)
                if link.key in self.scene.disabled:
                    actor.route = []
                    break
                points = list(link.points)
                if distance(actor.pos, points[0]) > 0.01:
                    points = [actor.pos, *points]
                if link.key not in self.motion_cache:
                    self.motion_cache[link.key] = self.scene.check_motion(
                        points,
                        ground_step=link.kind
                        in (
                            "walk",
                            "stairs",
                            "step",
                            "step-down",
                            "crowd-yield",
                            "door",
                            "source-floor-step",
                        ),
                    )["clear"]
                if not self.motion_cache[link.key]:
                    self.scene.disabled.add(link.key)
                    actor.route = []
                    self.flows.clear()
                    self.fallback.clear()
                    if hasattr(self, "fallback_staging"):
                        self.fallback_staging.clear()
                    self.stats["failedPathPlans"] += 1
                    break
                length = sum(distance(a, b) for a, b in zip(points, points[1:]))
                duration = link.time(
                    "player" if actor.id == -1 else "drone" if actor.drone else "enemy"
                )
                actor.edge = dict(
                    points=points,
                    index=1,
                    node=link.node,
                    speed=length / max(EPS, duration),
                    kind=link.kind,
                )
                if actor.id == -1:
                    self.replay["moves"].append(
                        dict(
                            start=round(start + elapsed, 6),
                            duration=round(duration, 6),
                            kind=link.kind,
                            points=points,
                        )
                    )
                    if link.kind in ("bullet-jump", "drop", "jump-down"):
                        self.stats["jumps"] += 1
                        self.stats[
                            (
                                "drops"
                                if link.kind in ("drop", "jump-down")
                                else "bulletJumps"
                            )
                        ] += 1
                        if points[-1][1] > points[0][1] + 1:
                            self.stats["upwardJumps"] += 1
            edge = actor.edge
            end = edge["points"][edge["index"]]
            length = distance(actor.pos, end)
            slow = 1.0
            if actor.id != -1:
                victim = self.combat.targets[actor.id]
                if victim.frozen_until > start + elapsed:
                    return dt - remaining
            speed = edge["speed"] * slow
            travel = min(length, speed * remaining)
            spent = travel / max(EPS, speed)
            candidate = mix(actor.pos, end, travel / length) if length > EPS else end
            if actor.id != -1 and not self._crowd_segment_clear(
                actor, actor.pos, candidate, priority_only=True
            ):
                self.stats["crowdWaitSeconds"] += remaining
                actor.crowd_blocked_seconds = (
                    getattr(actor, "crowd_blocked_seconds", 0.0) + remaining
                )
                if (
                    actor.crowd_blocked_seconds >= 0.8 - EPS
                    and start + elapsed >= getattr(actor, "crowd_retry_after", -1.0)
                ):
                    if self._yield_crowded_edge(actor, start + elapsed):
                        continue
                break
            actor.crowd_blocked_seconds = 0.0
            actor.travelled += distance(actor.pos, candidate)
            actor.pos = tuple(candidate)
            remaining -= spent
            elapsed += spent
            if length <= travel + EPS:
                edge["index"] += 1
                if edge["index"] >= len(edge["points"]):
                    actor.node = edge["node"]
                    actor.edge = None
                self.record(actor, start + elapsed)
            else:
                break
        return dt - remaining

    def move(self, end):
        dt = end - self.t
        if dt <= 0:
            return
        self.stats["playerTravelSeconds"] += self.move_actor(self.player, dt, self.t)
        for actor in self.live:
            if actor.unreachable:
                self.stats["enemyUnreachableSeconds"] += dt
            self.move_actor(actor, dt, self.t)
            self.combat.targets[actor.id].position = actor.pos
        self.t = end

    def run(self):
        started = time.perf_counter()
        self.start_wave()
        reason = ""
        status = "completed"
        steps = 0
        last_progress = started
        while not reason:
            steps += 1
            if self.cancelled():
                status = "cancelled"
                reason = "已取消"
                break
            if time.perf_counter() - started > self.c["wallSeconds"]:
                status = "limited"
                reason = "达到计算耗时预算"
                break
            if steps > 2_000_000:
                status = "limited"
                reason = "达到事件数量预算"
                break
            if self.wave_pending and self.t >= self.wait_until - EPS:
                self.start_wave()
            self.protection()
            self.drain(self.combat.advance(self.t))
            while self.events and self.events[0][0] <= self.t + EPS:
                steps += 1
                if steps > 2_000_000:
                    status, reason = "limited", "达到事件数量预算"
                    break
                _, _, kind, data = heapq.heappop(self.events)
                if kind == "impact":
                    self.impact(data)
            # Existing impacts/ticks at the cutoff settle; no new attacks are
            # launched at the absolute end of the requested window.
            if reason:
                break
            at_end = self.t >= self.c["seconds"] - EPS
            if not self.wave_pending and not at_end:
                if self.next_spawn <= self.t + EPS:
                    self.spawn()
                if self.t >= self.next_plan - EPS:
                    self.plan()
                if self.t >= self.next_fire - EPS and self.live:
                    aim = self.choose()
                    if aim:
                        self.fire(aim)
                        while self.events and self.events[0][0] <= self.t + EPS:
                            steps += 1
                            if steps > 2_000_000:
                                status, reason = "limited", "达到事件数量预算"
                                break
                            _, _, kind, data = heapq.heappop(self.events)
                            if kind == "impact":
                                self.impact(data)
                    else:
                        self.next_fire = self.t + 0.1
            if reason:
                break
            # Last direct/DoT kill ends a wave at its actual timestamp. World
            # fields survive the gap, but do not delay an otherwise clear wave.
            if (
                not self.wave_pending
                and self.generated >= self.c["enemies"]
                and not self.live
            ):
                self.replay["waves"][-1]["end"] = round(self.t, 6)
                self.stats["waves"] += 1
                if self.c["mode"] == "waves" and self.wave >= self.c["waves"]:
                    reason = "完成指定波数"
                    break
                self.wave_pending = True
                self.wait_until = self.t + self.c["waveWait"]
                self.next_spawn = math.inf
                if self.c["waveWait"] <= EPS:
                    continue
            if at_end:
                status = "time_limit"
                reason = "达到模拟时间预算"
                break
            if (
                not self.wave_pending
                and self.t - self.wave_start >= self.c["maxWave"] - EPS
            ):
                status = "limited"
                reason = "单波超时熔断"
                break
            if self.live and self.t - self.last_kill >= self.c["noKill"] - EPS:
                status = "limited"
                reason = "长时间无击杀熔断"
                break
            if self.t >= self.next_frame - EPS:
                self.record(self.player, self.t)
                for actor in self.live:
                    self.record(actor, self.t)
                self.next_frame = self.t + 0.5
            now = time.perf_counter()
            if now - last_progress > 0.25:
                self.progress(
                    dict(
                        t=round(self.t, 3),
                        wave=self.wave,
                        kills=self.stats["kills"],
                        alive=len(self.live),
                        elapsedSeconds=round(now - started, 2),
                    )
                )
                last_progress = now
            clocks = [
                self.t + self.c["movementStep"],
                self.c["seconds"],
                self.combat.next_event_time(),
            ]
            if self.events:
                clocks.append(self.events[0][0])
            if self.wave_pending:
                clocks.append(self.wait_until)
            else:
                clocks.extend(
                    (
                        self.next_spawn,
                        self.next_plan,
                        self.next_fire,
                        self.wave_start + self.c["maxWave"],
                        self.last_kill + self.c["noKill"],
                    )
                )
            next_time = min(t for t in clocks if t > self.t + EPS)
            self.move(next_time)
        self.record(self.player, self.t)
        for actor in self.live:
            self.record(actor, self.t)
        elapsed = (time.perf_counter() - started) * 1000
        self.stats.update(
            seconds=round(self.t, 6),
            live=len(self.live),
            elapsedMs=round(elapsed, 3),
            simulationSpeed=self.t * 1000 / max(EPS, elapsed),
            rays=self.scene.metrics["rays"],
            blockedRays=self.scene.metrics["blocked"],
            pathSearches=self.scene.metrics["pathSearches"],
            directDamage=self.combat.direct_damage,
            dotDamage=self.combat.dot_damage,
            reloads=self.combat.reloads,
            transforms=self.combat.transforms,
            enemyDistance=sum(a.travelled for a in self.actors.values()),
            enemyMoved=sum(a.travelled > 1 for a in self.actors.values()),
            liveUnreachable=sum(a.unreachable for a in self.live),
        )
        self.stats["eventHash"] = hashlib.sha256(
            json.dumps(
                self.replay, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest()[:16]
        self.stats["vitusExpected"] = round(self.stats["vitusExpected"], 4)
        return dict(
            schema=1,
            model=MODEL,
            status=status,
            reason=reason,
            stats=self.stats,
            replay=self.replay,
            loadout=self.context["loadout"],
            scenario=self.c,
            weaponName=self.context["weapon_name"],
            sources=dict(
                self.scene.sources,
                doorGeometry=self.scene.door_source,
                groundGeometry=self.scene.ground_source,
            ),
            diagnostics=list(
                dict.fromkeys([*self.diagnostics, *self.combat.diagnostics])
            ),
        )


class ArenaJobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.active = None

    def start(self, prepare):
        with self.lock:
            if self.active and self.jobs[self.active]["status"] in (
                "queued",
                "running",
            ):
                raise ValueError("已有场景任务运行，请先取消或等待完成")
            for key in list(self.jobs)[:-1]:
                self.jobs.pop(key, None)
            id = uuid.uuid4().hex
            entry = dict(
                id=id,
                status="queued",
                progress={},
                result=None,
                cancel=threading.Event(),
            )
            self.jobs[id] = entry
            self.active = id

        def run():
            try:
                with parallel.SCHEDULER.external_slot(entry["cancel"].is_set):
                    if entry["cancel"].is_set():
                        raise InterruptedError("已取消")
                    with self.lock:
                        entry["status"] = "running"
                    preparation_started = time.perf_counter()
                    context = prepare()
                    if entry["cancel"].is_set():
                        raise InterruptedError("已取消")

                    def progress(value):
                        with self.lock:
                            entry["progress"] = value

                    world = World(context, entry["cancel"].is_set, progress)
                    preparation_ms = (time.perf_counter() - preparation_started) * 1000
                    result = world.run()
                    result["stats"]["preparationMs"] = round(preparation_ms, 3)
                    result["stats"]["totalElapsedMs"] = round(
                        preparation_ms + result["stats"]["elapsedMs"], 3
                    )
                    with self.lock:
                        entry.update(
                            status=(
                                "cancelled"
                                if result["status"] == "cancelled"
                                else "completed"
                            ),
                            result=result,
                        )
            except InterruptedError:
                with self.lock:
                    entry.update(status="cancelled", message="已取消")
            except Exception as exc:
                with self.lock:
                    entry.update(status="failed", message=str(exc))

        threading.Thread(target=run, name="arena-world", daemon=True).start()
        return dict(id=id, status="queued")

    def get(self, id):
        with self.lock:
            row = self.jobs.get(id)
            return {k: v for k, v in row.items() if k != "cancel"} if row else None

    def cancel(self, id):
        with self.lock:
            row = self.jobs.get(id)
            if row is None:
                raise ValueError("任务不存在")
            row["cancel"].set()
            return dict(id=id, status=row["status"])


JOBS = ArenaJobs()
