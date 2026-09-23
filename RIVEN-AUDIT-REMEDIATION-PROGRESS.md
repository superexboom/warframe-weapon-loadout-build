# 紫卡收益异常修复：F01–F17 落地执行追踪

**更新时间：2026-09-22（滚动更新）**
**工作分支：`codex/riven-anomaly-fix-20260922`**
**审核基线：`a8e92c3644e39f5e92c360fad8486c7ed9d16549`**
**依据报告：`RIVEN-REMOTE-SOURCE-AUDIT-a8e92c3-20260922.md`**

> 本文档跟踪审计报告 F01–F17 的实际落地。每一项按「已端到端完成 / 仅基础设施 / 未实现 / 证据不足」标注，并记录实现位置、关联测试与验收输出。缓存策略不变：本阶段禁止全量烘焙；所有缓存测试使用临时目录，不触碰用户 `.local/cache` 旧文件。

## 总进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 测试目录纳入版本控制 + 失败测试（F17） | 已完成 |
| P0 | 缓存安全边界（F12/F13/F14） | 已完成 |
| P1 | 权威评价器：直接射击调度（F01）、DoT 合同（F02/F03/F04） | 已完成 |
| P2 | 统一评分记录（F05/F06/F07/F08） | 已完成 |
| P3 | 机制登记与静态分析补全（F16 + subagent） | 已完成（登记与导出修复；机制实现按证据推进，unknown 保持 fail-closed） |
| P4 | 搜索后升靶闭环 + 搜索质量（F09/F15） | 已完成 |
| P5 | 小样本缓存回归 + 状态合同（F10/F11） | 修复与回归测试完成 |

## 工作日志

### 2026-09-22 Round 2

- **F17 落地**：`.gitignore` 移除 `/tests/` 与 `/test_*.py` 忽略规则；`tests/` 进入版本控制。新增 `tests/test_windowed_damage_contract.py`（D01/D02/E01/E02/E07 合同回归，含三档超杀比例与分箱无关性）。
- **F12 落地**：`app.py::mod_gains_payload()` 会话缓存键补入完整紫卡（code/value/negative/顺序），修掉「只改紫卡数值返回旧结果」的键碰撞（验收 C02 的修复侧）。
- **F13 落地**：`_analysis_inputs_fingerprint()` 补入 `app.py` 与 `combat_events.py`；文件读取失败不再返回空指纹，改为显式 `SimulationError`，加载/持久化两侧都按「依赖缺失=缓存不可用」处理。
- **F14 落地**：
  - `app.py` 新增 `_AnalysisStaticsPersistence` 开关 + `_disable_analysis_statics_persistence()`；`_persist_analysis_statics_cache()` 受开关控制。
  - `tools/bake-analysis-statics.py` worker 进程入口即关闭持久化（结构上封死 `analyze_payload → _persist` 的间接写路径），worker 产出为零 statics 时显式失败，分片指纹带 `__unreadable_inputs__` 失败标记并在合并阶段被拒绝。
  - bake 默认开火模式与普通分析同口径（灵化多模式取末模式，其余取主模式）——修掉「烘焙条目永远不会被默认请求命中」的缺口。
  - bake 有失败时返回退出码 1；零任务也返回 1。
- **F02 落地**：`expected_dot_damage()` 生产者输出显式合同字段（`seedPerSecondPerProc`、`accumulatorPerSecondPerAttack`、`accumulatorSharedGroup`）；`windowed_status_damage()` 消费端不再从聚合 `perSecond` 反推（旧路径 `perSeed = perSecondRaw / expectedProcs` 使触发数在主项中抵消，且累加项双重计费）。修复后单 proc 种子伤害恒定（13.72/13.72），DoT 窗口总量随触发数正确缩放（2623→7344，2.8 倍触发数 = 2.8 倍 DoT）。
- **F03 落地**：`durationSeconds` 合同定为「生产者输出最终时长」，消费端删除第二次 `× duration_scale`。
- **F01 落地（主链路重写）**：`windowed_status_damage()` 步循环重写为事件结算混合模型（`eventModel: hybrid-event-settled-v2`）：
  - 直伤按离散攻击事件结算（本步区间内第 k 次攻击在 t=k/rate 落地，与 direct ledger 同一调度）；组件按攻击时刻目标代次逐个结算，同次攻击剩余组件 stale 不转杀（E02），不同攻击可各自击杀重生目标（E03）。
  - DoT 在攻击间隙按连续流量结算；非 DoT proc 改为每攻击计价（原为每秒流）。
  - 死亡即时结算（InstantRespawn），代次状态（ramp 时钟/Heat Inherit/DoT 层）随代次清理（F04）。
  - 实测：1 Hz、30 秒、EHP=单发伤害的 1/2/10 倍 → 主循环与 ledger 完全一致（30/15/3 杀，60/30/6 KPM）；旧代码在同一夹具下产生 300 杀（10 倍泄漏）。status=0 夹具 1176 杀 → 30 杀。
  - 性能：状态重负载场景（DoT+直伤+削甲）30 秒窗口 2 ms。
