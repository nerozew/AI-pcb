# AD26 AI 辅助 PCB 自动布局：最终架构（v1.0 定稿）

> 工程根目录 `D:\Code_all\AI-pcb`；基线 `eda_agent 0.8.1`（Apache-2.0）。
> Buck 6 器件链路已跑通，但原“5 hard”按单一事实源重新计数为：**3 个不变量 + 1 条 hard 规则 + 1 条 DRC advisory**。
> 下一目标 wisp6 65 器件，同一架构换板，不换模型。
> 本文只做设计，未修改任何文件。

---

## 0. 定稿结论

### 0.1 一句话方案

> **确定性 Step 流水线 + 独立几何 Gate 子进程 + 只写副本的执行器 + events WAL 单一事实源 + 只读观察/CLI 审批的控制台；LLM 只做规则提案，不产出坐标、不持有写权限。**

### 0.2 八条批评的落点

| # | 批评 | 修订结果 |
|---|---|---|
| 1 | EDA/planner 边界未闭合 | 所有 `eda_agent` 调用收进 `adapters/eda_agent/`；删除 `planner`、`execution/`；`place_job` 隔离子进程执行；AST 强制唯一入口 |
| 2 | Gate 契约与 DRC advisory 不自洽 | Gate 只读输入、JSON 写 stdout，worker 提交 `06`；DRC 独立为 `11_drc_advisory.json`；比较键加 `measured_nm` 与量化坐标；删除 `drc_baseline` 规则类型 |
| 3 | 写回链预复制违反 I3 | 删除 stage→output 预复制；`save_copy_as` 只写 `output/.staging/<id>/`，校验后原子 rename；intent 记录 `output_absent_before=true` |
| 4 | 双状态源，Step 能写 events | `events.jsonl` 为 WAL/唯一事实源；`run.json` 只是 checkpoint（带 `last_event_seq`）；`StepContext` 移除 `events`；提交顺序固定 |
| 5 | 同一事实的权威来源不唯一 | 增加 eda_agent 复用矩阵；板级事实只做 invariant；fingerprint 拆 `geometry_fingerprint` / `governance_hash`；Constraint 拆 `semantic_hash` / `governance_hash` |
| 6 | v1 过度设计 | 5 个 RunState、5 个 WriteState、8 个 Step、1 个 `04_compile.json`、3 种 claim kind、4 个 ports；删除 LangGraph/Advisor/RAGFlow/ToolBox.llm 桩；旧包归档 |
| 7 | Web 范围过大，审批身份未闭合 | v1 只做 2 个服务端页面 + 4 个只读 API + 3 秒轮询；审批走 CLI；reviewer 由服务端 `getpass.getuser()` 推导；`expected_hash` 过期 409 |
| 8 | search/select 与知识、预览无质量验收 | 定义 `SelectionScore` 并把 HPWL 纳入；20 条标注集；`retrieval_manifest` + hit@3；preview 保真测试 |

### 0.3 已拍板，不再讨论

| 决策 | 结论 |
|---|---|
| 主链是否走 MCP | **不走**。主链进程内 Python bridge；MCP 在 v1 不启动，仅 P3 人工只读诊断 |
| 是否用 LangGraph | **v1 不用**。Step 顺序就是状态机；P3 需要并行/跨进程恢复时再换 Driver |
| 是否自治多 Agent | **不做**。只有 Step 分工；LLM 规则提案是一个普通函数，不是 Agent 框架 |
| 规则数值来源 | 只允许 `quoted / human_entered / demo_placeholder`；无来源数值进 `review_required` |
| hard 由谁决定 | 作者写 `severity_intent`；编译器推导 `enforcement`；hard-intent 失败只进 `review_required`，绝不静默降 soft |
| DRC 是否参与门禁 | **不参与**。独立几何 Gate 决定 verdict；DRC 只写 `11_drc_advisory.json` |
| 写回目标 | 只写 run 目录下 `output/project/`；源工程只复制、只哈希、从不打开 |
| 状态权威 | `events.jsonl`；`run.json` 是 checkpoint；审批账本是 events 的投影 |
| 数据库 | v1 文件 + JSONL；SQLite/PG 为 P3 |
| Web 技术 | FastAPI + Jinja2 + 原生 JS + 3 秒轮询；无 npm/React/Vue/SSE/WebSocket |
| 审批入口 | v1 CLI（`pcbctl`）；Web 审批为 P2/P3 |
| 旧代码 | 现有 `src/ai_pcb` 归档到 `legacy/ai_pcb_v0/`；新实现占用 `src/ai_pcb`，旧代码不被 import |

### 0.4 v1 最小闭环

Buck 6 器件：读板 → 知识 → 规则提案 → 编译 → 候选 → 独立几何 Gate → 选优 → 人工审批 → 写 output 副本 → 重读/Gate/DRC → 报告 → 2 个 Web 页面。

验收标准不是“页面好看”，而是：

1. 源工程哈希前后不变；
2. 硬门禁可离线复算；
3. 每条规则能追到页码、数值来源、审批事件；
4. 写回失败可回滚，未知状态可对账；
5. 同一输入重放，关键产物哈希一致。

---

## 1. 边界、进程与依赖

### 1.1 进程模型

```text
浏览器
  │ HTTP：Jinja2 页面 + 4 个只读 JSON API + 3 秒轮询
FastAPI（127.0.0.1:8000，uvicorn --workers 1；不 import eda_agent）
  │ 只读 work/runs/<run_id>/；新建时只写 request.json
  ▼
worker 进程（单实例，串行处理 run；持有 AD bridge 与写租约）
  ├─ orchestrator：Step 顺序、checkpoint、events
  ├─ steps：8 个业务阶段
  ├─ adapters/eda_agent：bridge、读板、place_job、DRC、save_copy_as
  └─ gate 子进程：python -I -m ai_pcb.checks.gate_runner（禁止 eda_agent）
        │
        ▼
  eda_agent Python bridge → AD26 + 轮询脚本
```

进程边界的原因：

- `eda_agent` bridge 是进程级单例 + keepalive 线程；FastAPI reload/多 worker 会复制 bridge、抢同一 workspace。
- Web 不 import `eda_agent`，控制台不会变成第二个黑盒。
- Gate 必须在独立子进程，才能证明硬门禁不依赖 `eda_agent` 的 DRC 结论。
- 单 worker 串行是 v1 硬约束：`eda_agent` 没有事务隔离，两个 run 同时写同一块板会互相覆盖。

### 1.2 目录树

```text
D:\Code_all\AI-pcb\
├─ pyproject.toml                 # eda_agent==0.8.1, shapely>=2,<3, pydantic>=2, fastapi, jinja2
├─ configs\
│  ├─ policies\demo.json、production.json
│  ├─ rules\buck.demo.json
│  └─ executor.yaml
├─ src\ai_pcb\
│  ├─ domain\       units.py primitives.py entities.py snapshot.py governance.py
│  │                placement.py constraint.py index.py
│  ├─ geometry\     kernel.py shapely_kernel.py transform.py measure.py
│  ├─ rules\        schema.py kinds.py claims.py admission.py conflicts.py
│  │                compiler.py approval.py cli.py
│  ├─ checks\       results.py context.py registry.py invariants.py
│  │                side_check.py distance_check.py keepout_check.py
│  │                rotation_check.py gate.py gate_runner.py
│  ├─ knowledge\    json_source.py verify.py service.py
│  ├─ ports\        reader.py placer.py drc.py writer.py
│  ├─ adapters\eda_agent\ supervisor.py bridge.py reader.py placer.py
│  │                drc.py writer.py mapping.py guard.py preview.py
│  ├─ artifacts\    envelope.py store.py hashing.py verify.py
│  ├─ orchestrator\ run_record.py engine.py registry.py context.py
│  │                store.py events.py approvals.py policies.py errors.py
│  ├─ steps\        prepare.py knowledge.py rules.py candidates.py
│  │                validate_repair.py plan_writeback.py write_verify.py report.py
│  ├─ reports\      run_report.py preview_svg.py normalize.py
│  └─ web\          app.py routes\runs.py schemas.py
│                   templates\runs_list.html、run_detail.html
│                   static\app.css、poll.js
├─ scripts\         pcbctl.py import_legacy.py
├─ legacy\ai_pcb_v0\              # 旧 src/ai_pcb 整体归档
├─ docs\adr\0001-p3-options.md     # LangGraph/RAGFlow/Neo4j/VLM 一页 ADR
├─ work\
│  ├─ runs\<run_id>\
│  └─ rulesets\<ruleset_id>\ledger.jsonl   # 审批投影，不是权威
└─ tests\
   ├─ fixtures\boards\buck.snapshot.json、buck.governance.json
   ├─ fixtures\evidence\buck.passages.json
   ├─ fixtures\rules\buck.demo.json
   ├─ fixtures\legacy\rule_loop_report.json
   ├─ golden\buck\*.json
   ├─ unit\、contract\、acceptance\、web\
   └─ test_purity.py
```

