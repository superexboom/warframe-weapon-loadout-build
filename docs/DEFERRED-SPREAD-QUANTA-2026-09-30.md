# 散布暂缓与量子立方体接触事件（2026-09-30）

## 本轮完成

- 散布按用户最新要求保留但不接入：几何公式、角度归并、逐弹丸 Encumber 实验保存在 deferred_spread.py；原生角度与来源哈希保存在 deferred-spread-profiles.json；原研究导入流程保存在独立 scratch-only 工具。生产解算、自动配装、贡献、紫卡评分均不导入该模块，也不读取角度字段。
- 移除默认流程中的散布命中折扣及命中率展示，清楚标注“散布暂不参与计算”。距离伤害衰减、爆炸半径、Primary Compression、Hema/Tiberon 的连发节奏维持独立逻辑。
- Quanta、Quanta Vandal、Tenet Quanta 的副模式加入接触爆炸：普通/Vandal 为 100 电直击 + 150 爆炸；Tenet 为 180 电直击 + 150 爆炸。直击与爆炸的自然触发率、暴击、弱点身份分别处理，接触爆炸不继承 dormant EmbedDeathAttack 的强制电击。
- 核实原生每发耗弹 10、ConsumePartialAmmo=0：剩余弹药不足一发则换弹，不能开火后欠账；非空换弹不触发空仓条件，不把剩余弹药叠加到新弹匣。普通分数耗弹已有语义继续保留。
- Quanta/Vandal 继承枪托近战明确排除远程配装；副模式身份用 ammoCost、原始直击伤害、投射物路径共同校验。
- 接触模式的自动候选、手动回放、紫卡移除贡献共享事件。导入工具重跑后档案一致，活动数据不重新引入散布。

## 验证结果

451 项测试 + 3 个子测试通过；追加 Primary Compression 断言后相关 31 项复测通过。Python 编译、JS 语法及当前数据重导入检查通过。AST 检查确认生产模块无 deferred_spread 导入；测试也断言即使注入旧角度字段，伤害和状态次数都不变化。

本轮重新搜索 7 把武器：Quanta、Quanta Vandal、Tenet Quanta，以及额外的 Attica、Argonak、Veldt、Stradavar Prime。全部 12 个可用射击模式自动分数与手动复算相等。两个继承近战模式明确排除，不计为远程解算成功。

固定实际完整配装，以 30 秒、1000 次、0.5m、9999 级钢铁凶魂百夫长、相同 MOD path/rank/槽序重放到参考。0.5m 是控制场景输入，不能解释成散布量化或实际战斗保证；本地始终不计算散布。参考使用此前已校验的源码身份 3605094 / 发布包 71d91a6c11e1 / WASM f0ea532cbccb，完整 SHA 位于 JSON 中。

| 模式 | 本地 KPM | 固定 WFSim KPM | 差异 |
|---|---:|---:|---:|
| Tenet Quanta mode 0 | 5.87660 | 1.79038 | +228.23% |
| Tenet Quanta mode 1 | 3.04442 | 1.23284 | +146.94% |
| Quanta mode 0 | 1.50315 | 1.49695 | +0.41% |
| Quanta mode 1 | 1.15875 | 1.04611 | +10.77% |
| Quanta Vandal mode 0 | 1.88073 | 1.86759 | +0.70% |
| Quanta Vandal mode 1 | 1.29824 | 1.27495 | +1.83% |
| Argonak mode 0 | 1.92827 | 1.87589 | +2.79% |
| Stradavar Prime mode 0 | 2.04122 | 2.01290 | +1.41% |
| Veldt mode 0 | 2.27789 | 2.24185 | +1.61% |
| Attica mode 0 | 1.34492 | 1.39464 | -3.56% |

Argonak 和 Stradavar Prime 的 mode 1 本地自动/手动均通过，但参考形态映射未核实，因此外部对照明确拒绝；没有替换为主模式或默认武器。普通 Quanta 副模式仍差约 10.8%，未宣称完全对齐。

## 信条元素差异与对照工具修复

早期对照未显式传本地默认 60% 火属性始祖，参考自行选择 25% 冲击，数据无效且只保留在 .local。现使用手动结果回显的实际始祖参数；有始祖字段的参考武器若没有显式参数即拒绝。原请求与解析后的对照请求分别保存，不修改原配装。

即使两端均为 60% 火，信条主/副模式仍差距很大。面板总伤害接近，但本地得到磁力+火、参考得到电+爆炸；这是自带元素合并顺序的差异。固定原卡仅把始祖改为 60% 电进行诊断，主/副差异降至约 +4.43% / +10.49%。该诊断不是重配最优方案，不替代原火属性方案验收，也不足以证明哪一边的全部元素规则正确。未据此修改通用元素合并或补倍率。

## 留待后续

- Quanta 射击立方体后的强化爆炸、9 秒自然引爆与链式引爆；本轮仅接触直击/爆炸，不把所有触发条件合并相加。
- Mutalist Quanta 的球体转换，Stug 堆胶/延迟/弹跳，Simulor 合球与奇点，Talons 手动起爆；需要进一步核实原生生命周期。
- 信条量子切割器的元素合并差异；普通 Quanta 副模式残差。
- 紫卡分析完整上下文、全量搜索和缓存重烘焙仍未验收。当前模型改变会使旧指纹缓存失效，不能继续当新模型结果。
- 散布按用户要求从待实现优先级中移出；只保留研究代码。Duelist 仍暂缓。

本轮没有 EXE 打包、游戏内实测或新浏览器布局验收。上轮提到的 Quanta Vandal +0.70% 是主光束结果，不是副模式证据；副模式是半自动立方体，并非蓄力。

## 复现

```powershell
python tools/import_quanta_contact_profiles.py --packages C:/Users/SuperExboom/Documents/WF_Rever/wf-arsenal/data/raw/2026.09.22.16.46/packages --wfsim .local/wfsim-source-20260927 --evidence .local/reports/new-quanta-contact.json
python tools/audit_nonmelee_catalog.py --output .local/reports/new-quanta-audit --weapons Quanta 'Quanta Vandal' 'Tenet Quanta' Attica Argonak Veldt 'Stradavar Prime' --distance .5 --profile fast
python -m pytest -q tests/test_quanta_contact_events.py tests/test_spread_events.py tests/test_torid_reload_fields.py tests/test_generated_build_comparison.py
```

详见 docs/evidence/quanta-deferred-spread-20260930/ 和 DEFERRED-SPREAD-README.md。旧证据与分片未改写。
