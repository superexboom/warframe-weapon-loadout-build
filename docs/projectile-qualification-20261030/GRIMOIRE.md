# Grimoire 副射击：源消费者、条件覆盖与回放合同

2026-10-30；本轮基点 f47ef0b。原始 EXE SHA256 `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`，Packages SHA256 `00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06`。武器 `/Lotus/Weapons/Tenno/Grimoire/TnGrimoire` mode1，弹体 `/Lotus/Weapons/Tenno/Grimoire/TnGrimoireAltProj` 原始属性 SHA256 `a384ff36bc51b96972d82f317e6258ff1f7bf52b0f1754b082437cdb979401ac`。原始字节、完整函数提取、源继承和3个有限执行控制保存在 `.local/delivery/projectile-followthrough-20261030/grimoire/`；本文件保留可随仓库交付的关键证明，不能只凭旧导出350面板恢复接触伤害。

## 350接触声明没有实际递交

PlayerChainingProjectile constructor `141bddda0` 调用base constructor后在 `141bdddb7..dc9` 安装真实vtable `1423910d0`。该表 +578=`1410e2120`、+628=`1416373e0`、**+790=`1400bb680`，原始字节 `c2 00 00`，即 `ret 0`**。

物理碰撞 `1410e2bab..2bf0` 构建AttackData350，`1410e2df5`复制投射物暴击桶；实际递交点只有virtual+790（`1410e310c` 或 `1410e33eb`），所以到达空hook。完整碰撞函数没有独立avatar+340/+348递交。源未开启ExplodeOnImpact，base ctor16d0=0，碰撞也不额外产生250爆炸。350是周期链伤害的源基数，**不是可以另计一次的直击350**。

物理prior-hit记录+b58/+b60由 `1416c661f..6653` 在调用+578前检查；chain每轮去重列表是独立+1798。+750=`140e7ad20`能清理物理记录，但普通+b52默认0，没有每秒自动重打原目标的含义。即使外部明确清理物理记录，也不能让空+790产生350伤害。

## 链式280的实际消费者与源属性时点

| 项目 | 已闭合的普通player weapon合同 |
|---|---|
| 包金额／类型 | `140d7fdce`以默认PROJECTILE2，`140d7fde8`经+628构建AttackData350；`141693108..3123`对完整复制包乘 `.80000001` 一次。递归接收原始包，不是 `.8^depth` |
| 接收者 | `14169313a..162`写入当前selected target到packet+170；`141693283→140907cb0`直接送该avatar+340或+348，不调用projectile+790 |
| 来源 | +628通过`140aa9240`保留实际source weapon到packet+270，mode来自投射物+d91，creator+738保留；不随计分新目标或玩家切模式改写 |
| CO／Shiver | 链不走weapon818/820。victim modifier `14111fd11→141baa200(weapon,0)`在普通无ability parent时由+970空parent返回false，不执行`14111fd86` CO core；因此259／261均不适用 |
| 普通伤害／元素／status | 每轮重新+628：当前253、358／359、265、365／281；复用R2已有的current source阶段证明 |
| 暴击／上下文 | `140d7ff5c..82→140cbc9b0`复制投射物保留538／570桶。FE0／FE4／FE8／FF8和818仍是source／owner refresh通道维护的context缓存；不能每轮重查普通244／248 |
| 事件 | 完整selected-avatar340／348递交支持实际非零伤害的generic OnHit／OnCrit，须在原victim retirement前通知。type2独立允许普通source的Puncture／Cold victim crit；不由此授予原始瞄准head事件或任意Enervate脚本分组 |
| 强制异常 | AttackData强制PT_ELECTROCUTION随每个实际链包保留；独立expiry250没有该声明 |

selected-avatar dispatcher已执行两个代表控制，分别确实递交340／348各一次，第三控制执行实际表的空+790。目标弱引用、avatar ancestry和外部伤害回调是明确提供的控制输入；没有把fixture当游戏世界命中概率。

## 单orb、时钟及可选择的覆盖策略

源 `IgnoreFireIterations1/fireIterations1`使物理orb始终一枚。当前weapon+6e0=`140e5e790` query276 WEAPON_FIRE_ITERATIONS，把raw3变为共享target预算；nonnegative后truncate。root cap默认1，递归深度／MaxArcs与共享预算不能让同一个仍存活NPC在同一轮重复受伤。极低MS可使预算floor<1而无链包；高MS不把单目标280或expiry250乘倍。

