# Warframe & Weapon Loadout Build

[中文](README.md) | [English](README.en.md)

本地运行的 Warframe 紫卡分析、武器配装与战甲配装工具。运行时只读取仓库内的冻结数据，不访问 CDN、Warframe Market、Wiki、Overframe 或其他在线服务。

> 本项目是非官方社区工具，与 Digital Extremes 无隶属或背书关系。

## 功能

- **紫卡分析**：按武器、倾向、词条数量与数值区间计算评分、逐词条贡献、T0-T3 收益、推荐负面和致命负面。
- **武器配装**：支持枪械、近战、Kitgun、Zaw、显赫武器、架势、Exilus、赋能、Incarnon 分支、Forma 与 A/B/C 配置。
- **战甲配装**：支持光环、Exilus、普通 MOD、赋能、源力石、Helminth、活化、条件效果、容量和技能面板计算。
- **目标模拟**：支持本地敌人目录、自定义防御、等级缩放、钢铁之路、卓越者、超宏护盾、护甲削减、爆头和多种伤害口径。
- **本地素材**：卡图、边框、极性、战甲头像、技能图标和数据均随项目提供；配置可导入/导出，并兼容 Warframe Rabbit 紧凑格式。
- **明确降级**：未覆盖的运行时脚本、投射物组件或条件机制会保留 `unsupported` / `skipped` 诊断，不用猜值冒充精确结果。

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

## 数据更新

武器、MOD、赋能、敌人、战甲和技能数据必须从同一游戏 build 整体刷新，不能混用不同版本。来源锁、生成顺序和严格审计说明见 [DATA_PIPELINE.md](DATA_PIPELINE.md)。

完整来源审计（需要来源锁列出的原始输入；运行和打包不需要这些输入）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\update-data.ps1
```

## 项目结构

```text
app.py                 本地 HTTP 服务与 API
frontend/              中文 Web UI 与本地素材
vendor/wfarsenal/      配装、伤害和战甲计算内核
data/                  冻结数据、来源锁与运行 sidecar
tools/                 数据生成与审计工具
build-portable.ps1     Windows 便携包构建脚本
DATA_PIPELINE.md       数据来源和更新流程
THIRD_PARTY_NOTICES.md 第三方来源与授权说明
```

## 许可

未另行标注的项目源代码采用 [GNU Affero General Public License v3.0](LICENSE)，SPDX 标识为 `AGPL-3.0-only`。

Warframe 名称、图像、图标和其他 Digital Extremes 素材不因本项目的代码许可而被重新授权；第三方组件和素材继续适用各自条款，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
