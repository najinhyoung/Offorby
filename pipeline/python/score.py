"""sentiment_daily(최근 28일)로 인물별 100점 점수·10단계 등급을 계산해 일일 스냅샷(jsonl)으로 저장한다. 계약: docs/stage3_spec.md

방법(v1, 공개 설명은 docs/methodology.md):
  소스별 순감성 NET_s = clamp( Σ_d w_d·(n_pos−n_neg)·f_d / (Σ_d w_d·n_d + PRIOR_K), −1, 1 )
    n_d = n_pos+n_neu+n_neg(대상 관련 건), f_d = clamp(intensity_avg,1,3)/2(강도), w_d = 0.5^((D−d)/HALF_LIFE)
    PRIOR_K가 분모에 더해져 표본이 적을수록 0(=50점)으로 수축.
  net = 소스 가중 평균(글이 있는 소스만, 가중치 재정규화) → score = 50 + 50·net → grade = clamp(10 − floor(score/10), 1, 10)
  n_samples(가중 없는 건수) < MIN_SAMPLES 이면 score·grade NULL(데이터 부족). 대상 전원(v_collect_targets)에 대해 행을 낸다.

LLM 호출 없음(CLAUDE.md 규칙 3). 출력 pipeline/out/scores_YYYYMMDD.jsonl → scores 테이블(load_snapshot.py --append, 키 snapshot_date).
사용: python pipeline/python/score.py [--date YYYY-MM-DD] [--dry-run] [--top 20]
환경변수: GCP_PROJECT, BQ_DATASET(기본 offorby), BQ_LOCATION(기본 asia-northeast3)
"""
import argparse
import datetime as dt
import json
import math
import os
import pathlib
import sys
from collections import defaultdict

from google.cloud import bigquery

METHOD_VERSION = "v1"
WINDOW_DAYS = 28
HALF_LIFE_DAYS = 14
PRIOR_K = 20
MIN_SAMPLES = 10
SOURCE_WEIGHT = {"gnews": 0.5, "youtube": 0.3, "dc": 0.2}

KST = dt.timezone(dt.timedelta(hours=9))
OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "out"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def grade_of(score: float) -> int:
    return int(clamp(10 - math.floor(score / 10), 1, 10))


def fetch(client: bigquery.Client, project: str, dataset: str, day: dt.date) -> tuple[list[dict], list[dict]]:
    """(대상 전원, 창 안 sentiment_daily 행)."""
    targets = [dict(r) for r in client.query(
        f"SELECT person_id, name, role FROM `{project}.{dataset}.v_collect_targets` ORDER BY sample_rank").result()]
    rows = [dict(r) for r in client.query(
        f"SELECT snapshot_date, person_id, source, n_pos, n_neu, n_neg, intensity_avg "
        f"FROM `{project}.{dataset}.sentiment_daily` "
        f"WHERE snapshot_date BETWEEN @start AND @end",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", day - dt.timedelta(days=WINDOW_DAYS - 1)),
            bigquery.ScalarQueryParameter("end", "DATE", day),
        ])).result()]
    return targets, rows


def score_person(rows: list[dict], day: dt.date) -> dict:
    """한 인물의 sentiment_daily 행들 → {score, grade, n_samples, n_eff, components}."""
    acc: dict[str, dict] = defaultdict(lambda: {"num": 0.0, "n_eff": 0.0, "n": 0})
    for r in rows:
        n = (r["n_pos"] or 0) + (r["n_neu"] or 0) + (r["n_neg"] or 0)
        if n == 0:
            continue
        age = (day - r["snapshot_date"]).days
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        f = clamp(r["intensity_avg"], 1, 3) / 2 if r["intensity_avg"] is not None else 1.0
        a = acc[r["source"]]
        a["num"] += w * ((r["n_pos"] or 0) - (r["n_neg"] or 0)) * f
        a["n_eff"] += w * n
        a["n"] += n

    sources = {}
    for s, a in acc.items():
        if a["n_eff"] <= 0:
            continue
        sources[s] = {
            "net": round(clamp(a["num"] / (a["n_eff"] + PRIOR_K), -1, 1), 4),
            "n_eff": round(a["n_eff"], 2),
            "n": a["n"],
            "weight": SOURCE_WEIGHT.get(s, 0.0),
        }
    n_samples = sum(v["n"] for v in sources.values())
    n_eff = round(sum(v["n_eff"] for v in sources.values()), 2)
    wsum = sum(v["weight"] for v in sources.values())
    components = {
        "sources": sources,
        "window_days": WINDOW_DAYS, "half_life_days": HALF_LIFE_DAYS, "prior_k": PRIOR_K, "min_samples": MIN_SAMPLES,
    }
    if n_samples < MIN_SAMPLES or wsum <= 0:
        return {"score": None, "grade": None, "n_samples": n_samples, "n_eff": n_eff, "components": components}
    net = sum(v["weight"] * v["net"] for v in sources.values()) / wsum
    score = round(50 + 50 * net, 1)
    return {"score": score, "grade": grade_of(score), "n_samples": n_samples, "n_eff": n_eff, "components": components}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--date", default=None, help="계산 기준일 YYYY-MM-DD (기본 KST 오늘)")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 분포·상하위만 출력")
    parser.add_argument("--top", type=int, default=20, help="출력할 상위/하위 인원(기본 20)")
    args = parser.parse_args()

    project = os.environ.get("GCP_PROJECT")
    dataset = os.environ.get("BQ_DATASET", "offorby")
    location = os.environ.get("BQ_LOCATION", "asia-northeast3")
    if not project:
        sys.exit("GCP_PROJECT 환경변수가 필요합니다.")
    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(KST).date()

    client = bigquery.Client(project=project, location=location)
    targets, rows = fetch(client, project, dataset, day)
    by_person: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_person[r["person_id"]].append(r)
    print(f"{day}: 대상 {len(targets)}명, 창 {WINDOW_DAYS}일 안 sentiment_daily {len(rows)}행 "
          f"(반감기 {HALF_LIFE_DAYS}일, 수축 k={PRIOR_K}, 최소 표본 {MIN_SAMPLES})")

    out_rows, scored = [], []
    for t in targets:
        res = score_person(by_person.get(t["person_id"], []), day)
        out_rows.append({"snapshot_date": day.isoformat(), "person_id": t["person_id"], **res, "method_version": METHOD_VERSION})
        if res["score"] is not None:
            scored.append((res["score"], res["grade"], res["n_samples"], t["name"], t["role"], res["components"]["sources"]))

    scored.sort(reverse=True)
    grades = defaultdict(int)
    for s in scored:
        grades[s[1]] += 1
    print(f"점수 있음 {len(scored)}명 / 데이터 부족 {len(out_rows) - len(scored)}명")
    print("등급 분포: " + ", ".join(f"{g}등급 {grades[g]}" for g in sorted(grades)))

    def show(rows_: list) -> None:
        for score, grade, n, name, role, src in rows_:
            parts = " ".join(f"{s}:{v['net']:+.2f}({v['n']})" for s, v in sorted(src.items()))
            print(f"  {grade:2d}등급 {score:5.1f}  {name}({role}) 표본 {n:3d} | {parts}")
    if scored:
        print(f"상위 {min(args.top, len(scored))}명:"); show(scored[:args.top])
        if len(scored) > args.top:
            print(f"하위 {min(args.top, len(scored) - args.top)}명:"); show(scored[-args.top:])

    if args.dry_run:
        print("드라이런: 파일 미저장")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"scores_{day.strftime('%Y%m%d')}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"저장: {path} ({len(out_rows)}행)")


if __name__ == "__main__":
    main()
