# WFSim 公开紫卡配装复现审计

工具：`tools/audit_riven_board_builds.py`。取 WFSim 公开榜（`.local/wfsim-board-index.json`）
每把武器单目标基准下带紫卡、基础形态、无灵化进化、无赋灵元素的最高分配装：

- **public\***：公开配装去掉弱点特化卡（按导出效果/条件含 WEAKPOINT/HEADSHOT 判定：
  Acuity、氩晶/镀层瞄具、液压准心、激光瞄具、Target Acquired 等），空出的槽由本地
  优化器补齐；
- **ours**：同一张紫卡，本地优化器自选全部槽位；
- 条件：身体命中、无赋能、无 Exilus、凶魂百夫长钢铁之路，两个引擎各打分（WFSim 为
  `wfsim-live-20261004` 固定运行时，100 次）。

## 9999 级（榜单靶）不适合判断配卡

身体命中下 30 秒几乎打不死（约 1 KPM），所有击杀触发卡（镀层系列）都不生效，公开
配装被系统性低估。结果仅保留作模型差异参考：
`docs/evidence/riven-board-builds-20261004/`。

## 170 级（会产生击杀）

证据：`docs/evidence/riven-board-builds-170-20261004/cases.json`。19 把武器中：

- 14 把 WFSim 认为本地配装不差于公开配装；
- 5 把 WFSim 认为公开配装更好，按本地评分区分原因：

|武器|WFSim public\*/ours|本地 public\*/ours|原因|
|---|---:|---:|---|
|Basmu|3.12/1.99|0.93/1.72|模型：公开配装被低估 3.4 倍|
|Kompressa Prime|3.83/3.41|1.61/1.84|模型：低估 2.4 倍|
|Trumna Prime|7.38/6.63|5.47/5.88|模型：低估 26%|
|Akarius Prime|12.00/7.96|1.68/2.10|模型：低估 7 倍（爆炸弹体）|
|Zakti Prime|5.37/3.17|3.35/2.34|**搜索未命中**：本地同样认为公开配装更好|

模型低估集中在镀层射击/资质/扩散 + 多异常（Pestilence、Cryo、Malignant Force、
Radiated Reload）的异常叠层配装；另有偏高：Fulmin Prime ours 3.50/1.96、Flux Rifle
3.50/2.49、Bubonico 5.97/4.20、Cyanex 4.66/3.44（热/火焰向配装偏多）。
Amprex、Pyrana Prime、Stahlta、Sobek、Athodai Prime 两引擎吻合在 ±4% 内。

## 本轮发现的目录缺口

- **已修**：Internal Bleeding / Hemorrhage / Magnetic Welt 导出效果为 `NONE`，目录准入
  只看效果支持表，从不检查已验证的运行时适配器，因此被排除在手动配装与优化器之外。
  现在可解析运行时适配器的卡同样准入（`app.py::_manual_mod_rows`）。
- **未修**：Hunter Munitions（`WEAPON_SLASH_PROC_ON_CRIT_CHANCE` 未建模，暴击步枪
  常用卡）；狙击连击与开镜暴伤 +50%（所有狙击枪被低估，Rubico Prime 约 3 倍）；
  `SecondaryExplosionRadiusModExpert`、霰弹开镜射速卡不在候选池；Euphona Prime 被
  本地允许装 Semi-Pistol Cannonade，WFSim 判定不在该武器卡池。
