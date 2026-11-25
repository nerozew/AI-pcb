"""把规则 Agent 的输出编译成生效规则。纯函数，不碰 AD/文件系统。"""


def compile_rules(src: dict) -> dict:
    hard, soft, review, provenance, conflicts = [], [], [], [], []

    for rule in src.get("hard", []) + src.get("soft", []):
        status = rule.get("review_status", "draft")
        params = rule.get("params", {})
        source = rule.get("source_ref") or {}
        missing = []
        if not source:
            missing.append("source_ref")
        if rule.get("kind") == "pad_distance" and params.get("max_distance_mm") is None:
            missing.append("max_distance_mm")
        if missing:
            review.append({**rule, "missing": missing})
            continue
        if status in ("approved", "approved_demo"):
            hard.append(rule)
        elif status in ("demo_only", "draft"):
            soft.append(rule)
        else:
            review.append({**rule, "missing": ["review_status"]})
        provenance.append({"rule_id": rule.get("rule_id"), "source": source, "status": status})

    return {
        "board": src.get("board"),
        "note": src.get("note", ""),
        "agent": src.get("agent", ""),
        "passages_used": src.get("passages_used", []),
        "parts": src.get("movable", []),
        "fixed": src.get("anchors", []),
        "engine": src.get("engine", {}),
        "hard_rules": hard,
        "soft_rules": soft,
        "review_required": review,
        "conflicts": conflicts,
        "provenance": provenance,
    }
