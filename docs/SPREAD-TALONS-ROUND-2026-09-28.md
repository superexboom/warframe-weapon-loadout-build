# 散布、Talons 与自动配装回归（2026-09-28）

## 已落地

- [x] Talons 主攻击修复为嵌入后的 250 爆炸，保留空中 120 的原生数据，不重复计伤；强制穿刺进入事件流。继承枪托近战显式标为非远程模式。
- [x] 七把核实过的基础单体武器接入瞄准/腰射散布：Baza Prime、Akstiletto Prime、Supra Vandal、Karak Wraith、Viper Wraith、Tiberon、Bolto。
- [x] 命中概率作用于直伤、状态次数、命中/爆头/暴击条件；持续伤害单次种子不重复乘命中率。射击和装填仍消耗实际弹药。
- [x] Encumber 按逐弹丸命中机会聚合一次成功概率。自动评分、手动复算和 MOD 移除贡献使用同一事件路径。
- [x] 补入 Tiberon 原生三连发 NumShots=3 / BurstDelay=0.059999999 秒，沿用已有射速缩放和装填逻辑。
- [x] 中文回放提示展示中心距离、初始期望命中率、模型假设；重新导入不会丢失本轮配置。
- [x] 八把完整自动配装回放、固定参考对照、同配装消融和定向回归。

## 固定输入对照

基础提交 7f5a93d，验证时含本轮工作区补丁。原生 build 2026.09.22.16.46。参考源码固定 bb1dcb69b7045b62b8a858dad7550d4458624719；WASM 与源码发布标识不完全一致，实际使用发布包执行，不假定二者逐字对应。source/release/WASM SHA、完整 MOD path/rank/卡序/辅助槽、目标请求保存于 reference-comparison.json。

30 秒、1000 次、seed=12648430，9999 级钢铁凶魂百夫长，瞄准、指定爆头率 100%、中心距 10 米。以下为最终重新自动搜索的配装，不与旧配装混称单变量改进。

| 武器 | 本地 KPM | WFSim KPM | 相对差 |
|---|---:|---:|---:|
| Supra Vandal mode 0 | 2.0814 | 2.0499 | +1.54% |
| Karak Wraith mode 0 | 1.7192 | 1.6896 | +1.75% |
| Viper Wraith mode 0 | 1.5850 | 1.5798 | +0.33% |
| Tiberon mode 0 | 2.2784 | 2.2327 | +2.05% |
| Baza Prime mode 0 | 2.6257 | 2.5211 | +4.15% |
| Bolto mode 0 | 1.2369 | 1.2310 | +0.47% |
| Akstiletto Prime mode 0 | 2.8351 | 2.7521 | +3.02% |
| Talons mode 0 | 0.5637 | 0.0000 | 不可比：参考射程截断 |

八把主模式全部自动/手动匹配。另有四个继承枪托近战模式被显式排除，不计为远程解算成功，也不伪装成武器副开火。旧 409 武器审计保持原始失败历史；本轮为局部复测。

## 差异归因

### Tiberon
同一旧配装，补节奏前 237 发 / 1.87425 KPM，补后 300 发 / 2.09215 KPM；参考 300 发 / 2.15122 KPM，相差从 -12.88% 收敛为 -2.75%。重新自动搜索后为上方 +2.05%。见 tiberon-fixed-build-clock.json。

### 散布惩罚 MOD
原始 WEAPON_SPREAD 一般 ADD 项为 Heavy Caliber 每级 0.27000001、Magnum Force 每级 0.5；本地按升级运算作用于原生角度并保留 validType 筛选。参考使用 accuracy_bonus 分母缩放，两者不同。本轮没有游戏实测或完整引擎调用证据裁定实际行为，不能仅凭更接近参考就改公式。

同一旧配装保留惩罚卡：Supra Vandal +7.58%、Baza Prime -16.14%、Akstiletto Prime -28.14%；只移除惩罚卡后分别 +1.32%、+1.05%、+1.08%。因此新配装接近并不代表惩罚卡公式已完全对齐。见 fixed-build-ablations.json。

### Talons
相同完整配装两边都是 88 发。10 米参考为 0，其 range_m=4 对投掷距离作截断；0 米身体命中本地 0.56371、参考 0.58728（-4.02%）；0 米设爆头后本地不变，参考变成 1.73399。参考把整段爆炸当主攻击的范围/爆头口径与本地不同，不据此给纯爆炸补爆头倍率。只作为诊断，不用更改距离的结果替代原 10 米验收。

自然触发率原生未序列化：原值 0 单独保留，10% 来自固定参考。投掷后立即引爆为单目标时间假设，多重弹丸分散命中、手动起爆等待及布雷上限仍未完整建模。

## 验证与剩余事项

- 定向套件 454 passed、7 subtests passed；新增分类断言后相关 82 项复测通过。三项完整紫卡全局搜索的旧测试耗时较长而中止，保留未完成，不报全量通过。
- 覆盖已有空战玩家配装、灵化/状态/多部件/活化/赋能/自动约束等回归；没有重跑 409 武器总矩阵或全量缓存烘焙。
- node --check 通过；真实 API 结果加 DOM stub 执行实际 drawBenchmarkReplay，检查中文说明、命中率、tooltip 和图表生成。后台服务启动被自动审批拦截，浏览器布局和交互未验收。
- 连续射击散布扩张、真实目标碰撞体、爆炸落点/光束/灵化空间模型仍开放。半径 0.25m 和均匀角度分布来自固定参考假设，不称原生实测。
- Quanta / Mutalist Quanta / Stug 运行时转换、Simulor 合球及剩余灵化条件继续按之前清单推进；Duelist 暂缓。
- 旧紫卡烘焙缓存因引擎指纹变化失效；主体机制稳定后须全量重烘焙。

## 复现

```powershell
python tools/refresh_spread_talons.py --packages C:/Users/SuperExboom/Documents/WF_Rever/wf-arsenal/data/raw/2026.09.22.16.46/packages --wfsim .local/wfsim-source-20260927 --evidence .local/reports/new-spread-import.json
python tools/audit_nonmelee_catalog.py --weapons 'Baza Prime' 'Akstiletto Prime' 'Supra Vandal' 'Karak Wraith' 'Viper Wraith' Tiberon Bolto Talons --distance 10 --profile fast --output .local/reports/new-spread-audit
python tools/compare_generated_builds.py --wfsim .local/wfsim-source-20260927 --builds docs/evidence/spread-talons-round-20260928/final-builds.json --runs 1000 --output .local/reports/new-spread-comparison
python -m pytest -q tests/test_spread_events.py tests/test_native_multipart_events.py tests/test_nonmelee_catalog_audit.py
```

证据目录 docs/evidence/spread-talons-round-20260928/：final-* 为最终实现和配装；automatic-builds / initial-reference-comparison 为补 Tiberon 节奏前输入，用于因果对照。中间实验不覆盖为最终结果。
