"""본문 견본이 없는 양식(개조식 글머리만 있는 경진대회·공모 양식 등)도 본문 문단을 쓸 수 있어야 한다."""
from helpers import LONG, SECTION, append_to_body, para
from hwpxkit.body import own_text
from hwpxkit.header import Header
from hwpxkit.ns import q
from hwpxkit.package import Package
from hwpxkit.render import render_into
from hwpxkit.samples import infer
from hwpxkit.validate import validate


def bullets_only(blank):
    pkg = Package.open(blank)
    h = Header(pkg)
    big = h.derive_charpr("0", height=1400)
    hang = h.derive("paraPr", "0", lambda e: [m.set("value", "-2000") for m in e.iter(q("hc:intent"))])
    append_to_body(pkg, para("□ 제1장. 데이터 이해 및 진단"))
    append_to_body(pkg, para("○ 휴먼명조 14, 줄간격 160", para_pr=hang, char_pr=big))
    append_to_body(pkg, para("- 휴먼명조 14, 줄간격 160"))
    return pkg, big


def test_body_paragraph_without_body_sample(blank):
    pkg, big = bullets_only(blank)
    cat = infer(pkg)
    assert "body" not in cat.paras
    render_into(pkg, cat, LONG + "\n")
    p = next(p for p in pkg.xml(SECTION) if p.tag == q("hp:p") and own_text(p) == LONG)
    h = Header(pkg)
    pp = h.get("paraPr", p.get("paraPrIDRef"))
    assert pp.find(q("hh:heading")).get("type") == "NONE"
    assert all(m.get("value") == "0" for m in pp.iter(q("hc:intent")))  # 내어쓰기 없음
    text_run = next(r for r in p.findall(q("hp:run")) if r.find(q("hp:t")) is not None)
    assert text_run.get("charPrIDRef") == big                              # ○ 글머리와 같은 글자 모양
    assert [i for i in validate(pkg) if i.level == "error"] == []
    assert "body" not in cat.paras  # 호출한 쪽 견본 목록은 바꾸지 않는다


def test_samples_describe_explains_body_fallback(blank):
    pkg, _ = bullets_only(blank)
    line = next(x for x in infer(pkg).describe() if x.startswith("본문"))
    assert "○" in line and "글머리 없이" in line


def test_body_from_style_when_no_bullets(blank):
    pkg = Package.open(blank)
    append_to_body(pkg, para("제1장 서론"))
    render_into(pkg, infer(pkg), LONG + "\n")
    assert any(own_text(p) == LONG for p in pkg.xml(SECTION) if p.tag == q("hp:p"))
