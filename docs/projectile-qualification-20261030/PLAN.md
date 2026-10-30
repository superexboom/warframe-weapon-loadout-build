# 弹头分类、MOD 与赋能资格调查计划

起点：2026-10-30，Portable `ed2319c`；既有引擎输入 `13546df7351f47ab`。本记录追踪新增调查与落地，不覆盖历史报告。

## 执行约束

- 不用“伤害声明名含 Explosive / EmbedDeath”直接判定径向；几何范围、原生 HitType、弱点倍率、CO、命中／暴击／状态／击杀事件分别找消费者证据。
- 明确精确武器路径、模式、弹体、实际激活路径。声明不等于有效伤害，多个声明可能互斥。
- 能由当前游戏资源、Luau、原生消费者证明的先修；空间覆盖／实机操作留边界，不把仍能静态追踪的问题统称需要实测。
- root 独立做计算链与分类审查；子代理并行做原生事件、更多弹头族、测试精简。
- 一个修复通常 1 个例，功能通常不超过 3 个展开用例；优先现有测试补断言。删除重复／失效／逐字段拒绝矩阵，不为单项新增测试文件或一次性验收脚本。研究优先复用现有查询／反汇编工具。
- 不增加未经需要的通用防御框架。先修具体真实路径，再判断是否需要共用抽象。
- 本轮继续源码调查修复；未完成模型校准前不启动烘焙／Bot 迁移／发行构建。

## 工作项

| ID | 任务 | 负责人 | 状态 | 完成标准 |
|---|---|---|---|---|
| Q1 | 逐段审查 `radial_only`、`area_direct`、普通/延迟命中事件在 Python/Rust 和主、副伤害构建的使用 | root | 本批完成；独立资格位已落地 | 找到实际混淆点；最小修复或证明无误；不扩大未知资格 |
| Q2 | 比较 Stug、Zakti/Kompressa、普通 Bolto 接触/到期包的原生 HitType 与赋能通知 | packet_native_routes | 完成普通通知与Puncture/Cold门 | 给出 producer→packet→victim→event 链；有证据的族扩展才接入 |
| Q3 | 扩展 Cluster/Guided、持续毒场、多弹头/替代包等族的来源与当前映射清单 | projectile_families | 本批80资源/7子弹对照完成 | 至少覆盖有不同原生路径的代表；每项标已证明、静态待查或需场景 |
| Q4 | 精简上轮机械式参数矩阵、重复 engine/API 对照与内部字段校验 | test_slimming | 完成205→29，11→7文件 | 保留实际回归，给出前后展开用例/文件数量、删改理由和最小验证 |
| Q5 | 整合可证明修复，检查正常配置/缓存身份/旧 native 回退 | root | 完成100例限定验证+20场景选定模式对照 | Python/Rust 同语义；现有测试中最少回归验证；只跑受影响检查 |
| Q6 | 更新本计划、机制结论及测试范围，核实远端并推送 Portable | root | 完成；随本批源码提交推送 | 清楚区分本轮已完成与未闭合项；提交范围与验证一致 |

## 当前发现与决策

- 初查 `damage.py` 的主伤害 `radial_only` 仍由四种 source 名称推导，需核对后续按武器/组件的覆盖是否完整。
- `manual_combat.py` 为普通副组件统一设置 `radial_only=True`；Stug 在另一条 stackable 专用路径显式变为 area-direct。需要核对其他特殊包是否被漏在通用路径外。
- 以上是代码调查线索，不是已证实游戏机制错误；不先全局放宽所有爆炸的弱点/赋能资格。

## 记录规则

每个已落地项记录：原行为、原始来源/consumer、实际修改、保留边界、复用/修改的测试、结果。原始大转储放 `.local/delivery/projectile-qualification-20261030/`，仓库 MD 只记录能复核的事实与精简证据；不靠海量“通过数”替代结论。

## 本轮已落地记录

1. **Trumna／Prime 副射击**：保存资源 impact.IgnoreHeadshotBonus=1，冻结导出遗漏；同步为 damage.impactIgnoreHeadshotBonus=true。沿用已有独立伤害倍率门，未改成radial或关闭头部事件。复用test_projectile_headshot_rule.py，增加1个真实配装来源回归。
2. **Pox mode1**：原生WeaponMeleeRadius fire/state，既有extract规则已能标注auxiliary-melee；只补冻结导出，排除远程求解候选。现有inventory用例改用真实导出记录，无新增用例。
3. **四个即时副包**：Larkspur／Prime1600、Acceltra已武装44、ScourgePrime55，经actual victim delivery→AGC允许普通命中/暴击；在旧producer registry中添加精确来源和0秒触发，Python两处分支共用已有radial_hit逻辑，Rust即时分支打开同一通知。旧native能力版本1退回Python，当前版本2；不授予头部、CO或Enervate特殊分组。复用原事件测试文件，新增3个展开契约，同时删除旧数值笛卡尔/内部字段校验。
4. **范围与HitType清单**：root独立扫描264个导出引用弹体、433个正值伤害声明，找到3条范围字段明确标PROJECTILE：Phantasma／Prime主73与Nox玩家原型30。不是所有ExplosiveAttack都为RADIAL。分类consumer与Puncture/Cold资格继续单独追，避免一个标签顺带打开所有乘区。
5. **其余族**：4族普通集束子弹的contact2/radial4及SCRIPT5覆盖门已保留原生合同；当前身体命中近似和未验证modifier/event已公开。Pox/CodaPox/Torid场、Trumna弹跳与Sepulcrum锁定发射补明确缺口，未虚构多次命中。

