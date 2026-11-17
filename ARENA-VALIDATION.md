# 场景导航回归记录（2026-11-17）

本轮使用用户当前伯斯顿Prime配装、160起点、等级增长开启、4人仲裁拦截定额清场。固定seed20261116；地图使用全部已接入区域，各本图怪组独立运行。这里测试的是场景运动与伤害接线，不代表还原原生占点任务。

## 覆盖与口径

25张模板共37个可运行本图怪组组合，每组最终复测3个周期，共7473击杀，37组均清场。另进行过每组20周期/1800模拟秒的压力扫描；中途命中墙钟预算不会被称为AI死循环。最终运行使用2个独立单线程进程，诊断预算45秒；产品默认仍30秒。

“远处停步”指目标净位置在0.2米内停留超过15模拟秒，同时与战甲距离超过3米。该指标会包含源导航缺连接、拥挤等候，也可能受状态控制影响；不能仅凭此判定永久卡死。下表如实保留未消除的停步，不以最终清场掩盖。

## 图与本图怪组结果

| 模板 | 来源怪组 | 基线远处停步¹ | 修正后远处停步 | 最长（模拟秒） | 最终周期 / 击杀 | 实际计算秒² |
|---|---|---:|---:|---:|---:|---:|
| 1999-temple-defense-underground | DisruptionScaldraSpec | 0 | 0 | 0.00 | 3 / 209 | 2.34 |
| corpus-gas-city-defense | CorpusGasRemasterDefenseSquad | 4 | 0 | 0.00 | 3 / 203 | 3.12 |
| corpus-gas-city-defense | InfestedDefenseA | 5 | 0 | 0.00 | 3 / 204 | 5.50 |
| corpus-ice-defense | CorpusSquadDefenseB | 4 | 3 | 24.51 | 3 / 205 | 3.69 |
| corpus-ice-defense | InfestedDefenseB | 10 | 2 | 19.10 | 3 / 196 | 4.41 |
| corpus-outpost-defense-one | CorpusSquadDefenseB | 1 | 5 | 24.84 | 3 / 207 | 2.95 |
| corpus-outpost-defense-one | InfestedDefenseB | 7 | 2 | 26.31 | 3 / 203 | 4.53 |
| corpus-outpost-defense-two | CorpusSquadDefenseB | 0 | 0 | 0.00 | 3 / 200 | 2.18 |
| corpus-outpost-defense-two | InfestedDefenseB | 1 | 0 | 0.00 | 3 / 200 | 4.71 |
| corpus-ship-defense | CorpusShipSquadDefenseB | 0 | 0 | 0.00 | 3 / 203 | 4.63 |
| corpus-ship-defense | InfestedDefenseA | 0 | 0 | 0.00 | 3 / 199 | 6.44 |
| corpus-ship-defense | InfestedDefenseB | 0 | 0 | 0.00 | 3 / 203 | 6.79 |
| entrati-lab-mirror-defense-ear | EntratiMirrorDefenseSpec | 29 | 13 | 58.50 | 3 / 199 | 35.96 |
| entrati-lab-mirror-defense-eye | EntratiMirrorDefenseSpec | 47 | 10 | 87.60 | 3 / 203 | 37.73 |
| grineer-asteroid-defense | GrineerDefenseAAsteroid | 0 | 0 | 0.00 | 3 / 214 | 1.52 |
| grineer-asteroid-defense | InfestedDefenseA | 2 | 0 | 0.00 | 3 / 195 | 5.34 |
| grineer-asteroid-defense | InfestedDefenseB | 5 | 0 | 0.00 | 3 / 199 | 3.82 |
| grineer-forest-defense | GrineerDefenseForest | 0 | 0 | 0.00 | 3 / 206 | 1.67 |
| grineer-forest-defense | InfestedDefenseA | 1 | 0 | 0.00 | 3 / 196 | 4.80 |
| grineer-forest-interception-01 | GrineerDefenseForest | 0 | 0 | 0.00 | 3 / 200 | 1.41 |
| grineer-forest-interception-02 | GrineerDefenseForest | 0 | 0 | 0.00 | 3 / 206 | 1.97 |
| grineer-fortress-defense | GrineerDefenseFortress | 19 | 19 | 104.04 | 3 / 200 | 4.19 |
| grineer-galleon-defense | GrineerDefenseA | 0 | 0 | 0.00 | 3 / 202 | 2.37 |
| grineer-ocean-defense-02 | SeaLabGrineerDefenseA | 0 | 0 | 0.00 | 3 / 203 | 1.82 |
| grineer-ocean-defense-03 | SeaLabGrineerDefenseA | 0 | 0 | 0.00 | 3 / 202 | 2.02 |
| grineer-settlement-defense | DesertGrineerDefenseA | 0 | 0 | 0.00 | 3 / 206 | 1.43 |
| grineer-settlement-defense | InfestedDefenseA | 0 | 0 | 0.00 | 3 / 194 | 4.65 |
| grineer-shipyards-defense | GrineerShipyardsDefenseA | 0 | 0 | 0.00 | 3 / 204 | 2.20 |
| grineer-shipyards-defense | InfestedDefenseB | 0 | 0 | 0.00 | 3 / 200 | 4.77 |
| grineer-shipyards-interception | GrineerShipyardsDefenseA | 0 | 0 | 0.00 | 3 / 203 | 1.88 |
| infested-corpus-defense | InfestedDefenseB | 7 | 7 | 32.74 | 3 / 203 | 5.62 |
| lastwish-corpus-mirror-defense | CorpusGrineerDesertMix | 48 | 18 | 62.42 | 3 / 203 | 3.84 |
| lastwish-grineer-mirror-defense | CorpusGrineerDesertMix | 0 | 0 | 0.00 | 3 / 211 | 2.11 |
| orokin-derelict-defense | InfestedDefenseB | 0 | 0 | 0.00 | 3 / 198 | 4.36 |
| orokin-moon-defense | GrineerMoonDefense | 3 | 1 | 19.31 | 3 / 197 | 3.15 |
| orokin-tower-defense | OrokinDefenseSquad | 0 | 0 | 0.00 | 3 / 199 | 3.01 |
| orokin-tower-defense | OrokinDefenseSquadB | 0 | 0 | 0.00 | 3 / 198 | 4.05 |

