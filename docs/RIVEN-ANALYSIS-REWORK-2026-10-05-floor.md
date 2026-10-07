# 固定武器靶：120 级下限

`healthScale` 取 `max(120 级血量 / 170 级血量, 无紫卡基线 3 s 击杀的倍率)`；
120 级下限 = 0.8403（护甲在 100 级已封顶 2700，下限只作用于血量）。
`targetCalibration` 记录 `minimumLevel` 与 `healthScaleFloor`。

用旧静态缓存中 882 个武器/模式的无紫卡基线配装（Expert 旧路径按英文名映射到现目录），
在下限靶上（无超宏、身体命中、无赋能、30 s）重放：

|槽位|<1 击杀|1–3|3–10|≥10|
|---|---:|---:|---:|---:|
|主武器|169|95|45|4|
|副武器|169|46|16|7|
|近战|86|78|97|14|
|空战武器|1|9|16|0|
|同伴武器|22|2|0|0|

非近战中位数 0.72 击杀 / 30 s。打不死的不是个别武器而是一半目录：2700 护甲（90% 减伤）、
无削甲、身体命中下，120 级等效有效血量约 1060 万。排名用的连续指标（窗口伤害 / 击杀 +
当前目标进度）仍可区分，但这些武器的击杀触发类 MOD/赋能永远不触发。

若对基线击杀时间设上限（再软化血量）：10 s 上限时 489/577 个非近战模式被软化，其
等效血量等级中位 38；30 s 上限时 339/577，中位 52（护甲仍为 2700）。

证据：`docs/evidence/fixed-target-floor-20261005/baseline-kills-at-level120-floor.json`。

## 50% / 100% 弱点命中复核

### 旧缓存基线不可用于判断

旧缓存基线是在带超宏的旧靶上按身体命中选的：磁力向、几乎不削甲、没有 Acuity 类卡。
在下限靶上同样 882 个基线（非近战中位 kills/30 s）：0% 0.71，50% 1.93，100% 3.0。
改为在下限靶上、按各自弱点率**重新优化**基线（20 把热门武器抽样，
`headshot-sweep/reoptimized-baselines-floor.json`）：

|弱点率|击杀/30 s 中位|TTK 范围|每杀发数范围|
|---|---:|---|---|
|0%|1.29|6–60 s|11–925|
|50%|5.3|2.4–14 s|4–202|
|100%|7.7|1.4–10 s|2–119|

例：Amprex 0.61 / 5.5 / 9.3，Vectis Prime 3.0 / 11.9 / 20.0（100% 时每杀 2 发），
Rubico Prime 2.4 / 8.7 / 17.7（每杀 3 发），Basmu 0.39 / 2.0 / 4.0。弱点率 ≥50% 时
基线普遍换上 Acuity，击杀数是旧基线的 2–6 倍。

### 词条价值在三种失真区间里不可信

单词条价值 = 基线 + 该词条（3 正面满值）后 KPM 的相对增益（`stat-values-by-policy.json`、
`kills-per-window-sensitivity.json`）：

1. **窗口内击杀太少（≲3）**：新目标从零层异常开始，最后一个目标的进度与“刚好多杀一个”
   的悬崖主导结果。例：Amprex 在“恰好 1 杀/30 s”的软化靶上多重 +12%，同一靶硬度下
   拉长窗口为 +33%。30 s 窗口加 30 s 击杀上限正落在悬崖上，**不可取**。
2. **每杀发数太少（≲5–8）**：期望值引擎下“几枪必杀”是严格阶梯，同一基线上暴击、
   伤害、元素、W、Y 的增益完全相同或全为 0。例：Vectis Prime 50% 弱点时所有伤害类
   词条一律 +18%（5 杀窗口）或 +8%（10 杀窗口）；Laetum 50% 全部 0。WFSim 等级扫描
   显示同类武器 KPM 也有台阶但更平滑（暴击随机性）。这是弱点率 50/100% 下
   W/Y 估值的主要风险，与 W/Y 本身的结算无关。
3. **TTK 太短（发射率 / 装填受限）**：Torid 在 3 s TTK、50% 弱点下所有伤害词条 +0，
   只有射速 / 装填有价值。

两种失真都不存在时，W/Y 的排序是稳定的：例 Rubico Prime 100% 弱点 W +45/+47/+48、
Y +32/+33/+39（三种靶）；Burston Prime 100% W +51/+58/+56。Amprex（连续光束）
在 1–40 杀窗口下全部词条变化 <1 个百分点。

### 弱点结算对照 WFSim

同一配装、120 级、0/25/50/75/100% 弱点（`wfsim-headshot-rate-check.json`）：
Amprex 0.66/6.44/10.68/14.21/16.85 对 WFSim 0.65/6.28/10.60/14.00/16.76；
Trumna Prime、Rubico Prime 在 ±8% 内。Vectis Prime、Laetum、Fulmin Prime 偏高
1.7–7 倍。这是灵化进化口径不同（本地自动套用灵化，WFSim 请求未带进化），不是弱点
结算问题。

### 结论：硬度需要按武器、按弱点率同时满足三条

- 血量 ≥ 120 级（已实现）；
- 基线每杀至少 E 次伤害事件（避免阶梯），否则加硬；
- 窗口至少 K 杀：窗口 = clamp(K × 基线 TTK, 30 s, W_max)；TTK 超过 W_max / K 时才
  软化血量。

K = 5 时 1–40 杀窗口的数据已稳定（Trumna、Rubico、Lex、Kompressa）。
按旧扫描估算窗口成本（相对 30 s，非近战）：K = 5、W_max = 240 s 时，
0% 弱点平均 ×5.6（280/601 需软化），50% ×3.9，100% ×3.2。W_max = 1000 s 时 0% 平均 ×12.7。
回放耗时与窗口近似线性（Amprex 30/240/1000 s：23/198/826 ms）。

## 10–30 s 窗口评估（更正上一节“需要长窗口”的结论）

### 单词条价值（20 把 × 0/50/100% 弱点，参照 = 120 级硬度、每杀 ≥20 发、约 40 杀窗口）