- **F04 落地**：DoT 云存活窗口改用「本代次重生时钟」（`ramp_elapsed`，死亡清零），非 Heat 状态不再绑定整场战斗时间；步内击杀后的代次状态由 `_settle_death` 统一重建。
- wfsim 黄金回归集 43/43 全收敛（比值=1，无 mismatch）——面板口径公式未受影响。
- 端到端冒烟：`analyze_payload`（Braton Prime，fast 档，D/2/6/F 四词条）正常解算：score 100.0/EX、`scoreStatus: available`、校准到 Lv2800、windowedDps 重排生效、耗时 115.7 s（fast 档全链路）。
- 静态分析 subagent（zhipu/glm-5.3 max）三路完成，产出 `.local/research/*.json`：
  - **Torid**：毒云无独立游戏对象，伤害合同=投射物 `EmbedAttack`（40 DT_POISON、proc 0.25、半径 3 m、持续 10 s）；tick 间隔不在导出内（wfsim 实测 1/s，标记为 cross-reference）；Incarnon 光束 51 DT_POISON 无场。
  - **Opticor**：径向伤害在原始导出 `impact:RadialOnMissImpactBehavior.RadialDamage`（本体 200 磁力 r6m fallOff0.6；Vandal 100 磁力 r4.6m），compact 导出因 extract.py 只从 projectileType 分支读取径向而静默丢弃（影响 65 把 hitscan 武器）；另发现 `chargeTime` 大小写 bug（extract.py:610 读 `chargeTime`、原始字段是 `ChargeTime`，全部 65 把蓄力武器 chargeTime=null）。
  - **Latron/Double Tap**：sidecar 参数错误——mod 实际为 `_bonusDamagePercent 0.05`（5%）+ `_multTimeWindow 0.5s` 的下一发乘数（非 0.2/20 层/2.0s/resetOnMiss）；唯一 AvailableOnPve=1 的 PvP mod；灵化直击受支持（投射物自身接线 BonusDamageOnNextHit.lua），灵化径向无静态证据（ExplosiveAttack 无脚本钩子）；径向伤害确认（本体 80、Prime 140、Wraith 100，半径 4，fallOff 0.2）。

### 2026-09-22 Round 3

- **F06 落地**：`theoretical_structure_scale(positive_count, ...)` 从规范化实际结构传递——两正紫卡的理论上限不再进入写死的三正系数。实测：2+0 结构 D 词条 high=233.6（164.9997 基值 × 1.3 × 1.0 × 1.089 正确口径），旧实现会得到 177.0（错误的三正 0.757525 系数）。
- **F07 落地**：
  - 新增模块级 `validate_build()` 统一可行域校验器（必选在场/禁选不在场/min-max fill/槽位/容量）与 `_mark_required_cards()`。
  - 用户必选卡物化为 `required=True`（爬山 Drop/Swap 不再可能删除它们）。
  - 爬山 Add 检查 max_fill、Drop 检查 min_fill、Swap 检查全部约束；`_apply_riven_floor` 路径过同一验证器；`_optimize` 最终输出统一验证，不可行构建直接报错。
- **F08 落地**：逐词条贡献拆成两个口径——`delta`/`ablationDelta`（固定配卡消融：同配卡同指标只移除该词条）与 `reoptimizedDelta`（删词条+重选 MOD 的联合收益）。前端渲染消融口径为主数值、重优化为角标。实测：D 词条消融 +65.7%（真实口径），旧实现显示 +4459.7%（被子集重优化污染）。fatal 负面判定改用消融口径。
- **F05 落地**：连续指标（windowedDps）重搜的三条曲线（baseline/actual/bestFound）全部重绑为最终展示配卡与缓存记录——评分分子/分母、屏幕配卡、贡献明细、静态缓存引用同一 EvaluationRecord；静态缓存回写质量阶段赢家（热路径重建配卡可复现缓存数值，S03 重放合同）；解释文案区分「KPM 平台化/触顶」与普通切换。
- **F09 落地**：搜索后升靶重搜闭环——赢家在冻结上下文下仍饱和时，预算内（TARGET_CALIBRATION_MAX_ITERATIONS）逐级升靶探测，找到压力足够的等级后在最终上下文重跑三条正式曲线（旧赢家只作起点），再验压力；升级记录写入 `targetCalibration.postSearchEscalation`，缓存迁移复用 `_scoring_cache_migrate`。
- **F10 落地**：`targetCalibrated` 只在 `status == "calibrated"` 时为 true（capped-saturated/post-search-saturated/skipped 都不算），新增 `targetCalibrationStatus`；`targetStatus` 区分 not-applicable/calibrated/saturated-unresolved/skipped；新增 `scoreStatusReason` 原因码（ok / target-pressure-insufficient / model-missing:<tokens> / optimizer-optimum-lower-bound）；前端按原因码区分展示「模型有未建模机制」「目标过弱/饱和」「下界未证明」，不再一律「未证明全局最优」。
- **F11 落地**：升靶缓存回退查找改为「除等级外完整战斗上下文逐字段匹配」（敌人/窗口/钢铁之路/卓越者/削甲/爆头率/元素削甲全部参与），缓存键里多出的 benchmark 字段也必须与本请求口径一致。
- **F15 落地（第一部分）**：爬山 `seen_keys` 去重改为有序构建签名（保留元素顺序，同卡不同序不再被折叠）；Swap 把新卡放进被移除卡的槽位（保持元素边界，不追加到末尾）；多起点——贪心种子（逐张取当前最优单卡）先入 incumbent，覆盖 beam 剪枝漏掉的显见组合，并保证高档位不劣于贪心口径（S07 下界）。
- 端到端冒烟（fast 档）：三正 D/2/6/F 卡 111.1 s 正常解算；两正 D/2 卡 79.2 s，score 22.1/E（合理：2 正无负的实际上限低于 3 正结构），`ablationDelta` 与 `reoptimizedDelta` 分离正确。
- 14 项单测全通过；wfsim 黄金集保持 43/43 收敛。

