# 차례·표목차·그림목차와 상호 참조 (toc) 설계

## 1. 목적

보고서에 다음을 한글 고유 기능으로 넣는다. 그래서 사용자가 나중에 한글에서 고쳐도 계속 맞게 유지된다.

- 장·절 차례, 표 목차, 그림 목차: 쪽 번호 포함. 한글의 "차례 새로 고침"으로 다시 맞춰진다.
- 본문의 표·그림 참조: "[표 3]"의 번호를 한글 상호 참조로 넣는다. 표가 옮겨지면 한글이 번호를 고친다.
- 양식에 이미 있는 빈 목차 자리를 채운다.

## 2. 검증된 사실 (2026-10-08 실험, 한글 2024 13.0.0.564)

| 확인 | 결과 |
|---|---|
| `HAction.Execute("MakeContents")` 자동 호출 | 실패. 숨김/보임, 설정값과 관계없이 RPC_E_SERVERFAULT가 나고 한글이 죽음. 쓰지 않는다 |
| `HAction.Run("UpdateAllContents")` (숨은 한글) | 성공. 문서 안 차례 칸(TABLEOFCONTENTS)을 다시 만들고 쪽 번호를 채운다 |
| 상호 참조(CROSSREF) 표시 글 | 한글이 열 때 다시 계산한다. 틀린 값을 넣어 둬도 열면 맞는 값이 보인다 |
| 쪽 번호 묻기 | `KeyIndicator`를 C# 리플렉션(ParameterModifier, 7번째 인자 short)으로 부르면 PowerShell에서 된다. 이번 설계에서는 쓰지 않는다(새로 고침으로 충분) |

### 2.1 차례 칸 구조 (사용자가 한글에서 만든 표 차례에서 얻음)

차례 칸은 `TABLEOFCONTENTS` 필드로 시작하는 문단 하나, 항목 문단들, `fieldEnd`만 있는 문단 하나로 이루어진다.

```xml
<hp:p paraPrIDRef=".." styleIDRef="(차례 제목)"><hp:run charPrIDRef=".."><hp:ctrl>
  <hp:fieldBegin id="N" type="TABLEOFCONTENTS" name="" editable="1" dirty="0" zorder="-1" fieldid="F" metaTag="">
    <hp:parameters cnt="2" name="">
      <hp:integerParam name="Prop">8</hp:integerParam>
      <hp:stringParam name="Command" xml:space="preserve">TableOfContents:set:139:ContentsMake:uint:2 ContentsStyles:wstring:0: ContentsLevel:int:2 ContentsAutoTabRight:int:0 ContentsLeader:int:3 ContentsHyperlink:bool:1  </hp:stringParam>
    </hp:parameters></hp:fieldBegin></hp:ctrl><hp:t/></hp:run></hp:p>
<!-- 항목: HYPERLINK 필드로 대상 개체(?#<개체 id>)에 이어짐, 글 + 점선 오른쪽 탭 + 쪽 번호 -->
<hp:p paraPrIDRef=".." styleIDRef="(차례 1)"> ... <hp:fieldBegin type="HYPERLINK" ...>
  Command "?#1000000000;0;2;0;", Category HWPHYPERLINK_TYPE_HWP, TargetType HWPHYPERLINK_TARGET_TABLE ...
  <hp:t>[표 1-1] 첫째 표<hp:tab width="39216" leader="3" type="2"/>1</hp:t> ... fieldEnd</hp:p>
<hp:p ...><hp:run><hp:ctrl><hp:fieldEnd beginIDRef="N" fieldid="F"/></hp:ctrl><hp:t/></hp:run></hp:p>
```

- `ContentsMake` 비트: 1 = 제목(개요), 2 = 표, 4 = 그림, 8 = 수식, 64 = 차례 코드(제목 차례 표시). 실험 결과 1|64 = 65이면 제목 차례 표시가 붙은 제목을 모은다.
- 새로 고침은 항목 문단을 한글이 다시 만든다. 엔진이 넣는 항목은 한글이 없을 때 보일 임시 목록이다.
- 스타일 "차례 제목"(engName "TOC Heading"), "차례 1"(engName "TOC 1")은 한글 기본 문서 머리에 있다.

### 2.2 제목 차례 표시

`<hp:t><hp:titleMark ignore="1"/>제목 글</hp:t>`. 한글의 `Run("MarkTitle")`이 이 모양으로 넣었고, `ContentsMake` 64에서 모인다. `ignore="0"`은 모이지 않았다.

### 2.3 상호 참조 구조

