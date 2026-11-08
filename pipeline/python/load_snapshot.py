"""수집 스냅샷(jsonl)을 BigQuery 스테이징 테이블에 적재한다(기본은 덮어씀, --append면 날짜별로 쌓음).

사용: python pipeline/python/load_snapshot.py <jsonl 파일> --table stg_assembly [--append] [--approve]
--approve 없이 실행하면 행 수와 대상 테이블만 보여주고 적재하지 않는다.
환경변수: GCP_PROJECT, BQ_DATASET(기본 offorby), BQ_LOCATION(기본 asia-northeast3)
"""
import argparse
import json
import os
import pathlib
import sys

from google.cloud import bigquery


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl_file", type=pathlib.Path)
    parser.add_argument("--table", required=True, help="대상 스테이징 테이블명 (예: stg_assembly)")
    parser.add_argument("--append", action="store_true", help="덮어쓰지 않고 추가(--keys 조합이 같은 기존 행은 먼저 지움)")
    parser.add_argument("--keys", default="snapshot_date",
                        help="--append 때 지울 범위를 정하는 컬럼(쉼표 구분). 파일에 있는 값 조합만 지운다. 기본 snapshot_date")
    parser.add_argument("--approve", action="store_true", help="실제로 적재")
    args = parser.parse_args()

    project = os.environ.get("GCP_PROJECT")
    dataset = os.environ.get("BQ_DATASET", "offorby")
    location = os.environ.get("BQ_LOCATION", "asia-northeast3")
    if not project:
        sys.exit("GCP_PROJECT 환경변수가 필요합니다.")

    n_rows = sum(1 for line in args.jsonl_file.open(encoding="utf-8") if line.strip())
    table_id = f"{project}.{dataset}.{args.table}"
    mode = "WRITE_APPEND" if args.append else "WRITE_TRUNCATE"
    print(f"{args.jsonl_file} ({n_rows}행) → {table_id} ({mode})")

    if not args.approve:
        print("확인만 했습니다. 적재하려면 --approve")
        return
    client = bigquery.Client(project=project, location=location)
    if args.append:
        # 같은 날 재실행해도 중복이 쌓이지 않도록, 파일에 들어 있는 키 조합(기본 snapshot_date)의 기존 행을 먼저 지운다.
        # 소스별로 파일이 나뉜 테이블(mentions_daily 등)은 --keys snapshot_date,source 로 다른 소스 행을 보존한다.
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
        combos = sorted({tuple(str(json.loads(l)[k]) for k in keys)
                         for l in args.jsonl_file.open(encoding="utf-8") if l.strip()})
        # snapshot_date는 DATE, 나머지는 STRING으로 비교(TO_JSON_STRING 대신 단순 CAST)
        conds, params = [], []
        for i, combo in enumerate(combos):
            parts = []
            for k, v in zip(keys, combo):
                name = f"p{i}_{k}"
                typ = "DATE" if k == "snapshot_date" else "STRING"
                parts.append(f"{k} = @{name}")
                params.append(bigquery.ScalarQueryParameter(name, typ, v))
            conds.append("(" + " AND ".join(parts) + ")")
        client.query(
            f"DELETE FROM `{table_id}` WHERE " + " OR ".join(conds),
            job_config=bigquery.QueryJobConfig(query_parameters=params),
        ).result()
        print(f"기존 행 삭제: {keys} = {combos}")
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=getattr(bigquery.WriteDisposition, mode),
    )
    with args.jsonl_file.open("rb") as f:
        job = client.load_table_from_file(f, table_id, job_config=config)
    job.result()
    print(f"완료: {client.get_table(table_id).num_rows}행 적재")


if __name__ == "__main__":
    main()
