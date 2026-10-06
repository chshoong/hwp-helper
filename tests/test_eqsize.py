import json
import statistics
from pathlib import Path

import pytest

from hwpxkit.eqsize import estimate

FIXTURE = Path(__file__).parent / "fixtures" / "eq_sizes.json"


def test_plain_letter_is_one_line():
    w, h, b = estimate("X", 1000)
    assert 900 <= h <= 1300 and 80 <= b <= 90


def test_fraction_is_taller_than_line():
    assert estimate("{a} over {b}", 1000)[1] > 1.8 * estimate("a", 1000)[1]


def test_scales_with_base_unit():
    w1, h1, _ = estimate("x _{i} ^{2}", 1000)
    w2, h2, _ = estimate("x _{i} ^{2}", 2000)
    assert w2 == pytest.approx(2 * w1, abs=2) and h2 == pytest.approx(2 * h1, abs=2)


def test_estimates_match_hangul_sizes():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(data) >= 60
    rw = [abs(estimate(d["script"], d["u"])[0] / d["w"] - 1) for d in data]
    rh = [abs(estimate(d["script"], d["u"])[1] / d["h"] - 1) for d in data]
    under = [d["latex"] for d in data if estimate(d["script"], d["u"])[1] < 0.9 * d["h"]]
    assert statistics.median(rw) <= 0.15
    assert statistics.median(rh) <= 0.10
    assert len(under) <= len(data) * 0.05, under


def test_real_report_sizes(private_dir):
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    eqs = list(Package.open(private_dir / "final.hwpx").xml("Contents/section0.xml").iter(q("hp:equation")))
    rh = [abs(estimate(e.findtext(q("hp:script")), int(e.get("baseUnit")))[1]
              / int(e.find(q("hp:sz")).get("height")) - 1) for e in eqs]
    assert statistics.median(rh) <= 0.15


def test_top_level_line_break_stacks_lines():
    one = estimate("a = b", 1000)[1]
    two = estimate("a = b # c = d", 1000)[1]
    assert two >= 1.8 * one


def test_baselines_match_hangul():
    """기준선이 틀리면 수식이 글줄에서 위아래로 밀려 겹치거나 뜬다 (검토 I-4)."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    diffs = sorted(abs(estimate(d["script"], d["u"])[2] - d["b"]) for d in data)
    assert statistics.median(diffs) <= 5
    assert sum(x > 15 for x in diffs) <= len(data) * 0.05, diffs[-5:]


def test_fraction_in_superscript_is_in_calibration_set():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    latex = {d["latex"] for d in data}
    assert r"x^{\frac{a}{b}}" in latex and r"x^{\sum_{i=1}^n a_i}" in latex


def test_width_is_rarely_underestimated():
    """너비를 작게 잡으면 문단 속 수식 뒤 글자와 겹친다 (실제 양식 확인에서 '∀ε > 0에' 겹침)."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    under = [d["latex"] for d in data if estimate(d["script"], d["u"])[0] < 0.95 * d["w"]]
    assert len(under) <= len(data) * 0.05, under
