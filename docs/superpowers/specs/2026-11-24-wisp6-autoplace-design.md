# wisp6 自动布局 Demo — 设计文档 v1.1

> 版本：v1.2 · 2026-11-24
> 状态：待评审（评审通过后进入实施计划）
> 适用环境：Altium Designer 26.11.1.5（本机 `D:\Altium\AD26\X2.EXE`）、Windows、Python 3.13（`E:\python\py313`）
> 取代：`2026-11-24-spiritlevel-autoplace-design.md`

## 0. v1.1 修订记录（回应 builder 评审）

| # | 评审问题 | 本版处理 |
|---|---|---|
| 1 | “锁定”混用 AD LOCKED / PRIMITIVELOCK / YAML 锚点 | 拆成 `source_locked` 与 `anchor_locked`；忽略 `PRIMITIVELOCK`；`anchor_locked = source_locked ∪ yaml_anchors` |
| 2 | 双面板碰撞层语义不清 | 同面碰撞；THT 焊盘双面占位；组件自带 keepout 纳入；基线误报必须先校准到 0 |
| 3 | 11 个 region 被误当 keepout | 按 layer/kind 分类：铜区不是障碍；keepout/板挖空才是；YAML 人工覆盖并记录来源 |
| 4 | P0 范围与 MCP 起点不清 | P0 第一天先锁定解释器、安装/探测桥接；ScriptBridge 只补缺口，不要求 10 方法全对等 |
| 5 | 清铜副本、预览、DRC 角色未定 | 清铜副本为 v1 唯一形态；HTML/SVG 预览；DRC 仅信息性，独立几何校验才是硬门禁 |
| 6 | 10 分钟预算口径矛盾 | 全流程 3 候选 ≤15 分钟，共享预处理；每簇 ≤20 s；超时降级并记录 |
| 7 | 锚点与数值未定 | 锚点原则由用户确认；具体清单 P1 由工程师签字；数值用 AD 启用规则，demo 默认值单独标记 |
| 8 | 人力/工期假设未写 | 当前用户兼职推进；P1 锚点/约束签字、P2 布局盲评、最终验收三个检查点需要工程师，合计约 1–2 人天；工期按投入顺延 |
| 9 | 桥接重复建设 | 主通道改为已安装、已验证的 `eda_agent` 0.8.1；自建 `scripts/ad_bridge.py` 作废；`altium-mcp` 仅作备用 |
| 10 | 产品形态未定 | **Web 控制台**：FastAPI 后端 + 浏览器页面；单用户、本地 Windows |
| 11 | 集成方式未定 | **MCP 服务**调用 `eda_agent`；实验脚本可先用 Python API，产品层必须走 MCP |
| 12 | 主 demo 板未定 | **wisp6 65 器件为主**；Buck 6 器件仅作冒烟/回归 |

## 1. 意图与为什么

做一个**硬件团队内部可用、可对外展示**的自动布局 demo，证明一条完整、可审计的闭环能在真实 AD26 工程上跑通：

```text
读取真实板 → 统一模型 → 硬/软约束 → 确定性求解 → 多候选预览
→ 人工审批 → 写回隔离副本 → 回读校验 → 快照可恢复 → 对比报告
```

不是为了替代硬件工程师，也不是做整板布线/SI/PI/EMC 签核。目标是让工程师拿到一个**满足明确几何约束、可继续精修**的初版布局，并且整个过程可解释、可回退。

### 主 demo 板：wisp6 Basic Node

- 来源：`https://github.com/wisp/wisp6-hardware`，已下载到 `third_party/wisp6-hardware/`
- 许可证：**BSD-2-Clause**（Copyright 2014 University of Washington），可对外展示
- 工程：`Basic Node/wisp-6.0V2.PrjPcb` + `wisp-6.PcbDoc` + 4 个 SchDoc
- 规模（调研阶段用独立解析器核实，P1 以本项目模型为准）：**65 器件 / 4 层 / 63 网络 / 已布线**
- 自带库：**8 个 PcbLib + 2 个 SchLib**（`libraries/`），无需另找封装/原理库
- 变体：`wisp-6-dipole.PcbDoc` 可作为第二块回归板

### 1.1 产品形态

- **Web 控制台**：FastAPI 后端 + 浏览器页面；单用户、本地 Windows。页面展示候选布局、硬检、分数、审批和写回结果。
- **集成**：通过 **MCP 服务**调用 `eda_agent`；实验脚本可先用 Python API，产品层必须走 MCP。
- **Buck 6 器件**：只作 5 分钟冒烟和回归，不作为主 demo。

