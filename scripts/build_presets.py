"""프리셋 4종 제작: 빈 문서 → preset_kit 서식 + 견본 → 한글로 다시 저장 → 미리보기.

한글이 설치된 Windows에서 실행: python scripts/build_presets.py [이름 ...]
견본 글은 역할을 알아볼 수 있게 쓰고(samples.infer가 이것으로 역할을 배운다), 사용자 문서 내용은 넣지 않는다.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import preset_kit as kit  # noqa: E402
from lxml import etree  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from hwpxkit import bridge, shapes  # noqa: E402
from hwpxkit.header import Header  # noqa: E402
from hwpxkit.layout import page_geometry  # noqa: E402
from hwpxkit.ns import q  # noqa: E402
from hwpxkit.package import Package  # noqa: E402
from hwpxkit.samples import ParaStyle  # noqa: E402

BLANK = ROOT / "tests" / "fixtures" / "blank.hwpx"
OUT = ROOT / "presets"
LONG = ("본문 견본 문단입니다. 실제 보고서에서는 이 서식으로 일반 문단이 들어가며, "
        "글꼴과 글자 크기, 줄 간격과 문단 간격이 그대로 적용됩니다.")


def P(text, style):
    return kit.p(text, *style)


def add(pkg, *elements):
    sec = pkg.edit(pkg.section_names()[0])
    for el in elements:
        sec.append(el)


def sample_png(path: Path, size=(1200, 600)) -> None:
    img = Image.new("RGB", size, (245, 247, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(90, 110, 140), width=6)
    for k, hgt in enumerate((0.55, 0.35, 0.7, 0.5, 0.8)):
        x0 = 120 + k * 200
        d.rectangle([x0, size[1] - 80 - int(hgt * (size[1] - 200)), x0 + 120, size[1] - 80], fill=(120, 140, 175))
    img.save(path)


def figure(pkg, tmp, caption, cap_style, width):
    png = tmp / "sample.png"
    sample_png(png)
    bid = pkg.add_bin(png.read_bytes(), "png")
    w = int(width * 0.6)
    pic = shapes.new_picture(bid, 1200, 600, w, w // 2, "견본.png")
    pic.append(shapes.new_caption(caption, w, cap_style[0], "0", cap_style[1]))
    holder = kit.p("", *cap_style)
    run = holder.find(q("hp:run"))
    run.remove(run.find(q("hp:t")))
    run.append(pic)
    etree.SubElement(run, q("hp:t"))
    return holder


def equations(h, body, width):
    unit = int(h.get("charPr", body[1]).get("height"))
    inline = P("수식 견본 문단: 회귀식의 기울기 ", body)
    inline.find(q("hp:run")).append(shapes.new_equation("beta _{1}", 1000, round(unit * 1.3), 80, unit))
    eq = shapes.new_equation("y = beta _{0} + beta _{1} x + epsilon", 6000, round(unit * 1.3), 80, unit)
    return [inline, shapes.new_eq_table_para(h, ParaStyle(body[0], "0", body[1]), width, eq, "(1)")]


def merge_right(table_para, r, c):
    """(r, c) 칸을 오른쪽 칸과 가로로 합친다."""
    cells = {(int(tc.find(q("hp:cellAddr")).get("rowAddr")), int(tc.find(q("hp:cellAddr")).get("colAddr"))): tc
             for tc in table_para.iter(q("hp:tc"))}
    left, right = cells[(r, c)], cells[(r, c + 1)]
    left.find(q("hp:cellSpan")).set("colSpan", "2")
    sz = left.find(q("hp:cellSz"))
    sz.set("width", str(int(sz.get("width")) + int(right.find(q("hp:cellSz")).get("width"))))
    right.getparent().remove(right)


def build_rnd(pkg, h, tmp):
    kit.set_page(pkg, top=20, bottom=15, left=20, right=20, header=10, footer=10)
    width = page_geometry(pkg).text_width
    B, D = "함초롬바탕", "함초롬돋움"
    body = (kit.para(h, line=160, next_pt=4), kit.char(h, 11, font=B))
    blank = (kit.para(h, line=160), kit.char(h, 11, font=B))
    h1 = (kit.para(h, align="CENTER", prev_pt=12, next_pt=14, keep_next=True), kit.char(h, 18, bold=True, font=B))
    h2 = (kit.para(h, align="LEFT", prev_pt=12, next_pt=6, keep_next=True), kit.char(h, 15, bold=True, font=B))
    h3 = (kit.para(h, align="LEFT", prev_pt=8, next_pt=4, keep_next=True), kit.char(h, 13, bold=True, font=B))
    h4 = (kit.para(h, align="LEFT", prev_pt=6, next_pt=3, keep_next=True), kit.char(h, 12, bold=True, font=B))
    b1 = (kit.para(h, align="LEFT", prev_pt=6, next_pt=3, keep_next=True), kit.char(h, 12, bold=True, font=B))
    b2 = (kit.para(h, left_mm=4, indent_mm=-4, line=160, next_pt=2), kit.char(h, 11, font=B))
    b3 = (kit.para(h, left_mm=8, indent_mm=-3, line=160, next_pt=2), kit.char(h, 11, font=B))
    b4 = (kit.para(h, left_mm=11, indent_mm=-3, line=160, next_pt=2), kit.char(h, 11, font=B))
    cap = (kit.para(h, align="CENTER", prev_pt=6, next_pt=4, keep_next=True), kit.char(h, 10, bold=True, font=B))
    th = (kit.para(h, align="CENTER", line=130), kit.char(h, 10, bold=True, font=D))
    td = (kit.para(h, align="CENTER", line=130), kit.char(h, 10, font=D))
    tbl = kit.table(3, 3, width=width, head_bf=kit.fill_border(h, "#E7E6E6"), body_bf=kit.fill_border(h, "none"),
                    head=th, body=td, texts={(0, 0): "구분", (0, 1): "항목 1", (0, 2): "항목 2", (1, 0): "가",
                                             (1, 1): "1.0", (1, 2): "2.0", (2, 0): "나", (2, 1): "3.0", (2, 2): "4.0"})
    add(pkg, P("제1장 견본 장 제목", h1), P("1.1. 견본 절 제목", h2), P("1.1.1. 견본 소절 제목", h3),
        P("1) 견본 항 제목", h4), P("□ 견본 글머리 첫째 단계", b1), P("○ 견본 글머리 둘째 단계입니다", b2),
        P("- 견본 글머리 셋째 단계입니다", b3), P("· 견본 글머리 넷째 단계입니다", b4), P(LONG, body), P(LONG, body),
        P("[표 1-1] 견본 표 제목", cap), tbl, figure(pkg, tmp, "[그림 1-1] 견본 그림 제목", cap, width),
        *equations(h, body, width), P("", blank), P("제2장 두 번째 장 제목", h1), P(LONG, body))


def build_gov(pkg, h, tmp):
    kit.set_page(pkg, top=15, bottom=15, left=20, right=20, header=10, footer=10)
    width = page_geometry(pkg).text_width
    M, G = "휴먼명조", "맑은 고딕"
    body = (kit.para(h, line=160, next_pt=4), kit.char(h, 15, font=M))
    blank = (kit.para(h, line=160), kit.char(h, 15, font=M))
    h1 = (kit.para(h, align="LEFT", prev_pt=14, next_pt=8, keep_next=True, line=150), kit.char(h, 17, bold=True, font=G))
    h2 = (kit.para(h, align="LEFT", prev_pt=10, next_pt=6, keep_next=True, line=150), kit.char(h, 15, bold=True, font=G))
    b1 = (kit.para(h, left_mm=5, indent_mm=-5, prev_pt=8, line=160), kit.char(h, 15, font=M))
    b2 = (kit.para(h, left_mm=10, indent_mm=-5, prev_pt=3, line=160), kit.char(h, 15, font=M))
    b3 = (kit.para(h, left_mm=15, indent_mm=-4, line=160), kit.char(h, 13, font=M))
    b4 = (kit.para(h, left_mm=19, indent_mm=-4, line=160), kit.char(h, 13, font=M))
    cap = (kit.para(h, align="CENTER", prev_pt=6, next_pt=4, keep_next=True), kit.char(h, 12, bold=True, font=G))
    th = (kit.para(h, align="CENTER", line=130), kit.char(h, 12, bold=True, font=G))
    td = (kit.para(h, align="CENTER", line=130), kit.char(h, 12, font=G))
    tbl = kit.table(3, 3, width=width, head_bf=kit.fill_border(h, "#DCE6F2"), body_bf=kit.fill_border(h, "none"),
                    head=th, body=td, texts={(0, 0): "구분", (0, 1): "현황", (0, 2): "개선 방향", (1, 0): "가",
                                             (1, 1): "내용", (1, 2): "내용", (2, 0): "나", (2, 1): "내용", (2, 2): "내용"})
    add(pkg, P("Ⅰ. 견본 장 제목", h1), P("1. 견본 절 제목", h2), P("□ 견본 글머리 첫째 단계 문장", b1),
        P("○ 견본 글머리 둘째 단계 문장", b2), P("- 견본 글머리 셋째 단계 문장", b3), P("· 견본 글머리 넷째 단계 문장", b4),
        P(LONG, body), P("[표 1] 견본 표 제목", cap), tbl, figure(pkg, tmp, "[그림 1] 견본 그림 제목", cap, width),
        *equations(h, body, width), P("", blank), P("Ⅱ. 두 번째 장 제목", h1), P("□ 견본 글머리 첫째 단계 문장", b1))


def build_paper(pkg, h, tmp):
    kit.set_page(pkg, top=20, bottom=15, left=20, right=20, header=10, footer=10)
    width = page_geometry(pkg).text_width
    B, D = "함초롬바탕", "함초롬돋움"
    body = (kit.para(h, line=160, indent_mm=3), kit.char(h, 10, font=B))
    blank = (kit.para(h, line=160), kit.char(h, 10, font=B))
    h2 = (kit.para(h, align="LEFT", prev_pt=12, next_pt=4, keep_next=True), kit.char(h, 12, bold=True, font=B))
    h3 = (kit.para(h, align="LEFT", prev_pt=6, next_pt=2, keep_next=True), kit.char(h, 10, bold=True, font=B))
    b2 = (kit.para(h, left_mm=4, indent_mm=-4, line=160), kit.char(h, 10, font=B))
    b3 = (kit.para(h, left_mm=7, indent_mm=-3, line=160), kit.char(h, 10, font=B))
    cap = (kit.para(h, align="CENTER", prev_pt=6, next_pt=4, keep_next=True), kit.char(h, 9, bold=True, font=B))
    th = (kit.para(h, align="CENTER", line=130), kit.char(h, 9, bold=True, font=D))
    td = (kit.para(h, align="CENTER", line=130), kit.char(h, 9, font=D))
    tbl = kit.table(3, 3, width=width, head_bf=kit.fill_border(h, "#F2F2F2"), body_bf=kit.fill_border(h, "none"),
                    head=th, body=td, texts={(0, 0): "모형", (0, 1): "추정값", (0, 2): "표준오차", (1, 0): "A",
                                             (1, 1): "0.52", (1, 2): "0.03", (2, 0): "B", (2, 1): "0.61", (2, 2): "0.04"})
    add(pkg, P("1. 견본 절 제목", h2), P("1.1. 견본 소절 제목", h3), P(LONG, body), P(LONG, body),
        P("○ 견본 목록 첫째 단계입니다", b2), P("- 견본 목록 둘째 단계입니다", b3), P("[표 1] 견본 표 제목", cap), tbl,
        figure(pkg, tmp, "[그림 1] 견본 그림 제목", cap, width), *equations(h, body, width), P("", blank),
        P("2. 두 번째 절 제목", h2), P(LONG, body))


def build_progress(pkg, h, tmp):
    kit.set_page(pkg, top=15, bottom=15, left=15, right=15, header=10, footer=10)
    width = page_geometry(pkg).text_width
    G = "맑은 고딕"
    box_id, dash_id = kit.add_bullets(h, ["□", "-"])
    title = (kit.para(h, align="CENTER", line=150), kit.char(h, 20, bold=True, font=G))
    date = (kit.para(h, align="CENTER", prev_pt=24, next_pt=24), kit.char(h, 14, font=G))
    sec_head = (kit.para(h, align="LEFT", prev_pt=12, next_pt=4, keep_next=True), kit.char(h, 13, bold=True, font=G))
    th = (kit.para(h, align="CENTER", line=130), kit.char(h, 10, bold=True, font=G))
    td = (kit.para(h, align="CENTER", line=130), kit.char(h, 10, font=G))
    box = (kit.para(h, align="LEFT", line=130, bullet=box_id), kit.char(h, 10, font=G))
    dash = (kit.para(h, align="LEFT", left_mm=2, line=130, bullet=dash_id), kit.char(h, 10, font=G))
    cell_blank = (kit.para(h, align="LEFT", line=130), kit.char(h, 10, font=G))
    line = kit.fill_border(h, "none")
    shade = kit.fill_border(h, "#E7E6E6")
    cover = kit.table(1, 1, width=width, head_bf=line, body_bf=line, head=title, body=title,
                      texts={(0, 0): "‘26년 3월 월간업무보고서"})
    rate = kit.table(2, 4, width=width, head_bf=shade, body_bf=line, head=th, body=td,
                     texts={(0, 0): "계획(A)", (0, 1): "실적(B)", (0, 2): "계획 대비 실적(B/A)", (0, 3): "비고",
                            (1, 0): "0.0%", (1, 1): "0.0%", (1, 2): "0%"})
    plan = kit.table(4, 3, width=width, head_bf=shade, body_bf=line, head=th, body=td, widths=[1, 2, 2],
                     texts={(0, 0): "구분", (0, 1): "금월 추진실적", (0, 2): "향후 계획사항", (1, 0): "추진 과제 1",
                            (2, 0): "추진 과제 2", (3, 0): "요청사항", (3, 1): "-"})
    for rc in ((1, 1), (1, 2), (2, 1), (2, 2)):
        paragraphs = [P("견본 추진 항목", box), P("세부 추진 내용", dash)]
        if rc == (1, 1):
            paragraphs += [P("", cell_blank), P("둘째 추진 항목", box), P("세부 추진 내용", dash)]
        kit.cell_paragraphs(plan, rc, paragraphs)
    merge_right(plan, 3, 1)
    attach = kit.table(3, 2, width=width, head_bf=shade, body_bf=line, head=th, body=td, widths=[1, 3],
                       texts={(0, 0): "구분", (0, 1): "상세 추진 내용", (1, 0): "세부 과제 1", (1, 1): "상세 추진 내용",
                              (2, 0): "세부 과제 2", (2, 1): "상세 추진 내용"})
    add(pkg, cover, P("보 고 일 : 2026.04.06.(월)", date), P("□ 전체 공정률/달성률", sec_head), rate,
        P("□ 전월 실적 및 당월 계획", sec_head), plan, P("□ 별첨", sec_head), attach)


BUILDERS = {"rnd-report": build_rnd, "gov-brief": build_gov, "paper": build_paper, "progress": build_progress}


def build(name: str) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        pkg = Package.open(BLANK)
        h = Header(pkg)
        BUILDERS[name](pkg, h, tmp)
        raw = pkg.save(tmp / "raw.hwpx")
        dst = OUT / name
        dst.mkdir(parents=True, exist_ok=True)
        fixed, _ = bridge.refresh_equations(raw, tmp / "eq.hwpx")   # 수식 크기도 한글이 계산
        bridge.convert(fixed, dst / "template.hwpx")                 # 한글로 다시 저장해 정규화
        kit.scrub_metadata(dst / "template.hwpx")                   # 작성자 이름·날짜 지움
        pages = bridge.page_images(dst / "template.hwpx", tmp / "pages")
        shutil.copyfile(pages[0], dst / "preview.png")
    print(f"만들었어요: {name}")


if __name__ == "__main__":
    for name in (sys.argv[1:] or list(BUILDERS)):
        build(name)
