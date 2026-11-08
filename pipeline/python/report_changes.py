"""오늘 MERGE로 생긴 변경(국회의원 신규·변경·퇴임, 대통령 교체·보류)을 요약해 출력한다. 변경이 없으면 아무것도 출력하지 않는다.

사용: python pipeline/python/report_changes.py [--date YYYY-MM-DD]
GitHub Actions에서 출력이 있으면 Issue를 만든다. 읽기만 하며 DB를 바꾸지 않는다.
환경변수: GCP_PROJECT, BQ_DATASET(기본 offorby), BQ_LOCATION(기본 asia-northeast3)
"""
import argparse
import datetime as dt
import os
import sys

from google.cloud import bigquery

SQL = """
WITH opened AS (
  SELECT member_code, name, party, district FROM `{t}` WHERE valid_from = @d
),
closed AS (
  SELECT member_code, name, party, district FROM `{t}` WHERE valid_to = DATE_SUB(@d, INTERVAL 1 DAY)
)
SELECT
  COALESCE(o.member_code, c.member_code) AS member_code,
  COALESCE(o.name, c.name) AS name,
  CASE WHEN c.member_code IS NULL THEN '신규'
       WHEN o.member_code IS NULL THEN '퇴임'
       ELSE '변경' END AS kind,
  c.party AS old_party, o.party AS new_party,
  c.district AS old_district, o.district AS new_district
FROM opened o FULL OUTER JOIN closed c USING (member_code)
ORDER BY kind, name
"""

PRESIDENT_SQL = """
WITH opened AS (
  SELECT position, name, verified FROM `{t}` WHERE valid_from = @d
),
closed AS (
  SELECT position, name FROM `{t}` WHERE valid_to = DATE_SUB(@d, INTERVAL 1 DAY)
)
SELECT COALESCE(o.position, c.position) AS position, c.name AS old_name, o.name AS new_name, o.verified,
       c.position IS NOT NULL AS had_old, o.position IS NOT NULL AS has_new
FROM opened o FULL OUTER JOIN closed c USING (position)
ORDER BY position
"""

# 스냅샷 이름이 현재 행과 다른데 반영되지 않은 직위 = 보류(누리집 미확인, 연속 수집 3일 미만)
HELD_SQL = """
SELECT s.position, c.name AS old_name, s.name AS new_name
FROM `{stg}` s JOIN `{t}` c ON c.is_current AND c.position = s.position
WHERE s.snapshot_date = @d AND c.name IS DISTINCT FROM s.name
ORDER BY s.position
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    kst_today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    parser.add_argument("--date", default=kst_today)
    args = parser.parse_args()

    project = os.environ.get("GCP_PROJECT")
    dataset = os.environ.get("BQ_DATASET", "offorby")
    location = os.environ.get("BQ_LOCATION", "asia-northeast3")
    if not project:
        sys.exit("GCP_PROJECT 환경변수가 필요합니다.")

    client = bigquery.Client(project=project, location=location)
    table = f"{project}.{dataset}.members"
    # 첫 적재일(전원 신규)은 보고하지 않는다
    first = list(client.query(f"SELECT MIN(valid_from) d FROM `{table}`").result())[0].d
    if first is None or first.isoformat() == args.date:
        return

    job = client.query(
        SQL.format(t=table),
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("d", "DATE", args.date)]
        ),
    )
    rows = list(job.result())
    if rows:
        print(f"## {args.date} 국회의원 변경 {len(rows)}건\n")
        print("| 구분 | 이름 | 정당 | 선거구 |\n|---|---|---|---|")
        for r in rows:
            party = r.new_party if r.kind == "신규" else (r.old_party if r.kind == "퇴임" else f"{r.old_party} → {r.new_party}")
            district = r.new_district if r.kind == "신규" else (r.old_district if r.kind == "퇴임" else f"{r.old_district} → {r.new_district}")
            print(f"| {r.kind} | {r.name} | {party} | {district} |")
        print()

    report_president(client, f"{project}.{dataset}", args.date)


def report_president(client: bigquery.Client, prefix: str, date: str) -> None:
    table, stg = f"{prefix}.president", f"{prefix}.stg_president"
    params = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("d", "DATE", date)])
    first = list(client.query(f"SELECT MIN(valid_from) d FROM `{table}`").result())[0].d
    changed = [] if first is None or first.isoformat() == date else list(
        client.query(PRESIDENT_SQL.format(t=table), job_config=params).result())
    held = list(client.query(HELD_SQL.format(t=table, stg=stg), job_config=params).result())
    if changed:
        print(f"## {date} 국무위원 변경 {len(changed)}건\n")
        print("| 직위 | 이전 | 현재 | 누리집 확인 |\n|---|---|---|---|")
        for r in changed:
            # 이름 NULL은 공석. 직위 자체가 없으면 신설/폐지
            old = (r.old_name or "공석") if r.had_old else "(신설)"
            new = (r.new_name or "공석") if r.has_new else "(폐지)"
            print(f"| {r.position} | {old} | {new} | {'확인' if r.verified else '미확인'} |")
        print()
    if held:
        print(f"## {date} 국무위원 반영 보류 {len(held)}건\n")
        print("위키 표의 이름이 바뀌었으나 대통령실 누리집에서 확인되지 않아 보류 중입니다. 3일 연속 같은 값이면 자동 반영됩니다.\n")
        print("| 직위 | 현재 반영 | 수집값 |\n|---|---|---|")
        for r in held:
            print(f"| {r.position} | {r.old_name or '공석'} | {r.new_name or '공석'} |")
        print()


if __name__ == "__main__":
    main()
