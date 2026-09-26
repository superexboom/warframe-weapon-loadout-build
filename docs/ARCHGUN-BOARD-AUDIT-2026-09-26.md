# 空战榜单配装对照与剩余机制（2026-09-26）

## 交付状态

- 用户要求先上传的基线已提交并推送：`1eac3e6`，分支 `codex/riven-anomaly-fix-20260922`。
- 本轮新增共享引擎修复、目录准入修复、社区配装复算工具与回归；不是“全武器已与 WFSim 对齐”。
- 14 把武器、21 套公开榜单完整配装已复算；20 套通过生产手动入口，手动 KPM 与离线内核相等。另 1 套含尚未确认发售的 Primed Electrified Barrel，只作为离线审计。
- 6 把空战武器重新执行 8 槽自动搜索，全部与回填后的手动事件 KPM 一致。共同遗漏的机制仍可能使双方同时偏离外部模型。
- 全量回归：139 passed、12 subtests passed，467.20 秒；定向回归 66 passed；随后补入 20 套固定社区配装回归，该文件重跑 34 passed。

## 固定来源与场景

公开榜单输入来自 `https://wfsim.app/board/<weapon>.json`，保留行号、原始 8 张 MOD 顺序、2 个赋能、形态及赤毒元素。榜单既可能有玩家提交，也可能有自动搜索结果，不能声称全部为人工配卡。

WFSim 源码固定 `b98b3d456393131857e1c0e247b19aac6ecc08f4`；release commit `becb34b1+`、release `285450cbd40f`；WASM SHA-256 `697c63bfc0d2fe1c5da82e19adc9d76e54933bbc0baa9cd60c804e419fbe8f0f`。源码与 WASM 分别记账，参考 checkout 未修改。

统一地面部署、Lv9999 钢铁之路 Thrax Centurion、单目标、全爆头、ADS、无外部增益、30 秒；定时触发从零开始，参考 500 次随机运行，seed=12648430。参考显式指定 `class_rules.archgun.infinite_ammo=true`，这是**无限补给的归一化对照**。原榜单 180 秒口径保留为来源，未直接拿其公布分数对比本地 30 秒结果。地面空战储备弹药与补给规则尚未在本地完整实现。

本地敌人精确身份 `/Lotus/Types/Enemies/Duviri/Avatars/DuviriMeleeAvatar`；不是名称相近但不同的靶。双方目标血量 9,667,913.9637、超宏防护 15,523,399.9113、护甲 2,700；21/21 目标一致。

面板与事件分开验收：按 0.1% 相对误差、1e-5 绝对误差筛选，仅 10/21 面板全部通过。其余差异主要为导出精度与参考显示值，例如 Critical Focus 暴伤 5.28879 对 5.28、Imperator 射速 31.66667 对 31.73、Corvas 单弹丸触发 1.27273% 对 1.3%。这些差异完整保留，未把它们强行修成参考数字。

Corvas Prime、Larkspur 的现有匹配形态榜单没有无紫卡行，因此未纳入；紫卡 roll、融合属性与 disposition 的双方翻译需要单独校验，不能随意替换原卡。

## 已落地的修复

1. **空战赋能共同准入**：主/副武器的通用赋能同时进入手动、自动及伤害 reducer，支持两个武器赋能槽；依精确 compatibility 准入，保留 Kitgun、近战及武器专属限制。涵盖 Zariman 路径的 Cascadia，不能只匹配 Offensive 路径。
2. **赤毒元素基数**：元素 MOD 与 DoT 种子使用包含赤毒加成的基础伤害；原生元素仍在普通 MOD 顺序合成后加入，未改变配卡顺序。Kuva Grattler 的明显面板偏低由此修复。
3. **致命效率/Prime**：真实空弹匣装填完成后激活；按已核实 rank 缩放持续时间，满级分别 9 / 16.5 秒。其他装填触发保持原语义。
4. **基础攻击缺段**：Grattler、Kuva Grattler、Morgha 的范围段与 Cyngas / Morgha 的 burst 节奏加入经路径、形态与伤害向量校验的攻击档案。范围段不复制头部倍率。
5. **已发售卡的目录误拦截**：Primed Combustion Rounds 和 Primed Polar Magazine 的完整数据及图像已存在，但旧 `selectable=false` 让它们同时消失于手动和自动候选。新增共享、精确身份且校验词条/等级/兼容性/图像的加载修正；保留原始冻结文件，后续换快照也沿用校验。新模块进入缓存指纹。
6. **复算工具**：可抓取新榜单或重放固定快照；记录 board/source/WASM 哈希、完整请求和响应、面板偏差、目标检查、目录阻断、手动入口差异；支持只移除失活的消融对照。自动回归出现任一不一致时返回失败退出码。