### 2026-09-22 Round 4

- **F16 落地**：
  - `data/weapon_mechanics_overrides.json` 升级 schema v2：evidenceSchema（supported/conditional-supported/unsupported/not-applicable/unknown 五态 + 证据类型标注 raw-export-field / raw-export-script-reference / cross-reference-wfsim / wiki / in-game-measurement）。
  - Double Tap 参数按静态分析修正：`_bonusDamagePercent 0.05`（5%）+ `_multTimeWindow 0.5s` 下一发乘数（旧登记的 0.2/20 层/2.0s/resetOnMiss 无数据支持，已删）；`AvailableOnPve=1` 登记；灵化直击= supported（投射物接线证据）；灵化径向= unknown（fail-closed）。
  - Torid 登记 fieldContract：毒云=投射物 EmbedAttack（40 DT_POISON/proc 0.25/r3m/10s），tick 间隔标注「不在导出内，wfsim 实测 1/s 为 cross-reference」；Incarnon 光束无场。
  - Opticor/Vandal 登记 radialContract：磁力径向（本体 200 r6m fallOff0.6 / Vandal 100 r4.6m）、每发触发（命中或落空）、吃基伤不吃多重、蓄力 ×2；Vandal 径向暴击保留本体数值（原始数据不对称）。
  - Latron Prime/Wraith 登记 incarnonRadialContract（Prime 140=火70+穿70 / Wraith 100，r4m fallOff0.2，MaxBounces 6）。
  - `pipelineGaps` 段登记两个系统性导出缺口：hitscan-radial-dropped（extract.py 只从 projectileType 分支读径向，65 把 hitscan 武器被静默丢弃）与 chargeTime 大小写 bug。
  - app.py 的 fail-closed 消费同时接受旧 `event-unmodeled` 与新 `unsupported` 状态。
  - `tools/audit_weapon_mod_mechanics.py` schema v2：每个计数显式携带自己的筛选阶段与分母（weaponMods=878 全量、auditedRows=552、compatibilityWithoutWeaponSupport=347、eventUnmodeledCandidates=335），并加 coverageNote 声明「库存审计≠运行时消费覆盖证明」。
- **extract.py 双 bug 修复**（静态分析发现，影响未来的 compact 导出重建）：
  - hitscan 径向：impact 块的内联 RadialDamage 按 `_projectile_damage_components` 同口径提取进 components/radial。
  - `chargeTime` → `ChargeTime`（大小写），65 把蓄力武器不再 null。
- **min_fill/max_fill 边界修复**（F07 连带）：未设置的 min_fill 不再默认 slot_count（旧实现「只给 max_fill<8」直接报 min>max 错误）。
- **F14 修正**：`_disable_analysis_statics_persistence()` 现在翻转进程级 `ANALYSIS_STATICS_PERSISTENCE` 开关本体（旧写法新建对象没有关闭全局开关——bake worker 实际未被保护）。
- **新增回归套件 `tests/test_optimizer_contracts.py`**（S01/S02/C01/C02/C03/C04/U01/S04 共 15 用例）：
  - S01 四结构系数表 + 两正端到端（high=233.6 vs 旧 177.0）。
  - S02 验证器单元 + 必选卡在搜索中不被删除的端到端。
  - C02 只改紫卡数值的两次 mod-gains 调用产生不同缓存键与不同 baseValue。
  - C03 指纹稳定性 + 依赖缺失抛 SimulationError。
  - C04 持久化开关关闭期间 `_persist` 为 no-op + bake 默认模式策略镜像分析器（灵化取末模式）。
  - U01 结果携带 scoreStatus/targetStatus/targetCalibrationStatus 原因码。
  - S04 details 同时暴露 ablationDelta 与 reoptimizedDelta 且主 delta=消融口径。
- 全套测试 29 passed（7 subtests）；wfsim 黄金集 43/43 收敛；py_compile × 4、node --check、git diff --check 全过。

### 2026-09-22 Round 5（收尾）

- **E03/E05 合同测试补齐**：同一积分片内两个攻击实例可各自击杀重生目标（8 Hz/1 s/0.25 步 → 主循环与 ledger 一致给出 8 杀/480 KPM）；代次死亡清理 DoT 云（脆靶 vs 长命靶的 DoT 速率对比 <50%）。
- **N01 负向测试**：破坏 `windowed_status_damage` 返回哨兵值，断言 `_score` 与 `_window_pressure_probe` 的输出随之改变——证明生产评分/校准路径真实消费窗口模型（防止未来重构把引擎接线剪断而 helper 全绿）。
- **F15 双槽成对交换**（deep 档）：成对协同替换进入爬山邻域（每轮预算 24 对，成本受 climb_rounds 约束）——单卡邻域看不到「两张卡一起换才更优」的组合（元素边界/容量再分配）。
- 全套测试 **33 passed（7 subtests）**；wfsim 黄金集 43/43 收敛。
- `RIVEN-ANOMALY-FIX-STATUS.md` 重写为本阶段终态（F01–F17 交付摘要、静态分析结论、回归证据、明确未实现/fail-closed 清单、缓存准入条件）。

