import json
import subprocess

import pytest

from hwpxkit import bridge


def test_available_returns_bool():
    assert isinstance(bridge.available(), bool)


def test_unavailable_raises_korean_error(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "available", lambda: False)
    with pytest.raises(bridge.BridgeError, match="한글"):
        bridge.check(tmp_path / "x.hwpx")


def test_timeout_becomes_bridge_error(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=1)

    src = tmp_path / "x.hwpx"
    src.write_bytes(b"x")
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    with pytest.raises(bridge.BridgeError, match="응답"):
        bridge.check(src)


def test_unknown_target_format(tmp_path):
    with pytest.raises(ValueError, match="형식"):
        bridge.convert(tmp_path / "a.hwpx", tmp_path / "a.txt")


def test_same_path_refused(tmp_path):
    f = tmp_path / "a.hwpx"
    with pytest.raises(ValueError, match="덮어쓸"):
        bridge.convert(f, f)


@pytest.mark.hangul
def test_blank_fixture_opens_with_one_page(blank):
    assert bridge.check(blank) == 1


@pytest.mark.hangul
def test_convert_with_korean_bracket_path(blank, tmp_path):
    src = tmp_path / "[가상 과제 테스트](2차년도) 보고서 (4).hwpx"
    src.write_bytes(blank.read_bytes())
    pdf = bridge.convert(src, tmp_path / "결과 (1).pdf")
    hwp = bridge.convert(src, tmp_path / "결과 (1).hwp")
    assert pdf.stat().st_size > 0
    assert hwp.stat().st_size > 0


@pytest.mark.hangul
def test_page_images(blank, tmp_path):
    files = bridge.page_images(blank, tmp_path / "쪽 이미지")
    assert len(files) == 1
    assert files[0].suffix == ".png" and files[0].exists()


def test_timeout_kills_only_the_hangul_it_started(monkeypatch, tmp_path):
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"x")
    killed = []

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "powershell":
            pid_file = cmd[cmd.index("-PidFile") + 1]
            with open(pid_file, "w") as f:
                f.write("1234")
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=1)
        killed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    with pytest.raises(bridge.BridgeError, match="멈췄"):
        bridge.check(src)
    assert killed == [["taskkill", "/PID", "1234", "/T", "/F"]]


@pytest.mark.hangul
def test_long_path_over_260_chars(blank, tmp_path):
    d = tmp_path
    try:
        while len(str(d)) < 240:
            d = d / "[가상 과제 긴 폴더 이름 예시](2차년도)"
        d.mkdir(parents=True)
        src = d / "2월 보고서_수정 양식 (4).hwpx"
        src.write_bytes(blank.read_bytes())
    except OSError:
        pytest.skip("이 PC는 260자 넘는 경로를 만들 수 없음")
    assert len(str(src)) > 260
    assert bridge.check(src) == 1
    assert bridge.convert(src, d / "결과.pdf").stat().st_size > 0


def test_missing_source_is_friendly(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "available", lambda: True)
    with pytest.raises(bridge.BridgeError, match="찾을 수 없"):
        bridge.check(tmp_path / "없는 파일.hwpx")


def test_refresh_refuses_same_path_and_wrong_suffix(tmp_path):
    f = tmp_path / "a.hwpx"
    with pytest.raises(ValueError, match="덮어쓸"):
        bridge.refresh_equations(f, f)
    with pytest.raises(ValueError, match="hwpx"):
        bridge.refresh_equations(f, tmp_path / "b.pdf")


@pytest.mark.hangul
def test_refresh_fixes_wrong_sizes_inline_and_in_table(blank, tmp_path):
    from helpers import SECTION, append_to_body, para, table
    from hwpxkit import shapes
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    pkg = Package.open(blank)
    p = append_to_body(pkg, para("본문 "))
    p.find(q("hp:run")).append(shapes.new_equation("{a+b} over {c}", 975, 1200, 86, 1000))
    t = append_to_body(pkg, table(1, 2, texts={(0, 1): "(1)"}))
    next(t.iter(q("hp:tc"))).find(f".//{q('hp:run')}").append(
        shapes.new_equation("sum _{i=1} ^{n} x_i ^2", 975, 1200, 86, 1000))
    out, n = bridge.refresh_equations(pkg.save(tmp_path / "a.hwpx"), tmp_path / "b.hwpx")
    assert n == 2
    heights = [int(e.find(q("hp:sz")).get("height")) for e in Package.open(out).xml(SECTION).iter(q("hp:equation"))]
    assert all(h > 1500 for h in heights)


@pytest.mark.hangul
def test_refresh_real_report_equations(private_dir, tmp_path):
    out, n = bridge.refresh_equations(private_dir / "final.hwpx", tmp_path / "final_eq.hwpx")
    assert n == 269
    assert bridge.check(out) == bridge.check(private_dir / "final.hwpx")


def _fake_ps(results, calls, alive=()):
    """powershell 호출마다 results에서 하나씩 JSON을 돌려주는 가짜 subprocess.run."""
    alive = list(alive)

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if cmd[0] == "powershell":
            res = results.pop(0)
            if "pid" in res:
                with open(cmd[cmd.index("-PidFile") + 1], "w") as f:
                    f.write(res.pop("pid"))
            return subprocess.CompletedProcess(cmd, 0, (json.dumps(res) + "\n").encode(), b"")
        out = alive.pop(0) if alive else ""
        return subprocess.CompletedProcess(cmd, 0, out.encode(), b"")

    return fake_run


def test_rpc_unavailable_is_retried(monkeypatch, tmp_path):
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"x")
    calls = []
    results = [{"ok": False, "error": "The RPC server is unavailable. (Exception from HRESULT: 0x800706BA)"},
               {"ok": True, "pages": 3}]
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge.subprocess, "run", _fake_ps(results, calls))
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    assert bridge.check(src) == 3
    assert sum(c[0] == "powershell" for c in calls) == 2


def test_waits_until_started_hangul_exits(monkeypatch, tmp_path):
    src = tmp_path / "a.hwpx"
    src.write_bytes(b"x")
    calls = []
    results = [{"ok": True, "pages": 1, "pid": "4321"}]
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge.subprocess, "run", _fake_ps(results, calls, alive=["Hwp.exe 4321", "Hwp.exe 4321"]))
    monkeypatch.setattr(bridge.time, "sleep", lambda s: None)
    assert bridge.check(src) == 1
    assert sum(c[0] == "tasklist" for c in calls) == 3


@pytest.mark.hangul
def test_page_images_after_equation_refresh_are_whole_pages(blank, tmp_path):
    """수식 크기를 맞춘 뒤 저장한 문서에서 쪽 이미지가 '선택된 수식 그림'으로 나오던 문제 (프리셋 제작 중 발견)."""
    from helpers import append_to_body, para
    from hwpxkit import shapes
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    from PIL import Image
    pkg = Package.open(blank)
    from hwpxkit.samples import ParaStyle
    p = append_to_body(pkg, para("수식 "))
    p.find(q("hp:run")).append(shapes.new_equation("y = a x + b", 3000, 1300, 80, 1000))
    from hwpxkit.header import Header
    eq = shapes.new_equation("y = a x + b", 3000, 1300, 80, 1000)
    append_to_body(pkg, shapes.new_eq_table_para(Header(pkg), ParaStyle("0", "0", "0"), 40000, eq, "(1)"))
    out, _ = bridge.refresh_equations(pkg.save(tmp_path / "a.hwpx"), tmp_path / "b.hwpx")
    files = bridge.page_images(out, tmp_path / "pages")
    assert len(files) == bridge.check(out)
    assert Image.open(files[0]).size[0] > 700
