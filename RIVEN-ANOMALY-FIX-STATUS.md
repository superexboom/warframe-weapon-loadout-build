# 紫卡收益异常修复追踪

更新时间：2026-09-22
工作分支：`codex/riven-anomaly-fix-20260922`
缓存策略：本阶段禁止烘焙/重建静态缓存；只有完成引擎回归并得到明确指示后才执行。

## 验收口径

本任务把“能显示结果”“能算出一个数”和“结果可作为紫卡推荐依据”分开。每个阶段都要同时记录：

- 公式/机制是否已实现；
- 是否接入真实紫卡分析入口；
- 是否有针对性回归证据；
- 是否允许进入静态缓存。

单元测试通过不等于真实分析路径完成；缓存存在也不等于缓存结果在新计算语义下可信。

## 当前状态

| 领域 | 状态 | 已确认 | 未完成/限制 |
|---|---|---|---|
| 紫卡贡献指标 | 部分完成 | Pistol Elementalist 的状态伤害已进入贡献指标，未知贡献不再伪造 0% | 仍需抽样更多状态/换弹/弹射专属卡 |
| 连续窗口与升靶 | 部分完成 | 有事件时间诊断、请求/评价靶等级和上下文哈希；KPM 饱和时不再强行给 100% | 主窗口仍是连续伤害率积分，尚未成为完整离散攻击事件回放 |
| 攻击事件账本 | 部分完成 | `windowed_status_damage` 真实输出已带 direct ledger；能在真实优化入口观察攻击次数、击杀、stale component 和目标代次 | 连续 DoT/区域事件仍未与同一账本共同结算，当前 direct ledger 仍标记为 diagnostic |
| Torid / 区域与持续伤害 | 未完成、已阻止假精确 | 直击、区域/投射物静态事件可被列出；缺 field 时评分返回 `unresolved-model-partial` | 区域生成、持续跳伤、区域跨目标生命周期仍未完整回放 |
| Opticor / 径向 | 部分完成、已阻止假精确 | 静态 projectile event 可报告贡献范围；缺 radial 时评分返回 `unresolved-model-partial` | 爆炸时序、同次攻击目标归属和多目标覆盖未完整建模 |
| Latron 灵化状态 | 部分完成 | 普通/灵化 fire mode 与 Double Tap 差异已列入 sidecar；未验证部分 fail-closed | 灵化直击/径向分别吃词条的事件状态机尚未实现 |
| Double Tap | 防错完成、机制未完成 | 可见、可审计、`mod-gains` 对未建模机制返回空收益而非假收益 | 命中叠层、失误重置、弹丸顺序、灵化直击/径向分歧未进入正式评分 |
| 非功能槽/专属 MOD 静态审计 | 第一轮完成 | 已扫描武器兼容、条件效果、runtime script、特殊 upgradeType | 审计条目尚未逐一映射到运行时消费点；未知项必须保持 fail-closed |
| 搜索质量 | 部分完成 | fast/standard/deep 档位、beam/hill 和约束上下文已区分；结果明确标记 `best-known-search-result` | 多起点、联合紫卡+普通 MOD、双槽交换、有限空间穷举基准未完成 |
| 缓存 | 旧文件存在但当前代码已自动拒绝加载 | 文件仍是 fast/standard 共 1664 条、版本 8、带 fingerprint/contextHash；当前 `ANALYSIS_STATICS_CACHE` 加载条目为 0（optimizer 指纹变更） | 不重建、不删除旧文件；新事件语义未验收前不得宣称全量缓存可信；deep 未烘焙 |

## 本阶段执行顺序

1. **已完成（部分接入）**：将直接攻击事件账本接入真实 `windowed_status_damage` 输出，保留连续 DoT/区域模型的明确限制标记。
2. **已完成**：真实窗口入口回归覆盖 1 Hz 单发必杀、同一攻击组件不攻击重生目标、积分步多杀不靠一击上限截断。
3. **已完成（第一轮）**：升靶压力判断不再单独依赖 `maxKillsPerStep`；保留多杀字段作为诊断，并根据攻击周期区分积分网格问题。
4. **已完成**：结果补齐 `scoreBasis`、`modelStatus`、`targetStatus`、`searchStatus`，前端显示“best-known/未证明全局最优”。
5. **已完成（第一轮）**：静态 MOD 审计报告已生成；抽样覆盖 Pistol Elementalist、Double Tap、Latron、Torid、Opticor，发现 552 条需审计条目，其中 347 条存在兼容路径但 weapon support 缺失。
6. **本阶段保持**：只跑代码/回归/静态检查，不烘焙缓存。缓存重建作为后续独立阶段，需用户明确指示。

## 缓存准入条件（后续）

只有下列条件同时满足，才允许重新烘焙：

- 真实窗口事件回归通过；
- Torid/Opticor/Latron 的未建模机制在输出中可见且不会进入假精确评分；
- 搜索与评分使用同一 `contextHash` 和同一评价靶；
- cold/hot/bake 三路缓存测试通过；
- 烘焙报告列出 profile、条目数、指纹、失败 shard、`qualityCalibrated` 语义。

## 发布边界

- 只提交本任务相关源码、数据 sidecar、追踪文档和必要回归；
- 不提交无关 Markdown、临时报告、`.local` 产物或无关测试；
- 推送到本分支，不合并到 `main`；
- 推送前使用本机 SOCKS5 `127.0.0.1:10808` 做连通性验证。
