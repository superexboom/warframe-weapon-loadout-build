# 紫卡收益异常修复：F01–F17 落地执行追踪

**更新时间：2026-09-22（滚动更新）**
**工作分支：`codex/riven-anomaly-fix-20260922`**
**审核基线：`a8e92c3644e39f5e92c360fad8486c7ed9d16549`**
**依据报告：`RIVEN-REMOTE-SOURCE-AUDIT-a8e92c3-20260922.md`**

> 本文档跟踪审计报告 F01–F17 的实际落地。每一项按「已端到端完成 / 仅基础设施 / 未实现 / 证据不足」标注，并记录实现位置、关联测试与验收输出。缓存策略不变：本阶段禁止全量烘焙；所有缓存测试使用临时目录，不触碰用户 `.local/cache` 旧文件。

## 总进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 测试目录纳入版本控制 + 失败测试（F17） | 进行中 |
| P0 | 缓存安全边界（F12/F13/F14） | 进行中 |
| P1 | 权威评价器：直接射击调度（F01）、DoT 合同（F02/F03/F04） | 进行中 |
| P2 | 统一评分记录（F05/F06/F07/F08） | 进行中 |
| P3 | 机制登记与静态分析补全（F16 + subagent） | 进行中 |
| P4 | 搜索后升靶闭环 + 搜索质量（F09/F15） | 进行中 |
| P5 | 小样本缓存回归 + 状态合同（F10/F11） | 进行中 |

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


## 发现项落地状态

（每完成一项在此追加一行：编号｜实现位置｜关联测试｜验收输出｜状态）

| 编号 | 状态 | 说明 |
|---|---|---|
| F01 | 已端到端完成 | 主循环直伤离散事件结算（`hybrid-event-settled-v2`），E01 三档实测与 ledger 一致；测试 `test_windowed_damage_contract.py::DirectLedgerAuthorityTests` |
| F02 | 已端到端完成 | 生产者显式合同字段 + 消费端按 per-proc 计价；D01 数量关系实测（触发数 2.8× → DoT 2.8×） |
| F03 | 已端到端完成 | `durationSeconds` 最终时长合同；D02 测试夹具 |
| F04 | 已端到端完成 | 代次生命周期（ramp 时钟/Heat Inherit/DoT 云按代次清理），`_settle_death` 统一重建 |
| F05 | 进行中 | 统一 EvaluationRecord（DPS 重搜结果未绑定最终展示配卡） |
| F06 | 待开始 | 两正紫卡结构系数（`theoretical_structure_scale(3, ...)` 写死三正） |
| F07 | 待开始 | 搜索约束旁路（required 标记/beam 阶段 max_fill/riven-floor 路径） |
| F08 | 待开始 | 逐词条贡献 = `_best_fixed` 子集重优化而非同配卡消融 |
| F09 | 待开始 | 搜索后升靶无闭环（`post-search-saturated` 直接返回） |
| F10 | 待开始 | 三轴状态合同（targetStatus/searchQuality.targetCalibrated 冲突） |
| F11 | 待开始 | 升靶缓存回退不完整匹配战斗上下文 |
| F12 | 已端到端完成 | `mod_gains_payload` 缓存键补紫卡；C02 测试待补 |
| F13 | 已端到端完成 | 指纹补 app.py/combat_events.py；空指纹改显式失败 |
| F14 | 已端到端完成 | worker 持久化开关结构封死；bake 默认模式同口径；失败退出码修正 |
| F15 | 待开始 | 去重破坏元素顺序 + 搜索增强 |
| F16 | 进行中 | 静态分析三路完成（.local/research/*.json）；sidecar/审计矩阵更新待做 |
| F17 | 已端到端完成 | `.gitignore` 修掉；测试入库（14 passed） |