¹ 基线只统计原地15秒，不区分距战甲，且使用15秒预算；表中数量不能当作同时间覆盖的严格百分比改善。原始与修正版回放均保留在本地诊断目录。
² 批量并发、编译和诊断争用会影响墙钟；这些数字不作为产品独立运行延迟承诺。

## 已修复的根因

- 原有CSG地板完整却因导入必须新增visual witness而漏掉连接。
- 无原生offmesh记录的窄缺口，通过明确可关闭的保守NPC短跨越场景模型接入；不生成地板。
- 不同空中弧线同时通过同一狭窄通道相互锁住，现起步前预约。
- 毫米级事件步反复清零堵塞计时，现按实际脚点有效位移触发让位。
- 小型普通飞行敌人误用地面图，现按源Hover/Flyer字段独立分配。
- 全图Dijkstra反复执行占用计算预算，现可选Rust求路并复用任务内缓存。

## 剩余限制

10组在这次完整3周期中仍出现至少一次远处停步，尤其赤毒要塞、部分镜像防御与前哨站一。部分源NAV孤岛没有已证实可通行的门/跳落/地面连接；不放宽普通墙体或凭空造桥。大型飞行敌人的真实体积和高度控制尚未接入小型Hover代理。英择谛普通敌多为非头部弱点，用户的爆头配装不能等价于同等级普通Corpus的击杀速度。

待后续源连接或实测校准项保留在ARENA.md和本地实施记录中；本次不宣称全图全怪组完全无等待。


用户原燃气城完整20周期复验：真实8卡伯斯顿Prime、灵化循环、160起点并开启拦截等级增长、4人、固定seed。最终1338击杀、1275.79模拟秒，源码23.71秒、成品真实浏览器24.64秒（事件指纹7613316b2c2430b1一致），远离战甲的连续15秒停步为0；此前原回放16周期后耗尽30秒预算、29个目标连续停步超过15秒。最后修复是Door4969确切静态门框/Inlay底部三角支持，严格地面也可通行，未扩大门框穿越范围。上述矩阵燃气城两组已据此复算。
