"""승인된 SQL 파일을 BigQuery에 실행한다. 모든 DDL/DML은 이 스크립트로만 실행한다.

사용: python pipeline/python/apply_sql.py <sql 파일> [--approve]
--approve 없이 실행하면 SQL과 예상 처리량(dry run)만 보여주고 실행하지 않는다.
Claude Code에서는 .claude/settings.json에 의해 실행 전 항상 사용자 승인을 요청한다.
환경변수: GCP_PROJECT, BQ_DATASET (SQL 안의 ${project}, ${dataset} 치환), BQ_LOCATION(기본 asia-northeast3)
"""
import argparse
import os
import pathlib
import string
import sys

from google.cloud import bigquery


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_file", type=pathlib.Path)
    parser.add_argument("--approve", action="store_true", help="실제로 실행")
    args = parser.parse_args()

    project = os.environ.get("GCP_PROJECT")
    dataset = os.environ.get("BQ_DATASET", "offorby")
    location = os.environ.get("BQ_LOCATION", "asia-northeast3")
    if not project:
        sys.exit("GCP_PROJECT 환경변수가 필요합니다.")

    sql = string.Template(args.sql_file.read_text(encoding="utf-8")).substitute(project=project, dataset=dataset)
    print(f"--- {args.sql_file} ---\n{sql}\n")

    client = bigquery.Client(project=project, location=location)
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    print(f"예상 처리량: {dry.total_bytes_processed / 1e6:.2f} MB")

    if not args.approve:
        print("dry run만 수행했습니다. 실행하려면 --approve")
        return
    job = client.query(sql)
    job.result()
    print(f"완료: {job.statement_type}, 영향 행 {job.num_dml_affected_rows}")


if __name__ == "__main__":
    main()
