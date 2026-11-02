# 机制续查与显赫复审 — 2026-11-02

起点Portable `2b84fd4`，工作区干净。继续固定游戏2026.10.22.13.12原件的来源/脚本/原生消费者审查；实际飞行/覆盖后置。只推Portable源码，不烘焙/Bot/release。测试在既有文件内最少扩展，删改旧错误/重复用例。

| ID | 目标 | 责任 | 状态 |
|---|---|---|---|
| U1 | Mausolon主/副实际RadialDamage多重、CO、通知 | mausolon_consumer | 已完成：每ray一次radial，独立CO系数；consume-before-emission证明副射damageScale5 |
| U2 | Arbucep mushroom/ammo脚本、Nox原型tick/death/source | nox_arbucep_scripts | 完成：蘑菇外部状态、Nox原host3.5期望tick/晚爆、逐实体/native/首发修复 |
| U3 | 远程显赫的技能脚本与source伤害/强度/子包 | exalted_source_audit | Artemis/Dex/Noctua/Glory执行源码确认；Cyte/Lizzie full1.25强度乘区已修 |
| U4 | 显赫导出与战甲→武器→手动/搜索链复审 | root | 35条raw复核；12远程旗标/forced count刷新；Artemis源与7箭、Quiver排除、Lizzie输入门已修 |
| U5 | 可靠修复集成、最小回归与范围清单、远端推送 | root | 最终165回归/104搜索场景通过；文档与Portable提交推送 |

初查：显赫sidecar停留旧导出器，缺Noctua副模式与Lizzie的head-suppression标志、Noctua/Artemis副模式nativeIgnoreFireIterations；来源数值本次完整resolved对比未变。Lizzie当前API把“头部无倍率”误用为强制headshotChance=0，需要分离倍率门与实际头部输入；不自动授予未经验证的所有赋能资格。其余强度/技能覆盖先等实际脚本消费者确认，避免把技能表数字当真实全包金额。


U4补充：真实ForcedProcCount被旧提取遗漏，Neutralizeralt强制冰10已恢复；原机码counter loop代表控制1/10通过。ranged审计工具也已改为先执行显赫技能属性层，避免拿placeholder8/15和普通武器相同地审计而假称覆盖。


## 整体复审追加：显赫实体弹药扣除

raw复核发现Artemis/Glory的UseAmmo0、Regulators/Noctua主射ammoRequirement0，而通用计算仍把零值经`or1`转成每次1发。当前存在空弹匣/装填惩罚的可疑路径；正在核真实消费消费者，不能仅靠无限能量说明掩盖实体弹药逻辑。Dex Pixia和Neutralizer确实有实体弹药，不能把所有显赫一起设为无限弹药。此项列入U4闭环，不以通过前述测试视为已解决。


## 最终已落地范围

U1–U4本批选定的ordinary source修复已完成。显赫复审扩展补掉zero实体弹药误按1扣、Noctua副模式60s门漏失；Glory/Noctua/Regulators exact source适配，不改变Dex/Neutralizer真实弹夹。Mausolon主副CO基数180/72与1500/4500，副射每次consume5先于ray提交，在killcycle单独乘5；原1500/4500保留。

Nox采用稳定活Avatar原host策略：contact30、tick3零半径DOT7（普通hit/crit允许，无CO/Shiver/victimcrit）、自然U[2,4]期望tick0/1/2权重1及tick3权重.5、死亡30在3.1125代表时点。后发不销毁前弹，死去宿主不转移到新目标。terrain-trigger分支不借给活体host。源码明确原件hash与bodyatom；普通Grakata未变。新NOX1、修复首发的ALT3旧核门明确回退。

## 复审后仍未承诺覆盖的部分

| 范围 | 当前处理与后续工作 |
|---|---|
| Mesa启动爬升/中断 | 既有满2.5爬升稳态近似现明确API诊断；需要GunFu触发/恢复时序 |
| Glory副技能引爆 | 不在普通primary射击循环；明确未建模，需技能施放与标记/耗能输入 |
| Artemis Concentrated Arrow / Quiver | Quiver从伤害候选排除；装增幅时明确当前用普通箭策略且不支持增幅爆炸，需单独技能策略 |
| Lizzie charge资源 | 当前无限能量口径保留，Cycles/ConsumesChargesForFire不可当普通实体弹夹，已诊断 |
| 近战显赫 | 23条raw数值复核无漂移；剑气/风刃、施放型21combo点与12倍等独立技能消费者仍待后续近战审计 |
| 额外field与同伴 | Mutalist独立3trigger特殊上下文、Mandonel/Cortege field、FiredUp全局表、Deconstructor回收/在场限制仍在此前清单 |
| 场景与随机性 | 实际LOS/飞行/目标部位、尸体/terrain移动覆盖、随机expiry与跨包概率相关性、玩家hold/cancel/pickup；现有策略不自动等于实机 |

这些是明确剩余合同，不把全部归为只能实测；也不把本轮35显赫入口可调用等同全技能校准。用户既定远程优先不变。


## 本批最终验证与交付

- **165 passed，0失败/错误/跳过**，包含显赫实际auto-build、战甲双形态/Helminth、Nox原目标/首发/独立投射物、Mausolon真实5kill解锁副射、原生事件与原相关回归。一次较广验证发现旧Cortege整字典断言漏上轮已加入的sourceModeKillChargeTrue，已按真实源契约补正；不是删除有效检查。
- **15条实际武器路径/104搜索场景**，Python/native评分完全一致，0回退，输入稳定。所有35显赫目录入口复核：**43可计算模式调用成功，2个Quiver动作明确排除，0错误**。审计工具先执行显赫技能层，避免placeholder输入假覆盖。
- 全项目仅collect **2163**，起点2164，净**−1**；新增测试模块0。显赫新增2个真实合同（Artemis源/7箭/Quiver与Neutralizer强制冰10），其余扩现有用例；删除3个同路径参数校验重复值。Nox替换旧“未加伤害”断言，保持3例，不加新一次性验收脚本。
- 原生核心编译安装成功，只有已有unused警告。ALT_EMBEDDED_LIFECYCLE升3承载首发回调修正；NOX_AVATAR_LIFECYCLE1。旧核心走明确回退。JS语法、改动Python/JSON与diff格式检查通过。

引擎输入`4e7866024df63405`；native SHA256`3db1c25d19c1bd7eef297c3e6216099d3e8a03b090e2bf9a0d4fade7ab324d06`。验证文件[evidence/validation.json](evidence/validation.json)。当前inventory为423条/631显式模式，621可求解（扣除2个Quiver动作），46模式有明确缺口/近似提示，0准备异常；无提示模式仍不等于全部校准。


本批只推Portable源码与审计记录，不烘焙、Bot同步或创建新版发行包；发布缓存仍不是本轮引擎结果。上表剩余显赫特殊分支与其他武器合同继续保留，未声称所有机制已经结束。
