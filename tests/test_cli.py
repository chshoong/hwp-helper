from pathlib import Path
import json

import pytest

from helpers import append_to_body, para
from hwpxkit import bridge
from hwpxkit.cli import main
from hwpxkit.package import Package

OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 100


def test_inspect_blank_json(blank, capsys):
    assert main(["inspect", str(blank), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["구역"] == 1
    assert data["개수"]["표"] == 0
    assert data["쪽 크기(mm)"] == [210, 297]
    assert "함초롬바탕" in data["글꼴"]
    assert "바탕글" in data["스타일"]


def test_inspect_human_readable(blank, capsys):
    assert main(["inspect", str(blank)]) == 0
    out = capsys.readouterr().out
    assert "본문 폭" in out and "함초롬바탕" in out


def test_validate_exit_codes(blank, tmp_path, capsys):
    assert main(["validate", str(blank)]) == 0
    assert "문제 없음" in capsys.readouterr().out
    pkg = Package.open(blank)
    append_to_body(pkg, para("x", char_pr="999"))
    bad = pkg.save(tmp_path / "bad.hwpx")
    assert main(["validate", str(bad)]) == 1
    assert "999" in capsys.readouterr().out


def test_validate_json(blank, capsys):
    assert main(["validate", str(blank), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_old_hwp_message_without_hangul(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bridge, "available", lambda: False)
    f = tmp_path / "옛날 보고서.hwp"
    f.write_bytes(OLE)
    assert main(["inspect", str(f)]) == 2
    assert "HWPX" in capsys.readouterr().err


def test_convert_refuses_overwrite(blank, capsys):
    assert main(["convert", str(blank), str(blank)]) == 2
    assert "덮어쓸" in capsys.readouterr().err


def test_missing_file(tmp_path, capsys):
    assert main(["inspect", str(tmp_path / "없음.hwpx")]) == 2
    assert "찾을 수 없" in capsys.readouterr().err


@pytest.mark.hangul
def test_inspect_hwp_via_hangul(blank, tmp_path, capsys):
    hwp = bridge.convert(blank, tmp_path / "빈 문서.hwp")
    assert main(["inspect", str(hwp), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["구역"] == 1


@pytest.mark.hangul
def test_preview(blank, tmp_path, capsys):
    assert main(["preview", str(blank), str(tmp_path / "미리보기")]) == 0
    assert "page001.png" in capsys.readouterr().out


def test_directory_is_user_error(tmp_path, capsys):
    assert main(["validate", str(tmp_path)]) == 2
    assert "찾을 수 없" in capsys.readouterr().err


def test_unexpected_error_is_not_reported_as_validation_failure(blank, capsys, monkeypatch):
    import hwpxkit.cli as cli

    def boom(pkg):
        raise RuntimeError("예상 못한 문제")

    monkeypatch.setattr(cli, "validate", boom)
    assert main(["validate", str(blank)]) == 3
    assert "내부 오류" in capsys.readouterr().err


from helpers import report_template, tiny_png


def make_template(blank, tmp_path):
    pkg = Package.open(blank)
    report_template(pkg)
    return pkg.save(tmp_path / "양식.hwpx")


def test_read_with_anchors(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    assert main(["read", str(tpl), "--anchors"]) == 0
    out = capsys.readouterr().out
    assert "<!-- @" in out and "# 제1장 서론" in out


def test_samples_json(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    assert main(["samples", str(tpl), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "h1" in data["paras"] and data["table"] is True
    assert data["tbl_label"] == "[표 {c}-{n}]"


def test_render_new_document(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs" / "a.png").write_bytes(tiny_png())
    md = tmp_path / "내용.md"
    md.write_text("# 제1장 서론\n\n□ 요약\n\n![그림](figs/a.png)\n\n| a | b |\n| c | d |\n", encoding="utf-8")
    out = tmp_path / "결과.hwpx"
    assert main(["render", str(tpl), str(md), str(out)]) == 0
    assert "저장했어요" in capsys.readouterr().out
    assert main(["validate", str(out)]) == 0


def test_render_refuses_template_as_output(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "a.md"
    md.write_text("본문", encoding="utf-8")
    assert main(["render", str(tpl), str(md), str(tpl)]) == 2
    assert "덮어쓸" in capsys.readouterr().err


def test_render_markdown_error_is_user_error(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "a.md"
    md.write_text("$$\n닫히지 않음\n", encoding="utf-8")
    assert main(["render", str(tpl), str(md), str(tmp_path / "o.hwpx")]) == 2
    assert "닫히지" in capsys.readouterr().err


def test_render_replace_range(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "a.md"
    md.write_text("## 9.9. 바뀐 절", encoding="utf-8")
    out = tmp_path / "o.hwpx"
    assert main(["render", str(tpl), str(md), str(out), "--replace", "2:3"]) == 0
    capsys.readouterr()
    assert main(["read", str(out)]) == 0
    assert "## 9.9. 바뀐 절" in capsys.readouterr().out


@pytest.mark.hangul
def test_render_into_real_final_report(private_dir, tmp_path, capsys):
    md = tmp_path / "새 보고서.md"
    md.write_text(
        "# 제1장 서론\n\n## 1.1. 연구 배경\n\n#### 1) 필요성\n\n□ 주요 내용\n\n"
        + "가상 자료로 표본 생성 실험을 수행한 결과를 정리한다. " * 3 + "\n\n"
        + "표: 시험 표 {#tbl:t}\n| 구분 | 값 |\n| a | 1 |\n\n[@tbl:t]를 보라.\n", encoding="utf-8")
    out = tmp_path / "새 보고서.hwpx"
    assert main(["render", str(private_dir / "final.hwpx"), str(md), str(out),
                 "--preview", str(tmp_path / "pages")]) == 0
    assert "page001.png" in capsys.readouterr().out


def test_render_into_template_without_body_sample_uses_body_style(blank, tmp_path):
    """본문 견본이 없는 양식도 '본문'·'바탕글' 스타일로 쓴다 (예전에는 오류로 멈췄음)."""
    md = tmp_path / "a.md"
    md.write_text("그냥 본문 문장", encoding="utf-8")
    out = tmp_path / "o.hwpx"
    assert main(["render", str(blank), str(md), str(out)]) == 0
    assert out.is_file()


@pytest.mark.hangul
def test_equations_command(blank, tmp_path, capsys):
    from hwpxkit import shapes
    from hwpxkit.ns import q
    pkg = Package.open(blank)
    from helpers import append_to_body as _add, para as _para
    p = _add(pkg, _para("수식 "))
    p.find(q("hp:run")).append(shapes.new_equation("{1} over {2}", 500, 500, 86, 1000))
    src = pkg.save(tmp_path / "a.hwpx")
    assert main(["equations", str(src), str(tmp_path / "b.hwpx")]) == 0
    assert "1개" in capsys.readouterr().out


def test_render_without_hangul_warns_estimated_equations(blank, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bridge, "available", lambda: False)
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "m.md"
    md.write_text("값 $x^2$ 입니다", encoding="utf-8")
    assert main(["render", str(tpl), str(md), str(tmp_path / "o.hwpx")]) == 0
    assert "추정" in capsys.readouterr().out


@pytest.mark.hangul
def test_render_refreshes_equations_with_hangul(blank, tmp_path, capsys):
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "m.md"
    md.write_text("값 $\\frac{a}{b}$ 입니다\n\n$$ \\sum_i x_i $$", encoding="utf-8")
    assert main(["render", str(tpl), str(md), str(tmp_path / "o.hwpx")]) == 0
    assert "수식 2개" in capsys.readouterr().out


def test_render_refresh_failure_keeps_estimated_file(blank, tmp_path, capsys, monkeypatch):
    def boom(src, dst):
        raise bridge.BridgeError("한글이 응답하지 않았어요.")
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge, "refresh_equations", boom)
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "m.md"
    md.write_text("값 $x^2$ 입니다", encoding="utf-8")
    out = tmp_path / "o.hwpx"
    assert main(["render", str(tpl), str(md), str(out)]) == 0
    printed = capsys.readouterr().out
    assert "추정 크기로 저장" in printed and out.exists()


def test_partial_refresh_is_reported(blank, tmp_path, capsys, monkeypatch):
    import shutil as _shutil

    def half(src, dst):
        _shutil.copyfile(src, dst)
        return Path(dst), 1
    monkeypatch.setattr(bridge, "available", lambda: True)
    monkeypatch.setattr(bridge, "refresh_equations", half)
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "m.md"
    md.write_text("값 $x^2$ 와 $y$ 입니다", encoding="utf-8")
    assert main(["render", str(tpl), str(md), str(tmp_path / "o.hwpx")]) == 0
    assert "2개 중 1개" in capsys.readouterr().out


def test_fields_and_fill_commands(blank, tmp_path, capsys):
    from helpers import monthly_form
    pkg = Package.open(blank)
    monthly_form(pkg)
    src = pkg.save(tmp_path / "양식.hwpx")
    assert main(["fields", str(src)]) == 0
    assert "@칸 표2 | 가상 분야" in capsys.readouterr().out
    spec = tmp_path / "3월.md"
    spec.write_text("@바꾸기 2025.03.12.(목) => 2026.04.06.(월)\n@칸 표2 | 가상 분야 | 금월\n□ 3월 실적\n",
                    encoding="utf-8")
    out = tmp_path / "3월.hwpx"
    assert main(["fill", str(src), str(spec), str(out)]) == 0
    assert "저장했어요" in capsys.readouterr().out
    assert main(["fill", str(src), str(spec), str(src)]) == 2


def test_fill_command_reports_line_errors(blank, tmp_path, capsys):
    from helpers import monthly_form
    pkg = Package.open(blank)
    monthly_form(pkg)
    src = pkg.save(tmp_path / "양식.hwpx")
    spec = tmp_path / "bad.md"
    spec.write_text("@칸 표7 | 1 | 1\nx\n", encoding="utf-8")
    assert main(["fill", str(src), str(spec), str(tmp_path / "o.hwpx")]) == 2
    assert "1번째 줄" in capsys.readouterr().err


def test_review_and_renumber_commands(blank, tmp_path, capsys):
    from helpers import monthly_form
    pkg = Package.open(blank)
    monthly_form(pkg)
    src = pkg.save(tmp_path / "m.hwpx")
    assert main(["review", str(src)]) == 1
    out = capsys.readouterr().out
    assert "[오류]" in out and "수요일" in out
    assert main(["review", str(src), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)
    assert main(["renumber", str(src), str(tmp_path / "r.hwpx")]) == 0


def test_presets_command(capsys):
    assert main(["presets"]) == 0
    out = capsys.readouterr().out
    assert "국가R&D 보고서형" in out and "rnd-report" in out


def test_render_with_preset_name(tmp_path, capsys):
    md = tmp_path / "a.md"
    md.write_text("# 제1장 서론\n\n본문 문장입니다. 충분히 긴 문장으로 본문 견본을 씁니다.\n", encoding="utf-8")
    assert main(["render", "rnd-report", str(md), str(tmp_path / "o.hwpx")]) == 0
    assert "저장했어요" in capsys.readouterr().out


def test_unknown_preset_or_missing_file(tmp_path, capsys):
    md = tmp_path / "a.md"
    md.write_text("x", encoding="utf-8")
    assert main(["render", "없는양식", str(md), str(tmp_path / "o.hwpx")]) == 2
    assert "프리셋" in capsys.readouterr().err


def test_render_hint_uses_launcher(blank, tmp_path, capsys, monkeypatch):
    """한글 없을 때 안내는 플러그인 진입점(hwpx.py)으로 적는다 (최종 리뷰)."""
    monkeypatch.setattr(bridge, "available", lambda: False)
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "m.md"
    md.write_text("값 $x^2$ 입니다", encoding="utf-8")
    assert main(["render", str(tpl), str(md), str(tmp_path / "o.hwpx")]) == 0
    out = capsys.readouterr().out
    assert "hwpx.py equations" in out and "python -m hwpxkit" not in out


def test_preview_without_hangul_saves_and_succeeds(blank, tmp_path, capsys, monkeypatch):
    """기본 모드에서 --preview는 저장 성공(0) + [주의] (최종 리뷰)."""
    monkeypatch.setattr(bridge, "available", lambda: False)
    tpl = make_template(blank, tmp_path)
    md = tmp_path / "m.md"
    md.write_text("본문 문장", encoding="utf-8")
    out = tmp_path / "o.hwpx"
    assert main(["render", str(tpl), str(md), str(out), "--preview", str(tmp_path / "pv")]) == 0
    assert out.is_file() and "[주의]" in capsys.readouterr().out


def test_append_warns_when_document_lacks_samples(tmp_path, capsys):
    """앞 장 결과에 표·수식 견본이 없으면 append가 서식 손실을 알린다 (최종 리뷰)."""
    ch1, ch2 = tmp_path / "ch1.md", tmp_path / "ch2.md"
    body = "이 장은 가상의 견본 자료를 써서 문서 서식이 그대로 유지되는지 확인한다. " * 2
    ch1.write_text(f"# 제1장 서론\n\n{body}\n", encoding="utf-8")
    ch2.write_text("# 제2장 방법\n\n표: 비교\n| 구분 | 값 |\n|---|---|\n| a | 1 |\n\n$$ y = ax $$\n", encoding="utf-8")
    first = tmp_path / "ch1.hwpx"
    assert main(["render", "rnd-report", str(ch1), str(first)]) == 0
    capsys.readouterr()
    assert main(["render", str(first), str(ch2), str(tmp_path / "ch12.hwpx"), "--mode", "append"]) == 0
    out = capsys.readouterr().out
    assert "[주의]" in out and "표" in out and "수식" in out


def test_live_status_cli(monkeypatch, capsys):
    from hwpxkit import live
    monkeypatch.setattr(live, "status", lambda doc=None: {
        "docs": ["C:/a/보고서.hwp"], "active": "C:/a/보고서.hwp", "modified": True, "selection": False})
    assert main(["live", "status"]) == 0
    out = capsys.readouterr().out
    assert "보고서.hwp" in out and "수정됨" in out


def test_live_replace_cli_reads_file(monkeypatch, tmp_path, capsys):
    from hwpxkit import live
    seen = {}
    monkeypatch.setattr(live, "replace", lambda md, doc=None, base_dir=None: seen.update(md=md) or {"mode": "text", "warnings": []})
    f = tmp_path / "new.md"
    f.write_text("새 문장", encoding="utf-8")
    assert main(["live", "replace", str(f)]) == 0
    assert seen["md"] == "새 문장" and "바꿨어요" in capsys.readouterr().out


def test_live_error_is_user_error(monkeypatch, capsys):
    from hwpxkit import live
    def boom(doc=None):
        raise live.LiveError("한글에서 문서를 연 뒤 다시 말씀해 주세요.")
    monkeypatch.setattr(live, "status", boom)
    assert main(["live", "status"]) == 2
    assert "한글에서 문서를 연 뒤" in capsys.readouterr().err
