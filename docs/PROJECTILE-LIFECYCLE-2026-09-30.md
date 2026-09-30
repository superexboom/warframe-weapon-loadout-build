# 特殊投射物与紫卡验收（2026-09-30）

## 本轮计划

- [x] 核对当前工作树、上轮报告和已推送提交。
- [x] 提取 Mutalist Quanta、GooGun、StugIncarnon、StickyBomb 当前客户端脚本。
- [x] 保存当前武器脚本 IR、来源哈希和分支边界；未映射的视觉循环保留原始指令。
- [x] Talons 接入批次投掷、明确起爆等待、原生 8 枚部署上限和独立状态事件。
- [x] Stug 孤立胶团 1.5 秒嵌入计时、Simulor 孤立球体 1 秒寿命进入事件回放。
- [x] Mutalist Quanta 增幅爆炸说明改为盾体吸收伤害来源，不把普通毒爆作为倍率基数。
- [x] 10 把非近战完整自动配装、17 个有效模式通过手动复算；参考差异单独记录。
- [ ] 完整 Stug 堆胶/弹跳、MQ 球体合并和吸收伤害、Simulor 合球与奇点。
- [x] 7 组真实紫卡分析、返回配装复算和场景隔离；冷/热缓存上下文相等。
- [ ] 检查全量缓存任务范围、恢复已有有效分片，完成新指纹烘焙及覆盖校验。

散布按用户要求保持停用，不通过命中概率模拟 Talons 多重落点。
Duelist 继续暂缓。原生参数与参考实现、未验证生命周期分别记录。

## 证据

本轮研究目录 `.local/research/cases/wf-projectile-lifecycle-20260930/`。
当前原生 Packages 固定 `2026.09.22.16.46`；新提取字节码单独保存来源哈希，
不把历史 Luau 标准指令名称当作当前客户端解码结果。

## 已确认的紫卡输出问题

1. 连续评分重搜后 `Evaluation.score` 是窗口 DPS，旧输出直接把它写成配装
   `objectiveScore`，但客户端按 KPM 解读。现在 `objectiveScore` 按原优化目标
   重新求值，连续评分值放在 `scoringScore` / `scoringValues`。
2. 搜索用当前紫卡作为下限候选时，旧代码拿两个独立 `Evaluation` 对象的
   身份作判断，未切换到对应的紫卡词条。现在显式记录赢家，并绑定返回卡。
3. 缺失紫卡插入槽会丢失元素合并顺序。分析结果现在返回普通 MOD 的 `slot`
   和紫卡的 `riven.slot`，前端按槽位展示。
4. 质量缓存原来只有数字；现在保存实际卡序、紫卡数值及其范围，复用前
   重建并复算，数字与卡不一致则拒绝。用户实际紫卡下限不写入共享理论缓存。
5. 手动触发源策略改为读取共享解析后的场景，嵌套 `triggerPolicy` 不被顶层覆盖。

缓存合同版本升至 11。全量烘焙范围为 642 把可分析武器、878 个有效模式，
排除 6 个零伤害/辅助模式。fast 与 standard 分别执行、验收，deep 尚未烘焙。
新版 worker 使用外层并行；禁止再各自启动八进程搜索池。指纹在计算中变化
时不写分片，父进程合并也检查输入身份和缺失分片。

## 机制边界

当前延迟实现针对孤立投射物，未恢复的转换不计入伤害。投射物飞行、真实
场景碰撞、Stug 的嵌入跳数仍没有被当作完成；不把飞行中爆炸和嵌入死亡爆炸
相加。Talons 的多重落点保持未建模，不重新引入散布命中概率。

MQ 的 `OnOrbDestroyed` 检查武器上是否装备深埋之憾，取该 MOD 等级，读取
球体盾代理的 `baseAmount` 和元素比例，再生成 15m 爆炸。仅看到
`_radialDmgPct` 数组不足以算出这次伤害；还需要实际吸收弹丸后的盾数据。