删除的盒子：`planner`、`execution/`、`advisors/`、`orchestrator/drivers/langgraph.py`、`adapters/knowledge`、`adapters/rules`、`adapters/approvals`。

### 1.3 依赖红线（`tests/test_purity.py` AST 强制）

| 模块 | 允许 import | 禁止 |
|---|---|---|
| `domain/` | stdlib | 一切第三方、eda_agent、pydantic |
| `geometry/` | stdlib + shapely（仅 `shapely_kernel.py`） | eda_agent、fastapi |
| `rules/` | stdlib + pydantic | eda_agent、fastapi、shapely |
| `checks/` | stdlib + domain + geometry | eda_agent、fastapi、comtypes、win32com |
| `knowledge/` | stdlib + pydantic（仅边界） | eda_agent、fastapi |
| `orchestrator/`、`steps/` | stdlib + domain/ports/rules/checks/artifacts | eda_agent、fastapi、具体 adapter |
| `web/` | stdlib + fastapi + jinja2 + schemas | eda_agent、comtypes、win32com |
| `adapters/eda_agent/` | eda_agent + ports/domain | 其他模块不得 import eda_agent |
| gate 子进程 | domain/geometry/checks | eda_agent、网络、run 目录写入 |
| `reports/` | domain/geometry/artifacts | eda_agent |

`test_purity.py` 用 AST 扫描，不执行模块；CI 没有 AD 也能跑。

### 1.4 eda_agent 能力复用矩阵

| 能力 | eda_agent 模块 | v1 用法 | 说明 |
|---|---|---|---|
| 桥、心跳、轮询 | `bridge`、`application.ping` | **adapter 直用** | supervisor 管理生命周期 |
| 读板 | `pcb.get_layout_model`、`layout.read_altium` | **adapter 直用** | 唯一读板入口 |
| 布局候选 | `layout.place.job.place_job` | **adapter 子进程** | 子进程隔离 live 写入；内部 DRC 只作元数据，不作 verdict |
| 精确 DRC | `layout.drc.verdict` | **adapter 直用** | 只写 `11_drc_advisory.json` |
| 几何/审计 | `layout.geom`、`layout.audit`、`layout.rotation_audit` | **仅测试 oracle** | Buck/wisp6 差分测试，不进主链 |
| 板级规则 | `layout.rules` | **只读参考** | 数值以读入的 `BoardRule` 为准，不把库当权威 |
| 阶段门 | `design.phase_gates` | **不用** | 我们的独立 Gate 是唯一硬门禁 |
| 预览/快照 | `render.pcb_svg`、`design.live.snapshot` | **仅测试 oracle** | 运行时预览由 `BoardSnapshot + Placement` 纯 Python 生成 |
| 写副本 | `pcb.save_copy_as` | **adapter 直用** | 唯一 EDA 落盘写 |
| MCP | `eda_agent` MCP server | **v1 不启动** | P3 人工只读诊断 |

`place_job` 的处理：它内部会调用 `live.publish_safe` 并跑一次 DRC。v1 由 `adapters/eda_agent/placer.py` 在独立子进程中调用，工作目录/workspace 指向 `work/runs/<id>/eda_workspace/`；返回后只保留 candidate 数据，内部 DRC 字段改名为 `placer_internal_drc`，不进入 GateReport。若后续版本提供 `publish_live=False`，直接切换。

---

## 2. 核心域与数据契约

### 2.1 单位与几何约定

- 内部坐标一律整数纳米（nm），角度整数毫度（mdeg），`90000 = 90°`。
- 长度换算只在边界：规则作者 mm → 编译器 nm；eda_agent mil → adapter nm；UI nm → mm。
- 多边形不闭合、统一逆时针；圆弧离散容差 ≤ 0.01 mm。
- 器件自有几何存局部坐标；世界坐标由 `Component.pose` 变换；bottom 面含镜像。
- `eda_agent` 的 `place_job` 按整 mil 取整；1 mil = 25400 nm，转换精确。

```python
@dataclass(frozen=True, slots=True)
class Pose:
    x_nm: int
    y_nm: int
    rotation_mdeg: int
    side: Literal["top", "bottom"]

@dataclass(frozen=True, slots=True)
class Component:
    ref: str
    footprint: str
    pose: Pose
    courtyard: Polygon
    courtyard_source: Literal["courtyard", "body", "primitives", "pads"]
    pads: tuple[Pad, ...]
    source_locked: bool          # 只来自 AD 的 LOCKED，不等于 anchor
    height_nm: int
    properties: Mapping[str, str]

@dataclass(frozen=True, slots=True)
class BoardSnapshot:
    schema_version: str
    board_id: str
    source: BoardSource
    outline: Polygon
    cutouts: tuple[Polygon, ...]
    layers: tuple[Layer, ...]
    components: tuple[Component, ...]
    nets: tuple[Net, ...]
    regions: tuple[Region, ...]
    board_rules: tuple[BoardRule, ...]
    geometry_fingerprint: str

@dataclass(frozen=True, slots=True)
class Placement:
    geometry_fingerprint: str
    poses: Mapping[str, Pose]   # 全量，不是只存 move
```

### 2.2 指纹拆分：几何与治理

```python
geometry_fingerprint = sha256_canonical(
    board_id, outline, cutouts, layers,
    # 组件只取物理事实，不含审批状态
    components[ref, footprint, pose, source_locked, courtyard, pads, pad_net],
    nets, regions(geometry), board_rules(values)
)

governance_hash = sha256_canonical(
    geometry_fingerprint,
    regions[region_id, review_status],
    board_rules[origin, source_ref, review_status],
    ruleset.semantic_hashes, ruleset.governance_hashes,
    policy.id, policy.hash
)
```

- `Placement` 只绑 `geometry_fingerprint`；Gate 先校验，不一致返回 `E_STALE_PLACEMENT`。
- 改 region 审批状态、改规则审批，不会让 placement 失效；只会让 GateReport/规则哈希变化。
- 改板子物理几何，placement 和规则结果全部失效。

### 2.3 Constraint 拆分：语义与治理

```python
@dataclass(frozen=True, slots=True)
class RuleSemantic:
    constraint_id: str
    rule_id: str
    rule_version: int
    kind: str
    scope: Mapping[str, tuple[str, ...]]
    targets: Mapping[str, tuple[str, ...]]  # 已解析成 pad_id/net_id/region_id
    params: tuple[ParamValue, ...]
    source_ref: SourceRef
    evidence: tuple[EvidenceBinding, ...]
    checker_id: str
    semantic_hash: str

@dataclass(frozen=True, slots=True)
class RuleGovernance:
    enforcement: Literal["hard", "soft", "info"]
    governance: Literal["approved", "approved_demo", "proposed"]
    approval_ref: str | None
    decision_ref: str
    review_status: str
    governance_hash: str

@dataclass(frozen=True, slots=True)
class Constraint:
    semantic: RuleSemantic
    governance: RuleGovernance
```

