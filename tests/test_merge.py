"""이전 판 비교(compare)와 의견 합치기(merge)."""
import json
import shutil

import pytest

from helpers import LONG, SECTION, append_to_body, memo_run, para, table
from hwpxkit.ns import q
from hwpxkit.package import Package


def base_doc(blank, tmp_path, name="보고서.hwpx"):
    pkg = Package.open(blank)
    append_to_body(pkg, para("제1장 서론"))
    append_to_body(pkg, para("연구 배경을 설명하는 첫 문단이다. " + LONG))
    append_to_body(pkg, para("연구 목적을 설명하는 둘째 문단이다. " + LONG))
    append_to_body(pkg, table(2, 2, texts={(0, 0): "구분", (0, 1): "값", (1, 0): "표본", (1, 1): "120명"}))
    append_to_body(pkg, para("제2장 방법"))
    append_to_body(pkg, para("해당 없음"))
    append_to_body(pkg, para("자료 수집 절차를 설명한다. " + LONG))
    append_to_body(pkg, para("해당 없음"))
    return pkg.save(tmp_path / name)


def tops(pkg):
    return [p for p in pkg.xml(SECTION) if p.tag == q("hp:p")]


def edited(src, dst, change):
    """src 사본을 만들고 change(pkg)로 고쳐 dst에 저장."""
    shutil.copy(src, dst)
    pkg = Package.open(dst)
    change(pkg)
    out = dst.with_name(dst.stem + ".tmp.hwpx")
    pkg.save(out)
    out.replace(dst)
    return dst


def set_text(pkg, i, text):
    from hwpxkit.editor.doc import _set_text
    _set_text([p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][i], text)


def test_units_and_where(blank, tmp_path):
    from hwpxkit.compare import units
    us = units(Package.open(base_doc(blank, tmp_path)))
    keys = [u.key for u in us]
    assert ("p", 2) in keys and ("c", 4, 1, 1, 1, 0) in keys
    cell = next(u for u in us if u.key == ("c", 4, 1, 1, 1, 0))
    assert cell.text == "120명" and cell.where == "제1장 서론 · 표1 2행 2열"
    assert next(u for u in us if u.key == ("p", 7)).where == "제2장 방법"
    assert all(u.text for u in us)


def test_diff_edit_add_del(blank, tmp_path):
    from hwpxkit.compare import diff, units
    src = base_doc(blank, tmp_path)

    def change(pkg):
        set_text(pkg, 3, "연구 목적을 설명하는 둘째 문단이며 조금 고쳤다. " + LONG)
        root = pkg.edit(SECTION)
        ps = [p for p in root if p.tag == q("hp:p")]
        root.remove(ps[7])  # 자료 수집 절차 문단 삭제
        root.insert(root.index(ps[2]) + 1, para("새로 넣은 문단이다."))
        from hwpxkit.editor.doc import _set_text
        cell = [tc for tc in root.iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "150명")
    new = edited(src, tmp_path / "새판.hwpx", change)
    changes = diff(units(Package.open(src)), units(Package.open(new)))
    kinds = sorted((c["kind"], c.get("new", c.get("old"))) for c in changes)
    assert ("add", "새로 넣은 문단이다.") in kinds
    assert any(k == "del" and t.startswith("자료 수집 절차를") for k, t in kinds)
    edits = {c["old"][:6]: c for c in changes if c["kind"] == "edit"}
    assert set(edits) == {"연구 목적을", "120명"}
    assert edits["120명"]["new"] == "150명" and edits["120명"]["where"] == "제1장 서론 · 표1 2행 2열"
    add = next(c for c in changes if c["kind"] == "add")
    assert add["after_key"] == ("p", 2)


def test_memos_read(blank, tmp_path):
    from hwpxkit.compare import memos
    src = base_doc(blank, tmp_path)

    def change(pkg):
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
        p.append(memo_run("메모가 붙은 글", "근거를 더 쓰세요"))
    out = edited(src, tmp_path / "메모.hwpx", change)
    ms = memos(Package.open(out))
    assert ms == [{"text": "근거를 더 쓰세요", "anchor": "메모가 붙은 글", "where": "제1장 서론"}]


def test_memo_text_not_in_units(blank, tmp_path):
    from hwpxkit.compare import diff, units
    src = base_doc(blank, tmp_path)

    def change(pkg):
        p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][2]
        run = memo_run("", "근거를 더 쓰세요")
        for el in list(run):
            if el.tag == q("hp:t"):
                run.remove(el)
        p.insert(0, run)
    out = edited(src, tmp_path / "메모만.hwpx", change)
    assert diff(units(Package.open(src)), units(Package.open(out))) == []


