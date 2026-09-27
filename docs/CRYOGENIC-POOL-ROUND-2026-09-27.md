# 次要·低温与重复击破修复（2026-09-27）

状态：本轮实现、实际自动搜索和跨引擎对照已有证据；全非近战验收未完成。Duelist 仍延期。本文接续 `RADIAL-CATALOG-ROUND-2026-09-27.md`，没有把历史测试或单纯目录匹配计作全量通过。

## 已完成

- [x] 次要·低温按原生脚本与条件签名接入：每次穿刺异常在主目标追加冰冻，R0–R5 层数为 1/1/2/2/3/3，半径 10–15m。持续时间、超宏四层限制、冻结/解冻、冰冻暴伤走现有共享事件路径。邻敌仍不计算。
- [x] 清除旧合成占位词条对计算的影响，禁止把追加冰冻误当成触发几率或冰元素伤害；目录、手动回放、自动评分、装备贡献均识别同一适配器，陌生脚本参数继续拒绝。
- [x] 修复浮点残值导致的同一超宏/护盾重复击破。达到击破阈值时先把该池置零，再发磁力击破电击；记录 targetGeneration，回归断言每个敌人每种池最多一次击破。
- [x] 新增真实自动配装回归样本，验证此前同一时间的两次超宏击破只剩一次。重搜自动配装，验证新评分确实改变选卡。
- [x] 触发条件文字贯穿适配器、优化器元数据、实际回放和页面；Stug 明示开火叠层、换弹/形态切换清空。固定层数/覆盖率与事件累积单独标注。修复空悬浮提示初始遮住曲线标题。
- [x] 分片合并拒绝不同模型指纹、无版本清单、过期行和冲突重复武器；尚无结果的活跃分片也纳入计划总数，不能只对已完成行计算覆盖率。
- [x] 公开配装审计默认遇到目录阻塞或原生不兼容时继续检查下一份原始配装，保留跳过原因。`--allow-partial` 仅供明确的离线诊断，不能混入可导入配装验收。

## 原始证据与参考版本

原生 `SecondaryColdOnPuncture` 参数、条件、SHA-256：`evidence/radial-round-20260927/cryogenic-native.json`。参考冻结目录 source `bb1dcb69b7045b62b8a858dad7550d4458624719`；release `39047c9ca078`；WASM `7e893c83e508`。完整请求、原卡路径/等级、版本 hash 与基线均保存在 JSON。没有修改参考代码。

## 从差异定位到根因

Aksomati Prime 的新自动方案在安装次要·低温后，本地 4.888 KPM、参考约 3.672 KPM，偏高 33.13%。两个引擎都是 605 发，基础面板一致；不能归咎于射速或去调整整枪倍率。

七组单项消融中，去掉低温后偏差仅 0.35%，去掉磁力卡后 0.28%，去掉元素增幅后 2.13%。事件记录显示 **6.953947s** 与 **19.052631s** 各出现两次同一敌人的超宏击破：第一次扣除后留下浮点微小正数，已经发过击破事件，但下一个同刻事件又进入非零超宏分支。

置零修复后，同一套原卡为 **3.696 KPM 对 3.672 KPM（+0.66%）**；射击次数不变，重复磁力电击消失。这是本地错误，不能计入 WFSim 异常豁免。详见 `cryogenic-aksomati-ablation.json` 的 beforeFix、当前结果和 unchanged reference responses。

## 修复后重新搜索的自动配装

每套实际搜索 8 槽，保留满级次要·低温。Lv9999 钢铁 Thrax、30 秒、瞄头、ADS、0.5m、seed 12648430，参考 1000 runs。没有仅重算旧最优方案后冒充重搜。

| 武器 | 自动/手动 KPM | WFSim KPM | 差异 |
|---|---:|---:|---:|
| Aksomati Prime | 4.06612 | 4.02648 | +0.985% |
| Akbolto Prime | 3.46341 | 3.29485 | +5.116% |
| Kuva Twin Stubbas | 5.61374 | 5.62324 | -0.169% |

三套自动分数与对应手动回放逐项一致。Aksomati Prime 重搜后的选卡发生改变。Akbolto Prime 的 Cannonade 穿透仍明确报未支持；以上是单目标比较，不能据此宣称多目标/穿透已实现。

复现：

```powershell
python tools/regress_auto_build_events.py --cryogenic --full --output .local/reports/new-cryogenic-auto.json
python tools/compare_generated_builds.py --wfsim .local/wfsim-source-20260927 --builds .local/reports/new-cryogenic-auto.json --runs 1000 --output .local/reports/new-cryogenic-reference
```

## 固定公开配装的赋能矩阵

本轮另取 Aksomati Prime、Akbolto Prime、Kuva Twin Stubbas 三把的玩家原始配装，每把空赋能加参考列出的 18 种赋能，共 **57 项**。**51 项**本地可计算且与生产手动调用一致；**6 项**是三把各自的 Akimbo Slip Shot/Cascadia Empowered 尚不在生产目录，未伪造为零收益。参考调用无错误。`cryogenic-fixed-build-arcanes.json` 保留全部行与修复后本地重算。

Akbolto Prime 的最高单目标公开行带当前不支持的 Eject Magazine。工具记录并跳过 10 份此类方案，最终使用原始第 40 行，不擅自删除扩展槽卡。最初第 30 行仍保留为明确的历史部分诊断。

低温在 Aksomati Prime 固定公开配装上的增益是本地 **+3.902%**、参考 **+3.870%**；Kuva Twin Stubbas 是 **+0.00497%**、参考 **+0.00494%**。Akbolto Prime 此固定方案仍有较大基线/增益差异（低温后 +10.74% KPM），保留为待查，不能以其他两把接近来关闭。

## 范围武器与界面复核

浮点修复后，旧九套范围配装有六套回放数值不变，三套发生变化。对变化的 Kuva Bramma、Acceltra Prime、Synoid Simulor 重新执行 8 槽自动搜索；自动/手动逐项一致。跨引擎仍分别约 +24.65%、+96.66%、+178.91%，故集束、散布和合球仍未关闭。证据为 `radial-poolfix-rescore.json`、`radial-auto-poolfix.json`、`radial-auto-poolfix-comparison.json`。

页面使用实际 `/api/simulate` 返回的 Stug 配装数据渲染，验证说明可见、标题位于首部、折叠后说明隐藏、空悬浮提示初始隐藏，低温目录可见；截图已人工查看。见 `trigger-ui-validation.json`、`trigger-conditions.png`。

## 回归与全局范围

- 低温初次集成后全测试 **380 passed / 7 subtests**，787.05s；此后发现并修复重复击破，不能把这次结果宣称为最后两行修复的完整回归。
- 最后池修复后的相关回归 **170 passed**，6.08s；最终完整回归 **381 passed / 7 subtests**，730.82s，完整记录见 `evidence/radial-round-20260927/validation.json`。
- 分片版本/覆盖率与精确卡片映射额外回归 **14 passed**，1.78s；其中三项合并门禁测试在完整回归收集后新增，已另测。
- `node --check frontend/app.js` 与 `git diff --check` 通过。
- 当前非近战库存为 **409 把 / 608 个显式模式**，其中 **70 把灵化武器**；380 把可按内部路径匹配参考条目。这是库存，不是已通过数。`coverage-inventory.json` 中每一项仍明确要求配装、赋能与灵化验收。
- 后续继续完整目录带指纹回归、全部灵化、未实现赋能与攻击部件；核心稳定后再反哺紫卡分析和最佳紫卡。主武器压缩对异常伤害的归属仍无独立证据，不强行拟合参考。
