# 多部件弹丸补全 — 2026-09-27

本轮落地 Ogris、Lenz、Prisma Lenz、Stahlta 蓄力模式的弹丸组件，并额外抽测 Supra Vandal、Synapse、Baza Prime、Akstiletto Prime 的自动配装。原始包固定为 `2026.09.22.16.46`；参考 source 固定 `bb1dcb69b7045b62b8a858dad7550d4458624719`、release `39047c9ca078`，未改动参考工程。

## 已落地

- 共用事件管线支持按明确 fireMode 选择 profile，以及同一弹丸的多个独立范围事件；自动搜索、生产手动回放、MOD 贡献共用此路径。
- Ogris：保留 100 点直击，补 600 点爆炸；未加入未触发的 500 点 EmbedDeathAttack。
- Lenz / Prisma Lenz：保留 50 / 56 点直击；补 10 点冰冻初爆及强制冰冻，再于 1.3 秒后发生 660 / 740 点爆炸。每部分分别读取自然触发、强制触发和范围身份；初爆击杀后延迟部件不能跳到下一代目标。
- Stahlta：仅模式 1 增加 0.36 秒后发生的 1200 点辐射爆炸；模式 0 不继承该爆炸。
- Ogris 和 Stahlta 蓄力分别读取原始 0.3 / 1.6 秒，再加射速间隔；蓄力按原生 WEAPON_FIRE_RATE 修正。时间相加的时序来自冻结参考的 `seconds_to_next_shot`，不是游戏实测。
- Prisma Lenz 改用原生 0.8 秒拉弓，参考 YAML 为 1.2 秒。所有原始字段、继承文件哈希和冲突值已保存。
- 普通弹匣按 f32 结果取整，至少 1 发；不把零头累积成额外完整子弹。弹药消耗效率仍允许小数，换弹后的小数欠额规则保持独立；灵化固定池不应用普通弹匣修正。
- 全量审计合并器纠正成功项误计 `engineFailures` 的错误。历史 409 武器 / 614 次尝试的正确拆分是 **601 成功回放、11 结构缺口、2 个真实生成失败（Talons）**。本轮没有把 Talons 的失败隐藏成结构成功。
- 对比工具区分 WFSim 的 `mode` 和 YAML `form`：默认使用 `base`，Stahlta 模式 1 使用主武器 ID 加 `alternate`。响应必须返回同一武器，Stahlta alternate 还须实际执行 `charged`；不接受参考静默回退。

提取器源码早已修正 ChargeTime 大小写，但当前冻结导出仍是 null；本轮通过核验 sidecar 补回这四把的实际时间，没有全量重导出其他数据。弹药转换和穿透诊断保留，不以删除警告充当机制实现。

## 回归结果

- 最终相关回归：**295 passed，3 subtests passed**，13.77 秒。日志见 `regression.txt`。
- 本轮前段较大回归：146 passed，7 subtests passed，794.02 秒；它早于本轮最后的弹匣取整修改，不冒充最终全套回归。
- 8 把武器共 11 个模式执行过完整自动搜索。对蓄力/弹匣修正影响的 Ogris、Lenz、Prisma Lenz、Stahlta、Baza Prime 重搜。
- 最终 11/11：保存的自动分数、当前搜索事件评分、生产手动回放一致；详见 `local-final-parity.json`。这只证明共享路径一致，不证明配装已是全局最优或与游戏一致。
- 原生导入器在当前输入上重复执行结果相同，未更新无关 profile。

## 固定配装的跨引擎结果

每项均为实际 8 槽自动配装；卡序、精确内部 path/rank、赋能、目标等级/钢铁、10 米距离和瞄准条件保持一致。参考 30 秒、1000 runs、固定 seed。两个未映射的额外模式不替换成普通开火：Supra Vandal mode 1、Akstiletto Prime mode 1。

