# 旧配置恢复与敌人图标（2026-09-28）

## 原因与修复

截图中的 `mods[2].path is an unreleased tier variant` 来自旧配置第 3 槽。旧版本允许选择 `/Lotus/Upgrades/Mods/Rifle/Expert/WeaponToxinDamageModExpert`（10 级内部变体）；清理目录后后端正确拒绝它，但前端恢复保存配置时仍原样提交旧路径，缺少版本迁移。

恢复本机配置、切换配置槽、导入 JSON 或 Rabbit 配置时，统一经过 `migrateLegacyBuildConfig`。只有当前后端核验排除、且有可用正式版本的精确路径可以迁移（本次 52 条）。示例替换为 `/Lotus/Upgrades/Mods/Rifle/WeaponToxinDamageMod`：旧等级高于 5 时降到正式上限 5；0–5 级保持原等级。空等级按正式版本满级。未知路径、非整数/负等级、正常卡的越界等级均交给原校验，不猜路径，不解禁内部变体。

- 保留槽位、紫卡、极化、赋能和灵化选择。
- MOD、功能槽及必选/禁用限制使用同一精确映射；去重相同限制项。
- 原始条目、路径和等级保存在配置 `legacyModMigrations` 中，保存/导出/重载继续保留；重复打开不重复迁移。
- 页面持续显示迁移说明与等级变化，正式卡数值重新计算。
- 直接调用解算 API 仍拒绝未发布变体或非法等级；没有建立宽松别名。

## 合入副对话的敌人图标

带入 `enemy_assets.py`、`frontend/enemy-images.js`、原生图标继承清单、874 张独立本地 PNG、同步工具、相应样式/目录接口与测试。全部文件 SHA-256 与清单一致且可完整解码。运行时仅读本地资源，无外部下载。

源清单包含 1861 个敌人记录：995 精确图标、758 继承图标、107 缺失、1 通用原型。当前可选目录 1351 个敌人中 1253 个能显示本地图标；其余明确回退为派系占位，不拿通用原型冒充专属图片。

副对话的 bot 工程发布/ZIP 工作不在本轮验证范围。原先未提交的分片证据与本轮无关的中间报告保留原状。

## 验证

- 115 项测试通过：旧配置迁移、所有可迁移路径、合法低等级、未知路径与非法等级、原记录保留、重复恢复、后端严格校验、HTTP 静态资源、874 张图片哈希/解码、既有 MOD/引擎回归。
- 浏览器独立本地端口复现旧配置，启动后第 3 槽迁移为污染弹匣 5 级，实时结果成功。保存后重新加载仍成功，迁移历史保持 1 条。
- 实际页面检查迁移提示、卡片等级与实时数值；敌人选择器搜索枪兵，26 张实际图片完成加载，另 1 个缺图项保留派系占位。
- JavaScript 语法检查通过。未进行 EXE 重打包或游戏内行为验收。

证据：`docs/evidence/legacy-config-icons-20260928/verification.json`、`regression.txt` 及两张浏览器截图。

```powershell
python -m pytest -q tests/test_legacy_build_migration.py tests/test_catalog_tier_admission.py tests/test_enemy_assets.py tests/test_spread_events.py tests/test_native_multipart_events.py tests/test_new_items_landing.py tests/test_generated_build_comparison.py tests/test_nonmelee_catalog_audit.py
node --check frontend/build-config-migrations.js
node --check frontend/enemy-images.js
node --check frontend/app.js
```
