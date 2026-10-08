# 近战建模重做方案（2026-10-08）

本文分两部分：先列今天游戏更新对 Portable 的影响，再给近战重做的分析与方案。
数据来源：本机客户端 10.08 更新后的 Packages.bin（00:54 更新落地；昨晚 00:53 的解包是旧版），
动画头文件（Exporter `--write-raw`），以及游戏本体字符串。

---

## 一、今日更新的影响

与 09.25 版 Packages.bin 对比：782 个实体有改动，新增 315、删除 255，绝大多数是场景、音效和外观。
与计算有关的如下。

### 1. 紫卡模板（7 个 RandomModRare 全部改动）

- **枪械融合词条改为服务器口径**：手枪弱点伤害 0.01 → 0.025（基值 225）、弱点暴击 → 0.0275（247.5）；
  四类枪的弹药效率 -0.001 → -0.005（45）；磁力的伤害类型 DT_POISON → DT_MAGNETIC。
  这与我们昨晚按维基写入的 `FUSION_SERVER_BASES` 完全一致，**枪械不用再改**，覆盖表变成冗余但无害。
- **近战新增融合词条**：状态伤害（90）、六种复合元素（90）、Orokin / Techrot / Scaldra（45）。
  Portable 和 Bot 的近战融合表都只有重击伤害 / 蓄力 / 震地 / 格挡角度四条，**需要补上**。
- 格挡角度 0.09 → 0.009（×90 = 8.1），与我们现有值一致。
- **组合武器模板**（`LotusModularPistol` 组合枪、`LotusModularMelee` 赛特刀）这次才加入融合词条；
  `riven_fusion.available_codes` 优先读标准模板，结果不变，但 `riven_templates.json` 应重新生成。
- **融合配方（MergeOptions）现在对所有类型都发布了**（之前文档记录只有步枪）。
  近战配方例如：重击伤害 = 重击效率 + 额外连击；震地伤害 = 近战伤害 + 攻速；格挡角度 = 攻速 + 范围。
- 霰弹模板新增变焦（WeaponZoomFovMod，非融合）。看位置是弱点系配方的原料；它是否进入霰弹紫卡的随机池还需确认。

### 2. 武器与灵化

| 项目 | 改动 | 对我们的影响 |
|---|---|---|
| 毒囊双枪 进化 3B（爆头后 3 秒） | `WEAPON_DAMAGE_AMOUNT` +70% → `WEAPON_PERCENT_BASE_DAMAGE_ADDED` +70% 毒素 | 从基础伤害乘区改成加毒素元素；我们的数据还是旧口径，需要修 |
| Latron Prime 灵化副火 | 多重射击额外弹体改用 `LatronIncAltFireWaveMSProj`（即普通 Latron 的弹体：直击 50，爆炸 80，暴击 32%/3.0×），主弹体仍是 140、44%/3.4× | 多重射击额外弹体伤害下降；普通 Latron 数值不变 |
| Zymos 子母弹 | 嵌入死亡时的子母弹改由 `OnRadialDamage` 和 `OnDeath` 触发（Lua） | 触发时机变了，需要按新事件核对 |
| Argon Scope（Primed） | 只改了条件描述文本，条件本身仍是弱点击杀 | 无 |
| Duelist 手枪 / 弓 | 新武器的特效与音效条件 | 不在目录，无 |

### 3. 顺带发现的两个现有问题

- **近战快速档锁定病毒时误报不可达**：Nikana Prime 快速档 + 病毒报 `element-target-infeasible-DT_VIRAL`，
  退回无约束配装。超快档正常（Bot 走超快，不受影响）。
- **范围 MOD 被塞进配装**：Primed Reach（`WEAPON_RANGE` 未建模，等于零收益）出现在 Nikana Prime、
  Glaive Prime、Fragor Prime 的无紫卡和当前配装里，占掉一个槽位。

---

## 二、近战现状