### 2026-09-23 Round 6（词条融合布局 + 反哺算法强化）

**一、新版本静态分析（词条融合探测）**

- 今晚 0:03 游戏缓存更新（H.Misc 264MB）→ dump 出新 build `2026.08.19.11.06`（201531 对象 + 双语语言包）。
- **与 2026.08.13.13.24 全量 diff：0 新增 / 0 删除 / 15 个无关热修文件**（装饰、NPC 套装、商店礼包）——本 build 是补丁级热更，**不含词条融合数据**。
- 语言包 diff（tag 级 + 关键词计数）：`Coalescent/Ascent Fusion/升华融合/联结融合` 在旧 build 已存在（Archon 水晶合成器的既有 UI 预埋）；新增仅中文 `词条` 3→4、`转换` 74→78、英文 `Fusion` 174→178 等零星计数——**无新融合命名空间、无新机制对象**。
- Packages.bin 二进制标识符扫描（10 组正则）：新旧 build 融合相关标识符零 delta（唯一差异 `FuseP`——FX 粒子名）。
- **结论：词条融合的数值模型不在静态数据包中**——服务器侧下发（同 Cycle 元素/玄骸数值模式），或等正式内容 build 落盘。语言包里已有 `FUSE <FUSE_CURRENCY>|COST|` 格式串（Mod 融合=Endo 升级的既有 UI），可作为未来 UI 命名参考。

**二、反哺算法（根据配装算紫卡词条）强化——`recommend_optimal_riven`**

- 负面配对从「只配 3 正组合」扩展到 **2 正与 3 正组合都配**（2+1 结构的负面系数档位不同（0.5 vs 0.757525），最优负面可能完全不同——旧实现系统性跳过 2+1）。
- 负面头部随预算加宽：4（≤10s）→ 6（≤30s）→ 8（60s）。
- 阶段 3 精排用完整 keep 阶梯（7..0，含 keep7「紫卡换掉一张基准卡」的挂卡口径）；头部数量随预算（top_limit/3 → /2）。
- 自适应 beam：粗排提前完成（预算富余）时 beam 加宽一档。
- 端到端验证：Braton Prime + 4 卡配装，20s 预算 → 36.2s 全链路、3415 次评估、beam 10、负面头部 6，top 组合含 D+S+M- 等 2/3 正+负结构。
- 新增回归 `tests/test_recommender_upgrade.py`（3 用例：2+1 结构覆盖、完整 keep 阶梯、watcher 工具契约）。

**三、新数据包自动监测工具——`tools/watch-new-build.py`**

- `--dump`：检测游戏 build 比 dump 库新时自动跑 dump_all.ps1（Packages.bin + 双语语言包）。
- `--analyze`：新旧 build 内容 diff（聚焦 Lotus/Upgrades、Types/Items、Game、StoreItems、EE/Game 命名空间）+ Packages.bin 标识符扫描（10 组融合/紫卡相关正则）+ 语言包关键词计数 delta（en/zh），报告落 `.local/reports/new-build-watch/<build>-vs-<old>.md`；有新文件时退出码 3（可接 CI/脚本）。
- 实测当前状态：0 新增、标识符零 delta、语言包计数微变——与手工分析一致。

**四、全量验证**

- 36 项测试全通过（7 subtests）；wfsim 黄金集 43/43；py_compile/node --check/git diff --check 干净。

### 2026-09-23 Round 7（运行时数据获取路径 + 采集工具固化）

**一、运行时路径梳理（与用户确认安全边界后）**

- ✅ **路径 A——官方 Companion API**（已有基础设施 `WF_Rever/warframe-companion-5.3.5.0`）：走 Warframe 官方手机 App 协议（`mobile.warframe.com/api/inventory.php` 等只读端点），用自己账号 session，`auto_collect.py` 全自动（Steam 启动→登录→采集→退出）。**不是 hook/注入/内存读取**，风险=平时用手机 App 查仓库。实测当前仓库快照：`RawUpgrades` 363 条普通 MOD、0 紫卡（该账号无紫卡），但通道验证可读完整 `UpgradeFingerprint`（词条级数值 JSON）。
- ✅ **路径 B——公开 worldstate**（`collect_worldstate` 已在用）：无需登录零风险，新物品定义/商店条目先落这里。
- ✅ **路径 C——客户端二进制静态分析**（`nightcap-luau-dump` + objdump 工具链）：对磁盘文件逆向，不运行游戏零封号风险；客户端硬编码常量（如 Torid tick）从这条线挖。
- ❌ **路径 D——运行时 hook/内存读取**：用户明确不做（反作弊风险 + 收益不成比例——融合数值大概率服务器下发，API 响应直接可读）。

**二、意外发现：`RivenFragment` 材料类型**