### 内测板：SpiritLevel-SL1（仅内部）

- `D:\Altium\AD26\Examples\SpiritLevel-SL1\`，115 器件 / 2 层 / 126 网络
- 受 Altium EULA 约束，**只用于内部压力测试，不进入对外演示/公开材料**

## 2. 目标 / 非目标 / 反目标

### 目标

- G1：把真实 PcbDoc 读成统一模型（器件、焊盘、网络、板框、区域、面、旋转、锁定）。
- G2：对 wisp6 的可动器件生成 ≥3 个满足全部硬约束的候选布局。
- G3：预览 + 人工审批后写入**隔离副本**，回读校验，文件可重开，快照可恢复。
- G4：输出每个器件“为什么放这里”的依据与软目标分数。
- G5：用分层求解把 65 器件跑通；SpiritLevel 115 器件作为内部上限测试。

### 非目标

- 不布线、不做 SI/PI/EMC/热仿真、不做可制造性签核。
- 不移动已布线铜；只在“未布线副本”上做布局。
- 不做全自动无人审批；写入前必须人工确认。
- 不让 LLM 输出坐标或编造毫米数值；v1 不引入 LLM。
- v1 不覆盖 wisp6 以外的板卡对外演示。

### 反目标（即使跑通也算失败）

- 布局“成功”但网表、焊盘映射或锚点器件被改动。
- 硬约束有违规却因为评分高而写回。
- 原板在几何模型下本身就大量“违规”，却用“0 新增”糊弄过去。
- 部分写入失败后没有快照、无法恢复。
- 把 DRC 通过或 HPWL 更低当作电气/制造合格证明。

## 3. 约束

- AD26 固定 26.11.1.5；记录小版本，不假设跨版本 API 一致。
- 写回只作用于工程副本；原工程目录只读。
- `MoveToXY` 不带走板级走线/过孔/铺铜；demo 前先在副本上清铜。
- 文件级快照 + 哈希 manifest；不依赖 AD Undo。
- `altium_monkey` 为 AGPL-3.0：只作为独立只读 CLI/进程使用，不复制进对外分发代码。
- `eda_agent` 0.8.1（Apache-2.0，已装在 `D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119\.venv`）是唯一主通道：桥、`layout_place`、DRC、写回验证都已具备。`altium-mcp` 仅作备用，不再自建 DelphiScript 桥。
- `eda_agent` 的 AD26 轮询循环必须先运行；P0 第一项是 `eda-agent relaunch --restart`，或在 AD26 里 File > Run Script > `Altium_API.PrjScr` > `Dispatcher.pas` > `StartMCPServer` > Run。
- 所有硬约束的毫米数值必须有来源，或明确标记为“demo 默认值，待工程师批准”。
- Python 解释器以 `E:\python\py313` 为准；P0 第一项就是锁定解释器并核对依赖（shapely/networkx/pydantic 已装，ortools 需装）。

## 4. 已考虑的方案与选择

| 决策 | 备选 | 选择 | 理由 |
|---|---|---|---|
| 对外 demo 板 | AD26 Examples / wisp6 / Pixhawk | **wisp6** | BSD-2 最干净；65 器件/4 层规模合适；自带库；可公开 |
| 内测板 | SpiritLevel / 其他 | **SpiritLevel** | 115 器件、2 层，EULA 内部可用；只做压力测试 |
| 求解架构 | 单体 CP-SAT / 分层 | **分层** | 65 器件单体 CP-SAT 易超时；分层可控、可复现 |
| 写回通道 | 第三方 MCP / 自建桥 / 离线写回 | **`eda_agent` 为主通道；`altium-mcp` 仅备用；不自建桥** | 桥、placer、DRC、写回验证都在 `eda_agent` 里；自建桥是重复造轮子 |
| 可动范围 | 全部 / 锁结构件 | **默认 `source_locked ∪ 机械约束件`；另提供全可动对比模式** | 真实设计里“能否移动”是工程约束，不是文件属性；全可动可作压力测试，不能当真实结果 |
| 产品形态 | CLI / Web / AD 插件 | **Web 控制台** | 用户选定；HTML 报告不够，团队要交互 |
| 集成 | Python API / MCP | **MCP 服务** | 低耦合、可替换；实验脚本可先用 API |
| 主 demo | Buck / wisp6 | **wisp6 65 器件** | 用户选定；Buck 仅冒烟 |

### 4.1 与多 Agent 框架的差异

| 维度 | 之前（Gemini 多 Agent 方案） | 现在（本方案） | 为什么改 |
|---|---|---|---|
| 编排 | LangGraph + 5 个自治 Agent | 确定性状态机 + 模块化流水线 | 可测试、可复现、可审计；Agent 对话不产生坐标 |
| 规则 | L3 > L2 > L1 无条件覆盖 | 三层来源，安全底线优先，冲突不自动裁决 | 制造/法规/芯片硬要求不能被单板偏好覆盖 |
| 布局 | Cypress / RL | 分层 CP-SAT + SA + Shapely | Cypress 非即插即用；65 器件不需要 RL |
| 写回 | Electronics_AI 唯一通道 | coffeenmusic MCP + 自建桥兜底 | 12★ 实验项目不能当唯一生产通道 |
| 知识 | Neo4j / VLM 前置 | v1 不用；P3 可选 | 先证明闭环，再谈知识图谱 |
| 人 | 自动闭环 | 3 个人工检查点 | 锚点、规则、布局质量必须工程师签字 |
| 范围 | 整板 8 周 | wisp6 65 器件先跑通 | 先小后大，避免架构先行 |

保留自多 Agent 方案的部分：职责分离、规则分层、Critic/复查、快照回滚。它们现在是**模块和人工门禁**，不是自治 Agent。未来若需要多板并行、规则挖掘、VLM 复核，可以在同一接口上增加 Agent 服务，核心流水线不变。

## 5. 系统架构

```text
AD26 工程副本
  │  McpBridge / ScriptBridge（读）
  ▼
