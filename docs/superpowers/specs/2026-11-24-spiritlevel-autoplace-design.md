# SpiritLevel 115 器件自动布局 Demo — 设计文档（已被 wisp6 版取代）

> **本版已被取代**：对外展示改用 BSD-2 许可的 wisp6，见 [`2026-11-24-wisp6-autoplace-design.md`](2026-11-24-wisp6-autoplace-design.md)。本文件仅保留作历史记录。

> 版本：v1.0 · 2026-11-24
> 状态：待评审（评审通过后进入实施计划）
> 适用环境：Altium Designer 26.11.1.5（本机 `D:\Altium\AD26\X2.EXE`）、Windows、Python 3.13

## 1. 意图与为什么

做一个**硬件团队内部可用**的自动布局 demo，证明一条完整、可审计的闭环能在真实 AD26 工程上跑通：

```text
读取真实板 → 统一模型 → 硬/软约束 → 确定性求解 → 多候选预览
→ 人工审批 → 写回隔离副本 → 回读校验 → 快照可恢复 → 对比报告
```

不是为了替代硬件工程师，也不是做整板布线/SI/PI/EMC 签核。目标是让工程师拿到一个**满足明确几何约束、可继续精修**的初版布局，并且整个过程可解释、可回退。

Demo 主打板卡：AD26 自带 `SpiritLevel-SL1`（`D:\Altium\AD26\Examples\`）。

- 115 个器件（53 Top / 62 Bottom）
- 2 层板，180 × 50.5 mm
- 126 个网络、642 个焊盘
- 已布线（8225 条 track 记录、225 个 via、2 个 polygon）
- 随 AD26 授权，无需外网下载
- **许可边界**：AD26 Examples 受 Altium EULA 约束，只能在授权环境内部使用、不可再分发。对外演示或公开材料改用开源板：`wisp6`（BSD-2，65 器件 / 4 层）、`Pixhawk PSMv3`（CC BY-SA 3.0，66 器件 / 4 层）、`Luxonis OAK-D HAT`（MIT，84 器件 / 4 层）、`ODrive v3`（MIT，217 器件 / 2 层）。所有开源生产板都已布线，仍需在副本上清铜。

## 2. 目标 / 非目标 / 反目标

### 目标

- G1：把真实 PcbDoc 读成统一模型（器件、焊盘、网络、板框、区域、面、旋转、锁定状态）。
- G2：对约 90 个可动器件生成 ≥3 个满足全部硬约束的候选布局。
- G3：预览 + 人工审批后写入**隔离副本**，回读校验，文件可重开，快照可恢复。
- G4：输出每个器件"为什么放这里"的依据与软目标分数，而不是只有一个总分。
- G5：用分层求解把 115 器件规模跑通，不依赖 GPU、RL 或云端。

### 非目标

- 不布线、不做 SI/PI/EMC/热仿真、不做可制造性签核。
- 不移动已布线铜；只在"未布线副本"上做布局。
- 不做全自动无人审批；写入前必须人工确认。
- 不让 LLM 输出坐标或编造毫米数值。
- v1 不覆盖 SpiritLevel 以外的板卡；WiFi 28 器件板只作 1 天冒烟测试。

### 反目标（即使跑通也算失败）

- 布局"成功"但网表、焊盘映射或锁定器件被改动。
- 硬约束有违规却因为评分高而写回。
- 只在手工调过的合成板上有效，换真实板就崩。
- 部分写入失败后没有快照、无法恢复。
- 把 DRC 通过或 HPWL 更低当作电气/制造合格证明。

## 3. 约束

- AD26 固定 26.11.1.5，记录小版本；不假设跨版本 API 一致。
- 写回只作用于工程副本；原工程目录只读。
- `MoveToXY` 不带走板级走线/过孔/铺铜；demo 前先在副本上清铜。
- 文件级快照 + 哈希 manifest；不依赖 AD Undo。
- `altium_monkey` 为 AGPL-3.0：只作为独立只读 CLI/进程使用，不复制进对外分发代码。
- `coffeenmusic/altium-mcp`（MIT）优先作为实时读写通道；自建最小 DelphiScript 桥作为兜底。
- 所有硬约束的毫米数值必须有来源或明确标记为"demo 默认值，待工程师批准"。
- v1 不引入 LLM；语义角色识别推迟到 P3。

## 4. 已考虑的方案与选择

| 决策 | 备选 | 选择 | 理由 |
|---|---|---|---|
| 主打板卡 | WiFi 28 器件 / SpiritLevel 115 器件 | **SpiritLevel** | 用户明确要求复杂任务；115 器件、双面、2 层，真实且有挑战 |
| 求解架构 | 单体 CP-SAT / 分层（聚类 + 簇内求解 + 全局合法化） | **分层** | 115 器件单体 CP-SAT 变量与析取约束过多，易超时；分层可控、可复现 |
| 写回通道 | 第三方 MCP / 自建桥 / 离线文件写回 | **MCP 优先 + 自建桥兜底 + 离线只读对照** | MCP 有 MIT 实现和 AD26 实测；自建桥可控；离线写回不作主通道 |
| 可动范围 | 全部器件 / 锁定结构件与 FPGA | **锁定 FPGA + 连接器/LCD/开关/测试点/安装孔，其余可动** | 更接近真实工作流，降低首版风险；可配置 |

## 5. 系统架构

```text
AD26 工程副本
  │  McpBridge / ScriptBridge（读）
  ▼
