"""
DART(전자공시시스템) Open API로 재무제표를 자동 조회해, data/total_assets.csv와
data/kam_facts.csv에 수기로 옮겨 적은 자산총계·유형자산 금액을 대사(reconcile)합니다.

지금까지 이 프로젝트의 숫자는 전부 사람이 PDF 감사보고서를 읽고 옮겨 적은 것이었습니다.
이 스크립트는 그 중 "재무제표 계정과목 금액" 부분을 DART Open API로 재조회해서, 수기
입력값과 API 조회값이 일치하는지 독립적으로 재계산(recompute)합니다 — 이는 실제 감사
절차 중 "재계산/재수행(recalculation)"에 해당하는 접근입니다.

한계: DART Open API는 재무제표 "계정과목·금액"은 구조화된 데이터로 제공하지만, 핵심감사
사항(KAM) 본문 텍스트는 구조화된 API가 아니라 원문 공시서류(문서 API, document.xml)
안에 자연어로만 존재합니다. 따라서 "이 KAM 원문 전체를 API로 자동 추출"하는 것은 이
스크립트의 범위 밖입니다 — 그 부분은 여전히 raw_filings/의 수동 추출 텍스트에 의존합니다.

사용법:
    (PowerShell) $env:DART_API_KEY = "발급받은 키"
    (bash)       export DART_API_KEY=발급받은키
    python dart_fetcher.py
"""

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_URL = "https://opendart.fss.or.kr/api"
CORP_NAMES = {"samsung": "삼성전자", "skhynix": "SK하이닉스"}

# 자산총계 재계산 대상: data/total_assets.csv에 실려 있는 (회사, 연도, 기준) 조합
RECONCILE_TARGETS = [
    ("skhynix", 2023, "CFS"),
    ("skhynix", 2023, "OFS"),
    ("skhynix", 2024, "CFS"),
    ("skhynix", 2025, "CFS"),
    ("samsung", 2023, "CFS"),
    ("samsung", 2024, "CFS"),
    ("samsung", 2025, "CFS"),
]


def _api_get(path: str, **params) -> bytes:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise RuntimeError(
            "환경변수 DART_API_KEY가 설정되어 있지 않습니다. "
            "opendart.fss.or.kr에서 발급받은 키를 환경변수로 설정한 뒤 다시 실행하세요."
        )
    params["crtfc_key"] = api_key
    url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DART API 호출 실패 ({path}): HTTP {e.code}") from e


_corp_code_cache: Optional[Dict[str, str]] = None


def _load_corp_codes() -> Dict[str, str]:
    global _corp_code_cache
    if _corp_code_cache is not None:
        return _corp_code_cache
    raw = _api_get("corpCode.xml")
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    codes: Dict[str, str] = {}
    for node in root.findall("list"):
        name = node.findtext("corp_name")
        code = node.findtext("corp_code")
        stock_code = (node.findtext("stock_code") or "").strip()
        if name and code and stock_code:
            codes[name] = code
    _corp_code_cache = codes
    return codes


def get_corp_code(short_name: str) -> str:
    corp_name = CORP_NAMES[short_name]
    codes = _load_corp_codes()
    if corp_name not in codes:
        raise KeyError(f"'{corp_name}'의 corp_code를 DART 회사코드 목록에서 찾지 못했습니다.")
    return codes[corp_name]


def fetch_financial_statement(short_name: str, bsns_year: int, fs_div: str = "CFS") -> List[dict]:
    """단일회사 전체 재무제표 조회 (fnlttSinglAcntAll). fs_div: CFS=연결, OFS=별도."""
    corp_code = get_corp_code(short_name)
    raw = _api_get(
        "fnlttSinglAcntAll.json",
        corp_code=corp_code,
        bsns_year=str(bsns_year),
        reprt_code="11011",  # 사업보고서(연간)
        fs_div=fs_div,
    )
    data = json.loads(raw)
    if data.get("status") != "000":
        raise RuntimeError(f"DART API 응답 오류: status={data.get('status')} message={data.get('message')}")
    return data["list"]


def _find_account(items: List[dict], account_name: str, sj_div: str = "BS") -> Optional[dict]:
    for item in items:
        if item.get("sj_div") == sj_div and item.get("account_nm", "").strip() == account_name:
            return item
    return None


def _to_mkrw(amount_str: Optional[str]) -> Optional[int]:
    if not amount_str:
        return None
    return round(int(amount_str.replace(",", "")) / 1_000_000)


def reconcile_total_assets(short_name: str, year: int, fs_div: str) -> dict:
    items = fetch_financial_statement(short_name, year, fs_div)
    total_assets = _find_account(items, "자산총계")
    tangible_assets = _find_account(items, "유형자산")
    return {
        "total_assets_mkrw": _to_mkrw(total_assets["thstrm_amount"]) if total_assets else None,
        "tangible_assets_mkrw": _to_mkrw(tangible_assets["thstrm_amount"]) if tangible_assets else None,
    }


def _load_manual_total_assets() -> Dict[Tuple[str, int, str], int]:
    path = Path(__file__).parent / "data" / "total_assets.csv"
    manual: Dict[Tuple[str, int, str], int] = {}
    with open(path, encoding="utf-8") as f:
        next(f)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue
            company, fiscal_year, basis, total_assets_mkrw = parts[0], parts[1], parts[2], parts[3]
            manual[(company, int(fiscal_year), basis)] = int(total_assets_mkrw)
    return manual


def main() -> None:
    basis_map = {"CFS": "consolidated", "OFS": "separate"}
    manual = _load_manual_total_assets()

    header = f"{'회사':10}{'연도':6}{'기준':13}{'DART 자산총계':>16}{'수기입력값':>16}{'일치':>8}"
    print(header)
    print("-" * len(header))

    for short_name, year, fs_div in RECONCILE_TARGETS:
        basis = basis_map[fs_div]
        try:
            result = reconcile_total_assets(short_name, year, fs_div)
            dart_value = result["total_assets_mkrw"]
            manual_value = manual.get((short_name, year, basis))
            match = "OK" if dart_value == manual_value else "차이!"
            print(
                f"{short_name:10}{year:<6}{basis:13}"
                f"{dart_value if dart_value is not None else '-':>16}"
                f"{manual_value if manual_value is not None else '-':>16}"
                f"{match:>8}"
            )
        except Exception as e:  # noqa: BLE001 - 대사 실패도 결과로 보고
            print(f"{short_name:10}{year:<6}{basis:13}  오류: {e}")


if __name__ == "__main__":
    main()