- 账号仓库中存在 `/Lotus/Types/Items/MiscItems/RivenFragment`（紫卡碎片，7 个）——DE 为紫卡相关功能预留的材料类型。若词条融合需要消耗品，大概率是它或其变体；快照工具会对其变化立即报告。
- 另有 `OroFusexOrnament`（1999 融合宝物，Endo 融合用既有物品）——不要与词条融合混淆。

**三、新工具：`tools/collect-riven-snapshot.py`**

- 一键：Companion API 采集仓库（复用 `login_capture.py --once inventory`）→ 提取全部紫卡（含 `UpgradeFingerprint` 词条数值）+ 融合相关材料/货币 + 快照落盘 → 与上次快照 diff 报告新增项。
- 融合上线当天操作：正常玩→跑本工具→新紫卡 fingerprint（融合产物词条样本）与新货币立刻可见；多张样本 + `theoretical_structure_scale` 即可拟合融合数值缩放。
- 回归 `tests/test_riven_snapshot_tool.py`（2 用例：提取合同 + RandomMod 家族正则）。

### 2026-09-23 Round 8（静态逆向：Luau 脚本通道打通）

**一、重大发现：Luau 脚本字节码的静态提取路径**

- 游戏客户端的 **Font 缓存包**（`Cache.Windows\H.Font.cache`，2.5MB）携带全部 **5327 个编译后 Luau 脚本**（命名伪装成「字体」包；`--ls` 分类器不认识但 `--write-raw` 按内部路径直接取）。
- 提取路径（复刻 nightcap-lua-raw 试验的机制）：`Warframe-Exporter-CLI --write-raw --package Font --internal-path <路径>` → 输出 `.lua_B`（字节码）+ `.lua_H`（EE 参数声明头）。
- 反汇编：`nightcap_luau_dump <.lua_B>`（WF_Rever 现有工具，输出 UTF-16 需转码）→ 完整 proto/常量/指令流。
- **已提取并反汇编 8 个关键脚本**：BonusDamageOnNextHit（Double Tap，含 ApplyUpgrade/UnApplyUpgrade/OnProjectileContact/HudBuffLoop/GetModDescriptionInfo 五函数）、BioGrenade（Torid）、ProjectileEmbedTimeOnCondition（Renewed Horror）、UnlockAltFire（Latron 灵化）、SplitStatusProcsOnStackedStatusHit、BonusDamageForNextShot、BonusDamageNextShotForCurEnergy、RequireArmor。产物在 `.local/research/luau-disasm/`。
- BonusDamageOnNextHit.lua_H 头声明参数：`bonusDamagePercent`、`multTimeWindow`、`hudBuffType`。

**二、融合脚本静态确认（二次验证）**

- Font 包 5327 脚本全量关键词清点：**Riven=0、Fuse=0、Coalescent=0、Ascent=0**；Fusion 仅 6 个全部是既有 Endo/融合宝物 UI（ModFusion.lua、FusionTreasureManager.lua 等）。词条融合未落地客户端的结论再次被脚本通道独立证实。

**三、新工具：`tools/luau-extract.py`**

- `--list` / `--search <关键词>` / `--extract <路径>` / `--extract-dir <前缀>`（+`--disassemble`）——任何 script-driven 游戏机制都能静态提取反汇编。反汇编输出自动 UTF-16(BOM)→UTF-8 转码。
- 回归 `tests/test_luau_extract_tool.py`（4 用例：TOC 契约、融合脚本缺失哨兵（落地当天报错提醒重跑分析）、BioGrenade 提取+反汇编端到端、Double Tap 五函数契约）。

**四、进行中（subagent × 2）**

- Luau 反汇编深度分析（Double Tap 消费语义/重置规则、Torid/解锁脚本机制、引擎常量）。
- 引擎二进制逆向（Warframe.x64.exe 45.6MB，含 RTTI；已定位 mEmbedAttack/@34814185 字段元数据与 RadialOnMiss* 类型描述符/@36078771；用 objdump 定向反汇编 EmbedAttack tick 循环，交叉验证 wfsim 实测 1/s）。

### 2026-09-23 Round 9（静态逆向收尾：两大缺口闭合）

**一、Torid 场 tick 间隔——引擎逆向证实 1.0s（缺口闭合）**

- 路径：subagent 构建 PE 解析器（wfbin.py）→ RTTI 扫描 → 字段注册函数 fn_140c01880 反汇编 → **弹道类完整成员偏移表**（mEmbedAttack@0x950、mEmbedDamageRadius@0x954、计时器@0x8d0 等 100+ 字段）→ embed 更新函数 fn_14189a0ad 定向反汇编。
- 证据链：`fn_14189a0ad+0x88` 加载阈值常量 **0x14203bf94 = 1.0f**；计时器 `obj+0x8d0` 以 `dt × [projConfig+0x294]` 累积（每武器可覆盖的 tick rate）；`comiss` 与 1.0 比较 ≥ 时结算一次 EmbedAttack 伤害。BioGrenadeProjectile 无 TickRate 字段 → 引擎默认 1.0/s。
- **结论：Torid 毒云 tick = 1.0 秒，静态逆向证实，与 wfsim 实测一致**——不再是「静态无法获取需运行时」。
- 附带产出：弹道类成员偏移表（后续任何弹道机制逆向的现成索引）、DoT 应用函数 fn_140ccc940（每 tick 构造 5 个伤害类型条目）。
- sidecar 更新：`tickIntervalSeconds: 1.0`（引擎逆向证据标注），来源加 engine-reverse 条目。

