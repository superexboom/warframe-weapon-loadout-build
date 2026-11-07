# Portable 预烘焙缓存：机制、收益边界与 WFSim 分布式接入建议

> 面向 WFSim 维护者与分布式计算实现者。核对日期：2026-11-08（UTC+8）。
>
> 本文介绍 WF-Riven-Portable 已实现的缓存机制，并根据 WFSim 的当前公开源码提出适配建议。本文新增的跨任务预烘焙产物格式、持久评分缓存与接入扩展是建议方案，未核实其已在 WFSim 实现；已有能力在第6节单列。本文不表示已经测得 WFSim 的提速，也不把 Portable 的分数作为 WFSim 的正确性依据。

## 1. 先给结论

**可以把预烘焙产物分发给计算者，但应先明确产物是在省准备工作、省搜索，还是省已经完成的正式测量。三者不能共用一套信任和计费语义。**

对 WFSim，优先级建议如下：

1. **同一问题已有当前引擎认可的 fact：在服务端直接交付。** WFSim 已有这条能力，应先观测它的命中与遗漏，不再把同一问题分配给更多计算者“读取缓存后复核”。
2. **同武器、相近搜索反复出现：分发无权威分数的候选配装起点，以及能证明与战斗动态状态无关的只读准备数据。** 计算者仍用自己的当前引擎检查合法性、执行战斗和搜索。候选起点改变搜索轨迹，必须显式进入任务契约。
3. **重复候选评分很多：先在私人交互搜索或探索任务试验持久评分缓存。** 缓存键必须包含完整场景、随机流、run 范围与统计合同；正式验证、贡献结算须另行处理。不能先灌入同一份分数，再把多个客户端的转述算成独立见证。
4. **新场景、新模型、低重复率任务：通常不值得预烘焙数值结果。** 可以复用基础资源与无分数候选，仍需重新计算。先量实际重复工作，再决定烘焙哪些热点，避免把大空间全量烘一遍后几乎没人命中。

Portable 的实现最值得参考的是：**公共搜索提前做、身份完整匹配、候选缓存有界、分片独立写、统一验收发布、变化后保守失效。** 其 JSON 结构不适合直接接入 WFSim 的正式评分与见证链。

## 2. 本文依据和比较口径

| 对象 | 本文核对版本 | 证据范围 |
|---|---|---|
| WF-Riven-Portable | `d030e95b942ec84cbf2f0449d512752feed31111` | `app.py`、优化器、烘焙/打包/增量工具，以及仓库验收记录 |
| WFSim | `1db552fa9157817113029fa6bed9950caad1a431` | 2026-11-08 查询公开 Git `main` 所得；提交时间为 2026-11-07 23:15:04 UTC+8；核对下文列出的源码与项目文档 |
| WFSim 线上发布声明 | `engine=69219ccb033d`、`data=bb069d7aba3c`、`wasm=7d59d2968031`、`commit=edb6e613+` | 同日读取公开 `release.json`；只核对声明，未下载执行该代二进制，也未将它与Git main视为同一身份 |
| 一次实际成本记录 | Portable 引擎 `5b7901423511994e67538c01bb35b2cfcd4391c6` 的 Bot 固定预设 | 658 个目标、98 条路线、10 个计算 worker；这是 Bot 适配层使用 Portable 引擎的生产样本，不是 Portable UI 全档位烘焙数据 |

WFSim 部分是**公开源码快照审查**，没有读取其生产数据库，也没有对线上志愿者集群做性能采样。仓库 `main` 不自动等于每个在线客户端已运行的版本。实装时应绑定所发布的 engine/data/optimizer 合同，不能只引用本文日期。[W1–W9]

## 3. Portable 为什么需要预烘焙

用户紫卡不同，但大量计算共享同一组基础条件：武器与模式、目标与战斗窗口、倾向、容量、默认灵化/场景策略、搜索档位。重复计算这些条件下的无紫卡基线、推荐正面、负面影响，会让每张新卡都支付近似相同的深度搜索成本。

Portable 将一次分析拆成两部分：

```text
公共静态部分：基线配装、硬度节点、流派起点、2/3正面推荐、负面与致命阈值
实际卡相关部分：这张紫卡的数值、装配、贡献消融、必要复评

离线：冻结输入 → 计算公共部分 → 校验 → 随对应运行时分发
在线：匹配公共部分 → 重建所需候选 → 求解实际卡 → 返回结果
```

