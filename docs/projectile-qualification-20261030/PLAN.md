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


## 未尽静态事项续轮（起点 f47ef0b）

继续现有普通来源之外的具体欠项，不重做上一轮已完成工作，不将原生可追路径归为实测。主线程并行负责独立消费者轴和实际模型查漏，子代理按既定6.1sol/high审计。

| ID | 本轮目标 | 当前状态 | 完成标准 |
|---|---|---|---|
| S1 | CO接触/附着包的261逐层伤害（Shiver）与259异况共存，排查radial几何标签误关 | 已实现；Pox真实live/forced回归通过 | 用已确认原生callerBase分拆接入；一个代表回归覆盖真实数值与native对照 |
| S2 | Grimoire周期链与direct重复接触、源/事件门 | 完成：空contact修正＋条件链/expiry策略；3例通过 | 静态合同闭合后显式单体策略落地，生命周期不按post-impact6秒冒充 |
| S3 | Arbucep和Battacor独立CO/generic/victim-crit路线 | 已实现；实际源+native验证通过 | 按实际Projectile与hitscan分支分别确认并修复，不套c24到hitscan |
| S4 | 特殊下一发伤害/临时source上下文的真实可装备来源 | Crepuscular/Sharpshot完成；Scourge附着50/量化/取消时点已接入 | 找实际Lua/native消费者；去掉不可能组合的假欠项，接入可确定真实修正 |
| S5 | 新改动的必要验证、导入保持、MD及Portable提交 | 完成：260项聚焦＋56搜索场景验证，待随提交记录远端 | 测试不膨胀、精简证据、旧核心回退；不烘焙/Bot/release |


S4继续追踪发现Scourge Prime原生50物理嵌入包（DOT7），脚本本身只是拾取/吸弹。已接触300→主55→即时50，1秒重复；下一次prefire立即取消旧DoEmbedDamage delegate，按原有串行3.2秒投掷策略为0/1/2/3秒四跳，上限10秒。触发资格与+半径场分开：无CO/victimcrit/head，有实际generic hit/crit。新token只结束源跳伤，不删除已经施加给原宿主的异常。

Battacor中“primary旧DoT在切换副模式蓄力时补charge”在当前单体策略不可达：第N次kill先清旧generation全部状态，再进入windup，期间无主射击。未为此扩Heat架构。反向“副射击异常留在存活目标上，回主模式后击杀被误记primary”则真实可达，继续按原生Heat源身份修复，不能用当前active mode假代来源。


S5延伸覆盖Lenz/PrismaLenz与Sporothrix/Coda：明确原host的晚爆最终type2/generic/victimcrit已接入，普通CO/Shiver保持关闭；EmbeddedDie额外.075–.15s调度纳入总延迟，源ordinary damage/status落地重读。旧“未admit”两例原位替换，无新增测试模块；详见[DELAYED-FAMILIES.md](DELAYED-FAMILIES.md)。


本轮还闭合了Scourge量化：实际victim+340先调140dc9010进行每种比例1/32量化，35/5/10成为22/32、3/32、6/32，合计48.4375。没有为追求原始整数50而跳过真实消费者。源码链和单个原字节控制见[SCOURGE-EMBED.md](SCOURGE-EMBED.md)。

Grimoire默认source350也已从非window指标/排序入口排除；源面板仍明确显示source，shotDamage按所选orb完整直接包定义，持续指标支付45秒可用周期，默认不选覆盖为0。此前仅窗口修正而静态指标仍用350的漏洞已补。


S3真实跨模式异常来源已修：源mode从独立DoT/Gas实例保留，Heat按同武器mode0→mode1组提交且共享刷新不转移seed来源；满层Blast为总伤单包、来源取最后保留stack，自然到期仍归自身。8个已核PRIMARY_KILL profiles启用，其他条件码不擅自扩用。旧windup不可达问题没有触发无谓重写；真实alternate异常回primary后的误charge已回归验证。详见[BATTACOR-SOURCE.md](BATTACOR-SOURCE.md)。

S5补原生量化half-up修正，明确binary64与float32边界，并保留baseCD-before-relative升级桶顺序；未把最终CD强制clamp32。删去3条“全局无穿刺/冰冻暴击加成”的过时测试；对应真实packet契约早已有精确替代。


## S1–S5最终交付记录

本轮已完成上表普通player source范围的可实现合同；原始现场几何/多目标覆盖仍为明确输入，不将其默认为额外命中。

- S1：接触/附着261逐层伤害与259共享callerBase，Pox真实Shiver+CO为82.5而不是错误原基数。live/forced一致；CO、victimcrit、head、generic事件轴保持分离。
- S2：Grimoire350实际contact空hook，默认不再虚构伤害；显式覆盖窗按1秒280、可选launch+6到期250计算，真实来源时点、singleorb预算、原目标退场约束及静态/窗口/搜索/贡献度统一。
- S3：Arbucep六lane direct独立CO，explicit-host radial独立资格；Battacor208+208目标radial同区CO。Heat按原source mode分组，Blast保留满层最后stack来源，8条已核PRIMARY_KILL配置不再借active mode伪造蓄能。
- S4：Zymos合法Crepuscular最终CD不再被覆盖；Sharpshot已定位weapon ring→FE4，仅兼容弓，去掉Zymos不可能装备的伪欠项。Scourge native50/DOT7的每秒source-owned tick已接入；实际1/32比例损失48.4375、main300→55→50次序、3.2秒prefire取消均闭合。
- S5延伸：Lenz/Prisma与Sporothrix/Coda明确host晚爆资格、额外死亡调度延迟和late普通source刷新；正值half-up取整与Python/Rust/sustained一致，保持已证baseCD-before-relative阶段，不擅自改最终CD32上限。

最终引擎输入 **898532bd9efba0d3**；本机native SHA256 **0ccec2621e1baaeb805dec11141b67de2477b5af999ed7002ca961d4dd354d9a**。**260 passed**，零失败/错误/跳过；9武器记录、**56搜索场景**Python/native一致、零回退且输入稳定。8个请求名称包含目录中的不同Grimoire记录，统计保持实际路径身份，未把名称合并为覆盖证明。可选Grimoire的实际API／optimizer／native在原功能用例内验证，不混入默认56场景数。

全项目只collect，**2239例**，相对此轮起点2248净**-9**；新测试模块0、删除过时模块1。三档charge保留3个真实展开，用SHADOW替代Python×native双矩阵。没有执行全2239或宣称全部游戏校准。

导入/语法/JS/格式检查通过，原生构建成功，仅原有unused warnings。新能力不足会从旧native回退，分析缓存指纹包含全部更新源码/数据；本轮没有烘焙、Bot同步或release。详见[evidence/validation-s1-s5.json](evidence/validation-s1-s5.json)、[TEST-SCOPE.md](TEST-SCOPE.md)、[GRIMOIRE.md](GRIMOIRE.md)、[SCOURGE-EMBED.md](SCOURGE-EMBED.md)、[BATTACOR-SOURCE.md](BATTACOR-SOURCE.md)。

### 不夸大交付范围

保留的近似包括真实飞行/LOS/目标覆盖、分数多重与状态概率的期望模型、部分随机延迟取均值、binary64与原生float32边界。外部能力/脚本对source缓存的任意更新、特殊ADD_BASE暴击桶的全组合等未在本轮普通来源合同内承诺；这类后续工作是具体静态支持范围，未一概归类为只能实测。原生金额、触发路线、时钟和已实现的来源规则已按上述合同接入，不停留在研究报告。