|方案|单次回放耗时（30 s = 1）|排序相关 0/50/100%|前三一致|平均误差 pp|100%/0% 血量比|
|---|---:|---|---:|---:|---:|
|120 级 + 30 s（现行）|1|0.99/0.97/0.93|84%|3.9|1.0|
|120 级 + 20 s|0.81|0.98/0.95/0.92|87%|5.1|1.0|
|120 级 + 10 s|0.61|0.97/0.96/0.90|82%|7.0|1.0|
|软化至 10 s 内 5 杀|0.47|0.84/0.80/0.89|68%|15.3|16.7|
|软化至 30 s 内 5 杀|0.95|0.96/0.96/0.94|81%|6.2|13.5|

硬度固定时窗口长短影响很小；误差主要来自为保证击杀而软化血量，软化还使同一武器
0% 与 100% 弱点的靶子相差 13–17 倍。现行 120 级 + 30 s 已接近长窗口参照，不需要 240 s。

### 完整标准档分析（串行，`window-sweep/full-analysis-timing.json`）

|用例|30 s|20 s|10 s|
|---|---:|---:|---:|
|Amprex 0%|148.8 s|×0.86|×0.73|
|Burston Prime 0%|174.4 s|×0.87|×0.61|
|Burston Prime 100%|134.5 s|×0.85|×0.70|
|Kompressa Prime 50%|76.4 s|×0.96|×0.89|
|Vectis Prime 100%|72.3 s|×0.94|×0.91|

注意：分析请求的 `windowSeconds` 在 `app.py` 默认靶中写死为 30 s，与
`_BENCHMARK_WINDOW_SECONDS` 无关。

连续伤害武器（Amprex、Burston）10 s 下贡献与推荐基本不变；爆发 / 单发武器不稳定：
Vectis Prime 100% 弱点 10 s 时弱点伤害 +51 → +3、暴击率 +51 → +2；Kompressa Prime
20 s 时实际增益 41.9 → 4.0。总耗时只省 9–39%：窗口外的搜索与准备开销占大头。

结论：10–30 s 没有实质收益，保持 30 s。单发武器的台阶问题与窗口无关，需要按每杀
事件数加硬，或在引擎里按暴击方差平滑击杀时刻。

## 击杀反馈分支数（Bot 反哺计划）

Portable 中只有 Galvanized Scope / Crosshairs、Biotic Rounds、Combo Killer 触发分支，
且仅在弱点率 0–100% 之间、击杀是否为弱点击杀不确定时启用。20 把基线换入 Galvanized
后在 25/50/75% 弱点下与 64 分支对比（57 组触发分支，`kill-branches/branch-count-accuracy.json`）：

|分支|单次回放 ms|相对 16|KPM 误差均/最大|单词条价值误差均/最大 pp|最低排序相关|
|---|---:|---:|---|---|---:|
|16|438|1.00|0.06/0.39%|0.08/0.91|0.99|
|8|244|0.56|0.13/0.70%|0.16/2.84|0.96|
|4|145|0.33|0.25/1.89%|0.31/4.51|0.94|
|2|97|0.22|0.42/4.48%|0.49/5.89|0.96|
|不分支|49|0.11|0.30/1.98%|0.54/10.19|0.93|

4 分支可接受。Portable 自己的 9 次快速分析（50% 弱点）没有一次触发分支，分支数对
Portable 耗时几乎无影响；Bot 原型按面板指标选中 Galvanized 卡，最终回放才频繁分支。

## 元素合成顺序（已修复）

对照 Bot 原型的 12 张卡发现：同一组 MOD，搜索评估器与手动回放给出的分数可差 6 倍。
原因是元素按槽位先后两两合成，优化器的配卡有序，但束搜索按贪心顺序追加、爬山只有
换/加/减卡，永远不调整元素卡顺序；冰 + 毒 + 火 被固定成“爆炸 + 毒”而不是“病毒 + 火”。
Imperator Vandal 一组：搜索 3.14、手动 18.48、WFSim 18.26。

修复：`_evaluate` 在 MOD 出现 ≥3 种基础元素时，按每种不同两两配对各评估一次（元素卡
只在自身槽位间置换，至多 3 种），取最优并返回该顺序。修复后同一配卡两条路径一致；
Imperator Vandal 三张卡的配卡 8.5→36.0、17.3→26.0、6.7→30.6 KPM。代价：含 ≥3 元素的
候选评估次数至多 ×3，Imperator 一例快速分析 147→255 s，其余持平或更快。

Bot 原型的“强制病毒 / 腐蚀种子”本质上绕开了这个缺陷；Portable 快速档在 Torid、Dual
Toxocyst 上仍选 Acuity 系配卡、低于 Bot 种子配卡（本地 KPM），Rubico 上则高于 Bot
（16.3 对 12.2）——面板近似选卡并不更好，多元素种子 + 回放校验更好。
本地对 Torid / Dual Toxocyst / Rubico 相对 WFSim 偏高约 2 倍（前两把为灵化进化口径，
Rubico 待查），这组对比按 WFSim 结论不一致，需带进化重测。

## 分档与搜索改动（2026-10-05）

- 新档位 `ultra`（超快）：与快速档共用武器静态缓存，只读不写；配装搜索 = 面板近似
  （statusSustainedDps，束 4 / 候选 24）下的开放 / 病毒 / 腐蚀三个起点，结果用 KPM 回放
  复核取最好；推荐与负面词条只读缓存，缺失时留空并标注
  `ultra-profile-recommendation-not-cached` / `ultra-profile-negative-ranking-not-cached`；
  血量倍率偏离 >2 倍时不重搜基线。
- 快速 / 标准 / 深度：主搜索之外加病毒、腐蚀两个起点（面板近似，回放复核），只增加
  候选不会变差。
- 击杀反馈分支：快速 / 超快 4 条（经上下文 `killBranches` 传入回放，多进程安全），
  标准 / 深度仍 16 条。
- 负面词条排序随推荐一起缓存（同一正面词条数），同武器第二张卡起不再重算。
- 修复：倍率在 0.5–2 倍之间时基线分数仍是未缩放靶上的分数，而实际配装在缩放靶上评估，
  KPM 口径的实际增益被系统性放大（120 级下限时约 19%）。现在基线总在最终靶上重评。
- `ANALYSIS_STATICS_CACHE_VERSION` 15 → 16。

### 分档实测（Bot 原型的 5 把 × 3 张卡，50% 弱点，串行，`tiers/`）

