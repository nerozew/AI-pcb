# ADR 0002：选器件以 AD 框选为主

- 日期：2026-11-25
- 状态：已接受（用户选择）
- 背景：网页需要知道"哪些器件可动"。`eda_agent` 提供 `pcb_get_selected_objects`，可以读 AD 当前选择。
- 决策：主路径 = 用户在 AD26 里框选器件 → 网页新建运行时选择 `selection_mode=ad_current` → worker 在 `prepare` 步读选择，写 `01_selection.json`。
- 备选（P2）：网页勾选、配置默认（锁定连接器/结构件，其余全动）。

## 约束

- 目标板必须是 AD 当前焦点；读板用 `expect_file`，切板会 `WrongBoard`，不猜。
- Web 不 import `eda_agent`；只写 `request.json`，worker 独占 bridge。
- 选择为空 → `NEEDS_HUMAN, waiting_for=selection`；页面提示"请在 AD 里选中器件"。
- 选择里非器件对象（走线/过孔/文字）忽略；只取有 `SourceDesignator` 的元件。
- 锚点 = `source_locked ∪ 连接器/结构件`；用户可在配置覆盖。
- 运行期间切板 → 失败并提示，不自动换板重读。

## 使用流程

```text
① AD26 打开目标 PcbDoc，保持激活
② 浏览器打开 /runs；首页显示桥在线/离线、当前板
③ AD 里框选可动器件
④ 网页新建运行：selection_mode=ad_current，选策略
⑤ worker 捕获选择，页面显示"可动 N / 锁定 M"
⑥ 运行 8 步；页面 3 秒轮询进度
⑦ 候选 + 规则表（PASS/FAIL/BLOCKED + 阻挡件）
⑧ 选一个候选，请求写回
⑨ CLI 审批：pcbctl approve writeback <run_id>
⑩ 写 output 副本 → 回读 → 后置 Gate → DRC advisory
⑪ 用户在 AD 里打开 output 副本查看；原工程不变
```

## 影响

- `/runs` 新建表单增加"可动器件来源：AD 当前选择 / 配置默认"。
- 运行详情显示 captured selection 与锚点来源。
- 不新增桥 API；复用 `pcb_get_selected_objects`。
- P2 再补网页勾选；P3 再评估模板保存。
