r"""链路验证：passages → RuleAgent → Compiler → eda_agent → Critic → chain_report。

用 lab 的 venv 跑，因为它有 eda_agent：
  & "D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119\.venv\Scripts\python.exe" "D:\Code_all\AI-pcb\scripts\run_chain.py"
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Code_all\AI-pcb")
LAB = Path(r"D:\NeroZe\AD2611-PCB-Layout-Lab\Buck-C2-20261119")
VENV_PY = LAB / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / "work" / "runs" / "p0_buck"
CHAIN_OUT = ROOT / "work" / "runs" / "chain"
sys.path.insert(0, str(ROOT / "src"))

from ai_pcb.knowledge.base import JsonKnowledgeSource  # noqa: E402
from ai_pcb.rules.agent import StaticRuleAgent  # noqa: E402
from ai_pcb.rules.compiler import compile_rules  # noqa: E402


def main() -> None:
    CHAIN_OUT.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    source = JsonKnowledgeSource(ROOT / "configs" / "buck" / "passages.demo.json")
    passages = source.search("TPS561208 layout")
    print(f"[1/5] knowledge: {len(passages)} passages")

    agent = StaticRuleAgent(ROOT / "configs" / "buck" / "rules.demo.json")
    proposed = agent.propose(passages, board="buck")
    print(f"[2/5] rule agent: {len(proposed.get('hard', []))} hard + "
          f"{len(proposed.get('soft', []))} soft proposals")

    effective = compile_rules(proposed)
    (OUT / "effective_rules.json").write_text(
        json.dumps(effective, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[3/5] compiler: parts={len(effective['parts'])} "
          f"hard={len(effective['hard_rules'])} soft={len(effective['soft_rules'])} "
          f"review={len(effective['review_required'])} conflicts={len(effective['conflicts'])}")

    loop = subprocess.run(
        [str(VENV_PY), str(ROOT / "scripts" / "run_rule_loop.py")],
        text=True, capture_output=True,
    )
    print(loop.stdout)
    if loop.returncode != 0:
        print(loop.stderr, file=sys.stderr)
        raise SystemExit(loop.returncode)

    report = json.loads((OUT / "rule_loop_report.json").read_text(encoding="utf-8"))
    best = report["best"]
    chain = {
        "stages": {
            "knowledge": {"passages": len(passages)},
            "rule_agent": {"hard": len(proposed.get("hard", [])),
                           "soft": len(proposed.get("soft", []))},
            "compiler": {"parts": len(effective["parts"]),
                         "hard": len(effective["hard_rules"]),
                         "soft": len(effective["soft_rules"]),
                         "review_required": len(effective["review_required"]),
                         "conflicts": len(effective["conflicts"])},
            "placement": {"candidates": len(report["candidates"])},
            "critic": {"best": best["config"], "hard_ok": best["hard_ok"],
                       "soft_pass": best["soft_pass"], "soft_total": best["soft_total"],
                       "hpwl": best["hpwl_after"]},
        },
        "pass": best["hard_ok"] and best["soft_pass"] == best["soft_total"],
    }
    (CHAIN_OUT / "chain_report.json").write_text(
        json.dumps(chain, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[4/5] chain report:", json.dumps(chain["stages"], ensure_ascii=False))
    print("[5/5]", "PASS" if chain["pass"] else "NEEDS WORK")


if __name__ == "__main__":
    main()
