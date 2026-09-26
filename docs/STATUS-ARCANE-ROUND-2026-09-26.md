# 第二轮：状态赋能与非近战完整配装

采样始于2026-09-26，最终验证跨日到2026-09-27。当前轮以生产手动API、共享事件内核、自动搜索实际结果为验证对象。

## 已落地

- [x] Secondary Encumber：读取原始每级4%概率；13类物理/元素异常均匀抽取；按整数多重的概率分布计算成功率；同一时刻的直击/径向共享一次上限，额外异常不自触发。光束使用合并伤害种子。
- [x] 随机异常与GunCO：用异常类型存在概率近似代替“极小期望层数也算必定存在”；CO系数接受小数期望，公共Scenario仍保持整数合同。
- [x] Secondary Fortifier：目录可选、贡献可算，超宏专属乘区随实际命中的池变化；溢出到护盾/生命的部分不继承增幅。窃取按实际扣除超宏的1%，玩家超宏累计上限15000，排除集团爆发。
- [x] Kohm / Kuva Kohm / Kohmak / Twin Kohmak：补原始PlayerDamageMultiplier、弹丸递增、射速起转、弹药向上取整与长换弹重置。面板展示满转，真实循环从第一发开始；负射速持续按住扳机不误当停火。远距离衰减的绝对伤害也随PlayerDamageMultiplier换算。
- [x] Galvanized Hell / Savvy：补OnShotgunKillCondition事件映射。Repeater Clip / Pressurized Magazine / Spring-Loaded Chamber：从换弹完成后触发，持续时间按等级递增，R5为9秒。
- [x] Cascadia Flare等已支持事件条件：零初始层数不再误报“没有支持词条/需要提供触发率”；未知脚本、条件、词条继续保留缺失诊断。
- [x] 新增16套完整玩家配装（11种武器，其中8种是上轮未覆盖的武器），保留顺序、特殊槽、元素、条件和拒绝原因。
- [x] 63套新旧样本通过手动/自动评分路径一致性检查。
- [x] 全量pytest通过289项测试、12项子测试；86种跨武器场景评分一致。
- [x] 六把完整自动配装搜索，build回填生产手动评分6/6一致；Kohm保留非目标用的`WEAPON_CONVERT_AMMO`补给提示。
- [ ] 提交并推送现有分支。

## 固定对照条件

WFSim源码固定于`b98b3d456393131857e1c0e247b19aac6ecc08f4`，release `285450cbd40f`，WASM `697c63bfc0d2`。不将它称为最新版本；参考数据和WASM均只读。原始数据build `2026.09.22.16.46`。

30秒、1000次参考模拟、9999级钢铁之路Thrax Centurion、100%弱点命中、瞄准、0.5米、无限备弹但正常弹匣/换弹、从零叠层起步。来源URL、SHA256、完整请求和参考标准误见`docs/evidence/status-arcane-community-20260926.json`。

新覆盖武器：Twin Grakatas、Kuva Brakk、Spira Prime、Kohm、Akbolto Prime、Pandero Prime、Twin Kohmak、Kuva Sobek。额外复测Aksomati Prime、Tenet Cycron和空战Fluctus。空战对照按地面使用口径，不等同太空模式验收。

## 新采样结果

偏差=(本地/参考-1)。12/16套绝对偏差小于10%。这些是有限窗口期望模型与Monte Carlo的比较，不能将接近直接当成游戏内准确。

| 完整配装ID | 本地KPM | WFSim KPM | 偏差 |
|---|---:|---:|---:|
| twin_grakatas-2 | 0.7171 | 0.6991 | +2.57% |
| kuva_brakk-2 | 1.3007 | 1.2997 | +0.08% |
| spira_prime-2 | 3.7683 | 3.3517 | +12.43% |
| kohm-4 | 1.2001 | 1.7102 | -29.83% |
| kohm-5 | 1.4307 | 2.0281 | -29.46% |
| aksomati_prime-8 | 1.6337 | 1.5410 | +6.02% |
| aksomati_prime-9 | 1.3380 | 1.2388 | +8.01% |
| tenet_cycron-170 | 15.9063 | 15.9487 | -0.27% |
| tenet_cycron-171 | 14.4759 | 15.1760 | -4.61% |
| fluctus-6 | 7.0839 | 7.0972 | -0.19% |
| fluctus-7 | 9.7768 | 9.5961 | +1.88% |
| akbolto_prime-2 | 0.7417 | 0.7210 | +2.87% |
| pandero_prime-5 | 0.6334 | 0.6019 | +5.24% |
| twin_kohmak-2 | 1.2386 | 1.2869 | -3.75% |
| kuva_sobek-40 | 14.2909 | 14.5908 | -2.06% |
| kuva_sobek-41 | 5.0079 | 1.9642 | +154.96% |

