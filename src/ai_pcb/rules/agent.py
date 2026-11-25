"""规则 Agent 接口。v1 用静态 JSON 模拟 Agent 输出；LLM 版本只预留。"""
import json
from pathlib import Path
from typing import Protocol

from ai_pcb.knowledge.base import Passage


class RuleAgent(Protocol):
    def propose(self, passages: list[Passage], board: str = "") -> dict:
        ...


class StaticRuleAgent:
    """读取已整理好的规则 JSON，模拟规则 Agent 的输出。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def propose(self, passages: list[Passage], board: str = "") -> dict:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["agent"] = "static-json"
        data["passages_used"] = [
            {"document_id": p.document_id, "page": p.page, "source": p.source}
            for p in passages
        ]
        return data


class LlmRuleAgent:
    """预留：用内网 LLM 从 passages 生成 draft 规则。"""

    def propose(self, passages: list[Passage], board: str = "") -> dict:
        raise NotImplementedError("LLM rule agent reserved")
