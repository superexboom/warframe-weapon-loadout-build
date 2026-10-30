# Scourge Prime source-owned EmbedAttack

2026-10-30，f47ef0b续轮。EXE SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`，Packages `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`。来源：`/Lotus/Weapons/Tenno/LongGuns/PrimeScourge/PrimeScourgeChargedProjectile` 的独立EmbedAttack50、DT_PHYSICAL .70/.10/.20、SC.050000001、CC.1/CD2，EmbedTime10，默认radius0。

## 消费与时钟

实际Bolto contact先投递300，再在14093a64d经7b8投递55；随后14093a91b/93b→1412a62d0 attach→140c6d800→Bolto+738140f25fa0→140c3ecb0立即调用DoEmbedDamage140297cf0。之后每1秒调度，同delegate去重。半径0走140a58cb0的+628(DOT7)后140ede780复制暴击桶，再到真实host340。并不走正半径附着的790/818，所以无CO/Shiver，也不吃head/victim PunctureCold；SC独立查询365，普通damage/element重读，保留launchcrit。DOT7在该builder显式跳过typed-flat265，不把它当无status/无crit。genericHit/Crit实际AGC消费者仍可接受，不由DOT标签一刀禁用。

旧矛于下一次throw **prefire press** 立即取消futureticks：cap1旧矛418→1402e1be0→1417d6e70按receiver+method删除DoEmbedDamage140297cf0。随后.075–.15s延迟Die不恢复该delegate。Scourge所选state没有chargeTime，PrefireTime0/PRESSED；现有串行refire1s+reload2.2s→下一次press3.2，故旧源跳0/1/2/3；新源3.2起，4.0不会旧跳，新跳4.2。10秒只是上限，不叠每发完整10秒。source token仅取消后续50，不删除已施加到原敌人的status。原宿主死亡，后续包不打新generation。

SpearWeapons OnPriestSpearEmbed/UpdateAttractor脚本处理拾取和HEAD吸弹体，没有独立伤害payload；不将其与真实原生EmbedAttack50混为一项未明脚本伤害。

## 原生量化闭合

初期看到raw35/5/10在模型变成48.4375，随后沿实际victim340继续找到了消费点，不应为追求整数50跳过量化：140d9c670在140d9c698先调用140dc9010，再投递同一包。packet ctor241=0，Embed builder无覆盖，实际路径进入量化。

140dc9010逐20类型clampfraction到15.96875，再`trunc(fraction*32+.5)/32`，不归一化。因此.70/.10/.20→22/32、3/32、6/32，50*(31/32)=48.4375。后半量化CD至32/4095步长，CD2→2.0004884004884005。damagecontroller+7681416a01b0与+90014055edf0最终直接用这些比例乘amount，没有补回31/32损失。原字节代表控制见[evidence/scourge-packet-quantizer.json](evidence/scourge-packet-quantizer.json)。当前本例不处于rounding tie；通用tie规则另行核对，不能把这一证明扩为所有数值边界均已精确。

所以无crit/proc控制下3.1秒直接累计约548.749994，3.3秒约952.187488，源float误差按现有容差；不是555/960。源数据保持50与实际比例，不把量化后的48.4375写死成sourcebase。

实现：已有Scourge importer输出attachedTicks精确合同；manual构建独立包及late-source callback；Python/Rust owned-embed token在每次press替换；旧核心能力不足回退。现有两个测试扩断言验证packet顺序、替换边界与main55致死后无embed50，没有新文件/测试矩阵。


## 通用量化的窄修与CD阶段勘误

一个追加原字节packet控制确认正值half tie向上：.5/32→1/32，1.5/32→2/32，.640625→21/32；Python/Rust原ties-even会令第一、第三项分别偏低。当前导出基础向量未找到exacttie，本回归是原生算术合同，不声称某个现实紫卡恰好命中此点。fraction实现窄改为half-up；当前modified-base向量并不等同原生fraction字段，未把原生0..511上限机械施加到含CO的向量上；现有引擎仍使用binary64算术，不伪称每一步都复刻原生float32。

CD必须保留原生升级桶阶段。早先“最终CD量化”的概括不准确：140dc93d9..93f3解码base+ADD并量化，1411817a0保留STACKING/MULT等桶。原始base2 +VitalSense120%控制：manager查询4.400000095，140ede780复制后仍4.400000095，140dc9010后4.401074886；若把final4.4整体量化会得到4.399511814，明确不符。故只修现有base helper的half-up，**不**把32 clamp加到全局最终CD或量化外部AVATAR_CRIT_DAMAGE。ADD_BASE保留桶的完整特殊来源阶段不从该普通ADD控制泛化。

可交付证据：[fraction/CD tie](evidence/quantizer-tie-control.json)、[base2/VitalSense控制](evidence/quantizer-base-CD-control.json)。一项已有文件内的量化回归同时核原始分数与当前native实际回放；旧核心缺NATIVE_TYPE_QUANTIZATION时回到Python，native mods/replay/sustained三入口一致。
