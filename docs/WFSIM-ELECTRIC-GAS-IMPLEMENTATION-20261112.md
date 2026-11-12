# Portable 电、毒气与磁破实现记录

日期：2026-11-12。基线 `f9db67799843efe89c1659a3a6ace017c0754fc3`；上游依据固定为 WFSim `ad5849ddce87c2934efdb2c65edfb0c0340483c8` 的 M100/M08 与对应实现。详细来源、调查前差距见 [跟进评估](WFSIM-ELECTRIC-GAS-REVIEW-20261112.md)。本记录是实现和代码验证，不是新增游戏实测。

## 执行清单

|事项|状态|落点|
|---|---|---|
|拆开 applying seed、latest landing、group accumulator|完成|Python damage / Rust tables 与 sustained|
|电/毒气共享跳伤、落点相关性与 Gas 十层|完成|Python proc_probability / combat_replay；Rust proc / replay|
|电/毒气弱点击杀、磁破普通电入口|完成|两份事件重放与来源传递|
|producer 与 native DTO、窗口评分入口|完成|native_replay / status_native；旧 core 能力门|
|独立数学复核、删除被替代的旧分支|完成|三个小型数值控制；删除旧 Gas 独立跳伤路径|
|现有回归、native shadow、性能对照|完成|335项通过；原生基线/新实现对照|
|源代码提交和远端核对|随本次已验证变更交付|`Preview/performance-delivery-20261025`；提交身份以Git历史为准|

本轮只修改 Portable。计算任务使用单 worker，Rust 构建最多4并发，未超过用户要求的10。未启动全量烘焙、Bot移植或安装包 release。

## 已实现的合同

- 电/毒气每层保存施加时的 seed（包括第一次部位、暴击等既有规则），第二次 landing 独立保存。只有成功新增该异常才更新落点；不把一般命中当成更新。
- 同一目标代次、同类异常使用共同的一秒跳伤时钟。一组只加一个 accumulator，Gas 保留十层上限；死亡重置组和时钟。
- 条件分支携带同一实际属性视图下的 proc count、absence、seed、landing 和 weak 标记。Enervate、受害者暴击修正和派生 proc 不再拿原始武器的 absence 代替分支概率。
- 单弹丸机会按顺序折叠，用有限条件矩保留 `E[seed × latest landing]`，包括未触发的概率质量、Gas 保留次序以及空组不支付 accumulator。未新增 Monte Carlo。
- 最新落点的 weak 布尔值独立于数值倍率；合法头部倍率恰好为1仍有相应资格。无有效头部代理时不凭空赋予 DoT 弱点击杀资格。投射物 `ignore_headshot_bonus` 仍遵守原有特殊规则：抑制原始部位倍率，不取消独立的死首类奖励或头部事件。
- 磁破 seed 使用 `poolMax × 0.03 × min(magneticStacks,10) / 6`，再走破盾来源武器的电元素、异常伤害、派系和持续时间。异常伤害只乘一次；派系对 seed 为两层、accumulator 为一层。身体 landing 进入现有电组，可以被后续成功的头部电异常改写。
- 直接、延迟、热、毒、毒气等破盾来源随事件传递；Gas 已被十层上限淘汰的 cohort 不能被选作派生电的来源。
- 稳态评分在固定落点下使用整组一次 accumulator；窗口评分的电/毒气路径进入事件核心，并提供固定属性 resolver 以允许 native 执行。Native `ELECTRIC_GAS_PROC_PILE` 能力门防止旧二进制消费新 DTO。

## 数值与回归

现有测试承载三项核心合同：共享组及条件相关性、弱点击杀归属、磁破入口。删改旧的“所有 DoT 不具备弱点击杀”和“磁破固定六跳、异常倍率平方”断言；没有新增测试文件，也没有新增一次性验收脚本。

小型独立枚举控制：

|控制|期望结果|
|---|---|
|M100 两头一身，HHB / BHH，seed 240 / 1296，acc 1.5，头 landing 1.8|2833.5 / 5100.3|
|两弹丸，各自无异常0.5、身体0.25、头部0.25，seed 1/3，landing 1/2，acc 0.5|总伤3.9375；弱点伤害矩3.125；平均层数1；有层概率0.75|
|Gas 已有9层，再来概率0/1/2层和混合落点|总伤14.125；弱点伤害矩6.75；平均层数9.5|

共享时钟控制：100发/秒、每发确定一层Gas、seed50，在含终点的2秒窗口只有 `50.5 + 500.5 + 500.5 = 1051.5`，不会每次追加都立刻再跳一次。

