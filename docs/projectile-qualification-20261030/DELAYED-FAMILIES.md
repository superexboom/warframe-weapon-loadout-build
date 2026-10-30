# Lenz / Sporothrix delayed packet followthrough

2026-10-30，接续f47ef0b。原EXE `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`，Packages `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`。精确source与mode更新见[evidence/s-delayed-admission.json](evidence/s-delayed-admission.json)。

- Lenz/PrismaLenz为Bolto子类，Sporothrix/CodaSporothrix为普通Projectile。embed common140c3ecb0在15b8保存原contact host，death140163b27把该handle交common7b8；explicitpacket转换后被+c24默认2覆盖，外围scene仍4。
- Lenz immediate cold10来自c25false时ExplosiveAttack；晚爆只选c25true时EmbedDeathAttack，不重复冷10。Sporothrix独立41、Coda48源值保持。
- 普通source secondary explosion不走790/818/820，victimCO predicate排除无ability parent来源。因此无259CO/261Shiver；generic hit/crit与victim Puncture/Cold资格分别确认，仍无额外头部几何。
- **EmbeddedDie不是立即Die**：140c3f111安排source EmbedTime，回调1402e1be0在清delegate后尾跳14050b8c0，再排`.075+U24*.075/2^24`。总时钟Lenz/Prisma `[1.375,1.45)` 均值1.4125；Sporothrix/Coda约`[.97499998,1.04999998)` 均值1.01249998。原1.3/.9只是嵌入timer，缺后续死亡调度。
- 默认原目标中心策略保留；原host死亡后晚包不转移下一计分目标。late ordinary damage/element/status在落地重读，源CC/CD和发射数量保留。飞行与世界附着旁观覆盖不在该合同内。

三个有限原字节控制分别验证保存host、EmbedTime调度、完整EmbeddedDie追加死亡延迟。工具沿用已有native_code与Unicorn载入器；未新增一次性harness或测试模块。现有Lenz/Sporothrix两个代表用例替换旧unadmitted断言，验证总时钟、资格和实际通知，不增加参数展开数。