| 武器 / 模式 | 本地 KPM | WFSim KPM | 本地相对差 |
|---|---:|---:|---:|
| Ogris mode 0 | 0.8224 | 0.6751 | +21.82% |
| Lenz mode 0 | 0.8876 | 0.6410 | +38.48% |
| Prisma Lenz mode 0 | 1.4572 | 0.8281 | +75.97% |
| Stahlta mode 0 | 2.1394 | 1.7870 | +19.72% |
| Stahlta mode 1 | 3.3695 | 1.3938 | +141.74% |
| Supra Vandal mode 0 | 3.5786 | 1.4027 | +155.12% |
| Synapse mode 0 | 5.0144 | 5.4453 | -7.91% |
| Akstiletto Prime mode 0 | 2.1175 | 1.4537 | +45.66% |
| Baza Prime mode 0 | 2.6027 | 1.7488 | +48.83% |

上述差距仍未验收。Prisma Lenz 正确采用原生 0.8 秒后差距反而变大，因此不能把“更接近参考”当作唯一修复依据。Ogris 在同配装补蓄力后由 +64.18% 降到 +21.82%；Lenz 在整数弹匣并重新配卡后由 +72.14% 降到 +38.48%，两次阶段不是同一配装的单变量实验。

## 差异定位与未尽事项

`ablations-summary.json` 保存同一配装仅改变身体/头部、移除 Acuity、移除散布惩罚卡的 20 项实验。它们是消融试验，不是重新自动搜索的最优配装。

- Baza Prime 移除 Heavy Caliber 后相差 +1.05%；Akstiletto Prime 移除 Magnum Force 后相差 +2.03%。原配装仍分别约 +48.83% / +45.66%。本地虽读出散布倍率，仍按发射弹丸均命中处理；自动搜索也因此可能高估这类卡，命中几何是下一轮优先级。
- Stahlta alternate 移除 Heavy Caliber 后仍差 +42.42%。它还涉及每颗弹丸是否重复爆炸、命中后的延迟、装填时间等；不能将全部差值归于散布。
- Supra Vandal 移除 Heavy Caliber 后仍差 +72.91%，需要继续按触发与伤害来源拆解。
- Lenz 系列本地新增初爆与延迟，参考声明未计初爆；参考还把 radial multishot 关闭。本地按原生每颗弹丸产生事件处理，但当前缺少真实游戏的多重空间落点实验，保留证据冲突，不将其写成参考已确认错误。
- Talons 仍有纯范围攻击导出缺失与继承枪托近战误入模式列表的问题；原全量报告的两项真实失败保持打开。
- Quanta / Mutalist Quanta / Stug 的运行时转换、Simulor 合球曲线，以及未建模灵化条件仍未关闭。
- 本轮没有重跑 409 武器全量、所有赋能或全部灵化验收；紫卡分析反哺仍待主体机制稳定。

证据目录：`docs/evidence/multipart-round-20260927/`。原始导入复现：

```powershell
python tools/import_native_radial_profiles.py --packages C:/Users/SuperExboom/Documents/WF_Rever/wf-arsenal/data/raw/2026.09.22.16.46/packages --wfsim .local/wfsim-source-20260927 --evidence .local/reports/new-native-radial-import.json
```

自动配装复现：

```powershell
python tools/audit_nonmelee_catalog.py --weapons Ogris Lenz "Prisma Lenz" Stahlta "Supra Vandal" Synapse "Baza Prime" "Akstiletto Prime" --distance 10 --output .local/reports/new-multipart-auto
```

消融实验复现：

```powershell
python tools/probe_multipart_ablations.py --wfsim .local/wfsim-source-20260927 --builds docs/evidence/multipart-round-20260927/automatic-builds.json --names "Lenz mode 0" "Stahlta mode 1" "Supra Vandal mode 0" "Baza Prime mode 0" "Akstiletto Prime mode 0" --runs 1000 --output .local/reports/new-multipart-ablations
```