剩余链时钟1774初值0；有eligible候选时首次update可立即攻击，后续1秒。每轮清除+1798，允许下一轮再选同一NPC。无候选时不凭空强制等待1秒。MaxLife6属于launch时钟；DieOfOldAge由639只安排一次，先执行classDie后独立+7b8输出250。重复手动调用DieOfOldAge仍会输出更多radial，不能只用Die guard声称调度唯一。

实现采用显式 `combatState.grimoireStrategy='single-occupant'`：

- `grimoireCoverageSeconds`有限0..6，省略默认3；将第一次eligible update近似到launch t0，取每秒 `t < coverage` 且 `t < 6`。这是“符合范围／遮挡条件的时间窗口”，不是弹体停留；原生min speed1.75保持明确。
- 所有链包绑定本发原始victim generation。原目标死亡，后续链／expiry不能自动转给新的计分敌人。
- `grimoireExpiryDistance`可选有限0..6；填写即明确原目标在launch+6仍处于该爆心距离，root按当前 `6*explosion_radius_multiplier` 和 `.80000001` falloff计算。留空不计expiry。
- expiry为实际scene区域type4，不借+c24明确contact victim的type2。普通source无CO／Shiver、无Puncture／Cold victim crit；可按实际递交通知generic hit／crit。
- 未选择覆盖时，副射击仍服从原生45秒可用门，但没有350接触伤害、没有未指定链／expiry伤害；提示“选择范围策略以评估副射击”。不得用面板350 fallback。

满6秒、爆心0、同一高HP原目标的纯伤害控制为 `6*280+250=1930`（浮点源`.80000001`有正常微差），不是六个免费受害者；有限窗口与原目标死亡会截断。实际飞行/碰撞、LOS、候选对象和身体部位分配属于已明确的覆盖输入，金额／源consumer／CO／时钟不再归为“等实测未知”。

## 接口与持久化

`vendor/wfarsenal/projectile_events.py::grimoire_strategy`对精确武器＋选中mode1＋source350＋单orb原生标记＋ammo1返回合同；其余identity不匹配返回None。`__selectedFireMode__`支持optimizer选中后的单mode记录。默认合同 `noDirectContact=True,parts=[]`；opt-in才生成各part，chain保留源damage350与`damageMultiplier=.80000001`，expiry保留250和`__expiryDistance`。元数据携带客户端／Packages／raw source hashes。

Scenario正规化把off及未选策略的coverage／expiry移除；选中策略省略coverage正规化为3，因此默认与显式off缓存一致，省略和显式3一致，选中策略与默认缓存不同。UI仅精确Grimoire副模式显示控件，默认coverage输入3但未选策略不发送，expiry留空。通用配置／分享使用原有combatState管线。

导入器 `tools/import_grimoire_static_contract.py`升级schema2 source contract；输出`sourceContracts`供受控合并，`weapons={}`保持generic merger不自动添加伤害。旧pending结构保留来源兼容，并标明contact `damageSubmitted=False`；旧5条静态未闭合警告替换为明确coverage诊断。

## 有限验证

现有 `tests/test_grimoire_fire_gate_20261030.py`共3例，没有新增模块／参数展开；结合旧source-contract模块共 **21 passed**。实际检查包括：

- 默认350零伤且45秒门不被射速／MS缩短；canonical state/cache身份。
- exact／optimizer selected-mode identity一致、source drift拒绝、parts按各自nativeField／route。
- 当前native `GRIMOIRE_SELECTED_COVERAGE=1`的真实SHADOW调用计数增长；1930无350、7次hit／1次fire／无head、致死后只1次hit且不转给successor、预算0无伤害／hit。
- 真实Secondary Merciless与Galvanized Crosshairs初始层数在.5秒到期，后续链伤害刷新但保留发射CC；Python与native compact回放一致。
- 同一selected coverage的manual／optimizer评估一致；默认未选覆盖两条KPM均0。

`node --check frontend/app.js`和相关Python编译通过。本次未做浏览器视觉交互、实机轨迹、全场景命中率、烘焙、发布或Bot部署；这些不影响上述静态普通source合同。


静态指标入口也已跟随修正：Arsenal source350可作为源面板展示，但不再流入shotDamage/burst/sustained/mod-gains排序。单发定义为所选原目标上的一颗orb全部直接包，burst/attack除以6秒，持续除以45秒；需要异常时同一原目标回放结算至本周期。未选覆盖直接返回0而不做无意义45秒回放。KPM/window指标继续读取benchmark，不被静态字典缺项变成0；bounded projectile preview不能再覆盖真实指标。原功能第3例包含API与优化器检查，无新增测试例。
