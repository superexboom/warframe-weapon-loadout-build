# 显赫数据与求解路径复审

固定来源为2026.10.22.13.12原件；source审计见EXALTED-SOURCES。35条显赫包含23近战、12远程，raw amount/crit/status与当前重提取数值没有漂移；这不证明技能执行覆写和弹体行为正确。root完整对照在`.local/delivery/mechanics-followthrough-20261102/root/exalted-raw-mode-census.json`、`exalted-melee-raw-census.json`。

## 已发现并落地

1. 旧sidecar未带近几轮新增的独立head flag、type声明和IgnoreFireIterations。新增既有extract-exalted-weapons工具的`--refresh-native-flags --packages-bin ... --client-exe ...`路径，核原件SHA后仅更新远程声明/provenance，保留技能运行时伤害另层处理。Noctua副射击Wave的head抑制和固定单实体、Lizzie主beam impact及音符Wave的head抑制已恢复。它们不是Grimoire周期链。
2. UI/API以前只要headshotIssue非空就强制headshotChance0，错误抹掉Lizzie可选实际头部输入。现在headshotLocked仅用于Cowgirl自动躯干瞄准，Temple保留“无头部倍率”提示；真倍率由独立native flag控制。原既有测试扩actualAPI headmix与Python/native MOD核，无新增case。
3. Neutralizer副射击source ForcedProcs仅保存了列表，漏ForcedProcCount10。原生descriptor142798530→serializer1408f9e18/2b将mForcedProcCount写AttackData+24；140c80000在140c80396..5c7按计数轮询bitset，逐次累加DamageInfo218[type]，region140508a50同样累加plan+a0。提取器沿既有重复项表示展开计数，下游原本就计列表重复数量，故不需另建运行时字段。一个既有显赫文件新增case验证actualNeutralizer副射击10层Cold和native调用；不把0SC误当无强制异常。
4. Artemis副行为由RangerBow实际装备回调转为Quiver技能选择/释放，旧继承impact8不是另一个240伤害模式。选择器/直接计算/原生prepare回退入口统一拒绝该独立伤害候选，目录仍保留原索引与中文说明。正常Artemis的实际7箭和源参数继续按完整脚本核对。

## 审计工具修正

原ranged inventory和selected matrix直接读冻结显赫8/15等placeholder，没有执行技能属性层，旧“无差异”仅覆盖错误输入。两个现有工具现在用无MOD满级100%强度应用显赫规则及能力bonus，并排除ability-action，仍明确这不是跨所有战甲配置/技能增幅的正确性证明。未新增验收脚本。

## 本轮保留边界

近战23条raw核对没有值漂移，但ExaltedBlade/DesertWind的附加投射物、Khora/Gara/Atlas/Ash各自脚本combo/cast机制仍需独立技能消费者审核。旧CAST_COMBO_POINTS21与通用满连击12来源未在此远程优先批次升级为native确认，不能以raw相同代替校准。能量仍按既有无限能量求解＋无回复续航读数口径。


## Artemis完整箭体接入

原extract只在advanceSequence且多枚时展开sequence，Ranger固定slot0的两种普通/增幅箭未走该分支，错误回落weapon impact8。专用exalted提取器现按实际装备默认索引0选择ExaltedArrow/PrimeExaltedArrow，保留raw75和14/80/6比例、CC25%/CD2/SC20%。运行时RangerBow技能层把每箭源改240*S并设置7箭。

FiredArrow脚本先把箭体SC乘raw fireIterations7，实际1416373e0 source6c8后调用141586f50归一化。固定客户端linear flag142795214为1；本轮直接执行原helper以1.4/7得到.20000000298，故模型字段保存SC1.4/MS7，追加MOD多重不会再次稀释每箭SC。证据`root/artemis-proc-control.json`。

