# 远程原生机制落实，2026-10-29

当前基线cb7a22a，游戏EXE重新核验SHA256 eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d，仍为保留2026.10.22.13.12构建。Packages证据为此前保留样本00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06。没有把未完成静态路径写成必须实机测量。

已接入待总回归：

- Battacor先windup后副射击，避免首发提前及重复付费；Python/Rust feature KILL_CHARGED_WINDUP，旧native自动回退。0.4秒按原生chargeModifier和射速倍率缩短。
- Battacor允许combatState.battacorCharges=1/2/3，默认仍1；阈值分别需1/2/3次主射击击杀、消耗全部蓄能，两个伤害包消费前snapshot各乘1/2/3。配置加入Scenario验证和缓存上下文，UI可选且刷新恢复已检查。当前临时buff完成时快照，以及蓄力期间旧primaryDoT击杀是否另涨charge仍显式未闭环；不把这些说成精确模拟。
- Phantasma/Prime主爆炸73 Radiation、EFV8副射击313 Corrosive已按原生完整payload接入，空间单体中心假设与现有模型一致；额外CO和weakpoint权限仍不由rawHitType推断。7个时钟/替代死亡路径未闭合候选暂不合入默认评分。
- Miter700/Buzlok40/Aeolak25继承爆炸在当前普通路径radius0，已证构造器及radial builder拒绝，不属于活跃伤害遗漏。
- Zakti/Prime、Kompressa/Prime的权威damage->AGC链已进一步闭环，普通命中/暴击通知正在按准确producer身份接入（死亡归属与head限制独立）。

正在继续：MutalistCernos swarm的实际周期与source modifier；Acceltra实际原生接触伤害和arming门；Arbucep六投射物lane与多重额外弹体选择；其余待记录精确static/runtime边界。Zymos子弹体继承与Mandonel场仍未完成，不宣称全落地。

临时UI服务8774和临时IAB页已关闭。浏览器检查武使之力副模式可见蓄能1..3输入、填写3并刷新后仍3、无console error；实际manual custom100HP API三策略均有变换循环。最终证据/测试计数待所有生产修改冻结后写入。

## Quanta射击引爆静态进度

补找到了实际native开关，原生父Projectile constructor设GrenadeShootDamageMultiplier+0xfa4=4、RadiusMultiplier+0xfa8默认2，Quanta显式覆盖radius倍率12。原生selector14160c5a0仅在非embed且shotByAllowedSource+0x638成立时，把单包amount的operation2倍率乘4，同时半径0.5×12=6。自射/同队/玩家等许可门1419e1860在保留机器码上执行56组合，和字段位判定一致。操作2累乘测试确认4；当前未把这段直接加入默认contact模式，因为额外射击动作时序、包来源与脚本生命周期还需接通。旧CrpShockRifle.lua参数_radialDmgPct不能替代这条已找出的native射击引爆路径。

证据 .local/delivery/ranged-implementation-20261029/root/quanta-native/，仍进行中。

## 本次继续后的进展

- 已合入 Arbucep 六种实际投射物逐颗循环；额外多重继续序列，每颗32直击+228范围，SC按raw2.0940001/6。小数多重16轨迹明确近似，独立审查修复共享life curve累加16倍、同发后续lane异常条件不更新、native health batch绕过分层三项真实缺陷。review修复后相关103项通过，native正式重建。
- Battacor每射线独立范围包已由原始count、trace、local dedup、collector、impact完整链验证。单包不再额外乘MS，但N条命中射线有N包。无暴击状态中心条件总伤416×N×C；N1/2/3，C1/2/3 Python/native18例。已合入生产profile，取消原每trigger一包猜测及该旧诊断。
- Zakti/Prime与Kompressa/Prime延迟伤害独立通知已接入准确producer白名单，原35项及合并回归通过。
- Acceltra已合入原生26直击+44武装后爆炸，显式距离<6不爆炸；删除旧wiki35覆盖，其他弹道仍采用现有中心命中假设。
- Mutalist Cernos静态owner cleanup闭环：有效新箭替换旧箭，触发器随owner删除，嵌入后10秒上限；3毒素/0.5秒与5毒素EmbedAttack独立，DamageOnEnter额外一次、periodic初始0。源码接口v4已交引擎实现，不是仅留研究结论。

## Zymos继续追踪

共享metadata记录已证P1先remove再返回；两回调不能对同一条记录都各生成5颗。新verify_projectile_crit_transfer.py执行原始copy helper、weapon/owner/inventory/UpgradeManager路由、资格过滤、modifier bucket和getter共24控制例。Projectile使用保留modifier buckets的FloatUpgradedValue；同样STACKING_MULTIPLY再次查询是加倍bonus，而非自动平方：控制基数.05与bonus1.2，查询一次.11、两次.17。MULTIPLY则逐次相乘。真实爆炸路径0x140f36198调用0x140ede780，再复制538/570并合并既有planCC ADD和CD MULTIPLY，已同样原字节执行。

这尚不证明全游戏的总query次数、后续受害者临时暴击或实际子弹体命中。Lua设置并继承的15b1标记会把子爆炸包分类为DHT_SCRIPT=5；不能据此开放全部head/CO/赋能。已更正元数据描述中误写plan118/11c为crit的说明，实际crit来自538/570与0x140ede780，生产数值未因此改动。

当前仍进行Mandonel来源、Larkspur寿命/碰撞路径、Mutalist生产引擎接入；完整总回归将在当前生产改动冻结后运行。
