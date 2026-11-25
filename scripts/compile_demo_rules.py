"""把 demo 规则编译成 effective_rules.json。

规则分三类：
  hard_rules        approved / approved_demo，且参数完整
  soft_rules        demo_only / draft，但仍可被 Critic 检查
  review_required   缺来源、缺数值、或未批准
"""
import argparse
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="编译 demo 规则")
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = load(args.rules)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    hard, soft, review, provenance, conflicts = [], [], [], [], []

    for rule in src.get("hard", []) + src.get("soft", []):
        rule_id = rule.get("rule_id", "(missing)")
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
        provenance.append({
            "rule_id": rule_id,
            "source": source,
            "status": status,
        })

    effective = {
        "board": src.get("board"),
        "note": src.get("note", ""),
        "parts": src.get("movable", []),
        "fixed": src.get("anchors", []),
        "engine": src.get("engine", {}),
        "hard_rules": hard,
        "soft_rules": soft,
        "review_required": review,
        "conflicts": conflicts,
        "provenance": provenance,
    }

    for name, data in (
        ("effective_rules.json", effective),
        ("conflicts.json", conflicts),
        ("provenance.json", provenance),
    ):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"parts={len(effective['parts'])} fixed={len(effective['fixed'])} "
          f"hard={len(hard)} soft={len(soft)} review_required={len(review)} conflicts={len(conflicts)}")
    print("soft rules:", [r["rule_id"] for r in soft])
    if review:
        print("review_required:", [r.get("rule_id") for r in review])


if __name__ == "__main__":
    main()
