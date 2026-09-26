# 非近战完整配装回归：2026-09-26

## 范围与结果

新增尝试18把非近战武器，成功15把、26条玩家配装记录；加上14把空战武器21条记录，共29把武器47条记录。相同配置的重复投稿按原行保留，不当成独立机制覆盖。之前进度所说17把新增有误，以去重数量15把为准。

45条可导入记录全部通过生产手动API与离线内核一致性；新增25条与旧fixture20条通过手动/搜索评分回归。2条带Secondary Fortifier的记录仍明确不可导入。20条可导入空战记录全部在WFSim的±10%内，绝对偏差中位数2.61%；新增25条中12条在±10%内。合计32/45，仍有大偏差，不能宣称全面对齐。

## 已落地

- Crux改成相对基础触发率加成，与触发MOD同桶；不再增加300个百分点。
- 光束多重射击合并一次命中/暴击；自然异常种子使用E[M²]/E[M]，独立异常使用E[M]，保留整数抽样的小数多重期望。
- 镀层补副武器击杀条件；初始CO为0也会在击杀后启用动态异常计数。
- GunCO不再进入异常种子；切割用改装基伤，不用切割份额。
- 气体不再重复吃火毒MOD加成，只接受直接气体加成。
- 磁力破防电击进入事件流，输出magneticBreaks诊断。
- 信条循环者采用0.5秒延迟、40弹/秒补充，按弹匣容量计时，充电不触发装填事件。
- 镀层瞄准类副武器条件、逐层12秒计时补齐。
- 活化显式层数不再被API截成1层。
- 对比工具支持主副武器、特殊槽、0.5m距离；拒绝未映射进化/紫卡/外部状态。特殊槽按WFSim API的mods列表传入。
- 新增真实投稿fixture、贡献移除回归、完整自动配装回填。修复旧审计脚本损坏字符串导致的SyntaxError。

## 比较合同

WFSim source b98b3d456393131857e1c0e247b19aac6ecc08f4；WASM release 285450cbd40f，编译标识becb34b1+；WASM SHA256 697c63bfc0d2fe1c5da82e19adc9d76e54933bbc0baa9cd60c804e419fbe8f0f。源码和发布二进制标识不同，分别保留，不宣称同一构建。参考仓库未编辑。

30秒、1000次参考模拟、seed=12648430、Lv9999 SP Thrax、100%弱点、瞄准、0.5m、条件从0开始；空战明确无限补给。MOD顺序、等级、特殊槽、赋能、元素保留。原榜单180秒，因此这里不复刻原榜单分数。

原始快照、请求、响应、标准误与诊断在`.local/reports/2026-09-26-nonmelee-round/`。随仓库证据：`docs/evidence/nonmelee-community-20260926.json`；新增输入：`tests/fixtures/nonmelee_board_20260926.json`。旧空战fixture未改。

