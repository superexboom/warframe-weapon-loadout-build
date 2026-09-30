# 散布研究：保留但暂不接入

2026-09-30 用户要求暂不计入散布，也不要为接近参考而继续量化命中损失。已实现代码保留，当前没有生产调用：

- `vendor/wfarsenal/deferred_spread.py`：原始角度归并、均匀角度/圆形目标命中概率、逐弹丸 Encumber 命中试验。
- `data/mechanics/deferred-spread-profiles.json`：八把已核对武器的原生角度、来源和 SHA，保留原提交身份。
- `tools/deferred_spread_research.py`：旧导入逻辑的独立研究副本，必须显式传 scratch export/output，CLI 拒绝覆写活动 data 目录。
- `tests/test_spread_events.py`：保留研究数学检查；生产侧断言散布词条不改变伤害、触发次数或事件评分，旧角度字段注入也不产生损失。

`ModdedStats.spread_min_deg/spread_max_deg` 保留为兼容/研究字段，生产 apply_mods 不赋值，回放不消费。旧的展示型 spread_multiplier 字段保留，不参与命中几何或分数。

活动 combat-reference 仅保留 `cadenceProfiles` 的连发参数，不导入散布。Hema/Tiberon 连发、距离伤害衰减、爆炸半径与 Primary Compression 等独立机制继续运行。

以后重新接入时，需要先确认角度分布、散布词条运算、持续射击扩张、目标碰撞体与多重/爆炸空间关系；然后同时接入手动、自动、贡献、紫卡候选及缓存指纹。不能只在结果展示层乘系数。现在不得把旧的研究函数重新挂到默认流程。
