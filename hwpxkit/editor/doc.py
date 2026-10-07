"""편집 화면의 문서 모델. 사본에 쓰는 곳은 이 클래스 하나이고, 쓰기는 잠금으로 차례대로 한다."""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from lxml import etree

from ..body import own_text
from ..header import Header
from ..ns import q
from ..package import Package
from ..samples import bullet_chars, classify, heading_levels

HISTORY_KEEP = 50


class EditError(Exception):
    """사용자에게 그대로 보여 줄 한국어 메시지와 HTTP 상태 코드."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def copy_path(src: Path) -> Path:
    src = Path(src)
    return src.with_name(f"{src.stem}_수정.hwpx")


def _section(pkg: Package) -> str:
    return pkg.section_names()[0]


def _tops(root) -> list:
    return [p for p in root if p.tag == q("hp:p")]


class EditDoc:
    def __init__(self, src: Path):
        self.src = Path(src)
        self.path = copy_path(self.src)
        self.history_dir = self.path.with_name(f"{self.path.stem}.이력")
        self.lock = threading.Lock()
        if not self.path.exists():
            if self.src.suffix.lower() == ".hwp":
                from .. import bridge
                bridge.convert(self.src, self.path)
            else:
                shutil.copyfile(self.src, self.path)
        self.version = 1
        self._stamp = self._stat()
        self._external = False

    def _stat(self) -> tuple[float, int]:
        st = self.path.stat()
        return st.st_mtime, st.st_size

    def doc(self) -> dict:
        pkg = Package.open(self.path)
        h = Header(pkg)
        chars = bullet_chars(h)
        names = pkg.section_names()
        ps = _tops(pkg.xml(names[0]))
        levels = heading_levels(ps)
        blocks = []
        for i, p in enumerate(ps):
            tbl = next(p.iter(q("hp:tbl")), None)
            if tbl is not None:
                blocks.append({"i": i, "kind": "table", "rows": _rows(tbl)})
                continue
            if next(p.iter(q("hp:pic")), None) is not None or next(p.iter(q("hp:equation")), None) is not None:
                if not own_text(p).strip():
                    blocks.append({"i": i, "kind": "object", "text": "[그림·수식]"})
                    continue
            role, _ = classify(p, h, chars, levels)
            blocks.append({"i": i, "kind": "para", "role": role or "other", "text": own_text(p),
                           **_looks(p, h)})
        return {"version": self.version, "name": self.path.name, "external_change": self._external,
                "sections": len(names), "blocks": blocks}


def _rows(tbl) -> list[list[dict]]:
    rows = []
    for tr in tbl.findall(q("hp:tr")):
        row = []
        for tc in tr.findall(q("hp:tc")):
            addr, span = tc.find(q("hp:cellAddr")), tc.find(q("hp:cellSpan"))
            texts = [own_text(p) for p in tc.find(q("hp:subList")).findall(q("hp:p"))]
            row.append({"r": int(addr.get("rowAddr")), "c": int(addr.get("colAddr")), "text": "\n".join(texts),
                        "rs": int(span.get("rowSpan")), "cs": int(span.get("colSpan"))})
        rows.append(row)
    return rows


def _looks(p, h: Header) -> dict:
    """화면에서 문서처럼 흉내 내는 데 쓰는 겉모양 (첫 글자 모양·문단 왼쪽 여백)."""
    ids = [run.get("charPrIDRef") for run in p.findall(q("hp:run")) if run.find(q("hp:t")) is not None]
    cp = h.get("charPr", ids[0] if ids else p.find(q("hp:run")).get("charPrIDRef"))
    pp = h.get("paraPr", p.get("paraPrIDRef"))
    left = next((m.get("value") for m in pp.iter(q("hc:left"))), "0")
    return {"size": int(cp.get("height", "1000")) / 100, "bold": cp.find(q("hh:bold")) is not None,
            "indent": int(left) / 100, "mixed": len(set(ids)) > 1}