- 改数值/目标/测量方式 → `semantic_hash` 变化 → 旧审批自动失效。
- 只重新审批 → `governance_hash` 变化 → 规则语义哈希不变。
- 检查器只认 `Constraint.semantic`；不读原始 YAML/JSON，不从字符串猜目标，不做单位换算。

### 2.4 运行目录与 artifact envelope

```text
work/runs/<run_id>/
├─ request.json            # Web 只写这一个文件；worker 接管
├─ run.json                # checkpoint：state、resume_step、last_event_seq
├─ events.jsonl            # append-only WAL，唯一事实源
├─ manifest.json           # logical name -> ArtifactRef
├─ artifacts/              # 00–12
├─ stage/project/          # 源工程完整副本；AD 只打开它
├─ output/project/         # 唯一落盘写目标（最终）
├─ output/.staging/<id>/   # save_copy_as 临时目标
├─ eda_workspace/          # place_job/live 的隔离目录
├─ approvals/              # CLI 审批请求与结果快照
└─ logs/
```

Artifact envelope：

```json
{
  "schema": "ai_pcb.artifact/1.0",
  "artifact_type": "compile",
  "run_id": "20261125-1015-buck-a1",
  "stage": "04",
  "created_at": "2026-11-25T10:16:03+08:00",
  "producer": {"name": "rule_compiler", "version": "0.1.0"},
  "policy": {"id": "demo", "hash": "sha256:77ab..."},
  "inputs": [
    {"stage": "01", "path": "artifacts/01_board_snapshot.json", "sha256": "sha256:..."},
    {"stage": "03", "path": "artifacts/03_rule_proposals.json", "sha256": "sha256:..."}
  ],
  "payload_schema": "ai_pcb.compile/1.0",
  "payload": {},
  "payload_sha256": "sha256:..."
}
```

- `payload_sha256` 只对 payload 做 canonical JSON 哈希；文件 SHA-256 记在 manifest。
- 写入先 `.tmp`、fsync、`os.replace`；不允许原地修改 artifact；重跑生成新 run 目录。
- `events.jsonl` 每行带 `seq`、`prev_hash`、`hash`；事件类型固定枚举。

---

## 3. 规则系统

### 3.1 生命周期

```text
draft -> proposed -> approved -> deprecated
                   \-> rejected
demo 专用：approved_demo
```

- `approved`：审批人非空且不等于创建者；审批事件存在且 `semantic_hash` 匹配。
- `approved_demo`：`demo_note` 非空；不允许伪造工程师；生产模式不承认。
- LLM 自批直接拒绝。

### 3.2 NumericClaim 只保留三种

| kind | 含义 | 可进 hard | 条件 |
|---|---|---|---|
| `quoted` | 原文明确写出数值+单位 | 是 | quote 命中 passage，number_token 在 quote 内，换算一致 |
| `human_entered` | 工程师人工确定 | 是 | `entered_by` + `rationale` + 审批事件 |
| `demo_placeholder` | demo 占位值 | 否 | 仅 demo 模式 |

- 无来源即“缺 claim”，直接 `review_required`，不再有 `absent` / `visual_inferred` 类型。
- 单位换算（如 mil→mm）作为 `quoted.conversion` 字段，不单独设 `derived` kind。
- VLM/图片只能产出 `demo_placeholder` 或人工录入，永远不能直接支撑 hard。
- Schema 里 **不允许裸 float**；数值用字符串或整数表示，编译后只存 nm/mdeg 整数 + `claim_ref`。

### 3.3 规则提案示例

```json
{
  "schema_version": "ai_pcb.rule_proposal_set/1.0",
  "board_id": "buck",
  "geometry_fingerprint": "sha256:9a7d...",
  "proposer": {"kind": "llm", "id": "rule-proposer-v1", "model": "internal-llm"},
  "passages_used": ["p_3f2a9c1d"],
  "rules": [
    {
      "rule_id": "R_DEMO_CIN_VIN",
      "version": 1,
      "kind": "max_pad_distance",
      "severity_intent": "soft",
      "scope": {"board": "buck", "components": ["C2", "IC1"]},
      "targets": {"a": "C2", "a_pad": "1", "b": "IC1", "b_pad": "VIN", "net": "IN"},
      "params": {
        "max_distance_mm": {
          "kind": "human_entered",
          "value": "5.0",
          "unit": "mm",
          "entered_by": "engineer:zhang",
          "rationale": "数据手册只写 close to VIN；5mm 为首版工程取值"
        },
        "measure": "center_to_center"
      },
      "source_ref": {
        "origin": "datasheet",
        "document_id": "TI-SLVSC95A",
        "revision": "A",
        "pages": [19],
        "quote": "Place the input capacitor close to VIN and PGND ..."
      },
      "evidence": [{"passage_id": "p_3f2a9c1d", "role": "primary"}],
      "created_by": {"kind": "llm", "id": "rule-proposer-v1", "model": "internal-llm"},
      "confidence": 0.6
    }
  ]
}
```

关键：数据手册只写 “close”，5mm 来自工程师，所以 `kind=human_entered`；`measure` 必须显式写，不能默默默认。

### 3.4 v1 规则 kind 只保留五个

| kind | targets | params | checker | 最大级别 |
|---|---|---|---|---|
| `side` | components/scope | `side` | `side_check` | hard |
| `max_pad_distance` | `a`,`b`；可选 `a_pad`,`b_pad`,`net` | `max_distance_mm`, `measure` | `distance_check` | hard |
| `min_pad_distance` | `a`,`b`；可选 `net_a`,`net_b`,`layers` | `min_distance_mm`, `measure` | `distance_check` | hard |
| `keepout` | components/scope | `region_kinds` | `keepout_check` | hard |
| `rotation_set` | components/scope | `allowed_deg` | `rotation_check` | hard |

板级事实不再作为规则：

- `anchor` → 只由不变量 `I_ANCHOR` 执行，目标是 `source_locked ∪ run.pinned_refs`；`pinned_refs` 来自 `00_run_config` 的人工输入，不是规则。
- `inside_outline` → `I_INSIDE_OUTLINE`。
- `netlist` → `I_NETLIST`。
- `drc_baseline` → 删除；DRC 永远是 `11_drc_advisory.json`，写回策略可额外要求 `no_new_drc`。

提案里出现这些 kind，编译器拒绝：`E_BOARD_FACT_IS_INVARIANT` 或 `E_DRC_IS_ADVISORY`。
P1 可选 kind：`region_containment`、`edge_clearance`、`pin`、`mask_sliver`。每种 kind 不允许数值默认值。

### 3.5 准入与冲突

hard-intent 必须全部通过：结构合法、板卡几何指纹匹配、kind/checker 存在、targets 可解析、参数完整、距离类 `measure` 显式、`source_ref` 存在、claim kind 允许、审批事件绑定 `semantic_hash`。
任一项失败 → `review_required`；schema 非法 → `rejected`；soft-intent 目标/参数/checker 都 OK → `soft`，blocking conflict → `info`。
**hard-intent 绝不静默降级为 soft。**

理由码保留：`E_SCHEMA`、`E_DUPLICATE_ID`、`E_BOARD_MISMATCH`、`E_UNKNOWN_KIND`、`E_NO_CHECKER`、`E_TARGET_NOT_FOUND`、`E_TARGET_AMBIGUOUS`、`E_PARAM_MISSING`、`E_PARAM_RANGE`、`E_MEASURE_MISSING`、`E_SOURCE_MISSING`、`E_LOCATOR_MISSING`、`E_QUOTE_MISMATCH`、`E_NUMBER_NOT_IN_QUOTE`、`E_APPROVAL_MISSING`、`E_STALE_APPROVAL`、`E_SELF_APPROVAL`、`E_CONFLICT`、`E_BOARD_FACT_IS_INVARIANT`、`E_DRC_IS_ADVISORY`。

