# Warframe & Weapon Loadout Build

[中文](README.md) | [English](README.en.md)

本地运行的 Warframe 紫卡分析、武器配装与战甲配装工具。运行时只读取仓库内的冻结数据，不访问 CDN、Warframe Market、Wiki、Overframe 或其他在线服务。

> 本项目是非官方社区工具，与 Digital Extremes 无隶属或背书关系。

## 功能

- **紫卡分析**：按武器、倾向、词条数量与数值区间计算评分、逐词条贡献、T0-T3 收益、推荐负面和致命负面。
- **武器配装**：支持枪械、近战、Kitgun、Zaw、显赫武器、架势、Exilus、赋能、Incarnon 分支、Forma 与 A/B/C 配置。
- **自动搜索**：复用同一场景下已评估的候选；同时开启自动灵化与自动赋能时，额外检查两者联合调整的组合，只采用实际评分更高的配装。搜索结果仍为预算内找到的较优解。
- **最终复评**：紫卡分析的主搜索、元素种子和保底配装按同一组三个硬度节点比较；原生核心批量计算这些独立测试点，复用初始化但不共享战斗状态。
- **完整配装精修**：自动配装最后重新检查同家族卡片，避免零层时较弱的镀层 MOD 提前被淘汰；标准和深度档还检查完整候选池的单卡替换、增减。只采纳当前战斗指标更高且满足原约束的结果。
- **守护**：同伴武器按 AI 实际行为计算（只打躯干、不开镜、不能装赋能，镀层叠层可开关）；可为机械守护本体配 10 个守护 MOD，查看本体属性，过热射击等影响武器的守护 MOD 计入伤害。
- **配装约束**：自动配装可设必选 / 本武器禁选 / 全局屏蔽，一键屏蔽派系歧视卡；右键已装备的卡可直接剔除并重新配装。
- **紫卡收藏夹**：跨武器保存紫卡，按武器分组查看，一键载入分析或装进配装，可导出 / 导入。
- **显赫武器**：35 把显赫武器（含长鞭利爪、琉璃碎击、土石坍方、剑刃风暴）进入武器配装，关联战甲配装页的配置读取技能强度 / 效率 / 能量；伤害按技能数值与强度计算，施放型按每次施放与技能连击计算；结果区给能量续航（不回复时能持续多久 / 放几次），启动不了或续不上连击时持续提示。计算一律按无限能量。
- **10-23 紫卡倾向**：所有紫卡武器统一按 1.2 计算，原倾向在界面上括号显示。
- **战甲配装**：支持光环、Exilus、普通 MOD、赋能、源力石、Helminth、活化、条件效果、容量和技能面板计算。
- **目标模拟**：支持本地敌人目录、自定义防御、等级缩放、钢铁之路、卓越者、超宏护盾、护甲削减、爆头和多种伤害口径。
- **本地素材**：卡图、边框、极性、战甲头像、技能图标和数据均随项目提供；配置可导入/导出，并兼容 Warframe Rabbit 紧凑格式。
- **明确降级**：未覆盖的运行时脚本、投射物组件或条件机制会保留 `unsupported` / `skipped` 诊断，不用猜值冒充精确结果。

Tennokai 卡目前保留装备与容量信息，机会触发及随后的自动重击尚未建模，相关结果会明确提示该限制。

当前冻结游戏数据 build：`2026.08.13.13.24`。

## 源码运行

要求 Python 3.11 或更高版本。运行服务本身只依赖 Python 标准库和仓库内的 `vendor/wfarsenal`。

```powershell
python app.py
```

默认地址为 <http://127.0.0.1:8765/>，程序会自动打开浏览器。端口占用时可让系统选择空闲端口：

```powershell
python app.py --port 0
```

也可以双击 `run-dev.cmd`。

可选的 Rust 计算核心能显著加快搜索：装好 Rust 工具链后运行 `python tools/build_native.py`，生成的 `vendor/wfarsenal/wfcore.pyd` 会被自动加载；没有它时引擎使用同等结果的 Python 实现。

## Windows 便携包

从仓库 Releases 下载 `Warframe-Weapon-Loadout-Build-win-x64.exe`，双击启动。无需安装 Python，也无需在 EXE 旁放置数据或依赖目录；界面使用系统默认浏览器。退出时在服务窗口按 `Ctrl+C`。

