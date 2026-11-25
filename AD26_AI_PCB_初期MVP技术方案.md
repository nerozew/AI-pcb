# AD26 AI 辅助 PCB 自动布局：初期 MVP 技术方案（供 Codex 评审与实施）

> **文档性质**：工程探索方案 / MVP 技术设计草案（不是已验证的功能承诺）  
> **版本**：v1.0 · 2026-11-23  
> **适用场景**：企业内网、Altium Designer 26（AD26）、既有 Datasheet → 原理图库 / 封装库流程、现有 RAGFlow/DeepDoc 知识库  
> **项目目标**：验证“**识别局部电路的布局意图 → 编译可靠约束 → 算法计算坐标 → 安全写回 AD26 → 自动检查与回退**”这一最小闭环。

---

## 0. 一页结论

**建议采用：少量 LLM 语义角色 + 确定性规则/几何引擎 + AD26 原生数据接口 + 人工验收。** 初期**不**以五个自治 Agent、Cypress 全局求解、自动布线、Neo4j、云端视觉审核作为前置条件。

初期最值得验证的不是“AI 能否调用鼠标摆器件”，而是：

1. 能否可靠读取 **真实 PCB 工程**中的元器件、引脚/焊盘、网络、封装几何、板框、禁布区及锁定状态；
2. 能否识别一个具体子电路（首选 **Buck 降压电源**或 **MCU 去耦电路**）中的器件功能角色；
3. 能否把规格书、公司规范与工程师经验转换成**有来源、可校验、不会凭空编造数值**的机器约束；
4. 能否用非 LLM 算法得到满足明确硬约束的器件位置与角度；
5. 能否**先预览、后审核、再批量写入 AD26**，写入后重新读取核对，异常能可靠恢复原工程。

**MVP 成功定义**：在指定板卡的一个真实子模块中，自动给出可审查的候选布局；经授权写回 AD26 后，已定义的几何硬约束全部通过，网表连接不变、锚点不动、工程正常打开，且工程师认为可作为继续设计的初稿。它**不等同于**可直接投板、SI/PI/EMC 合格或整板可自动布通。

---

## 1. 背景与约束

### 1.1 可复用的现有基础

- 已有基于 Datasheet 的**引脚、引脚表、封装尺寸与库文件**提取/生成工作；可复用器件位号、Pin/Pad 映射、焊盘几何信息，但不能假设现有库文件生成能力等于整板布局能力。
- 已有 **RAGFlow / DeepDoc** 文档解析、图册及图文资产管理经验；可用于检索芯片原厂推荐布局图、规范正文、图注、原厂约束。
- 已考虑 **LangGraph、NetworkX、MCP、AD26 自动化**；可复用这些基础设施，但必须将稳定执行与 AI 自主推理分开。
- 企业资料、未公开网表和 PCB 截图默认按**涉密数据**处理；方案默认内网运行，外部模型/API 需独立安全审批。

### 1.2 初期范围（In Scope）

- 真实 AD26 工程的**读取、快照、只读解析与关键字段一致性核查**。
- 一个相对简单的局部电路：例如 Buck 的 U/CIN/L/COUT/反馈电阻，或 MCU 与若干本地去耦电容；优先约 **5～20 个待调整器件**，其余锁定。
- 支持 0°/90°/180°/270° 旋转（视封装和约束决定）、Top 面的二维局部布局；其他旋转与 Bottom 面先列扩展项。
- 固定锚点、板框/禁布区、器件不重叠、近特定引脚、区域限制、相对方位等**能够明确量化**的约束。
- 产出可审核的候选布局、冲突列表、规则证据、评分和工程副本。
- 经人工确认后可批量写回、重新读取比对、失败恢复。

### 1.3 初期明确不做（Out of Scope）

- 自动完成整板最终布局布线、正式可制造性签核、SI/PI/EMC/热仿真。
- DDR/高速差分、射频天线、复杂 BGA 逃逸、高压爬电、严格隔离电源等高风险场景。
- 将图片中的示意间距自动当作毫米硬约束。
- 通过 Windows 鼠标模拟作为主要摆件方式。
- 多个 Agent 无约束对话、自动接管所有异常弹窗。
- 必须部署 Neo4j、Cypress、Freerouting、专用 GPU 或完整 VLM 管线。

### 1.4 安全优先级

1. **工程安全/制造底线**：禁止被普通板级偏好覆盖；涉及法规、耐压、爬电等高风险条件由工程师维护与签核。
2. **工程约束与原厂要求**：只对适用对象生效；有冲突时不自动二选一，输出冲突并请求裁决。
3. **性能/经验偏好**：可转为软目标优化；必须保留来源和权重。
4. **未经确认的 AI 推断**：仅作建议，**不能**自动提升为强制硬约束。

---

## 2. MVP 的总体架构