阶段验证：现有相关集合77 passed（4.78s），含native/Python SHADOW、真实Arcane消费者、未武装不触发与原目标死亡条件；未启动全量重测或烘焙。

6. **Phantasma／Prime73特殊主爆炸**：native event+1bf为PROJECTILE2；victim1408ea3d0的mask0x0e允许其接受Puncture/Cold暴击易伤，独立于head suppression25c。普通weapon来源谓词两个原字节控制已通过。新增独立radial_victim_crit资格位，未将radial_only改false；不给头部、GunCO、Shiver/Careen或Enervate顺带授权。两源也接入genericHit/Crit精确通知。现有Phantasma文件新增1个真实Frigid Blast配装、native/Python SHADOW回归，删除旧“尚无runtime payload”阶段测试。旧native缺新能力时回退Python；修复原生MOD包装dataclass字段顺序。

## 下一轮仍可静态推进的具体入口

| 项目 | 已闭合 | 下一步／剩余边界 |
|---|---|---|
| Zarr/KuvaZarr/Bramma/Kulstar contact子弹 | contact2/radial4；SCRIPT5覆盖门；victim crit mask明确 | base contact+790→weapon+818的impact成功路径及最终source。当前保留body近似与显式未验证资格，不仅凭字段切换整个radial_only |
| Stug parent area-direct | plan+e8来源+634与HitType+139是独立字段；旧实测规则保留 | 查plan+e8的实际recipient consumer；不能把M127实测表升级为纯native证明 |
| Pox/CodaPox/Torid EmbedAttack | 独立伤害、半径、寿命；Pox/Coda共享祖先 | EmbedAttack builder/时钟、CO基数/来源、普通事件。reference中true/false差异尚无原生依据 |
| Phantasma普通/MS子弹 | 普通3/18、MS6/36；MS载体2子弹；SendEvents是脚本门 | 子弹实际生成/继承/到达、impact与death互斥或重复路径，不能同一模板直接乘总MS |
| Trumna弹跳/Sepulcrum锁定 | 原生7bounce/MaxLife5与5target锁定字段 | 实际激活/投递数量和时钟；单体不能免费计所有空间目标 |
| Zymos／Quanta | 继承前轮来源／创建／脚本进展 | 沿前报告明确入口继续；本轮未混入新假定伤害 |

结论与证据：[NATIVE-ROUTES.md](NATIVE-ROUTES.md)、[FAMILY-INVENTORY.md](FAMILY-INVENTORY.md)。这些未尽项并非全部必须实测；明确需要场景的覆盖／LOS／弹跳命中与仍能静态还原的消费者分别记录。

## 最终验证与发布范围

- 最终相关集合 **100 passed**，零失败/错误/跳过；这些包含先前阶段的77例，不能相加报成177例。
- 现有audit工具只选Phantasma Prime、Trumna Prime、Pox：**20场景**，Python/native搜索评分完全一致、零回退、输入稳定。没有再次运行全武器2476场景矩阵。
- 全项目collect **2247例**，相比起点2443净减少196；新建测试模块0，删除4。没有宣称已执行全部2247。
- 本机Rust核心编译安装成功。旧的即时通知/独立victim-crit能力缺失会按已有机制退回Python；既有缓存指纹随代码、数据和native变化，不复用旧机制结果。
- 本批只推Portable源码与审计记录，不烘焙、不迁移Bot、不构建发行包。公开未闭合机制仍列在上表，未声称完成所有武器校准。

最终引擎输入 `4178a14118b19241`；验证native SHA256 `50a6ca44eda6654ebc1c9dea55edb5d2376cebc2e73d966aa3f16e5ed091ffba`。验证明细见 [evidence/validation.json](evidence/validation.json)。

## 连续落地轮次（起点 dd78e98）

本轮持续推进下列既定未尽项，只有确需游戏实测／场景输入的部分后置。主线程负责Stug及集成，不等待子代理空转。