```xml
<hp:ctrl><hp:fieldBegin id="N" type="CROSSREF" name="" editable="0" dirty="0" zorder="-1" fieldid="F" metaTag="">
  <hp:parameters cnt="8" name="">
    <hp:booleanParam name="Fiexde">1</hp:booleanParam>
    <hp:integerParam name="Prop">0</hp:integerParam>
    <hp:stringParam name="Command">?#<개체 id>;<대상 0=표 1=그림>;<내용 0=쪽 1=번호 2=캡션 내용>;0;0;</hp:stringParam>
    <hp:stringParam name="RefPath">?#<개체 id>;</hp:stringParam>
    <hp:stringParam name="RefType">TARGET_TABLE | TARGET_PICTURE</hp:stringParam>
    <hp:stringParam name="RefContentType">OBJECT_TYPE_NUMBER</hp:stringParam>
    <hp:booleanParam name="RefHyperLink">false</hp:booleanParam>
    <hp:stringParam name="RefOpenType">HWPHYPERLINK_JUMP_CURRENTTAB</hp:stringParam>
  </hp:parameters></hp:fieldBegin></hp:ctrl><hp:t>3</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="N" fieldid="F"/></hp:ctrl>
```

- `OBJECT_TYPE_NUMBER`는 한글 자동 번호(문서 전체에서 센 번호)를 보여 준다. 장별 번호 "[표 2-1]"의 "2-1"은 만들 수 없다(실험: [표 2-1]을 가리켜도 "2"가 보임).
- 대상 개체 id는 `hp:tbl`·`hp:pic`의 `id` 속성이다.

## 3. 사용 흐름

- 새 보고서: 마크다운에 `[차례]`, `[표 목차]`, `[그림 목차]` 줄을 쓰면 그 자리에 차례 칸이 들어간다. 본문의 "[표 3]"은 자동으로 상호 참조가 된다(장별 번호가 아닌 문서만). 한글이 있으면 마지막에 새로 고침까지 한다.
- 기존 문서: `hwpx.py toc <문서> <결과> [--kinds 제목,표,그림] [--level 2]`. 양식에 목차 자리가 있으면 거기를 채우고, 없으면 표지 다음에 넣는다. `--refs`를 주면 본문 참조도 상호 참조로 바꾼다.
- 한글이 없을 때: 차례 칸에 쪽 번호 없는 임시 목록을 넣고 "한글에서 도구 → 차례 새로 고침(또는 차례 모두 새로 고침)을 눌러 주세요"라고 안내한다.

## 4. 구성

| 파일 | 책임 |
|---|---|
| `hwpxkit/toc.py` (새로) | 차례 칸 만들기·교체, 제목 차례 표시, 차례 자리 찾기, 상호 참조 연결, 임시 항목 목록 |
| `hwpxkit/bridge_hwp.ps1`, `bridge.py` | 동작 `refresh_toc`: 숨은 한글로 열어 `UpdateAllContents` 후 다른 이름으로 저장 |
| `hwpxkit/render.py`, `mdparse.py` | `[차례]` `[표 목차]` `[그림 목차]` 블록, 렌더 뒤 상호 참조 연결 |
| `hwpxkit/cli.py` | `toc` 명령, `render`·`fill`의 마무리 단계에서 연결·새로 고침 |
| `hwpxkit/review.py` | 차례가 있는데 새로 고침이 안 된 것(쪽 번호 빈 항목)을 [확인]으로 알림 |
| 스킬 문서 | `reference/toc.md`, SKILL.md 한 줄 |

### toc.py 인터페이스

- `insert_toc(pkg, kinds: set[str], *, level: int = 2, at: int | None = None) -> list[str]` — kinds ⊆ {"제목", "표", "그림"}. 종류마다 차례 칸 하나(제목 칸이 맨 앞)를 `at` 문단 앞(없으면 자동 자리)에 넣거나, 같은 종류의 기존 칸을 바꾼다. 경고 목록을 돌려준다.
- `mark_titles(pkg, level: int) -> int` — h1..h{level} 역할 문단에 `titleMark ignore="1"`을 넣는다(이미 있으면 그대로). 넣은 수를 돌려준다.
- `find_slot(pkg) -> tuple[int, str]` — (문단 번호, 근거). 근거는 "기존 차례 칸" / "양식 목차 자리" / "표지 다음" / "문서 처음".
- `link_refs(pkg) -> tuple[int, list[str]]` — 본문 "[표 n]", "[그림 n]", "표 n", "그림 n"의 n을 CROSSREF로 바꾼다. 장별 번호 문서면 0과 이유를 돌려준다.
- `uses_chapter_numbers(pkg) -> bool` — 캡션 글이 "n-m" 꼴이면 True.

## 5. 동작 규칙

### 차례 칸