|武器|超快 冷|快速 冷（首卡）|快速 已缓存|超快 已缓存|下限靶 KPM（旧 Portable 快速 / Bot 原型 / 现在）|
|---|---|---|---|---|---|
|Torid|3.7–7.6 s|76.7 s|10.3–12.6 s|2.2–5.8 s|7.9 / 14.5 / 16.1（卡 1）|
|Rubico Prime|2.7–4.0 s|59.3 s|9.5–10.8 s|1.5–2.9 s|16.3 / 12.2 / 22.4|
|Dual Toxocyst|8.7–11.9 s|177.5 s|13.7–16.9 s|5.3–7.9 s|20.1 / 28.0 / 28.0|
|Verglas Prime|5.0–9.1 s|120.1 s|11.2–16.1 s|3.4–7.5 s|— / — / 20.9|
|Imperator Vandal|8.0–17.4 s|193.3 s|15.4–23.8 s|5.8–15.0 s|8.5 / — / 42.2|

超快与快速选出的当前卡配装在 15 张卡上相同（KPM 一致），已缓存时推荐与负面词条也一致。
超快冷启动的增益不可信：基线来自面板近似（Dual Toxocyst 169.7% 对快速档 91.9%），
读到快速档缓存后与快速档一致。

## 靶子强度：从“选一个血量”到“对血量积分”（方案；落地见下一节）

任何单一血量 H 都会放大某一类机制：软靶放大射速 / 弹药 / “几枪必杀”台阶，硬靶放大
异常叠层 / 削甲 / 病毒；击杀太少又出现“刚好多杀一个”的悬崖。按武器校准 H 只是在挑
一个偏差，而且 0% 与 100% 弱点会落到不同的 H 上。

### 1. 单条命伤害曲线 + 更新过程（让所有 H 一次算完）

目标死亡前，目标侧状态（异常层数、削甲、已受伤害）与它的总血量无关。因此对一个打不
死的目标回放一次，得到累计伤害 D(t)，任意 H 的击杀时间就是 TTK(H) = D⁻¹(H)。

- 每条命的周期 = TTK(H) + 击杀后下一次命中的等待；武器侧（弹匣、装填、增益）在命与命
  之间延续，对起始相位取平均。
- 击杀反馈（镀层叠层、击杀回弹）：不动点迭代，增益层数 ↔ 击杀率，2–3 次收敛。
- 方差平滑：用每次命中的暴击档 / 触发次数方差（`crit_cv2` 已有），
  P(t 时已死) = Φ((D(t) − H) / σ(t))，期望击杀时间对 H 连续，消除“几枪必杀”台阶，
  与 WFSim 蒙特卡洛同口径。
- 叠层与削甲饱和后 D(t) 近似线性，可直接外推，不需要长窗口。

可行性探测（`headshot-sweep/one-life-damage-curve-probe.json`）：只用 0.25 s 粗网格、
不含等待与相位时，120 级及更硬的靶上预测与真实多击杀回放相差 5–25%，单次回放
40–150 ms；软靶严重高估（Vectis 1/64 血量预测 918 杀，实际 51），正是缺少的等待项。

### 2. 评价指标改为对硬度分布积分

Score = ∫ w(H)·KPM(H) dH，w 取对数均匀区间。区间两种取法：
- 绝对：如钢铁之路 50–200 级血量。所有武器、所有弱点率同一个分布，可跨武器比较。
- 相对（无量纲）：以无紫卡基线“每杀命中次数”N 为坐标，N ∈ [5, 200] 对数均匀。单发
  狙击与光束同一尺度，天然避开台阶区和极硬区。

有了第 1 点，积分几乎免费。过渡实现：搜索用中心点，最终配装、逐词条贡献、推荐排序
用 3 个高斯节点的现有回放（成本只在这几步 ×3）。

### 3. 把硬度变成展示维度

逐词条贡献按“软 / 中 / 硬”三段给出；推荐按整个硬度带的最小最大遗憾（minimax
regret）选组合。纯触发（冰淞）在硬目标占优、直伤在软目标占优，两者同时可见，而不是
被单一 H 裁决。

## 硬度积分靶（已实现，`hardness-integrated-v1`）

- 硬度坐标：本次分析的无紫卡基线在**身体命中**下的击杀时间 T。T 在 [1, 20] s 上对数
  均匀，三点高斯—勒让德积分：1.4 / 4.5 / 14.3 s，权重 5/18、8/18、5/18。
  起初试过“每杀命中数”（5–200 发），但光束一跳也算一发：Amprex 中心节点约 2.6 s、
  Vectis 约 25 s，硬度差一个数量级；异常叠层与削甲按时间计，改为时间坐标。
- T → 血量：对“打不死”的同一目标回放一次（`search_combat.body_ttk_health`；回放的
  `life_curve` 记录每次伤害），T 秒内造成的累计伤害就是该节点血量。目标死亡前的状态
  与其总血量无关，所以这是定义而非近似。
- 评分：三个节点各跑一次原有的 30 s 多击杀回放，KPM 取加权几何平均（`_score` 读到
  `hardnessNodes` 时自动积分）。几何平均下窗口 DPS 与 KPM 排序等价。
- 搜索（束搜索、元素起点、推荐排序、负面排序、流派基础配装的元素选择）只用中心节点；
  最终配装、紫卡底线候选、逐词条贡献、头条 KPM 用三节点。节点随武器缓存
  （`statics["hardnessNodes"]`）；首次中心节点与初始靶差 >2 倍时在中心节点重搜基线并重算。
- 身体命中计时：同一武器各弱点率的基线相同时，节点完全相同（Torid 0/50/100% 实测一致）。
- 取代：每武器 3 s 击杀倍率与 120 级下限。`ANALYSIS_STATICS_CACHE_VERSION` 16 → 17。

### 击杀时刻平滑：血量展布（替代逐次击杀的时间修正）

先实现过“逐次击杀把期望击杀时刻的偏移累加进更新过程”（KPM × W/(W+Σ偏移)）。它消除了
平坦段，却破坏了单调性：60 组伤害词条扫描中 26–31 组出现“加伤害 KPM 下降 >1 pp”，
最坏 −36 pp（`leftover-fixes-20261006/quadrature-renewal-shift-rejected.json`）。根因是
确定性路径与换弹周期锁相：致命一击在“换弹前的燃烧跳动 / 换弹后的跳动 / 光束直击”之间
切换时，偏移补偿不齐；即使改用“下一条命首次直击时刻”的偏移（换弹前击杀不再前移下一
条命）、逐事件累计方差，也仍有残余。该方案已撤回。