统一模型 Board / Component / Pad / Net / Region / Constraint
  │
  ├─ NetworkX 网络图 + 聚类（功能簇）
  ├─ 硬/软约束编译（YAML + AD 规则 + 人工配置）
  ▼
分层求解
  1) 簇级 floorplan（粗网格 CP-SAT / 力导向）
  2) 簇内布局（CP-SAT 或 SA，≤20 器件/簇）
  3) 全局合法化（Shapely + hard-shove）
  4) SA 精修（固定种子、多起点）
  5) 评分与 top-3 候选
  ▼
独立校验（几何 + 回读 diff + DRC 探测）
  ▼
HTML/SVG 预览 → 人工审批 → 文件快照 → 写入副本 → 回读 → 报告
```

### 5.1 模块职责

| 模块 | 职责 | 关键约束 |
|---|---|---|
| `adapters` | AD26 读写、清铜、回读、DRC、快照 | 只写副本；失败不留半成品 |
| `models` | Pydantic Schema、单位、版本、哈希 | mm、封装原点、side、rotation、`source_locked`、`anchor_locked`、`geometry_source` |
| `geometry` | 板框、区域、封装保守占位、同面碰撞/距离 | Shapely；圆弧离散容差 ≤0.01 mm |
| `graph` | Component–Net–Pad 图、功能簇 | 排除高扇出电源/GND 造成假聚类 |
| `rules` | 硬/软约束、来源、冲突、审批状态 | 无来源数值不进硬约束 |
| `solver` | 分层布局、合法化、评分 | 固定种子；无解时报告冲突，不放宽硬约束 |
| `validation` | 独立硬检、回读 diff、DRC、基线对比 | 与求解器代码路径分离 |
| `execution` | 快照、写入、回读、恢复、审计日志 | manifest 记录输入/输出哈希 |
| `reports` | SVG 图层、HTML 报告、差异 | 每个器件可追溯约束与分数 |
| `workflows` | 显式状态机 | 可重试、有上限、可中断 |

### 5.2 EDA Adapter 最小接口

```python
class AdBridge(Protocol):
    def environment(self) -> dict: ...
    def open_project(self, path: str) -> str: ...
    def export_components(self, project_id: str) -> list[dict]: ...
    def export_nets(self, project_id: str) -> list[dict]: ...
    def export_regions(self, project_id: str) -> list[dict]: ...
    def clear_copper(self, project_id: str) -> dict: ...
    def apply_placements(self, project_id: str, moves: list[dict]) -> dict: ...
    def readback(self, project_id: str, refdes: list[str]) -> dict: ...
    def run_drc(self, project_id: str) -> dict: ...
    def snapshot(self, project_id: str) -> str: ...
    def restore(self, snapshot_id: str) -> dict: ...