| 环节 | 现在的做法 | 问题 |
|---|---|---|
| 普通攻击 | 每把武器取维基架势表里 DPS 倍率最高的一套连段，把「总倍率 ÷ 时长」当作常数乘到每次攻击上，攻击频率就是攻速 | 没有逐次挥击：每击的强制异常、伤害类型倍率、连击数增长全都丢了；维基表有 5 处缺口、1 处缺时长 |
| 连击数 | 场景固定 `comboTier = 0` | 嗜血（Blood Rush）、创口溃烂（Weeping Wounds）恒为 0，永远不会被选；初始连击、连击时长、额外连击这些词条都没有价值 |
| 重击 | 只在 `heavyDamage` 口径下算一次重击的单发伤害；`heavyAttack` 数据里的蓄力时间取 `ComboData.HeavyMeleeChargeTime` | 不进 KPM 循环；连击倍率、连击消耗、重击效率都没算；77 把武器的蓄力时间是 2.0 秒（Nikana Prime 也是），疑似读到了类默认值 |
| 震地 | 不建模（EXPANSION-2026.09.22 里明确写了「有意不建模」） | 震地伤害、震地范围、重击震地全部为零 |
| 战刃 | 重击 = 一次投掷直击 + 一次召回爆炸的单发伤害 | 没有投掷循环、弹跳、普通投掷和重投的区别，爆炸是否吃连击倍率未定 |
| 支持的升级类型 | 近战伤害、初始连击、连击时长、重击效率 | 未支持：重击蓄力速度（Killing Blow、Melee Elementalist、Amalgam Organ Shatter）、震地伤害（Seismic Wave、Boreal 套装）、额外连击几率、范围、护甲削减（Shattering Impact）、处决伤害；近战赋能（Melee Influence / Crescendo / Animosity / Duplicate 等）全部依赖脚本，未接入；Tennokai（强化重击）未接入 |

结果：近战紫卡分析里，初始连击 B、连击时长 N、额外连击 O/Q、重击效率 U、重击蓄力 HC、震地 SL、
范围 T、滑行暴击 E 全都给不出有效贡献，推荐和评分对近战系统性失真。

---

## 三、静态分析结论：游戏数据里都有什么

### 1. 武器本体（`MeleeImpactBehavior` 与 `LotusMeleeStateBehavior`）

- 伤害：`AttackData`（各伤害类型、总量、触发几率）、暴击、攻速（`fireRate`，如 65 → 1.083）。
- 连击计数器：`BaseHitCount=20`、`HitReqNextTierOperator=20`（加法）、`HitCounterCap=220`、
  `TimeBetweenHits=5`（受 `WEAPON_MELEE_COMBO_DURATION_BONUS` 影响），`InitialHitCounter`。
  227 把一致；例外 5 把：上限 240、110，时长 6 / 9 / 10。
- 重击：`ComboData.HeavyMeleeChargeTime`、`MeleeDisableTime`、`ConsumeComboOnHeavyAttack`
  （17 把显式写了，战刃为 0 = 重投不消耗连击）、重击攻击集（`CC_GROUND_HEAVY`）。
- 多目标：近战树 `AvatarDamageFalloff`（贯穿衰减，如 0.7）、`SweepRadius`、`MaxHitAvatarsPerAttack`。

### 2. 震地（`Slams[]`，逐把武器）

每条记录：触发动画事件（MeleeSlam / HeavySlam / AxeSlam / LightSlam / GauntletSlam / GlaiveAirSlam…）、
`Radius`、`FallOffMax`、`CanCrit`（全部 0）、`CanUseComboMultiplier`（重击震地为 1）、
`BaseDamageAttenuation`（普通震地 1，重击震地 1–5）、伤害类型（冲击 / 爆炸 / 电 / 磁 / 火）、强制异常、
`UseWeaponProcChance`、`UseModifiedRadius`（范围 MOD 影响半径）。另有：