现方案：伤害噪声等价于目标血量噪声（伤害 + 噪声 ≥ 血量 ⇔ 伤害 ≥ 血量 − 噪声）。每个硬度
节点记录基线在该节点击杀时刻累计伤害的相对标准差 σ（`healthSpread`，上限 0.5），评分在
血量 ×(1 ± σ) 两点取平均（两点高斯—埃尔米特）。单调阶梯的平均仍单调；σ 来自基线、按武器
固定，所有紫卡面对同一血量分布。

验证（60 组，参照 = 9 点积分 + 展布，`leftover-fixes-20261006/quadrature-health-spread.json`）：

|方案|平均误差 pp|p90|排序相关中位|前三一致|下降 >1 pp 的扫描|最大单步占比中位|
|---|---:|---:|---:|---:|---:|---:|
|单靶|8.91|19.8|0.78|66%|1|0.27|
|三点积分，无展布|—|—|—|—|1|0.47|
|**三点积分 + 展布**|**3.68**|**7.5**|**0.96**|**82%**|**1（−1.0 pp）**|**0.35**|

两点展布只部分抹平台阶（更多采样点可进一步平滑，成本按点数增加，留作标准档可选项）。
`KillAttribution.crossing` 的逐事件累计方差与换弹感知外推保留，仅用于弱点击杀归因；
旧 `weak()` 回溯错位一格的 bug 已修。

单条命曲线直接替代多击杀回放（全部硬度一次算完）的“精确版”未采用：事件级原型在硬靶
上误差 5–20%，软靶与连射 / 爆发 / 持续伤害云武器偏差可到 2 倍（Burston 1/64 血量预测
1022 杀、实际 474；`hardness-integration/one-life-estimator-vs-multikill.json`）。该曲线只用
来把 T 换算成血量，KPM 仍由多击杀回放给出。

### 成本

三节点只用于最终评分：底线候选先在中心节点比较、只给胜出者算三节点；已定序的配装在
重评 / 消融 / 读缓存时不再枚举元素配对（`_evaluate(reorder_elements=False)`）。串行实测
（`tiers-hardness/`，bot 原型卡，50% 弱点）：

|武器|超快 已缓存|快速 已缓存|快速 冷启动|
|---|---|---|---|
|Torid|2.2–5.9 s（积分前 2.2–5.8）|10.4–13.3 s（10.3–12.6）|72 s（77）|
|Imperator Vandal|6.2–16.0 s（5.8–15.0）|16.3–24.7 s（15.4–23.8）|187 s（193）|

测试：794 项通过（排除早已存在的 `test_one_magnetic_break_per_pool_and_target_generation`
1.99 ≠ 2 失败）。


## 遗留问题修复（2026-10-06）

### 与 WFSim 的差距逐个查清

|武器|结论|
|---|---|
|Rubico Prime|狙击枪按“始终开镜”评估（狙击连击 / 开镜加成，设计如此）；WFSim 开镜时比值 1.00–1.14|
|Fulmin Prime|对照时本地模式 0 = 半自动、WFSim base = 全自动；同模式后剩电池差异，见下|
|Vectis Prime|带上本地灵化路线作为 WFSim 进化后 1.01 / 0.94|
|Torid|**本地 bug，已修**：灵化“+N 基础伤害”与弹池多重 +60% 被加到毒云部件（40 → 71 每跳）。WFSim 只加在主攻击。修后裸枪与逐卡 0.95–1.01，换进化全部 1.00|
|Dual Toxocyst|50% / 100% 弱点 0.99–1.06；0% 时 WFSim 仍套用“狂乱”毒素（与其 frenzy.yaml 的“仅爆头触发”矛盾），Fevered Frenzy 施放技能叠层 WFSim 默认叠满|

对照工具 `tools/validate_hunter_munitions.reference_evolutions`：WFSim 图标去掉 `Incarnon`
前缀、同图标按效果数值区分。Laetum 图标命名体系不同，无法映射，未对照。

### 电池武器（`tools/import_battery_profiles.py` → `data/mechanics/battery-profiles.json`）

电池武器打空后等待 BatteryRegenDelayFromEmpty 再按 BatteryRegenRate 回充，导出的
ReloadTime 不描述它（Fulmin Prime 导出 3 s，原生 0.7 + 80/40 = 2.7 s）。原生字段没有可靠
的“电池武器”标记（Arch-gun、弓、Kitgun 也带回充字段但正常换弹），名单取 pinned WFSim 的 13
把；数值逐字段取原生，原生缺失时用 WFSim 并标来源。电池按武器（所有非灵化模式）生效，
不再挂在单个模式的伤害总量上。旧的 Tenet Cycron 硬编码被导入数据取代（同值）。

以 WFSim 电池参数运行本地：11 把中 10 把射击数一致、8 把 KPM ±6%；Tenet Cycron / Plinx
射击数一致，差在伤害（赋灵元素）；Coda Bubonico 为 WFSim“部分回充”语义差异（已知）。
WFSim 的 Fulmin Prime 抄了普通版 30/s、1 s。Basmu 原生带回充参数但不在 WFSim 名单，未纳入。

### 超快档

- 冷启动增益：基线为近似时，“当前卡去掉紫卡再补一张卡”的反向底线若更强则用于增益
  （仅超快且无缓存基线时；缓存基线按武器固定，同武器各卡共用）。Dual Toxocyst 冷启动增益
  169.7% → 83.4%（= 快速档）。
- 所有档位都跑开放 / 病毒 / 腐蚀三个起点，快速档不会低于超快档（Torid 第二张卡曾 10.21 < 11.93）。
- 紫卡底线候选与反向底线不再枚举元素顺序（沿用基线 / 当前卡已定顺序）。Imperator Vandal
  超快已缓存 13.6–34.7 s → 8.1–12.5 s；Torid 2.3–5.2 s。Imperator 单次回放约 0.13 s 且
  4 元素，3 s 目标仍未达到。

`ANALYSIS_STATICS_CACHE_VERSION` 17 → 18（节点带 `healthSpread`）。

## WFSim 差距第二轮（2026-10-06）

对照脚本与输出：`docs/evidence/wfsim-gaps-20261006/`（`scripts/` 内为对照脚本，170 级钢铁 Thrax、
0% 弱点、30 s；带灵化的武器把本地实际路线映射成 WFSim 进化一并发送）。

### 本地真实问题（已修）

