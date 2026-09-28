# 未尽机制、自动配装与紫卡反哺（2026-09-28）

## 已完成与发布范围

Bot 图标适配位于独立 checkout 的 `Preview/enemy-visual-assets-20260928`。提交 `8d59d398` 已存在于远端，本次重新执行 push 并确认本地/远端 0/0；`go test ./service/rasset ./service/rimg` 通过。未合并 main，没有把旧主目录的采集实验、凭据或其他脏改动一起提交。

本项目继续完成以下内容：

1. Torid Final Fusillade 的末发多重正确作用于真实循环的基础弹匣；选中的灵化形态和灵化弹池不触发。
2. Torid Renewed Horror 在空仓换弹完成后，仅把下一次基础射击的毒云时间从 10 秒延长到 20 秒。初始弹匣不赠送，换形态不冒充换弹，杀死目标的首发也会消耗该一次性机会，不把场转移到下一目标。
3. Hema 原生三连发 `NumShots=3 / BurstDelay=0.1 / ConsumeAmmoOncePerBurst=0` 接入共享事件节奏；同时导入其原生瞄准/腰射散布。角色换弹耗血没有被当作已模拟，显式提示。
4. 修复贡献接口显式 `metric=killsPerMinute` 时遗漏事件分支的问题。以前主配装与删卡变体都错误返回 0；现在与配装页、手动回放、自动候选及紫卡候选推荐共用事件评分。
5. 进化选项与回放显示具体条件和首发毒云延时次数；所有新增档案重导入后仍一致。

## 验证

446 项测试及 3 个子测试通过，包括原生签名变化拒绝、换弹/变形/末发边界、多重、负异常持续、自动/手动/紫卡候选及 MOD/紫卡贡献。Python 编译、JavaScript 语法、diff 检查通过。本轮 UI 为输出内容与代码检查，没有重新做整页浏览器验收。

六组实际八槽自动配装均与当前手动及固定候选评分一致。原始自动搜索保留自己的 fingerprint；后续贡献接口修正后的当前复算另存 `delivery-parity.json`，不反写原搜索身份。

| 案例 | 本地 KPM | 最新 WFSim KPM | 差异 |
|---|---:|---:|---:|
| Torid base | 1.39178 | 1.21613 | +14.44% |
| Tysis base | 1.69293 | 1.62190 | +4.38% |
| Tenora Prime base | 4.22709 | 4.11808 | +2.65% |
| Hema base | 3.19854 | 3.10103 | +3.14% |
| Quanta Vandal base | 1.88073 | 1.86759 | +0.70% |
| Torid 真实循环 | 1.47126 | 未映射 | 仅本地一致性验收 |

五组参考为相同原卡 path/rank/槽序/辅助槽，30 秒、1000 次、seed 12648430、9999 级钢铁凶魂百夫长、10m、显式瞄准和原请求爆头率。未用裸枪结果代替完整配装。

Hema 重配前后不是单变量：旧配装 229 发、本地 2.33494 对参考 3.29202（-29.07%）；只在旧配装套用连发与原生散布后是 300 发 / 1.71840，受 Heavy Caliber 散布惩罚影响。重新自动配装会换掉这张卡，最终 336 发 / 3.19854，参考 3.10103（+3.14%）。完整固定旧配装结果见 `causal-checks.json`，不以最终重配数值掩盖散布公式分歧。

## Torid 参考版本差异

旧参考源码 bb1dcb69、release 39047c9ca078 / WASM 7e893c83e508 保持只读。远端新源码身份为 `3605094fb2f9784074b7a5bde2cacd8dfba50a27`，发布包声明 `93be93ff+`，release `71d91a6c11e1` / WASM `f0ea532cbccb`。完整 clone/archive 因网络失败；改为按精确 commit 获取三个运行文件及两份数据定义，续传后校验 WASM 大小 6677341、Git blob `28c9f9d76981b191f3884b0466902cddb521719f` 和 SHA-256。没有声称拿到完整新源码 checkout。

同样五个请求在新旧运行包得到相同结果。两者 `/api/panel` 的毒云基础伤害都以 40×(1+1.65+1.65)=172 计算，来源列表同时列出 Final Fusillade +51。新旧进化数据说明明确写毒云 40→91，应为 91×4.3=391.3；本地按该基础加值处理。它是可复现的参考声明与运行差异，不据此把本地毒云基础加值删掉。

+14.44% 不能全归因于该项：原靶超宏击破、异常、几何等会压缩或放大总差值。额外中性大血量/超宏不击破探针隔离了池转换；开/关 Renewed Horror 在两边都产生延时收益。诊断数据见 `field-duration-pool-probe.json`、新旧 panel 和发布哈希，不对外发送消息，不修改参考实现。

## 紫卡反哺状态

已经确认候选推荐与移除紫卡贡献使用共享事件路径。实测一张 +100% 暴击伤害、-91.008% 异常持续的 Torid 配装：当前 KPM 0.343724884，去掉紫卡为 1.325941038；接口正确回显约 0.344 / 1.326，能反映负收益。三种入口指标 killsPerMinute/sustainedDps/attackDps 的事件贡献均有回归。

**完整紫卡分析页面的上下文覆盖、全局搜索验收和新缓存重烘焙仍未完成。** 旧缓存不能直接作为当前引擎结果。还需处理的机制：Quanta/Mutalist Quanta 运行时转换、Stug 堆胶/弹跳、Simulor 合球/奇点、散布惩罚公式分歧及连续扩散、Talons 落点和手动等待。Duelist 暂缓。普通手动提前换弹、换弹取消与游戏实测没有在本轮声明支持。

## 复现

```powershell
python tools/audit_remaining_events.py --output .local/reports/new-remaining-auto.json
python tools/compare_generated_builds.py --wfsim .local/wfsim-source-20260927 --builds docs/evidence/remaining-events-20260928/delivery-builds.json --runs 1000 --output .local/reports/new-reference-comparison
python tools/probe_torid_field_duration.py --builds docs/evidence/remaining-events-20260928/delivery-auto.json --wfsim .local/wfsim-source-20260927 --output .local/reports/new-field-probe
python -m pytest -q tests/test_torid_reload_fields.py tests/test_spread_events.py tests/test_optimizer_events.py
```

证据目录中 `auto-final.json`/`regression.txt` 是早期 Torid 阶段记录；`delivery-*` 为 Hema 和显式 KPM 贡献补齐后的记录。保留原文件，不把旧结果重命名成新验收。