这里“静态”指**对同一完整上下文、不同实际卡请求可以复用**，不表示这些结果永远不变，也不表示战斗模拟本身没有动态状态。敌人、命中策略、条件增益、元素顺序或游戏机制变化，都可能改变它们。[P1–P3]

## 4. Portable 实际有哪些缓存

| 层 | 当前实现 | 保存什么 | 是否适合直接分发 |
|---|---|---|---|
| 持久分析 statics | `app.py`、`optimizer.py` | 基线卡组、硬度节点、候选起点、2/3正面推荐、负面/致命负面及阈值、评价上下文 | **可以**，但须匹配运行时和完整上下文 |
| 候选评估缓存 | `evaluation_cache.py` | 某个精确配装与场景的评分、属性值快照和卡片索引 | 当前是进程内 LRU；**没有现成跨机器分发协议** |
| 战斗重放缓存 | `search_combat.py` | 精确输入的重放结果；评分用简化结果与完整展示结果分开 | 当前是对象内/进程内缓存，不直接导出 |
| 完整请求缓存 | `app.py` 的 `_ANALYSIS_RESULTS` | 最近完全相同的分析请求响应 | 最近 32 个请求的内存 LRU，不是预烘焙库 |
| 原生核心与数据文件 | `native/wfcore`、冻结 exports/sidecars | 可执行算法与静态游戏数据 | 是运行依赖，**不是已经算出的配装答案** |

候选评估缓存最多 8,192 条，快照字节预算 16 MiB；共享重放 LRU 最多 4,096 项。候选快照不携带另一个调用的可变战斗状态，命中后重建本次对象。把 Python pickle、对象引用、Rust 指针或活跃 RNG 状态直接跨进程分发，不是本项目的缓存分发方式。[P4]

### 4.1 持久 statics 的内容和读取

当前优化器写入的公共内容包括：

- `baselineCards`：无紫卡基准配装的卡片键；
- `hardnessNodes`、`targetCalibration`、`evaluationTarget`、`contextHash`：评价靶与校准上下文；
- `archetypeBases`：可复用的搜索起点；
- `counts["2"]`、`counts["3"]`：分别保存推荐词条、分层、负面推荐、`fatal`、`fatalAbove`。

`_bakeStaticsOnly` 跳过触发用假想紫卡自己的配装、下限修正和逐词条贡献。真实用户卡仍有自己的计算；读取基线卡片键时也可能重建并评分。因此，命中 statics **不是**完整 HTTP 响应零计算返回。[P2]

Portable 当前不将启发式搜索结果称为“理论上限”，其核心紫卡输出保留相对基线增益与推荐。Bot 适配层额外维护评分参考卡与归一化分数，这属于调用方预设，不能把 Bot 字段说成所有 Portable 缓存都有。[P2、P7]

### 4.2 身份匹配比“文件存在”更重要

文件级校验包含：

```text
buildLabel + stances + inputs + cacheVersion
```

`inputs` 来自快照身份及明确列出的引擎源码、游戏数据、运行补丁内容；Python 文本统一换行。读取依赖失败时不回退为一个通用空指纹。每条上下文键还包含武器、组合部件/显赫强度、模式、先天元素、元素目标、搜索档位、倾向、容量、评分指标、校准版本及 benchmark。固定额外场景、近战上下文和固定灵化路线也进入对应键。[P1、P2]

显式赋能、时间线、必选/禁选 MOD、数量范围等请求，不能直接套用无约束公共缓存。调用方若固定一种额外场景或路线，必须明确允许缓存，并把它纳入身份。

**一个实际踩过的边界：** 同伴请求从“隐含默认”变成显式 `companion=true`、`companionPlayerStacks=false` 后，旧 Bot 一方面没申请缓存该场景，另一方面又拒绝读取含 `scenario` 的键，造成求解完成却没有可复用缓存。修复必须同时覆盖写入准入和读取匹配，而不是删除同伴身份来追求命中率。[P7]

### 4.3 分片烘焙、打包与增量

`tools/bake-analysis-statics.py` 将工作组织为武器 × 开火模式，选定的档位在同一 worker 内顺序计算。三正面后接两正面，共享基线与已热的进程内结果；worker 只写独立分片，父进程校验身份后合并。有效分片可在中断后续跑。[P3]

