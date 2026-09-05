# 数据维护指南

## 选择操作

| 操作 | 所需输入 | 入口 |
|---|---|---|
| 运行现有数据 | 仓库自带的 `data/`、`frontend/` 和计算内核 | `python app.py` |
| 构建 Windows EXE | 同上，加 PyInstaller | `build-portable.ps1` |
| 审计来源与产物 | 冻结数据及来源锁列出的全部原始输入 | `tools/update-data.ps1`，不加 `-Apply` |
| 更新游戏数据 | 同一客户端 build 的原始输入、上游核心导出及补充数据 | 配置来源后执行 `tools/update-data.ps1 -Apply` |

运行和构建不需要重新提取客户端，也不需要其他项目目录。完整数据更新仍依赖外部提取器和素材输入；本仓库没有从游戏安装目录自动获取全部输入的入口。

## 数据布局

- `data/source-lock.json`：`activeBuild`、来源位置、版本、哈希和派生器哈希。
- `data/export/<build>/`：武器、战甲、MOD、敌人、赋能、模块化武器和补充导出。
- `data/*.json`：架势、功能槽、显赫武器、战甲技能及技能字段派生数据。
- `frontend/assets/`：界面需要的图片和素材索引。
- `.local/`：本地输入、暂存输出和审计报告，不提交到仓库。

核心导出与根目录派生数据必须属于同一 build。`WF_RIVEN_BUILD` 只选择核心导出目录，不会切换根目录派生数据或素材，不能用它代替完整数据集升级或回滚。

## 来源审计

在仓库根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\update-data.ps1
```

该命令不替换数据，但会写入 `.local/audit/source-audit.json`。审计包括来源是否存在、锁定哈希、产物 build、技能字段覆盖及派生器一致性。

也可指定 build 和报告位置：

```powershell
python tools/audit_data_pipeline.py --build <build> --output .local/audit/source-audit.json --strict
```

以退出码和报告的 `errors` 为准。没有原始输入的普通克隆会出现 `required source missing`，这不表示随仓库提供的程序无法运行。不要通过删除必需来源或修改哈希来消除审计错误；先核对输入及版本。

## 准备更新输入

Python 3.11+ 用于数据脚本，卡框图像生成另需 Pillow 和 NumPy。准备以下输入后再执行更新：

| 输入 | 要求 |
|---|---|
| 核心导出 | `weapons.json`、`warframes.json`、`mods.json`、`enemies.json`、`arcanes.json`、`manifest.json`、`zaws.json`，build 标签一致 |
| Packages | 同一 build 的 `Packages.bin` 和展开的 `packages/` 树 |
| 官方本地化 | 国际服 `en.json`、`zh.json`，保留原始版本信息 |
| Font 脚本 | 同一客户端 `B.Font/H.Font` 导出的技能脚本及配对头文件，保留资源目录结构 |
| 社区结构化输入 | warframe-items 的 `data/`、Wiki 清洗快照、敌人补充导出、武器及 MOD 素材索引 |
| 图像输入 | 官方战甲和 MOD 图像、Companion 卡框素材、补充卡框图层 |
| 冻结补充表 | 技能字段 schema、架势表、Zaw 部件及可选灵化默认路线策略 |

上游核心提取器必须提供 `wfarsenal.packages`、`wfarsenal.extract` 及其依赖。`tools/generate_kitguns.py --source-root` 接收这个提取器项目根目录，并读取其 `src/` 和 `data/raw/<build>/`。仓库内的 `vendor/wfarsenal` 是运行时计算内核，不能替代该提取器。

不要混用不同客户端版本的 Packages、Languages 和 Font。社区快照固定到具体版本或哈希；游戏数值、字段模式和默认路线策略分别核对，不将社区默认配装当成游戏基础数值。

## 配置输入位置

`tools/update-data.ps1` 当前使用维护环境的默认目录，不提供统一的输入根目录参数。在独立工作副本中执行完整更新前，需调整脚本中的 `$wfArsenal`、`$sourceExport`、`$rawPackages`、`$languages`、`$warframeItems` 和 `$blackcat` 绑定，并同步检查 `data/source-lock.json` 中的来源位置。

显式参数只能覆盖以下输入：

| 参数 | 含义 |
|---|---|
| `-Build` | 待生成的新 build；目标导出目录必须不存在 |
| `-FontRoot` | Font 导出根目录，更新时必填 |
| `-WikiSnapshot` | Wiki 清洗快照目录 |
| `-EnemyExport` | 敌人补充导出 JSON |
| `-SkipAssets` | 跳过最后的 MOD 素材同步阶段，不等于禁用所有图片写入 |
| `-Apply` | 生成产物并更新活动数据；不加时只审计 |

还需向下游调用传入实际素材路径：`generate_warframe_data.py` 的 `--rabbit-assets`，以及 `sync_mod_assets.py` 的 `--rabbit-root`、`--companion-mods`、`--warframe-items`、`--warframe-items-img`、`--i18n`、`--lang`、`--modframe-root`。只修改来源锁不会自动重定向这些生成器。各脚本的 `--help` 列出接受的参数。

本地输入目录不要提交；来源记录使用可移植路径，避免写入用户名或绝对机器路径。

## 执行更新

在独立工作副本中操作，保留上一版完整数据和素材。当前更新入口会在最终审计前复制部分派生数据并修改活动 build，失败时不会自动回滚，不要直接对正在运行的分发目录执行。

配置完来源后，从该工作副本根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\update-data.ps1 `
    -Build <new-build> -Apply `
    -FontRoot <font-export-root> `
    -WikiSnapshot <cleaned-wiki-root> `
    -EnemyExport <enemy-export-json>
```

脚本的处理顺序：

1. 检查输入及 build，复制核心导出和可选灵化策略。
2. 生成 Kitgun、Riven 模板、敌人补充数据和灵化文本。
3. 生成架势、功能槽、显赫武器及战甲数据。
4. 提取技能字段，生成差异，再将唯一匹配的数值写入战甲数据。
5. 同步素材，更新来源锁和派生器哈希，执行严格审计。

任一步失败就停止发布，检查错误及 `.local/temp/data-update-<build>/` 的输出。不要只改 `activeBuild` 或反复覆盖新 build 目录继续发布。

## 验收与发布

1. 严格审计退出码为 0，检查报告中的警告、缺失字段、未知升级类型和关联失败。
2. 对比新旧记录 ID、中文名称、武器开火模式、Riven 资格与倾向、技能等级数值、模块化部件和图片索引。未覆盖的机制保留明确诊断。
3. 在候选副本运行 `python app.py --port 0`，检查紫卡分析、武器配装和战甲配装，确认素材可加载。
4. 执行 `build-portable.ps1`，将生成的 EXE 单独放入空目录启动，核对目录 API、计算结果及静态素材。
5. 将 `data/`、`frontend/assets/` 和来源锁作为同一个版本提交并发布。回滚时恢复上一版完整数据与素材，或直接使用上一版 EXE。