**二、Double Tap 消费语义——Luau 字节码反汇编（缺口大部分闭合）**

- 反汇编结构：五函数（ApplyUpgrade/UnApplyUpgrade/OnProjectileContact/HudBuffLoop/GetModDescriptionInfo）+ buff 载荷常量 **BONUS/DURATION/CAP=100** + 引擎 buff 签名（instigator/affected/buffType/buffData/buffDataExtra）。
- **结论**：单次增益、命中消耗（proto 0.3 呈「读出→应用→清态」模式）、窗口过期（0.5s）、CAP=100%；**无叠加计数器、无失误重置分支**（旧登记 20 层/2.0s/resetOnMiss 无字节码依据，确认删除）。灵化直击受支持（投射物接线）；径向 unknown 维持。
- sidecar 更新：status → `conditional-supported`（数据已理解）+ 新增 `simulatorImplemented: false` 字段（引擎事件模拟未实现）；app.py fail-closed 门扩展为「conditional-supported 且 simulatorImplemented=false 也拒算」——数据到位但引擎未实现时绝不输出假收益。
- 置信度标注：常量与载荷结构为直接字节码证据；consume-on-use 基于 proto 0.3 的调用/清态模式（结构性证据单边支持，游戏内帧捕获可最终确认）。

**三、验证与交付**

- 42 项测试全通过（Double Tap fail-closed 测试在新状态下依然通过）。
- 逆向产物归档：`.local/research/engine-embed-tick.json`、`luau-mechanics-analysis.json`、`engine-disasm/`（含成员偏移表与全部函数反汇编）。

### 2026-09-23 Round 10（引擎裁决：Double Tap 伤害路径 + wiki 纠错）

**背景**：用户提供 wiki 记录（Latron Incarnon Genesis bugs：只有 AoE 吃 buff 直击不吃；切形态快照/恢复 buff 状态）与此前静态分析矛盾。按用户要求继续深入逆向（wiki 只作对照不作权威）。

**一、引擎伤害路径完整裁决（subagent 深度逆向，98 个工作文件）**

- `mUseNextShotDamageBonus` 成员 = **proj+0x658**（引用计数的 per-hit-type bonus 表 + 原始值 +0x660；字段注册 fn_140c01880@0x140c0220f，typedesc 0x1428cf410）。
- **直击消耗 bonus**：投射物冲击处理 fn 0x1400e2212 把 proj[0x658] 拷贝进出站伤害包（packet+0x180/+0x188，0x1400e2895-0x1400e28bf）→ 调用实体伤害虚函数 vt+0x5a8/vt+0x5a0——**倍率乘直击**。
- **径向不乘**：爆炸 fn 0x14148be10 构造径向包时传入**空哨兵表** 0x14272f3b0（ctor 0x14047c562-585）；径向伤害结算（vt+0x788）之后才 consume-and-clear proj[0x658]（仅副作用事件）。
- **buff 聚合**：fn 0x141807a80 计算倍率写入引擎 payload 键 NextShotMult/NextShotMult2。
- **per-form 状态**：bonus 表挂在 **behavior/fire-mode 对象**上（开火路径读 [[weapon+0x48]]+0x90）——各形态结构性独立保有状态；**无快照/恢复代码**（ClearChargesOnBehaviorChange 零静态 xref）。

**二、Wiki 纠错裁决**

| Wiki 记录 | 引擎裁决 |
|---|---|
| 「只有 AoE 吃、直击不吃」 | **推翻**——引擎接线完全相反（直击伤害包携带 bonus 表；径向包是空哨兵表） |
| 「切形态快照 buff 值+时长、切回恢复」 | **机制描述不准确**——实际是 per-behavior 存储（无快照代码）；但可观察行为「各形态独立 buff 状态」成立 |

**三、Prime vs Wraith（数据侧完整澄清）**

- Packages.bin 父链证实：Prime/Wraith 灵化波投射物**都继承自 LatronIncarnonAltFireWaveProj**（只覆盖数值字段）→ OnProjectileContactScript（命中叠加/刷新 buff，参数 _bonusDamagePercent=1/_multTimeWindow=1 即每层 100%/1s）**两者都继承**。
- 引擎伤害路径对两把武器完全相同（proj[0x658] 消费）。

**四、sidecar 更新**

- enginePath 段（成员偏移/直击/径向/聚合/per-form 存储/wiki 差异全登记）；modeRules 三条全部引擎裁决标注；Prime/Wraith 继承链说明；evidenceTypes 增加 engine-reverse 与 luau-disasm 两个证据类别。
- 交付物：`.local/research/nextshot-bonus-path.json`（完整裁决）+ `engine-disasm/nsb_*`（98 个分析文件）。
- 42 项测试全通过。

### 2026-09-23 Round 11（解算正确性排查：守望者异常 + KPM 差异）

**用户报告的三组问题与排查结果：**

**一、守望者 Prime 双爆负弹匣解算异常（1.3 亿 KPM / UNRESOLVED / 无膛室 Prime）——部分修复**

