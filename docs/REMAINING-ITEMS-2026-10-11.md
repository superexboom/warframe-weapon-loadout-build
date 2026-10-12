# 遗留项收尾与 WFSim 同步（2026-10-11）

范围：除实测之外 Portable 还能做的遗留项，以及 WFSim 上游这一周的机制改动。
客户端数据仍是 10.08 的 Packages.bin（本机缓存 10.08 00:57 之后没有更新）。

## 一、WFSim 同步

上次对照的源码是 `7399c9e4`（10.04），这次是 `c993d6ffc`（10.11），中间 482 个提交，
涉及引擎和武器数据的约 30 个。结论：**没有需要接入的新机制**；Melee Duplicate 的口径参考了它。

WFSim 这一轮改成了与原生数据一致（本地早已如此，以后对照时不再是差异）：

- Bubonico / Coda Bubonico 电池空仓等待、Enkaus 副火耗弹 15、Javlok 0.3 秒自动蓄力、Prisma Lenz 0.8 秒、
  Mutalist Cernos 毒云每跳强制毒素、Kuva Hind / Kuva Kraken 连发间隔、Fulmin / Fulmin Prime / Haalvu 副形态的电池；
- Kuva Zarr / Kuva Bramma 子母弹也吃赋能元素；
- 毒囊双枪 3B（神经毒素）加的是毒素，狂乱的毒素只在狂乱期间生效；
- 灵化每一档都视为已装，未指定的取第一项。

与单目标紫卡分析无关、不接入的：穿透拆成表面米数和无限穿透、光束链不吃多重、帝国神殿 / 冰缚的敌人强化、
Tenet Exec 震地的三段冲击波（多目标）、优化器搜索流程、志愿计算与网站。WFSim 仍然不支持 Zaw，
也不处理 `MultiShotProjectileType`。

## 二、本轮完成

### 1. Zaw

**部件路径。** `zaws.json` 是按维基冻结的，路径大多是编的：剑刃的 `Head/...`、握把 `HandleSeven` / `HandleEight` /
`PlagueAkwinHandle`、连接器 `BalanceOne`、`BalanceCritOne` 等在客户端里都不存在；`HandleOne`–`HandleSix` 还是按名字的字母顺序套上去的
（例：Peye 写成 HandleSix，客户端的 HandleSix 是 Kroostra）。数值与名称是对的，只是路径错了。

`tools/refresh_modular_dispositions.py` 现在把每个部件对到客户端实体：剑刃按 Tip 路径，握把按握持类型 + 攻速 + 伤害加成，
连接器按攻速 / 伤害 / 暴击 / 触发。每个都唯一匹配，维基数值全部与客户端一致，然后改写成客户端路径，旧路径留作 `legacyPath`。
用旧路径保存的装配按剑刃识别后整组按旧路径解析，因此旧的 HandleSix 仍是 Peye，不会被当成 Kroostra。

|握把|客户端|中文本地化|握持|攻速|伤害加成|
|---|---|---|---|---|---|
|Peye|ModularMelee01/Handle/HandleOne|轻短握柄|单手|1.000|−4|
|Laka|HandleTwo|短握柄|单手|0.917|0|
|Kwath|HandleThree|重短握柄|单手|0.850|+14|
|Seekalla|HandleFour|轻长握柄|双手|1.000|−4|
|Jayap|HandleFive|长握柄|双手|0.917|0|
|Kroostra|HandleSix|重长握柄|双手|0.850|+14|
|Korb|ModularMelee02/Handle/HandleNine|特重短握柄|单手|0.783|+28|
|Shtung|ModularMelee02/Handle/HandleTen|特重长握柄|双手|0.783|+28|
|Plague Akwin|ModularMeleeInfested/Handles/InfestedHandleOne|异变轻短握柄|单手|0.950|−2|
|Plague Bokwin|ModularMeleeInfested/Handles/InfestedHandleTwo|异变重长握柄|双手|0.883|+7|

连接器是 `Balance/BalanceSpeed…`（Jai 系）与 `Balance/BalanceDamage…`（Ruhang 系），后缀 `CritI/II`、`StatusI/II` 对应 Vargeet / Ekwana 与 I / II 级。

**双手伤害系数。** 客户端剑刃的 `TwoHanded.damageAttenuation`，即维基「双手 Zaw 伤害再乘一个系数」那张表：
长柄 Cyath 1.08、Dehtat 1.09、Kronsh 1.07、Mewan 1.09、Plague Kripath 1.08，锤 Rabvee 1.08，重剑 Dokrahm 0.93，
棍 Plague Keewar 0.85，其余 1.00。之前没有乘。

**逐次命中。** 剑刃的单手 / 双手块各自给出近战树和震地（重击震地倍率 3.5–5，长柄与锤带 AxeSlam）。
`melee-mechanics.json` 新增 `zaws` 一节，`melee_sequence.weapon_row` 按装配的剑刃和单双手取用。
此前 Zaw 没有近战树，一直落回旧的架势倍率模型。双手 Rabvee（锤）默认走垂直子弹跳震地，其余走 A。

**最佳组合重算**（`tools/build_modular_winners.py --family zaw`，新增按家族合并写回，组合枪部分不变；10.6 分钟）：

|剑刃|握把 / 连接器|无紫卡 KPM|
|---|---|---|
|Dokrahm|Seekalla / Vargeet Jai II|8.55|
|Plague Kripath|Seekalla / Ekwana Jai II|7.31|
|Plague Keewar|Peye / Vargeet II Jai|6.37|
|Ooltha|Peye / Vargeet Jai II|5.99|
|Mewan|Peye / Vargeet Jai II|5.65|
|Sepfahn|Peye / Vargeet Jai II|4.95|
|Dehtat|Seekalla / Vargeet Jai II|4.54|
|Kronsh|Seekalla / Vargeet Jai II|3.87|
|Cyath|Seekalla / Vargeet Jai II|3.76|
|Rabvee|Peye / Vargeet Jai II|2.98|
|Balla|Seekalla / Ekwana Jai II|1.95|