- `SlamMeleeAttack=SlamAoE`（`BaseDamageAtten=2`）、`HeavySlamMeleeAttack=HeavySlamAoE`（3），
  两者的 `DamageUpgradeTypes` 都含 `WEAPON_MELEE_SLAM_DAMAGE_BONUS`；
- `FullSlamRadiusHeight=10`、`SlamRadiusPercentageClamps={0.5,1.5}`：半径随下落高度缩放（0.5–1.5 倍）。

按武器分组后有 25 类以上的组合，例如锤类普通震地半径 9、重击震地 ×5；
Kestrel / Halikar 震地是磁力；Lecta 系是电。

### 3. 架势（近战树 → 攻击集 → 攻击 → 动画）

- 近战树按情境给出攻击集：`CC_GROUND`、`CC_GROUND_BRANCH_A/B/C`、`CC_GROUND_HEAVY`、`CC_SLIDING`、
  `CC_AIR`、空中 `BP_DOWN`（震地）等。
- 每次攻击有 `BaseDamageAtten`（倍率）、`ProcChanceAtten`、`DamagePctAtten`（逐伤害类型倍率）、
  `ExtraProcs`（强制异常）、`ComboHitsToAdd`、`PerSwingOverrides`（一个动画内多次挥击各自的参数）。
- **动画事件就在 Packages.bin**：`StartMeleeSweep` / `EndMeleeSweep`（以及 MeleeSlam、HeavySlam、
  ReleaseProjectile、MeleeChargeFinished 等），时间是 0–1 的归一化值。
- **动画时长从动画头文件解出**：`Take 001` 前的浮点数是 1/时长；全部是 30 fps 的整数帧
  （2.5 → 12 帧 = 0.4 秒，15/14 → 28 帧）。

**校验**（Decisive Judgement 中立连段）：倍率 2+3+2+3+4 = 14、5 击，与维基完全一致；
时长按动画求和 0.4+0.4+0.4+0.667+0.7 = 2.57 秒，维基实测 2.65 秒（差 3%）。
前进格挡连段 3 次挥击各自的覆盖值加上 4 倍终结 = 10、4 击，也与维基一致。

### 4. 战刃（`GlaiveMeleeStateBehavior` 与投射物）

- `TapTime=0.4`（短按 = 普通投掷）、`HeavyMeleeChargeTime=0.7`、`ChargeDuration=1.2`（重投）；
- 普通投射物与 `TurboProjectileType`（重投，伤害更高，如 Glaive Prime 360 / 普通 180）；
- 爆炸：`ExplosiveAttack`（592，半径 4.8，衰减 0.4），重投召回爆炸 `HeavyRecallDamageAtten=2`；
- 飞行：初速 55、`MaxReflections=4`（弹跳）、`AutoRecallTimer=0.75`、`SeekDistance=20`、`MaxLife=15`。

### 5. 待定（游戏数据里没有直接写的）

| 问题 | 现有线索 | 定案办法 |
|---|---|---|
| 连击倍率每档加多少 | 维基：每 20 击 +1×，1×–12×；数据 `BaseHitMultipler=1` | 游戏本体静态分析，或游戏内一次实测 |
| 震地伤害公式（原伤害 × 哪几个系数，元素 MOD 是否加到范围伤害上） | `UseImpactBehaviorAttackDataAmount=1` + 覆盖伤害类型 | 静态分析 `mBaseDamageAttenuation` 相关函数，或训练场实测 |
| 重击真实蓄力时间 | 77 把是 2.0 秒，与维基常见的 0.5–0.8 秒对不上；蓄力动画里有 `MeleeChargeFinished` 事件 | 对比蓄力动画时长与维基；必要时静态分析 |
| 攻速是否影响重击蓄力、震地动画 | — | 同上 |
| 战刃爆炸是否吃连击倍率 / 重投是否消耗连击 | `ConsumeComboOnHeavyAttack=0` | 静态分析 + 维基 |
| 连击计数超时是清零还是逐级掉 | 狙击是每周期 -1 | 维基 + 静态分析 |