两张卡的可装备性证据是售卖记录，而非把 `excludeFromCodex` 当发布开关：

- Primed Combustion Rounds：2026-05-15 当期新卡记录，https://www.reddit.com/r/Warframe/comments/1tdvui0/baro_kiteer_inventory_and_recommendations_20260515/ 。
- Primed Polar Magazine：2026-08-21 当期新卡记录，https://www.reddit.com/r/Warframe/comments/1vufw4w/baro_kiteer_inventory_and_recommendations_20260821/ ，并与固定 WFSim YAML 的推出日期交叉核对。
- 当前官方 PublicExport 的数值/路径也匹配，但三张 Prime 元素卡仍有 `excludeFromCodex=true`。电卡未拿到同等级的发售证据，仍不解禁。
- 两张新准入卡的本地图像存在；本轮未新增浏览器视觉验收，不把资源存在等同于页面已实测。

## 社区配装结果

下列是相同 30 秒归一化场景的 KPM（含末个目标的进度分数）；不是裸枪，也不是榜单原始 180 秒名次分数。`移除失活` 只移除该赋能，其余卡和条件不动，是人工消融，不冒充另一套玩家投稿。保留参考 score_se、panelDifferences 和逐事件响应供进一步定位。

| Build ID | 本地 KPM | WFSim KPM | 偏差 | 移除失活 WFSim KPM | 消融偏差 |
|---|---:|---:|---:|---:|---:|
| corvas-5 | 1.979 | 3.568 | -44.53% | 1.878 | 5.37% |
| mausolon-136 | 21.342 | 24.830 | -14.05% | 24.830 | -14.05% |
| mausolon-137 | 22.528 | 25.136 | -10.37% | 25.136 | -10.37% |
| larkspur_prime-1033 | 5.586 | 19.403 | -71.21% | 7.849 | -28.83% |
| larkspur_prime-1037 | 7.438 | 19.693 | -62.23% | 9.369 | -20.62% |
| imperator-2 | 1.566 | 3.237 | -51.62% | 1.698 | -7.80% |
| imperator_vandal-75 | 27.740 | 23.969 | 15.73% | 23.969 | 15.73% |
| imperator_vandal-76 | 15.211 | 20.174 | -24.60% | 20.174 | -24.60% |
| grattler-2 | 1.517 | 1.974 | -23.14% | 1.640 | -7.48% |
| kuva_grattler-190 | 18.000 | 15.018 | 19.86% | 15.018 | 19.86% |
| kuva_grattler-191 | 19.347 | 17.996 | 7.51% | 17.996 | 7.51% |
| fluctus-6 | 5.078 | 7.080 | -28.28% | 3.413 | 48.77% |
| fluctus-7 | 9.304 | 9.581 | -2.89% | 9.581 | -2.89% |
| cyngas-2 | 1.693 | 3.834 | -55.85% | 1.993 | -15.04% |
| velocitus-5 | 1.620 | 1.672 | -3.09% | 1.672 | -3.09% |
| morgha-5 | 1.389 | 1.589 | -12.63% | 1.407 | -1.34% |
| cortege-219 | 9.848 | 21.640 | -54.49% | 11.425 | -13.80% |
| cortege-223 | 13.313 | 28.047 | -52.54% | 14.895 | -10.62% |
| dual_decurion-2 | 1.702 | 3.465 | -50.89% | 1.830 | -7.03% |
| prisma_dual_decurions-10 | 11.301 | 18.277 | -38.17% | 10.977 | 2.95% |
| prisma_dual_decurions-11 | 11.220 | 17.833 | -37.08% | 11.242 | -0.20% |