统一模型 Board / Component / Pad / Net / Region / Constraint
  │
  ├─ NetworkX 网络图 + 聚类（功能簇）
  ├─ 硬/软约束编译（YAML + 设计规则 + 人工配置）
  ▼
分层求解
  1) 簇级 floorplan（粗网格 CP-SAT / 力导向）
  2) 簇内布局（CP-SAT 或 SA，≤30 器件/簇）
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
| `models` | Pydantic Schema、单位、版本、哈希 | mm、封装原点、side、rotation、locked、geometry_source |
| `geometry` | 板框、区域、封装保守占位、碰撞/距离 | Shapely；圆弧离散容差 ≤0.01 mm |
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
    def clear_copper(self, project_id: str) -> dict: ...
    def apply_placements(self, project_id: str, moves: list[dict]) -> dict: ...
    def readback(self, project_id: str, refdes: list[str]) -> dict: ...
    def run_drc(self, project_id: str) -> dict: ...
    def snapshot(self, project_id: str) -> str: ...
    def restore(self, snapshot_id: str) -> dict: ...
```

`McpBridge` 与 `ScriptBridge` 都实现该接口；离线 `altium_monkey` 只实现只读部分。

## 6. 数据模型（v1 必需字段）

- `Board`：`board_id`、`outline_mm`（含圆弧离散）、`origin_mm`、`units`、`source_hash`、`copper_layers`、`side_count`。
- `Component`：`refdes`、`footprint`、`origin_mm`、`rotation_deg`、`side`、`locked`、`body_polygon_local_mm`、`geometry_source`、`source_unique_id`。
- `Pad`：`pad_id`、`refdes`、`designator`、`local_polygon_mm`、`net_id`。
- `Net`：`net_id`、`name`、`pad_ids`、`net_class`（可得时）。
- `Region`：`polygon_mm`、`kind`（board_cutout/keepout/mechanical）、`side/layer`、`source`。
- `Constraint`：`rule_id`、`kind`、`severity`、`scope`、`targets`、`params`、`source_ref`、`review_status`。
- `Candidate`：`candidate_id`、`placements`、`hard_violations`、`soft_scores`、`solver_info`、`seed`。
- `Manifest`：输入/输出哈希、变更清单、工具版本、AD 版本、时间、错误。

坐标约定：内部统一 **mm**；器件 `(x, y)` 是封装原点；Pad 经旋转/翻面变换到板级；rotation 为逆时针角度；side 只有 top/bottom。

## 7. 约束（v1）

### 硬约束

1. 锁定器件的位置、旋转、面不变。
2. 可动器件的保守占位多边形不重叠，且满足配置间距。
3. 全部器件在板框内（含板边余量）。
4. 避开已分类的 keepout / 板挖空区域。
5. 器件面固定；旋转只允许配置集合（默认 0/90/180/270，连接器固定）。
6. 网表、Pad→Net 映射、器件数量不变。

### 软目标

- 关键网络加权 HPWL（电源/GND 低权重或排除）。
- 去耦电容到目标 IC 电源 Pad 的距离。
- LED/按键/连接器靠板边或保持原相对方位。
- 保留原布局的簇级相对位置（v1 的强先验，避免"合法但乱"）。
- 局部余量与可维护性。

所有软权重放在 `configs/spiritlevel.yaml`，首版不宣称公司标准；用原板与人工方案做对照后再校准。

## 8. 分层求解（115 器件）

### 8.1 预处理

- 建 `Component–Net–Pad` 图；对高扇出网络（电源/GND）降权，避免把所有器件连成一团。
- 聚类输入：网络邻接 + 位号前缀 + 封装类型 + 原布局邻近性。
- 目标 8–15 个簇，每簇 ≤30 个可动器件；锁定器件作为锚点参与簇边界。
- 输出 `clusters.json`，每个簇含成员、锚点、关键网络、原布局包围盒。

### 8.2 簇级 floorplan

- 粗网格 0.5–1.0 mm；簇包围盒为矩形/保守多边形。
- CP-SAT：`NoOverlap2D` + 板框/keepout + 锚点相对方位 + 簇间间距。
- 目标：加权簇间 HPWL + 与原布局簇位置的偏差。
- 时限 30–60 s；超时回退力导向 + 合法化。

### 8.3 簇内布局

- 每簇 ≤30 器件，0.25–0.5 mm 栅格，CP-SAT optional intervals。
- 旋转集合按封装配置；引脚朝向关键网络的方向作为软目标。
- 时限每簇 10–30 s；超时回退 SA。
- 去耦电容优先靠近目标 IC 的电源 Pad（软约束）。

### 8.4 全局合法化与精修

- Shapely 检查全部多边形；残余重叠用 hard-shove 推开，锁定件不动。
- SA：微移、±90° 旋转、同封装交换；每步硬约束校验；固定种子，8–16 起点。
- 只接受硬约束可行解；记录每次迭代的分数与违规数。

### 8.5 多候选

- 3 组不同种子/权重，输出 top-3；每个候选附硬违规数、软分、运行参数。
- 无可行解时输出冲突规则/空间不足报告，不返回"最接近但违规"的解。

## 9. 独立校验

- V1 几何：Shapely 相交、板框包含、keepout、锁定不变、Pad 距离、side/rotation 合法性；与求解器分离实现。
- V2 回读：器件数、位号、Pad→Net、网络数、面、旋转、坐标；非目标零变化。
- V3 DRC：先探测 `RunBatchDesignRuleCheck`；失败退模态 `PCB:DesignRuleCheck`；再失败用 `check_placement` 成对检查；记录基线与增量。
- V4 对比：与原板布局比较关键网络 HPWL、间距、板边余量；只报告差异，不宣称更优。

## 10. 写回与回退

1. 复制整个工程目录到 `work/runs/<run_id>/project/`；记录文件哈希。
2. 在副本上清铜（仅铜层 track/via/polygon），保留板框、丝印、机械层、规则。
3. 求解与预览；人工审批候选。
4. 再次快照；批量写入副本；回读校验；保存重开。
5. 输出 `manifest.json`、`hard_check.json`、`candidate_scores.json`、`layout_diff.json`、`validation_report.html`。
6. 任一硬检失败 → 恢复快照并停止；不写原工程。

## 11. 分阶段与验收

### P0｜写回生死门（3–5 天）

实验：

1. 复制 SpiritLevel 工程到隔离目录，哈希全部文件。
2. AD26 脚本导出器件清单，与 `altium_monkey` 解析交叉核对。
3. 单个非锁定器件移动 1 mm + 旋转 90°，回读、保存、重开。
4. 10 个器件批量移动，回读。
5. 副本清铜，统计删除/保留对象，保存重开。
6. 快照恢复，哈希比对。
7. DRC 能力探测（批量/模态/check_placement）。

通过标准：坐标/旋转误差 ≤0.01 mm 或 1 个内部单位（以实测为准）；网表/Pad 映射不变；锁定件不变；文件可重开；快照可恢复；无部分写入遗留。

不通过：停止自动写回，降级"导出候选 JSON + 人工应用"。

### P1｜模型与校验器（3–5 天）

- 输出 SpiritLevel 的 `board.json` / `components.json` / `pads.json` / `nets.json` / `regions.json`。
- 实现 Shapely 校验器；注入合成重叠/越界/keepout 用例，验证检出。
- 对原板跑基线体检，解释任何误报。
- 产出 `configs/spiritlevel.yaml`（锚点、间距、旋转、权重）。

通过标准：校验器能稳定检出注入错误；原板基线可解释；模型字段缺失明确标记而非猜测。

### P2｜求解与 demo（2–3 周）

- 先跑 WiFi 28 器件冒烟测试（1 天），再跑 SpiritLevel 115 器件。
- 实现聚类、簇级 floorplan、簇内 CP-SAT/SA、合法化、top-3 候选。
- HTML/SVG 预览 + 审批 + 写回副本 + 回读 + 对比报告。

通过标准：硬门禁 0 违规；锁定件与网表零变化；≥3 个可行候选；115 器件单次 <10 分钟；文件可重开；快照可恢复；工程师认为可作为继续精修的初稿。

### P3｜可选

- LLM 角色识别与规则候选（带证据、可弃权）。
- 规则库/RAG 接入、更多板卡、SpiritLevel 全自由重排（不保留原相对位置）。

## 12. 目录结构

```text
ai_pcb_mvp/
├─ configs/spiritlevel.yaml
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
│  └─ workflows/
├─ tests/
│  ├─ fixtures/
│  ├─ unit/
│  └─ integration/
├─ work/runs/            # 每次运行的副本、快照、日志、候选
└─ docs/
```

## 13. 风险与缓解

| 风险 | 触发信号 | 缓解/退出 |
|---|---|---|
| 115 器件求解超时 | CP-SAT 单簇 >60 s、全局 >10 min | 分层 + 减小簇、SA 回退、时限内输出可行解 |
| 封装占位不准 | 无 Courtyard、bbox 含丝印 | 保守 Pad 包围盒 + 3D body 参考，标记 `geometry_source`，工程师复核 |
| 板框/区域语义错误 | 圆弧离散误差、区域分类错 | 离散容差 ≤0.01 mm；11 个区域人工分类进配置 |
| 写回破坏工程 | 回读不一致、无法重开 | P0 门禁；只写副本；文件快照；失败恢复 |
| DRC 不可靠 | 批量调用失败/弹窗/上限 | 独立 Shapely 校验 + 能力探测 + 基线 diff；不把 DRC=0 当合格 |
| AGPL 污染 | 产品分发包含 altium_monkey 代码 | 独立进程/CLI；只读；不复制代码 |
| 许可/合规 | 对外演示使用 AD26 Examples、来源不明样本或 CC BY-SA 工程 | 内部用 Examples；对外换 BSD/MIT 板；CC BY-SA 仅内部隔离使用；集成前法务审查 |
| 期望落差 | 认为"自动布局=可直接投板" | 报告明确"初稿、未布线、未做 SI/PI/EMC" |

## 14. 需要工程师确认的默认值

- **锚点**：建议锁定 U1（FPGA）、HDR1/2/3、J1、LCD1、S1–S3、TP1–TP3、安装孔/Logo；其余可动。可在 YAML 调整。
- **间距**：优先使用 AD 已启用的 ComponentClearance 规则；未启用的用 0.2 mm demo 默认值并标记。
- **旋转**：连接器/LCD/开关固定；阻容 0/90；IC 0/90/180/270。
- **强先验**：v1 保留原布局的簇级相对位置；P3 再评估完全自由重排。
- **审批**：每轮候选必须人工选一个，才允许写入副本。

## 15. 交付物

- 可运行的 `ai_pcb_mvp`（CLI）。
- SpiritLevel 的模型 JSON、3 个候选、HTML 预览、硬检报告、写回 manifest。
- 一份 `README`：环境、命令、如何复核、如何恢复。
- P0 实验记录与 DRC 能力结论。

## 16. 评审问题

1. 锚点列表是否认可？尤其是 U1（FPGA）是否锁定。
2. 是否接受"清铜副本"作为 demo 形态。
3. 115 器件首版允许 10 分钟求解时间是否可接受。
4. 预览先做 HTML/SVG 是否够，还是必须在 AD26 内直接看。