游戏本体里能找到对应的反射字段（`mHeavyRecallDamageAtten`、`mCanUseComboMultiplier`、
`mConsumeComboOnHeavyAttack`、`mSlamRadiusPercentageClamps`、`mChargeAffectsSlamDamage` 等），
可以沿用之前定位 `Projectile::DoEmbedDamage` 的做法。

---

## 四、方案

### 阶段 0：同步今日更新（小）

1. 用 10.08 版重新生成 `riven_templates.json`（融合配方、组合武器模板）；近战融合表补状态伤害、元素、新派系。
   Bot 的 `riven_fusion_bases.go` 同步补近战。
2. 毒囊双枪 3B、Latron Prime 灵化多重弹体按新数据修；Zymos 核对新触发方式。
3. 修近战快速档锁定元素的误报；不支持的 MOD（范围）不再作为填充进入配装。

### 阶段 1：近战静态数据（新工具 `tools/import_melee_mechanics.py` → `data/mechanics/melee-mechanics.json`）

- 逐武器：伤害、攻速、连击计数器、重击参数、`Slams[]`、震地攻击倍率、贯穿衰减、战刃全部字段。
- 逐架势：各情境的攻击序列，每次攻击的倍率、逐类型倍率、触发倍率、强制异常、连击数、逐挥击覆盖、
  动画时长与挥击窗口；无架势时用武器类默认树。
- 动画时长需要从游戏缓存解出，一次性烘进 JSON，运行时不依赖游戏文件。
- 自检：231 套维基连段的总倍率与击数逐一比对（应完全一致），时长偏差列表（目标 ≤10%），离群值逐个看。

### 阶段 2：引擎（逐次挥击 + 动态连击计数器）

- 新模块 `melee_sequence.py`：把一条攻击路线展开成命中事件表
  （时间、倍率、逐类型倍率、触发倍率、强制异常、加多少连击、能否暴击、是否吃连击倍率、攻击种类）。
  动画时间按攻速缩放，重击蓄力按蓄力速度缩放。
- `combat_replay` 增加这类事件源，伤害仍走现有的伤害包（暴击、异常、DoT、Condition Overload 全部复用）。
- 连击计数器进入回放：逐击累加（额外连击几率），按档位给出倍率，超时衰减，初始连击来自 MOD / 赋能；
  嗜血、创口溃烂这类连击档位条件改为逐击读取当前档位，取代固定的 `comboTier`；
  重击按当前档位乘倍率，再按重击效率扣连击。
- 单目标口径：靶子站在震地中心或挥击路径上，半径和贯穿只在后续多目标模式里起作用；
  震地的距离衰减按场景参数（默认 0 米）。

### 阶段 3：攻击路线（与灵化路线同样的机制）

| 路线 | 循环 | 关键参数 |
|---|---|---|
| 轻击连段 | 架势中按 KPM 最优的一套连段循环 | 架势、连段 |
| 重击循环 | 轻击攒到 N 档后重击，重复；N 由搜索决定 | 蓄力、连击消耗、重击效率、初始连击 |
| 震地 | 跳起 → 普通震地或重击震地 → 落地硬直，循环 | 起跳高度（影响半径）、单次循环时长、震地伤害 |
| 战刃 | 投掷 → 弹跳 → 引爆或召回；重投 → 引爆；或近战连段 | 短按 / 重投、引爆时机、弹跳次数（单目标下按 1 次命中） |
| 滑行攻击（可选） | 滑行 + 攻击 | 滑行暴击 E |

- 每把武器的默认路线：无紫卡状态下各路线跑一次，取 KPM 最高者固定下来，后续评分都用这条路线
  （避免紫卡把路线来回切换）。计算说明里加一行「攻击路线：…」，前端可手动改。
