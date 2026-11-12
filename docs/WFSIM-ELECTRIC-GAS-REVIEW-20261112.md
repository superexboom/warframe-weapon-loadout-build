# WFSim 电/毒气与磁破更新：Portable 跟进评估

核对日期：2026-11-12（UTC+8）。本轮仅调查与最小只读验证，未改计算核心、未烘焙、未同步 Bot。

## 版本与证据

- Portable：`f9db67799843efe89c1659a3a6ace017c0754fc3`，调查开始工作区干净。
- WFSim main：`ad5849ddce87c2934efdb2c65edfb0c0340483c8`，提交时间2026-11-12 17:55:37 UTC+8。
- 主要更新：[ef4fa11f7284501b2b6a6f0dbc196ed26dc8c131](https://github.com/magenie33/wfsim/commit/ef4fa11f7284501b2b6a6f0dbc196ed26dc8c131)，11月12日14:32:49；[d12163712546f998599759f73822709086211fba](https://github.com/magenie33/wfsim/commit/d12163712546f998599759f73822709086211fba)，17:03:14。
- 公开release声明：`engine=5ddb771d2cb1`、`data=4de0096387f5`、`wasm=07e4a69ccb99`、`commit=0af950a1+`。这里只核声明，未执行该线上WASM，不将它与Git main视为相同身份。
- 上游依据为作者提供的实测、测量文档及实现；不是本轮自行游戏实测，也不是DE官方确认。
- 本地保存12个上游文件、两份完整commit diff和release声明：`.local/delivery/wfsim-electric-gas-review-20261112/`。

## 结论

需要跟进，范围是一次中等规模的状态模型修正，不是更新两行元素倍率。四块主要工作是：

1. 电/毒气共享tick组、时钟与累加项；
2. 最新成功施加异常的落点与历史伤害种子的分离；
3. 气/电致死tick的head/weak-point归属；
4. 磁破派生电触发通过普通电异常入口执行。

基础0.5系数、Gas十层保留、单层种子继承暴击/施加部位、气/电再次吃头部奖励的主项已有覆盖，不应全部推倒重写。现有Python/Rust一致不代表已满足最新实测合同。

## 上游本次改了什么

### 1. 末次成功proc决定整组落点

每一层保留当次施加命中的头/身与暴击种子；同一目标的同类气/电pile，在跳伤时使用**最后一次成功施加该异常**的落点倍率与head/weak-point标记。不是最后一次普通命中，也不是把旧种子改写成新种子，tick不重新掷暴击。

M100最新样例：Laetum基础160、+80%头部伤害奖励、Lavos +200%对应元素。相同两次头proc与一次身proc的种子，因顺序不同：

- 头→头→身：2833.5，显示2834；
- 身→头→头：5100.3，显示5100。

此设置中末层head landing为1.8，所以整跳差1.8倍。这不是所有武器统一获得1.8倍，不能外推为KPM提升80%。head/body相同bonus为1时，伤害倍率可能相同，弱点击杀布尔归属仍然不同。

### 2. 电/毒气tick可以产生弱点击杀

上游实测中：最后异常施加在头部，致死tick可获得headshot-kill/Deadhead资格；最后异常施加在身上则不行，即使旧层保留很多头部/暴击伤害。实现同时影响共享弱点击杀触发器，例如Galvanized Scope/Crosshairs。

这不意味着Slash、Heat、Toxin全部改成爆头，也不意味着爆炸/子弹头一律具备头部资格。此处Gas是毒气，不能扩展为Toxin毒素。

### 3. 磁破产生普通电异常

破盾/破超宏时，以破掉池子的最大值和当时磁层数生成基础种子；磁层数量在该次事件快照。属性上下文来自**实际造成破盾的武器**，不是先前叠磁的武器。

派生电异常进入普通电pile：读取相应电伤、异常伤害、派系/Roar和持续时间规则，共享电tick时钟、累加项和落点状态。它自身按身体施加，因此会把已有头部电pile改回身体落点；后续头部电proc又可以改回头部。武器基础伤害和破盾命中的暴击/头部倍率不直接放大该目标池基础种子。

实测10磁层在全身/全头瞄准下均为3455，另加165%电伤为9154；比例约2.64949，支持电元素倍率，但显示值的精确舍入重建尚未闭合。持续时间/换武器归属有定性实测，未给完整逐跳数值。应区分这些证据强度。

## Portable 现状与差距

| 项目 | 本地实际实现 | 跟进判定 |
|---|---|---|
| 施加命中的seed | `damage.py::expected_dot_damage`继承部位与暴击；气电再乘headshot bonus；Rust `tables.rs`同构 | 已有单次主项；应拆出tick landing，不重复乘第三份 |
| 最新proc落点 | instance只有dtype/per/count/end/origin_mode；无每目标每类最新landing；head/body预先期望混合到per | 缺失，需独立状态；不能用普通末击覆盖 |
| 电/气共享clock | 每层按施加时间`t+j`排自己的tick | 与上游共享clock不一致，是本次同时确认的旧缺口 |
| 累加项 | helper区分shared group，但事件replay对shared类型只取seed，气电未加组累加项；helper累加项也未吃独立landing | 必须一并校准，不能只加head字段 |
| 气电弱点击杀 | Python明确`False: A DoT kill ... never a weak-point kill`；Rust `WeakKill::Flag(false)` | 与新合同直接冲突；只修符合资格的气/电 |
| 磁破公式 | `pool * .03 * stacks * proc_damage^2 / 6`，手工安排固定六跳 | 仍是旧专用公式，需要进入普通电proc路径 |
| 磁破电状态可见性 | 已登记electricity presence，可触发目标有电条件 | 已覆盖，保留该能力；它不等于普通电公式已覆盖 |
| 邻居电弧、气云 | 当前核心是单目标 | 本轮不顺带加群体收益；只处理当前受击目标的pile |

### 最小只读检查

- 用现有helper探查，base100、无暴击、head part=3，额外头部倍率1.8时：body seed50、head seed486，即`50*3*1.8*1.8`。说明旧版“头部奖励吃两次”的seed主项已经存在。
- 电与气在2发/秒、1.1秒窗口下，事件序列都是`t0一跳、t0.5一跳、t1两次独立tick`，确认当前没有完整的同类共享clock。
- 复用现有8项相关用例，全部通过；这些用例证明当前旧合同仍然生效，**不是新机制验收通过**。未新增测试文件。
- timeline探查走Python；Rust差距由当前源码确认，未在本轮重编译并宣称新原生合同通过。

## 为什么需要改到搜索层

Portable使用期望值模型，headshotChance通常是0到1之间的概率。本次规则有“最新落点”和“已有各层seed”的相关性，不能简单写成：

```text
平均seed总和 × 平均landing
```

也不能把每层自己的landing提前烤进seed后一直不变。需要保留成功proc的头/身条件状态或等价的有限统计表示，明确零proc、多个proc、同帧顺序和目标代次。是否需要更细分支须先用小样例验证，不为同步此项直接迁成高成本全Monte Carlo。

静态评分、事件重放、手动模拟、优化器候选排序都消费这些结果。只修手动展示而保留Rust候选打分旧模型，会造成“搜索选中一套、最终模拟又不同”。

## 影响优先级

- **高：** 电/气状态构筑，尤其有Deadhead类头部奖励或依赖弱点击杀增益，并混合头/身施加的武器。赋能与镀层是否能叠起来也可能变化，不仅是最终伤害数字。
- **高：** 有磁异常且会破盾/超宏的自定义目标、实战对照。电伤、异常伤害和持续时间MOD的边际收益会变化。
- **仍需覆盖：** 同伴及0%头命中场景没有混合头身问题，但共享tick/累加项仍可能改变时间线。
- **不能泛化：** 纯直伤、无电/气/磁破的固定配装未必数值改变；但优化候选可能包含受影响分支，不能只看最终面板元素决定缓存可复用。
- **Bot特定边界：** 固定预设是50%弱点（同伴0%），所以latest landing与seed相关性值得优先处理。其默认Lv170靶经实际配置解析，shield=0、overguard=0；磁破这一支通常不在默认评分靶上触发。不能因此说Portable自选靶或将来的Bot目标同样不受影响。

## 建议实施顺序与最小范围

1. **先整理seed/landing/accumulator合同。** 让producer输出未含二次landing的seed、组累加项来源、部位资格与持续时间；保留原施加命中的暴击与部位信息。
2. **实现按目标代次、按气/电类型的共享tick状态。** 维护latest successful proc landing；调度共同clock，并保留各层自身寿命、Gas十层替换和明确未验证的过期边界。
3. **接入致死tick归属。** 气/电使用实际最新landing资格；非气/电与爆炸/子弹特殊规则保持各自合同。
4. **磁破统一入口。** 只构造目标池基础种子与破盾武器来源，复用普通电状态、duration、clock和landing；避免继续维护独立六跳公式。
5. **同步评分与native能力门。** Python/Rust状态、窗口/稳态评分及接口一致；旧core不能静默执行新DTO。用实际native/shadow验证，性能仍以有限状态实现为目标。

直接涉及约6–8个核心/桥接文件，按最终DTO调整可能另含一处Rust稳态消费者：

- `vendor/wfarsenal/damage.py`
- `vendor/wfarsenal/combat_replay.py`
- `native/wfcore/src/tables.rs`
- `native/wfcore/src/proc.rs`
- `native/wfcore/src/replay.rs`
- `vendor/wfarsenal/native_replay.py`
- `vendor/wfarsenal/status_native.py`
- `native/wfcore/src/sustained.rs`（复核评分消费）

测试复用`test_combat_replay.py`、`test_kpm_event_semantics.py`、`test_nonmelee_community.py`等原有用例。优先三个核心合同：混合落点/整跳、气电弱点击杀、磁破普通电构造；同时删改“全部DoT不能弱点击杀”“固定六跳平方异常倍率”旧断言，不复制上游整套新增矩阵。

## 仍不能从这批实测直接推定

M100明确未覆盖：最后一个造成新异常的普通命中之外的“无异常末击”、最新层先过期后锚点是否变化、多来源竞争、邻居接收情况。磁破新增读数也未给精确duration逐跳和全部舍入边界。

这些需要保留证据限制；“上游实现暂时保留最新landing直到新proc”与“实测已经证明任意过期顺序”是不同表述。当前单目标模型也不能借此推导额外群体伤害。

## 缓存与发布

`damage.py`、`combat_replay.py`和相关桥接属于分析输入指纹；实现变化会使旧statics失效。Rust源本身不直接在该Python指纹列表内，不能只替换`.pyd`却保持对外合同不变。

现有保守增量工具对共享引擎变化不允许跨代复用，不能直接保证“只重烘电/气武器”安全。合理顺序是：四块一起落地→最小实测合同和Python/Rust一致性→少量实际配装/性能预检→冻结→按发布需求统一烘焙一次。当前缓存仍代表旧机制，不能把其11月3日完整覆盖当成11月12日新模型正确性。

## 可复核来源

- [WFSim M100 当前实测与范围](https://github.com/magenie33/wfsim/blob/ad5849ddce87c2934efdb2c65edfb0c0340483c8/docs/measurements/M100-electricity-and-gas-ticks-land-on-a-part.md)
- [WFSim M08 磁破来源](https://github.com/magenie33/wfsim/blob/ad5849ddce87c2934efdb2c65edfb0c0340483c8/docs/measurements/M08-magnetic-break-proc-attribution.md)
- [WFSim DebuffState](https://github.com/magenie33/wfsim/blob/ad5849ddce87c2934efdb2c65edfb0c0340483c8/engine/src/fight/debuffs.rs)、[tick消费](https://github.com/magenie33/wfsim/blob/ad5849ddce87c2934efdb2c65edfb0c0340483c8/engine/src/fight/ticks.rs)、[磁破构造](https://github.com/magenie33/wfsim/blob/ad5849ddce87c2934efdb2c65edfb0c0340483c8/engine/src/fight/stacks.rs)
- [Portable damage.py](https://github.com/superexboom/warframe-weapon-loadout-build/blob/f9db67799843efe89c1659a3a6ace017c0754fc3/vendor/wfarsenal/damage.py)、[combat_replay.py](https://github.com/superexboom/warframe-weapon-loadout-build/blob/f9db67799843efe89c1659a3a6ace017c0754fc3/vendor/wfarsenal/combat_replay.py)、[native replay](https://github.com/superexboom/warframe-weapon-loadout-build/blob/f9db67799843efe89c1659a3a6ace017c0754fc3/native/wfcore/src/replay.rs)
