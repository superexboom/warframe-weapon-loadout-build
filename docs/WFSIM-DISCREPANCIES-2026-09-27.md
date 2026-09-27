# WFSim 可复现差异记录（2026-09-27）

参考固定：source `bb1dcb69b7045b62b8a858dad7550d4458624719`，release `39047c9ca078`，WASM SHA-256 `7e893c83e50896ea043d3a5753492399c23b4a6c71fa09dbf12e91f913b59f36`。release 声明 `11db54b9+`，以下区分当前源码声明和实际冻结 WASM 行为。没有修改参考代码或对外发送消息。

## 1. Castanas / Sancti Castanas 纯爆炸错误获得头部乘区（最小复现已完成）

参考各自 YAML 明确说没有接触伤害，整条攻击只是爆炸，却把 160/300 电伤放在主 attack.damage，未标为独立 radial。原生导出也表明 source=ExplosiveAttack。

测试没有 MOD、赋能、进化；中性 1e12 生命、零甲盾、免疫全部异常；10 秒、1000 runs、同 seed，同样 14 发。只把 headshot_pct 从 0 改为 100。

| 武器 | 身体 DPS | 头部 DPS | 倍率 |
|---|---:|---:|---:|
| Castanas | 233.04 ±0.25 SE | 780.48 ±3.05 SE | 3.3491x |
| Sancti Castanas | 520.35 ±1.50 SE | 2163.15 ±13.49 SE | 4.1571x |

同为纯爆炸，选头不应改变爆炸伤害。两组显著差异超过抽样波动；不是 DOT/触发、爆头命中次数或卡序差异。这里只比各引擎内部 body/head 比值，不拿本地 perShot 与参考 DPS 混比。

原始请求、响应、source hash：`docs/evidence/radial-round-20260927/reference-headshot-probe/`。复现：

```powershell
python tools/probe_radial_headshots.py --wfsim .local/wfsim-source-20260927 --output .local/reports/new-radial-headshot-probe
```

修复方向：保留纯范围攻击的身份，隔离 head multiplier/weakpoint crit/headshot events；不应只调整基础电伤去抵消错误乘区。本地已加入纯范围 identity 与多个 reducer/事件测试。

## 2. Zarr 与 Semi-Rifle Cannonade 原生兼容被参考拒绝（证据冲突）

原生 `GrnCannonWeapon` 解析后的 CompatibilityTags 包含 `SEMI_AUTO`；卡的 CompatibilityTags 要求 `SEMI_AUTO`，ItemCompatibility 为 Rifle；本地实际配装可通过原生类型检查。参考 Zarr YAML 写 `attack.trigger: auto`，实际 WASM 返回 `semi_rifle_cannonade cannot be equipped on Zarr ... not in this weapon's pool`。

证据：`native-compatibility.json`、`generated-build-comparison.json` 中 Zarr 的完整原卡请求和拒绝响应。需要核对参考触发/池标签，不应替换用户原卡后声称同配装对比成功。这里尚无真实游戏安装录屏，因此列为原生兼容与参考实现的可验证冲突。

## 3. 尚不能判定归属的差异，不作为参考错误结论

- Primary Compression 对 Ogris：本地 DOT seed 乘压缩系数；参考 `fight/pellet.rs` 在最终实例读取 compression_multiplier，未加入 ModifiedBase。消融确认压缩导致差距放大，但未获取运行时 Lua 的完整计算或游戏独立测量，需确认伤害加成是否应影响异常。
- Simulor 强制电击：原生爆炸记录带 PT_ELECTROCUTION，参考此 radial 无 forced_procs。两边还同时欠缺 orb merging，不能把全部 KPM 差距归于某一项。
- Acceltra Prime：本地原生 arming gate 为 6m，参考注释写 wiki 7m 并明示未实现；10m 重口径方案另有空间命中损失，本地该部分欠缺。
- Stug：本地当前所选源是 75 爆炸/0SC，参考采用 4 embed/10%SC；两边 attack identity 不同，延迟/堆胶不能仅通过调基础伤害抹平。
- Secondary Fortifier：原生 rank5 MULTIPLY=8 与参考 x9 的已有冲突继续独立记录，不用误差总表裁决。

Elementalist 已由对方确认并修复；本轮参考是修复后的冻结版本。以上条目不能用来豁免本地未实现机制，也不能把部分接近结果算作全武器验收。


## 4. Kompressa / Cyanex 投射物多重与范围部件口径冲突（新增，未归因）

本地已补入原生投射物部件与 Kompressa 0.6–0.8 秒嵌入延迟、Cyanex 爆炸部件。冻结 WFSim 的 `pellet.rs` 明确规定 `takes_multishot=false` 的 radial 在 `pellet_idx > 0` 不重复生成；因此在同一目标、无状态、只增加 Barrel Diffusion 的最小实验中，参考 Kompressa KPM/DPS 比约 1.192，而本地按每个原生投射物结算范围部件会显著不同。该差异已保存于 `evidence/radial-round-20260927/secondary-radial-multishot-probe-20260927/summary.json` 与源码行证据；当前没有真实游戏录制，不能断言哪一边是游戏正确行为。

这条不用于豁免本地未实现机制，也不把 Kompressa 的公开紫卡跨引擎差异强行压到参考值。