| 投稿记录 | 本地KPM | WFSim KPM | 差异 | 状态 |
|---|---:|---:|---:|---|
| ignis_wraith-80 | 6.0400 | 5.3578 | +12.73% | 可导入 |
| ignis_wraith-81 | 5.9721 | 5.9381 | +0.57% | 可导入 |
| amprex-9 | 1.4829 | 1.4367 | +3.21% | 可导入 |
| amprex-10 | 1.2341 | 1.2121 | +1.82% | 可导入 |
| kuva_nukor-626 | 21.6582 | 22.6553 | -4.40% | 可导入 |
| kuva_nukor-627 | 21.6582 | 22.6553 | -4.40% | 可导入 |
| tenet_cycron-170 | 5.5999 | 15.9487 | -64.89% | 赋能未支持 |
| tenet_cycron-171 | 14.4759 | 15.1760 | -4.61% | 可导入 |
| akstiletto_prime-2 | 0.5320 | 0.4820 | +10.37% | 可导入 |
| baza_prime-116 | 5.3566 | 5.0835 | +5.37% | 可导入 |
| baza_prime-117 | 4.8325 | 4.6159 | +4.69% | 可导入 |
| phantasma_prime-448 | 8.6663 | 12.2647 | -29.34% | 可导入 |
| phantasma_prime-449 | 8.0094 | 12.2150 | -34.43% | 可导入 |
| trumna_prime-43 | 6.7975 | 8.6165 | -21.11% | 可导入 |
| trumna_prime-44 | 6.8617 | 8.5084 | -19.35% | 可导入 |
| cedo-4 | 1.2538 | 1.2094 | +3.67% | 可导入 |
| tigris_prime-2 | 2.6332 | 1.6615 | +58.49% | 可导入 |
| rubico_prime-69 | 0.8457 | 4.2531 | -80.11% | 可导入 |
| rubico_prime-70 | 1.1873 | 1.7982 | -33.98% | 可导入 |
| aksomati_prime-8 | 0.6385 | 1.5410 | -58.56% | 可导入 |
| aksomati_prime-9 | 0.5787 | 1.2388 | -53.28% | 可导入 |
| kuva_karak-2 | 1.3459 | 1.3751 | -2.12% | 可导入 |
| supra_vandal-8 | 1.9795 | 2.0114 | -1.58% | 可导入 |
| supra_vandal-9 | 1.3902 | 1.4736 | -5.66% | 可导入 |
| tenora_prime-12 | 4.0817 | 3.4197 | +19.36% | 可导入 |
| tenora_prime-13 | 3.5548 | 2.0394 | +74.30% | 可导入 |
| corvas-5 | 3.7620 | 3.5672 | +5.46% | 可导入 |
| mausolon-136 | 25.7996 | 24.8072 | +4.00% | 可导入 |
| mausolon-137 | 26.2577 | 25.1328 | +4.48% | 可导入 |
| larkspur_prime-1033 | 17.5494 | 19.4349 | -9.70% | 可导入 |
| larkspur_prime-1037 | 19.7349 | 19.6883 | +0.24% | 可导入 |
| imperator-2 | 3.2892 | 3.2379 | +1.59% | 可导入 |
| imperator_vandal-75 | 25.1814 | 23.9825 | +5.00% | 可导入 |
| imperator_vandal-76 | 21.5528 | 20.2107 | +6.64% | 可导入 |
| grattler-2 | 1.9983 | 1.9752 | +1.17% | 可导入 |
| kuva_grattler-190 | 16.1208 | 15.0202 | +7.33% | 可导入 |
| kuva_grattler-191 | 18.4798 | 18.0050 | +2.64% | 可导入 |
| fluctus-6 | 7.0839 | 7.0972 | -0.19% | 可导入 |
| fluctus-7 | 6.4761 | 9.5961 | -32.51% | 赋能未支持 |
| cyngas-2 | 3.8348 | 3.8327 | +0.05% | 可导入 |
| velocitus-5 | 1.6705 | 1.6722 | -0.10% | 可导入 |
| morgha-5 | 1.5912 | 1.5897 | +0.10% | 可导入 |
| cortege-219 | 22.2147 | 21.6563 | +2.58% | 可导入 |
| cortege-223 | 29.3215 | 28.0521 | +4.53% | 可导入 |
| dual_decurion-2 | 3.4779 | 3.4656 | +0.35% | 可导入 |
| prisma_dual_decurions-10 | 18.8411 | 18.2764 | +3.09% | 可导入 |
| prisma_dual_decurions-11 | 18.2190 | 17.8288 | +2.19% | 可导入 |

## 剩余缺口与下一轮入口