- 耗时：只在无紫卡阶段多跑 2–4 次回放；超快档可以只跑缓存里记录的默认路线。

### 阶段 4：词条与配装

- 接入近战专属升级类型：重击蓄力速度、震地伤害、额外连击几率、范围（只作用于震地半径）、护甲削减；
  处决伤害不在 KPM 口径内，标为不计入。
- 紫卡词条 B / N / O / Q / U / HC / HD / SL / T / E 在对应路线下有了实际贡献；新近战融合词条进入推荐。
- 近战赋能、Tennokai（强化重击）依赖脚本，放到后续单独一轮。

### 阶段 5：验证与收尾

- 数据层自检（阶段 1）；对几把代表武器做路线对照：Nikana Prime（轻击）、Fragor Prime（震地 / 重击）、
  Glaive Prime 与 Orvius（战刃）、Kronen Prime 或 Dual 系（连击）。
- WFSim 是否覆盖近战待确认；如果不覆盖，需要你在训练场测几组数字（连击倍率、震地、重击蓄力）作为锚点，
  或者用本体静态分析代替。
- 缓存版本号递增；完成后 Bot 重新同步、重新烘焙（约 1 小时）。

---

## 五、需要你拍板的事项

1. **靶子口径**：近战沿用单目标 KPM（推荐），还是加一个多目标模式（震地半径、贯穿、战刃弹跳才有意义）？
2. **路线选择**：按无紫卡最优自动定路线（推荐），还是按武器类固定（如锤 = 震地、战刃 = 重投引爆）？
3. **震地场景**：默认按原地跳一次的低空震地，还是子弹跳高空震地？这决定循环时长和半径。
4. **重击循环**：允许「轻击攒连击再重击」的混合循环（推荐），还是只算纯重击 + 初始连击？
5. **阶段 0 是否先单独提交**：它会改变枪械的结果（毒囊双枪、Latron Prime），Bot 缓存要重新烘焙；
   我的建议是阶段 0 先在 Portable 提交，Bot 等近战一起同步，只烘焙一次。

---

## 六、用户决定（2026-10-08）

- 单目标，不让范围武器的数字被放大。
- 路线：Portable 可选「走A（轻击连段）/ 震地」；Bot 锤类走震地，战刃走「蓄力重投 + 引爆」，其余走 A。
- 重击只按初始连击算倍率，不做「连段攒连击再重击」（计算量过大）。
- 震地高度：Portable 保留「原地跳到最高点震地」和「垂直子弹跳震地」两种，比较时间与收益后择优或都保留。

## 七、阶段 0 结果

- `tools/refresh_riven_fusion.py` 改为逐类型读取各自模板的 MergeOptions（不再只读步枪表、近战不再用工坊表）；
  用 10.08 模板重新生成 `riven_templates.json`：5 类共 84 条配方全部来自游戏数据；近战融合词条 14 条
  （原 4 条 + 状态伤害、六种复合元素、三个新派系），近战配方与官方工坊表一致（震地 = 近战伤害 + 攻速等）。
- 毒囊双枪 3B：四处效果改为 `WEAPON_PERCENT_BASE_DAMAGE_ADDED` 毒素；描述显示「毒素伤害 +70%」。
  裸卡 KPM（Lv170 钢铁、50% 爆头、选 3B）0.167 → 0.135。
- Latron Prime 灵化副火：`fireModes[1].multishotCopy` 记录额外弹体（直击相同、爆炸 80/140、暴击 32%/3.0×、触发 24%），
  `damage.apply_mods` 按期望值混合（伤害按份额、暴击与触发按弹体）。带分裂膛 + 警戒等 5 张卡 KPM 0.703 → 0.600。
  游戏里另有 Grattler 太空模式、Kuva Grattler（暴击 27%→25%）的多重弹体与主弹体不同，暂未接入。
