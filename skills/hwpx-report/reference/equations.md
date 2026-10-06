# 수식

수식은 LaTeX로 쓴다. 엔진이 한글 수식 문법으로 바꿔 한글 수식 개체로 넣는다(한글에서 수식 편집기로 고칠 수 있음).

- 문단 속: `$x_i^2$` — `$` 앞이 영문·숫자면 수식이 아니다(`US$5`는 글자). 닫는 `$` 뒤에 바로 숫자가 오면 수식이 아니다.
- 번호 붙은 문단 수식: `$$ … $$ {#eq:이름}` (`reference/markdown.md`)

## 잘 되는 것 (한글 2024에서 그려 보고 확인)

| 종류 | LaTeX |
|---|---|
| 분수·근호·조합 | `\frac{a}{b}` `\dfrac` `\tfrac` `\sqrt{x}` `\sqrt[3]{x}` `\binom{n}{k}` |
| 첨자 | `x_i^2` `x_{ij}^{(k)}` `A^\top` (전치 ⊤, `\intercal`도 같음) `x'` |
| 큰 연산자 | `\sum_{i=1}^{n}` `\prod` `\int_0^1` `\oint` `\lim_{n\to\infty}` `\bigcup` `\bigcap` (`\limits`는 무시) |
| 함수 | `\log \ln \exp \sin \cos \tan \det \max \min \arg \Pr \deg`, `\sup` `\inf`(하한, 로만체), `\operatorname{argmin}` `\operatorname*{arg\,max}` |
| 장식 | `\hat \bar \overline \tilde \vec \dot \ddot \underline` (`\widehat`·`\widetilde`는 `\hat`·`\tilde`로) |
| 글꼴 | `\text{글}`(한글 가능) `\mathrm` `\mathsf` `\mathbf` `\boldsymbol` `\bm` `\mathit` |
| 그리스 문자 | `\alpha` … `\omega`, `\varepsilon` `\varphi`, 대문자 `\Gamma \Delta \Theta \Lambda \Xi \Pi \Sigma \Phi \Psi \Omega` |
| 관계·연산 | `\le \ge \ne \approx \sim \simeq \cong \equiv \propto \ll \gg \times \cdot \div \pm \mp \ast \circ \bullet \star \odot \otimes \oplus \ominus` |
| 집합·논리 | `\in \notin \ni \subset \subseteq \supset \cup \cap \emptyset \forall \exists \neg \land \lor \wedge \vee \therefore \because \perp \parallel \angle` |
| 화살표 | `\to \rightarrow \leftarrow \Rightarrow \implies \Leftarrow \Leftrightarrow \iff \leftrightarrow \mapsto` |
| 괄호 | `\left( … \right)` `\left[ … \right]` `\left\{ … \right\}` `\left| … \right|` `\left\langle … \right\rangle` `\left\lVert … \right\rVert` `\left. … \right|` |
| 행렬·경우 | `pmatrix` `bmatrix` `vmatrix` `matrix` `cases` `aligned`·`align`·`split`(여러 줄 정렬, `&`와 `\\`) |
| 간격 | `\,` `\;` `\quad` `\qquad` |
| 버림 | `\displaystyle` `\textstyle` `\limits` `\nolimits` `\label{…}` `\tag{…}` `\nonumber` |

## 안 되는 것 (한글 수식에 없음)

`\mathbb{R}`·`\mathcal`(굵은 로만체로 바꾸고 알림), `\setminus`, `\bigoplus`, `\models`, `\nexists`, `\iint`, `\overset`·`\underbrace` 같은 꾸밈 명령(내용만 남기고 알림). 모르는 명령은 로만체 글자로 남기고 `[주의]`로 알린다.

꼭 한글 수식 문법을 직접 쓰고 싶으면 `\hwp{sum _{i} x}`처럼 감싼다(그대로 들어감).

## 수식 크기

- 한글이 있으면: 만든 뒤 한글이 모든 수식의 크기를 다시 계산한다(자동).
- 한글이 없으면: 엔진이 크기를 추정한다(한글 실측 80여 개로 맞춘 값, 높이는 작게 잡지 않음). 나중에 한글이 있는 PC에서 `equations` 명령으로 정확히 맞출 수 있다.

## 기존 문서 읽기

`read`로 읽으면 한글 수식이 LaTeX로 나온다. 사람이 쓴 한글 수식 표기(`sum from{i=1} to{n}`, `barU`, `rm SSE it`)도 읽는다.