```text
                  ┌──────────────────────────────┐
                  │ AD26 工程 .PrjPcb / .PcbDoc   │
                  │ .SchDoc / BOM / 库 / 约束文件  │
                  └──────────────┬───────────────┘
                                 │
                     [只读解析 + 一致性验证]
                                 ▼
                  ┌──────────────────────────────┐
                  │ Unified PCB Model            │
                  │ Board / Component / Pad / Net│
                  │ Region / Geometry / Rule     │
                  └───────┬──────────────┬───────┘
                          │              │
             ┌────────────▼───┐   ┌─────▼─────────────────┐
             │ 图拓扑 + 功能识别│   │ RAG/规则检索与编译     │
             │ NetworkX+LLM  │   │ 原厂证据/三层规范      │
             └────────────┬───┘   └─────┬─────────────────┘
                          └──────┬───────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │ 有效约束集 ConstraintSet     │
                  │ 规则冲突与人工审批状态       │
                  └──────────────┬───────────────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │ Placement Solver             │
                  │ Shapely + OR-Tools / 局部搜索 │
                  │ 候选坐标 (x, y, rotation)    │
                  └──────────────┬───────────────┘
                                 ▼
                  ┌──────────────────────────────┐
                  │ Validator + Scorer           │
                  │ 几何硬检、软目标、差异报告  │
                  └──────────────┬───────────────┘
                                 ▼
                     [人工确认候选方案]
                                 ▼
                  ┌──────────────────────────────┐
                  │ AD26 EDA Adapter             │
                  │ 快照 → 批量写入 → 重读校验    │
                  │ DRC/失败恢复/审计日志        │
                  └──────────────────────────────┘

               外层：确定性工作流（起步可用 Python 状态机，
                     稳定后使用 LangGraph 编排）
```

### 2.1 模块分工：不是每个模块都要 Agent

| 模块 | 主要输入 | 主要输出 | 实现方式 | MVP 优先级 |
|---|---|---|---|---|
| EDA Adapter | AD26 工程、器件清单、坐标修改 | 工程快照、统一数据、变更结果 | AD 脚本/API/MCP 封装；不可依赖截图获取几何 | P0 |
| PCB Parser & Normalizer | AD 读出结果 / 离线解析结果 | 统一 PCB Model | Python + Pydantic | P0 |
| Geometry Validator | 封装外形、坐标、区域、规则 | 违规清单 | Shapely、精确几何计算 | P0 |
| Netlist Analyzer | Component/Pad/Net | 连接图、候选子模块 | NetworkX + 确定性规则 | P1 |
| Circuit Role Assistant | 拓扑、引脚功能、BOM、规范 | 器件功能角色与证据 | LLM 按需调用 + Schema 校验 | P1 |
| Rule Compiler | 项目规则、原厂资料、人工审批 | Hard/Soft 约束集 | 确定性程序 + LLM 仅提候选 | P1 |
| Placement Solver | 可移动器件、几何、约束 | 多个候选布局 | OR-Tools / SA + Shapely | P1 |
| Critic / Reporter | 违规、评分、AD DRC、证据 | 根因建议、异常报告 | 先代码，复杂情况再调用 LLM | P2 |
| RAG 文档接入 | 公司规范、原厂规格书、图片资产 | 相关段落/图注/原图链接 | 复用现有 RAGFlow 管线 | P1（可手工规则先行） |
| Windows UI MCP | AD 非关键窗口操作 | UI 操作结果 | 可选辅助；异常弹窗高危时停机 | P2 |

> **关键原则**：批量移动器件、坐标换算、碰撞验证、快照回滚、结果评分都是确定性代码职责，不应委托 LLM 每次自由决策。

---

## 3. AD26 接入：项目成败第一关

### 3.1 不预先指定唯一第三方项目

候选：