冲突类型：`duplicate_rule_id`、`param_conflict`、`role_conflict`、`side_conflict`、`containment_conflict`。
`scope_key = kind | targets | param_names`；`conflict_id` 由内容哈希生成；数值一改，旧 resolution 自动失效。
人工 resolution 枚举：`prefer_rule`、`narrow_scope`、`supersede_rule`、`reject_all`；v1 不自动裁决。

### 3.6 编译器与单一 `04_compile.json`

```python
def compile_rules(
    proposals: ProposalSet,
    board: BoardIndex,
    policy: CompilePolicy,
    *,
    evidence: EvidenceIndex,
    approvals: ApprovalIndex,
    conflict_resolutions: Sequence[ConflictResolution] = (),
    now: datetime,
) -> CompilationResult: ...
```

纯函数：不读文件、不访问网络、不调用 `eda_agent`、不使用随机数；时间只来自 `now`；输出按 `rule_id`、`version` 排序；同输入同 policy 同审批 → 同 `content_hash`。

只产出一个 `04_compile.json`：

```json
{
  "schema": "ai_pcb.compile/1.0",
  "policy": {"id": "demo", "hash": "sha256:..."},
  "effective_rules": {
    "hard": [],
    "soft": [],
    "info": []
  },
  "review_queue": [],
  "conflicts": [],
  "decisions": [],
  "provenance": {},
  "hashes": {
    "semantic": "sha256:...",
    "governance": "sha256:...",
    "effective": "sha256:..."
  }
}
```

`decisions` 保证每条输入规则恰好一个 decision；`provenance` 是 `rule_id@version -> source / evidence / claims / approval / decision` 的映射。

### 3.7 审批：CLI 事件，账本只是投影

- v1 审批走 CLI：

```text
pcbctl approve rules --run-id <id> --rule-id R_DEMO_CIN_VIN --note "5mm 首版取值"
pcbctl approve writeback --run-id <id> --expected-report-hash sha256:... --confirm-copy
```

- `reviewer = getpass.getuser()`，服务端推导；CLI 不接受 `--reviewer`。Web 审批接口若出现请求体 `reviewer`，返回 400。
- 审批写入 `events.jsonl` 的 `approval.decided` 事件，绑定 `semantic_hash`（规则）或 `report_hash + plan_hash`（写回）。
- `work/rulesets/<id>/ledger.jsonl` 由 `rules/approval.py` 从 events 投影生成，带 `source_last_event_seq`；它是审计导出，不是权威。编译器接收 `ApprovalIndex`（从 events 构建），不读账本当权威。
- 审批过期（`expected_hash` 不匹配）返回 409 `STALE_SUBJECT`；CLI 退码 3。

---

## 4. 检查与 Gate

### 4.1 Checker 接口

```python
@dataclass(frozen=True, slots=True)
class CheckContext:
    board: BoardSnapshot
    governance: BoardGovernance
    placement: Placement
    baseline: BoardSnapshot
    baseline_placement: Placement
    kernel: GeometryKernel
    baseline_mode: Literal["absolute", "delta"]
    tolerance_nm: int = 1_000

@dataclass(frozen=True, slots=True)
class CheckResult:
    constraint_id: str
    kind: str
    status: Literal["pass", "fail", "not_evaluated", "not_applicable"]
    measurements: tuple[Measurement, ...] = ()
    violations: tuple[Violation, ...] = ()
    blocked_by: tuple[str, ...] = ()
    message: str = ""

class Checker(Protocol):
    kind: ClassVar[str]
    def check(self, constraint: Constraint, ctx: CheckContext) -> CheckResult: ...
```

检查器只依赖 `Constraint.semantic`、`BoardSnapshot`、`Placement`、`GeometryKernel`；不 import `eda_agent`，不读文件，不写文件。

### 4.2 内建不变量（不可关闭、不可 soft 化）

| ID | 检查 | 模式 |
|---|---|---|
| `I_BOARD_BINDING` | placement 指纹与 board 一致 | absolute |
| `I_NETLIST` | 组件、pad、pad→net、net 与基线一致 | absolute |
| `I_ANCHOR` | `source_locked ∪ run.pinned_refs` 位姿不变 | absolute |
| `I_INSIDE_OUTLINE` | 组件 world courtyard 在 outline − cutouts 内 | absolute |
| `I_COMPONENT_OVERLAP` | 同面 courtyard 不相交 | absolute |
| `I_PAD_CLEARANCE` | 同层不同 net 铜间距 ≥ 板级 clearance | delta（Buck）/ absolute（wisp6 校准后） |

- `I_PAD_CLEARANCE` 的数值来自 `BoardRule`，不是代码常量。
- `I_MASK_SLIVER` 为 P1；v1 只保留证据解释，不阻断。
- 板级事实只有这一条执行路径；规则系统不再重复实现。

### 4.3 Gate 子进程契约

- 启动方式：`sys.executable -I -m ai_pcb.checks.gate_runner`；M0 必须 `pip install -e .`，否则 `-I` 下 `src` layout 不可导入。
- 输入：一个只读 JSON 文件路径（board、governance、placement、baseline、04 的 effective_rules、policy）。
- 输出：JSON 写 stdout；**不写 run 目录**。
- 退出码：0 表示产出了合法报告（即使 verdict=fail）；2 表示输入非法/崩溃。worker 捕获 stdout，校验 schema，再原子写 `06_gate/<candidate>.json`。
- 非零/无 JSON → 该候选标 `invalid`，错误码 `E_GATE_CRASH`，绝不当作 pass。

判定顺序固定：`I_BOARD_BINDING` → 其余不变量按 ID → hard constraints 按 `constraint_id` → soft constraints 按 `constraint_id`。

```text
fail       任一 invariant 或 hard constraint 为 fail
incomplete 任一 invariant 或 hard constraint 为 not_evaluated（fail closed）
pass       其余
```

`not_applicable` 不算失败，但必须给原因。soft 的 `not_evaluated` 不阻断 verdict，但进 selection 指标。

### 4.4 GateReport

```json
{
  "schema": "ai_pcb.gate_report/1.0",
  "candidate_id": "cand_analytic_0",
  "geometry_fingerprint": "sha256:9a7d...",
  "governance_hash": "sha256:41c2...",
  "rules_hash": "sha256:31fe...",
  "placement_hash": "sha256:be02...",
  "verdict": "pass",
  "baseline_mode": "delta",
  "summary": {
    "invariants": {"total": 6, "pass": 6, "fail": 0, "not_evaluated": 0},
    "hard": {"total": 1, "pass": 1, "fail": 0, "not_evaluated": 0},
    "soft": {"total": 4, "pass": 2, "fail": 2, "not_evaluated": 0}
  },
  "hard": [],
  "soft": [
    {
      "constraint_id": "R_DEMO_CIN_VIN@1",
      "kind": "max_pad_distance",
      "status": "fail",
      "measurements": [
        {"name": "distance", "value_nm": 5780000, "method": "center_to_center"}
      ],
      "limit_nm": 5000000,
      "blocked_by": ["L1", "R2"],
      "violations": [
        {"object_a": "R2.1", "object_b": "C2.7", "layer": "TopLayer",
         "detail": "clearance", "measured_nm": 0, "required_nm": 254000}
      ]
    }
  ],
  "report_hash": "sha256:..."
}
```

**GateReport 不含 `advisories`，不含 DRC。** 文件由 worker 提交，`report_hash` 只覆盖报告内容与输入哈希。

### 4.5 DRC advisory：独立文件，独立类型

`11_drc_advisory.json`：

```json
{
  "schema": "ai_pcb.drc_advisory/1.0",
  "status": "pass",
  "source": "eda_agent 0.8.1 layout.drc",
  "baseline": {"total": 37, "run_id": "p0_buck"},
  "candidate": {"total": 37, "new": 0, "worsened": 0, "fixed": 0},
  "comparison": {
    "identity": "rule|layer|a|b",
    "signature": "identity|required_nm|measured_nm_1um|ax_1um|ay_1um|bx_1um|by_1um"
  },
  "rows": []
}
```

