# 紫卡收益异常修复追踪

更新时间：2026-09-22（Round 4 后）
工作分支：`codex/riven-anomaly-fix-20260922`
审核基线：`a8e92c3644e39f5e92c360fad8486c7ed9d16549`（本阶段三个修复提交之上）
缓存策略：本阶段禁止烘焙/重建静态缓存；只有完成引擎回归并得到明确指示后才执行。

## 验收口径

本任务把「能显示结果」「能算出一个数」和「结果可作为紫卡推荐依据」分开。每个阶段都要同时记录：

- 公式/机制是否已实现；
- 是否接入真实紫卡分析入口；
- 是否有针对性回归证据；
- 是否允许进入静态缓存。

单元测试通过不等于真实分析路径完成；缓存存在也不等于缓存结果在新计算语义下可信。

## 本阶段修复（审计 F01–F17 落地）

详细执行记录见 `RIVEN-AUDIT-REMEDIATION-PROGRESS.md`。摘要：

| 编号 | 状态 | 交付 |
|---|---|---|
| F01 | 已端到端完成 | 主循环直伤离散攻击事件结算（`hybrid-event-settled-v2`），与 direct ledger 同一调度；审计反例（1 Hz/30 s/10×超杀=300 杀）修正为 30/15/3 杀与 ledger 一致 |
| F02 | 已端到端完成 | DoT 生产者/消费者显式合同（seedPerSecondPerProc 等），触发数正确缩放主项，累加项不再双重计费 |
| F03 | 已端到端完成 | durationSeconds 最终时长合同，删除第二次 ×duration_scale |
| F04 | 已端到端完成 | 目标代次生命周期（ramp 时钟/Heat Inherit/DoT 云死亡清理），`_settle_death` 统一重建 |
| F05 | 已端到端完成 | windowedDps 质量阶段三曲线重绑统一 EvaluationRecord（评分/展示/贡献/缓存同源，S03 重放合同） |
| F06 | 已端到端完成 | 结构系数按实际 positive_count（2+0 的 D high=233.6，旧 177.0） |
| F07 | 已端到端完成 | `validate_build()` 统一可行域验证器覆盖必选/禁选/数量/容量，全部搜索阶段 + floor + 最终输出 |
| F08 | 已端到端完成 | `ablationDelta`（同配卡消融）与 `reoptimizedDelta`（重优化）分离；主 delta=消融口径 |
| F09 | 已端到端完成 | 搜索后升靶重搜闭环（预算内逐级升靶 → 冻结上下文重跑三曲线 → 再验压力） |
| F10 | 已端到端完成 | `targetCalibrated`/`targetStatus`/`scoreStatusReason` 原因码合同；前端按原因区分展示 |
| F11 | 已端到端完成 | 升靶缓存回退全战斗上下文逐字段匹配 |
| F12 | 已端到端完成 | mod-gains 会话缓存键补完整紫卡 |
| F13 | 已端到端完成 | 指纹补 app.py/combat_events.py；依赖缺失显式失败（不降级空指纹） |
| F14 | 已端到端完成 | bake worker 进程级持久化开关（结构封死间接写路径）；默认模式镜像分析器；失败退出码 |
| F15 | 已完成 | 有序去重（保元素顺序）+ 槽位保持 Swap + 贪心多起点 + deep 档双槽成对交换 |
| F16 | 已端到端完成 | sidecar schema v2（证据类型/五态/固定来源/参考比例免责）+ 审计计数分母合同 + extract.py 双 bug 修复 |
| F17 | 已端到端完成 | tests/ 入库（33 用例），`.gitignore` 修掉 |

## 静态分析补全（subagent：zhipu/glm-5.3 max）

产出 `.local/research/*.json`（不入库，结论已并入 sidecar）：

- **Torid**：毒云=投射物 `EmbedAttack`（40 DT_POISON/proc 0.25/r3m/10s）；tick 间隔静态不存在（wfsim 实测 1/s 标记 cross-reference）；Incarnon 光束 51 DT_POISON 无场。
- **Opticor/Vandal**：径向在原始导出 impact 块（磁力 200/100，r6/4.6，fallOff 0.6，每发触发，吃基伤不吃多重，蓄力 ×2）；compact 导出因 extract.py 只读 projectileType 分支而丢弃（65 把 hitscan 武器）——已修 extract.py。
- **Latron/Double Tap**：mod=5% 下一发乘数/0.5s 窗口（非旧登记的 0.2/20 层/2.0s）；唯一 PvE 可用 PvP mod；灵化直击 supported、径向 unknown；灵化径向伤害确认（Prime 140/Wraith 100，r4m）。
- 另发现 `chargeTime` 大小写导出 bug（65 把蓄力武器 null）——已修 extract.py。

## 回归证据

