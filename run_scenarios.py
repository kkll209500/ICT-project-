"""
시나리오 실행 및 결과물(CSV, 차트) 생성 스크립트

사용법:
    python3 run_scenarios.py

data/kam_facts.csv에 등록된 "감가상각개시시점이 KAM으로 지적된" 모든
회사/연도/기준 조합에 대해 -6개월~+6개월 시나리오를 계산하고,
output/ 폴더에 CSV 요약표와 비교 차트를 저장합니다.
"""

import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from cip_timing_simulator import (
    load_case_facts,
    load_capitalized_borrowing_cost,
    run_capitalization_scope_scenario,
    run_scenario_set,
    _read_csv,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 한글 폰트 설정 (있으면 사용, 없으면 기본 폰트로 진행 - 라벨이 깨질 수 있음)
for font_name in ["NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "AppleGothic"]:
    if any(font_name.lower() in f.name.lower() for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = font_name
        break
plt.rcParams["axes.unicode_minus"] = False


def get_kam_cases():
    rows = _read_csv("kam_facts.csv")
    return [
        (r["company"], int(r["fiscal_year"]), r["basis"])
        for r in rows
        if r["population_at_risk"]
    ]


def write_summary_csv(all_results):
    path = os.path.join(OUTPUT_DIR, "scenario_summary.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "company",
                "fiscal_year",
                "basis",
                "population_at_risk_mkrw",
                "is_approximation",
                "shift_months",
                "months_depreciated",
                "delta_depreciation_mkrw",
                "delta_cogs_mkrw",
                "delta_operating_income_mkrw",
                "delta_net_income_mkrw",
            ]
        )
        for (company, year, basis), facts, results in all_results:
            for r in results:
                writer.writerow(
                    [
                        company,
                        year,
                        basis,
                        f"{facts.population_at_risk:.0f}",
                        facts.is_approximation,
                        r.shift_months,
                        r.months_depreciated,
                        f"{r.delta_depreciation:.0f}",
                        f"{r.delta_cogs:.0f}",
                        f"{r.delta_operating_income:.0f}",
                        f"{r.delta_net_income:.0f}",
                    ]
                )
    print(f"저장됨: {path}")


def write_capitalization_scope_csv(cases):
    path = os.path.join(OUTPUT_DIR, "capitalization_scope_summary.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "company",
                "fiscal_year",
                "basis",
                "capitalized_borrowing_cost_mkrw",
                "useful_life_years",
                "capitalized_case_current_year_expense_mkrw",
                "expensed_case_current_year_expense_mkrw",
                "delta_net_income_mkrw",
            ]
        )
        for company, year, basis in cases:
            cap_cost = load_capitalized_borrowing_cost(company, year, basis)
            if cap_cost is None:
                continue
            facts = load_case_facts(company, year, basis)
            r = run_capitalization_scope_scenario(facts, cap_cost)
            writer.writerow(
                [
                    company,
                    year,
                    basis,
                    f"{cap_cost:.0f}",
                    r.useful_life_years,
                    f"{r.capitalized_case_current_year_expense:.0f}",
                    f"{r.expensed_case_current_year_expense:.0f}",
                    f"{r.delta_net_income:.0f}",
                ]
            )
    print(f"저장됨: {path}")


def plot_comparison(all_results):
    fig, ax = plt.subplots(figsize=(10, 6))
    for (company, year, basis), facts, results in all_results:
        label = f"{company} FY{year} ({basis}){' *근사' if facts.is_approximation else ''}"
        xs = [r.shift_months for r in results]
        ys = [r.delta_net_income / 1_000_000 for r in results]  # 백만원 -> 조원
        ax.plot(xs, ys, marker="o", label=label)

    ax.axhline(0, color="gray", linewidth=0.8)
    ax.axvline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_xlabel("가동개시(감가상각개시) 시점 조정 (개월, +는 앞당김/-는 늦춤)")
    ax.set_ylabel("당기순이익 영향 (조원)")
    ax.set_title("건설중인자산 가동개시 시점 판단이 당기순이익에 미치는 영향")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    path = os.path.join(OUTPUT_DIR, "scenario_comparison.png")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"저장됨: {path}")


def main():
    cases = get_kam_cases()
    all_results = []
    for company, year, basis in cases:
        facts = load_case_facts(company, year, basis)
        results = run_scenario_set(facts)
        all_results.append(((company, year, basis), facts, results))

    write_summary_csv(all_results)
    plot_comparison(all_results)
    write_capitalization_scope_csv(cases)


if __name__ == "__main__":
    main()