Simulor 的原生合球攻击入口已找到：伤害按合球比例线性插值，半径按比例
平方根插值，合球后寿命为 20 秒。奇点初始化脚本也已提取，但尚未证实
奇点伤害对象与原投射物升级、叠层及目标切换的完整关系，继续标为缺口。

## 固定参考

参考数据注册表为 bb1dcb69，执行包为 3605094 对应的固定运行文件。
报告同时保留两者身份，不假定 YAML 与 WASM 逐字对应。
WFSim 的空间命中和范围口径与当前停用散布的本地模型不同；Simulor、
Arca Plasmor 等在 10m 的大残差不能当作纯伤害倍率误差，更不能补倍率。
Fulmin 原生模式 0 为半自动，参考默认模式却为自动；工具已纠正请求映射，
并要求响应实际执行对应 APL。未得到该形态时拒绝该项比较。

## 复现命令

```powershell
python -m pytest -q tests/test_manual_detonation.py tests/test_delayed_projectile_lifecycle.py tests/test_riven_build_slots.py tests/test_generated_build_comparison.py
python tools/audit_riven_analysis_context.py --output .local/reports/new-riven-context
python tools/run_riven_acceptance_bake.py --acceptance .local/reports/new-riven-context --output .local/reports/new-riven-bake --workers 4
```

批处理只有完整分析复算通过后才烘焙；两档全部完成、指纹和磁盘缓存覆盖
均通过后才写 `status=complete`。当前不把已启动或部分分片写成全量完成。

## 当前验证记录

- 常规矩阵 569 项及 7 个子测试通过；三项完整搜索合同单独跑完通过，约 12 分钟。
- 新增缓存发布测试验证保留其他进程发布的条目，以及旧引擎进程不能覆盖新缓存。
- Torid 常驻形态冷/热缓存三套配装复算相等，热缓存实际命中；真实循环三套
  配装也复算相等。后续 metadata 修订去掉 `contextHash` 中不影响模型的校准
  诊断轨迹；最新 v11 批处理已验证冷/热 hash 相等。
- Talons 等待和 Fulmin Prime 的真实分析三套配装复算通过；10 把非近战武器
  的全部 17 个有效模式自动/手动匹配。完整特殊生命周期未计为已完成。
- 浏览器 390×844 与桌面截图确认控制区无溢出；旧场景 CSS 高优先级规则压过
  移动端布局的问题已修复。起爆批次与等待值保存、传参和 API 回显一致。

0.5m 诊断仍保留原 10m 配装与卡序：Arca Plasmor 参考从 0.05449 升到
0.45205 KPM，但本地仍为 1.71540，距离只解释部分残差。Simulor 的参考
0.07618 与 Synoid Simulor 的参考 0.06552 完全不变，因此不能把两者大差值
归为散布。两端径向多重、强制电击与生命周期仍有不同；这里只定位差异，
未宣称哪一边完整正确。Talons 参考在 10m 为 0，0.5m/头部请求为 1.73399，
其范围/爆头口径与本地纯爆炸不同。

旧、失败和重启前的审计保留在 `.local/reports/`，不覆盖为最终通过记录。

最新 7 组为 Torid 常驻、Torid 真实循环、Talons 批次/等待、Fulmin Prime、
Arca Plasmor、Dera Vandal、Scourge Prime，全部 `passed=true`。
默认 Torid 的热缓存实际命中，三套配装 KPM 与冷缓存相等，hash 同为
`0d2c96697a84569db2bb`。本轮固定引擎指纹 `be545d5a2e34da88`。

证据归档在 `docs/evidence/projectile-lifecycle-20260930/`，manifest 记录实际
字节的 SHA-256。新批处理正在运行，状态文件为
`.local/reports/riven-full-run-v11-20260930/status.json`；运行 PID 32712。
分析验收已完成，fast 开始烘焙，随后自动进入 standard。失败会保存明确状态；
资源失败依次降低 worker 数到 2/1，并保留有效分片。两档最终磁盘覆盖和
全部 contextHash 通过后才会写 complete。

生产缓存写回会合并同指纹的磁盘条目，避免运行中的预览服务覆盖烘焙结果；
旧进程加载的引擎指纹与磁盘源码不同则拒绝写缓存。