当前这是**本机多进程流程**，不是已经部署好的跨机器任务调度器。其分片设计可以演化为分布式，但还需任务认领、可信产物归属、跨机协议和发布验收。

`tools/stage_portable_cache.py` 在真正的打包 staging 运行时中计算身份，只有匹配且非空的缓存才进入包；`--require-cache` 可要求没有合格缓存就不继续。便携运行时先读匹配的包内缓存，再合并匹配的可写本地缓存，同 key 由本地项覆盖。[P1、P5]

`tools/incremental_bake.py` 的复用十分保守：

- 先保存验证过的缓存和依赖清单；
- 仅当共享依赖完全一致、该武器展开后的完整记录一致，才离线迁移其缓存；
- 引擎、MOD、敌人、赋能、组合部件或策略等共享变化，拒绝跨版本复用；
- 迁移完成仍要走正常烘焙校验，不以改写指纹冒充有效结果。[P6]

需要改进的边界也应公开：当前主 statics 指纹并未直接覆盖任意 `.pyd` 二进制和后端环境；增量归档的 inventory 才额外覆盖 `.pyd/.so` 等。WFSim 若做跨平台数值分发，应显式定义数值合同和经过验证的后端等价关系，不照抄这个缺口。Portable 的部分分片成功时也可能写入部分缓存并返回非零，发布方必须另验覆盖完整性。[P1、P3、P6]

## 5. 实际效果：哪些数字能说，哪些不能

### 5.1 一次完整生产样本

以下来自仓库中的 2026-11-03 验收记录：[P7]

| 项目 | 实测 |
|---|---:|
| 引擎 | Portable `5b79014`，经 Bot 固定预设调用 |
| 目标 | 658 个；普通武器与组合装配合计 |
| 灵化路线 | 98 条 |
| 计算并发 | 10 个 worker，内部串行；限制10个逻辑处理器 |
| 正式路线 + deep 缓存批次 | 12,245 秒，约3小时24分钟 |
| deep 阶段 | 11,600 秒；复用先前通过的3个预检目标 |
| 最终缓存上下文 | 658/658，缺项0 |
| 横痃重炮实际卡 warm 请求 | 约0.300秒，7张普通MOD、75次native重放、0回退 |
| 翠雀实际卡 warm 请求 | 约0.261秒，7张普通MOD、75次native重放、0回退 |
| GPU参与 | 没有 |

这是“离线公共工作成本”和“特定在线请求耗时”的记录，**不是**将3小时24分钟除以0.3秒得到提速倍率。两者任务量不同，且没有同质量、同工作量的冷热端到端 A/B。此样本也不能代表 WFSim 的 Monte Carlo 工作量或 Portable UI 全模式、多档位的总成本。

### 5.2 运行期缓存是另一项优化

候选评估缓存、精简重放键和 score-only 返回路径，会减少同一次或同一进程内重复构造与重放的成本；它们与持久 statics 命中是不同机制。评估时应分别开关并记录 CPU 时间、命中率和结果一致性，不能把多项代码改动的综合收益全算到“预烘焙”头上。[P4]

收益的基本来源是避免重复工作；缓存不会补全错误的武器机制，不会自动扩大搜索覆盖，也不会把局部最优变成全局最优。

## 6. WFSim 当前已经有什么

下表依据所列公开提交的实际实现。`worker/` 在 WFSim 中主要是服务端任务模块，浏览器执行战斗的 Web Worker 与它不是同一个层次。

