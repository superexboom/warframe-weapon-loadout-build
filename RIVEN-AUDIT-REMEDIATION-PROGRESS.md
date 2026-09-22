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
| P4 | 搜索后升靶闭环 + 搜索质量（F09/F15） | F09 完成；F15 部分完成 |
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
| F15 | 部分完成 | 有序去重 + 槽位保持 Swap + 贪心多起点已落地；双槽交换与联合搜索待做 |
| F16 | 已端到端完成 | sidecar schema v2（证据类型/五态/固定来源）+ 审计计数分母合同 + extract.py 双 bug 修复 |
| F17 | 已端到端完成 | `.gitignore` 修掉；测试入库（14 passed） |
