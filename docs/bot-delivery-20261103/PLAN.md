# Bot缓存交付与机制收口（临时工作计划）

2026-11-03。Portable起点8c6a595；Bot使用远端bb3ae5c2隔离工作区，原Bot目录754提交落后且含无关dirty，保持原样。总计算并发≤10；禁止提前全量烘焙。

|事项|状态|
|---|---|
|横痃重炮负变焦H范围与跨家族同类审计|已修：源新增普通H被fusion-only刷新遗漏；H base41.9940009；原截图与Larkspur生成包校验通过|
|可静态推进的剩余远程/同伴消费者|Deconstructor回收限制继续追；其余按已证据边界收口|
|Bot新版运行时移植与显赫影响|已补3模块delayed_radial_events/projectile_lanes/zymos；658targets=635普通+23组合，显赫交集0|
|性能/终止性预审|原核心56已有用例与7个180s replay通过，无native fallback；现代Bot deep pipeline也已审：98route与statics顺序池，取消/原子提交/完整性检查；3600秒下一heartbeat超时不是任意卡死硬杀|
|冻结引擎/数据/worker身份与小规模真实预检|待上述修正完成|
|唯一一次Bot完整缓存生成|待冻结；Bot自有deep+灵化路线+2/3正面与伤害参考，≤10计算worker|
|缓存覆盖/真实截图/致命负面/组件manifest验证|待烘焙|
|Portable与Bot远端推送|待验收；仅相关文件，Bot原工作区不动|

增量边界：本次共享引擎改变，旧数值缓存不跨指纹复用；冻结后的有效预检目标直接复用至同一次完整烘焙，最终归档供未来data-only增量。GPU现有production收益0，未经完整评分kernel不得声称加速。

未覆盖游戏场景与独立显赫技能分支不借普通射击模拟擅自开放。无新增一次性测试文件，尽量扩充既有核心用例。

## 同步前已确认

- 最新Bot main bb3ae5c2，隔离分支codex/bot-mechanics-cache-20261103。源目录未动；临时checkout缺失blob已下载，未清空用户dirty。
- H=Zoom，CO=Corrosive。源LotusShotgunRandomModRare SHA a301aad4e5a59df91a4d7309a1e428e849f99d62f7000a6925b45de0fdfb1061，raw0.0046660001，range34.01514–41.57406（3+1、1.2）。刷新器补本家族新增普通行，非跨家族借值；保留NotSentinel约束。
- FiredUp重用已确认的raw00 JUMPBACK完整解码：8protos unknown0/invalidJumps0；P5只是Wait(1000000)回环，未引入新的cache清除。全局20bbc0cd生命周期仍无静态闭合，不据此擅自改过期后续增伤。普通Bot预设不装备守护本体MOD，这条不改变此次默认烘焙输入。
- 组合装配筛选在完整缓存之前进行，2960套fixed-build screen，23heads/slots各取前4+seed完整搜索。属于缓存的上游输入生成，完成后才冻结。

## 静态续查收窄

- Mandonel独立场此前已实现：7秒/.2秒、初始两包与neutral通知路径；剩余yield帧相位与实际覆盖，不能再次重复添加一份场伤害。
- FiredUp完整脚本解码现已无unknown；缺全局存储生命周期，保留明确expiry-resume提示，默认Bot未选守护本体MOD。
- Cortege本轮闭合两处回环、共享帧时钟与12秒自清理；主包纯Heat范围/持续触发、特殊instigator与实际overlap尚未完成，不擅自按3field×12/13tick补满DPS。
- Deconstructor继续闭合状态7/20及slot释放；当前已证明maxActive3和严格elapsed>1且双距离>=29.5才请求回收，timer1不是1秒返还，不固定扣射速。

组合刷新已完成：6worker/274秒，2960套筛选、23套赢家，9套装配部件发生变化（8 Zaw+1副手Sporelacer）；已写入源文件，随后完整Bot缓存以这份输入计算，不沿用旧装配分数。

## 冻结前修正收口

- 普通紫卡模板canBeBuff/canBeCurse与NotSentinel由实际输入、分析推荐、配装页推荐共用过滤；Bot缺缓存neutral展示同样过滤。未凭DamageTypes/NotGrimoire字段名扩大拒绝。
- Deconstructor maxActive3、状态20 FIRE_DISABLED、状态7 REFIRE_WAIT、保存behavior-ID的移除转发均闭合；恢复1/effectiveFireRate携带非正timer余量。写入source lifecycleContract和精准unmodeled诊断，真实flight/catch缺失不伪造固定回收时间。
- 同伴边界用例由全24武器×两状态缩为4个真实Riven family代表×两状态，删除40个重复展开用例；增加H真实回归1个，预计本轮净减39。
- Bot service/rarsenal、domain/riven、app/ocr与feature/ocr已通过。隔离工作区补齐sparse checkout遗漏的模板资源后feature/ocr通过；这是checkout范围问题，无业务代码修改。
- 本轮数值修复与已知静态调查到此冻结。未完成的火场Heat duration/空间接触和显赫独立技能仍列明，不声称全游戏校准。