- 复现确认：`scoringValues` 天文数字（baseline 9300万 / actual 1.35亿 windowedDps）、`unresolved-lower-bound`、bestFound 无 Primed Chamber、postSearchProbe KPM=284 饱和。
- **根因 1（已修复）**：`expected_dot_damage` 的 Slash DoT seed 用 **dot_base（武器总基伤）** 而非 **该类型面板份额**——IPS 类 DoT 被高估 `dot_base/slash_share` 倍（物理武器 2-4×，Vectis 实测 2.65×：模型 766/s vs 正确 287/s）。修复：IPS（Slash/Impact/Puncture）seed 基数改为 `stats.damage_types[dtype]`（最终面板份额，暴击仍按 seed_tiers 分档），元素 DoT（Heat/Toxin/Elec/Gas）维持 `dot_base × elemental`。修复后模型 287 vs 手工 289（0.99×）。此高估与高暴击/多重叠乘后使 DoT 通道撑爆步进 KPM（240 饱和=每 250ms 步一杀）→ 千万级分母。
- **根因 2（遗留待查）**：搜索中间候选出现**异常膨胀面板**（capture 到 dmg=798,639、DT_CORROSIVE 38万 + DT_EXPLOSION 41.9万、`projectile-component-damage-unapplied`）——某候选的 stats 构建把投射物组件伤害算进了面板。需后续审计 `_evaluate` 的候选 stats 构建（尤其含爆炸组件的形态/`_branch_effects`）。
- 腔室 Prime 未被推荐：与上述两个问题相关（分母失真 + `first_shot_damage_bonus` 在负弹匣场景的协同未被正确排序）；根因 2 修复后需复验。

**二、PrimeBoltor 配卡 5.3 vs wfsim 1.3 KPM——部分定位**

- 复现（100k 血无甲自定义靶）：我们 KPM=159.5、79 杀、directWindow=7.94M；**物理上限** 340 攻击 × perShot 11,208 = 3.81M——入账是上限的 2.085 倍。
- 深挖（逐步插桩）：**per_attack 在步循环内从 11,208 涨到 ~23,000**——动态来源是 **puncture/cold proc 的 crit 覆写**（puncture 层数爬升给 +crit chance，模型允许到 +25%；0.24→0.49 cc 使 crit_avg 3.06→5.23，×1.71 ≈ 观测 1.79×）。入账与 per_attack 一致（无双重入账；340 次攻击枚举无重复）。
- **待验证**：puncture proc +crit 的游戏真实行为（上限/衰减/是否影响 DoT）需引擎逆向或游戏实测确认；wfsim 是否建模此机制。
- wfsim 同武器快测（base form + 近似 mod 映射）：**mod 映射无法对齐**（MagneticClipRifleMod 误映射 malignant_force 电卡），面板元素合成结果不同（我们 Viral+Magnetic+Fire vs wfsim Viral+Electricity）——**需精确 mod 映射后重跑同条件对比**才能下结论。
- wfsim 快测还显示：30 秒 228 发、3 次装填、downtime 7.2s（弹匣 84? 不——wfsim panel 与我们的 mag=84 reload=0 有显著差异，**灵化形态的弹匣/装填语义**需对照）。

**三、元素状态机制完备性（冰内置 CD 等）——登记待查**

- 当前模型：cold proc 削甲/crit 加成按 live_stacks 连续近似；**冰的「冻结」与触发内置 CD**（若存在）未建模；viral/magnetic/corrosive 的层数爬升已建模但无 proc 间隔 CD 概念。
- 待办：引擎逆向 cold proc 的 CD/冻结规则（走 Round 10 的 RE 管线：字段注册 → 消费函数 → 常量），确认哪些状态有 per-target proc cooldown。

**验证**：42 项测试全通过；wfsim 黄金集 43/43 保持收敛。

### 2026-09-23 Round 12（遗留事项完成：ADD_BASE 膨胀 + proc 暴击引擎裁决）

**一、守望者 80× 面板膨胀——根因修复（ADD_BASE 语义）**

- 插桩定位：`PrimeVectisEvoTier1B`（灵化进化「+150 基础伤害」）词条 `WEAPON_DAMAGE_AMOUNT / ADD_BASE / value=150` 被 `_combine(1.0, ...)` 当成「基值 1 + 150 = ×151 乘算」→ 150×151×2.551 = 57,780（385× 膨胀）。
- 修复：ADD_BASE 从 damage_scale 池分离，按类型份额摊入基伤向量（非变异拷贝），百分比 MOD 再乘增广后的基伤。回归 `tests/test_incarnon_add_base.py`（面板 300±30 / Serration 缩放 (150+150)×2.65=795）。
- 守望者端到端复验：scoringValues 从 9300万/1.35亿/1.59亿 → **101万/250万/303万**（44×↓）；targetStatus saturated-unresolved@9999 → **calibrated@298**；postSearchProbe KPM 284 → 48；scoreStatusReason 如实标注 `model-missing:projectile-component`（灵化波投射物 ExplosiveAttack 未建模，正确 fail-closed）。

**二、同条件 KPM 对比方法建立 + proc 暴击引擎裁决**

