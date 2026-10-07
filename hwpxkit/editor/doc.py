"""편집 화면의 문서 모델. 사본에 쓰는 곳은 이 클래스 하나이고, 쓰기는 잠금으로 차례대로 한다."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Callable

from lxml import etree

from ..body import own_text, strip_lineseg
from ..header import Header
from ..ns import q
from ..package import Package
from ..samples import bullet_chars, classify, heading_levels

HISTORY_KEEP = 50
_replace = os.replace  # 사본 바꾸기 (시험에서 잠긴 파일 흉내용)


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

    def _stat(self) -> tuple[float, int]:
        st = self.path.stat()
        return st.st_mtime, st.st_size

    def check_external(self) -> bool:
        """한글 등 다른 프로그램이 사본을 바꿨으면 판 번호를 올리고 한 번만 알린다."""
        with self.lock:
            now = self._stat()
            if now != self._stamp:
                self._stamp = now
                self.version += 1
                return True
            return False

    def doc(self) -> dict:
        changed = self.check_external()
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
        return {"version": self.version, "name": self.path.name, "external_change": changed,
                "sections": len(names), "blocks": blocks}

    def _expect(self, version: int) -> None:
        if version != self.version:
            raise EditError("그 사이 문서가 바뀌었어요. 새로 불러올게요.", 409)

    def write(self, mutate: Callable[[Package], None], version: int | None = None, history: bool = True) -> int:
        """잠금 안에서 열기 → mutate → 이력 저장 → 사본 바꾸기 → 판 번호 올림. mutate가 실패하면 아무것도 안 바뀐다."""
        with self.lock:
            if version is not None:
                self._expect(version)
            pkg = Package.open(self.path)
            mutate(pkg)
            fd, tmp = tempfile.mkstemp(suffix=".hwpx", dir=self.path.parent)
            os.close(fd)
            tmp = Path(tmp)
            try:
                tmp.unlink()
                pkg.save(tmp)
                hist = None
                if history:
                    self.history_dir.mkdir(exist_ok=True)
                    hist = self.history_dir / f"{self.version:05d}.hwpx"
                    shutil.copyfile(self.path, hist)
                try:
                    _replace(tmp, self.path)
                except PermissionError as e:
                    if hist is not None:
                        hist.unlink(missing_ok=True)
                    raise EditError("한글에서 이 사본을 닫은 뒤 다시 저장해 주세요.", 423) from e
            finally:
                tmp.unlink(missing_ok=True)
            if history:
                for old in sorted(self.history_dir.glob("*.hwpx"))[:-HISTORY_KEEP]:
                    old.unlink()
            self.version += 1
            self._stamp = self._stat()
            return self.version

    def edit_para(self, version: int, i: int, text: str) -> int:
        if "\n" in text or "\r" in text:
            raise EditError("여러 문단은 '부탁하기'로 남겨 주세요.", 400)

        def mutate(pkg):
            ps = _tops(pkg.edit(_section(pkg)))
            if not 0 <= i < len(ps):
                raise EditError("그 문단을 찾지 못했어요. 새로 불러올게요.", 409)
            p = ps[i]
            has_obj = any(next(p.iter(q(t)), None) is not None for t in ("hp:tbl", "hp:pic", "hp:equation"))
            if has_obj and not own_text(p).strip():
                raise EditError("표·그림만 있는 문단은 글을 고칠 수 없어요.", 400)
            _set_text(p, text)

        return self.write(mutate, version)

    def edit_cell(self, version: int, i: int, r: int, c: int, text: str) -> int:
        lines = text.replace("\r\n", "\n").split("\n")

        def mutate(pkg):
            ps = _tops(pkg.edit(_section(pkg)))
            tbl = next(ps[i].iter(q("hp:tbl")), None) if 0 <= i < len(ps) else None
            tc = None if tbl is None else next((tc for tc in tbl.iter(q("hp:tc")) if _addr(tc) == (r, c)), None)
            if tc is None:
                raise EditError("그 칸을 찾지 못했어요. 새로 불러올게요.", 409)
            sub = tc.find(q("hp:subList"))
            cps = sub.findall(q("hp:p"))
            first = cps[0]
            for extra in cps[1:]:
                sub.remove(extra)
            _set_text(first, lines[0])
            at = sub.index(first)
            for k, line in enumerate(lines[1:], 1):
                clone = etree.fromstring(etree.tostring(first))
                _set_text(clone, line)
                sub.insert(at + k, clone)

        return self.write(mutate, version)

    def undo(self) -> int:
        hist = sorted(self.history_dir.glob("*.hwpx")) if self.history_dir.exists() else []
        if not hist:
            raise EditError("되돌릴 단계가 없어요.", 400)
        last = hist[-1]
        restored = Package.open(last)

        def mutate(pkg):
            for name in pkg.names():
                pkg.remove(name)
            for name in restored.names():
                pkg.write(name, restored.read(name))

        # 되돌리기는 이력을 새로 남기지 않고, 되살린 이력을 지운다: 거듭하면 더 옛 판으로 간다
        v = self.write(mutate, history=False)
        last.unlink(missing_ok=True)
        return v


def _addr(tc) -> tuple[int, int]:
    a = tc.find(q("hp:cellAddr"))
    return int(a.get("rowAddr")), int(a.get("colAddr"))


def _rows(tbl) -> list[list[dict]]:
    rows = []
    for tr in tbl.findall(q("hp:tr")):
        row = []
        for tc in tr.findall(q("hp:tc")):
            span = tc.find(q("hp:cellSpan"))
            r, c = _addr(tc)
            texts = [own_text(p) for p in tc.find(q("hp:subList")).findall(q("hp:p"))]
            row.append({"r": r, "c": c, "text": "\n".join(texts),
                        "rs": int(span.get("rowSpan")), "cs": int(span.get("colSpan"))})
        rows.append(row)
    return rows


def _looks(p, h: Header) -> dict:
    """화면에서 문서처럼 흉내 내는 데 쓰는 겉모양 (첫 글자 모양·문단 왼쪽 여백)."""
    ids = [run.get("charPrIDRef") for run in p.findall(q("hp:run")) if run.find(q("hp:t")) is not None]
    first = p.find(q("hp:run"))
    cp = h.get("charPr", ids[0] if ids else (first.get("charPrIDRef") if first is not None else "0"))
    pp = h.get("paraPr", p.get("paraPrIDRef"))
    left = next((m.get("value") for m in pp.iter(q("hc:left"))), "0")
    return {"size": int(cp.get("height", "1000")) / 100, "bold": cp.find(q("hh:bold")) is not None,
            "indent": int(left) / 100, "mixed": len(set(ids)) > 1}


def _set_text(p, text: str) -> None:
    """문단 글을 바꾼다. 글이 든 첫 줄의 글자 모양을 쓰고, 다른 글 조각은 지운다. 구역 설정·개체는 남긴다."""
    runs = p.findall(q("hp:run"))
    with_t = [run for run in runs if run.find(q("hp:t")) is not None]
    keep = with_t[0] if with_t else (runs[-1] if runs else etree.SubElement(p, q("hp:run"), {"charPrIDRef": "0"}))
    for run in runs:
        for t in run.findall(q("hp:t")):
            run.remove(t)
        if run is not keep and len(run) == 0:
            p.remove(run)
    t = etree.SubElement(keep, q("hp:t"))
    t.text = text
    strip_lineseg(p)