- 比较键包含 `measured_nm`（按 1 µm 取整）和两端量化坐标；仅按 `rule|layer|a|b` 计数会让“平移后的同一条违规”被抵消成 `new=0`。
- 分类：`new`（候选有、基线无）、`worsened`（同一 identity 的 measured 变差超过 1 µm）、`fixed`、`unchanged`。
- `status=pass` 仅当 `new=0` 且 `worsened=0`；DRC 不参与 `GateReport.verdict`。
- 写回策略若要求“不写回 DRC 变差的布局”，在 `authorize_writeback` 里检查 `11`，仍然与 Gate 类型分离。

### 4.6 写回授权是独立函数

```python
def authorize_writeback(
    report: GateReport,
    approval: HumanApproval,
    drc: DrcAdvisory,
    policy: WritebackPolicy,
) -> WritebackDecision: ...
```

```python
@dataclass(frozen=True, slots=True)
class WritebackPolicy:
    require_gate_pass: bool = True
    require_no_not_evaluated: bool = True
    require_human_approval: bool = True
    require_output_is_copy: bool = True
    require_no_new_drc: bool = False   # Buck demo 可设 True
```

这样“DRC 只作信息”和“工程上不想写回 DRC 变差的布局”同时成立，但类型上分开。

---

## 5. 编排与执行

### 5.1 只有 5 个 RunState、5 个 WriteState

```text
RunState:   RUNNING | NEEDS_HUMAN | SUCCEEDED | FAILED | ABORTED
WriteState: NONE | INTENT_WRITTEN | SAVED | VERIFIED | UNKNOWN
```

- 不再为“上一步完成”建状态；用 `last_completed_step`、`resume_step`、`resume_mode` 表达进度。
- `QUARANTINED` 不是独立状态：写成 `state=NEEDS_HUMAN, waiting_for=reconcile_write, write_state=UNKNOWN`。
- 写回过程中的 `APPLYING / APPLIED_MEMORY / SAVING / REOPENED / GATED` 都是瞬时阶段，不持久化；崩溃后由 `write_state` + 文件哈希重建。

```json
{
  "schema_version": "run/v2",
  "run_id": "20261125-143012-wisp6-a1b2",
  "state": "NEEDS_HUMAN",
  "last_completed_step": "plan_writeback",
  "resume_step": "write_verify",
  "resume_mode": null,
  "waiting_for": "writeback_approval",
  "write_state": "NONE",
  "last_event_seq": 87,
  "mode": "apply_copy",
  "board": {"board_id": "wisp6", "geometry_fingerprint": "sha256:..."},
  "ruleset": {"ruleset_id": "wisp6-v1", "effective_hash": "sha256:..."},
  "last_error": null
}
```

### 5.2 8 个 Step

| # | Step | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| 1 | `prepare` | 源工程路径、run config | `00`、`01`、source manifest、stage 副本 | 路径守卫、复制、打开 stage 只读、基线快照 |
| 2 | `knowledge` | `01`、query | `02` + `retrieval_manifest` | JSON 语料；quote 校验 |
| 3 | `rules` | `01`+`02`+policy | `03`、`04` | 规则提案 + 编译；可触发 `rule_approval`；审批后以 `recompile` 模式复跑 |
| 4 | `candidates` | `01`+`04` | `05` + baseline 候选 | `place_job` 隔离子进程；固定 seed |
| 5 | `validate_repair` | `01`+`04`+`05` | `06`、`07` | Gate、有限修复、选择；不写回 |
| 6 | `plan_writeback` | `06`+`07` | `08` | 写回计划；触发 `writeback_approval` |
| 7 | `write_verify` | `08`+审批 | `09`、`10`、`11` | intent、应用、save_copy_as、重读、后置 Gate、DRC |
| 8 | `report` | 全部 | `12` | 报告 + SVG 预览 |

Step 硬规则：

- 只能通过 `ctx.artifacts` 读写；不得修改已提交产物。
- 不得自己改 `run.state`；只返回 `StepResult`，由 Engine 写事件和 checkpoint。
- 所有外部调用经 `ctx.tools`（reader/placer/drc/writer），便于录制/回放/故障注入。
- Step 内部由小函数组成；Step 只负责一个业务阶段，不把多个业务目标混在一起。

```python
class StepResult(BaseModel):
    status: Literal["ok", "retryable", "failed", "needs_human"]
    outputs: list[ArtifactRef] = []
    metrics: dict = {}
    error: StepError | None = None
    next_hint: str | None = None

@dataclass(frozen=True)
class StepContext:
    run: RunRecord
    artifacts: ArtifactStore
    tools: ToolBox          # eda / knowledge / llm（仅 rules step 使用）
    policy: Policy
    attempt: int
    cancel: CancellationToken
    # 注意：没有 events；Engine 统一发事件
```

### 5.3 状态转移与 Engine

整个 FSM 只有下面几条：

| From | 条件 | To |
|---|---|---|
| RUNNING | Step 返回 ok，还有下一步 | RUNNING（`resume_step` 前移） |
| RUNNING | Step 返回 ok，最后一步完成 | SUCCEEDED |
| RUNNING | Step 返回 needs_human | NEEDS_HUMAN（记录 `waiting_for`） |
| NEEDS_HUMAN | 审批事件到达且哈希匹配 | RUNNING（回到 `resume_step`） |
| RUNNING | Step 永久失败 | FAILED |
| RUNNING | 用户取消 | ABORTED |

```python
def advance(run_id: str) -> None:
    run = store.load_checkpoint(run_id)
    if run.state != "RUNNING":
        return
    step = registry[run.resume_step or registry.next_after(run.last_completed_step)]
    result = step(StepContext(...))
    if result.status == "ok":
        emit_step_ok(run, step, result)        # 先事件，后 checkpoint
    elif result.status == "needs_human":
        emit_state(run, "NEEDS_HUMAN", waiting_for=result.next_hint)
    elif result.status == "retryable":
        retry_with_budget(run, step)
    else:
        emit_state(run, "FAILED", error=result.error)
```

审批恢复：

- 规则审批 → `state=RUNNING, resume_step=rules, resume_mode=recompile`；`rules` 检测到已有 `03` 时跳过提案，只重编译。
- 写回审批 → `state=RUNNING, resume_step=write_verify`。
- 对账 → `state=RUNNING, resume_step=write_verify, resume_mode=reconcile`。

### 5.4 events WAL：唯一事实源

事件类型固定枚举：

```text
run.created, run.recovered, state.changed,
step.started, step.finished, step.failed,
artifact.committed, approval.requested, approval.decided,
write.intent, write.saved, write.verified,
rollback.done, run.finished
```

每行：

```json
{"seq":42,"ts":"2026-11-25T10:15:31Z","run_id":"run_...","kind":"step.finished",
 "step":"validate_repair","attempt":1,"status":"ok","duration_ms":812,
 "artifacts":["06_gate","07_selection"],"metrics":{"candidates":2,"hard_ok":1},
 "prev_hash":"sha256:...","hash":"sha256:..."}
```

提交协议（固定顺序）：

1. artifact 写临时文件 → fsync → `os.replace`；
2. append `artifact.committed` 事件 → fsync；
3. append `step.finished` / `state.changed` → fsync；
4. 原子替换 `run.json`，写入新的 `last_completed_step`、`resume_step`、`state`、`last_event_seq`。

崩溃恢复：

1. 启动时扫描 `state=RUNNING` 的 run；
2. 读 `run.json`，重放 `seq > last_event_seq` 的事件；
3. 若 events 已有 `step.finished` 但 checkpoint 落后，推进 checkpoint；
4. 删除没有对应 `artifact.committed` 事件的临时文件；
5. 非幂等步骤只有 `write_verify`：按 `09` intent/receipt 与 output 哈希对账后再继续；
6. 每个 run 目录一把文件锁，Web 与 worker 不能同时推进同一个 run。