Fluctus-7 含电卡，保留离线结果；其他 20 套手动入口与内核一致。

### 完整自动搜索

| 武器 | 自动 KPM | 手动 KPM | 一致 |
|---|---:|---:|---|
| Imperator Vandal | 19.692725 | 19.692725 | True |
| Mausolon | 19.721146 | 19.721146 | True |
| Kuva Grattler | 16.786469 | 16.786469 | True |
| Larkspur Prime | 11.662461 | 11.662461 | True |
| Cyngas | 16.842362 | 16.842362 | True |
| Morgha | 10.387677 | 10.387677 | True |

## 剩余缺口：能否补齐、怎么补

| 优先级 | 缺口与证据 | 可行方案与验收门槛 | 结论 |
|---|---|---|---|
| P0 | 次要·失活：多数大负差的配装携带它；本地提示 runtime-script 并未计入。移除后 Prisma Dual Decurions 的 -37.08% 缩至 -0.20%，Larkspur Prime 的 -71.21% 缩至 -28.83%。 | 独立暴击堆叠/重置状态机：按 hitscan、弹丸、多重、光束、范围与 Blast 到期事件分别定义命中次数；10 个绝对百分点/命中，橙暴及以上计数重置，rank 决定阈值；30/s 限流。先建固定命中轨迹和 seeded Monte Carlo 金标准，再让手动、搜索、贡献共用实现；不能塞一个平均暴击率。 | 可以补。WFSim 自己仍列出同击先增后重置、限流究竟最短间隔还是滚动窗口待游戏确认；实现必须明确假设。 |
| P0 | Heat、状态寿命及条件覆盖率残差：移除失活后 Fluctus 仍 +48.77%，本地总 DoT 约 32.74M，参考 Heat 12.83M + Slash 0.35M；总直击约 31.22M/30.24M。 | 对齐状态次数、首跳、刷新、死亡清空、种子继承与实际加成；用无甲固定高血目标、固定 proc 轨迹和完整配装逐步消融。当前期望小数 proc 会刷新持续时间，与随机“这一枪未触发”不同；不能把统计近似当成精确随机等价。 | 可以逐项补，当前证据只定位差异，尚未证明全部来自单一公式。 |
| P0 | 赋能触发/到期边界，例如 Primary Crux 的 per-stack 与参考 all-at-once 差异，持续射击很难暴露。 | 添加“射击—停火超过10秒—再射击”、装填临界、目标死亡及叠层上下限轨迹；追原脚本确认刷新/掉层规则，再更新共享 adapter。 | 可补，需要明确来源而非直接迁就榜单 KPM。 |
| P1 | 地面空战有限储备、拾取与重新部署缺失；无限补给会掩盖 180 秒后半程差距。 | 引入弹匣+储备+拾取/部署事件，武器配置纳入场景和评分缓存；分别验无补给、固定补给、无限补给三组。确认参考模拟约定与游戏实际规则的区别。 | 可补；在此之前不可宣称复现原榜单 180 秒。 |
| P1 | 充能副射、全蓄力与仅有紫卡的榜单案例尚未覆盖。 | 分离 quick/full-charge/burst/alternate 身份，补计量表和模式切换；紫卡通过参考 /api/riven 取实际 roll 数值，保留极性、槽位、融合代码和顺序。 | 可补；不接受以普通模式或替代卡偷换输入。 |
| P1 | 其他灵化范围段和条件：Braton、Latron、Laetum 等；Torid Renewed Horror；部分武器专属触发。 | 按机制目录逐项加入明确事件、持续、刷新/到期与伤害归属，配套自动/手动/贡献三路测试，再进入搜索候选。当前 66 个充能档案不等于全部进化已实现。 | 大部分可补；通用脚本解释器不是必要前置，复杂依赖仍需专用适配。 |
| P2 | 多目标、穿透/弹射、波形命中体积、范围/场重叠、队友亲和点。 | 增加目标空间状态、命中归属与每目标生命周期；固定距离/敌人布局，单目标和群体分别报告。 | 可补，但属于模型扩展，不能乘一个“群怪倍率”。 |
| P2 | 近战架势/特殊重击和进化树联合搜索；有限预算 beam/局部搜索不保证最优。 | 补动作序列与资源，再把进化作为搜索维度；小候选集全穷举作 oracle，大集合报告 best-found 和预算。 | 可补；当前内核一致性不等于全局最优。 |
| 暂缓 | Duelist 被动/技能、所有运行时脚本的完全恢复、全游戏实测。 | 按用户指示暂放战甲；缺游戏侧证据的分支保留不可用及具体原因，不能把 WFSim 无数据变成有结论。 | 未完成，不列入本轮通过项。 |

