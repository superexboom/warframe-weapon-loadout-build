# Tenet Plinx 原生接触与嵌入到期消费闭合

2026-10-31，固定客户端2026.10.22.13.12。EXE SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`；Packages SHA256 `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`。本轮重读完整资源及真实父链，未以旧报表代替当前资源。原字节和控制证据在 `.local/delivery/projectile-continuation-20261031/plinx/`，无新增测试模块或一次性脚本。

## 精确路径及独立资格

武器 `/Lotus/Weapons/Corpus/BoardExec/Secondary/CrpBEPlinx/CrpBEPlinxWeapon`；副模式1弹体同目录 `CrpBEPlinxAltFireProj`。它继承 GunProjectile → Engine/Projectile，真实构造函数140fba500安装表142101120；+628=1416373e0，+630=14160c5a0，+738=140c3ecb0，+790=1400dc970，+7b8=140f360f0。原生构造清零da8/dac/15b1，并初始化word c24=2；祖先和源无覆盖。

| 实际包 | CO259 / Shiver261 | 目标Puncture/Cold暴击易伤 | 头部伤害 / 通知 | 普通OnHit/OnCrit |
|---|---|---|---|---|
| 主模式0，hitscan70 | 模式impact来源，保留原additive系数1 | 普通hitscan资格 | impact IgnoreHeadshotBonus0；实际头部几何独立 | 实际投递可通知 |
| 副模式1，物理contact100N | fallback820以已建packet为基数，independent系数1 | 最终PROJECTILE2通过mask | dac0，不抑制实际头部；源body/aim策略仍独立 | 实际投递可通知 |
| 副模式1，原宿主EmbedDeath100N | 不调用790/818/820，普通无ability-parent来源不借victim CO | common c24覆写为2，允许 | converter25c=1抑制普通头部伤害；头部通知仍取实际proxy/bodypart，不由25c推断false | 实际投递可通知 |
| 同爆炸的外围region接收者 | 不借原宿主contact CO | 保留plan4，不借原宿主2 | 不推定头部 | 实际投递可通知 |

主模式RadialOnMissImpact的额外RadialDamage原始baseAmount0、radius0，无可计正伤害径向包；不能因为类名生成免费伤害。普通直接包仍经14140fd17调用1409febe0投递。副模式AttackData100与exclusive EmbedDeath100 / unembedded Explosive500保持分离；Vortex源Amount0不增加伤害。

## 接触callerBase是真正的独立CO

1410e2120构建AttackData时，+628将无覆盖的type置为PROJECTILE2，保留weapon708/source；实际预CO金额写Projectile1700。da8=0让+790的1400dcae7跳过818 impact-source路线，之后1400dccbc读取1700，1400dccef调用weapon820。确切函数14101fdb0保留xmm3，在14101fe03 tail-jump14113e250。不能把相邻unwind14101fcf0误认为此leaf的函数体。

本轮原字节控制从真实da8分支执行到820调用，记录callerBase1000、原packet、原avatar和weapon；对象/owner getter为明确控制输入。它证明全夹N10已建金额作为CO基数，无额外raw100查询。259/261共享该基数，因此普通加伤也放大这两项。生产原先mode1无coProfiles，落到普通additive默认，是真实漏项；新增精确mode1 independent profile，模式0原规则不变。例：普通+100%、CO+100%、N10无暴击时，direct为100*10*2*2=4000，旧路径3000。

## 嵌入到期有额外终止延迟

140c3ecb0设置embedded8e1及c25，保存真实原宿主到15b8。140c3f111..1a4在接受嵌入后排队EmbeddedDie1402e1be0，固定源EmbedTime .80000001。该回调并不立即Die：完整函数取消同delegate后tail-jump14050b8c0；后者以c34去重并排Die140273d98，额外延迟为.075+U24*.075/2^24，即[.075,.15)。本轮执行完整EmbeddedDie得到实际终止delay .0984625965，且c34置1。

所以原来的impact_delay_seconds=.80000001提前了死亡伤害。选择确定性均值总延迟 `.91250001`，真实范围 `[.87500001,.95000001)`；保留抖动近似提示。它只改EmbedDeath伤害到达，不改charge .8、refire等待或battery恢复策略。

死回调140163b27用&15b8调+7b8；common140f362ee..2fa转换plan后在140f36343..34a用c24覆写explicit-host event1bf；原字节控制将初始4改为2。140f365cb/5df投递同一宿主340/348；region2c8独立保留4并排除原宿主，不能双算。Selector c25 true仅选EmbedDeath100而不是500，两者互斥。

141234720在到期重建普通伤害/元素/status，复制发射538/570暴击桶；可复用既有liveSourceDamageAtImpact以更新普通来源，保留发射暴击/多重和静态N。普通通知沿已闭合340→140d9c670→140d40ee0→1402c3940→1412dc050→141375130→1416a6090→14179b840→challenge+d0；OnCrit需要实际critical packet。此授权不等于Enervate Lua分组或头部事件授权。最终type2通过1408ea872的mask0e与普通source predicate(arg1)，独立于25c。

## 入口快照已确认，动态容量仍属模型支持范围

1418abdb3..1418abe3d在进入CHARGE时读取owner2f0当前ammo，写state198；正MaxDamage cap另行min。1405774f0及1405cb04f读取这个快照，计算最终damage scale184。三个原字节控制：入口10→随后容量/弹量5仍scale10；入口5→随后10仍scale5；10→10仍10。因此不能再说原生是否保存入口N未知。

同一1405cb0b8却在每次charge耗弹更新读取owner2f8当前有效容量，结合固定charge duration进行ceil/delta/clamp消费。原生入口伤害快照与每帧当前容量消费为两条不同轴。当前引擎只支持静态修改容量，动态WEAPON_CLIP_MAX仍需实现入口N状态、后续容量变化和装弹预算；继续拒绝该组合是明确支持边界，不是缺少native消费者。建议将旧snapshot-unverified提示改为dynamic-capacity-unsupported，保留当前静态策略。

## 接入与验证

独立修改tools/import_tenet_plinx_cycle.py及既有tests/test_tenet_plinx_runtime.py；root负责生产combat-reference、producer registry以及共享代码。ROOT-HANDOFF.json列出精确组件、registry范围、CO profile和旧提示退休项。导入器现导出radial真实路线/资格/延迟/live普通source，并单列operationalCoProfiles，供root按指定模式merge。一个既有真实Galvanized Shot回归增加普通+100%下的CO增量翻倍断言；原有小容量cycle回归改为等待新的.9125爆炸到达，无新增展开例。

验证只声明离线固定原字节及受影响模型回归；未启动bake、Bot或release。实际proxy/bodypart、飞行与覆盖、动态容量支持、非普通能力parent仍分别保留边界。

聚焦验证：固定源导入通过；原字节控制通过；在内存应用精确待合并合同后既有6例全过。共享生产JSON未合并时新增的原位CO断言如期复现299.9997165而期望599.999433，证明不是仅内部字段比较。root合并后需正常重跑该文件确认实际生产数据。

## 实际可装备来源复核与direct Shiver后续

生产当前合法候选90张：弹夹词条仅破损/普通/Prime Slip Magazine、Tainted Clip、Ice Storm，均为永久静态词条；没有条件WEAPON_CLIP_MAX。1442 MOD /182 Arcane导出无damage ADD_BASE/SET_BASE可给Plinx。固定Packages扫描9314个Upgrade属性记录、10877个Weapon属性记录；197个weapon flat-base匹配全为其他武器Incarnon，Plinx无匹配。Upgrade匹配中的Combo Fury装于Glaive，12秒给LotusPistol容量并运行RefreshClip，是合法跨装备来源，但不属于当前Plinx单武器可选MOD输入；Calendar容量、Decree和非通用Antique描述字段分别列在原始census，不能冒充普通Plinx可装备卡。

因此普通配装不再应显示dynamic-capacity/flat-add未知诊断；保留对手工注入unsupported效果的明确拒绝，可把外部跨装备context列为支持范围。不能拿不可能装备的Incarnon flat-base来制造Plinx普通配置缺口。

独立direct Shiver另有真实缺陷：N10、普通加伤100%、真实Secondary ShiverR5一层Cold、无暴击/异常，当前forced direct2450，但相同callerBase原生应1000*2*(1+.45)=2900。live路径同样遗漏倍率。最小方案为精确mode1打开directTakesVictimStackDamage，进入apply_mods_spec前清forced runtime_chance，保留forced层数；构建st后沿已存在contactShiver字段标记，scale取spec.ordinary_scale（本源independent系数1）。之后fullClip清_co_spec不会清这些字段。现有Python/Rust处理contact_shiver/scale/fixed，无需新增Rust结构。CO.4同时存在时应1000*2*(1+.4+.45)=3700，不是CO乘Shiver。root负责共享core接入，反例及契约已写ROOT-HANDOFF。

## 非窗口面板／静态排名同步修复

最终审查确认optimizer `_score(shotDamage)`→`_metrics`仍直接使用原始apply_mods，不是单纯显示标签。原forced Shiver在raw source100上为245，与native source应290不符；全夹倍率后对应2450/2900。因此已按精确event_profile.directTakesVictimStackDamage且非__radialPart__修正Python及Rust reducer：此来源的forced261不进普通伤害桶，而复用CO tail现有ordinary-scale独立加项。CO与Shiver按同一callerBase相加；不扩到其他武器或Plinx主模式。manual先清forced层数的既有运行时路径保留，防止双算。

新增native capability DIRECT_SOURCE_STACK_DAMAGE1；旧core仅对此exact source prep回退Python。没有新增CoSpec字段或通用模型，原有native tuple可继续表达该独立加项。已有Shiver真实回归扩展raw source390（ordinary2＋CO.5＋Shiver.45）、无CO source290，以及primary70*(2+.5+.45)不变；同例nativeSHADOW运行时direct3900。类型比例量化依旧遵循正常路径，不把.4CO例的raw3700误称实际投递值。静态raw仍是每个packet source100口径，不在此补全夹N/死包/周期；完整操作指标使用manual replay。

源码修正范围damage.py、mods_native.py、native mods.rs/lib.rs；native release核心编译安装成功。聚焦Plinx7例＋既有通用Shiver1例，共8 passed，新增测试文件/展开例均0。


最终重导边界修复：通用`import_co_reference`此前整表重建会擦除已核native mode1。现用明确sourceKind/nativeEvidence保存独立审计模式，并只覆盖普通reference来源；原Plinx source用例追加无I/O合并断言，普通mode0仍可更新。完整集成验收见PLAN及validation-t1-t5.json，前文“待root合并”均为阶段记录。
