# 건설중인자산 감가상각개시시점 손익영향 시뮬레이터

삼성전자·SK하이닉스 실제 사업보고서/감사보고서(DART)에서 추출한 데이터를 바탕으로,
핵심감사사항(KAM)으로 지적된 "건설중인자산 → 유형자산 대체(가동개시) 시점 판단"이
몇 개월 앞당겨지거나 늦춰졌을 때 손익에 미치는 영향을 계산하는 프로그램입니다.

## 폴더 구조

```
program/
  data/
    kam_facts.csv                     # 회사·연도별 KAM 대상 금액, 내용연수 가정, 근사 여부
    depreciation_split.csv            # 감가상각비의 매출원가/판관비/개발비 배분 비율
    cip_dataset.csv                   # 건설중인자산 잔액·감가상각비·자본화차입원가 원자료
    capitalized_borrowing_cost.csv    # 회사·연도·기준별 자본화된 차입원가·이자율
    goodwill_impairment_samsung.csv   # 삼성전자 보고부문(CGU)별 영업권 손상차손 (FY2023~2025)
    goodwill_impairment_skhynix.csv   # SK하이닉스 CGU(Solidigm 포함)별 영업권 현황
    board_resolutions_skhynix.csv     # SK하이닉스 신규 Fab 등 시설투자 이사회결의 내역
  cip_timing_simulator.py    # 핵심 계산 로직 (라이브러리)
  run_scenarios.py           # 전체 KAM 사례에 대해 시나리오 실행 + CSV/차트 출력
  output/
    scenario_summary.csv               # 시점조정 시나리오별 손익 영향 전체 표
    scenario_comparison.png            # 회사·연도별 비교 차트
    capitalization_scope_summary.csv   # 자본화 차입원가 자본화 vs 즉시비용화 비교
```

## 실행 방법

```bash
cd program
python3 run_scenarios.py
```

`output/` 폴더에 `scenario_summary.csv`와 `scenario_comparison.png`가 생성됩니다.

개별 사례를 직접 다뤄보고 싶다면:

```python
from cip_timing_simulator import load_case_facts, run_scenario, run_scenario_set

facts = load_case_facts("skhynix", 2025, "consolidated")
result = run_scenario(facts, shift_months=3)   # 3개월 앞당긴 경우
print(result.delta_net_income)                 # 당기순이익 영향 (백만원)

# 여러 시나리오를 한 번에
for r in run_scenario_set(facts, shift_range_months=[-6, -3, 0, 3, 6]):
    print(r.shift_months, r.delta_net_income)
```

자본화 원가범위(자본화된 차입원가) 시나리오:

```python
from cip_timing_simulator import load_case_facts, load_capitalized_borrowing_cost, run_capitalization_scope_scenario

facts = load_case_facts("skhynix", 2025, "consolidated")
cap_cost = load_capitalized_borrowing_cost("skhynix", 2025, "consolidated")
r = run_capitalization_scope_scenario(facts, cap_cost)
print(r.delta_net_income)   # 차입원가를 자본화하지 않고 즉시 비용화했다면 당해년도 순이익이 얼마나 줄었을지
```

## 이 프로그램이 계산하는 것 / 계산하지 않는 것

계산하는 것: "만약 감사인이 문제 삼은 그 판단(가동가능 시점)이 실제보다 N개월
빨랐거나 늦었다면, 그 해 감가상각비·영업이익·당기순이익이 얼마나 달라졌을까"를
정액법 가정 하에 근사적으로 계산합니다.

계산하지 않는 것: 실제로 그 판단이 틀렸다는 뜻은 아닙니다. 감사인은 감사절차를
통해 회사의 판단이 적절하다는 결론(적정의견)을 내렸습니다. 이 시뮬레이션은
"판단 하나가 재무제표에 미치는 영향의 크기"를 체감하기 위한 학습 도구이지,
실제 판단의 오류를 지적하는 것이 아닙니다.

## 핵심 가정 (README 상단 docstring에 상세 설명, `cip_timing_simulator.py` 참고)

- 기준 시나리오: 연중 평균 7월 1일(6개월) 가동개시 가정
- 대상 금액: SK하이닉스는 KAM 원문에 명시된 실제 금액, 삼성전자는 KAM에 정확한
  금액이 공시되지 않아 재무제표 주석의 기계장치 취득액(건설중인자산 대체분 포함)
  으로 근사 — `kam_facts.csv`의 `population_source` 컬럼에 명시
