# 异融西诺斯持续源属性刷新（2026-10-31）

起点f6024c6。保留游戏构建2026.10.22.13.12，EXE SHA256 eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d，Packages SHA256 00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06。

## 原因与原生证据

原模型将箭体5毒附着包与独立3毒DamageTrigger转换为source-owned-fields后，在每跳直接使用同一个发射快照；之前修正的普通lingering刷新并未覆盖该分支。故发射时有Merciless、持续场存续中失去Merciless时，旧场仍错误保留伤害。

箭体真实来源`/Lotus/Weapons/Infested/Bow/InfCernosBow/ChargeInfCernosArrowProjectile`为Bolto，EmbedAttack5、radius2.5。其DoEmbedDamage140297cf0→140a58cb0每跳建新包；原始通用消费者详情见FAMILY-INVENTORY末节及embed-fields/NOTES。普通damage/element/status按当前来源查询，Projectile538/570暴击桶仍保留发射时值。

独立场`/Lotus/Weapons/Infested/Bow/InfCernosBow/InfCernosSwarmDamageTrigger`直接继承DamageTrigger；脚本保存原weapon来源，AttackData3毒、SC1与强制毒不取箭体参数。每次140e5f490在140e5ff7b重新问weapon+aa0当前DamageUpgradeTypes、140e5ffbb→1401413d0读取基础伤害升级，并在140e60081..c5读取当前元素次序/模式→1403a6ea0。这些在伤害函数内逐跳执行，没有发射期快照。原反汇编`.local/delivery/projectile-qualification-20261030/zymos-completion/140e5f490.asm`及原先trigger-source-reproduction保持可复核；本轮再提取当前resolved来源保存至`.local/delivery/projectile-continuation-20261031/mutalist/sources.json`。

## 落地与验证范围

Python/Rust的source-owned-field事件改为调用各独立包的当前源解析器；缓存按实际buff层数/当前victim状态计数复用。回填箭体保留的CC/CD，独立毒雾仍是自己SC1/CC0，未擅自授予头部、CO或新赋能通知。native SOURCE_OWNED_FIELDS升2，旧核心回退Python。

原snapshot-only用例替换为真实Primary Merciless过期回归：首发带1层，.5秒失去；0秒附着/毒雾有增益，.5/1秒毒雾与1秒附着读取当前无增益，Python/Rust SHADOW一致。源IPS比例量化为29/32、2/32、2/32，预期独立计算该已知量化而非把410面板直接当实际总和。相同文件精简邻接时间重复值、重复shadow网格和元素别名矩阵；没有新增测试文件。

剩余独立缺口：附着5的+818 CO callerBase属于当前weapon charged/normal模板查询，普通/蓄力不同源的时点尚未闭合，现有数值仍为reference来源；本修复不将其升为原生确认。独立DamageTrigger的特殊source升级、最终hit/crit资格及同帧场替换仍分别待查；场景覆盖/LOS是输入。上述缺口不影响已证明的普通源属性逐跳刷新。


## 当前charge源查询与最小连续操作策略

随后已闭合上述attached5的CO缺口：+818→141300a00每跳重新问weapon498→fire190/2a0→140e496d0/141809340。实际weapon760→当前charged-state2b0读取elapsed/duration；state14或ratio约1选410，否则normal205。完整原字节7个getter控制与4个transition控制证实14→1保留full elapsed，1→13、14→0、1→7清零。因此既不能固定82，也不能说“发射瞬间必然变41”。

当前求解采用显式`full-charge-contact-before-next-action`连续操作：满蓄shot的理想即时contact/initial field先查询410；处理完同批初始包后进入下一次draw/reload/idle，后续旧owner tick查询205。下次满蓄发射替换owner并使新initial tick再查410。精确时刻与新shot同帧的旧tick沿现有事件队列顺序，保留动作离散近似；没有把该策略称为任意真实飞行、任意停射hold都成立。真实flight/手动hold可在未来扩展为显式当前phase输入。

实现只增加source-owned tick的initial布尔及精确component的currentSourceCoFraction（charged82/normal41），未建无关通用状态机。已有live callback读取当前层数并选择源基数；attached5独立开放generic通知、CO/Shiver，RADIAL4仍不吃Puncture/Cold；独立trigger3仍noCO。SOURCE_OWNED_FIELDS升3，旧核回退。替换既有fractional-CO用例，检查5+.5*410=210、5+.5*205=107.5以及半个状态56.25，并验证实际native与原目标事件数。

原证据见`.local/delivery/projectile-continuation-20261031/mutalist/NOTES-CO.md`；提取控件保存为[evidence/mutalist-source-query-controls.json](evidence/mutalist-source-query-controls.json)。该节覆盖前文“callerBase尚未闭合”的阶段状态，独立trigger3特殊升级和最终通知仍未借附着包结论扩用。