- Zymos：本地模型只有直击 + 爆炸，未建模爆头嵌入爆发和子母弹，这次的触发方式变化不影响现有结果（遗留缺口）。
- 近战快速档锁定元素误报：约束解失败时先按超快档同样的方式预置最强的两种元素卡再解，仍不可行才退回无约束。
  Nikana Prime 快速档 + 病毒现在得到病毒配装。
- 「范围 MOD 占槽」不是 bug：`_candidate_mods` 对非显赫近战把 Primed Reach 设为必带（既有策略），撤回。
- `ANALYSIS_STATICS_CACHE_VERSION` 23 → 24。全量测试 848 通过（含新增 `tests/test_update_20261008.py` 3 项）。

## 八、阶段 1 进展：静态数据

- `tools/packages_bin.py`（Packages.bin 读取器，原在 .local）、`tools/import_melee_mechanics.py`、
  `tools/check_melee_stances.py`、`vendor/wfarsenal/melee_sequence.py`，输出 `data/mechanics/melee-mechanics.json`
  （237 把武器、109 个近战树、939 次攻击，全部攻击都有动画时长）。
- 动画事件有两处来源：Packages.bin 里的动画实体（覆盖）和动画头文件里路径后面的「长度 + 文本」块（基础）。
- 连段内的震地：动画里的 MeleeSlam / AxeSlam / ShieldBash 等事件触发武器 `Slams[]` 对应条目，算一次范围命中
  （倍率取该条目的 `BaseDamageAttenuation`；1 米的 GroundAttackEffect 只是效果）。
- 与维基 206 套有数据的连段对照：总倍率与击数同时一致 185 套（90%）；其余主要是拳套 / 格斗类（拳脚效果事件）与疑似维基笔误。
- 时长：非末段攻击在 `WaitStart` 事件处接下一段、末段播完，150/205 套在维基时长 ±10% 内（均值 0.96）。
- 维基补充（wiki.warframe.com Melee / Heavy Attack）：连击倍率每 20 击 +1×（2×–12×），5 秒无命中清零；
  重击消耗全部连击（重击效率保留一部分，上限 90%）；攻速不缩短重击蓄力；普通震地直击 2×、重击震地 3×，
  范围伤害为单一类型（冲击 / 爆炸）、可被伤害与元素 MOD 加成，中心 100% 线性衰减到边缘 50% / 70%；
  下落高度只放大半径（最多 150%）——单目标下高度不影响伤害，只影响循环时间；战刃只有爆炸吃连击倍率。
  维基的分类重击蓄力时间（Nikana 0.5、锤 1.2 秒等）与数据里 77 把武器的 2.0 秒不符，引擎改用蓄力动画时长核对。

## 九、阶段 2–4 结果：逐次命中引擎与攻击路线

### 引擎

- `melee_sequence.build_schedule` 把一条路线展开成「固定秒数 + 动画秒数（1.0 攻速）+ 命中」的循环；
  回放每次 fire 事件落一次命中：按该次的倍率、逐类型倍率、触发倍率、强制异常改写当次属性，
  动画时间除以攻速，跳跃 / 下落 / 飞行 / 蓄力不受攻速影响（蓄力受重击蓄力速度影响）。
  有命中表时架势倍率与触发频率倍率不再叠加（回放里置 1）。
- 连击计数器进回放：从初始连击开始，每击加 `ComboHitsToAdd ×（1 + 额外连击几率）×（1 − 不加连击几率）`，
  超过连击时长无命中回到初始连击；倍率 1 + 每 20 击 1 档（2×–12×）。嗜血、创口溃烂等连击档位条件
  改为 `__comboTier` 动态层数（按各自上限截断），不再用静态 `comboTier`；优化器候选池保留这类「静态为空」的卡。
- 重击（重击震地、战刃重投）按用户口径用初始连击的倍率；重击震地按重击效率保留连击（上限 90%，不低于初始连击）。
  重击命中以 `PM_HEAVY_MELEE` 场景重算（重击伤害融合词条、Killing Blow、暴击卡对重击的双倍部分生效）。