`run.json` 是 checkpoint，不是第二事实源；UI 的历史来自 events，不读 `state_history`。

### 5.5 失败、重试、预算

| 错误 | 可重试 | 去向 |
|---|---|---|
| `E_BRIDGE_TIMEOUT` | 是（3 次） | 同 Step 重试 |
| `E_SOURCE_OPEN` / `E_SOURCE_UNSTABLE` | 否 | FAILED / NEEDS_HUMAN |
| `E_SCHEMA` / `E_RULE_UNAPPROVED` | 否 | NEEDS_HUMAN 或 FAILED |
| `E_NO_HARD_OK` / `E_SOFT_BLOCKED` | 否 | NEEDS_HUMAN |
| `E_APPLY_PARTIAL` / `E_SAVE_COPY_FAILED` | 否 | FAILED，清理 staging/output |
| `E_WRITE_VERIFY` | 否 | 回滚本次 output → FAILED |
| `E_UNKNOWN_WRITE_STATE` | 否 | NEEDS_HUMAN + reconcile |
| `E_GATE_CRASH` | 否 | 该候选 invalid；全部无效 → NEEDS_HUMAN |
| `E_BUDGET_EXCEEDED` | 否 | NEEDS_HUMAN |

- 重试只在 Step 内部，默认 `max_attempts=1`；仅瞬时错误重试。
- LLM 提案允许 1 次 schema 修复重试，仍失败走确定性降级（静态模板/人工补录）；不允许无限对话。
- 预算：`max_wall_seconds`、`max_llm_calls`、`max_candidates`、`max_repair_iters`、`max_trials_per_rule`，每次外部调用前扣减。
- 除 `write_verify` 外，所有 Step 都是“读旧产物 → 写新产物”，失败只是没有新提交，天然无需回滚。

### 5.6 Bridge 与命令白名单

**BridgeSupervisor 状态**（adapter 内部，不是 RunState）：

```text
STOPPED → STARTING_AD → STARTING_LOOP → HANDSHAKING → READY
异常 → DEGRADED / RESTARTING / QUARANTINED；写事务中 → BUSY
```

- `auto_shutdown_ms=0`；supervisor 每 20 秒 ping 刷新 `PumpLastActivityMs`；应用层 `application.ping` 3 秒一次。
- 健康三路：AD 进程；ping 返回 `script_version`、`loop_workspace_dir`、`stale_units`；`last_fault.json`、`progress_<id>.json`、`bridge_trace.log` 的 mtime。
- 握手校验版本与 workspace；写事务中禁止重启；`allow_cold_start=false`，AD 由用户手动打开。
- v1 单 worker + 写租约；MCP 不启动，避免两个会话抢同一 AD 脚本引擎。

允许命令：`application.ping`、`application.get_open_documents`、`project.get_open_projects`、`project.get_documents`、`pcb.get_layout_model`、`pcb.run_drc`、`pcb.file_info`、`project.open`、`pcb.focus_board`、`application.set_active_document`、`pcb.batch_move_components`、`pcb.save_copy_as`、`project.close(save=false)`。

禁止：`app.save_all`、`project.save`、`obj.run_process`、`pcb.delete_*`、`pcb.place_*`、`pcb.route_*`、`pcb.repour_polygons`、所有 UI 自动化、`app.detach` / `application.stop_server`（仅 supervisor 优雅停机可用）。

### 5.7 路径守卫

```python
def assert_writable(path: Path, *, role: str) -> None:
    p = canonical(path)
    if _is_unc_or_device(p):
        raise PathNotAllowed(...)
    for root in cfg.source_roots_deny:
        if _is_under(p, canonical(root)):
            raise PathNotAllowed(...)          # deny 优先
    if role == "web" and not _is_under(p, run_dir / "request.json"):
        raise PathNotAllowed(...)
    if role == "worker" and not any(
        _is_under(p, canonical(root)) for root in cfg.allowed_write_roots
    ):
        raise PathNotAllowed(...)
    if p.exists() and _is_link_or_junction(p):
        raise PathNotAllowed(...)
    if p.exists() and _hardlink_to_source(p):
        raise PathNotAllowed(...)
```

- worker 的 `allowed_write_roots`：`work/runs`、`work/rulesets`。
- `source_roots_deny` 包含 `work/runs/p0_wisp6`、`work/runs/p0_buck`、`D:/NeroZe/AD2611-PCB-Layout-Lab` 等源工程目录；deny 优先于 allow。
- Web 角色只允许新建 `<run_id>/request.json`，其余 run 文件只读；不得写 `work/rulesets`。

### 5.8 写回链：无预复制，唯一落盘写是 save_copy_as

```text
1. prepare：源清单哈希；复制源 → stage；逐文件哈希；打开 stage 只读，生成 01；close save=false
2. candidates：place_job 子进程产出候选；不打开 AD 写
3. validate_repair：独立 Gate；修复；选出 07
4. plan_writeback：08 计划；记录 output 目标、source/stage 哈希、plan_hash；等待人工审批
5. write_verify：
   a. 重新校验 08 的哈希、审批绑定、output 最终路径不存在（output_absent_before=true）
   b. 写 09a intent
   c. 打开 stage；stage 内存分块 batch_move_components
   d. 读回 stage，逐点校验
   e. pcb.save_copy_as → output/.staging/<id>/<board>.PcbDoc
   f. 校验 staging 哈希；原子 rename 到 output/project/
   g. project.close(stage, save=false)；复核 stage 哈希未变
   h. 打开 output；从磁盘重读 → 10；对 output 跑 DRC → 11
   i. 对 output 跑后置独立 Gate，写 10
   j. 关闭 output；恢复焦点；写 09b/09c receipt
6. report：12
```

写回五不变式：

| # | 不变式 | 证明 |
|---|---|---|
| I1 | 源工程从不进入 AD 打开文档集合 | 审计 open/focus/save/close；源只被复制和哈希 |
| I2 | stage 从不保存 | `close save=false`；关闭后 stage 哈希等于复制时哈希 |
| I3 | EDA 侧唯一落盘写是 `save_copy_as` 到 staging；executor 只做校验后的原子 rename | 命令白名单 + 路径守卫 + staging 哈希 |
| I4 | 单写者 | worker 进程锁 + `leases` 写租约 |
| I5 | 源清单前后哈希一致 | prepare/commit 各算一次；变化则 `SOURCE_CHANGED_EXTERNALLY` |

**删除原设计中的“先复制 stage 到 output，再 save_copy_as”**：save 失败时 output 已有一份副本，看起来像成功。现在 save 目标只能是 staging；staging 校验通过后才 rename，失败时 output 最终路径不存在。

intent：

```json
{
  "schema": "ai_pcb.write_intent/v1",
  "idempotency_key": "20261125-103012-buck-7f3a2c:write:1",
  "mode": "save_copy_as",
  "source_manifest_sha256": "...",
  "stage_board_sha256_before": "...",
  "output_final": ".../output/project/Buck.PcbDoc",
  "output_staging": ".../output/.staging/20261125-103012-buck-7f3a2c/Buck.PcbDoc",
  "output_absent_before": true,
  "plan_sha256": "...",
  "rules_sha256": "..."
}
```

receipt：

```json
{
  "schema": "ai_pcb.save_receipt/v1",
  "idempotency_key": "...",
  "status": "applied",
  "chunks": [{"index": 0, "requested": 5, "moves_applied": 5, "failed": 0, "duration_ms": 812}],
  "moved": 5,
  "failed": 0,
  "expected": 5,
  "staging_sha256": "...",
  "final_sha256": "...",
  "renamed": true
}
```

对账规则：