| ID | 静态目标 | 负责人 | 当前状态 |
|---|---|---|---|
| R1 | 四族集束contact实际impact提交、source、crit/事件/CO各自消费 | packet_native_routes | 完成：逐枚配对、实时CO、独立资格已验证 |
| R2 | Pox/CodaPox/Torid EmbedAttack实际时钟与modifier/事件 | projectile_families | 完成：每跳当前伤害/元素/触发/CO，保留暴击桶 |
| R3 | Phantasma普通/MS子弹生成和继承合同 | lifecycle_remaining | 满夹与普通/MS子弹已接入并验证 |
| R4 | Trumna bounce/expiry实际回调，单体可用策略 | lifecycle_remaining | 已闭合；保留首次接触策略与几何边界 |
| R5 | Sepulcrum lock-target到emission和时序 | lifecycle_remaining | 已闭合；现有5主击杀→单锁导弹循环正确 |
| R6 | Stug plan+e8实际recipient consumer及特殊分类来源 | root | 错误descriptor已纠正；Stug通知已修复 |
| R7 | Zymos/Quanta剩余来源、脚本/对象生命周期合同 | root／空闲子代理 | 完成普通来源策略：有序快照、付费动作、generation门；特殊外部context另列边界 |
| R8 | 可证明修复接入、原有测试最少补改、清单收束与推送 | root | 实现/验证/文档完成；Portable提交与远端记录确认交付 |


### 本轮落地结果

- R1：四族contact已独立确认CO、victim crit及generic通知；三族终止碰撞爆炸的explicit recipient也独立开放，Kulstar不套用该终止接触结论。所有子包改为每枚contact→explosion，当前CO在到达时读取。
- R2：Torid/Pox/Coda的1秒附着包、精确CO基数与generic通知完成。普通damage/element/status动态读取，保留发射暴击桶；真实Galvanized、Merciless及Crosshairs变动在同一个既有回归覆盖。
- R3：Phantasma满夹蓄力/耗弹/父伤害与MS子弹数量分开；显式理想覆盖选项已接UI、Scenario、manual/optimizer、Rust。默认未假定每枚追踪命中。
- R4/R5：Trumna生命周期、Sepulcrum单目标锁定预算已闭合，现有首次接触/5击杀循环保留；无免费7/8次bounce或5目标伤害。
- R6：旧descriptor错移与c24后覆盖的结论已更正；Stug的genericcrit漏发已修，事件在旧目标retirement前递交。
- R7：Quanta付费主射击引爆选项已落地；Zymos有序B物理接触+333独立毒伤、普通CC/CD两查询、Enervate时点读取与Shiver接触资格已落地。实际飞行/覆盖以显式策略配置，不伪装为已实测。
- 旧核心能力不足自动回退Python；新增适配模块和机制数据均参与分析缓存指纹，旧缓存不能冒充新结果。导入器保留同source的多field/route记录，更新四种旧delayed来源不覆盖后来新增的消费者审核。

### 验证与提交范围

当前引擎输入 `bc77957493b0dd90`，本机native SHA256 `671627078a79fdcdc3b457b0db7f66d307c9c7fb1c3acb16b74aa3dfd8d92882`。

- 聚焦 **137 passed**，零失败/错误/跳过；包含真实Crosshairs保留暴击及最终Zymos源身份门。
- 现有工具选5种代表武器的 **28** 个实际搜索场景，Python/native评分完全一致，零回退，输入稳定。Quanta/Zymos可选策略另在原功能用例中经真实manual/optimizer及SHADOW验证。
- 全项目collect **2248**，本轮起点2247，净 **+1**；新增测试文件0。删掉旧“爆炸一律不吃状态暴击”的源码字符串断言与重复Phantasma旧父弹数值用例，保留真实生命周期/消费者回归。
- `node --check`、Python导入/编译及`git diff --check`通过。Rust编译完成；仅已有unused警告，没有发行包构建。
- 已fetch核对远端；本轮仅提交Portable源码、机制数据与精简证据。不烘焙、不迁移Bot、不创建release。

验证证据：[evidence/validation-r1-r8.json](evidence/validation-r1-r8.json)；实际源码链：[NATIVE-ROUTES.md](NATIVE-ROUTES.md)；测试范围：[TEST-SCOPE.md](TEST-SCOPE.md)。

### 明确后置和支持边界

| 类别 | 内容 | 处理 |
|---|---|---|
| 需要场景／实测 | 追踪子弹LOS、飞行命中率、具体命中部位；弹跳再次覆盖；cube相邻链、瞄准失败与重试 | 继续后置；UI提供显式理想单体策略，不额外发明必命中次数 |
| 已知近似 | 分数MS期望权重、Enervate两个时间点边际概率相关性、Wait0按所选帧间隔、随机延迟取代表值 | 保留诊断；不称为实机帧级／随机轨迹精确复刻 |
| 额外来源支持范围 | 能力/脚本向F/G/FE0/FE4/FE8临时缓存注入、非普通来源武器、特殊下一发伤害context | 普通静态MOD和本次Enervate不借用这些字段；已追setter/getter/reset并区分来源。不将未接入的任意能力组合称为“必须实测”或“全游戏已校准” |

本轮完成R1–R8所列普通来源合同与可选操作策略；这不是全部武器、全部外部能力组合的游戏校准证明。