- [wavenumber-eng/altium_monkey](https://github.com/wavenumber-eng/altium_monkey)：重点验证离线格式解析、图元/网络提取的真实覆盖范围。
- [M-R-Abedini/Electronics_AI](https://github.com/M-R-Abedini/Electronics_AI)：重点验证目标 AD26 版本的实时器件读取、批量写入及稳定性；项目自述为实验性，不能默认生产可用。
- [coffeenmusic/altium-mcp](https://github.com/coffeenmusic/altium-mcp)：可纳入摆件/检查/渲染能力对照测试。
- [Altium 官方 MCP 文档](https://docs.developer.altium.com/ad-mcp-docs/)：查看当前版本、许可证与可调用能力，不预设有批量摆件写入 API。
- [embedded-society/altium-designer-mcp](https://github.com/embedded-society/altium-designer-mcp)：更适合既有 SchLib/PcbLib 建库业务，非整板布局的必选执行器。

这些链接是**待验证技术候选**，不能把 README 中的宣传描述直接视作现有环境可用。对每项记录安装版本、实际接口、支持文件、失败样例、许可条件和维护成本。

### 3.2 EDA Adapter 必须暴露的最小接口

```python
class EDAAdapter(Protocol):
    def get_environment_info(self) -> dict: ...
    def open_project_readonly(self, project_path: str) -> str: ...
    def export_board_model(self, project_id: str) -> dict: ...
    def validate_design_baseline(self, project_id: str) -> dict: ...
    def create_snapshot(self, project_id: str) -> str: ...
    def apply_component_placements(self, project_id: str, changes: list[dict]) -> dict: ...
    def reread_placements(self, project_id: str, refdes: list[str]) -> dict: ...
    def run_available_checks(self, project_id: str) -> dict: ...
    def restore_snapshot(self, snapshot_id: str) -> dict: ...
```

`Protocol` 是内部目标接口，不代表任一开源工具天然实现。若接口无法实现，应及时降级为“**导出候选 JSON + 工程师手动应用**”，避免不可靠的生产写入。

### 3.3 接入验证用例（必须先通过）

1. 将真实工程复制到**隔离测试目录**，保存 `.PrjPcb`、`.PcbDoc`、`.SchDoc`、所有相关库/配置等依赖，确认能完整打开。
2. 只读导出所有器件：`refdes`、唯一对象 ID（如可得）、封装、所在面、位置、旋转、锁定状态。
3. 导出网络的 **Pad→Net→Component** 关系，核查器件/网络数量；不能只靠 SchDoc 推断 PCB 上实际已放置的器件。
4. 提取板框、禁布区、元件可用占位边界、关键焊盘中心/形状，记录每个字段是“直接获得 / 计算推导 / 未获得”。
5. 对**单个非锁定测试器件**先做小幅移动和旋转，然后重新读取验证其坐标；再测试批量移动。
6. 保存、关闭、重新打开测试工程；验证文件可用、元件属性和网络关系未改变。
7. 模拟中断：执行失败、AD 无响应、文件被占用、部分批量写入成功；验证恢复原副本的能力。

**P0 停止条件**：无法稳定读取 Net/Pad 映射，或写入后无法恢复、无法保证文件完整性，则**禁止进入自动布局阶段**。

### 3.4 数据与坐标规范

- 内部统一使用 **mm**、明确的板坐标系与旋转方向；在 Adapter 边界转换 AD 内部单位。
- 明确器件 `(x,y)` 是封装**原点**而不是中心点；Pad 相对于封装原点，经过旋转/翻面变换后得到板级坐标。
- 每个器件必须有 `side`、`rotation_deg`、`locked`、`geometry_source` 字段；无法取得真实外形时不能假设其封装库外框一定合法。
- 几何优先使用经过确认的 Courtyard/实体占位轮廓；缺失时可用可解释的**保守替代边界**，但必须标记精度并要求人工确认。
- AD 的禁布区、限高区、板边、层和正反面并非同一种约束，不可简单当成一张二维全局多边形。

---

## 4. 统一数据模型（建议先定义，再写工具）

统一数据结构把具体 AD 实现、RAG、LLM 和求解器隔离开。MVP 可使用 Python Pydantic 模型 + JSON 文件，不必一开始为每个中间结果建 MySQL 表。

### 4.1 核心实体

| 实体 | 必需字段（示例） | 用途 |
|---|---|---|
| `Board` | `board_id`、`outline_polygon_mm`、`coordinate_frame`、`units`、`source_hash` | 板级几何与版本锚点 |
| `Component` | `refdes`、`footprint_id`、`origin_mm`、`rotation_deg`、`side`、`locked`、`body_polygon_local_mm` | 真实器件占位与变换 |
| `Pad` | `pad_id`、`component_refdes`、`pad_designator`、`local_geometry_mm`、`net_id` | 精确的引脚/网络约束 |
| `Net` | `net_id`、`name`、`pad_ids`、`net_class`（如能取得） | 网表与拓扑 |
| `Region` | `polygon_mm`、`type`、`side/layer`、`source` | 禁布、限高、固定布局区域 |
| `CircuitGroup` | `group_id`、`type`、`members`、`anchors`、`evidence` | 电路功能模块 |
| `Rule` | `rule_id`、`kind`、`scope`、`targets`、`params`、`severity`、`source_ref`、`review_status` | 规则编译前的规范化表示 |
| `PlacementCandidate` | `candidate_id`、`placements`、`hard_violations`、`soft_scores`、`solver_info` | 求解结果与复现 |

### 4.2 示例：布局候选（示意值，不代表任何芯片原厂规范）

```json
{
  "board_id": "demo_board_01",
  "source_revision_hash": "sha256:example",
  "candidate_id": "buck_local_candidate_001",
  "coordinate_unit": "mm",
  "placements": [
    {"refdes": "U3", "x_mm": 40.0, "y_mm": 20.0, "rotation_deg": 0, "side": "top", "locked": true},
    {"refdes": "C12", "x_mm": 37.5, "y_mm": 20.5, "rotation_deg": 90, "side": "top", "locked": false}
  ],
  "hard_violations": [],
  "requires_human_approval": true,
  "status": "PREVIEW_ONLY"
}
```

**禁止**仅依赖 `refdes` 处理版本差异或对象身份：写入前必须验证工程来源哈希和对象匹配，防止原理图同步/ECO 或位号变化后误移器件。

---

## 5. 从网表到电路功能：AI 真正需要做什么

### 5.1 先确定性建图，再做语义识别

使用 NetworkX 建立 **Component—Net—Pad** 关系模型。网络图可以帮助确认连接、搜索局部邻域，但不能直接从连通性推出“谁是去耦电容/反馈电阻”。

原因：电源/GND 等高扇出网络会把许多无关器件关联起来；只有结合**引脚名字、器件类别/数值、线路拓扑、数据手册、原理图功能标注**才能更可靠地判断电路作用。

识别路线：

1. **规则识别优先**：器件类型、网络命名、引脚功能、局部电路模式（如 Buck 的 VIN/SW/FB/PGND）进行候选识别。
2. **LLM 负责歧义消解**：只输入当前子模块的结构化网表、BOM/引脚功能与检索资料；输出 JSON，不生成坐标。
3. **证据审查**：每个推断记录原始网络/引脚证据及引用的文档版本；关键器件角色由人工确认后方可生成硬约束。
4. **不确定则弃权**：引脚功能不明、网表缺失、多个角色冲突，输出 `REVIEW_REQUIRED`；不硬猜。

### 5.2 示例：角色输出

```json
{
  "group_id": "buck_u3",
  "group_type": "buck_converter",
  "roles": [
    {
      "refdes": "C12",
      "role": "input_decoupling_capacitor",
      "parent_refdes": "U3",
      "related_pins": ["VIN", "PGND"],
      "evidence": [
        {"type": "netlist", "detail": "C12 两端位于输入供电网及电源地网"},
        {"type": "datasheet", "asset_id": "doc_example_fig_3", "page": 12}
      ],
      "review_status": "PENDING"
    }
  ]
}
```

此例只演示字段；是否确属输入去耦，必须由实际工程、电容参数和文档证据确定。

### 5.3 MVP 的智能边界

- 初期只支持**一类模块做深**，优先 Buck 或 MCU 去耦，避免同时覆盖几十种电路模式。
- 若识别不到已知模块，**允许人工指定器件组与角色**；不要让模型为了自动化率编造结果。
- `Tier 0～3` 分级思路可保留，但不采用“按节点度数 Top N、固定每组数量”等作为决定性规则；在局部 MVP 中以**锚点、关键伴随件、其余锁定**即可。

---

## 6. 规则知识库与 Constraint Compiler

### 6.1 初期知识库：轻量化而不是重建平台

优先复用现有 RAGFlow/图册资产。如果暂时取不到原图或版面质量不可靠，先用工程师整理的**10～30 条经过批准的规则**建立最小规则库。

原厂示意图 / 公司正反例图应保留：

- `document_id`、`document_revision`、页号、图注、`asset_id`、关联器件型号/电路类型；
- 原图路径、检索文本（可由标题、图注、人工摘要组成）、明确的审核状态；
- 图片中**明确标注**的数值与**视觉推断**的数值必须分开存储。

MVP 无需每条规则都先用 VLM 转写。**OCR/VLM 生成的描述是候选证据，不是已验证设计规则。**

### 6.2 三层来源 + 强制安全约束

| 来源 | 示例 | 使用方式 |
|---|---|---|
| L1 通用规则 | 板框、安全间距、禁止碰撞、制造基础要求 | 已批准的安全底线优先，不能被较高级普通偏好覆盖 |
| L2 芯片/电路规则 | 退耦靠近目标 Pad、反馈远离 SW、振荡器区域限制 | 判断适用料号/电路后加载，核对来源 |
| L3 单板规则 | 固定连接器、散热/结构区域、用户指定布局方向 | 在不违反安全底线及适用原厂要求前提下生效 |
| 人工裁决 | 两条规则冲突时批准的取舍 | 记录人员、原因、版本，不让 LLM 擅自覆盖 |

> 原 Gemini 方案的 `L3 > L2 > L1` 可用于部分**普通偏好**的覆盖，但不适用于制造安全底线、法规约束以及必须核对的芯片硬要求。

### 6.3 规则类型

**硬约束**（失败则不得自动应用）：

- 已锁定器件位置/旋转不变；
- 有效占位形状不重叠、满足配置的间距；
- 器件位于允许区域、避开对应面/层的禁布区；
- 指定器件到**指定 Pad**的距离上限（只有真实可信、已批准的数值才启用）；
- 设计规则/元件属性保持一致，不删除/改变 Net 或焊盘。

**软目标**（加权优化，不作为安全证明）：

- 缩短关键网络的加权连接距离；
- 保持输入/输出流向、功能分区与可维护性；
- 增大局部预留空间，避免器件过于拥挤；
- 尽量复现经批准的参考布局相对关系。

**暂不自动数学化**：高频环路的电磁质量、热耦合、复杂参考平面完整性；如果无法合理建模，则输出为**人工复核条目**。

### 6.4 约束 JSON 样例（示意规则值）

```json
{
  "rule_id": "R_BUCK_CIN_TO_VIN_001",
  "kind": "max_pad_distance",
  "severity": "hard",
  "scope": {"board_id": "demo_board_01", "group_id": "buck_u3"},
  "targets": {
    "movable_refdes": "C12",
    "movable_pad": "1",
    "anchor_refdes": "U3",
    "anchor_pad": "VIN"
  },
  "params": {"max_distance_mm": 3.0},
  "source_ref": {
    "document_id": "approved_rule_example",
    "revision": "example_v1",
    "page": null,
    "origin": "engineer_approved"
  },
  "review_status": "APPROVED"
}
```

`3.0 mm` 是为了展示格式而填写的**虚构示例值**，不是任何具体芯片的推荐距离。真实系统只有在验证源文档、物理意义、适用条件和审批通过后才能采用数值硬约束。

### 6.5 规则冲突处理与审计

输出 `effective_rules.json` + `conflicts.json` + `provenance.json`。任何 `REVIEW_REQUIRED` 的关键硬规则、互相矛盾的距离要求、缺少必要 Pad ID、未批准的硬限制，均阻止自动应用。禁止由大模型静默合并冲突。

---

## 7. 布局求解：先做可验证的小问题

### 7.1 两级求解

**第一级：工程师/规则确定锚点与模块边界。** 固定主控、连接器及已布局器件；MVP 只允许移动一个小模块的选定器件。

**第二级：非 LLM 数值求解。**

1. 生成合法候选：在允许区域内放置，枚举准许旋转角度；
2. 使用几何引擎剔除与锚点、板框、其他器件及禁布区的冲突；
3. 对通过硬约束的候选按关键 Pad 距离、连线、相对位置、可维护性等评分；
4. 输出**至少一个可复现候选**，可选保留若干非支配/高分候选供人工比较；
5. 无可行解时明确报告冲突规则/空间不足，而非返回“最接近但违规”的布局让它自动写回。

### 7.2 算法首选与限制

| 工具/算法 | 初期职责 | 重要限制 |
|---|---|---|
| `Shapely` | Polygon 变换、碰撞、距离、区域合法性 | 需确保几何模型、间距和单位准确 |
| `OR-Tools CP-SAT` | 小规模离散网格/候选槽位上的无重叠与约束优化 | 连续坐标需量化；复杂不规则多边形可由外部几何验证 |
| Python 局部搜索/模拟退火 | 在硬约束已满足前提下改善角度和距离 | 可复现需固定种子；不保证全局最优 |
| `NetworkX` | 电气拓扑与目标网络权重 | 不是布局求解器 |
| `NVlabs/Cypress` | 未来研究大规模全局布局 | 需转换输入、映射约束、重新评测，不是即插即用 AD 布局插件 |

**不建议一开始采用纯矩形装箱代表完整 PCB 布局**。矩形可以作为初步筛选，但最终要用实际封装外形/焊盘及适用的安全留量校验，并保留未知几何的人工关卡。

### 7.3 质量评价

**先硬门禁，再软评分，最后人工比较。**

- 硬门禁：已批准的硬约束违规数 = 0；被锁定器件无变动；工程对象/网络数和映射保持一致；工程可重新打开。
- 软评分：关键 Pad 距离、加权估计连线长度、局部剩余空间、指定相对顺序、人工修改成本。
- 不把 HPWL 低、所有 DRC 为零或评分达到某固定数字，等同于 SI/PI/EMC 或可制造性通过。
- **评分权重由对照实验校准**，初期不硬编码 Gemini 示例的 0.35/0.25/0.20/0.20 为公司标准。

输出包括：`hard_check.json`、`candidate_scores.json`、`placements.json`、`layout_diff.json`；每项得分须能追溯算法版本与输入快照。

---

## 8. 固定工作流与异常回退

```text
INIT
  ↓
SNAPSHOT_INPUT → READ_ONLY_PARSE → BASELINE_VALIDATE
  ↓                                   │
BUILD_TOPOLOGY → EXTRACT_ROLES         └─失败→ STOP / REPORT
  ↓
RETRIEVE_RULES → COMPILE_CONSTRAINTS → HUMAN_REVIEW_IF_NEEDED
  ↓                                            │
SOLVE_LOCAL → GEOMETRY_VALIDATE                └─未批准→ STOP
  ↓
RANK_CANDIDATES → PREVIEW → HUMAN_APPROVE
  ↓
SNAPSHOT_BEFORE_WRITE → APPLY_TO_TEST_COPY → REREAD_VERIFY
  ↓                                                 │
RUN_AVAILABLE_CHECKS → REPORT                       └─失败→ RESTORE / STOP
  ↓
ACCEPT_TEST_OUTPUT (工程师决定是否进入正式工程)
```

### 8.1 写入策略

- 默认**只读**与**预览模式**；初期写入只作用于隔离副本，不自动覆盖用户的工作工程。
- 写入必须同时校验：项目版本哈希、器件唯一身份、锁定状态、输入约束版本、批准者。
- 批量写入前制作**文件级快照**，不能仅依赖 AD Undo；保存 manifest（输入哈希、输出哈希、变更清单、工具版本、时间、错误）。
- 写入后重新读取，并检查每个目标器件坐标/旋转是否与候选一致、其他器件有无意外变化、网表/Pad 映射有无变化。
- 若存在基线本来就有的 DRC 问题，记录**基线与增量差异**，不能要求未布线板卡所有 DRC 类目绝对为零；MVP 重点检查与布局相关且可用的规则。
- 如果 UI 弹窗造成阻塞：**检测并暂停**，不得默认让 Windows MCP 自动点击所有“确认/继续/覆盖”。

### 8.2 重试与人工接管

- 同一输入的求解重试上限可配置（建议先 2～3 次），每次记录随机种子、约束与结果。
- 几何失败优先报告 `component_overlap / outside_board / keepout / locked_moved / rule_conflict`，不让 Critic Agent 反复自由发挥。
- 结构性无解时停止并交给工程师调整模块边界或约束，而不是擅自放宽安全要求。

---

## 9. 分阶段实施与交付门槛

> 各阶段按**通过门槛**推进，不把“第几周完成”当成已验证承诺。当前先做 P0→P1→P2，P3 可选。

### P0｜AD26 数据与执行可行性验证（最优先）

**开发内容**

- 选定一块**非涉密或获授权的 2～4 层简单板卡副本**；记录 AD26 具体小版本与相关许可证。
- 制作 `EDAAdapter`；对至少两个候选接入方式进行对照：真实可读取字段、批量写入、重开工程、异常恢复。
- 建立 `Board/Component/Pad/Net/Region` 统一 JSON；实现只读导出器和基线审计工具。
- 编写 `pytest` 用例：数量一致、Pad→Net 映射、坐标回读、Locked 不变、文件快照恢复。

**交付物**

- `sample_board.json`（脱敏示例）；`adapter_benchmark.md`；`baseline_report.json`；`test_ad_roundtrip.py`；一套可回滚的测试工程副本。

**放行标准**

- 关键对象清单与 AD 中人工抽查一致；所有缺失字段明确标记，而非猜测；
- 目标器件写入/回读的坐标与旋转误差在明确的接口量化容差内；
- 原工程副本在保存与重开后完整，网表连接关系未被改动；
- 可以从异常演练中恢复，或证明“不可恢复时绝不提交变更”。

**如果 P0 不通过**：停止自动写入开发，改成只读解析、约束建议与候选坐标导出工具。

### P1｜单模块语义识别 + 约束编译

**开发内容**

- 选择一个真实 Buck 或 MCU 去耦电路，用人工确认其器件清单与功能角色，作为 Ground Truth。
- 建立 NetworkX 图、关键 Pin/Pad 映射、规则模式；LLM 只在歧义场景生成结构化角色候选。
- 从批准的设计规范/数据手册建立少量规则（先人工录入），实现规则版本、溯源、冲突检测与审批。
- 输出可供求解器读取的约束，不急于接入完整多模态入库管线。

**交付物**

- `roles.json`、`roles_review.md`、`effective_rules.json`、`conflicts.json`；测试电路标签与初期规则集。

**放行标准**

- 在选定样本中关键器件角色经工程师逐项核实；
- 不存在自动采用无证据距离、错误 Pad 或未审批硬规则的路径；
- 对缺失信息、冲突规则、识别不确定情形能明确停机/请求人工确认。

### P2｜局部自动布局 + AD26 闭环

**开发内容**

- 固定主芯片及既有器件，仅释放 5～20 个候选器件；在允许区域内计算 `(x, y, rotation)`。
- 实现 Shapely 几何硬检；先用候选槽位 + CP-SAT 或局部搜索求解。
- 生成变更前后预览、硬约束检查、软目标分数，提供人工审核入口（CLI/HTML 报告即可，不必先写复杂前端）。
- 对批准方案执行：备份 → 写入隔离工程 → 回读验证 → 可用的 AD 检查 → 完整报告 → 异常恢复。

**交付物**

- `placements.json`、`validation_report.html`、`write_manifest.json`、可打开的 AD26 布局副本、回归测试。

**放行标准**

- **100% 的已定义且适用的硬门禁通过**；其他不可检验的工程规则明确标注“未验证”；
- 被锁定器件与网表无非预期变化；写入可审计、文件可重开，失败时可恢复；
- 至少一个真实子电路候选经过硬件工程师验收，认为可用于继续人工精修；
- 与原始/人工布局对照报告包含关键距离、可用区域、违规数、工程师修正项，而非只有主观得分。

### P3｜可选扩展（P2 真正成立后再评估）

- 多模块 Floorplanning、Tier 0～3 的动态分类、普通器件自动填充。
- Cypress 与现有求解器对照；仅在数据适配、规则映射和质量增益可证明时引入。
- Freerouting 的 DSN/SES 试布线验证；需先检查层叠/规则/网表转换完整性，不能直接把试布通率当最终质量证明。
- VLM 读取真实原厂布局图并提供“参考图 vs 实际布局”的辅助审查；不得作为唯一硬门禁。
- 跨板历史知识/Neo4j、复杂板型、完整 LangGraph、多 Agent 独立调度。

---

## 10. 验收评价方法：不要凭“演示成功”判断可落地

为避免样例过拟合，至少保留：**1 块开发样本 + 1 块未参与规则调优的验证样本**；条件允许时增加不同芯片/不同封装的局部电路。

| 指标 | 如何验证 | MVP 期望/口径 |
|---|---|---|
| 数据完整性 | AD26 与解析 JSON 的器件/Pad/Net 对照 | 关键范围全部一致；缺失必报错 |
| 写回正确性 | 提交 JSON 与 AD 回读比较 | 全部目标器件在定义容差内一致 |
| 工程不变性 | 写入前后网表、锁定器件与非目标器件 diff | 不允许未授权变更 |
| 已实现硬约束 | 独立几何校验，不直接相信求解器自身结果 | 0 违规；未覆盖规则单列 |
| 角色识别质量 | 与硬件工程师标签对照 | 逐类记录准确率及弃权率，不提前承诺百分比 |
| 布局实用性 | 工程师盲评候选与人工方案/基线 | 记录可用率、需修改器件数及主要问题 |
| 工程效率 | 计时从读取到工程师认可的初版布局 | 对照人工流程，计算净节省时间（含修正） |
| 稳定性 | 多次重复写入/恢复、异常注入 | 不能出现无快照不可逆工程损坏 |
| 保密 | 检查模型日志、网络调用、资产存储 | 未批准数据不得离开内网 |

**特别说明**：MVP 不以“整板 DRC 全部为零”“评分 85 分”或“70%～80% 工作量减少”作为未经验证的承诺。

---

## 11. 推荐技术栈与代码目录

### 11.1 技术栈（按能力选型，不要重复建设）

| 能力 | 首选/现有 | 使用原则 |
|---|---|---|
| 后端 | Python 3.11+、Pydantic、pytest | 统一 Schema、校验、自动回归 |
| AD 接入 | AD 内置脚本/SDK + 经验证 MCP，altium_monkey 作辅助解析 | 选择实际稳定读写路径，而不是堆 MCP 数量 |
| 图拓扑 | NetworkX | 分析局部器件和网络，避免仅靠度数聚类 |
| 几何 | Shapely | 统一 mm、变换后精确校验 |
| 初期求解 | OR-Tools（离散化）+ Python 局部搜索 | 固定 seed；候选可复现 |
| 知识库 | 现有 RAGFlow/图册 + 小型结构化规则集 | 图文溯源，硬规则需审核 |
| LLM | 公司批准的本地模型 / 内网 API | 结构化输出、局部证据，不直接执行写坐标 |
| 状态机 | 简单显式状态机，后续 LangGraph | 必须可回滚、可重试、有上限 |
| 持久化 | 起步 JSON + SQLite / 现有 MySQL | 首期无需 Neo4j/额外平台 |
| 可视化 | 生成 SVG/HTML 差异报告 | 初期不做完整 Web 拖拽界面 |

> 所有第三方项目的许可证（尤其 GPL/AGPL）、目标 AD26 小版本兼容性、商业内用/分发/网络服务义务，都需由项目组核查后再集成；不能仅凭“开源”二字认定无需审核。

### 11.2 建议项目目录

```text
ai_pcb_mvp/
├─ README.md
├─ pyproject.toml
├─ configs/
│  ├─ board_profile.example.yaml
│  └─ solver_defaults.yaml
├─ src/ai_pcb/
│  ├─ models/              # Pydantic: Board, Component, Pad, Net, Rule
│  ├─ adapters/            # EDAAdapter + 多个可替换实现
│  ├─ parser/              # 格式统一、坐标换算、数据一致性
│  ├─ graph/               # NetworkX 拓扑、子模块候选
│  ├─ semantics/           # 电路角色规则 + LLM 结构化候选
│  ├─ knowledge/           # RAG/来源证据/图册引用
│  ├─ rules/               # 规则编译、审批、冲突处理
│  ├─ geometry/            # 碰撞/区域/Pad 距离/坐标变换
│  ├─ solver/              # OR-Tools/局部搜索/Cypress(可选)
│  ├─ validation/          # 独立硬门禁 + AD 检查对比
│  ├─ execution/           # 只读/预览/写回/快照/回滚
│  ├─ workflows/           # 显式状态机/后续 LangGraph
│  └─ reports/             # JSON/HTML/SVG 报告
├─ tests/
│  ├─ fixtures/            # 脱敏最小测试板与预期数据
│  ├─ unit/
│  └─ integration/         # AD26 真实环境的集成测试
└─ runs/                   # 输入哈希、候选、日志、快照索引
```

### 11.3 先写哪些接口（建议依赖顺序）

1. `models`：确定 Pydantic Schema 和单位/版本规范；
2. `adapters`：先只读，后单器件写入、批量写入、快照恢复；
3. `geometry` 与 `validation`：先独立检查人工摆出来的既有板，证明校验器本身可信；
4. `graph` + `semantics`：小样本角色识别，严格证据记录；
5. `rules`：从已审批样例生成约束；
6. `solver`：先局部，输出多候选 JSON；
7. `execution`/`workflows`：合并成可审计闭环；
8. 再考虑多 Agent、Freerouting、Cypress、VLM 深度接入。

---

## 12. 主要风险与退出条件

| 风险 | 早期信号 | 应对/退出条件 |
|---|---|---|
| AD26 API/MCP 不兼容或不稳定 | 无法批量写、坐标错误、异常破坏工程 | 降级“只读+预览”；不强行靠 Windows 点击替代 |
| 离线解析不完整 | Pad/Net 缺失、禁布层语义丢失 | 使用 AD 运行态数据交叉核查；关键字段缺失则停机 |
| 功能角色识别错误 | 连接电源/GND 的电容被一概分类 | 结合引脚、器件值与原厂资料；低置信/歧义人工审核 |
| 知识库幻觉 | 原图无尺寸却输出精确毫米 | 数值硬约束须有真实来源与审批；未批准不执行 |
| 求解结果漂亮但电气质量差 | 飞线短，却破坏回流或环路 | 缩小模块、引入电路特定约束、工程师验收；必要时后期仿真 |
| 几何外形不准确 | Courtyard 缺失或不符合实物 | 记录几何来源，保守边界 + 人工审查 |
| 写入工程不可恢复 | AD 中断/部分写入/ECO 副作用 | 工作副本、文件快照、强制回读、失败恢复 |
| 过度架构 | 花大量时间接多 Agent/Neo4j，却无可运行板 | 坚持 P0/P1/P2 门槛和单模块闭环 |
| 开源许可/安全问题 | AGPL/GPL 义务未评估、敏感数据进入外部服务 | 法务/信息安全预审，内网默认闭环 |

---

## 13. Codex 评审任务（可以直接按此检查当前源码）

请 Codex **先审查，不要未经确认就大规模重构**。输出下面六项：

1. **现状差距矩阵**：当前已有代码能否读取 AD26 的 Board/Component/Pad/Net/Region？哪些字段缺失、需要什么工具实现？请逐项举实际代码位置。
2. **AD26 接口验证计划**：评估现有 AD 接入链路与候选 MCP；设计一个“复制工程 → 改单器件 → 回读 → 重开 → 恢复”的最小测试。
3. **统一数据模型审查**：明确原点/旋转/单位/Top-Bottom/Pad 位置/几何来源和文件版本处理，避免错误坐标。
4. **MVP 最小求解器**：选 1 个模块，列出硬/软约束、候选生成算法、独立几何校验方法，以及无解如何处理。
5. **验收与风险**：给出能自动测试的用例、人工必须验收的项目、不可实现或不确定的现有假设。
6. **最小开发任务拆分**：按 P0→P1→P2 排出依赖，每项说明输入/输出文件、模块路径、验收方式；区分“现有能力 / 新开发 / 需要验证 / 延后”。

**Codex 必须遵守**：

- 不把所有模块都设计成自治 Agent；
- 不把“相关 GitHub 项目存在”视为“接口已经兼容 AD26”；
- 不自动推断缺失电路规则中的距离数值；
- 不在未创建完整快照、未通过独立硬检时写回用户的正式设计文件；
- 不把 DRC 通过、试布通率或视觉相似当作 PCB 电气/制造最终合格证明。

---

## 14. 开源项目与资料入口（用于进一步验证，而非功能担保）

- Gemini 原始规划候选：
  - https://github.com/wavenumber-eng/altium_monkey
  - https://github.com/embedded-society/altium-designer-mcp
  - https://github.com/M-R-Abedini/Electronics_AI
  - https://github.com/NVlabs/Cypress
  - https://github.com/freerouting/freerouting
  - https://github.com/sbroenne/mcp-windows
- 本评审补充的 AD 接口候选：
  - https://github.com/coffeenmusic/altium-mcp
  - https://docs.developer.altium.com/ad-mcp-docs/
- 算法工具：
  - https://developers.google.com/optimization
  - https://shapely.readthedocs.io/
  - https://networkx.org/

> **来源说明**：本文是根据用户提供的 Gemini 初稿以及本轮工程评审整理的**修订建议**。初稿中的多 Agent、分层规则、图文解耦、四级器件分层、Goal/回滚等构想已择优保留；关于“先单模块、统一模型、独立校验、人工审批、减轻初期依赖”的内容为本评审提出的实施调整。开源项目的具体兼容性、许可和接口覆盖必须由项目组在目标环境复核。

---

**最终建议：** 先证明 **“一个 Buck/MCU 局部电路自动布局”** 在 AD26 工程中真实、可解释、可回滚地运行，再决定是否扩大为整板多 Agent 自动布局平台。
