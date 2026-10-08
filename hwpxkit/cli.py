"""명령줄 진입점: python -m hwpxkit <명령> ...

스킬·명령 문서는 이 CLI만 호출한다. 기본 출력은 사람이 읽는 한국어, --json이면 기계용 JSON.
종료 코드: 0 정상, 1 검증 오류 있음, 2 사용자 오류, 3 내부 오류(안내 메시지는 stderr).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.parse
from collections import Counter
from pathlib import Path

from . import bridge, form
from . import presets as presets_mod
from . import review as review_mod
from .header import Header
from .layout import hu_to_mm, page_geometry
from .ns import q
from .package import Package, PackageError
from .reader import to_markdown
from .render import render_into
from .samples import infer
from .validate import autofix, validate


def _resolve_template(arg: str) -> Path:
    """양식 자리의 값: 있는 파일이면 그 파일, 아니면 프리셋 이름."""
    path = Path(arg)
    if path.is_file() or path.suffix.lower() in (".hwp", ".hwpx"):
        return path
    return presets_mod.path(arg)


def _open_any(path: Path, workdir: Path) -> Package:
    if not path.is_file():
        raise PackageError(f"파일을 찾을 수 없어요: {path}")
    if path.suffix.lower() == ".hwp":
        if not bridge.available():
            raise PackageError("구형 한글(.hwp) 파일은 한글이 설치된 PC에서만 바로 열 수 있어요. "
                               "한글에서 '다른 이름으로 저장 → HWPX 문서'로 바꿔 주세요.")
        path = bridge.convert(path, workdir / (path.stem + ".hwpx"))
    return Package.open(path)


def summarize(pkg: Package) -> dict:
    h = Header(pkg)
    geo = page_geometry(pkg)
    sections = pkg.section_names()
    counts = {"문단": 0, "표": 0, "그림": 0, "수식": 0}
    runs = Counter()
    for sec in sections:
        root = pkg.xml(sec)
        counts["문단"] += sum(1 for _ in root.iter(q("hp:p")))
        counts["표"] += sum(1 for _ in root.iter(q("hp:tbl")))
        counts["그림"] += sum(1 for _ in root.iter(q("hp:pic")))
        counts["수식"] += sum(1 for _ in root.iter(q("hp:equation")))
        runs.update(r.get("charPrIDRef") for r in root.iter(q("hp:run")))
    fonts = Counter()
    for cid, n in runs.items():
        try:
            fonts[h.charpr_faces(cid)["HANGUL"] or "(알 수 없음)"] += n
        except KeyError:
            fonts["(정의 안 됨)"] += n
    return {
        "구역": len(sections),
        "쪽 크기(mm)": [round(hu_to_mm(geo.width)), round(hu_to_mm(geo.height))],
        "본문 폭(mm)": round(hu_to_mm(geo.text_width), 1),
        "개수": counts,
        "글꼴": dict(fonts.most_common()),
        "스타일": [e.get("name") for e in h.items("style")],
    }


def _print_summary(s: dict) -> None:
    w, h = s["쪽 크기(mm)"]
    print(f"쪽 크기: {w}×{h}mm, 본문 폭: {s['본문 폭(mm)']}mm, 구역 {s['구역']}개")
    print("개수: " + ", ".join(f"{k} {v}" for k, v in s["개수"].items()))
    print("글꼴(사용 횟수): " + ", ".join(f"{k} {v}" for k, v in s["글꼴"].items()))
    print("스타일: " + ", ".join(s["스타일"]))


def _cmd_inspect(args, workdir) -> int:
    s = summarize(_open_any(Path(args.file), workdir))
    if args.json:
        print(json.dumps(s, ensure_ascii=False))
    else:
        _print_summary(s)
    return 0


def _cmd_validate(args, workdir) -> int:
    issues = validate(_open_any(Path(args.file), workdir))
    if args.json:
        print(json.dumps([i.to_dict() for i in issues], ensure_ascii=False))
    elif not issues:
        print("문제 없음: 한글에서 열 때 깨질 만한 부분을 찾지 못했어요.")
    else:
        for i in issues:
            mark = "오류" if i.level == "error" else "주의"
            print(f"[{mark}] {i.message}")
    return 1 if any(i.level == "error" for i in issues) else 0


def _cmd_convert(args, workdir) -> int:
    out = bridge.convert(Path(args.src), Path(args.dst))
    print(f"저장했어요: {out}")
    return 0


def _cmd_preview(args, workdir) -> int:
    files = bridge.page_images(Path(args.file), Path(args.outdir))
    print(f"쪽 이미지 {len(files)}장을 만들었어요:")
    for f in files:
        print(f"  {f}")
    return 0


def _cmd_read(args, workdir) -> int:
    print(to_markdown(_open_any(Path(args.file), workdir), anchors=args.anchors), end="")
    return 0


def _cmd_samples(args, workdir) -> int:
    cat = infer(_open_any(_resolve_template(args.file), workdir))
    if args.json:
        data = {
            "paras": {role: {"para_pr": st.para_pr, "style": st.style, "char_pr": st.char_pr,
                             "auto_bullet": st.auto_bullet, "example": st.example, "spacer": st.spacer is not None}
                      for role, st in cat.paras.items()},
            "table": cat.table_para is not None, "figure": cat.figure_para is not None,
            "tbl_label": cat.tbl_label, "fig_label": cat.fig_label, "notes": cat.notes,
        }
        print(json.dumps(data, ensure_ascii=False))
    else:
        print("\n".join(cat.describe()))
    return 0


def _parse_range(text: str) -> tuple[int, int]:
    try:
        a, b = text.split(":")
        return int(a), int(b)
    except ValueError:
        raise ValueError(f"--replace는 '시작:끝' 형식이어야 해요 (예: 12:20). 받은 값: {text}") from None


def _cmd_render(args, workdir) -> int:
    template, out = _resolve_template(args.template), Path(args.out)
    if out.resolve() == template.resolve():
        raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    if out.suffix.lower() not in (".hwpx", ".hwp"):
        raise ValueError(f"결과 파일은 .hwpx 또는 .hwp여야 해요: {out.name}")
    md_path = Path(args.md)
    if not md_path.is_file():
        raise PackageError(f"내용 파일을 찾을 수 없어요: {md_path}")
    pkg = _open_any(template, workdir)
    cat = infer(pkg)
    warnings = render_into(pkg, cat, md_path.read_text(encoding="utf-8-sig"), mode=args.mode,
                           replace=_parse_range(args.replace) if args.replace else None,
                           base_dir=md_path.parent)
    for w in warnings:
        print(f"[주의] {w}")
    return _save_checked(pkg, out, workdir, args.preview)


def _save_checked(pkg: Package, out: Path, workdir: Path, preview) -> int:
    """자동 수정 → 검증(오류면 저장 안 함) → 저장(.hwp면 변환) → 수식 크기 맞춤 → 미리보기."""
    for f in autofix(pkg):
        print(f"[자동 수정] {f}")
    errors = [i for i in validate(pkg) if i.level == "error"]
    if errors:
        for i in errors:
            print(f"[오류] {i.message}")
        print("오류가 있어 저장하지 않았어요.")
        return 1
    hwpx = out if out.suffix.lower() == ".hwpx" else workdir / (out.stem + ".hwpx")
    out.parent.mkdir(parents=True, exist_ok=True)
    pkg.save(hwpx)
    total = _count_equations(pkg)
    if total and bridge.available():
        _refresh_in_place(hwpx, workdir, total)
    elif total:
        print("[주의] 한글이 없어 수식 크기를 추정했어요. 한글이 있는 PC에서 "
              f"'hwpx.py equations {out.name} 고친결과.hwpx'로 정확히 맞출 수 있어요.")
    if hwpx != out:
        bridge.convert(hwpx, out)
    print(f"저장했어요: {out}")
    if preview and not bridge.available():
        print("[주의] 한글이 없어 쪽 미리보기는 만들지 못했어요. 파일은 저장했어요.")
    elif preview:
        files = bridge.page_images(hwpx, Path(preview))
        print(f"쪽 이미지 {len(files)}장:")
        for f in files:
            print(f"  {f}")
    return 0


def _cmd_fields(args, workdir) -> int:
    fields = form.list_fields(_open_any(_resolve_template(args.file), workdir))
    if args.json:
        print(json.dumps(fields, ensure_ascii=False))
        return 0
    table = None
    for f in fields:
        if f["table"] != table:
            table = f["table"]
            print(f"\n[표{table}]")
        state = "내용 있음" if f["filled"] else "비어 있음"
        preview = f["text"].replace("\n", " / ")[:40]
        print(f"  {f['row']}행 {f['col']}열 ({state}) {preview}")
        print(f"    {f['address']}")
    return 0


def _cmd_fill(args, workdir) -> int:
    src, out = _resolve_template(args.file), Path(args.out)
    if out.resolve() == src.resolve():
        raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    spec = Path(args.spec)
    if not spec.is_file():
        raise PackageError(f"지시문 파일을 찾을 수 없어요: {spec}")
    pkg = _open_any(src, workdir)
    warnings = form.fill(pkg, form.parse_fill(spec.read_text(encoding="utf-8-sig")), base_dir=spec.parent)
    for w in warnings:
        print(f"[주의] {w}")
    return _save_checked(pkg, out, workdir, args.preview)


def _count_equations(pkg: Package) -> int:
    return sum(1 for sec in pkg.section_names() for _ in pkg.xml(sec).iter(q("hp:equation")))


def _report_refreshed(n: int, total: int) -> None:
    if n >= total:
        print(f"수식 {n}개 크기를 한글로 맞췄어요.")
    else:
        print(f"[주의] 수식 {total}개 중 {n}개만 한글로 크기를 맞췄어요. 나머지는 머리말·각주 같은 곳에 있거나 "
              "한글이 고치지 못한 것일 수 있어요. 한글에서 열어 확인해 주세요.")


def _refresh_in_place(hwpx: Path, workdir: Path, total: int) -> None:
    """render 결과의 수식 크기를 한글로 맞춘다. 실패해도 추정 크기 파일은 그대로 남기고 안내만 한다."""
    fixed = workdir / "eq_fixed.hwpx"
    try:
        _, n = bridge.refresh_equations(hwpx, fixed)
    except bridge.BridgeError as e:
        print(f"[주의] 한글로 수식 크기를 맞추지 못해 추정 크기로 저장했어요 ({e})")
        return
    shutil.copyfile(fixed, hwpx)
    _report_refreshed(n, total)


def _cmd_equations(args, workdir) -> int:
    total = _count_equations(_open_any(Path(args.src), workdir))
    out, n = bridge.refresh_equations(Path(args.src), Path(args.dst))
    _report_refreshed(n, total)
    print(f"저장했어요: {out}")
    return 0


def _cmd_review(args, workdir) -> int:
    findings = review_mod.review(_open_any(Path(args.file), workdir))
    if args.json:
        print(json.dumps([f.to_dict() for f in findings], ensure_ascii=False))
    elif not findings:
        print("확인할 것이 없어요.")
    else:
        for f in findings:
            print(f"[{f.level}] {f.message}")
    return 1 if any(f.level == "오류" for f in findings) else 0


def _cmd_renumber(args, workdir) -> int:
    src, out = Path(args.file), Path(args.out)
    if out.resolve() == src.resolve():
        raise PackageError("원본 파일을 덮어쓸 수 없어요. 다른 이름으로 저장해 주세요.")
    pkg = _open_any(src, workdir)
    changes = review_mod.renumber(pkg)
    for c in changes:
        print(f"  {c}")
    print(f"번호 {len(changes)}곳을 고쳤어요." if changes else "고칠 번호가 없어요.")
    return _save_checked(pkg, out, workdir, None)


def _cmd_presets(args, workdir) -> int:
    items = presets_mod.listing()
    if args.json:
        print(json.dumps(items, ensure_ascii=False))
        return 0
    for p in items:
        print(f"{p['name']}: {p['title']} — {p['description']}")
        for mark, meaning in p["levels"].items():
            print(f"    {mark}  →  {meaning}")
    return 0


def _cmd_live(args, workdir) -> int:
    from . import live
    act, doc = args.live_action, args.doc
    if act == "status":
        st = live.status(doc)
        if args.json:
            print(json.dumps(st, ensure_ascii=False))
            return 0
        print(f"지금 문서: {Path(st['active']).name}" + (" (수정됨, 저장 안 함)" if st["modified"] else ""))
        if len(st["docs"]) > 1:
            print("열린 문서: " + ", ".join(Path(d).name for d in st["docs"]))
        print("선택한 부분: " + ("있음" if st["selection"] else "없음"))
        return 0
    if act == "selection":
        sel = live.selection(doc)
        if args.json:
            print(json.dumps(sel, ensure_ascii=False))
        elif not sel["selected"]:
            print("선택한 부분이 없어요.")
        else:
            where = "표 칸 안" if sel["in_table"] else "본문"
            print(f"[{where} · {sel['paragraphs']}문단 · {sel['para']}번째 문단]\n{sel['text']}")
        return 0
    if act == "export":
        print(f"내보냈어요(창은 그대로): {live.export(Path(args.target), doc)}")
        return 0
    if act == "review":
        r = live.review(doc, memo=args.memo)
        for f in r["findings"]:
            print(f"[{f.level}] {f.message}")
        if not r["findings"]:
            print("확인할 것이 없어요.")
        if args.memo:
            print(f"한글 메모 {r['placed']}개를 달았어요." + (f" 위치를 못 찾은 것: {', '.join(r['missed'])}" if r["missed"] else ""))
        return 0
    md_path = Path(args.target)
    if not md_path.is_file():
        raise PackageError(f"내용 파일을 찾을 수 없어요: {md_path}")
    md = md_path.read_text(encoding="utf-8-sig")
    if act == "replace":
        r = live.replace(md, doc, base_dir=md_path.parent)
        print("선택한 부분을 바꿨어요." + (" (여러 문단: 양식 서식으로)" if r["mode"] == "fragment" else ""))
    elif act == "insert":
        r = live.insert(md, doc, base_dir=md_path.parent)
        print("커서가 있는 문단 다음에 넣었어요.")
    else:  # section
        r = live.section(args.heading, md, doc, base_dir=md_path.parent)
        print(f"'{r['start']}' 장을 바꿨어요." + (f" ('{r['end']}' 앞까지)" if r["end"] else " (문서 끝까지)"))
    for w in r["warnings"]:
        print(f"[주의] {w}")
    print("저장은 하지 않았어요. 한글에서 확인 후 저장하거나, 되돌리기(Ctrl+Z)로 취소할 수 있어요."
          + (" 여러 단계로 넣었으니 되돌리기를 여러 번 눌러야 할 수 있어요." if r.get("backup") else ""))
    if r.get("backup"):
        print(f"바꾸기 전 화면 문서 사본: {r['backup']}")
    return 0


def _edit_state(src: Path) -> dict | None:
    """살아 있는 편집 서버의 상태 (없거나 죽었으면 None, 죽은 상태 파일은 지운다)."""
    import urllib.request
    from .editor import copy_path
    from .editor.server import state_path
    st_file = state_path(copy_path(src))
    if not st_file.exists():
        return None
    st = json.loads(st_file.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/doc",
                                     headers={"X-Key": urllib.parse.quote(st["key"])})
        with urllib.request.urlopen(req, timeout=5):
            return st
    except OSError:
        if bridge._alive(str(st["pid"])):  # 살아 있는데 응답만 늦음: 둘째 서버를 띄우거나 직접 쓰면 안 된다
            raise PackageError("편집 화면 서버가 응답하지 않아요. 잠시 뒤 다시 시도해 주세요.")
        st_file.unlink(missing_ok=True)
        return None


def _edit_post(st: dict, path: str, body: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{st['port']}{path}", method="POST",
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"X-Key": urllib.parse.quote(st["key"]), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _cmd_edit(args, workdir) -> int:
    import subprocess
    import time
    from .editor import AskQueue, EditDoc, copy_path
    from .editor.server import serve, state_path
    src = Path(args.file)
    if not src.is_file():
        raise PackageError(f"파일을 찾을 수 없어요: {src}")
    act = args.edit_action
    if act == "serve":
        serve(src)
        return 0
    if act == "start":
        st = _edit_state(src)
        if st is None:
            EditDoc(src)  # 사본을 먼저 만들어 오류를 여기서 알린다
            root = Path(__file__).resolve().parents[1]
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([sys.executable, str(root / "hwpx.py"), "edit", "serve", str(src)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=flags, close_fds=True)
            for _ in range(60):
                time.sleep(0.25)
                st = _edit_state(src)
                if st:
                    break
            if st is None:
                raise PackageError("편집 화면을 띄우지 못했어요. 다시 시도해 주세요.")
        print(f"편집 화면: {st['url']}")
        print(f"사본: {copy_path(src)} (원본은 그대로)")
        return 0
    if act == "stop":
        st = _edit_state(src)
        if st:
            _edit_post(st, "/api/stop", {})
            for _ in range(20):
                time.sleep(0.25)
                if not state_path(copy_path(src)).exists():
                    break
        state_path(copy_path(src)).unlink(missing_ok=True)
        print("편집 화면을 껐어요.")
        return 0
    queue = AskQueue.for_copy(copy_path(src))
    if act == "asks":
        from .editor.queue import locate
        doc = EditDoc(src)
        texts = doc.texts()
        pending = []
        for a in queue.all():
            if a["status"] != "pending":
                continue
            rng = locate(texts, a)  # 앞 부탁 반영으로 번호가 밀렸을 수 있어 지금 자리를 다시 찾는다
            if rng is None:
                queue.set(a["id"], "stale", "부탁을 남긴 뒤 그 부분이 바뀌어서 어디에 반영할지 다시 확인이 필요해요.")
                print(f"[{a['id']}] 그 부분이 바뀌어서 다시 확인이 필요해요: {a['text']}", file=sys.stderr)
                continue
            pending.append({"id": a["id"], "text": a["text"], "start": rng[0], "end": rng[1],
                            "markdown": doc.range_markdown(*rng)})
        if args.json:
            print(json.dumps(pending, ensure_ascii=False))
        elif not pending:
            print("대기 중인 부탁이 없어요.")
        for a in [] if args.json else pending:
            print(f"[{a['id']}] {a['start']}~{a['end'] - 1}번 문단: {a['text']}\n{a['markdown']}")
        return 0
    if act == "watch":
        seen = {a["id"] for a in queue.all()}
        while state_path(copy_path(src)).exists():
            for a in queue.all():
                if a["id"] not in seen and a["status"] == "pending":
                    seen.add(a["id"])
                    print(f"새 부탁 {a['id']}: {a['text']}", flush=True)
            time.sleep(2)
        print("편집 화면이 꺼졌어요.", flush=True)
        return 0
    # apply
    md_path = Path(args.md)
    if not md_path.is_file():
        raise PackageError(f"내용 파일을 찾을 수 없어요: {md_path}")
    md = md_path.read_text(encoding="utf-8-sig")
    st = _edit_state(src)
    if st:
        code, r = _edit_post(st, "/api/apply", {"id": args.ask_id, "md": md, "base_dir": str(md_path.parent)})
        if code != 200:
            raise PackageError(r.get("error", "반영하지 못했어요."))
    else:
        r = EditDoc(src).apply(queue, args.ask_id, md, md_path.parent)
    for w in r.get("warnings", []):
        print(f"[주의] {w}")
    if r["status"] == "done":
        print("반영했어요. 편집 화면이 새로 고쳐져요.")
        return 0
    print(r["message"])
    return 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hwpxkit", description="HWPX 문서 도구")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inspect", help="문서 요약 (쪽 크기, 개수, 글꼴, 스타일)")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_inspect)
    s = sub.add_parser("validate", help="한글에서 깨질 만한 부분 검사")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_validate)
    s = sub.add_parser("convert", help="hwp/hwpx/pdf 변환 (한글 필요)")
    s.add_argument("src")
    s.add_argument("dst")
    s.set_defaults(func=_cmd_convert)
    s = sub.add_parser("preview", help="쪽 이미지(PNG) 만들기 (한글 필요)")
    s.add_argument("file")
    s.add_argument("outdir")
    s.set_defaults(func=_cmd_preview)
    s = sub.add_parser("read", help="문서를 보고서 마크다운으로 읽기")
    s.add_argument("file")
    s.add_argument("--anchors", action="store_true", help="문단 번호 표시 (부분 수정용)")
    s.set_defaults(func=_cmd_read)
    s = sub.add_parser("samples", help="양식에서 찾은 견본(역할별 서식) 보기")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_samples)
    s = sub.add_parser("render", help="보고서 마크다운을 양식 서식으로 넣어 새 파일 만들기")
    s.add_argument("template")
    s.add_argument("md")
    s.add_argument("out")
    s.add_argument("--mode", choices=["new", "append"], default="new")
    s.add_argument("--replace", help="최상위 문단 범위 시작:끝 (read --anchors의 번호)")
    s.add_argument("--preview", help="쪽 이미지를 만들 폴더 (한글 필요)")
    s.set_defaults(func=_cmd_render)
    s = sub.add_parser("equations", help="수식 크기를 한글로 다시 계산해 저장 (한글 필요)")
    s.add_argument("src")
    s.add_argument("dst")
    s.set_defaults(func=_cmd_equations)
    s = sub.add_parser("fields", help="양식의 표 칸 목록과 채우기 주소(@칸 …) 보기")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_fields)
    s = sub.add_parser("fill", help="지시문(@칸/@행수/@바꾸기)으로 양식 채우기")
    s.add_argument("file")
    s.add_argument("spec")
    s.add_argument("out")
    s.add_argument("--preview", help="쪽 이미지를 만들 폴더 (한글 필요)")
    s.set_defaults(func=_cmd_fill)
    s = sub.add_parser("review", help="날짜·요일·번호·참조·안내 문구·빈 칸·글꼴 검토")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_review)
    s = sub.add_parser("renumber", help="표·그림 번호를 다시 매기고 본문 참조도 고치기")
    s.add_argument("file")
    s.add_argument("out")
    s.set_defaults(func=_cmd_renumber)
    s = sub.add_parser("presets", help="양식 없이 쓸 수 있는 프리셋 목록")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_presets)
    s = sub.add_parser("live", help="열린 한글 창의 문서를 저장 없이 읽고 고치기 (한글 필요)")
    s.add_argument("live_action", choices=["status", "selection", "replace", "insert", "export", "review", "section"])
    s.add_argument("target", nargs="?", default="", help="내용 .md (replace/insert/section) 또는 결과 .hwpx (export)")
    s.add_argument("--heading", default="", help="section: 바꿀 장의 제목 글 (예: 제2장)")
    s.add_argument("--doc", default=None, help="열린 문서가 여러 개일 때 문서 이름 일부")
    s.add_argument("--memo", action="store_true", help="review: 지적 사항을 한글 메모로 달기")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_live)
    s = sub.add_parser("edit", help="앱 브라우저 창에서 사본을 보며 고치기 (원본은 그대로)")
    s.add_argument("edit_action", choices=["start", "serve", "asks", "apply", "watch", "stop"])
    s.add_argument("file", help="원본 .hwpx (또는 .hwp)")
    s.add_argument("ask_id", nargs="?", default="", help="apply: 부탁 번호 (예: a1)")
    s.add_argument("md", nargs="?", default="", help="apply: 새 내용 .md")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_edit)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="hwpxkit-") as tmp:
        try:
            return args.func(args, Path(tmp))
        except (PackageError, bridge.BridgeError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 2
        except Exception as e:  # 검증 실패(1)와 구분되도록 따로 알린다
            print(f"내부 오류가 났어요 (문서 문제가 아닐 수 있어요): {type(e).__name__}: {e}", file=sys.stderr)
            return 3