- 종류별 `ContentsMake`: 제목 = 65(1|64), 표 = 2, 그림 = 4. `ContentsLevel`은 level, `ContentsLeader` 3(점선), `ContentsHyperlink` 1.
- 시작 문단 스타일은 "차례 제목", 항목은 "차례 1"을 쓴다. 문서에 그 스타일이 없으면 바탕글 + 오른쪽 탭 문단 모양을 만든다.
- 시작 문단의 글은 비워 둔다. 한글이 새로 고칠 때 "<표 차례>" 같은 머리글을 넣는다.
- 임시 항목: 제목은 표시한 제목 글, 표·그림은 캡션 글(번호 포함)을 쓰고, 탭 뒤 쪽 번호는 비운다. 항목은 HYPERLINK 필드 없이 글만 넣는다(새로 고침에서 다시 만들어짐).
- 다시 넣기: 같은 `ContentsMake`의 기존 칸(fieldBegin부터 그 fieldEnd 문단까지)을 지우고 그 자리에 넣는다.
- 필드 id·fieldid는 문서 안에서 겹치지 않는 값을 새로 매긴다(기존 IdAllocator와 같은 방식).

### 차례 자리

1. 기존 TABLEOFCONTENTS 칸 → 그 자리.
2. 본문 문단 글이 정확히 "목차", "차례", "목 차", "차 례", "표 목차", "그림 목차", "표 차례", "그림 차례"(공백 무시)인 문단 → 그 다음 문단 앞. 그 다음에 있는 빈 문단과 빈 목차 표(모든 칸이 비었거나 "…"만 있는 표)는 차례 칸으로 바꾼다. 종류별 제목이 따로 있으면 각 칸을 자기 제목 아래에 넣는다.
3. 첫 `pageBreak="1"` 문단(표지 다음) → 그 앞에 넣고, 차례 칸 뒤에 쪽 나누기를 둔다.
4. 아무것도 없으면 문서 처음(0번 문단 다음).

### 상호 참조

- 대상: 첫 구역 본문 문단의 글. 표 칸 안 글과 캡션 안 글, 차례 칸 안 글은 건드리지 않는다.
- "[표 n]"·"표 n"(n은 숫자, 뒤에 "-" 없음)을 찾아, n번째 캡션 달린 표의 id로 CROSSREF(번호)를 만든다. 글 "[표 " / "]"는 그대로 두고 숫자만 필드로 감싼다.
- 이미 필드 안에 있는 글은 다시 감싸지 않는다(다시 실행해도 같음).
- n이 실제 표 수보다 크면 바꾸지 않는다(review의 기존 참조 검사가 알림).
- 장별 번호 문서(캡션 "n-m")는 아무것도 바꾸지 않고, `renumber`의 기존 글 고침을 쓴다.
- 문단 안에서 여러 글 조각(run)에 걸친 "[표 3]"은 바꾸지 않는다(드묾, 경고 없이 건너뜀).

### 새로 고침

- `bridge.refresh_toc(src, dst)`: 숨은 한글로 열고 `Run("UpdateAllContents")` 뒤 dst에 HWPX로 저장한다. src와 dst는 달라야 한다.
- `render`·`fill`·`toc` 명령은 결과에 차례 칸이 있고 한글이 있으면 마지막에 새로 고침을 한다. 한글이 없거나 실패하면 결과는 그대로 두고 안내만 한다.

## 6. 오류 처리

| 상황 | 동작 |
|---|---|
| 넣을 제목(h1..h{level})이 없음 | 제목 칸은 넣지 않고 경고 |
| 캡션 달린 표·그림이 없음 | 그 종류 칸은 넣지 않고 경고 |
| 한글 없음·새로 고침 실패 | 결과 저장은 그대로, 쪽 번호가 빈 이유와 한글에서 새로 고치는 방법 안내 |
| 장별 번호 문서에서 `--refs` | 바꾸지 않고 "장별 번호는 renumber가 글로 함께 고쳐요" 안내 |
| 구역이 여러 개 | 첫 구역만 다루고 경고 |

## 7. 범위 밖

- 수식 차례, 찾아보기(색인).
- 장별 번호의 한글 고유 상호 참조.
- 차례 항목의 단계별 들여쓰기 직접 조정(한글 새로 고침이 정함. 시험에서 확인한 결과를 스킬 문서에 적는다).

## 8. 시험

- toc.py 단위:
  - 차례 칸 구조(시작 필드 Command·Make 값, 끝 필드, 임시 항목).
  - mark_titles(단계 제한, 다시 해도 하나).
  - find_slot 네 경우.
  - 다시 넣기에서 칸이 하나만 남음.
  - link_refs: 숫자만 필드, 표·그림 구분, 없는 번호 그대로, 장별 번호 문서 제외, 다시 실행해도 같음, 캡션·표 칸 글 제외.
- render: `[차례]` 블록, 렌더 뒤 상호 참조 연결.
- 한글 시험(hangul):
  - 새로 고침 뒤 표 차례·그림 차례 쪽 번호가 실제 쪽과 맞음.
  - 제목 차례가 채워짐.
  - 상호 참조 문서를 열면 맞는 번호가 보임(일부러 틀린 값을 넣은 뒤 확인).
- 실제 결과물 확인: 시험 보고서를 한글로 열어 쪽 그림으로 차례 모양을 확인(수동, 기록).