```

`EdaAgentAdapter` 实现全部方法；`AltiumMcpAdapter` 仅作备用。`eda_agent` 的 import 只允许出现在 `adapters/` 与 `engines/` 内，`domain/models/rules/geometry/validation` 不依赖它。

### 5.3 依赖方向（高内聚、低耦合）

```text
domain/models/rules/geometry/validation   ← 纯 Python，不 import eda_agent / MCP
        ▲
engines（PlacementEngine 协议）           ← EdaAgentPlacer 是唯一调用 eda_agent.layout 的地方
        ▲
adapters（EdaPort 协议）                  ← EdaAgentAdapter 是唯一 import eda_agent.bridge / MCP 的地方
        ▲
workflows / reports / CLI                 ← 只依赖 domain 和 ports
```

- 新增引擎（OR-Tools、Cypress）或适配器（altium-mcp）通过注册表接入，不改流水线。
- `eda_agent` 的 IPC 细节、超时、版本差异、错误码全部封装在 `EdaAgentAdapter` 内。
- P0 的 `scripts/run_eda_place.py` 只是实验脚本，不属于产品分层。

## 6. 数据模型（v1 必需字段）

- `Board`：`board_id`、`outline_mm`（含圆弧离散）、`origin_mm`、`units`、`source_hash`、`copper_layers`、`side_count`。
- `Component`：`refdes`、`footprint`、`origin_mm`、`rotation_deg`、`side`、`source_locked`、`anchor_locked`、`body_polygon_local_mm`、`geometry_source`、`source_unique_id`。
- `Pad`：`pad_id`、`refdes`、`designator`、`local_polygon_mm`、`net_id`、`layer`、`side`、`plated`（THT 双面占位）。
- `Net`：`net_id`、`name`、`pad_ids`、`net_class`（可得时）。
- `Region`：`polygon_mm`、`kind`（copper/keepout/board_cutout/mechanical）、`layer/side`、`source`、`review_status`。
- `Constraint`：`rule_id`、`kind`、`severity`、`scope`、`targets`、`params`、`source_ref`、`review_status`。
- `Candidate`：`candidate_id`、`placements`、`hard_violations`、`soft_scores`、`solver_info`、`seed`。
- `Manifest`：输入/输出哈希、变更清单、工具版本、AD 版本、时间、错误。

坐标约定：内部统一 **mm**；器件 `(x, y)` 是封装原点；Pad 经旋转/翻面变换到板级；rotation 为逆时针角度；side 只有 top/bottom。

### 6.1 锁定语义（评审修订）

- `source_locked`：AD 文件里的 `LOCKED` 属性，只读，不由我们修改。
- `anchor_locked`：`source_locked ∪ configs/*.yaml` 里的锚点集合。
- `PRIMITIVELOCK`：只锁图元编辑，不代表器件不可移动；求解与校验都不使用它。
- 求解器只移动 `not anchor_locked` 的器件；校验器同时报告 `source_locked` 与 `anchor_locked` 两列。
- 如果工程师想移动一个 AD `LOCKED=TRUE` 的器件，必须在 AD 里显式解锁并记录；工具不会绕过。

### 6.2 什么能移动？

真实 PCB 里，“能移动”不是文件属性，而是工程约束：

- **机械/结构**：连接器、安装孔、天线、面板开孔对应的按键/LED——由外壳、线缆、装配决定，动了就装不进去。
- **电气关键**：RF 馈点、晶振、功率环路——通常有优选区域或相对位置要求，可作为硬区域约束或软约束，不必全部锁死。
- **可动**：去耦电容、电阻、小 IC、测试点——自动布局真正该摆的部分。

AD 的 `LOCKED` 只表示“编辑时锁住”，不等于工程上必须固定。v1 默认锁 `source_locked ∪ 机械约束件`；`--all-movable` 模式只用于对比和压力测试，不作为真实交付结果。

## 7. 约束（v1）

### 硬约束

1. `anchor_locked` 器件的位置、旋转、面不变。
2. 可动器件在**同一面**上的保守占位多边形不重叠，且满足配置间距；跨面 XY 重叠允许。
3. THT 焊盘按双面占位；组件自带 keepout（如 LCD 圆弧）纳入障碍。
4. 全部器件在板框内（含板边余量）。
5. 避开分类为 `keepout` / `board_cutout` 的区域；`copper` 区域不是障碍。
6. 器件面固定；旋转只允许配置集合（默认 0/90/180/270，连接器固定）。
7. 网表、Pad→Net 映射、器件数量不变。

### 基线校准（评审修订）

- P1 必须先用同一几何模型检查**原板**；如果原板出现大量“违规”，说明几何模型（保守 bbox/间距/层语义）错了，必须先修正模型，而不是用“0 新增”绕过。
- 目标：原板在几何模型下 0 违规（允许明确记录的近似误报，但必须逐条解释）。
- P2 的硬门禁是**绝对 0 违规**（在已校准模型下），不是“0 新增”。

### 软目标

- 关键网络加权 HPWL（电源/GND 低权重或排除）。
- 去耦电容到目标 IC 电源 Pad 的距离。
- LED/按键/连接器靠板边或保持原相对方位。
- 保留原布局的簇级相对位置（v1 强先验）。
- 局部余量与可维护性。

所有软权重放在 `configs/wisp6.yaml`，首版不宣称公司标准；用原板与人工方案对照后再校准。

### 7.1 工程师规则如何加入

规则不写在代码里，放在 `configs/wisp6.yaml` 与 `configs/rules/*.yaml`，由工程师维护和签字。

```yaml
- rule_id: R_DECAP_U1_MAX
  kind: max_pad_distance
  severity: hard
  scope: {board: wisp6, group: rf}
  targets: {movable: C12, movable_pad: "1", anchor: U1, anchor_pad: "VDD"}
  params: {max_distance_mm: 2.0}
  source_ref: {document: "...", revision: "...", page: 12, origin: engineer_approved}
  review_status: approved
  approved_by: "..."
  version: 1
```

流程：

1. 工程师写/改 YAML（后续可做简单表格/表单，不读代码）。
2. Rule Compiler 检查冲突、缺 Pad、无来源数值，输出 `effective_rules.json` + `conflicts.json`。
3. 只有 `approved` 的硬规则进入求解；`draft` 只作建议，不改变硬门禁。
4. 规则与板卡哈希绑定；规则变更触发重新校验。
5. P3 的 RAG/LLM 只能生成 `draft` 规则，必须工程师批准后才能升级为硬约束。

工程师不需要读代码，只看三样：规则/锚点清单、冲突报告、候选 HTML 预览。

## 8. 分层求解（65 器件，SpiritLevel 115 为上限）

### 8.1 预处理

- 建 `Component–Net–Pad` 图；高扇出电源/GND 降权。
- 聚类输入：网络邻接 + 位号前缀 + 封装类型 + 原布局邻近性。
- 目标 6–10 个簇，每簇 ≤20 个可动器件；锚点作为边界。
- 输出 `clusters.json`。

### 8.2 簇级 floorplan

- 粗网格 0.5–1.0 mm；簇包围盒为保守多边形。
- CP-SAT：`NoOverlap2D` + 板框/keepout + 锚点相对方位 + 簇间间距。
- 目标：加权簇间 HPWL + 与原布局簇位置偏差。
- 时限 30–60 s；超时回退力导向 + 合法化。

### 8.3 簇内布局

- 每簇 ≤20 器件，0.25–0.5 mm 栅格，CP-SAT optional intervals。
- 旋转集合按封装配置；关键网络朝向作为软目标。
- 时限每簇 ≤20 s；超时回退 SA。
- 去耦电容优先靠近目标 IC 电源 Pad（软约束）。

### 8.4 全局合法化与精修

- Shapely 同面检查；残余重叠用 hard-shove 推开，锚点不动。
- SA：微移、±90° 旋转、同封装交换；每步硬约束校验；固定种子，8 起点。
- 只接受硬约束可行解。

### 8.5 多候选与时间预算

- 3 个候选共享聚类与几何预处理，仅求解种子/权重不同。
- 质量优先：默认目标 15 分钟；质量模式不设硬上限，单次最长 60 分钟，超时后降级并记录。
- SpiritLevel 内测单次最长 90 分钟。
- 降级顺序：减少 SA 起点 → 减少候选数 → 放粗栅格；报告中记录“被丢弃的搜索预算”。

## 9. 独立校验

- V1 几何：同面 Shapely 相交、板框包含、keepout、锚点不变、Pad 距离、side/rotation 合法性；与求解器分离实现。
- V2 回读：器件数、位号、Pad→Net、网络数、面、旋转、坐标；非目标零变化。
- V3 DRC：**信息性**。先探测 `RunBatchDesignRuleCheck`；失败退模态；再失败用 `check_placement`。记录基线与增量，不把 DRC 当硬门禁。
- V4 对比：与原板布局比较关键网络 HPWL、间距、板边余量；只报告差异，不宣称更优。

## 10. 写回与回退

1. 复制整个工程目录到 `work/runs/<run_id>/project/`；记录文件哈希。
2. 在副本上清铜（仅铜层 track/via/polygon），保留板框、丝印、机械层、规则、keepout。
3. 求解与预览；人工审批候选。
4. 再次快照；批量写入副本；回读校验；保存重开。
5. 输出 `manifest.json`、`hard_check.json`、`candidate_scores.json`、`layout_diff.json`、`validation_report.html`。
6. 任一硬检失败 → 恢复快照并停止；不写原工程。

## 11. 分阶段与验收

以下 3–5 天 / 3–5 天 / 2–3 周是**工作量估算**，不是日历承诺。兼职推进（每周 2–3 天投入）日历时间约翻倍：P0 1–2 周、P1 1–2 周、P2 4–6 周；专职工程师加入后可压缩。

### P0｜写回生死门（3–5 天）

第 1 天先锁定解释器与桥接：

1. 锁定 `E:\python\py313`，核对 shapely/networkx/pydantic 版本，安装 ortools。
2. 用 `Buck-C2-20261119\.venv` 里的 `eda_agent` 读板、跑 `layout_place`、DRC；确认桥可用。
3. 不再安装/自建第二套桥；`altium-mcp` 只保留为文档化备用。
4. 复制 wisp6 工程到隔离目录，哈希全部文件。
5. AD26 导出器件清单，与 `altium_monkey` 解析交叉核对；确认 `LOCKED` / `Moveable` / `PRIMITIVELOCK` 语义。
6. 单器件移动 1 mm + 旋转 90°，回读、保存、重开。
7. 10 个器件批量移动，回读。
8. 副本清铜，统计删除/保留对象，保存重开。
9. 快照恢复，哈希比对。
10. DRC 能力探测（批量/模态/check_placement）。

通过标准：坐标/旋转误差 ≤0.01 mm 或 1 个内部单位（以实测为准）；网表/Pad 映射不变；锚点不变；文件可重开；快照可恢复；无部分写入遗留。

不通过：停止自动写回，降级“导出候选 JSON + 人工应用”。

### P1｜模型与校验器（3–5 天）

- 输出 wisp6 的 `board.json` / `components.json` / `pads.json` / `nets.json` / `regions.json`。
- 区域分类：区分铜区/keepout/板挖空/机械；人工覆盖写入 YAML 并记录来源。
- 实现同面 Shapely 校验器；注入合成重叠/越界/keepout 用例，验证检出。
- 对原板跑基线体检；几何模型必须校准到原板 0 违规（或逐条解释误报）。
- 产出 `configs/wisp6.yaml`（锚点、间距、旋转、权重），由工程师签字。

通过标准：校验器稳定检出注入错误；原板基线可解释；模型字段缺失明确标记而非猜测。

### P2｜求解与 demo（2–3 周）

- 先尝试 `eda_agent` 对 wisp6 65 器件的整板布局；失败或超时再加聚类分层。
- Web 控制台：FastAPI + 单页 HTML/JS，展示候选、硬检、审批、写回。
- MCP 客户端封装；实验脚本与产品层共用 `EdaPort`。
- 写回副本 + 回读 + 对比报告。

通过标准：硬门禁 0 违规；锚点与网表零变化；≥3 个可行候选；wisp6 默认 ≤15 分钟、质量模式 ≤60 分钟；文件可重开；快照可恢复；工程师认为可作为继续精修的初稿。

### P3｜可选

- LLM 角色识别与规则候选（带证据、可弃权）。
- 规则库/RAG 接入、更多板卡、完全自由重排（不保留原相对位置）。

## 12. 目录结构

```text
ai_pcb_mvp/
├─ configs/wisp6.yaml
├─ src/ai_pcb/
│  ├─ models/
│  ├─ adapters/          # mcp_bridge.py, script_bridge.py, offline_parser.py
│  ├─ geometry/
│  ├─ graph/
│  ├─ rules/
│  ├─ solver/            # cluster.py, floorplan.py, cp_sat.py, sa.py, legalize.py
│  ├─ validation/
│  ├─ execution/
│  ├─ reports/
│  ├─ web/               # FastAPI + 单页控制台
│  ├─ mcp/               # MCP 客户端封装
│  └─ workflows/
├─ tests/
│  ├─ fixtures/
│  ├─ unit/
│  └─ integration/
├─ third_party/wisp6-hardware/   # BSD-2，只读输入
├─ work/runs/                     # 副本、快照、日志、候选
└─ docs/
```

## 13. 风险与缓解

| 风险 | 触发信号 | 缓解/退出 |
|---|---|---|
| 写回破坏工程 | 回读不一致、无法重开 | P0 门禁；只写副本；文件快照；失败恢复 |
| 锁定语义错误 | 移动了 AD LOCKED 器件，或该锁的没锁 | `source_locked ∪ yaml_anchors`；P1 工程师签字 |
| 双面碰撞误判 | 原板在模型下大量重叠 | 同面检查 + THT 双面占位 + 基线校准到 0 |
| 区域分类错误 | 铜区被当 keepout，或真 keepout 漏掉 | 按 layer/kind 分类 + 人工覆盖 + P1 用例 |
| 65 器件求解超时 | 全流程 >15 min | 分层、并行簇、减少 SA 起点；记录降级 |
| 封装占位不准 | 无 Courtyard、bbox 含丝印 | 保守 Pad 包围盒 + 3D body 参考，标记 `geometry_source` |
| DRC 不可靠 | 批量调用失败/弹窗/上限 | DRC 仅信息性；独立几何硬检；基线/delta |
| AGPL 污染 | 对外分发包含 altium_monkey 代码 | 独立进程/CLI；只读；不复制代码 |
| 许可/合规 | 对外使用 AD26 Examples 或 CC BY-SA 工程 | 对外只用 wisp6（BSD-2）；SpiritLevel 仅内部 |
| 期望落差 | 认为“自动布局=可直接投板” | 报告明确“初稿、未布线、未做 SI/PI/EMC” |

## 14. 需要用户/工程师确认的事项

- **锚点原则**：默认 `source_locked ∪ 机械约束件`（连接器/天线/安装孔/面板开孔相关的按键与 LED）；具体清单 P1 由工程师签字。另提供 `--all-movable` 对比模式，仅作压力测试。
- **清铜副本**：v1 唯一形态；清铜保留板框/丝印/机械层/规则/keepout。
- **预览**：HTML/SVG 静态报告；是否必须同时在 AD26 内打开候选。
- **DRC**：信息性，不作硬门禁；独立几何校验为准。
- **时间预算**：质量优先，不设硬上限；默认 15 分钟，质量模式最长 60 分钟；超时降级并记录。
- **人力**：当前用户兼职推进；后续专职工程师只在三个检查点介入——P1 锚点/约束签字、P2 布局盲评、最终验收，合计约 1–2 人天。没有工程师签字时，demo 只能标注“技术演示，未经工程验收”。

## 15. 交付物

- 可运行的 `ai_pcb_mvp`（CLI）。
- wisp6 的模型 JSON、3 个候选、HTML 预览、硬检报告、写回 manifest。
- 一份 `README`：环境、命令、如何复核、如何恢复。
- P0 实验记录与 DRC 能力结论。

## 16. 项目节奏与人力

| 阶段 | 工作内容 | 谁做 | 工程师介入 |
|---|---|---|---|
| P0 | 写回验证、清铜、快照、DRC 探测 | 用户 + Claude | 不需要；AD GUI 由用户操作 |
| P1 | 模型、几何校验器、锚点/约束 | Claude + 用户 | 0.5–1 人天：锚点与约束签字 |
| P2 | 聚类、求解、预览、写回、报告 | Claude + 用户 | 0.5–1 人天：候选盲评 |
| 验收 | 最终确认与演示 | 用户 + 工程师 | 0.5 人天 |

工程师不需要读代码，只看三样东西：锚点/约束清单、候选 HTML 预览、AD26 副本。没有工程师签字时，demo 只能标注“技术演示，未经工程验收”。

## 17. 评审问题

1. 锚点原则是否按 `source_locked ∪ 机械约束件`，并保留 `--all-movable` 对比模式？
2. 锚点清单由哪位工程师在 P1 签字？
3. 项目投入是 1 人全职，还是兼职？