落地顺序：先失活状态机与 Heat 固定轨迹，再 Primary Crux 等边界，随后有限弹药、紫卡/充能样本扩容。每一阶段都必须先进入共同 prepare/replay，再验搜索回填与贡献移除；不保留另一套旧候选算法。

## 回归、证据和复现

证据根目录 `.local/reports/2026-09-26-archgun-board`（本机忽略目录，不随远端分支上传）：

- `tests/fixtures/archgun_board_20260926.json`：随代码提交的精简输入、来源哈希和双方数值，避免远端只能依赖会变化的在线榜单。
- `verified/comparison.json`：21 套原始配卡、双方全部输出和身份；`requests.json` / `responses.json` / `board-*.json` 可复核。
- `verified-no-enervate/comparison.json`：相同输入逐套移除失活的消融。
- `fetch-smoke/comparison.json`：在线抓取入口 Imperator 冒烟；10 次运行仅检查流程，不能用于精度结论。
- `auto-full-final.json`：6 套实际自动搜索与手动回填，全部通过。
- `official-upgrades.json`：当日 PublicExport 原始响应；manifest `ExportUpgrades_en.json!00_8OAjaCAFR9CWHGr7OrhxAA`。
- `pytest-full.txt`：目录修复前 138 passed；`pytest-final.txt`：最终 139 passed，12 subtests passed。
- `import-check/combat-reference.json`：独立再生成；与生产文件解析后完全相等。只增加 4 个 auditedAttacks，其他机制内容未变化。
- `initial` / `arcane-fixed-v2` / `mechanics-fixed` / `final` / `no-enervate` 保留中间失败、旧模式或准入问题，不能作为最终验收。

本轮未打 EXE、未烘焙全量推荐缓存、未合并主分支、未宣称游戏内验证。代码/测试/报告上传远端分支，原始输入与参考源保持不变。

```powershell
# 首次可使用 --fetch；重放固定来源则换成 --board-dir .local
python tools/compare_archgun_board_builds.py --wfsim .local/wfsim-source-20260926 --fetch --output .local/reports/new-archgun-board --per-weapon 2 --runs 500
python tools/compare_archgun_board_builds.py --wfsim .local/wfsim-source-20260926 --board-dir .local --output .local/reports/new-archgun-ablation --per-weapon 2 --runs 500 --without-enervate
python tools/regress_auto_build_events.py --full --archguns --output .local/reports/new-archgun-auto.json
python -m pytest tests tools/test_data_pipeline.py -q --tb=short
node --check frontend/app.js
git -c core.whitespace=cr-at-eol diff --check
```

比较工具报告残差，不把“运行完成”包装为外部数值通过；自动/手动一致性回归则在任一失败时返回非零退出码。
