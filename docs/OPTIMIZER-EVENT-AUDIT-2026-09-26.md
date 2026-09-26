# 自动配装与多武器事件验收

日期：2026-09-26。基线 359363b，分支 codex/riven-anomaly-fix-20260922。保留已有工作树改动；原始配卡不改写。

## 执行清单

- [x] 确认旧候选评分、默认满层赋能与手动事件回放的分歧。
- [x] 统一候选初筛、beam、局部搜索、功能槽、紫卡推荐及移除贡献的事件上下文。
- [x] 扩到 26 把武器、86 个形态/条件案例；另执行 8 套完整自动配装。
- [x] 校验目标、赋能策略、紫卡顺序/极性、必选禁选、槽数与元素约束。
- [x] 固定 WFSim 源码及 WASM，完成 24 把远程武器的基础攻击对照。
- [x] 完成实际浏览器点击、全量回归、导入器复现及证据归档。

通过只指本报告规定的案例和口径；全武器机制完整度、全局最优或游戏内验证未列为已完成。

## 核心修复

### 自动搜索与手动回放使用同一计算链

1. 新增 search_combat.py：候选携带原始武器全部形态、当前形态、按槽排序的 MOD/紫卡、原始赋能及层数/覆盖率、进化分支和场景。prepare → replay 同时用于候选排序和最终复算。
2. 持续射击/普通攻击自动配装以 30 秒事件 KPM 评分。初筛、beam、局部改良、功能槽及紫卡比较均使用该计算链。显式重击/面板指标保留各自语义。
3. 使用用户实际目标、等级、钢铁之路、增强、人数、头部比例、ADS、真实循环、外部增益；修复普通自动配装固定 170 级、紫卡推荐固定 9999 级的混用。
4. 赋能默认为真实事件叠层；显式固定层数/覆盖率与 assumed_max 保持恒定，覆盖率 0 不会被击杀重新激活。原生双毒狂躁同样遵守策略。
5. 缓存版本升至 10，纳入新机制/数据指纹和上下文；非默认触发、ADS、真实循环场景不能误读旧静态结果。未重新烘焙静态缓存。
6. 已装备 MOD、紫卡和赋能的贡献以同一事件 KPM 移除复算；移除赋能同时移除其事件源。种族 MOD 不再被候选池和界面无条件排除。

### 排序、约束和页面接线

- 紫卡参与真实元素顺序；回填保留求解器槽位和紫卡极性，极化操作不重新排序元素。
- 紫卡推荐保留必选、禁选、槽数/填充上下限、目标元素、功能槽及容量费用，并返回可复算的完整方案；结果为 heuristic-best-found。
- 功能槽按加入后的事件增益比较；已选功能槽参与紫卡推荐的套装和容量计算。
- 修复前端漏登记 build-optimize-arcanes、build-min-fill、build-max-fill：之前页面勾选不保证赋能开关和填充上下限进入请求。
- 赋能文案改为“沿用当前触发策略”；返回 evaluationScenario/evaluationContext/evaluationTarget 供核对。主动排除赋能时，说明搜索与带赋能手动分数不可直接比较。

### 本轮补齐的武器机制

| 武器 | 修复 | 验证范围 |
|---|---|---|
| Torid | 分离 100 直击与 40 毒素持续场；1 Hz、10 秒、可叠加；目标死亡清理旧场；灵化直击充能 | 基础场伤害、灵化充能、自动/手动一致 |
| Felarx | 基础弹匣 6；装填含开始、逐发与结束时间，随弹匣变化 | 基础逐发装填，非全部进化脚本 |
| Mausolon | 72 火焰范围段独立于直击和弱点倍率 | 基础射击、中心单目标 |
| Opticor Vandal | 100 磁力范围段，不错误复制多重或弱点倍率 | 与导出数据匹配的 quick 模式 |
| Paris Prime / Nataruk / Cinta | 模式 0 为未蓄力/quick，修正蓄力与搭箭节奏混淆 | quick 模式，非全部完美蓄力窗口 |
| Dual Toxocyst | 原始包确认直接爆头后 3 秒狂躁；射速 x2.5、毒素 +100%、普通弹药消耗 0 | 身体/头部触发、持续、assumed_max |

新增参考攻击按路径、形态和基础伤害向量校验后启用，避免套错形态。首发增伤只作用于弹匣首发；零事件不刷新触发计时。

## 验证结果

### 26 把武器 / 86 个条件案例

- 步枪与光束：Braton Prime、Soma Prime、Latron Prime、Burston Prime、Boltor Prime、Ignis Wraith、Amprex、Torid。
- 霰弹与空战：Boar Prime、Kuva Brakk、Felarx、Kuva Hek、Corvas Prime、Mausolon。
- 手枪与其他枪械：Twin Grakatas、Lato、Lex Prime、Dual Toxocyst、Laetum、Phenmor、Opticor Vandal。
- 弓与近战：Paris Prime、Nataruk、Cinta、Nikana Prime、Glaive Prime。

86/86 候选事件评分与同配卡手动回放相等，涵盖首/末形态、身体/头部、ADS、真实循环、负 91.008% 异常持续和赤毒自带元素。部分武器仍有 unsupported；一致性不证明缺失机制已经实现。

### 8 套完整自动配装

统一 Lv9999 钢铁之路、50% 头部、ADS、Roar 50%；按案例启用循环和赋能。fast 档、8 槽、至少填 7；Burston 保留负持续紫卡。