| 当前能力 | 源码依据 | 对新方案的影响 |
|---|---|---|
| canonical question 与跨 producer 去重 | `task_contract.js::questionId` 对 verb + 规范请求哈希；`task_ledger.js` 复用已有 question/fact | 不必新建第二套“相同任务去重”服务 |
| 当前 engine 的 fact 交付 | 已有验证事实可直接满足新 demand；旧 engine 事实受现有重开/再验证规则约束 | 已确认结果应优先服务端复用，而非再派发给计算者转述 |
| 独立见证 | `independent()` 按 owner/network 去重；验证器据一致答案形成 fact | 共享来源的预评分不等于独立计算 |
| 配装 canonicalization、单次搜索去重 | `optimizer/src/search.rs`、`descent.rs` | 不应把通用“加个 HashMap”当成新贡献 |
| 请求内准备缓存 | `webapi/src/optimize.rs` 在请求内按 `(variant, arcane)` 保存 `Entrant`；候选仍 seat mods、生成 params | 可研究跨任务保留，但必须补全当前隐含的请求上下文 |
| quick fleet 共享缓存 | `webapi/src/optimize/quick.rs::Fleet` 保存 score、candidate、legality、rough、screened_runs、best_runs；`fresh` 清空上一搜索 | 已经复用单次页面搜索中的评分；跨任务持久缓存才是另一件事 |
| short→full 续算 | quick screen 首段 runs 随 shard 回传，full measurement 继续相同配对随机流 | 不能把同一段样本重复累计，也不能另造一套不兼容续算 |
| 只读战斗准备对象 | `PreparedSimulation` 保存 immutable params、seed；每个 run 独立 RNG 与战斗状态 | 是准备数据复用的切入点，但当前 Rust 对象不是可直接分发的稳定序列化格式 |
| simulation 分片及固定折叠合同 | `(seed,index)` 决定每个 run；Rust merge；随机状态使用无损线格式 | 评分缓存必须保留 run 范围、分组和序列化精度 |
| 同家族候选迁移 | `family_build` 把已有配置迁到同家族其他武器，重新快速搜索，之后走正式测量 | 不是从零开始做候选起点复用；宜扩展现有入口 |
| 按内容摘要发布资源与榜单增量 | `DISTRIBUTION.md` 的 release/assets/data 分层、manifest、每文件摘要 | 可借用分发基础设施，但新计算产物仍需自己的语义/信任分类 |

源码能确认上述机制，**不能据此宣称当前已将跨任务、完整上下文的持久评分库下发给所有志愿计算者**。另外，`scripts/build_cache.py` 的 `web/cache/` 主要保存图片、固定库和 OCR 模型等网站构建资源，不是配装求解结果缓存。[W1–W9]

## 7. 哪些场景值得分发预烘焙产物

| 工作负载 | 建议复用内容 | 必须重新计算/验证的部分 | 预期价值 |
|---|---|---|---|
| 同一 canonical question 已有认可 fact | 服务端已有 fact | 按现有模型纠错、独立复核和生命周期规则处理重测 | 直接避免派发；这一层WFSim已有 |
| 同一热门武器、少数固定 rulers、大量紫卡请求 | 无紫卡/常见流派的配装起点、合法候选结构、可证明稳定的准备数据 | 实际紫卡值、元素顺序、条件触发和最终评分 | 较适合，能避免每个请求从零准备或从单一起点开始 |
| 同一搜索在多设备接力/重载 | 完整身份匹配的轮次checkpoint或候选身份 | 新run、未完成轮次、最终复评；仍遵循原schedule | 适合续算，不能把checkpoint当全局最优证明 |
| 多个搜索重复访问相同候选、相同场景和随机流 | 精确评分/统计分片缓存，先限私人探索 | 正式见证与贡献语义另行处理 | 取决于命中率和重复模拟占比 |
| 志愿者各自领取完全不同配装、不同场景 | 通用数据pack、只读基础索引、进程内准备缓存 | 几乎全部战斗工作 | 数值预烘焙收益可能很小，下载反而占成本 |
| 新武器机制或大范围公式修正后 | 无分数配装身份，重新校验后可用作起点 | 受影响分数、条件效果、排序、删减结论 | 不能沿用旧分数避免重算；应合并修正再计算 |
| 新ruler、群体阵型、不同击杀窗口/命中策略 | 通用结构与多样化候选 | 全部依赖场景的评价 | Portable单体缓存不能覆盖WFSim群体测量 |
| 任意紫卡连续数值、任意buff和约束组合 | 局部精确缓存、结构化起点 | 新输入自身的效果与合法性 | 不应预烘焙整个连续参数空间 |

“同一配卡”不代表同一计算：紫卡值、MOD等级、形态循环、赋能、起始增益、弹药/装填、目标和阵型、爆头策略、时间窗、RNG、统计阶段任一不同，都可能改变结果。

## 8. 建议的最小接入路线

### 8.1 第一步：先观测已有 fact 和评分重复率

沿现有 `task_ledger` / `task_delivery` / `task_usage` 记录：

- 新 demand 中有多少直接命中当前可交付 fact；有多少本来就是新的问题；
- 任务中准备数据、生成候选、合法性检查、实际战斗、序列化各占多少 CPU；
- 同武器同场景重复的候选身份有多少，是否还同时拥有相同随机流与run范围；
- 同一worker、同一页面fleet、跨任务三种重复率分别是多少。