最终 release core 构建成功；开启 `WF_NATIVE_SHADOW=1`，下列现有文件合计 **335 passed，69.97秒**：`test_combat_replay.py`、`test_kpm_event_semantics.py`、`test_nonmelee_community.py`、`test_status_native_20261013.py`、`test_ranged_hit_audit_20261028.py`、`test_session_20261016.py`、`test_status_arcanes.py`、`test_enervate.py`。仅新增一个数学核心用例、删除一个重复参数化分支，收集用例数净增0；其余修改既有断言。

补充的内存核对覆盖混合头/身、暴击派生电、Enervate、无头部代理，三条native调用均无fallback/精确shadow差异。此检查没有生成新测试文件。

## 小规模性能结果

每次模拟10秒，单worker、native、无timeline；每组预热1次，3轮各50次取中位数。基线从 `f9db677` 的引擎源码独立编译，不用旧DLL冒充同版本。常规组12发/秒、3.3多重、65%异常、40%头部；Gas压力组50发/秒、6.6多重。目标生命1e10、护甲300，刻意积累长队列，非真实配装或完整烘焙基准。

|场景|旧实现/次|新实现/次|变化|
|---|---:|---:|---:|
|electric|0.180 ms|0.257 ms|+42.7%|
|gas|0.278 ms|0.478 ms|+72.0%|
|gas-stress|0.798 ms|1.888 ms|+136.6%|
|direct-control|0.097 ms|0.097 ms|+0.5%|

两版各604次native调用、0 fallback。新实现保留条件状态，电/毒气比旧的独立平均模型更贵；纯直伤控制基本不变。已用固定Rust栈缓冲替代每cohort分配，并把同一属性视图的absence计算移到缓存producer。初版高压Gas约2.23ms，收尾约1.89ms；这是同机小样本优化观察，不能外推烘焙总时长。

数值变化属于规则修正：此压力设置下旧Gas每次施加立即跳伤会明显高估，本次与旧版伤害不应相等。没有证明全量烘焙更快，也没有运行全量烘焙。原始记录：`.local/delivery/electric-gas-implementation-20261112/performance-final.json`。

## 精度边界和后续事项

这些不是已完成游戏验证的泛化结论：

1. 采用一条“首次可能施加”期望时钟，不枚举随机首次成功的所有时相。条件矩在这条时钟下求解；实际随机时间线仍有近似。
2. 到达层数沿用引擎的 absence + 相邻整数分布，不是所有天然/强制/暴击派生触发的完整联合分布。弱点击杀沿用伤害份额与既有分支反馈近似，不把伤害份额声称为精确的随机生命穿零概率。
3. Gas 使用累计更新到达量的 FIFO rank。统一持续时间下适用；后生短层先过期等混合寿命场景仍是既有近似，不能称为任意寿命精确队列。
4. 最新层先过期后，保留 latest landing 直到新的成功施加，遵循当前上游实现；M100 没有独立实测证明此边界。
5. 多形态混合组的击杀/派生事件来源仍取“有正概率存活的最老 cohort”这一单来源约定。任意多来源竞争、群体邻居伤害、旧 Syndicate 固定脚本派生路径与武器组的混合归属未在本轮泛化。
6. seed 保留现有施加时属性快照；tick-time 重读所有变化中的元素/派系增益未在本轮迁移。固定落点稳态评分仍用平均活跃层数近似 occupancy；精细时序由事件评分承担。

运行结果 `limitations` 已标注共享期望时钟、相邻整数到达、最新层过期、多来源归属与混合duration rank边界。后续优先在不扩大测试矩阵的前提下完善状态算法；缺乏游戏证据的部分单独等待实测。

## 缓存、构建和分发

`damage.py`、`combat_replay.py`、`proc_probability.py`、native桥接均属于 `_analysis_inputs_fingerprint()`。本轮源代码变化自动使旧预烘焙 statics 失效，无需仅为失效而增加缓存格式版本。共享评分规则影响候选搜索，不能只按最终武器元素筛选缓存复用。

实测新分析输入指纹为 `7d2d9ea104a8e826`；现存本地缓存指纹 `7aa6c97127eb8a75`，版本均为26，读取器接受条目为0。当前工作树不存在 `data/riven-analysis-statics.json` bundled缓存。

本地构建命令：`CARGO_BUILD_JOBS=4 python tools/build_native.py`（PowerShell通过 `$env:CARGO_BUILD_JOBS='4'` 设置）。`.pyd` 是忽略的构建产物，不提交到源代码远端。后续Bot移植和打包时必须带新core，并在冻结规则后统一生成新缓存；旧缓存没有被改指纹冒充新缓存。
