"""열린국회정보 OpenAPI에서 현직 국회의원 인적사항을 받아 일일 스냅샷(jsonl)으로 저장한다.

사용: python pipeline/python/collect_assembly.py [--dry-run]
환경변수: ASSEMBLY_API_KEY
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

from assembly_apis import ASSEMBLY_APIS

ENDPOINT = ASSEMBLY_APIS["members"]  # 국회의원 인적사항
PAGE_SIZE = 100
OUT_DIR = pathlib.Path(__file__).parents[1] / "out"

FIELDS = {
    "MONA_CD": "member_code",
    "HG_NM": "name",
    "HJ_NM": "name_hanja",
    "POLY_NM": "party",
    "ORIG_NM": "district",
    "ELECT_GBN_NM": "election_type",  # 지역구 / 비례대표
    "REELE_GBN_NM": "reelection",
    "UNITS": "units",
    "CMITS": "committees",
    "TEL_NO": "tel",
    "E_MAIL": "email",
    "HOMEPAGE": "homepage",
}


def fetch_page(key: str, page: int) -> list[dict]:
    params = {"Type": "json", "pIndex": page, "pSize": PAGE_SIZE}
    if key:
        params["KEY"] = key
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{ENDPOINT}?{query}", headers={"User-Agent": "offorby-collector"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if "nwvrqwxyaytdsfvhu" not in body:
        # 데이터 끝이면 INFO-200, 그 외는 오류
        result = body.get("RESULT", {})
        if result.get("CODE") == "INFO-200":
            return []
        raise RuntimeError(f"API 오류: {result}")
    return body["nwvrqwxyaytdsfvhu"][1]["row"]


def collect(key: str) -> list[dict]:
    rows, page = [], 1
    while True:
        batch = fetch_page(key, page)
        rows.extend({dst: r.get(src) for src, dst in FIELDS.items()} for r in batch)
        if len(batch) < PAGE_SIZE:
            return rows
        page += 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 요약만 출력")
    args = parser.parse_args()

    # 키 없이도 동작하지만, 호출 제한을 피하려면 발급 키를 ASSEMBLY_API_KEY로 설정 권장
    key = os.environ.get("ASSEMBLY_API_KEY", "")
    if not key:
        print("경고: ASSEMBLY_API_KEY 미설정, 키 없이 호출합니다.", file=sys.stderr)

    rows = collect(key)
    # Actions(UTC)에서도 한국 날짜가 찍히도록 KST 기준
    snapshot_date = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    district = sum(1 for r in rows if r["election_type"] == "지역구")
    print(f"{snapshot_date}: 의원 {len(rows)}명 (지역구 {district}, 비례 {len(rows) - district})")

    if args.dry_run:
        return
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"assembly_{snapshot_date.replace('-', '')}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({**r, "snapshot_date": snapshot_date}, ensure_ascii=False) + "\n")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