- 新支持的升级类型：额外连击几率、不加连击几率、重击蓄力速度、震地伤害（与近战伤害同一乘区，
  按 SlamAoE 的 DamageUpgradeTypes）。范围仍不计入（单目标）。
- 范围命中（连段内的震地事件、震地范围、战刃爆炸）：武器物理基础伤害改为该次的单一类型（冲击 / 爆炸 / 电 / 磁 / 火），
  元素 MOD 部分保留；震地范围不暴击；靶在中心，无距离衰减。
- 战刃投掷与爆炸用投射物自己的数值，相对近战数值按比例换算暴击、暴伤与触发（暴击 MOD 的平加部分有微小误差）。

### 路线

| 路线 | 循环（1.0 攻速） | 说明 |
|---|---|---|
| combo 走 A | 架势四套连段中按「总倍率 / 秒」取最优 | 非末段在 WaitStart 接下一段，末段播完 |
| slam 原地跳 | 起跳 0.73 s + 下落 0.73 s + 落地动画到 WaitStart | 有重击震地就用重击震地（直击 ×3 + 范围 ×4–5 × 初始连击倍率） |
| slamBullet 垂直子弹跳 | 起跳 0.32 s + 下落 1.03 s（10 m） | 同上 |
| glaive 蓄力重投 + 引爆 | 蓄力 + 投掷动画 + 飞行（默认 10 m）| 直击用 Turbo 投射物，爆炸 × HeavyRecallDamageAtten 2 × 初始连击倍率 |

- 默认路线 = Bot 规则：锤类震地、战刃重投引爆、其余走 A；Portable 分析页新增「近战攻击路线」选择（只对近战显示，战刃项只对战刃显示）。
- 计算说明新增「攻击路线：…」一行（置顶），内容为架势中文名、连段、击数、总倍率与一轮时长。
- 架势默认选择改为按提取数据的循环倍率排序（维基值兜底）。
- 战刃分析从单发重投伤害（heavyDamage）改为 KPM。
- 统计缓存键加入近战路线（route / stance / combo）。

### 震地高度对比（16 把锤，同一套卡，Lv170 钢铁）

单目标下高度只影响半径，不影响伤害，差别只在一轮时长。按当前模型，垂直子弹跳一轮短约 0.1 s
（起跳更快，下落更长），KPM 持平到 +11%（Fragor Prime 6.17 → 6.83、Ekhein 5.29 → 5.85、Volnus Prime 4.83 → 5.23），
没有一把更差。两种都保留，默认原地跳——因为下落按自由落体估计（数据里没有震地俯冲速度），
子弹跳的上升也没算前 0.8 s 的减重力，这两个假设恰好决定两者的先后。需要游戏内各掐一次一轮的时间来定。

### 已知问题 / 后续

- Magistar / Sancti Magistar / Sibear 等近战灵化武器的面板伤害异常偏高（Magistar 冲击 16968）：进化 II 的
  `WEAPON_MELEE_DAMAGE ADD_BASE 100`（+100 点基础伤害）被近战伤害乘区当成 +10000% 倍率，与此前修过的
  `WEAPON_DAMAGE_AMOUNT ADD_BASE` 同一类错误（既有问题）。本轮一并修正：近战 ADD_BASE 并入平坦基础伤害。
- Orvius 用 `HomingGlaiveFireBehavior`，导入器补上后才有战刃路线。
- 赛特刀（Zaw）与暗影分裂剑的两种形态没有命中表，仍走旧的架势倍率模型。
- 拳套 / 格斗类连段里的拳脚效果事件（PunchEffect / KickEffect）、枪刃射击事件未计入命中，21 套连段与维基不符。
- 滑行攻击（E 滑行暴击）、处决（X）、近战赋能、Tennokai 未接入。
- 多重弹体：Grattler 太空模式、Kuva Grattler 未接入。