| 武器 | 自动 KPM | 手动 KPM | 用时/秒 |
|---|---:|---:|---:|
| Braton Prime | 5.478417 | 5.478417 | 14.31 |
| Burston Prime | 23.030895 | 23.030895 | 11.17 |
| Torid | 9.553208 | 9.553208 | 10.33 |
| Felarx | 8.000000 | 8.000000 | 2.83 |
| Mausolon | 4.033330 | 4.033330 | 14.04 |
| Nataruk | 5.878030 | 5.878030 | 4.93 |
| Lex Prime | 4.641629 | 4.641629 | 6.17 |
| Nikana Prime | 6.412791 | 6.412791 | 3.61 |

8/8 完全一致：7 张 MOD + 紫卡或 8 张 MOD。另有小候选池全排列测试，确认排名确实使用事件分数。

### 原配卡与浏览器链路

- 原件 SHA-256：ed1c58baa76bfbfa787fd10ba66cac81f77d979d471a0f9347613160192a991e；复核未改写。
- 原卡、Archimedea 开启、未瞄准、真实循环：91.478580 KPM；Heat 最大 27.672 层、削甲达 50%，Truth 在约 6.133 秒触发。
- 保留原紫卡、进化、目标，自动更换普通 MOD，启用已配置赋能：fast 搜索约 45.37 秒；自动 214 KPM = 同配卡手动 214 KPM。91.48 与 214 是不同配卡的结果。
- 浏览器真实导入、点击自动配装、回填再回放：214 KPM；7 张 MOD + 原紫卡，原紫卡极性保留，容量 59/60；10 个 SVG 面板，无可见坏图，无页面错误。3 个空 src 图片均为隐藏占位。
- 贡献移除复算：移除敏锐主武后 83.108 KPM；移除紫卡后 51.083；移除赋能后 45.216。
- 负对照：关闭考虑赋能时搜索 94.413563，同样去掉赋能的手动结果也为 94.413563。带赋能手动的 178 不可与之比较。最初不相等的原始记录保留，修正上下文另存。

### WFSim 外部对照

源码：b98b3d456393131857e1c0e247b19aac6ecc08f4。release commit：becb34b1+；release：285450cbd40f。WASM SHA-256：697c63bfc0d2fe1c5da82e19adc9d76e54933bbc0baa9cd60c804e419fbe8f0f。源码与打包 WASM 身份分别记录。

24 把远程武器基础形态、裸枪、30 秒、无甲免疫异常高血量目标，200 次参考随机模拟。校验身份、形态与面板后，23 把可比，DPS 偏差均小于 2%（最大 1.988948%）。Dual Toxocyst 参考注册逻辑在 frenzy=false 时仍加入狂躁基础值，面板 150 对本地 75，列为不可比。

此项验证基础攻击、装填、范围或场伤害节奏，不代表全部配装、灵化形态、异常条件已与外部随机模型一致。

### 测试与再生成

- 全量：125 passed，12 subtests passed，505.92 秒。
- node --check frontend/app.js、Python 编译检查、git diff --check 通过。Git 仅有换行转换提示。
- 导入器新增 --output，隔离重建与当前 combat-reference.json 解析后完全相等：66 个充能档案、7 个基础攻击档案、1 个原生触发、25 个集团 MOD、12 把集团武器、6 个亲和点参考。
- 66 档案为 65 个弱点充能 + 已审计 Torid 直击充能；其他 direct_hits 档案不会因批量导入被误标为支持。

## 证据与复现

证据目录：.local/reports/2026-09-26-optimizer-events。

- parity-final.json：86 条输入、双方输出和 unsupported。
- auto-builds-full.json：8 套实际搜索、完整方案和手动请求。
- reference-aligned/comparison.json 及各武器请求/响应：外部对照。
- user-build-final/comparison.json：原卡四组条件、Heat、Truth 和 SHA。
- user-auto-with-arcanes.json / user-auto-with-arcanes-contributions.json：完整自动结果与贡献。
- user-auto-full.json / user-auto-context-corrected.json：原始失败与上下文修正负对照。
- browser-build-response.json / browser-click-result.json / browser-final-check.json / browser-final.png：实际页面与 API 链路。
- pytest-final-complete.txt / delivery-verification.json：全量测试及验收汇总。
- import-check/combat-reference.json：隔离重建，不改参考源或原始包。

从仓库根目录执行，证据输出文件须不存在：

```powershell
python tools/audit_optimizer_events.py --output .local/reports/new-audit/parity.json
python tools/regress_auto_build_events.py --full --output .local/reports/new-audit/full-auto.json
python tools/compare_weapon_events.py --wfsim .local/wfsim-source-20260926 --output .local/reports/new-reference
python -m pytest tests tools/test_data_pipeline.py -q --tb=short
node --check frontend/app.js
git diff --check
```

## 尚未覆盖的机制与搜索边界

1. 单目标、期望触发数事件模型，非逐弹丸 Monte Carlo。多目标、穿透/弹射、群体场重叠、集团角色恢复和队友亲和点未计入。
2. 部分灵化运行时分支和战甲状态条件未建模；Braton/Latron/Laetum 等灵化范围段保留 unmodeled。Torid Renewed Horror 云持续翻倍等条件尚未适配。完整诊断保存在 parity-final.json。
3. 搜索固定用户进化或既有默认进化，不联合穷举全部进化树；beam、局部搜索和推荐均为有限预算启发式，不证明全局最优。
4. 弓验证为匹配导出的 quick 模式；近战为当前普通攻击模型。完美蓄力窗口、全部架势连段、特殊重击及复杂重击优化需要专门验证；显式重击面板路径未冒称事件模型。
5. 没有通用 Lua/Luau 解释器；使用真实字段、脚本入口和已验证 adapter。未实现条件不会默认常驻全开。
6. Duelist 暂缓；未做全武器游戏内验收、全量缓存烘焙或 EXE 发布。交付为代码、数据、可重复工具、测试与证据。