- 내용연수: 주석 공시 대표추정내용연수 사용 (기본값 5년, 조정 가능)
- 법인세 실효세율: 기본 22% (조정 가능)

## 결과 요약 (2026-07-27 실행 기준)

| 사례 | 대상금액(백만원) | ±6개월 이동 시 당기순이익 영향 |
|---|---|---|
| SK하이닉스 FY2023(연결) | 4,940,500 | 약 ∓3,850억원 |
| SK하이닉스 FY2025(연결) | 17,618,705 | 약 ∓1조3,740억원 |
| 삼성전자 FY2024(연결, 근사) | 40,219,596 | 약 ∓3조1,300억원 |
| 삼성전자 FY2025(연결, 근사) | 38,773,884 | 약 ∓3조240억원 |

가동개시 판단이 ±6개월만 달라져도 조 단위의 당기순이익 차이가 발생할 수 있다는
점이, 이 이슈가 왜 핵심감사사항으로 지정되는지를 숫자로 보여줍니다.

## 자본화 원가범위 시나리오 (`output/capitalization_scope_summary.csv`)

감가상각 "개시시점" 판단과는 별개로, 애초에 취득원가에 무엇을 자본화할지도
경영진 판단 영역입니다. 여기서는 자본화된 차입원가(이자비용)를 (a) 실제처럼
자본화해 내용연수에 걸쳐 감가상각하는 경우와 (b) 자본화하지 않고 발생 즉시
이자비용으로 전액 비용화하는 경우를 비교합니다.

| 사례 | 자본화된 차입원가(백만원) | 비자본화 시 당기순이익 영향 |
|---|---|---|
| SK하이닉스 FY2023(연결) | 136,622 | 약 -959억원 |
| SK하이닉스 FY2025(연결) | 249,760 | 약 -1,753억원 |
| 삼성전자 FY2024(연결) | 515,824 | 약 -3,621억원 |
| 삼성전자 FY2025(연결) | 557,852 | 약 -3,916억원 |

자본화(현재 실제 회계처리)는 같은 비용을 5년에 걸쳐 조금씩만 당기손익에
반영하는 반면, 비자본화는 전액을 당해년도에 즉시 비용화합니다 — "개시시점"
뿐 아니라 "자본화 범위" 판단 역시 당기 이익 규모를 좌우하는 별도의 회계적
레버라는 것을 보여줍니다. 시운전비용 등 이자비용 외 항목은 공시 자료에서
확인되지 않아 이번 시나리오는 자본화된 차입원가로 한정했습니다.

## 다음 단계 (추가 확보 예정 데이터)

- 손상차손 인식 세부 내역(금액·CGU별) → 완료(일부). `data/goodwill_impairment_samsung.csv`,
  `data/goodwill_impairment_skhynix.csv`에 영업권(CGU/보고부문별) 손상차손 반영 —
  삼성전자는 FY2025에 DX·DS·Harman 3개 부문에서 총 2,485억원 손상 최초 인식,
  SK하이닉스는 Solidigm CGU 영업권이 애초에 0원이라 손상 자체가 발생한 적 없음.
  단, 유형자산(반도체 설비) 자체의 CGU별 손상 세부내역은 미확보(총액만 MD&A에 공시).
- ~~삼성전자 연결 기준 자본화 차입원가·이자율, 감가상각비 기능별 배분 비율~~ → 완료.
- ~~자본화 대상 원가범위(이자비용 외 시운전비용 등) 조정 시나리오~~ → 완료(이자비용
  기준). `run_capitalization_scope_scenario()` 및 위 표 참고.
- 이사회 의결 시점(신규 Fab 등 시설투자 결정일)과 KAM/재무데이터 시점 대조 → 완료(일부).
  `data/board_resolutions_skhynix.csv`에 SK하이닉스 신규시설투자 이사회결의 내역 반영.
  단, 착공 시점 공시와 KAM의 "감가상각 개시(가동가능시점)" 금액은 집계 단위가 달라
  1:1 매칭은 불가능하다는 한계 확인. 삼성전자는 이런 유형의 공시 자체가 없음.