程序启动时会释放内嵌资源到系统临时目录，正常退出后清理。持久计算缓存位于 `%LOCALAPPDATA%\Warframe-Weapon-Loadout-Build\cache`；配装和主题仍保存在浏览器本地存储中，跨机器迁移配装请使用导入/导出。不要依靠复制 EXE 迁移浏览器数据。

服务窗口提供内置说明、许可证和第三方声明的本地链接，默认分别为 `/docs/README.md`、`/docs/LICENSE` 和 `/docs/THIRD_PARTY_NOTICES.md`。

打包需要 PyInstaller：

```powershell
python -m pip install pyinstaller
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-portable.ps1
```

输出位于 `.local/artifacts/release/Warframe-Weapon-Loadout-Build-win-x64.exe`，同目录生成 `.exe.sha256` 校验文件。分发时只需 EXE，校验文件供核对下载完整性。`.local/` 保存本机构建、缓存、审计与归档材料，不会提交到 Git。

## 开发验证

`python -m pytest -q` 运行回归，`python tools/check_runtime.py` 检查本地冻结数据与实际导入路径。自动配装、手动模拟及贡献分析 API 可显式传入 `windowSeconds`（0.1–600 秒），缺省保持 30 秒；比较结果必须使用相同战斗窗口。

开发用 WFSim 对照工具需要 Node.js 和 PyYAML。以下命令只抓取公开参考资源并在本机复测，不提交榜单，也不生成计算缓存：

```powershell
python tools/fetch_wfsim_runtime.py --output .local/wfsim-reference
python tools/compare_wfsim_boards.py prepare --runtime .local/wfsim-reference --output .local/wfsim-comparison --weapons laetum nikana_prime --profile fast --window-seconds 30
python tools/compare_wfsim_boards.py run --runtime .local/wfsim-reference --output .local/wfsim-comparison --runs 1000 --workers 2
python tools/compare_wfsim_boards.py summarize --runtime .local/wfsim-reference --output .local/wfsim-comparison
```

省略 `--window-seconds` 使用官方榜单的窗口。`cross-window --window-seconds 180` 可将已有搜索结果放到 180 秒条件复测，不重新搜索。报告保留不能映射的样例、超时及两个模型的排序差异；它衡量固定赋能、灵化路线和紫卡数值下的 MOD 搜索，不证明全局最优。默认使用官方 WASM；提供带匹配构建清单的 simfleet 原生库时，会校验引擎标识和文件哈希后使用它。

## 项目结构

```text
app.py                 本地 HTTP 服务与 API
frontend/              中文 Web UI 与本地素材
vendor/wfarsenal/      配装、伤害和战甲计算内核
native/wfcore/         可选的 Rust 计算核心
data/                  冻结数据、来源锁与运行 sidecar
tools/                 数据生成、导入、烘焙与审计工具
tests/                 回归测试与测试夹具
build-portable.ps1     Windows 便携包构建脚本
THIRD_PARTY_NOTICES.md 第三方来源与授权说明
```

## 许可

未另行标注的项目源代码采用 [GNU Affero General Public License v3.0](LICENSE)，SPDX 标识为 `AGPL-3.0-only`。

部分计算机制与代码移植或改编自 [WFSim](https://github.com/magenie33/wfsim)（作者 magenie33 及 WFSim 贡献者，`AGPL-3.0-or-later`），对应部分在 AGPL-3.0 下随本项目分发，代码注释标明了出处。本项目不是 WFSim，也未获其背书，“WFSim”一名仅用于说明来源。从 WFSim 导入的数据、实测规则与基准结果（测试夹具，`CC BY-NC-SA 4.0`）均按其条款署名。

部分武器数据读取自 [WARFRAME Wiki](https://wiki.warframe.com/)；随仓库提供的 `Module:Stances/data` 副本适用 Wiki 声明的 `CC BY-NC-SA 3.0`。

*Warframe* 是 Digital Extremes Ltd. 的商标。游戏数据、卡面文本，以及 `frontend/assets/` 中的卡图、图标和其他美术均为 Digital Extremes 版权所有，不在本项目的代码许可范围内，本项目不就其授予任何权利；权利人要求移除的内容将予以移除。

各项来源、作者与条款详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
