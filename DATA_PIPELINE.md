# 数据维护指南

## 常用命令

在仓库根目录运行，要求 Python 3.11+。运行现成数据和构建 EXE 不需要原始输入，也不依赖其他源码仓库。

```powershell
# 验证当前冻结数据、版本和引用的素材
python tools/data_pipeline.py check

# 安装仅用于数据重建的图像依赖
python -m pip install -r tools/requirements-pipeline.txt

# 创建本地输入配置，然后填写实际输入位置
Copy-Item tools/pipeline-inputs.example.json .local/pipeline-inputs.json

# 生成并验收候选快照，不切换当前数据
python tools/data_pipeline.py prepare --config .local/pipeline-inputs.json
```

首次创建配置前可用 `New-Item -ItemType Directory -Path .local -Force` 创建目录。已有配置不要重复覆盖。`tools/update-data.ps1` 是同一入口的 PowerShell 包装，默认执行 `check`。

## 输入约定

配置中的 `build` 是整套输入所属的游戏 build。`inputs` 的相对路径以配置文件所在目录为基准；也可使用绝对路径。本地配置和原始输入放在忽略提交的 `.local/` 中。

| 输入键 | 内容 |
|---|---|
| `rawRoot` | 目录名等于 build，含 `Packages.bin`、`packages/` 和 `dump.json`；后者的 `buildLabel` 必须一致 |
| `languages` | 国际服 `en.json`、`zh.json`，格式为本地化键到字符串的 JSON 对象 |
| `fontRoot` | 同一 build 的技能 `.lua_B` 与 `.lua_H` 导出，保留资源目录结构 |
| `wikiSnapshot` | Wiki 页面 JSON 快照，含正文及标题或原始 URL |
| `warframeItems` | warframe-items 的 `data/`，含 `json/Mods.json`、`Warframes.json`、`Arcanes.json`、`i18n.json` 和 `img/` |
| `modIndex` | MOD 元数据 JSON 数组，使用 `RabbitID`、`UniqueName`、`NameEn`、`NameZh`、`Type`、`Polarity`、`Image` 等字段 |
| `weaponIndex` | 武器及部件元数据 JSON 数组，使用 `UniqueName`、`NameEn`、`NameZh`、`VariantType` 等字段 |
| `enemyExport` | Public Export Plus 的 `ExportEnemies.json` |
| `artRoot` | 官方图像树，保留 `Lotus/...` 相对路径 |
| `completeArtRoot` | 完整官方图像树，含槽位、适配器和 Forma 图标；完整时可与 `artRoot` 相同 |
| `menuIcons` | 含 `IconStance.png`、`IconExilus.png`、`IconArcane.png` 的目录 |
| `umbraForma` | Umbra Forma PNG 文件 |
| `companionMods` | Companion 的 `Resources/common/mods/`；同级 `icons/polarityIcons/` 也需保留 |
| `modframeRoot` | 补充卡框图层目录 |
| `zaws` | 已核对当前 build 的 Zaw 部件表，必须含匹配的 `buildLabel` 或 `gameBuild` |
| `incarnonDefaults` | 可选，已核对当前 build 的灵化默认路线表 |
| `overframeSchema` | 可选，替换随仓库提供的技能字段 schema |
| `stanceTable` | 可选，替换随仓库提供的 Wiki 架势 Lua 表 |

这些是文件输入，不是对某个工程目录布局的要求。元数据索引需保留完整字段，不要仅从上表挑选字段重新生成。

Packages 和 Font 的客户端容器提取由 Warframe-Exporter-CLI 等提取工具完成；本入口消费已提取的原始数据，不负责安装游戏、下载社区快照或运行外部提取器。核心导出、继承解析、本地化合并和 Kitgun 生成模块已随仓库提供，无需预先生成另一工程的 `data/export/`。

客户端文件、语言表和 Font 必须来自同一 build，不能通过改目录名或标签混用。社区快照固定版本后再运行，生成过程中保持输入不变。来源锁保存逻辑输入名和哈希，不保存机器目录。

## 生成与检查

`prepare` 的执行顺序：

1. 检查配置、原始输入和版本，创建独立暂存目录。
2. 从 Packages 生成武器、战甲、MOD、赋能、敌人和核心 manifest。
3. 生成 Kitgun、Riven 模板、敌人补充数据、灵化文本、架势和功能槽数据。
4. 生成战甲技能数据，提取 Font 字段，计算差异并合并可确认数值。
5. 生成卡框并同步素材。
6. 更新候选来源锁，验证来源、导出记录、版本、技能字段、素材引用及运行时计算。
7. 为整套数据和素材生成 `snapshot.json`，将候选标记为可启用。

成功时输出 `Prepared: <候选目录>`。候选位于 `.local/pipeline/`，日志位于候选目录的 `.local/logs/`，完整审计报告为 `.local/source-audit.json`。

任一步失败，退出码非 0，当前活动数据不变。修正输入后重新执行 `prepare`；失败目录仅用于检查，不要手动补齐 `snapshot.json` 或将其启用。

检查候选产物：

```powershell
python tools/data_pipeline.py --root <候选目录> check
```

检查当前数据及其原始来源：

```powershell
python tools/data_pipeline.py check --sources .local/pipeline-inputs.json
```

普通 `check` 不要求原始输入。`check --sources` 额外检查配置中的来源及锁定哈希，不会自动更新来源锁。审计通过也不等于所有游戏机制均已实现；未知字段和未覆盖机制保留诊断。

## 试用、启用与回滚

先将候选打包到独立输出目录，无需启用它：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-portable.ps1 -Snapshot <候选目录> -OutputDirectory .local/artifacts/candidate
```

试用候选 EXE，检查紫卡分析、武器配装、战甲配装和图片。确认后启用：

```powershell
python tools/data_pipeline.py activate <候选目录>
```

启用前会重新验证完整文件清单、内容哈希和产物一致性。数据与素材复制到 `data/snapshots/<版本标识>/` 后，才原子替换根目录的 `data/source-lock.json`。旧数据不删除；写入失败不会切换到半套数据。多个启用或回滚操作互斥。

命令输出 `Rollback file: <备份文件>`。需要恢复时：

```powershell
python tools/data_pipeline.py rollback <备份文件>
```

备份位于 `.local/pipeline/backups/`。回滚同样验证目标数据后再切换，并生成撤销此次回滚的备份。

**启用或回滚后重启应用。** 已运行的进程继续使用启动时选定的数据和素材，不做热切换。`WF_RIVEN_BUILD` 不再允许选择与活动快照不同的导出目录。

## 构建与发布

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-portable.ps1
```

构建前自动验证并整理选定快照，只打包该版本的数据和素材，不包含原始输入、回滚备份或其他历史快照。默认输出为 `.local/artifacts/release/Warframe-Weapon-Loadout-Build-win-x64.exe` 及其校验文件。

发布源代码时，活动来源锁与其引用的 `data/snapshots/<版本标识>/` 必须一同提供；初始平铺数据布局仍可运行。不要只提交活动指针而遗漏快照。不要手改已经验收的快照，修改数据应重新准备候选。

## 回归检查

```powershell
python -m unittest discover -s tools -p test_data_pipeline.py -v
python tools/data_pipeline.py check
python tools/check_runtime.py
```

检查覆盖输入格式、版本路径、候选篡改拒绝、指针写入失败、启用、回滚及单版本打包。测试使用临时工作副本，不切换当前项目数据。