| 现场 | 动作 |
|---|---|
| 有 receipt 且 `renamed=true` | 直接进入重读/后置 Gate |
| 无 output 最终路径，且无 staging | 安全重跑 |
| staging 存在、无 receipt | 删除 staging，重跑 |
| output 最终路径存在且哈希等于 receipt | adopt，继续 verify |
| 其他 | quarantine，人工对账 |

故障注入必须覆盖：save 中杀 AD、杀轮询脚本、`save_copy_as` 超时、staging 损坏、output 被外部修改、磁盘满、焦点被抢、源被外部修改。

---

## 6. Web 控制台（v1 只做观察与启动）

### 6.1 两个页面

| 路径 | 用途 |
|---|---|
| `/runs` | 运行列表 + 新建运行表单（HTML POST） |
| `/runs/{run_id}` | 工作台：概览、规则、候选（内嵌 SVG）、日志 |

- 服务端渲染，Jinja2 + 原生 JS；无 npm、React/Vue、Tailwind、图表库、WebSocket、SSE。
- 状态刷新用 3 秒轮询；URL 就是状态，刷新不丢。
- 候选 SVG 由 `reports/preview_svg.py` 从 `BoardSnapshot + Placement` 生成，内嵌页面；不调用 AD。
- 候选全屏页、拖拽编辑、地图式预览：P3。

### 6.2 4 个只读 API

```text
GET /api/v1/runs
GET /api/v1/runs/{run_id}
GET /api/v1/runs/{run_id}/events?after=<seq>
GET /api/v1/runs/{run_id}/artifacts/{path}   # 白名单路径
```

- 新建运行由 `/runs` 的 HTML 表单处理：Web 只写 `work/runs/<run_id>/request.json`，worker 接管后 Web 只读。
- 不提供 `/api/v1/writeback/*`、`/api/v1/bridge/*`、候选 approve API；这些在 v1 走 CLI。
- 路径白名单只允许 `artifacts/`、`candidates/` 下的 JSON/SVG/文本；拒绝任意文件读取和 `..`。

### 6.3 审批身份

- v1 CLI：`reviewer = getpass.getuser()`；审批事件记录 Windows 用户名。
- P2 Web 审批：服务端同样从 `getpass.getuser()` 推导；请求体出现 `reviewer` → 400 `IDENTITY_NOT_ACCEPTED`。
- `expected_hash` 不匹配 → 409 `STALE_SUBJECT`。
- 审批写走 worker 队列/事件，不直接写 canonical ledger；Web 只读展示。
- 本地单用户不做登录；团队阶段接反向代理 SSO，审批事件格式不变。

### 6.4 页面必须区分三条线

```text
硬门禁 PASS：不变量 6 / 硬规则 1
软规则 2/4
DRC 信息：基线 37 / 候选 37 / 新增 0（不参与硬门禁）
```

- 规则行固定列：规则 ID、类型、严重度、审批状态、当前/阈值、结果、阻挡件、操作。
- 结果用文字标签 + 四色：`PASS` / `FAIL` / `BLOCKED` / `NOT EVALUATED`，不能只靠颜色。
- 抽屉三段：来源（文档/页码/quote/审批事件）、评估（当前值/阈值/尝试次数）、阻挡（类型/层/A/B/gap/required/坐标）。
- `blocked_by` 必须来自真实几何证据；没有记录时显示“未记录明确阻挡件，仅有 N 次尝试”，不编造。
- 页脚固定：“技术演示，未经工程验收；DRC 仅信息性。”

---

## 7. 验收与质量门

### 7.1 Buck golden：重新计数，不混淆 hard/soft/DRC

原 `effective_rules.json` 的 5 条 hard 去向：

| 原规则 | 新归属 |
|---|---|
| `R_DEMO_ANCHORS` | `I_ANCHOR`（目标 = source_locked ∪ pinned_refs） |
| `R_DEMO_TOP_ONLY` | 保留为 hard 规则，`kind=side` |
| `R_DEMO_PRESERVE_NETS` | `I_NETLIST` |
| `R_DEMO_INSIDE_OUTLINE` | `I_INSIDE_OUTLINE` |
| `R_DEMO_NO_NEW_DRC` | `11_drc_advisory.json`（demo_gate，不参与 verdict） |

因此 Buck 新基线是：**不变量 6/6，hard 规则 1/1，soft 2/4，DRC advisory new=0**。
批评第 2 条建议“4 hard + 1 advisory”，第 5 条进一步指出其中 3 条其实是 invariant；这里采用更严格的去重方案，最终是 1 hard + 6 invariants + 1 advisory。

固定 fixture：

- `tests/fixtures/boards/buck.snapshot.json`：从真实 PcbDoc 读一次后固化。
- `tests/fixtures/boards/buck.governance.json`：region 审批状态、board_rules。
- `tests/fixtures/evidence/buck.passages.json`：4 条 TI passage。
- `tests/fixtures/rules/buck.demo.json`：1 hard + 4 soft，补齐 `measure: center_to_center`。
- `tests/fixtures/legacy/rule_loop_report.json`：现有报告，作为 legacy 对照。

断言：

```python
def test_compile_buck_demo():
    r = compile_buck(...)
    assert len(r.effective.hard) == 1
    assert r.effective.hard[0].semantic.kind == "side"
    assert len(r.effective.soft) == 4
    assert len(r.review_queue) == 0
    assert r.effective.hard[0].governance.governance == "approved_demo"

def test_gate_baseline():
    report = run_gate(board, baseline_placement, rules, baseline=board, policy=DELTA)
    assert report.verdict == "pass"
    assert report.summary.invariants.all_pass
    assert report.summary.hard.not_evaluated == 0

def test_candidate_matches_legacy():
    report = run_gate(board, candidate, rules, baseline=board, policy=DELTA)
    assert report.verdict == "pass"
    assert report.summary.invariants.pass_ == 6
    assert report.summary.hard.pass_ == 1
    assert report.summary.soft.pass_ == 2
    cin = find(report.soft, "R_DEMO_CIN_VIN")
    assert cin.measurements[0].value_nm == 5_780_000
    assert set(cin.blocked_by) == {"L1", "R2"}
    fb = find(report.soft, "R_DEMO_FB_VFB")
    assert fb.measurements[0].value_nm == 5_640_000
```

HPWL：legacy `rule_loop_report.json` 的 `hpwl_after=2693.0`（eda_agent 原生单位，mil）。新建 `SelectionScore` 后要求：

```text
hpwl_mil <= 2693.0
hpwl_mil <= baseline_hpwl_mil
```

### 7.2 SelectionScore（显式排序键）

```python
@dataclass(frozen=True)
class SelectionScore:
    hard_ok: bool                 # Gate verdict == pass
    soft_pass: int
    max_soft_violation_norm: int  # max(measured/limit - 1)，按 1e-4 取整
    hpwl_mil: float
    max_displacement_nm: int
    runtime_ms: int
    candidate_id: str

sort_key = (
    not hard_ok,
    -soft_pass,
    max_soft_violation_norm,
    hpwl_mil,
    max_displacement_nm,
    runtime_ms,
    candidate_id,
)
```

- 候选集必须包含 `cand_baseline`（零位移），保证基线永远有合法候选。
- `hpwl_mil > baseline_hpwl_mil` 的候选不选，除非所有候选都更差（则选 baseline）。
- `select_final` 不写“字典序”，只写上面的排序键。

### 7.3 知识检索与规则提取

`02_knowledge_passages.json` 必须包含：

```json
{
  "schema": "ai_pcb.knowledge_passages/1.0",
  "retrieval_manifest": {
    "query": "buck input capacitor VIN placement",
    "corpus_sha256": "sha256:...",
    "top_k": 10,
    "method": "keyword",
    "model": null,
    "hits": [{"passage_id": "p_3f2a9c1d", "score": 3.2, "rank": 1}]
  },
  "passages": []
}
```

- 20 条标注 passage，人工标注期望规则。
- hard 规则的引用/数字校验 100% 通过；召回率 ≥ 0.8；precision 进评审但不设硬门槛。
- `hit@3 ≥ 0.9`。
- 运行 `tests/acceptance/test_rule_extraction.py`；LLM 关闭时用录制的响应 fixture 验证 schema/quote/number 校验。