这些观测不应改变评分、任务身份或工作量结算。先回答“重复发生在哪一层”，再决定生产哪种包。

### 8.2 第二步：候选起点包（建议优先试点）

以武器家族、合法模式和少数热点 ruler 为分片。每个包保存少量**完整且多样的配装身份**：MOD与等级、元素相对顺序、赋能、灵化、部件、固定槽约束等。保留暴击、触发、元素和弹药等不同可行分支，不能只留榜首一套。

消费方式：

1. 验证包的版本与内容摘要，解析稳定 ID；
2. 使用 WFSim 自己的合法性入口检查当前武器和任务约束；显式锁定的槽位不能默默丢弃；
3. 用用户的实际紫卡和当前场景重新评分；同家族迁移按目标武器的规则转换数值；
4. 把通过的候选加入 `starts`，与原有默认/多样化起点合并去重；
5. 由现有 quick/descent/fleet 继续优化，最终候选仍走普通上榜与测量入口。[W2、W4]

**这是热启动，不是数值缓存命中。** 它既可能节省收敛时间，也可能因多了起点增加总工作；必须测同预算质量、达到同质量的时间两个指标。不能保证每个任务都更快。

对要求确定性报告的分布式任务，`starts` 及其排序、`seedPackDigest`、选择策略必须在派发前确定。所有 witness 看到同一请求；不能依据某台设备“恰好下载了哪个包”悄悄改变搜索。只有记录在请求中的起点，才能成为可复现的优化条件。

### 8.3 第三步：只读准备数据与本机长期缓存

先考虑**计算者本机跨任务保留**经过完整键约束的准备结果，再考虑中心序列化分发。这样可先测准备开销是否值得网络下载。

适合候选包括：解码后的不可变数据、稳定ID索引、按完整规则生成的候选池、明确不依赖当前战斗状态的结构。`Entrant`/`PreparedSimulation` 可作为依赖边界的参考，但不能直接导出 Rust 内存布局、引用或闭包。

如确需跨 WASM/native 分发，新增独立、版本化的只读 IR；加载后由当前引擎构建本地对象。**已解析配置**和**已经结算战斗条件后的伤害**必须分开。CO、镀层、过热、命中/击杀触发、目标状态、弹体时钟和队列属于战斗过程，不能为了“预热”冻结成常量。

准备工作是否落在 WFSim 的 gas 计量范围内，要沿实际调用链确认。不能因为调用点叫 `prepare` 就假定它完全不影响正式 `work`。

### 8.4 第四步：探索任务的持久评分/分片缓存

只有前两步仍留下大量精确重复评分，才增加跨任务数值缓存。先放在私人搜索、研究或非正式排名路径，保持正式测量关闭该优化，直到下节合同明确。

可利用 WFSim 已有 indexed runs、`Shard` 和 rough→full continuation，保存明确 run 区间的结果；不要只保存一个 `meanKpm`。需要续算时保留其统计矩、离散样本/中位代表所需信息和run索引，是否保留完整series取决于请求输出。只保存均值既不足以续算，也可能不能重建完整报告。[W3、W7]

WFSim 的 walk 用全局序号派生随机流，descent 使用配对流；缓存需使用实际生成的流身份。不得把“同一个用户seed”误当所有候选都用了相同完整随机序列。

## 9. 不可省略的正确性和信任合同

### 9.1 正式见证不能靠同一预评分自证

WFSim 当前按 owner/network 保证见证独立。若A、B都下载同一份未验证分数，再分别上传相同答案，网络身份虽不同，计算来源却相同。内容摘要只证明收到相同字节，不证明分数正确；两台机器都读了同一个错误缓存，也不会使错误变成事实。[W5]

最小可行策略：

- **已有认可fact：** 由服务端复用、交付，沿现有规则结算，不新增一轮“计算贡献”；
- **尚待见证的正式任务：** 可以复用基础准备，但正式需独立执行的战斗不能由共享未验证结果替代；
- **探索评分缓存：** 标记为辅助证据，不直接写榜单，不冒充 witness；
- **显式纠错/独立复核任务：** 按原 review/nonce/状态规则执行，不能拿普通缓存回答新一轮复核。

最终重新计算幸存配装，只能保证这些配装的分数正确；若早期错误缓存已经把更好的候选剪掉，最终复评不会自动恢复它。探索缓存若参与剪枝，必须额外验证候选覆盖和质量，不能只验证最终一个分数。

