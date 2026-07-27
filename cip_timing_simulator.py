"""
건설중인자산(CIP) 감가상각 개시시점 판단이 손익에 미치는 영향 시뮬레이터
================================================================

이 프로그램은 삼성전자·SK하이닉스의 실제 사업보고서/감사보고서(DART 공시)에서
추출한 데이터를 바탕으로, 감사보고서 핵심감사사항(KAM)으로 지적된
"건설중인자산 → 유형자산 대체(가동개시) 시점 판단"이 몇 개월 앞당겨지거나
늦춰졌을 때 당해년도 감가상각비·매출원가·영업이익·당기순이익이 어떻게
달라지는지를 시나리오별로 계산합니다.

핵심 가정 (모두 조정 가능한 파라미터로 노출됨)
------------------------------------------------
1. 기준(baseline) 시나리오는 "해당 연도 중 평균적으로 7월 1일(연 6개월)에
   가동이 개시되었다"고 가정합니다. 실제 KAM 원문은 정확한 월별 시점을
   공시하지 않으므로, 이는 근사치입니다.
2. 감가상각 개시시점이 N개월 앞당겨지거나 늦춰지면, 해당 연도에 상각되는
   개월수가 (6+N)개월로 바뀌고, 이에 비례해 당해년도 감가상각비가
   증감한다고 가정합니다(정액법, 잔존가치 0 가정).
3. 대상 금액(population_at_risk)은 KAM에서 감사인이 "당기 중 사용가능
   상태에 도달했다고 판단하여 감가상각을 개시한 기계장치 금액"으로 명시한
   수치를 우선 사용합니다(SK하이닉스). 이 금액이 KAM 원문에 명시되지 않은
   경우(삼성전자)에는 재무제표 주석의 "기계장치 일반취득 및 자본적지출"
   금액(건설중인자산 대체분 포함)으로 근사합니다 — data/kam_facts.csv의
   population_source 컬럼에 근사 여부가 명시되어 있습니다.
4. 내용연수는 재무제표 주석에 공시된 "대표추정내용연수"를 사용합니다
   (기계장치: SK하이닉스 5~15년, 삼성전자 5년). 기본값은 두 회사 모두
   5년(반도체 장비의 통상적인 최단 내용연수)을 사용하되 파라미터로
   변경할 수 있습니다.
5. 감가상각비의 매출원가/판관비/개발비 배분비율은 주석에 공시된 실제
   비율(data/depreciation_split.csv)을 사용합니다. 삼성전자는 해당
   주석이 확인되지 않아 SK하이닉스 평균 비율을 기본값으로 사용하며,
   이 경우 결과에 근사치임을 표시합니다.
6. 법인세는 실효세율(effective tax rate)을 단순 적용합니다. 기본값은
   각 연도 사업보고서에서 확인한 실제 실효세율이며, 없는 경우 22%를
   기본값으로 사용합니다.

이 프로그램은 "정답"을 제시하는 것이 아니라, 감사인이 왜 이 판단을
핵심감사사항으로 지적했는지 — 즉 판단 하나가 재무제표에 미치는 영향의
크기(order of magnitude)를 체감하기 위한 학습용 시뮬레이션입니다.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

DEFAULT_EFFECTIVE_TAX_RATE = 0.22
DEFAULT_BASELINE_MONTHS = 6  # "연중 평균 7월 1일 가동개시" 가정
DEFAULT_COGS_RATIO_FALLBACK = 0.92  # 삼성전자용 SK하이닉스 평균 근사치
DEFAULT_SGA_RATIO_FALLBACK = 0.07
DEFAULT_RND_RATIO_FALLBACK = 0.01


@dataclass
class CaseFacts:
    company: str
    fiscal_year: int
    basis: str
    population_at_risk: float  # 백만원, 감가상각 개시 판단의 영향을 받는 자산 금액
    population_source: str
    useful_life_years: float
    cogs_ratio: float
    sga_ratio: float
    rnd_ratio: float
    total_depreciation_disclosed: float
    effective_tax_rate: float = DEFAULT_EFFECTIVE_TAX_RATE
    is_approximation: bool = False


@dataclass
class CapitalizationScopeResult:
    capitalized_borrowing_cost: float
    useful_life_years: float
    capitalized_case_current_year_expense: float
    expensed_case_current_year_expense: float
    delta_expense: float
    delta_net_income: float


@dataclass
class MultiYearRow:
    year_index: int  # 1 = KAM 해당연도, 2 = 그 다음해, ...
    baseline_depreciation: float
    scenario_depreciation: float
    delta_depreciation: float
    delta_net_income: float
    cumulative_delta_net_income: float


@dataclass
class MaterialityContext:
    total_assets: float
    population_at_risk: float
    population_pct_of_assets: float


@dataclass
class ScenarioResult:
    shift_months: int
    months_depreciated: int
    scenario_depreciation: float
    baseline_depreciation: float
    delta_depreciation: float
    delta_cogs: float
    delta_sga: float
    delta_rnd: float
    delta_operating_income: float
    delta_net_income: float


def _read_csv(filename: str) -> list[dict]:
    path = os.path.join(DATA_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_case_facts(company: str, fiscal_year: int, basis: str) -> CaseFacts:
    """kam_facts.csv와 depreciation_split.csv에서 해당 회사/연도/기준의
    사실관계를 읽어 CaseFacts로 조립합니다."""

    kam_rows = _read_csv("kam_facts.csv")
    split_rows = _read_csv("depreciation_split.csv")

    kam_row = next(
        (
            r
            for r in kam_rows
            if r["company"] == company
            and int(r["fiscal_year"]) == fiscal_year
            and r["basis"] == basis
        ),
        None,
    )
    if kam_row is None:
        raise ValueError(f"kam_facts.csv에 {company}/{fiscal_year}/{basis} 데이터가 없습니다.")

    if not kam_row["population_at_risk"]:
        raise ValueError(
            f"{company}/{fiscal_year}/{basis}: 이 연도는 감가상각개시시점이 KAM이 아니었거나 "
            f"공시된 금액이 없어 시뮬레이션 대상이 아닙니다. "
            f"(사유: {kam_row['population_source']})"
        )

    split_row = next(
        (
            r
            for r in split_rows
            if r["company"] == company
            and int(r["fiscal_year"]) == fiscal_year
            and r["basis"] == basis
        ),
        None,
    )

    is_approx = False
    if split_row and split_row["cogs_ratio"]:
        cogs_ratio = float(split_row["cogs_ratio"])
        sga_ratio = float(split_row["sga_ratio"])
        rnd_ratio = float(split_row["rnd_ratio"])
        total_dep = float(split_row["total_depreciation"])
    else:
        cogs_ratio = DEFAULT_COGS_RATIO_FALLBACK
        sga_ratio = DEFAULT_SGA_RATIO_FALLBACK
        rnd_ratio = DEFAULT_RND_RATIO_FALLBACK
        total_dep = float(split_row["total_depreciation"]) if split_row else 0.0
        is_approx = True

    if kam_row["population_source"].startswith("KAM 원문 명시") is False:
        is_approx = True

    return CaseFacts(
        company=company,
        fiscal_year=fiscal_year,
        basis=basis,
        population_at_risk=float(kam_row["population_at_risk"]),
        population_source=kam_row["population_source"],
        useful_life_years=float(kam_row["useful_life_representative"]),
        cogs_ratio=cogs_ratio,
        sga_ratio=sga_ratio,
        rnd_ratio=rnd_ratio,
        total_depreciation_disclosed=total_dep,
        is_approximation=is_approx,
    )


def load_capitalized_borrowing_cost(
    company: str, fiscal_year: int, basis: str
) -> Optional[float]:
    """data/capitalized_borrowing_cost.csv에서 해당 회사/연도/기준의 자본화된
    차입원가(백만원)를 조회합니다. 공시되지 않은 조합이면 None을 반환합니다."""
    rows = _read_csv("capitalized_borrowing_cost.csv")
    row = next(
        (
            r
            for r in rows
            if r["company"] == company
            and int(r["fiscal_year"]) == fiscal_year
            and r["basis"] == basis
        ),
        None,
    )
    return float(row["capitalized_borrowing_cost_mkrw"]) if row else None


def run_capitalization_scope_scenario(
    facts: CaseFacts,
    capitalized_borrowing_cost: float,
    months_depreciated: int = DEFAULT_BASELINE_MONTHS,
    useful_life_years: Optional[float] = None,
    effective_tax_rate: Optional[float] = None,
) -> CapitalizationScopeResult:
    """차입원가를 자본화(현재 회계처리)한 경우와, 만약 자본화 범위에서 제외하고
    발생 즉시 이자비용으로 비용화했다면 당해년도 손익이 어떻게 달라졌을지 비교합니다.

    - 자본화 시: 차입원가가 기계장치 취득원가에 포함되어 내용연수에 걸쳐
      감가상각되므로, 당해년도에는 (차입원가/내용연수)*(상각월수/12)만 비용화됩니다.
    - 비자본화 시: 차입원가 전액이 발생한 해에 이자비용(영업외비용)으로 즉시
      비용화됩니다.

    즉, 자본화 범위를 넓힐수록 같은 비용도 당기 손익에는 작게, 여러 해에
    걸쳐 나눠 반영된다는 점을 보여줍니다 — "감가상각 개시시점" 판단과는
    별개로 이익에 영향을 주는 또 하나의 회계적 판단 축입니다.
    """
    useful_life = useful_life_years or facts.useful_life_years
    tax_rate = effective_tax_rate if effective_tax_rate is not None else facts.effective_tax_rate

    capitalized_case_current_year_expense = (
        capitalized_borrowing_cost / useful_life * (months_depreciated / 12)
    )
    expensed_case_current_year_expense = capitalized_borrowing_cost

    delta_expense = expensed_case_current_year_expense - capitalized_case_current_year_expense
    delta_net_income = -delta_expense * (1 - tax_rate)

    return CapitalizationScopeResult(
        capitalized_borrowing_cost=capitalized_borrowing_cost,
        useful_life_years=useful_life,
        capitalized_case_current_year_expense=capitalized_case_current_year_expense,
        expensed_case_current_year_expense=expensed_case_current_year_expense,
        delta_expense=delta_expense,
        delta_net_income=delta_net_income,
    )


def _build_depreciation_schedule(
    population_at_risk: float, useful_life_years: float, months_in_year1: int
) -> list[tuple[int, float]]:
    """1년차에 months_in_year1개월치를 상각하고, 그 뒤로는 매년 12개월씩
    상각해 총 useful_life_years*12개월치(=population_at_risk 전액)를 다
    상각할 때까지의 연도별 (연차, 상각액) 목록을 반환합니다."""
    monthly_dep = population_at_risk / (useful_life_years * 12)
    remaining_months = round(useful_life_years * 12)
    schedule: list[tuple[int, float]] = []
    year = 1
    months_this_year = max(0, min(12, months_in_year1))
    while remaining_months > 0:
        months_this_year = min(months_this_year, remaining_months)
        schedule.append((year, monthly_dep * months_this_year))
        remaining_months -= months_this_year
        year += 1
        months_this_year = 12
    return schedule


def run_multi_year_comparison(
    facts: CaseFacts,
    shift_months: int,
    baseline_months: int = DEFAULT_BASELINE_MONTHS,
    useful_life_years: Optional[float] = None,
    effective_tax_rate: Optional[float] = None,
) -> list[MultiYearRow]:
    """가동개시 시점을 shift_months만큼 조정했을 때, KAM 해당연도부터
    자산이 완전히 상각될 때까지 연도별 손익 영향이 어떻게 나타나는지 보여줍니다.

    핵심 포인트: 총 상각액(population_at_risk)은 시점을 언제로 잡든 동일하므로,
    연도별 누적 Δ당기순이익은 결국 0으로 수렴합니다 — "시점" 판단은 이익을
    만들어내는 게 아니라 여러 해에 걸쳐 이익을 이동(재배치)시킬 뿐이라는 뜻입니다.
    """
    useful_life = useful_life_years or facts.useful_life_years
    tax_rate = effective_tax_rate if effective_tax_rate is not None else facts.effective_tax_rate

    scenario_months_year1 = max(0, min(12, baseline_months + shift_months))
    baseline_schedule = dict(
        _build_depreciation_schedule(facts.population_at_risk, useful_life, baseline_months)
    )
    scenario_schedule = dict(
        _build_depreciation_schedule(facts.population_at_risk, useful_life, scenario_months_year1)
    )

    years = sorted(set(baseline_schedule) | set(scenario_schedule))
    rows: list[MultiYearRow] = []
    cumulative = 0.0
    for year in years:
        baseline_amt = baseline_schedule.get(year, 0.0)
        scenario_amt = scenario_schedule.get(year, 0.0)
        delta_dep = scenario_amt - baseline_amt
        delta_ni = -delta_dep * (1 - tax_rate)
        cumulative += delta_ni
        rows.append(
            MultiYearRow(
                year_index=year,
                baseline_depreciation=baseline_amt,
                scenario_depreciation=scenario_amt,
                delta_depreciation=delta_dep,
                delta_net_income=delta_ni,
                cumulative_delta_net_income=cumulative,
            )
        )
    return rows


def load_total_assets(company: str, fiscal_year: int, basis: str) -> Optional[float]:
    """data/total_assets.csv에서 해당 회사/연도/기준의 자산총계(백만원)를
    조회합니다. 공시되지 않은 조합이면 None을 반환합니다."""
    rows = _read_csv("total_assets.csv")
    row = next(
        (
            r
            for r in rows
            if r["company"] == company
            and int(r["fiscal_year"]) == fiscal_year
            and r["basis"] == basis
        ),
        None,
    )
    return float(row["total_assets_mkrw"]) if row else None


def compute_materiality_context(facts: CaseFacts, total_assets: float) -> MaterialityContext:
    """KAM 대상 금액(population_at_risk)이 회사 자산총계 대비 몇 %인지 계산합니다.

    주의: 이건 감사인이 실제로 사용한 중요성금액(materiality)이 아닙니다 — 그
    수치는 감사보고서에 공시되지 않습니다. 여기서는 "이 판단이 재무제표 전체
    규모에 비해 얼마나 큰가"를 가늠하기 위한 근사 지표로 자산총계 대비 비율을
    씁니다(참고로 실무에서 흔히 쓰이는 중요성 기준 중 하나가 총자산의
    0.5~2% 수준입니다).
    """
    return MaterialityContext(
        total_assets=total_assets,
        population_at_risk=facts.population_at_risk,
        population_pct_of_assets=facts.population_at_risk / total_assets * 100,
    )


def run_scenario(
    facts: CaseFacts,
    shift_months: int,
    baseline_months: int = DEFAULT_BASELINE_MONTHS,
    useful_life_years: Optional[float] = None,
    effective_tax_rate: Optional[float] = None,
) -> ScenarioResult:
    """감가상각 개시시점을 shift_months만큼 앞당기거나(+) 늦췄을 때(-)의
    당해년도 손익 영향을 계산합니다.

    shift_months > 0: 더 일찍 가동개시(더 이르게 판단) -> 당해년도 상각월수 증가
    shift_months < 0: 더 늦게 가동개시(더 보수적으로 판단) -> 당해년도 상각월수 감소
    """
    useful_life = useful_life_years or facts.useful_life_years
    tax_rate = effective_tax_rate if effective_tax_rate is not None else facts.effective_tax_rate

    annual_full_year_depreciation = facts.population_at_risk / useful_life

    months_depreciated = max(0, min(12, baseline_months + shift_months))
    baseline_depreciation = annual_full_year_depreciation * (baseline_months / 12)
    scenario_depreciation = annual_full_year_depreciation * (months_depreciated / 12)
    delta_depreciation = scenario_depreciation - baseline_depreciation

    delta_cogs = delta_depreciation * facts.cogs_ratio
    delta_sga = delta_depreciation * facts.sga_ratio
    delta_rnd = delta_depreciation * facts.rnd_ratio

    # 감가상각비 증가 -> 매출원가/판관비/개발비 증가 -> 영업이익 감소(부호 반대)
    delta_operating_income = -delta_depreciation
    delta_net_income = delta_operating_income * (1 - tax_rate)

    return ScenarioResult(
        shift_months=shift_months,
        months_depreciated=months_depreciated,
        scenario_depreciation=scenario_depreciation,
        baseline_depreciation=baseline_depreciation,
        delta_depreciation=delta_depreciation,
        delta_cogs=delta_cogs,
        delta_sga=delta_sga,
        delta_rnd=delta_rnd,
        delta_operating_income=delta_operating_income,
        delta_net_income=delta_net_income,
    )


def run_scenario_set(
    facts: CaseFacts,
    shift_range_months: list[int] = None,
    **kwargs,
) -> list[ScenarioResult]:
    shifts = shift_range_months or [-6, -3, -1, 0, 1, 3, 6]
    return [run_scenario(facts, s, **kwargs) for s in shifts]


if __name__ == "__main__":
    for company, year, basis in [
        ("skhynix", 2023, "consolidated"),
        ("skhynix", 2025, "consolidated"),
        ("samsung", 2025, "consolidated"),
    ]:
        facts = load_case_facts(company, year, basis)
        print(f"\n=== {company} FY{year} ({basis}) ===")
        print(f"대상 금액(population_at_risk): {facts.population_at_risk:,.0f} 백만원")
        print(f"출처: {facts.population_source}")
        print(f"내용연수 가정: {facts.useful_life_years}년 | 근사치 여부: {facts.is_approximation}")
        for r in run_scenario_set(facts):
            print(
                f"  shift={r.shift_months:+d}개월 | 상각월수={r.months_depreciated:2d} | "
                f"Δ감가상각비={r.delta_depreciation:+,.0f} | Δ영업이익={r.delta_operating_income:+,.0f} | "
                f"Δ당기순이익={r.delta_net_income:+,.0f} (백만원)"
            )

        cap_cost = load_capitalized_borrowing_cost(company, year, basis)
        if cap_cost is not None:
            cap_result = run_capitalization_scope_scenario(facts, cap_cost)
            print(
                f"  [자본화 범위] 자본화된 차입원가={cap_cost:,.0f} | "
                f"자본화 시 당기비용={cap_result.capitalized_case_current_year_expense:,.0f} | "
                f"비자본화(즉시 비용화) 시={cap_result.expensed_case_current_year_expense:,.0f} | "
                f"Δ당기순이익={cap_result.delta_net_income:+,.0f} (백만원)"
            )

        print("  [다년도 누적] 6개월 앞당긴 경우, 연차별 Δ당기순이익 (백만원):")
        for r in run_multi_year_comparison(facts, shift_months=6):
            print(
                f"    {r.year_index}년차 | Δ당기순이익={r.delta_net_income:+,.0f} | "
                f"누적={r.cumulative_delta_net_income:+,.0f}"
            )

        total_assets = load_total_assets(company, year, basis)
        if total_assets is not None:
            ctx = compute_materiality_context(facts, total_assets)
            print(
                f"  [중요성 근사] 자산총계={total_assets:,.0f} 대비 "
                f"대상금액 비중={ctx.population_pct_of_assets:.2f}% (백만원)"
            )