### 7.4 预览保真

`reports/preview_svg.py` 只读 `BoardSnapshot + Placement`，不 import `eda_agent`。

对比测试：

- 组件数量一致；
- pad 数量一致；
- board bounding box 与组件 bounding box 误差 ≤ 1 µm；
- 与 `eda_agent.render.pcb_svg` / `design.live.snapshot` 的 oracle 对比作为 nightly/manual 测试，不要求 CI 有 AD。

### 7.5 质量门清单

| 类别 | 测试 | 门槛 |
|---|---|---|
| 纯度 | `test_purity.py` AST | domain 只 stdlib；eda_agent 只在 adapter；web/gate 不 import |
| 确定性 | 编译两次、规则乱序 | `effective_hash` 相同 |
| Gate | 同输入重放 | `report_hash` 相同；篡改 payload 被发现 |
| 规则不变量 | 每条输入规则恰好一个 decision | 100% |
| 证据 | quote/number 校验 | hard 100%；VLM 不能支撑 hard |
| 审批 | 改数值旧审批失效 | `semantic_hash` 变化即过期 |
| 写回 | 源哈希、stage 哈希、output 不存在 | I1–I5 全部断言 |
| 故障 | 10 个场景 | 可恢复或可对账，无静默成功 |
| Web | TestClient | 200/400/404/409；不 import eda_agent |
| 性能 | wisp6 Gate | < 60 秒 |

### 7.6 wisp6 验收

- 65 器件、4 层、63 网络；11 个 region 人工标 `keepout/board_cutout/copper/mechanical` + `review_status=approved`，工具不猜。
- 基线 `I_PAD_CLEARANCE` 先 delta；基线违规清零并审批后切 absolute。
- 候选修复循环调优；Gate < 60 秒。
- 10 个故障场景全部演练：写中杀 AD、杀轮询脚本、save 超时、staging 损坏、output 损坏、磁盘满、焦点被抢、源被外部修改、workspace 冲突、审批过期。
- DRC 与 Gate 差异逐条可解释；不一致进 `review_required`，不自动 promote。

---

## 8. v1 做与不做

| 能力 | v1.0 Buck 6 | v1.1 wisp6 65 | P3 可选 |
|---|---|---|---|
| 核心域/规则/检查/artifacts | 实现 | 复用 | 复用 |
| 知识 | JSON 语料 + 文件规则库 | 同左 + 更多 passage | RAGFlow/向量库 |
| 规则提案 | 静态 fixture；可选单次 LLM 调用 | 同左 | 多模型/多策略 |
| 编排 | 8 Step 顺序 + events WAL | 同左 | LangGraph Driver |
| 执行 | 写回闭环 + 故障注入 | 校准 + 性能 | 多 AD 工作站队列 |
| Web | 2 页 + 4 只读 API + 轮询 | 同左 | Web 审批、SSE、全屏候选页 |
| 审批 | CLI | CLI | Web + SSO |
| 存储 | 文件 + JSONL | 同左 | SQLite/Postgres |
| DRC | advisory + 可选写回策略 | 同左 | 策略化门禁 |
| Neo4j/VLM/MCP | 不做 | 不做 | 按触发条件评估 |

**v1 明确不做**：

- 不做 SPA、React/Vue/Next/Vite/npm。
- 不做客户端路由、拖拽布局编辑、WebSocket/SSE。
- 不做登录/角色系统、Web 审批、候选全屏页。
- 不做自治多 Agent、LLM 输出坐标、LLM 自动写规则。
- 不做 Neo4j、VLM、RAGFlow 运行时依赖、向量库。
- 不把 domain 做成 Pydantic 模型；domain 是 frozen dataclass，Pydantic 只在规则边界。
- 不在规则文件里放可执行代码或动态 import。
- 不把 DRC 当硬门禁；写回策略可以额外要求它。
- 不覆盖源工程；`promote` 只是复制 output 到用户指定目录。

**P3 触发条件**：

| 能力 | 触发条件 |
|---|---|
| LangGraph | 需要 fan-out/fan-in、跨进程恢复、动态重规划 |
| RAGFlow/向量库 | passage > 500、关键词召回不足、团队已有服务 |
| Neo4j | 规则 > 500、跨文档修订影响分析 |
| VLM | 图多、人工整理成本高；必须本地/内网；只能 advisory |
| SQLite/Postgres | 多用户、并发 run、规则 > 50 |
| SSO/RBAC | 团队内网多用户 |
| MCP 产品面 | 外部 Agent 需要触发 run；仍不能直接写 AD |
| Web 审批/SSE | CLI 审批成为瓶颈 |

---

## 9. 一页执行清单

> 角色：**你** = 工程决策、规则数值审批、写回审批、AD 现场；**Claude** = 代码、测试、故障演练脚本；双方共同验收。

| 阶段 | 主要产出 | 验收门槛 | 谁做 |
|---|---|---|---|
| **M0 迁移与基线冻结**（1–2 天） | 旧 `src/ai_pcb` 归档到 `legacy/ai_pcb_v0/`；`pyproject.toml` editable install；Buck snapshot/governance/passages/legacy report fixture；`test_purity.py` 骨架 | fixture 哈希固定；旧代码不被新包 import；`pip install -e .` 后 `python -I -m ai_pcb.checks.gate_runner --help` 可运行 | Claude 实现；你确认旧代码处置与 Buck 基线 |
| **M1 核心域 + 编译器 + Gate 离线**（4–5 天） | `domain/`、`geometry/`、`rules/`、`checks/`、`artifacts/`；`04_compile.json`；gate runner；Buck golden | 编译出 1 hard + 4 soft、review=0；Gate 基线 6/6 invariants；候选 1/1 hard、2/4 soft、CIN 5.78mm blocked_by={L1,R2}、FB 5.64mm；HPWL ≤ 2693.0；同输入 hash 一致 | Claude 实现；你审批 5mm/8mm demo 数值 |
| **M2 Bridge + 写回闭环**（5–7 天） | `adapters/eda_agent/`；8 Step；events WAL；stage/output；intent/receipt；故障注入 | 源哈希前后不变；stage close 后哈希不变；只写 output；output 可重开；回读一致；save 失败无残留；未知状态可对账；审批过期 409/退码 3 | Claude 实现；你现场操作 AD、审批写回 |
| **M3 Web 只读 + CLI 审批**（3–4 天） | 2 个页面、4 个只读 API、3 秒轮询、SVG 预览；`pcbctl approve rules/writeback` | 200/400/404/409 测试；web 不 import eda_agent；页面三条线分开；`reviewer` 不能由请求体指定 | Claude 实现；你验收页面与 CLI |
| **M4 wisp6 65 器件**（5–7 天） | region 人工标注；绝对 clearance 校准；修复循环；性能；10 个故障演练 | Gate < 60s；11 个 region 全部审批；基线 0 违规后切 absolute；10 个故障可恢复/可对账；DRC 与 Gate 差异逐条解释 | Claude 实现；你标注 region、校准数值、签收 |
| **M5 P3 评估**（按需） | 一页 ADR + 触发条件评估 | 只有触发条件满足才启动；不预先写 stub | 你决策；Claude 评估 |

**建议顺序**：M0 → M1（离线 Gate 先复现 Buck）→ M2（写回闭环）→ M3（Web 只读）→ M4（wisp6）。不要先做 Web 再做 Gate；Gate 是验收核心，页面只是观察窗。

**第一周只做三件事**：

1. 冻结 Buck 基线 fixture；
2. 写 domain + purity 测试；
3. 离线复现 1 hard + 4 soft + 6 invariants + 5.78/5.64mm + L1/R2 blockers + HPWL 2693.0。

复现不出来，不接 AD、不写 Web。

---

本设计未修改任何文件。