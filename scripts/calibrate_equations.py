"""수식 크기 보정: 가상 LaTeX 수식들을 한글에 넣어 실제 크기를 재고, eqsize.K를 맞춘다.

한글이 설치된 Windows에서 실행한다.
  python scripts/calibrate_equations.py          # 측정 + tests/fixtures/eq_sizes.json 저장 + K 맞춤
  python scripts/calibrate_equations.py --fit    # 저장된 자료로 K만 다시 맞춤
"""
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.stdout.reconfigure(encoding="utf-8")

from hwpxkit import eqsize  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "eq_sizes.json"
LATEX = [
    "x", "X", "k", r"\theta", r"\Gamma", "12", "3.14", "ab", "XYZ", r"\alpha\beta\gamma", "x+y", "a=b", "a+b=c",
    r"x \le y", r"f(x)", r"f(x,y)", r"[a,b]", r"\{a\}", "x_i", "x^2", "x_i^2", r"x_{ij}^{(k)}", r"e^{-x^2}",
    r"\hat{\beta}", r"\bar{x}", r"\tilde{y}_t", r"\vec{v}", r"\frac{a}{b}", r"\frac{a+b}{c}", r"\frac{1}{2}\sigma^2",
    r"\frac{\partial f}{\partial x}", r"\frac{\frac{a}{b}}{c}", r"\sqrt{x}", r"\sqrt{x^2+y^2}", r"\sqrt[3]{x}",
    r"\sum_{i=1}^{n} x_i", r"\sum_i x_i", r"\prod_{j} p_j", r"\int_0^1 f(x)\,dx", r"\lim_{n\to\infty} a_n",
    r"\max_{i} x_i", r"\left( \frac{a}{b} \right)", r"\left[ x \right]", r"\left| x \right|",
    r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", r"\begin{bmatrix} 1 \\ 2 \\ 3 \end{bmatrix}",
    r"\begin{cases} x & x \ge 0 \\ -x & x < 0 \end{cases}", r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
    r"\text{if } x > 0", r"\operatorname{argmin}_{\theta} L(\theta)", r"\mathrm{Var}(X)", r"P(Y \mid X)",
    r"E[Y|X] = \beta_0 + \beta_1 X", r"\hat{\beta} = (X^T X)^{-1} X^T y", r"f(y,z|x)=f(y|x)f(z|x)",
    r"\sum_{i=1}^{n} w_i (y_i - \hat{y}_i)^2", r"\frac{1}{n}\sum_{i=1}^{n} x_i", r"\binom{n}{k} p^k (1-p)^{n-k}",
    r"\rho_{YZ|X}", r"a \cdot b \times c", r"x \in A \cup B", r"\alpha + \beta = \gamma",
    r"\hat{\sigma}^2", r"N(0,\hat{\sigma}^2)", r"\hat{\theta}^{(m)}", r"\bar{U}", r"\hat{F}_{Z|X}^{-1}",
    r"\tilde{x}_i^2", r"a = b \\ c = d", r"\text{가중치} \times \text{평균점수}",
    r"x^{\frac{a}{b}}", r"e^{-\frac{(x-\mu)^2}{2\sigma^2}}", r"x^{\sum_{i=1}^n a_i}", r"A_{1/2}^{1/2}",
    r"\binom{n}{k}^{1/2}", r"x_{\frac{1}{2}}", r"\frac{1}{n}\sum_{i=1}^{n} \hat{\beta}_i^2",
    r"\prod_{j=1}^{m} p_j^{x_j}", r"\forall \varepsilon > 0", r"\exists x \in A", r"A^\top \Sigma^{-1} A", r"\bigcup_{i=1}^{n} A_i",
]


def measure() -> list[dict]:
    from helpers import append_to_body, para
    from hwpxkit import bridge, shapes
    from hwpxkit.equation import latex_to_hwp
    from hwpxkit.ns import q
    from hwpxkit.package import Package
    pkg = Package.open(ROOT / "tests" / "fixtures" / "blank.hwpx")
    scripts = [latex_to_hwp(x)[0] for x in LATEX]
    for s in scripts:
        p = append_to_body(pkg, para(""))
        p.find(q("hp:run")).append(shapes.new_equation(s, 1000, 1000, 86, 1000))
    with tempfile.TemporaryDirectory() as tmp:
        src = pkg.save(Path(tmp) / "cal.hwpx")
        out, n = bridge.refresh_equations(src, Path(tmp) / "cal_out.hwpx")
        eqs = list(Package.open(out).xml("Contents/section0.xml").iter(q("hp:equation")))
    data = [{"latex": x, "script": s, "u": 1000, "w": int(e.find(q("hp:sz")).get("width")),
             "h": int(e.find(q("hp:sz")).get("height")), "b": int(e.get("baseLine"))}
            for x, s, e in zip(LATEX, scripts, eqs)]
    FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"측정 {len(data)}개 → {FIXTURE}")
    return data


def loss(data) -> float:
    total = 0.0
    for d in data:
        w, h, b = eqsize.estimate(d["script"], d["u"])
        total += (abs(math.log(w / d["w"])) + abs(math.log(h / d["h"])) + 4 * max(0.0, (d["h"] - h) / d["h"])
                  + abs(b - d["b"]) / 25 + 4 * max(0.0, (d["w"] - w) / d["w"]))
    return total / len(data)


def fit(data, rounds=12) -> None:
    best = loss(data)
    for _ in range(rounds):
        for key in list(eqsize.K):
            for factor in (0.8, 0.9, 0.95, 1.05, 1.1, 1.25):
                old = eqsize.K[key]
                eqsize.K[key] = old * factor
                cur = loss(data)
                if cur < best - 1e-6:
                    best = cur
                else:
                    eqsize.K[key] = old
    report(data)
    print("K = dict(")
    for k, v in eqsize.K.items():
        print(f"    {k}={v:.3f},")
    print(")")


def report(data) -> None:
    rw = [abs(eqsize.estimate(d["script"], d["u"])[0] / d["w"] - 1) for d in data]
    rh = [abs(eqsize.estimate(d["script"], d["u"])[1] / d["h"] - 1) for d in data]
    under = sum(eqsize.estimate(d["script"], d["u"])[1] < 0.9 * d["h"] for d in data)
    rb = [abs(eqsize.estimate(d["script"], d["u"])[2] - d["b"]) for d in data]
    print(f"너비 오차 중앙값 {statistics.median(rw):.1%}, 높이 오차 중앙값 {statistics.median(rh):.1%}, "
          f"높이 10% 넘게 작게 잡음 {under}/{len(data)}, 기준선 오차 중앙값 {statistics.median(rb):.0f}%p "
          f"(15%p 넘음 {sum(x > 15 for x in rb)})")


if __name__ == "__main__":
    data = json.loads(FIXTURE.read_text(encoding="utf-8")) if "--fit" in sys.argv else measure()
    report(data)
    fit(data)