|问题|修正|代表结果（本地 / WFSim）|
|---|---|---|
|原生默认弹匣|包里只在与默认不同时才写 AmmoClipSize（Tenet Detron / Vulkar 的 6 是覆盖父级 5 / 4），缺失即引擎默认 6；本地按 0（永不换弹）|Javlok +108% → +3%，Marelok、Vasto(Prime)、Fusilai、Cantare 均 ±3%|
|逐发装填|原生 AmmoTakenPerReload = 1 的状态行为：起始 + 每发 × 弹匣 + 结束（`tools/import_shell_reload_profiles.py`，8 把）|Strun 0.5 + 0.5×6 + 0.25 = 3.75 s，射击 / 换弹次数全部与 WFSim 一致|
|多弹丸触发加成|触发词条作用于每次射击的触发几率，再按固有弹丸数均分（Strun 进化 ADD_BASE 1.32 经 GetProcChancePerPellet ÷ 12 显示 +11%）；本地加到每弹丸|Strun 家族 +26–92% → ±2%|
|火焰异常|“任一触发刷新全部层”在期望值模型下被小数触发永久续命；改为按“最后一次真实触发时刻”分世界的精确期望（`HeatChains`，与穷举一致）|39 组火焰对照（其余代码相同，仅换火焰模型）中位误差 4.6% → 1.9%（`heat-chains.txt`）；Tenet Plinx 裸枪 +19% → −2%|
|毒气层数上限|10 层上限下每层寿命是随机的；按“新到达层数”的分布计算存活概率（`capped_stack_add`，与穷举一致），必中时退化为原截断|Tenet Cycron 毒素赋灵裸枪 +10% → +6%|
|IsInfinite 条件|原生 IsInfinite = 1 的增益持续到条件重置，UpgradeDuration 不是寿命；且换弹时清零“无持续时间的换弹增益”会把刚触发的增益立刻抹掉（`tools/import_infinite_conditions.py`）|Boar −28% → −2%，Lato 家族 −30% → −4%，Zylok 改善|
|Torid 毒云|上一轮把弹池多重 +60% 一并从毒云去掉；WFSim 明确“随生成的榴弹进入毒云”|见下|
|Basmu|原生带 BATTERY 标记与回充参数，2 + 21/42 = 2.5 s（= wiki 完整装填）；电池对所有模式生效|+14% → ±2%（两种模式）|
|Lex / Lex Prime|ApplyUpgradesByDefault = 1 的条件块即常驻（Prime +20）；Lex +80 无条件标签，按常驻|Lex −35% → +4%，Lex Prime −9% → +1%（击破开关关闭对照）|

### 灵化“自身护盾 / 超宏击破”开关

Lex 2-1：基础 +80（Prime +20）常驻；“护盾击破后 8 秒再 +80”需要战甲配合。新增战斗状态
`selfShieldBreakForced`（默认开启 = 强制生效），关闭后按“自身护盾 / 超宏击破”时间轴触发；
配装页战斗状态面板新增复选框（默认勾选，取消时才发送 false）。同一开关覆盖 Gorgon 家族、
Atomos、Ceramic Dagger、Cestra。Lex 的 +80 原生挂在“自身护盾受伤”条件下但无条件标签，
游戏显示为普通基础伤害，按常驻计算。WFSim 把击破效果列为范围外，对照脚本与参考测试一律
关闭该开关（Gorgon 关闭后 0.0121 / 0.012）。

### 口径差异（未改）

- Torid Plentiful Mayhem + 多重：毒云带 +60% 后本地直击 + 毒云 46094 / WFSim 46058；剩余差在毒素
  DoT——WFSim 不把 +60% 计入异常伤害，去掉后两边 1.00–1.01。wiki 写明该加成与 Serration 类基础伤害
  相乘，本地保留计入 DoT（本地高约 13%）。
- Tenet Cycron / Plinx 的 +31–40% 是对照请求缺赋灵元素；补上后配装 −0.4% 至 +5.6%。
- Zylok：WFSim 声明双动扳机未建模并用 wiki 射速 1.8，本地用原生 1.5（射击 40 / 47）。
- Coda Bubonico：原生与 wiki 一致——打空后回充延迟缩短为 0.1 s，空弹匣回满 0.1 + 36/9 = 4.1 s；WFSim
  的停火时间为每次 5.5 s（= 1.5 + 36/9，即打空也按 1.5 s 部分延迟），与其数据注释矛盾。本地正确。

### 进化映射与新对照

对照工具的进化映射（`tools/validate_hunter_munitions.reference_evolutions`）：图标命名不一致时改用
游戏中文名对 WFSim `i18n/zh/evolutions.yaml`（Laetum 图标为 “Evolution…” 体系）；同时修正了
“按效果数值区分同图标进化”时条件效果数值被运算符优先级吞掉的错误。Laetum 首次可对照：
裸枪 −0.0%、配装 +0.6%；Felarx +0.7% / +0.3%（验证了多弹丸触发加成按 4 弹丸均分）；Sybaris
Prime +2.2% / +0.8%。

灵化形态爆炸部件的“+N 基础伤害”口径：WFSim 只有在充能满后才进入灵化形态，因此用 100% 弱点的
循环模式对照（本地 `incarnonCycle`）。Strun、Latron、Vectis Prime、Braton、Burston、Gorgon 两个 2 级
选项全部 −6.5% 至 +0.3%（`incarnon-cycle-radial.txt`），爆炸部件吃基础伤害加成与 WFSim 一致。

### 仍开放

Zarr / Kuva Zarr 子母弹（已标 `cluster-submunitions-unmodeled`，−57% 至 −91%）；Stug 堆胶生命周期
（+113%）；Tenet Cycron 毒气剩余 +6%（每层平均跳数本地 2.84、WFSim 推算 2.35，来源不明）；其他
有上限的异常（病毒、腐蚀等）仍用 min(期望层数, 上限)，接近饱和时略高估。

### 速度

- 火焰护甲剥除改为按“层的斜坡 / 衰减台阶”事件增量维护：触发与到期都不改变当前剥除值（被击中的
  熄灭世界带着当前衰减值转为重启，到期的存活世界带着当前斜坡值转为熄灭），只在台阶处变化；
  与直接求和逐点一致（随机含整点对齐 18000 次，误差 1e-15；`test_incremental_heat_strip_equals_direct_sum`）。
  Torid 单次回放 0.120 → 0.065 s。
