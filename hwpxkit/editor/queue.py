"""부탁 대기 목록 (JSONL, 한 줄에 부탁 하나). 범위는 남길 때의 문단 번호와 글을 함께 적는다."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class AskQueue:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    @classmethod
    def for_copy(cls, copy: Path) -> "AskQueue":
        copy = Path(copy)
        return cls(copy.with_name(f"{copy.stem}.부탁.jsonl"))

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _save(self, asks: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in asks), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, ask_id: str) -> dict:
        for a in self.all():
            if a["id"] == ask_id:
                return a
        raise KeyError(ask_id)

    def add(self, version: int, start: int, end: int, texts: list[str], text: str) -> dict:
        with self.lock:
            asks = self.all()
            ask = {"id": f"a{len(asks) + 1}", "version": version, "start": start, "end": end, "texts": texts,
                   "text": text, "status": "pending", "message": "", "time": time.strftime("%Y-%m-%d %H:%M")}
            self._save(asks + [ask])
            return ask

    def set(self, ask_id: str, status: str, message: str = "") -> dict:
        with self.lock:
            asks = self.all()
            for a in asks:
                if a["id"] == ask_id:
                    a["status"], a["message"] = status, message
                    self._save(asks)
                    return a
        raise KeyError(ask_id)


def locate(current: list[str], ask: dict) -> tuple[int, int] | None:
    """부탁 범위를 지금 문서에서 찾는다: 같은 자리 → 밀린 자리(한 곳일 때만) → 못 찾음(None)."""
    texts, start, end = ask["texts"], ask["start"], ask["end"]
    n = len(texts)
    if current[start:end] == texts:
        return start, end
    hits = [k for k in range(len(current) - n + 1) if current[k:k + n] == texts]
    return (hits[0], hits[0] + n) if len(hits) == 1 else None
