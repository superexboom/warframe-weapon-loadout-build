# Portable快速紫卡搜索与Bot集成

2026-11-12；源码基线 `f8ec277`。本次修正不改变固定病毒、50%弱点（同伴0%）、单体硬度节点与禁止Bot自动赋能求解的约定。

## 问题与实现

- deep静态表原先提供无紫卡基线与推荐排名；ultra用户卡仍只用beam4/shortlist24的面板代理挑选方案，缓存优秀构筑没有继续做真实事件搜索。
- 当前卡现在使用同缓存上下文的baseline、archetypeBases，以及可选reference.build中的最多4个去重MOD方案。所有方案用当前卡重新验容量、家族、必选/禁选、元素与紫卡插槽，旧KPM不当作当前卡分数。
- floor改为最高合法保留层枚举，完整考虑容量需要两删时的28组；不继续枚举所有更低子集。元素约束进入排列评分内部，并区分评估缓存身份；Cold/Heat配Toxin紫卡时，合法Viral/Heat槽位不会被非法Blast/Toxin高分排列遮蔽。
- warm screening最多64次evaluation，最多两个起点各64次真实中节点换卡/增删，总上限192次evaluation、每起点最多两轮、共享5秒phase；最终按原三节点再评分，保留已有合法actual作为下限。一次evaluation可尝试多个元素插槽，192不是底层回放总数。
- ultra明确35秒总预算/5秒phase；内部剩余预算只会缩短。Go仍45秒，启动worker后将剩余期限扣2秒传给Python，避免Python原先90秒默认预算迟于外层超时。最终有限评分/序列化仍需时间，不把预算说成硬实时保证。
- 完整响应缓存不再把每请求变化的剩余秒数当身份；budget-limited结果不写该LRU，以免短预算结果阻止下次继续搜索。
- freeAmmo-only构筑仅在真实空仓决策不确定时触发额外分支，不再因无关弱点击杀启动probe+16轨迹；真实弱点击杀消费者与后续draw顺序保留。

## 最小质量验证

使用机制优化后基线引擎离线生成Lato别名记录与Amprex的deep静态起点，然后同卡、同目标、同节点读取该上下文进行前后对照。原始记录及请求保存在`.local/delivery/bot-search-quality-20261112/`，未改发布缓存指纹。这里Lato命中目录身份为`/Lotus/Weapons/Tenno/Pistol/CoHLoanerPistol`，不是普通`.../Pistol/Pistol`；不可泛化同名全部变体。

|记录/词条|原KPM|新KPM|变化|原耗时|新耗时|
|---|---:|---:|---:|---:|---:|
|Lato D+1|210.098|229.600|+9.28%|0.254s|0.435s|
|Lato 6+S|157.854|164.985|+4.52%|0.285s|0.636s|
|Amprex 1+6|194.553|194.553|+0.00%|0.211s|0.449s|

这些是三个有限控制，不证明全局最优，也不是全武器平均。新用户卡搜索多做约135–137次evaluation，增加约0.18–0.35秒，在这组样本里换得两张卡4.5%/9.3%的KPM改善；第三张卡保持原方案。三例均未达到时间预算。最终61项搜索/预算/上下文测试通过；包括完整双删、跨槽有限搜索、元素约束、剩余预算和响应LRU。机制与搜索相关合计145项native shadow回归通过。没有新测试文件。最终三卡重跑KPM相同，本机耗时0.362/0.510/0.354秒。freeAmmo-only无空仓控制中native轨迹由17降为1，KPM均为300；不推广为所有武器提速17倍。

## Bot交付接口

Bot-owned worker在`tools/wfarsenal_bot/bot_riven.py`，通过`tools/sync_wfarsenal_component.ps1`生成包。reference格式升至2，候选保留`build.mods`有序路径与`build.rivenSlot`，缺失witness会视为待补烘焙；在线读同key的构筑，重新求当前卡分数。ultra预算字段`_searchBudgetSeconds`由Go传入，不进入战斗身份。

源代码与native核心必须一起迁移。Bot本轮已快进至远端main `cfd4ac4f`后集成，旧数据/代码指纹不能冒充新缓存。最终全量烘焙完成后检查实际每个目标的baseline、2/3正推荐、负面阈值、reference/witness和manifest；进度文件只用于追踪，不能替代内容验证。

## 已交付结果

- Portable计算源码：`1d59e621c6bb9649696d8a45cc4a76f5a779b31e`，已推送 `Preview/performance-delivery-20261025`。
- Bot代码、native组件与缓存：`a09149cf6087f183bf969ed906ea9a3266c3d284`，已推送远端 `main` 并核对提交。
- 98条灵化路线、658/658目标、2632份reference v2配装全部完整；输入指纹 `f5b24b11d0db51e3`，无目标计算失败。全程最多10个计算worker。
- 过程中在第390个目标提交后，Windows进度文件打开出现一次`OSError errno22`。父进程停止worker；随后核验390份完整缓存和98条路线，原输入续跑剩余268个，未重算已完成目标。进度记录少一项不作为缺缓存判据，最终按实际内容验证全覆盖。
- 约4小时40分包含路线、deep缓存、一次续跑及最终核验；并发与范围不同，不把它与此前16worker或不带新reference搜索的烘焙时长直接相比。
- Bot所有者Python检查40项通过；`go test -p 1 -buildvcs=false -count=1 -timeout 180s ./service/rarsenal ./domain/riven`通过。生成包92文件在工作区和Git暂存blob均逐项size/SHA256一致；路线文件已使用仓库约定LF字节。
- 抽样Amprex、Ignis Wraith、普通Lato的缓存MOD顺序/紫卡位置固定重放，KPM与记录逐位一致。
- 实际JSONL worker预热后，三张卡分别0.247/0.381/0.262秒，均静态命中、非完整响应命中、有效配装/伤害评分、未达到预算。worker首次导入与推荐请求合计3.687秒，单独列出，不混入热态计算。

交付cache SHA256：`d28dafc804aa933707030ba30c0782d7d55cfc277774e47ab59fdd70fec0a47f`。

交付manifest tree SHA256：`ad3385fea95611da2c43d2f09d613fe2fc5d4e2caf967623a70ed1bea07d6681`。

完整记录保存在`.local/delivery/bot-search-quality-20261112/`：`final-coverage.json`、`reference-replay.json`、`worker-canary.json`及两段烘焙日志。远端已交付，不代表这三个样本覆盖所有武器的搜索最优性或生产网络延迟。