- 超快档：元素起点与紫卡底线候选先把紫卡放末位比较，只给胜出者枚举紫卡位置；逐词条贡献在中心
  硬度节点上比较（`ultra-profile-contributions-center-node`，与三节点积分差 0.5–3 个百分点、排序不变）；
  无紫卡基线的三节点评分在进程内按精确输入缓存。

|武器|超快 已缓存|超快 冷启动|
|---|---|---|
|Torid|1.8–3.9 s（本轮前 3.6–9.8）|6.8–12.1 s|
|Imperator Vandal|4.4–5.9 s（本轮前 8.0–10.3）|8.4–9.2 s|

（`tiers-*.txt`，同机测得，机器负载有波动；Imperator 单次回放约 0.1 s × 约 50 次，3 s 目标仍未达到。）

`ANALYSIS_STATICS_CACHE_VERSION` 18 → 19。测试：821 项通过（排除早已存在的
`test_one_magnetic_break_per_pool_and_target_generation`）。

注：上面被排除的 `test_one_magnetic_break_per_pool_and_target_generation` 在第三轮已改为符合语义的
断言并恢复（见下）。

## WFSim 差距第三轮（2026-10-07）

对照脚本与输出：`docs/evidence/wfsim-gaps-20261007/`（`cappedsweep` / `burstsweep` / `radialsweep` /
`clustersweep` / `hitscansweep` / `chargesweep` / `embedsweep` / `opticorsweep`，
170 级钢铁 Thrax、0% 弱点、30 s；WFSim score 标准误普遍 ≤ 1%）。

### 本地真实问题（已修）

|问题|修正|代表结果（本地 / WFSim）|
|---|---|---|
|有上限异常的非线性|病毒 / 磁力“首层 ×2、之后每层 +25%”，腐蚀“首层 26%、之后每层 6%”；把期望层数代入这些折线会因 Jensen 不等式高估。替换成“替换最旧层”池的精确分布：窗口内到达层数 N 的 min(N, 上限) 分布用双栈队列维护截断卷积（`CappedPool`，与穷举一致），期望 = 1 + 0.75·P(N≥1) + 0.25·E[min(N,10)]|按层数直接对照的武器全部 ±1%（中位 0.31%，`cappedsweep.txt`）|
|腐蚀的护甲减伤|减伤 0.9·√(A/2700) 对腐蚀剥除是凸的；按层数分布逐层求护甲倍率的期望，不再代入期望剥除|Rubico Prime 腐蚀 −8.6%（只修层数时）→ −3.7%|
|点射|原生 `WeaponBurstStateBehavior`（NumShots / BurstDelay / IgnoreFireRate / BurstRemainingClip）以前只在 4 把手工审计武器上生效；新增 `tools/import_burst_profiles.py` → `data/mechanics/burst-profiles.json`（45 把，按导出模式记录的原生行为位置匹配，零跳过），每个开火模式各用各的；灵化形态是独立模式（Sybaris 本体 2 连 / 灵化 4 连，Burston 灵化全自动无点射），旧逻辑会把本体点射套到灵化形态上，已拆为 `baseBurst` / `incarnonBurst`|Hind −35% → −0.3%，Quartakk −70% → −0.1%，Cyanex 清空弹匣副模式 −0.4%，Kuva Quartakk +1.0%；点射对照中位 0.39%（`burstsweep.txt`）|
|子母弹|原生 `NumClusterProjectiles` + `ClusterProjectiles` 子弹体，每枚各有直击（AttackData）与爆炸（ExplosiveAttack）、各自的暴击与触发；`tools/import_cluster_submunitions.py` 与 WFSim `attack.cluster` 的数量、伤害三方一致才写入 `clusters`（4 把，零跳过），回放作为额外的纯范围部件，每发弹壳 × 数量，不吃多重（与弹壳爆炸同口径）。WFSim 未建模项只有“子母弹不吃 Condition Overload”（另两项无视掩体 / 自身硬直与单靶无关）；本地按 wiki CO 目录行（WFSim 引用的 `cluster_bomblet_co`：Adding，每 +100% 的加成量取弹壳伤害 25 / 50 / 200）给子母弹直击加 CO，基数比 = 加成量 ÷ 自身伤害；子母弹爆炸没有目录行，不加|Zarr −0.2% / +0.1%（含火焰、毒素、Serration+双元素配装均 ±2%），Kulstar −50% → −4.8% / −11.8%，Kuva Zarr / Kuva Bramma 见口径差异（`clustersweep.txt`）|
|蓄力时间|锁定的导出早于“读大写 ChargeTime”的抽取修正，所有蓄力模式 `chargeTime` 为空，只有手工审计的 55 个模式会蓄力；`tools/import_charge_profiles.py` → `data/mechanics/charge-profiles.json`（71 个模式，与 55 个审计值零差异），按原生行为位置匹配；`ChargeModifier` 决定射速 MOD 是否缩短蓄力（WEAPON_CHARGE_RATE 的 Phantasma、Corvas 等不随射速，原先只对 Arch-Gun 写死）|Ferrox +52% → +0.7% / +1.6%，Tenet Ferrox +119% → +4.1% / +2.1%，EFV-5 Jupiter +212% → +12%，Vadarya Prime +190% → −2.3%，射击数与 WFSim 一致（`chargesweep.txt`）|
|即时命中武器的爆炸|即时命中模式没有抛射体，爆炸在武器行为 `impact:RadialOnMissImpactBehavior.RadialDamage`（基础值 × 类型占比、自身暴击 / 触发 / 半径 / 衰减）；导入器回退读取它|Trumna −43% → +3.3% / +1.5%，Trumna Prime +3.6% / +1.8%（`hitscansweep.txt`）|
|蓄力倍率与爆炸|Opticor 满蓄 ×2（导出 `chargeDamageMultiplier`）；导入器拿未乘倍率的直伤匹配参考而跳过；运行时爆炸部件复制模式，同样 ×2，比对时把参考除以倍率|Opticor +6.0% / +1.5%（Vandal 对照 0.0%，`opticorsweep.txt`）|
|嵌入式持续场|原生 `Embed = 1` 的抛射体带 `EmbedAttack`（每跳伤害、强制触发）与 `EmbedTime`，按 Torid 的持续场回放；`tools/import_embed_fields.py`：伤害、类型、时长、半径、强制触发取原生，原生没有跳动间隔，取参考的每秒一跳|Pox、Coda Pox、Mutalist Cernos 由“毒云缺失”变为有（与 WFSim 的差见口径差异，`embedsweep.txt`）|
|原生爆炸部件|`tools/import_projectile_components.py` 扩展：原生 `UseNewFormat = 1` 按 DT_* 分类型写数值（以前判为“类型缺失”）；WFSim 副模式文件（`inherits`）取父武器路径；同直伤总量的多个模式按副开火 / 扳机 / 抛射体是否带爆炸部件区分。新增 23 项|Kuva Tonkor −2.1% / +2.5%，Kuva Chakkhurr +1.5% / −0.5%，Afentis Prime −0.5%，Helstrum −88% → +3.6%，Kuva Zarr −57%~−91% → −9.1% / −3.0%，Corinth / Javlok / Tenet Tetra / Sepulcrum 副模式 ±1.5%（`radialsweep.txt`）|

