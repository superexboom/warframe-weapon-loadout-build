# Non-melee catalog audit — 2026-09-27

本轮使用当前分支 `5e54df9` 的两路分片审计，覆盖全部非近战与 companions 目录。

- 目录指纹：`d7543a576dee5f4573225c1806b1e7b4f7062ac73e68dbc126e48c2e9b37cfbc`
- 目标武器：409；实际覆盖：409；缺失：0
- 尝试：614；成功/结构性可解释：601；结构性缺口：11
- 本地手动回放：601/601 通过；失败：0；回放错误：0
- 结构性缺口：`abstract-modular-placeholder` 6、`catalog-absent` 4、`mode-metric-unavailable` 1
- 外部 WFSim 配装对比：本工具本轮未执行，不能据此宣称跨引擎数值一致。

主要剩余机制缺口按频次排序：

1. `WEAPON_CONVERT_AMMO` / `WEAPON_PUNCTURE_DEPTH`：导出字段已识别，当前只作为未落地机制诊断。
2. `projectile-component-damage-unapplied`：仍集中在多部件/运行时弹丸武器，必须按 native projectile 或运行时脚本逐类确认，不能统一套主爆炸。
3. Incarnon 2.x/3.x/4.x/5.x 条件事件、运行时脚本和 frame-state 条件：当前审计会保留原始来源与缺口，不将未确认条件折算成静态面板收益。
4. `projectile-runtime-script` / `script-radial-transition-unverified`：Quanta、Mutalist Quanta、Stug、Arbucep 等需继续做 native/runtime 证据链。
5. Simulor 合球/奇点和叠层曲线仍未建模；本轮没有伪造曲线。

证据文件：`docs/evidence/nonmelee-catalog-audit-20260927.json`。