1. **Secondary Encumber / Fortifier**：Aksomati Prime两条约-53%/-59%；Fortifier配装仍拒绝导入。前者需随机异常的一次瞬间上限与类型概率分布，后者需超宏伤害与窃取的事件范围。已有精确样本，不能用调常数掩盖。
2. **Rubico Prime**：-80%/-34%，狙击连击与镜档未完整建模。原始RubicoPrimeWeapon.txt已有2.5x/5x镜档的+35%/+50%暴伤；需要明确镜档输入与连击递减，不把aiming布尔值默认成最高档。
3. **Phantasma Prime**：原始2026.09.22.16.46 fireIterations=5，WFSim按6束。额外中心束是否独立于fireIterations需继续证明；本轮保留原始值。明确0.5m距离已启用Vendetta，两条仍约-29%/-34%。
4. **参考MOD冲突**：Rifle及Shotgun Elementalist的参考YAML写成base_damage_bonus，描述和原始UpgradeType却是WEAPON_PROC_DAMAGE。影响Tenora、Supra、Kuva Karak、Tigris；数值偶然接近不代表该机制正确。Rifle原始SHA256=f93427ec2d3659f3df3a5074490ec0a663dbd4d4572fc20279ae0fa731f6fae5；Shotgun=d867e88c76d5c569d59445b2da5d35b465a22e3e0939c94e857e5eb1ec9c0775。参考仓库未改。
5. **Trumna Prime**：-19%/-21%；直击/爆炸原始85+50已确认，仍需核对同一弹丸的直击/径向暴击与弱点增幅边界。
6. **活化与期望模型**：WFSim也将叠层/清零先后、30Hz门控标为未游戏校准。特殊副射击忽略增长时是否仍清零、投射物/非链式多束分组仍待证明。随机状态与击杀时刻相关性、光束升温、空间连锁尚有残差。
7. **磁力破防合同**：采用固定参考Rust实现的6次tick和异常倍率平方。同一参考YAML对阵营、元素、持续时间写了更广规则，二者不一致。输出limitations已标明固定参考合同，游戏完整机制验证仍开放。
8. **拒绝输入**：Vectis/Soma Prime高分行带未映射进化，Prisma Grakata无符合条件的无紫卡基础形态记录。之后补导入映射，不删除字段冒充完整配装。Duelist继续延后。

## 验证

- 全量pytest：220 passed、12 subtests，791.74秒；该进程在最后几项修正前启动。
- 最终机制定向回归：129 passed；改进GunCO测试为独立计算两种场景、精确路径匹配后43 passed。
- 最终跨26个武器系列的评分一致性检查86/86通过，输出parity-broad-final.json并写入随仓库证据。
- 最终封版扩大回归：197 passed、7 subtests，530.02秒；包含旧武器、优化器约束与全部本轮机制用例。
- compileall覆盖app、vendor/wfarsenal、tools；git diff --check。
- 最终完整自动配装6/6通过，输出auto-full-final.json。所有自动得分与生产手动API回填一致。
- 未声称完成游戏内实测、全部武器覆盖或打包发布。

| 自动配装武器 | 自动KPM | 手动KPM |
|---|---:|---:|
| Ignis Wraith | 8.474413 | 8.474413 |
| Amprex | 3.706830 | 3.706830 |
| Kuva Nukor | 19.804602 | 19.804602 |
| Tenet Cycron | 15.299922 | 15.299922 |
| Baza Prime | 8.735375 | 8.735375 |
| Trumna Prime | 11.440298 | 11.440298 |

## 重放

```powershell
python tools/compare_archgun_board_builds.py --wfsim .local/wfsim-source-20260926 --fetch --weapons ignis_wraith amprex kuva_nukor tenet_cycron baza_prime trumna_prime --per-weapon 2 --runs 1000 --output .local/reports/NEXT-UNIQUE-DIRECTORY
python tools/regress_auto_build_events.py --community --full --output .local/reports/NEXT-UNIQUE-AUTO.json
python -m pytest tests/test_nonmelee_community.py tests/test_galvanized_scope.py -q
```

各输出目录独立保留；早期缺少特殊槽/距离的探索结果不作为最终验收结果。