### 9.2 `work/gas` 不是可忽略的附属字段

当前 `simulate` 的 canonical answer 包含 `{score, metric, work}`，`optimize` 包含 `{build, score, work}`。同一 engine 的答案按完整 canonical 内容比较；`work` 还关联贡献结算。[W5]

因此存在两个不能直接选的捷径：

- cache hit 按少量读文件成本报告 `work`：可能与冷算的同engine witness不一致；
- cache hit 把缓存生产时的 `work` 重新当作本次计算上报：可能重复领取并未新执行的工作量。

建议先保持正式协议不变，仅复用不影响规定gas的准备部分。若以后允许正式数值复用，应显式区分**逻辑测量内容、缓存生产成本、实际新执行成本、复用交付**，由验证与计费所有者共同调整协议。不得只在执行器里“补回旧gas”绕过当前合同。

### 9.3 模型、场景与随机统计的完整身份

下面是**建议的概念键，不是现有WFSim API字段**：

```text
Kscore = H(
  simulationContract, dataDependencies, numericContract,
  canonicalBuild, canonicalFight, triggerPolicy,
  rngAlgorithm, derivedSeed, runStart, runCount,
  aggregationContract, outputKind
)

Ksearch = H(
  Kscore的固定场景部分, optimizerContract,
  candidatePool, requiredAndForbidden, slotAndCapacityRules,
  startsAndOrder, searchStrategy, budgetSemantics,
  roundSchedule, candidateRuns, finalists, tieBreakPolicy
)
```

补充要求：

- 保留元素顺序、MOD等级、紫卡值、模式、灵化/赋能、部件、战甲/同伴策略；规范化只折叠**已经证明等价**的表示。
- 字节SHA256用于验证文件；语义合同用于判断数值是否可复用，两者不是同一回事。当前WFSim question ID是verb+规范请求，engine在生命周期中另外管理，不能误写成它已经哈希进question ID。
- 旧静态依赖未完整建图前，先以完整语义代次保守失效；不要使用修改时间或仅武器名判定。
- Rust/native/WASM可在已证明数值合同等价时复用；部署包字节不同不必然代表算法不同。反过来，平台相同也不证明任意新二进制等价。
- 随机种子和run范围必须无损传输，64位值不能任由JavaScript Number舍入；继承当前RunKey/序列化约定。
- run区间必须不重叠；10次rough与前10次相同的100次full不能当成110次独立样本。
- 浮点加法分组会影响末位。现有WFSim已区分不同分组的容差与同一分组的逐位一致，正式复用应遵守相同fold顺序和分组合同。[W3]
- 估计值、少量run结果、完整统计结果、启发式搜索结果必须分别标记。不能将“可续算片段”标为“已完成最终答案”。

### 9.4 缓存命中也影响搜索预算

WFSim 当前搜索以候选数量、状态推进和确定性计算为重要边界，不能简单因cache hit将“eval次数”清零，让热缓存机器比冷缓存机器走得更远却仍声明同一个任务答案。

若缓存只是执行优化，逻辑候选顺序、budget扣减、tie-break、round schedule应与冷算一致。若目标是让同样墙钟预算探索更多空间，应明确这是**另一种搜索策略/预算合同**，用相同的新合同让所有执行者复现，而不是伪装成不改变答案的加速。

## 10. 分发格式与发布流程建议

优先复用 WFSim 已有内容寻址和不可变发布机制，不让每个worker扫描一个巨型共享JSON，也不把Python pickle放到不受信任的下载路径。

建议一个索引加按武器/场景拆分的小产物：

```json
{
  "format": "wfsim-prebake-proposal-v1",
  "kind": "candidate-starts",
  "simulationContract": "<审定的模型代次>",
  "dataDigest": "<语义依赖摘要>",
  "optimizerContract": "<搜索代次>",
  "scopeDigest": "<武器、场景及约束摘要>",
  "contentSha256": "<产物字节摘要>",
  "verification": {"role": "hint-only", "mayAnswerWitness": false},
  "coverage": {"expected": 32, "complete": 32},
  "objects": [{"weapon": "<stable-id>", "digest": "<sha256>", "bytes": 12345}]
}
```