磁力破盾附带的电击按“当时磁力层存在的概率”加权，`test_one_magnetic_break_per_pool_and_target_generation`
的“电击次数 = 破盾次数”改为“略少于且不超过破盾次数”，测试恢复。

### 口径差异（未改）

- Bubonico / Coda Bubonico 副模式 +34% / +82%：WFSim 打空后仍按 1.5 s 部分回充延迟（原生空弹匣 0.1 s），
  射击数 45 对本地 60（上一轮已记录的同一问题）。
- Enkaus 副模式 −61%：原生 `ammoRequirement` 15，WFSim 写 1，30 s 内从不装填。
- Kohm −22%：WFSim 声明弹丸数逐发增加未建模（第一发就打满 12 发），本地按原生逐发增加。
- Acceltra −44%~−50%：本地按原生起爆距离，近距离火箭不爆；WFSim 自注“7 米内整段高估爆炸”。
- Kuva Hind / Kuva Kraken 点射间隔：WFSim 0.083 s（wiki），原生 0.07 / 0.03 s，本地用原生。
- 灵化武器（Soma、Braton、Lex、Strun、Zylok 等）不带进化无法直接对照；Kuva / Tenet / Coda 必须两边同带赋灵。
- Kuva Zarr / Kuva Bramma 带子母弹后 +37~39%（火焰赋灵）/ +13~15%（毒素赋灵）：WFSim 给弹壳直击与弹壳爆炸加赋灵，
  不给子母弹加；MOD 元素则照常加到子母弹上。已用 WFSim 逐发回放确认（`cluster-valence-replay.txt`，超宏护盾上
  无护甲，按来源 × 类型的每发增量）：Kuva Zarr 弹壳直击火焰 +30、弹壳爆炸恒 +404（= 673 × 60%），子母弹直击只有
  冲击、子母弹爆炸只有爆炸；Kuva Bramma 爆炸火焰恒 503（= 839 × 60%）。本地去掉子母弹赋灵后四组 +0.7%~+2.3%
  （`cluster-valence-experiment.txt`）。赋灵是按基础伤害比例的元素加成，本地对所有伤害部件一视同仁。
- Kulstar 子母弹暴击：原生子弹体 0.1 / 2.0，WFSim 用武器本体 0.17 / 2.3，本地取原生（暴击配装下差距放大到 −12%）。
- Javlok −32%：原生 `WeaponChargedStateBehavior`、扳机 Charge、蓄力 0.3 s；WFSim 写 `trigger: auto`（其注释自称
  “charged shot”），射击 50 对本地 35。上一轮 +3% 是两边都漏了蓄力。
- Prisma Lenz +33%：原生拉弓 0.8 s，WFSim 写 1.2 s（与 Lenz 相同），射击 17 对 22。
- Nataruk −32%：WFSim 用“完美释放”（拉弓 0.7 s）并自注普通满弦（1 s）未建模，本地按满弦。
- Lenz / Prisma Lenz 带 Split Chamber 时偏高：本地审计时已定“每个生成的抛射体一次爆炸”（爆炸吃多重），WFSim 不吃。
- Mutalist Cernos +22% / +18%：原生 `EmbedAttack.ForcedProcs = PT_POISONED`，每跳必附中毒；WFSim 的持续场没有
  强制触发字段，只按 0.49 几率（总触发 128 对本地 351；本地去掉强制中毒后 −0.7% / −1.9%）。
- Pox / Coda Pox +14% / +16~18%：原生 `EmbedTime` 5 s，WFSim 写 4 s（触发数 84 : 70 = 5 : 4）。
- WFSim 副开火要用父武器 id + `mode: alternate`，并以返回 `apl` 含 `alt_fire` 确认；带 MOD 时 WFSim 不走副开火，
  副模式只能比裸枪。

### 仍开放

- Scourge 投掷 +59%：原生 `LotusSpearGunStateBehavior`，`ReloadAfterEveryShot = 1`、reloadTime 2.5 s；WFSim
  按每次投掷后 0.6 s。本地未建模“每次投掷后装填”，两边的回手时间口径都缺可靠依据。
- Trumna 榴弹 +6~7%：射击数一致，差在火焰 DoT；WFSim 注明榴弹本应由主火力充能计量条解锁、此处按固定节奏发射，本地同样未建模计量条。
- 冰冻仍按期望层数截断（冻结是对层数的阈值，留待单独处理）。
- 其余原生带爆炸部件、但 WFSim 无对应参考或三方不一致的模式未导入：Aegrit、Alternox / Cortege 副模式（原生
  爆炸量与参考不唯一匹配）、Arbucep、Simulor 系、Grimoire、Tenet Plinx 蓄力、Scourge Prime 投掷，以及近战投掷、
  Castanas 类遥控雷。
- EFV-5 Jupiter 副模式 +12%（射击 20 对 18）。

### 给 WFSim 的反馈清单（均已与原生数据核对）

1. 子母弹不吃赋灵（Kuva Zarr、Kuva Bramma），MOD 元素却照常加；逐发证据见 `cluster-valence-replay.txt`。
2. 电池武器打空后仍用 1.5 s 部分回充延迟（Bubonico 系；原生 `BatteryRegenDelayFromEmpty` 0.1 s）。
3. Enkaus 副开火耗弹 1（原生 `ammoRequirement` 15）。
4. Javlok 主火力写成 auto（原生 Charge，`ChargeTime` 0.3 s）。
5. Prisma Lenz 拉弓 1.2 s（原生 0.8 s）。
6. Pox / Coda Pox 毒云 4 s（原生 `EmbedTime` 5 s）；持续场没有强制触发（Mutalist Cernos 原生每跳强制中毒）。
7. Kuva Hind / Kuva Kraken 点射间隔 0.083 s（原生 0.07 / 0.03 s）。
8. Kulstar 子母弹暴击用武器本体 0.17 / 2.3（原生子弹体 0.1 / 2.0）——这条也可能是原生字段不生效，需对方确认。