- `python -m pytest tests/` → **33 passed（7 subtests）**：
  - `test_riven_calibration.py`（8）：原有账本/上下文/mod-gains/Double Tap fail-closed 合同（eventModel 断言升级到 v2）。
  - `test_windowed_damage_contract.py`（10+3 subtests）：D01/D02（DoT 数量与时长合同）、E01 三档超杀、E02 stale 组件、E03 同片双杀、E05 代次清理、E07 分箱无关、N01 生产接线负向测试。
  - `test_optimizer_contracts.py`（15）：S01 四结构、S02 验证器+必选存活、C01 回退上下文、C02 紫卡缓存键、C03 指纹、C04 worker 隔离+模式镜像、U01 原因码、S04 消融分离。
- `node .local/wfsim-converge/converge-check.mjs .local/wfsim-converge/result-golden.json` → **43/43 全收敛**（面板口径公式未受影响）。
- `py_compile`（app/extract/optimizer/audit/bake）× 通过；`node --check frontend/app.js` 通过；`git diff --check` 干净。
- 端到端冒烟：Braton Prime fast 档三正卡 111 s / 两正卡 79 s 正常解算，`ablationDelta` 与 `reoptimizedDelta` 分离正确，校准闭环与原因码字段齐备。

## 明确未实现 / 保持 fail-closed

- **已闭合（静态逆向）**：Torid 场 tick 间隔 = 1.0s（引擎 fn_14189a0ad 常量 0x14203bf94=1.0f，2026-09-23 逆向证实）；Double Tap 消费语义 = 单次增益/命中消耗/0.5s 窗口/CAP=100%（Luau 字节码反汇编，consume-on-use 模式）。
- Latron 灵化径向的 Double Tap 适用性：无静态证据（ExplosiveAttack 无脚本钩子）——unknown。
- Torid/Opticor 的场/径向伤害本体实现：伤害合同已登记且 tick 已证实，但 compact 导出数据源尚未重建（需要用修复后的 extract.py 重跑导出管线）——在重建+验收前保持 `weapon-radial-or-field-damage-not-in-export` 诊断路径。
- Double Tap 的引擎事件模拟：数据已理解（conditional-supported），事件账本实现待做——`simulatorImplemented: false` 期间 fail-closed。
- wfsim 目录中 Opticor Vandal 径向 300 与原始数据 100 不符（1.5×）——以原始导出为准，差异登记 openQuestions。
- 弹匣/装填/蓄力的精确开火调度（E04）：当前 `sustained_attack_rate` 平均口径仍是模型近似（attackRateSource 字段如实标注）。
- 搜索全局最优性：仍是 beam+爬山+多起点+双槽交换的 best-known（`scoreBasis: best-known-search-result`），不宣称全局证明。

## 缓存准入条件（后续）

只有下列条件同时满足，才允许重新烘焙：

- 真实窗口事件回归通过（本轮 33 项已过，后续引擎改动仍需全绿）；
- Torid/Opticor/Latron 的未建模机制在输出中可见且不会进入假精确评分；
- 搜索与评分使用同一 `contextHash` 和同一评价靶；
- cold/hot/bake 三路缓存测试通过（临时目录，C04 隔离已结构化保证）；
- 烘焙报告列出 profile、条目数、指纹、失败 shard、`qualityCalibrated` 语义。

## 词条融合（2026-09-23 布局）

- **当前判定**：今晚 0 点更新的 build `2026.08.19.11.06`（9/23 0:03 缓存落盘，已全量 dump）**不含词条融合数据**——201531 个对象与 8/13 完全一致（0 新增/0 删除/15 个无关热修），语言包与 Packages.bin 标识符零新增。融合数值为服务器侧下发或等正式内容 build。
- **已就绪的探测工具**：
  - `python tools/watch-new-build.py --dump --analyze`——检测新 build 自动 dump + 内容 diff + 融合/紫卡标识符扫描 + 语言包关键词 delta，报告落 `.local/reports/new-build-watch/`。融合数据落盘后第一时间可见。
  - `python tools/collect-riven-snapshot.py`——官方 Companion API（手机 App 协议、自己账号 session，无 hook）采集仓库 → 提取全部紫卡 `UpgradeFingerprint`（词条级数值）+ 融合材料/货币 → 快照 diff。融合上线当天融合一张任意紫卡即可拿到数值样本。账号现有 `RivenFragment` 材料（紫卡碎片）已被监测——若融合需消耗品大概率是它。
- **接入计划**（数据到位后）：融合词条若有新 UpgradeType/新 RandomModRare 结构 → `RIVEN_RULES`/`synthetic_riven_effects` 扩词条码；数值缩放若改变结构系数 → `theoretical_structure_scale` 与 `_structure_remap` 同步；`recommend_optimal_riven` 的组合搜索自动纳入新词条（候选行来自 `_candidate_lines`，无硬编码）。

## 发布边界

- 只提交本任务相关源码、数据 sidecar、追踪文档和必要回归；
- 推送到本分支，不合并到 `main`；
- 推送前使用本机 SOCKS5 `127.0.0.1:10808` 做连通性验证。