示例数值只是格式示意，不是已生成的WFSim包。`contentSha256` 指独立payload的原始字节摘要；manifest自身摘要由外部入口索引记录，不在自身字段中做自引用哈希。`candidate-starts`、`prepared-ir`、`exact-run-shard`应分别有明确schema；不要只用一个模糊的“cached”布尔值代表全部语义。

发布过程：

1. 选取热点和目标任务合同，冻结源码、数据及搜索策略；
2. 各生产worker写自己的不可变对象，以计算键去重；不并发覆盖同一个主JSON；
3. 聚合端验完整性、上下文、数值、覆盖与可信角色；未验证的数值不能标为fact；
4. 先上传对象与不可变manifest，最后原子更新其入口索引；失败不能把未落齐的一代标为完整；
5. 消费者按任务所需分片拉取，校验摘要和合同，保留本地有界只读缓存；miss或版本不符走正常计算；
6. 任务执行期间固定该代输入，不在半次搜索里无声明地换包；
7. 与新引擎无关的显示更新可复用已有语义产物，但须有明确合同依据，不以文件名猜测。

WFSim当前榜单属于单独可更新的数据平面，已能按文件摘要增量获取；release属于签名代码平面。候选提示包可采用明确标记的数据产物；能影响正式计算的准备IR/测量片段需要可信manifest和语义版本绑定。不要把小时级变化的排行榜候选直接烘死到每个引擎二进制中。[W8]

## 11. 何时真的省时间：一个可计算的判断式

对某一类任务，令：

- `N`：一个语义版本寿命内的请求数量；
- `M`：实际需要首次下载的计算者数量；
- `P`：中央预计算总成本；
- `D`：每位计算者的下载、校验、解码成本；
- `R`：每请求可被复用部分的成本；
- `U`：每请求不可复用的计算；
- `h`：精确命中率；
- `H`：每请求的查询/载入额外成本。

在一致成本单位下：

```text
不烘焙： N × (U + R)
预烘焙： P + M × D + N × [U + (1 - h) × R + H]
值得做： N × (h × R - H) > P + M × D
```

这是成本决策式，不是排队延迟模型；CPU秒、网络传输、电费、墙钟时间不能不加权地相加。评估用户体验时另测下载延迟、单任务P50/P95、首次启动与排队时间；评估总算力时统计**生产+复用+复核**的总CPU秒或统一资源成本。

缓存能减少的比例受可复用部分限制。若90%成本本来就是每个不同任务必做的独立Monte Carlo，准备部分即使免费也不能获得十倍加速。反之，很多新紫卡请求重复相同武器的基线与候选搜索，公共搜索缓存可能明显降低在线延迟。

不建议在缺少实测前给WFSim承诺固定节省百分比，也不能用Portable的单体、少节点计算与WFSim的多目标、不同run数量直接比较优劣。

## 12. 最小试点和验收

不新增大规模“防御测试矩阵”。先在现有回归上补核心断言，再用一个有限工作负载做性能对照：

| 试点 | 有效对照 | 必须验收 |
|---|---|---|
| 无分数起点包 | 相同请求集；冷起点与候选包起点分别运行 | 当前合法性；同预算质量/候选多样性；达到相同质量的时间；不把历史分数当当前分数 |
| 准备数据跨任务复用 | 相同任务与RNG，关闭/开启复用 | 正式结果与规定work合同不变；准备时间下降；内存有界 |
| 探索评分分片复用 | 同seed、同run区间、同fold的冷算/续算 | 分数及统计状态匹配，无run重叠；缓存不会污染独立复核；未验证数据不错误剪枝 |

覆盖普通直击、范围/持续伤害、条件叠层、灵化循环、同伴等真实不同路径即可；不为所有组合机械展开用例。只读统计也应复用已有task/usage/进度链，不另建一套难维护的监控系统。

应报告：缓存命中率、重复候选数、准备/战斗CPU秒、总下载字节、首次与后续延迟、失效重算率、同预算解质量、正式见证一致性、实际新算工作与复用量。没有这些数据时，只能说“机制可行”，不能说“已节省多少电或多少总算力”。

## 13. 建议给 WFSim 的实施顺序

