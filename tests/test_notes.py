"""'* 출처…', '※ 참고…' 주석 줄은 양식의 주석 서식(보통 작은 글씨)으로 넣는다."""
import pytest

from helpers import LONG, SECTION, append_to_body, para
from hwpxkit.body import own_text
from hwpxkit.header import Header
from hwpxkit.mdparse import Note, Para, parse
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.reader import to_markdown
from hwpxkit.render import render_into
from hwpxkit.samples import classify, infer


@pytest.mark.parametrize("text", ["* 휴먼명조 10, 줄간격 160", "※ 작성 후 삭제", "* 출처: 팀 공통 코드"])
def test_note_lines_are_notes(blank, text):
    h = Header(Package.open(blank))
    assert classify(para(text), h, {})[0] == "note"


def test_italic_is_not_a_note(blank):
    h = Header(Package.open(blank))
    assert classify(para("*강조* 로 시작하지만 주석이 아닌 아주 긴 본문 문장이 여기에 이어진다"), h, {})[0] == "body"


def test_markdown_note_block():
    blocks = parse("* 출처는 팀 공통 코드\n※ 수치는 잠정값\n*기울임*으로 시작하는 문장\n")
    assert isinstance(blocks[0], Note) and isinstance(blocks[1], Note)
    assert isinstance(blocks[2], Para)


def with_note_sample(blank):
    pkg = Package.open(blank)
    small = Header(pkg).derive_charpr("0", height=900)
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para(LONG))
    append_to_body(pkg, para("* 휴먼명조 10, 줄간격 160", char_pr=small))
    return pkg, small


def test_note_uses_note_sample(blank):
    pkg, small = with_note_sample(blank)
    render_into(pkg, infer(pkg), LONG + "\n* 전처리는 팀 공통 코드로 일원화함\n")
    p = next(p for p in pkg.xml(SECTION) if p.tag == q("hp:p") and own_text(p).startswith("* 전처리"))
    run = next(r for r in p.findall(q("hp:run")) if r.find(q("hp:t")) is not None)
    assert run.get("charPrIDRef") == small
    assert own_text(p) == "* 전처리는 팀 공통 코드로 일원화함"


def test_note_without_sample_falls_back_to_body(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para(LONG))
    render_into(pkg, infer(pkg), LONG + "\n※ 수치는 잠정값임\n")
    assert any(own_text(p) == "※ 수치는 잠정값임" for p in pkg.xml(SECTION) if p.tag == q("hp:p"))


def test_note_reads_back(blank):
    pkg, _ = with_note_sample(blank)
    render_into(pkg, infer(pkg), LONG + "\n* 전처리는 팀 공통 코드로 일원화함\n")
    assert "* 전처리는 팀 공통 코드로 일원화함" in to_markdown(pkg).splitlines()
