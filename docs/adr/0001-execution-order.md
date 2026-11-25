# ADR 0001：执行顺序调整为 wisp6-first

- 日期：2026-11-25
- 状态：已接受（用户选择）
- 背景：架构定稿建议 Buck 6 作为第一块板，用于 Gate 基线；用户选择第一周直接做 wisp6 65。
- 决策：M0/M1 以 wisp6 为主板；Buck 6 保留为 Gate 单元测试/校准，不作为主 Demo。
- 影响：
  - M0 fixture 以 wisp6 snapshot/governance 为主，Buck 作为最小 golden。
  - M1 Gate 先在 wisp6 上建立基线；Buck 用于验证 Gate 的已知正确性。
  - 若 wisp6 的 region/clearance 校准阻塞，回退到 Buck 先完成 Gate，再回 wisp6。
- 风险：wisp6 没有已校准的已知正确布局；Gate 必须用合成故障 + Buck 单元测试自证。