def add_memo(pkg, i, memo):
    """i번 문단의 글을 그대로 둔 채 메모로 감싼다 (글은 바뀌지 않음)."""
    from hwpxkit.body import own_text
    p = [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][i]
    text = own_text(p)
    for run in p.findall(q("hp:run")):
        for t in run.findall(q("hp:t")):
            run.remove(t)
    p.append(memo_run(text, memo))


def opinion_files(blank, tmp_path):
    src = base_doc(blank, tmp_path)

    def hong(pkg):
        set_text(pkg, 3, "연구 목적을 설명하는 둘째 문단이며 홍이 고쳤다. " + LONG)
        add_memo(pkg, 2, "출처를 다세요")

    def kim(pkg):
        set_text(pkg, 3, "연구 목적을 설명하는 둘째 문단이며 김이 고쳤다. " + LONG)
    a = edited(src, tmp_path / "보고서_홍길동.hwpx", hong)
    b = edited(src, tmp_path / "보고서-김철수.hwpx", kim)
    return src, a, b


def test_opinion_name():
    from pathlib import Path
    from hwpxkit.merge import opinion_name
    base = Path("보고서.hwpx")
    taken = set()
    assert opinion_name(base, Path("보고서_홍길동.hwpx"), taken) == "홍길동"
    assert opinion_name(base, Path("보고서-김철수.hwpx"), taken) == "김철수"
    assert opinion_name(base, Path("보고서_홍길동.hwpx"), taken) == "보고서_홍길동"  # 겹치면 파일 이름
    assert opinion_name(base, Path("의견.hwpx"), taken) == "의견"