- wfsim 精确 mod 映射（magnetic_capacity 等同名卡找到）；复现用户数值：**wfsim 1.2763（用户的 1.3）vs 我们 5.36（用户的 5.3）**——同靶（Thrax Lv170 SP）同卡。
- 行为隔离实验（value-matched 面板对齐 940 vs 939.55、cc/cd/ms 全同）后：我们 3.45 vs wfsim 1.2763（2.7× 行为差）。
- **引擎逆向裁决（subagent，proc-mechanics-re.json）**：
  - **穿刺 crit：我们模型错误**——引擎无内建「每层 +5% 暴击率（上限 25%）」；对带 proc 目标的暴击只通过数据驱动的 `WEAPON_CRIT_CHANCE_IF_VICTIM_PROC_ACTIVE`（平坦值、非按层，GrnDrillScytheInnateUpgrade 实证）实现。
  - **冰 crit 伤害：我们模型错误**——引擎无每层暴伤加成；冰是冻结层机器（mBaseFreezeModifier 等字段）；WEAPON_FROZEN_CRIT_* 零原生内容使用。
  - **冰内置 CD：不存在**（proc 门控是乘法免疫检查 fn 0x14170e110，无计时器）。
  - **Viral 2×@10 层：机制确认**（fn 0x1410d28b0 → GetPairModifier 四容器），数值数据驱动（wiki 值维持）。
  - Buff 键簇完整枚举：proc 不走 buff 键系统（victim pair-modifier 系统）。
- 修复：删除窗口层的穿刺/冰 crit 覆写（臆造机制），mod 桶的 `WEAPON_CRIT_CHANCE_IF_VICTIM_PROC_ACTIVE` 类词条本来就正确处理。回归 `tests/test_proc_crit_contract.py`（3 用例钉住删除契约 + RE 产物存在性）。
- **收敛效果**：value-matched 我们 **3.45 → 2.26**（对 wfsim 1.2763 差距 2.7× → 1.77×）；用户原配卡（Expert 满级）5.36 → 3.75。

**三、Boltor 灵化弹匣语义澄清（非 bug）**

- 灵化形态 reload=0 是**有意近似**（注释已说明：170 充能池、ammoCost=0；30s×11.33/s=340 发恰好耗尽 340 容量——边界情况已记录）。
- wfsim 的 252 发/2 装填是 base form（对比时形态映射错误导致误判）。

**四、剩余差异（1.77×）登记**

- wfsim damage_sources 显示 Electricity DoT 15 万（magnetic proc 链电伤判定？）我们未建模；
- viral 曲线细节、reload/射速离散化差异；
- RE 产物 openQuestions：pair-multiplier 写路径（层数如何缩放条目乘数）、冻结字段默认值、四个 victim 容器的语义分工。

**验证**：44 项测试全通过；wfsim 黄金集 43/43。











## 发现项落地状态

（每完成一项在此追加一行：编号｜实现位置｜关联测试｜验收输出｜状态）

| 编号 | 状态 | 说明 |
|---|---|---|
| F01 | 已端到端完成 | 主循环直伤离散事件结算（`hybrid-event-settled-v2`），E01 三档实测与 ledger 一致；测试 `test_windowed_damage_contract.py::DirectLedgerAuthorityTests` |
| F02 | 已端到端完成 | 生产者显式合同字段 + 消费端按 per-proc 计价；D01 数量关系实测（触发数 2.8× → DoT 2.8×） |
| F03 | 已端到端完成 | `durationSeconds` 最终时长合同；D02 测试夹具 |
| F04 | 已端到端完成 | 代次生命周期（ramp 时钟/Heat Inherit/DoT 云按代次清理），`_settle_death` 统一重建 |
| F05 | 已端到端完成 | 质量阶段三曲线重绑统一 EvaluationRecord；缓存回写质量赢家（S03 重放合同） |
| F06 | 已端到端完成 | 结构系数按实际 positive_count 传递；2+0 实测 high=233.6（旧 177.0） |
| F07 | 已端到端完成 | `validate_build()` 统一校验器；必选卡物化 required；Add/Drop/Swap/floor/最终输出全覆盖 |
| F08 | 已端到端完成 | `ablationDelta`（消融）与 `reoptimizedDelta`（重优化）分离；前端主数值=消融 |
| F09 | 已端到端完成 | 搜索后升靶重搜闭环（`postSearchEscalation` 预算循环 + 冻结上下文重跑） |
| F10 | 已端到端完成 | `targetCalibrated`/`targetStatus`/`scoreStatusReason` 原因码合同；前端区分展示 |
| F11 | 已端到端完成 | 升靶缓存回退全上下文逐字段匹配（C01 修复侧） |
| F12 | 已端到端完成 | `mod_gains_payload` 缓存键补紫卡；C02 测试待补 |
| F13 | 已端到端完成 | 指纹补 app.py/combat_events.py；空指纹改显式失败 |
| F14 | 已端到端完成 | worker 持久化开关结构封死；bake 默认模式同口径；失败退出码修正 |
| F15 | 已完成 | 有序去重 + 槽位保持 Swap + 贪心多起点 + deep 档双槽成对交换 |
| F16 | 已端到端完成 | sidecar schema v2（证据类型/五态/固定来源）+ 审计计数分母合同 + extract.py 双 bug 修复 |
| F17 | 已端到端完成 | `.gitignore` 修掉；测试入库（14 passed） |