## 差异与消融

1. **Encumber修复**：Aksomati Prime两套从上轮约-59%/-53%变为+6.02%/+8.01%。该改善包含额外异常及类型存在概率处理。
2. **Fortifier接入**：Tenet Cycron-170从约-65%变为-0.27%；Fluctus-7从约-32.51%变为+1.88%。原始Upgrade是MULTIPLY，采用R0×3到R5×8；固定WFSim YAML将“Extra”解释为总×9，属于明确的来源冲突，不能声称已游戏实测消除。
3. **Kohm起转差异**：两套正式结果约-29.8%/-29.5%；WFSim明示开场已满12弹丸且满射速。仅用于诊断的“双方满转”对照变为+6.46%/-0.04%。产品仍保留真实起转过程，不能为了对齐丢掉这个机制。
4. **元素增幅卡**：Kuva Sobek-41的+154.96%受已确认的WFSim Elementalist错误影响。双方同时移除这张卡的诊断对照为本地1.608951、参考1.617057，偏差-0.50%。这是额外消融，不冒充完整8卡验收，也不回调本地正确乘区。
5. **Twin Kohmak**：起转/弹丸/玩家倍率修复后，该完整配装从约-81%变为-3.75%。
6. **旧空战样本**：重新走生产接口与共享评分，保留全部差异；未重新抽换一批低偏差样本。

## 剩余缺口与可行补法

- **Spira Prime约+12.43%**：先分离直击、穿刺暴击增益、独立异常与击杀时间离散性；保留当前请求做单因素消融，不调基础常数。
- **Rubico Prime约-80%/-34%**：需要显式镜档和狙击连击输入、递减事件；已有原始镜档字段，具备实现入口，但不能把aiming直接默认最高镜档。
- **Phantasma Prime约-18%**：本轮散弹条件修复后较上轮改善，5束/6束的中心束来源仍待核对。需检查额外fire behavior及子投射物，不能凭参考值补1束。
- **Trumna Prime约-19%/-21%**：继续按同一弹丸拆直击/径向暴击、弱点命中与触发顺序。
- **Encumber概率近似**：当前Poisson占用近似不保留所有异常之间、击杀时刻之间的联合分布；仅模拟单目标。强制异常输入是每次攻击的期望计数，其触发相关性仍近似；非链式多光束、空间链式和旅行时间未完整覆盖。
- **起转细节**：射速按原始ContinuousMaxShots线性插值；换弹达到完整停转阈值时归零，短暂停火的部分衰减与游戏实际曲线尚未实测。
- **Fortifier防御**：已计算累计窃取与15000上限，不模拟玩家受到伤害、超宏消耗或队友来源。原始×8与参考×9分歧需独立游戏记录定案。
- **活化**：本轮沿用已实现的联合暴击概率/清零模型并回归；30Hz门控、特殊副射击的清零范围仍属未实测边界。
- **MOD/赋能导入拒绝**：未映射进化、未知运行时脚本继续明确拒绝或标出未计入；不删字段冒充完整配装。Duelist继续延后。

## 最终验证

- 全量pytest：289 passed、12 subtests passed，1363.44秒。
- 63套新旧完整玩家配装：生产手动与自动评分内核63/63一致。
- 26个武器系列、86种场景：含灵化、负触发紫卡、瞄准和各射击模式，86/86一致。
- `compileall`覆盖app、vendor/wfarsenal、tools；`git diff --check`通过。
- 完整自动搜索六把通过：Aksomati Prime 8.5061、Twin Grakatas 9.5372、Akbolto Prime 5.6829、Tenet Cycron 1.9957、Kohm 9.6670、Twin Kohmak 10.1354 KPM；各自动结果与回填生产手动API完全相等。Kohm仍报告弹药转换机制未实现；本轮无限备弹战斗窗口不受该项影响。

## 重放命令

```powershell
python -m pytest -q
python tools/regress_auto_build_events.py --status-arcanes --full --output .local/reports/NEXT-UNIQUE-AUTO.json
python tools/audit_optimizer_events.py --output .local/reports/NEXT-UNIQUE-PARITY.json
python tools/compare_archgun_board_builds.py --wfsim .local/wfsim-source-20260926 --fetch --weapons twin_grakatas kuva_brakk spira_prime kohm akbolto_prime pandero_prime twin_kohmak kuva_sobek --per-weapon 2 --runs 1000 --output .local/reports/NEXT-UNIQUE-BOARD
```

未声称完成游戏内实测、全部武器覆盖、桌面界面验收或安装包发布。