### 速度与缓存

新异常池每次到达 O(上限)、查询 O(上限²)（带版本缓存）；Soma Prime 腐蚀配装与 Kohm 单次手动模拟新旧模型
耗时相同（0.044–0.055 s / 0.015–0.016 s，噪声内）。`ANALYSIS_STATICS_CACHE_VERSION` 19 → 21（20 为本轮
前半，21 加入蓄力、即时命中爆炸、持续场、子母弹 CO）。
测试：见文末（含恢复的磁力破盾测试与新增的异常池穷举、点射、子母弹回放测试）。

测试：835 项全部通过（2026-10-07 最终一次全量 833 项 + 随后新增的 2 项蓄力 / 原生爆炸与持续场测试单独通过）。

## 遗留项第四轮：机制核实与静态分析（2026-10-07）

依据优先级：原生包数据 > 游戏本体静态分析（国服 `Warframe.x64.exe`，2026-09-25 构建，capstone 反汇编，
脚本在会话草稿区，证据见下）> wiki。Lua 脚本（如 `GooGun.lua`）运行时加载，缓存与本体中都没有正文。

### 已修

|项目|游戏设计（来源）|修正|结果|
|---|---|---|---|
|冰冻暴伤与范围伤害|wiki Cold：+0.1x 首层、+0.05x 每层、冻结 +1.0x，“不作用于范围伤害”（穿刺同理，本地已排除）|爆炸 / 持续场 / 胶团等 `radial_only` 部件不吃冰冻暴伤|—|
|完美蓄力|原生 `PerfectChargeRange` + `PerfectChargedProjectileType`（只有 Nataruk 0.7–1.0、Cinta 0.7–0.9）|`tools/import_charge_profiles.py` 解析完美弹体伤害；按未改装单位时间期望伤害判定是否划算（Nataruk 1274 对 900 → 启用；Cinta 定时释放是 600 火焰冲击波，436 对 655 → 不启用）；战斗状态 `perfectCharge` 默认开，配装页新增复选框|Nataruk −32% → −0.3%（对 WFSim 完美释放）|
|Stug 胶团|原生 `EmbedTime 1.5`（`MaxLife 8` 是飞行寿命）；wiki：每加一层刷新寿命，满 10 层或到期引爆；跳伤 4 × 层数（4–36），爆炸 75 × 层数（75–750）|`resetLifeOnStack` 改为真、寿命 1.5 s；刷新只移动引爆时刻，跳伤保持嵌入后每秒一次|+113% → +2.1% / +8.9%（WFSim 把跳伤简化为每发 4）|
|按击杀充能的副开火|原生 `AddChargeConditions: PRIMARY_KILL`、`NumChargesToConsume`、`ConsumesChargesForFire`；Trumna 副开火 `ModeSwitchTime 1`（72 个副开火行为里只有 Trumna 两把非 0）|`tools/import_kill_charged_alts.py`（Trumna / Trumna Prime / Sepulcrum / Mausolon / Morgha 每 5 杀 1 发，Higasa 每 15 杀 1 发）；选副模式时回放“主火力 → 计量满切换 → 副开火 → 切回”的循环，主火力弹匣保留|Trumna 榴弹不再无限连发|
|遥控雷|原生 `RemoteMineStateBehavior`（`DetonateManually`，Aegrit 最多 4 颗）；嵌入后的引爆取 `EmbedDeathAttack`（与 Talons 同口径，不与等值的 `ExplosiveAttack` 叠加）|导入器识别遥控雷；引爆时连同爆炸部件一起结算（投掷时不再提前结算爆炸）|Aegrit −3.0%；Alternox / Alternox Prime 副模式同时补上|
|矛枪投掷后装填|静态分析：`LotusSpearGunStateBehavior` 虚表（0x142361300）第 45 项在 `ReloadAfterEveryShot`（+0x1a4）为真时把武器切到状态 8、以武器虚函数 +0x2d0 的时长播放事件 0x79，与通用装填路径（0x1405ac670）完全相同 → 每次投掷后一次普通装填（武器装填时间，吃装填速度）|`tools/import_reload_after_shot.py`（Scourge 2.5 / Prime 2.2、Javlok 1.9、Ferrox / Tenet Ferrox / Afentis 1.8）；回放每次射击后弹匣清零，静态面板弹匣按 1|Scourge 投掷 30 s 9 次（原 30 次）|

### 静态分析确认的争议项

- **嵌入伤害（毒云）跳动**：嵌入处理函数（0x140d3e350）先以 `EmbedTime` 注册 `Projectile::EmbeddedDie`，再**立即**调用
  `DoEmbedDamage`（0x1408a33e0）并注册 1.0 s 的同名定时器；`DoEmbedDamage` 每次结算后再注册 1.0 s 后的自己。跳伤在
  0、1、2…秒，到期销毁先于同时刻的跳伤（销毁定时器最先注册）→ 跳数 = `EmbedTime`。Pox / Coda Pox 5 跳（原生 5 s），
  wiki 与 WFSim 的 4 s 不对；Torid 10 跳与 WFSim 一致。本地持续场本来就是从 0 开始每秒一跳、共 ⌈时长⌉ 跳，无需改动。
- **矛枪投掷装填**：见上表；wiki 的 0.6 s（Scourge、Javlok）、2.0 s（Ferrox）在原生与本体中都找不到依据。

### 仍未定

- Kulstar 子母弹暴击：原生子弹体自身写 0.1 / 2.0（Zarr 子弹体同样有自身暴击，且与 wiki 一致），wiki / WFSim 写 0.17 / 2.3
  （等于武器本体）。生成子弹体的逻辑在 `ClusterBombProjectile` 的虚函数里，本体去掉了 RTTI，未能定位；本地维持原生。
- 按击杀充能的副开火只在“选择副模式”时按循环回放；选主模式时仍只计主火力。

测试：840 项全部通过（2026-10-07 第四轮：全量 836 项 + 随后新增的 4 项单独通过）；`ANALYSIS_STATICS_CACHE_VERSION` 21 → 22。
