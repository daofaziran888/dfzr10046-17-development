# 维链工坊 · 维度建模与缓慢变化维加工平台

面向维度注册、缓慢变化维拉链、一致性维度核对、事实表装配、代理键生成、维度退化、迟到事实回补、汇总层派生、指标口径绑定与维度快照发布的数仓维度建模加工平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/routers/handoff.py   粒度声明交接副本：出档/签收/补正/离线材料
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/grain_handoff.py   交接副本与汇总层签收待办领域服务
│   ├── app/services/handoff_material.py 快照/哈希/离线凭据纯函数（无 store 依赖）
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── frontend/
│   ├── src/components/GrainHandoffPanel.vue    粒度声明侧：出档/修订/补正
│   ├── src/components/SummaryHandoffPanel.vue  汇总层侧：签收待办采用/退回
│   └── ...
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8003/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5176/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8003`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 维度建档 | `dim_entry` | 维度条目 | 维度编号、维度名称、业务主键 |
| 拉链加工 | `scd_chain` | 拉链记录 | 拉链编号、所属维度、代理键 |
| 代理键生成 | `surrogate_key` | 代理键段 | 键段编号、所属维度、键段起点 |
| 一致性核对 | `conform_check` | 核对条目 | 核对编号、基准维度、对照维度 |
| 事实装配 | `fact_assemble` | 事实批次 | 批次编号、所属事实表、度量列集合 |
| 退化维度 | `degenerate_dim` | 退化维条目 | 条目编号、所属事实表、退化字段 |
| 迟到事实 | `late_fact` | 迟到记录 | 记录编号、所属事实表、业务发生日 |
| 汇总层派生 | `summary_layer` | 汇总条目 | 汇总编号、来源事实表、汇总粒度 |
| 粒度声明 | `grain_declare` | 粒度声明 | 声明编号、所属事实表、一行代表 |
| 度量目录 | `measure_catalog` | 度量条目 | 度量编号、度量名称、计算表达式 |
| 指标绑定 | `metric_bind` | 绑定关系 | 绑定编号、指标名称、引用度量 |
| 维度快照 | `dim_snapshot` | 快照版本 | 快照编号、所属维度、快照日期 |
| 层级路径 | `hier_path` | 层级路径 | 路径编号、所属维度、层级名称 |
| 多值桥接 | `bridge_link` | 桥接条目 | 桥接编号、所属事实表、关联维度 |
| 属性失效 | `attr_decay` | 失效条目 | 失效编号、所属维度、属性名称 |
| 装载窗口 | `load_window` | 装载窗口 | 窗口编号、所属事实表、窗口起点 |
| 重跑任务 | `reprocess_task` | 重跑任务 | 重跑编号、触发原因、影响事实表 |
| 装配质量闸 | `quality_gate` | 质量闸条目 | 闸口编号、所属事实表、校验项 |
| 血缘关系 | `lineage_edge` | 血缘边 | 血缘编号、上游对象、下游对象 |
| 维度发布 | `dim_publish` | 发布版本 | 发布编号、所属维度、发布版本 |
| 建模审计 | `model_audit` | 审计条目 | 条目编号、操作类型、操作对象 |
| 源端抽取 | `src_extract` | 抽取批次 | 抽取编号、来源系统、抽取范围 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 粒度声明交接副本（跨模块签收流程）

粒度声明原本只有普通下载，缺少给汇总人员核对、修订、签收的交付凭据。新增「声明交接副本」
把制单员（粒度声明 `grain_declare`）与汇总员（汇总层派生 `summary_layer`）串成一条留痕流程：

1. **出档**：制单员把声明当日内容冻结成不可变出档件（出档号 `HD-<声明号>-NN`，含快照与
   内容哈希），同时在汇总层派生一单一笔「签收待办」。出档与声明编辑共用
   `HANDOFF_LOCK`，两个修订不会拼接进同一份出档。
2. **离线凭据**：每个出档件在出档时渲染一份自包含 HTML（内联样式、无外部依赖），可离线
   打开；声明页和汇总页凭同一个出档号下载到的始终是同一份字节，后续修订不改变旧材料。
3. **签收**：汇总员按声明号 + 出档号「采用」或「退回」。退回必须登记具体原因。
4. **冲突一致规则**：汇总员已打开旧副本尚未采用、建档员又保存新版出档时，旧待办进入
   「冲突待决」而不是被静默关闭。两边界面与执行共用同一规则——要么「采用旧口径」（新待办
   登记去向后作废），要么「回到新副本」（旧待办登记去向后作废、新待办继续办理）。采用
   决定只绑定一个出档号，两个版本不共享一笔决定；已采用结果始终可回查。
5. **补正**：制单员按被退回的出档号发起补正（`FX-<声明号>-NN`），落实修订后确认，另发
   新出档件并保留 `父出档号` 链路；一个退回件只允许一条补正链。

专用接口挂在 `/api/grain-handoff/...`（见 `app/routers/handoff.py`），既有普通清单
（`/api/grain_declare` 及其 CSV 导出）保持不变。

领域：数据工程
子方向：数仓与数据湖