同一现有文件新增1个Artemis合同验证实际箭体、IPS、100%多重14箭且SC仍20%、selected-mode与manual前处理一致、目录副模式不可选以及manual/build均拒绝Quiver伤害请求。Concentrated Arrow已识别为真实不同script分支，当前未接其爆头爆炸；若关联配置装该增幅，会带明确`artemis-concentrated-arrow-not-supported-normal-arrow-policy-used`，不把默认7箭说成支持增幅。真实箭束全命中是现有单目标覆盖策略；完整tap/hold/蓄力旋转和场景落点不是本次金额验证。

旧近战施放循环的21连击点/12倍、所有显赫增幅MOD与技能叠加仍需各自执行脚本复审，不能拿这次12远程声明复核当成35把全机制完成。


## 肃清者、丽兹强度乘区纠正

FrumentariusSniper与TempleGuitar都以原始1.25进入InventoryController490标量查询axis10，在查询完成后减1，并写WEAPON_DAMAGE_AMOUNT253/op3。实际InventoryController142331a78/4901416d07b0→4981410c45f0→UpgradeManager把普通强度应用完整base，故普通规则为1.25*S−1。原`.25*S`只在S1时巧合相等。S2应+150%（旧+50%）；不含其他卡时Cyte255*2.5=637.5，Lizzie85*2.5=212.5。原字节控制已验证S.5/1/2/3，保留conditionedcontext/clamp支持边界。

同一既有bonus回归补Cyte/LizzieS2、实际关联Blind Rage S1.99 API、Glory2倍强度单radial300。Glory确认脚本写的是ExplosiveAttack.Amount(+5c8)，当前topprimary原本已是该radial，故只同步component预览金额，不再把旧15加成第二包。


### 普通MOD与技能强度不能重复烘入

最后消费者复核纠正精确存储语义：Noctua/Glory的df33cc3d仅返回UpgradedValue base+addBefore，因此脚本写入的是base250/2750/150，强度modifier仍在Projectile818，而不是setter直接写全求值后的S倍值。当前产品把base*S作为effective source，在普通乘法强度且没有特殊ADD_BASE/override的本次范围下数值等价，只吃一次普通weapon MOD。Artemis的c6e5fc7b取impact时传false/false，140a62030分别读原始impact104并跳过ordinary upgrade loop，不先把Serration烘进箭体；当前240*S后加普通MOD一次正确。

这里是精确存储与产品等价式的区分，覆盖前文“setter写150*S”的简写。特殊addBefore/override与所有增幅尚非本次普通口径证明。Mesa满爬升2.5仍是既有明确稳态近似，不称本次已校准其启动爬升。


## 显赫实体弹药与Noctua冷却补全

消费者续查确认UseAmmo0或rawrequirement0不会被原生变为1。当前通用ammoCost `or1`只在这些显赫产生错误默认：Glory、Noctua两模式、Regulators/Prime已按精确模式标nativeAmmoFree，Python/native MOD入口同步ammo0。DexPixia/Neutralizer保留实体弹药。Artemis虽然zero物理扣除，但UseReloadTimeBetweenShots1有独立.85s状态间隔，本次未把它当作普通无需等待连射。Lizzie主射ConsumesChargesForFire1有独立资源循环，保留无限能量求解下的明确未建模诊断，不从UseAmmo0发明资源免费结论。

Noctua副射击与已核Grimoire相同LotusFireAndToggleState：InstantOverheat1/PLATEAU，60秒，CooldownModifier1；PRIMARY_DIRECT_HIT每次恢复1秒，单独副模式没有这些主射击事件。现exact mode.nativeFireCooldownSeconds60进入现有事件门，静态/搜索的实际射速也封顶1/60，不吃射速MOD；初次ready，59.9秒1发、60.1秒2发、没有假装填。混合主副射击的恢复策略不在当前单模式接口中假造。原测试扩native SHADOW/调用计数和Dex未改断言，无新case。

以上发现属于本轮整体回顾后真实补漏，覆盖PLAN中“实体弹药消费待核”的临时状态。真实无限能量边界保留，token/随机状态不因此称为实机复刻。