- **先查重用机会：** 把已有fact命中、单次fleet命中、跨任务重复分开计数；确认是否有真正重复的昂贵工作。
- **先做候选和准备复用：** 沿已有`family_build`、`starts`、`PreparedSimulation`、quick fleet边界扩展，保留当前引擎评分和独立见证。
- **再做受控数值缓存：** 仅当收益值得，先限探索路径；完整定义版本、run/fold、work与信任协议后再讨论正式路径。
- **按依赖增量：** 初版保守全版本失效；建立可信依赖图后再按武器/场景复用。显示层更新不应无谓重算，真实机制更新也不能漏掉受影响结果。
- **统一发布验收：** 批量合并数值修正，冻结后烘焙一次；合法产物可恢复续跑，已完整产物不重复算。缺覆盖和版本错配都应在分发前发现。

最终目标应是：**把真正重复的计算从每个参与者那里拿掉，让新增算力投入新的候选和需要独立证明的测量；缓存的来源、精度与用途始终可辨认。**

## 参考源码与记录

源码引用均指向固定提交，便于讨论时复核。线上声明来自[公开 release.json](https://wfsim.app/release.json)，该地址会随发布更新，上表仅记录本次读取结果。本文为方案说明，不复制原项目长段正文。

### Portable

- [P1] [`app.py`：指纹、加载、写入及请求LRU](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/app.py)。关键符号：`_analysis_inputs_fingerprint`、`_load_analysis_statics_cache`、`_persist_analysis_statics_cache`、`_ANALYSIS_RESULTS`。
- [P2] [`optimizer.py`：静态内容、上下文键与实际求解](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/vendor/wfarsenal/optimizer.py)。关键符号：`_statics_cache_key`、`_default_analysis_scenario`、`analyze_riven_request`；`baselineCards`、`archetypeBases`、`counts`、`statics_only`。
- [P3] [`bake-analysis-statics.py`：本机分片烘焙](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/tools/bake-analysis-statics.py)。
- [P4] [`evaluation_cache.py`](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/vendor/wfarsenal/evaluation_cache.py)、[`search_combat.py`](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/vendor/wfarsenal/search_combat.py)、[`search_session.py`](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/vendor/wfarsenal/search_session.py)。
- [P5] [`stage_portable_cache.py`：真实发布运行时的身份匹配](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/tools/stage_portable_cache.py)。
- [P6] [`incremental_bake.py`：保守增量迁移](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/tools/incremental_bake.py)。
- [P7] [`VALIDATION.json`：Bot固定预设生产样本](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/docs/bot-delivery-20261103/VALIDATION.json)、[`PLAN.md`：验收范围](https://github.com/superexboom/warframe-weapon-loadout-build/blob/d030e95b942ec84cbf2f0449d512752feed31111/docs/bot-delivery-20261103/PLAN.md)。Bot额外评分字段仅用于说明适配差异。

### WFSim

- [W1] [`docs/COMPUTE_TASKS.md`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/docs/COMPUTE_TASKS.md)：任务所有权、需求去重、交付与完整inventory。
- [W2] [`docs/OPTIMIZER.md`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/docs/OPTIMIZER.md)、[`optimizer/src/descent.rs`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/optimizer/src/descent.rs)、[`optimizer/src/search.rs`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/optimizer/src/search.rs)：搜索、缓存、配对随机流和shard划分。
- [W3] [`docs/WASM.md`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/docs/WASM.md)：checkpoint、Gas、quick fleet与simulation分片的数值合同。
- [W4] [`docs/BOARD.md`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/docs/BOARD.md)：Family candidates、fact factory和正式复核边界。
- [W5] [`worker/task_contract.js`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/worker/task_contract.js)、[`worker/task_ledger.js`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/worker/task_ledger.js)、[`worker/task_verification.js`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/worker/task_verification.js)、[`worker/factory.js`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/worker/factory.js)：实际question身份、独立性、canon和work。
- [W6] [`webapi/src/optimize.rs`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/webapi/src/optimize.rs)、[`webapi/src/optimize/quick.rs`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/webapi/src/optimize/quick.rs)：请求内Entrant和单次fleet缓存，不等于跨任务持久缓存。
- [W7] [`webapi/src/simulate.rs`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/webapi/src/simulate.rs)：`PreparedSimulation`及indexed runs。
- [W8] [`docs/DISTRIBUTION.md`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/docs/DISTRIBUTION.md)：release/assets/data平面和按文件摘要分发。
- [W9] [`scripts/build_cache.py`](https://github.com/magenie33/wfsim/blob/1db552fa9157817113029fa6bed9950caad1a431/scripts/build_cache.py)：网站构建资源缓存，不是配装评分库。