def test_opinions_numbered_with_conflict(blank, tmp_path):
    from hwpxkit.merge import opinions
    src, a, b = opinion_files(blank, tmp_path)
    ops = opinions(Package.open(src), [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    assert [o["id"] for o in ops] == ["m1", "m2", "m3"]
    kinds = [(o["who"], o["kind"]) for o in ops]
    assert kinds == [("홍길동", "memo"), ("홍길동", "edit"), ("김철수", "edit")]
    assert ops[1]["conflict"] == ["m3"] and ops[2]["conflict"] == ["m2"] and ops[0]["conflict"] == []


def test_conflict_marked(blank, tmp_path):
    from hwpxkit.merge import memo_text, opinions
    src, a, b = opinion_files(blank, tmp_path)
    ops = opinions(Package.open(src), [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    assert memo_text(ops[0]) == "[홍길동] 출처를 다세요"
    assert memo_text(ops[1]).startswith("[충돌] [홍길동 수정] 원래: 연구 목적을") and "→ 고친 글:" in memo_text(ops[1])


def test_original_memos_not_repeated(blank, tmp_path):
    from hwpxkit.merge import opinions
    src = base_doc(blank, tmp_path)
    with_memo = edited(src, tmp_path / "원본메모.hwpx",
                       lambda pkg: [p for p in pkg.edit(SECTION) if p.tag == q("hp:p")][1].append(
                           memo_run("연구 배경", "원래 있던 메모")))
    copy = tmp_path / "원본메모_박.hwpx"
    shutil.copy(with_memo, copy)
    assert opinions(Package.open(with_memo), [("박", Package.open(copy))]) == []


def test_notes_become_opinions(blank, tmp_path):
    from hwpxkit.merge import opinions
    src = base_doc(blank, tmp_path)
    ops = opinions(Package.open(src), [], notes=[{"who": "교수님", "where_text": "자료 수집 절차", "text": "표본 크기 근거"}])
    assert ops == [{"id": "m1", "who": "교수님", "kind": "note", "text": "표본 크기 근거", "anchor": "자료 수집 절차",
                    "where": "제2장 방법", "conflict": []}]


def test_anchor_counts_earlier_occurrences(blank, tmp_path):
    from hwpxkit.compare import units
    from hwpxkit.merge import anchor_for
    us = units(Package.open(base_doc(blank, tmp_path)))
    assert anchor_for(us, ("p", 8)) == ("해당 없음", 2)
    assert anchor_for(us, ("p", 6)) == ("해당 없음", 1)
    assert anchor_for(us, None, text="자료 수집 절차") == ("자료 수집 절차", 1)
    assert anchor_for(us, None, text="없는 글") is None


def test_memo_plan_falls_back(blank, tmp_path):
    from hwpxkit.merge import memo_plan, opinions
    src = base_doc(blank, tmp_path)
    ops = opinions(Package.open(src), [], notes=[{"who": "교수님", "where_text": "없는 글", "text": "의견"}])
    plan = memo_plan(Package.open(src), ops)
    assert plan[0]["anchor"] == "제1장 서론" and plan[0]["text"].startswith("[자리 못 찾음] [교수님]")


def test_accept_edit_keeps_format(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    before = tops(base)[3].get("paraPrIDRef"), tops(base)[3].find(q("hp:run")).get("charPrIDRef")
    ops = opinions(base, [("홍길동", Package.open(a))])
    applied, skipped = accept(base, ops, ["m2"])
    from hwpxkit.body import own_text
    p = tops(base)[3]
    assert applied == ["m2"] and skipped == []
    assert "홍이 고쳤다" in own_text(p) and (p.get("paraPrIDRef"), p.find(q("hp:run")).get("charPrIDRef")) == before


def test_accept_cell_edit_add_del(blank, tmp_path):
    from hwpxkit.body import own_text
    from hwpxkit.compare import units
    from hwpxkit.merge import accept, opinions
    src = base_doc(blank, tmp_path)

    def change(pkg):
        from hwpxkit.editor.doc import _set_text
        root = pkg.edit(SECTION)
        cell = [tc for tc in root.iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "150명")
        ps = [p for p in root if p.tag == q("hp:p")]
        root.remove(ps[7])
        root.insert(root.index(ps[3]) + 1, para("셋째로 넣은 문단."))
    other = edited(src, tmp_path / "보고서_이.hwpx", change)
    base = Package.open(src)
    ops = opinions(base, [("이", Package.open(other))])
    applied, skipped = accept(base, ops, [o["id"] for o in ops])
    texts = [u.text for u in units(base)]
    assert "150명" in texts and "셋째로 넣은 문단." in texts and not any(t.startswith("자료 수집") for t in texts)
    assert texts.index("셋째로 넣은 문단.") == texts.index(next(t for t in texts if t.startswith("연구 목적"))) + 1


def test_accept_skips_changed_original(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    ops = opinions(base, [("홍길동", Package.open(a))])
    set_text(base, 3, "그 사이 원본이 바뀜")
    applied, skipped = accept(base, ops, ["m2"])
    assert applied == [] and "m2" in skipped[0]


def test_accept_both_conflicting_refused(blank, tmp_path):
    from hwpxkit.merge import MergeError, accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    ops = opinions(base, [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    with pytest.raises(MergeError, match="충돌"):
        accept(base, ops, ["m2", "m3"])
    with pytest.raises(MergeError, match="m9"):
        accept(base, ops, ["m9"])


def test_delete_last_cell_paragraph_blanks(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src = base_doc(blank, tmp_path)

    def change(pkg):
        from hwpxkit.editor.doc import _set_text
        cell = [tc for tc in pkg.edit(SECTION).iter(q("hp:tc"))][3]
        _set_text(cell.find(q("hp:subList")).find(q("hp:p")), "")
    other = edited(src, tmp_path / "보고서_최.hwpx", change)
    base = Package.open(src)
    ops = opinions(base, [("최", Package.open(other))])
    assert [o["kind"] for o in ops] == ["del"]
    accept(base, ops, ["m1"])
    cell = [tc for tc in base.xml(SECTION).iter(q("hp:tc"))][3]
    assert len(cell.find(q("hp:subList")).findall(q("hp:p"))) == 1


def test_accept_memo_ignored(blank, tmp_path):
    from hwpxkit.merge import accept, opinions
    src, a, b = opinion_files(blank, tmp_path)
    base = Package.open(src)
    ops = opinions(base, [("홍길동", Package.open(a))])
    applied, skipped = accept(base, ops, ["m1"])
    assert applied == [] and "메모" in skipped[0]


def test_add_memos_uses_bridge(tmp_path, monkeypatch):
    from hwpxkit import bridge
    seen = {}

    def fake_run(action, work, *, src=None, dst=None, fmt=None, timeout=0):
        seen["action"], seen["memos"] = action, json.loads(open(fmt, encoding="utf-8").read())
        open(dst, "wb").write(b"x")
        return {"ok": True, "placed": 1, "missed": [2]}  # 1부터 센 번호
    monkeypatch.setattr(bridge, "_require", lambda: None)
    monkeypatch.setattr(bridge, "_run", fake_run)
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"y")
    memos = [{"anchor": "가", "n": 1, "text": "m"}, {"anchor": "나", "n": 2, "text": "n"}]
    placed, missed = bridge.add_memos(src, tmp_path / "b.hwpx", memos)
    assert seen["action"] == "memos" and seen["memos"] == memos and placed == 1 and missed == [memos[1]]
    assert (tmp_path / "b.hwpx").read_bytes() == b"x"


def test_cli_compare(blank, tmp_path, capsys, monkeypatch):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src, a, b = opinion_files(blank, tmp_path)
    assert main(["compare", str(src), str(a)]) == 0
    out = capsys.readouterr().out
    assert "제1장 서론" in out and "~ 수정" in out and "홍이 고쳤다" in out
    assert main(["compare", str(src), str(src)]) == 0
    assert "바뀐 곳이 없어요" in capsys.readouterr().out
    assert main(["compare", str(src), str(a), "--memo", str(tmp_path / "표시.hwpx")]) == 0
    assert "한글이 있어야" in capsys.readouterr().out and not (tmp_path / "표시.hwpx").exists()


def test_cli_merge_table_and_accept(blank, tmp_path, capsys, monkeypatch):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src, a, b = opinion_files(blank, tmp_path)
    out = tmp_path / "모음본.hwpx"
    assert main(["merge", str(src), str(a), str(b), str(out), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [o["id"] for o in data["opinions"]] == ["m1", "m2", "m3"] and not out.exists()
    assert main(["merge", str(src), str(a), str(b), str(out), "--accept", "m2"]) == 0
    text = capsys.readouterr().out
    assert "m2" in text and out.exists()
    from hwpxkit.body import own_text
    assert "홍이 고쳤다" in own_text(tops(Package.open(out))[3])
    assert main(["merge", str(src), str(a), str(b), str(out), "--accept", "m2,m3"]) == 2
    assert "충돌" in capsys.readouterr().err


def test_cli_merge_notes_and_errors(blank, tmp_path, capsys, monkeypatch):
    from hwpxkit import bridge
    from hwpxkit.cli import main
    monkeypatch.setattr(bridge, "available", lambda: False)
    src = base_doc(blank, tmp_path)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps([{"who": "교수님", "where_text": "자료 수집 절차", "text": "근거"}], ensure_ascii=False),
                     encoding="utf-8")
    assert main(["merge", str(src), str(tmp_path / "out.hwpx"), "--notes", str(notes), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["opinions"][0]["kind"] == "note"
    assert main(["merge", str(src), str(src)]) == 2
    assert "덮어쓸 수 없어요" in capsys.readouterr().err


@pytest.mark.hangul
def test_add_memos_with_hangul(blank, tmp_path):
    from hwpxkit import bridge
    from hwpxkit.compare import memos
    src = base_doc(blank, tmp_path)
    plan = [{"anchor": "해당 없음", "n": 2, "text": "[홍길동] 둘째 자리"},
            {"anchor": "120명", "n": 1, "text": "[김철수] 칸 메모"},
            {"anchor": "없는 글", "n": 1, "text": "x"}]
    placed, missed = bridge.add_memos(src, tmp_path / "메모본.hwpx", plan)
    assert placed == 2 and missed == [plan[2]]
    ms = memos(Package.open(tmp_path / "메모본.hwpx"))
    texts = {m["text"]: m for m in ms}
    assert set(texts) == {"[홍길동] 둘째 자리", "[김철수] 칸 메모"}
    assert texts["[홍길동] 둘째 자리"]["where"] == "제2장 방법"


def test_skill_documents_merge():
    from pathlib import Path
    root = Path(__file__).parents[1] / "skills" / "hwp-helper"
    text = (root / "reference" / "merge.md").read_text(encoding="utf-8")
    for word in ('hwpx.py" compare', 'hwpx.py" merge', "--accept", "--notes", "충돌"):
        assert word in text, word
    assert "reference/merge.md" in (root / "SKILL.md").read_text(encoding="utf-8")


def test_memo_plan_combines_same_spot(blank, tmp_path):
    """같은 자리에 붙는 의견은 메모 하나에 줄을 나눠 담는다 (한 자리에 메모를 두 번 달면 둘째는 자리를 못 찾음)."""
    from hwpxkit.merge import memo_plan, opinions
    src, a, b = opinion_files(blank, tmp_path)
    ops = opinions(Package.open(src), [("홍길동", Package.open(a)), ("김철수", Package.open(b))])
    plan = memo_plan(Package.open(src), ops)
    assert len(plan) == 2
    both = next(p for p in plan if "김철수" in p["text"])
    assert "[홍길동 수정]" in both["text"] and "\n" in both["text"] and both["id"] == "m2,m3"
