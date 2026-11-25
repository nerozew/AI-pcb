"""把 knowledge.json + rules.json 编译成生效规则。

输出：
  effective_rules.json  parts / fixed / engine 参数 / hard_rules / soft_rules / review_required
  conflicts.json        规则冲突（v1 先留空，冲突检测后续加）
  provenance.json       每条规则的来源

原则：没有 source_ref、或数值为 null 的规则进 review_required，绝不进 hard_rules。
"""
import argparse
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="编译 knowledge.json + rules.json")
    ap.add_argument("--knowledge", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fixed", default="", help="逗号分隔的锚点器件，如 IC1,J1,J2")
    args = ap.parse_args()

    k, r = load(args.knowledge), load(args.rules)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    groups = r.get("move_group", {})
    parts = groups.get("six") or groups.get("four") or []
    fixed = [x.strip() for x in args.fixed.split(",") if x.strip()]

    hard, soft, review, provenance = [], [], [], []

    # L1/L3：板子/单板规则，来自 rules.json
    for key, value in r.items():
        if key == "move_group":
            continue
        rule = {
            "rule_id": f"R_{key.upper()}",
            "kind": key,
            "severity": "hard",
            "params": {key: value},
            "source_ref": {"origin": "rules.json"},
            "review_status": "approved",
            "approved_by": None,
        }
        hard.append(rule)
        provenance.append({"rule_id": rule["rule_id"], "source": "rules.json", "field": key})

    # L2：芯片/电路规则，来自 knowledge.json
    doc = k.get("source", {})
    for req in k.get("layout_requirements", []):
        for pair in req.get("pairs", []):
            rule = {
                "rule_id": f"R_{req['id']}_{pair.get('left')}_{pair.get('right')}",
                "kind": "proximity",
                "severity": "hard",
                "targets": pair,
                "params": {"max_distance_mm": None},
                "source_ref": {
                    "document": doc.get("document_id"),
                    "revision": doc.get("revision"),
                    "page": req.get("page") or req.get("layout_fig_page"),
                    "origin": "datasheet",
                },
                "review_status": "draft",
                "approved_by": None,
            }
            review.append(rule)
            provenance.append({
                "rule_id": rule["rule_id"],
                "source": doc.get("url"),
                "page": rule["source_ref"]["page"],
            })

    effective = {
        "board": k.get("part_id"),
        "parts": parts,
        "fixed": fixed,
        "engine": {"strategy": "analytic", "grid_mm": None, "decap_pull": 0.0, "spread_density": 0.0},
        "hard_rules": hard,
        "soft_rules": soft,
        "review_required": review,
        "conflicts": [],
    }

    for name, data in (
        ("effective_rules.json", effective),
        ("conflicts.json", effective["conflicts"]),
        ("provenance.json", provenance),
    ):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"parts={len(parts)} fixed={len(fixed)} hard={len(hard)} "
          f"review_required={len(review)} conflicts={len(effective['conflicts'])}")
    print("review_required:", [x["rule_id"] for x in review])


if __name__ == "__main__":
    main()
