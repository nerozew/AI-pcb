"""知识库接口。v1 只用 JSON；RAGFlow 和数据库只预留，不实现。"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Passage:
    text: str
    document_id: str = ""
    page: int | None = None
    asset_id: str = ""
    score: float = 0.0
    source: str = ""


class KnowledgeSource(Protocol):
    def search(self, query: str, top_k: int = 10) -> list[Passage]:
        ...


class JsonKnowledgeSource:
    """从本地 JSON 读取 passages；用于链路验证和离线测试。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def search(self, query: str, top_k: int = 10) -> list[Passage]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Passage(**p) for p in data.get("passages", [])][:top_k]


class RagflowSource:
    """预留：RAGFlow 检索适配器。"""

    def __init__(self, base_url: str, api_key: str, dataset_ids: list[str]):
        self.base_url = base_url
        self.api_key = api_key
        self.dataset_ids = dataset_ids

    def search(self, query: str, top_k: int = 10) -> list[Passage]:
        raise NotImplementedError("RAGFlow adapter reserved; see scripts/fetch_ragflow.py")


class DbSource:
    """预留：数据库规则/审批状态适配器。"""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def search(self, query: str, top_k: int = 10) -> list[Passage]:
        raise NotImplementedError("DB adapter reserved")