Plague Keewar 双手系数 0.85，改选单手（镰刀）；Rabvee 双手锤的震地循环不如单手砍刀走 A。

### 2. Dark Split-Sword

客户端里这是一把混合武器（`LotusHybridWeapon.WeaponTypes`），两个形态是独立实体：`DarkSwordDaggerSingle`（重剑）和
`DarkSwordDaggerDuals`（双剑）。导入器把它们加进 `melee-mechanics.json`（`hybrids` 一节），两个形态记录通过 `meleePath`
走各自的近战树、震地和连击数据，不再落回旧模型。原生伤害、暴击、触发与原先按维基手填的一致；攻速改为原生 55 / 60 与 70 / 60
（原手填 0.917 / 1.17）。

### 3. 拳套 / 格斗类连段

武器 `Slams[]` 里半径为 0 的条目（PunchEffect / KickEffect、ShieldBashEffect、GlaiveCatchEffect）只是特效挂点，碰不到任何身体，
不再算作范围命中。连段与维基吻合 185 → 188 套（Brutal Tide 两套、Grim Fury 一套）。枪刃类的射击动作维持「攻击本身一次命中 +
射击爆炸一次」，维基的枪刃连段总倍率正是这样数的。

### 4. Zymos

客户端弹体只在头部嵌入（`ValidEmbedPart: HEAD`），`EmbedTime` 1.1 秒后打出 `EmbedDeathAttack`：953 毒素、50% 触发。
导出里本来就有这段，但回放没有计入。新工具 `tools/import_head_embed_bursts.py` 把它作为带 `headOnly` 的第二段范围伤害写进
`combat-reference.json`，回放按每发的爆头概率计入。击杀后才放出的孢子由 Lua 脚本生成（客户端缓存里没有），单目标下目标已死，不计。
无卡 Lv170 钢铁：0% 爆头不变，50% 爆头 0.0075 → 0.056 KPM（维基同样把爆头爆发当作这把枪的主要伤害）。

### 5. 多重弹体副本（`MultiShotProjectileType`）

扫了全部武器：绝大多数副本与主弹体数值相同。地面模式 Grattler 的副本与主弹体一致，不变；Kuva Grattler 的副本暴击 / 触发 25%
（主弹体 27%），按 Latron Prime 的 `multishotCopy` 写入，只在有多重射击时生效。

### 6. 近战赋能

- **Melee Duplicate** 接入事件解算：能暴击的近战命中按「黄色（一级）暴击概率 × 触发率」重放一次，暴击和异常重新判定，
  不增加连击数；触发率 0–5 级 25 / 40 / 55 / 70 / 85 / 100%（本地化文本）。Nikana Prime 测试配装 5 级 +15%，带嗜血 +48%
  （嗜血把暴击率推到 1–2 之间，黄色暴击占比变化）。
- Arcane Fury、Arcane Strike 原本就生效（同一配装 +17% / +63%）。
- Melee Animosity、Melee Crescendo 只作用于重击 / 处决，现有路线里没有这两种攻击，结果为 0 属实。
- Melee Influence / Vortex / Afflictions / Fortification 是多目标或生存效果，不计。

### 7. 缓存

引擎指纹之前没有包含 `melee_sequence.py`、`melee-mechanics.json`、`kitguns.json`、`zaws.json`，改这些文件不会让静态缓存失效；
现已补上。`ANALYSIS_STATICS_CACHE_VERSION` 25 → 26。

### 8. 前端

Rabbit 分享码的目录只收了组合枪部件，Zaw 装配的分享码解不回来（报「目录缺少短 ID」）；已补上 Zaw 部件，编码再解码一致。

## 三、仍需实测或需要你决定

实测：

- 连击倍率每档、震地俯冲速度和子弹跳上升段、重击蓄力（此前已列）；
- 18 套与维基不一致的连段（主要是格斗、枪刃、刺刀类）；
- Tenet Detron：客户端的多重弹体副本指向普通 Detron 的弹体（暴击 4% / 1.5 倍、触发 90%）。如果真的生效，10 发里有 9 发是它，
  与维基和玩家体感都对不上，未接入；
- Kulstar 子母弹暴击（原生 0.1 / 2.0，维基 0.17 / 2.3）；
- 滑行攻击一轮的时长（滑行位移不在数据里）。

需要决定：

- 是否加「滑行攻击」路线（只在 Portable 可选，依赖上面的滑行时长假设）；
- 是否接入 Tennokai（重击穿插在连段里，与「重击只按初始连击、不做攒连击再重击」的决定相关）。

其他：

- 维护者：服务器上的 `v2_wm_riven_att.json` 仍有 15 个 0.45 应为 45；
- Bot：本轮改了引擎和 Zaw 最佳组合，Bot 需要重新同步并烘焙（约 2.5 小时）才生效。

## 四、验证

- `tests/test_remaining_20261011.py` 8 项：Zaw 路径与旧装配、双手系数、Zaw 近战树与路线、Dark Split-Sword 形态、半径 0 特效、
  Zymos 爆头爆发、Melee Duplicate、Kuva Grattler 副本。
- `python tools/check_melee_stances.py`：总倍率与击数同时吻合 188 / 206。
- 本地服务：Plague Kripath + Seekalla + Ekwana Jai II 的紫卡分析走逐次命中（长柄「回转尖峰」格挡连段），Zaw 装配分享码往返一致。
