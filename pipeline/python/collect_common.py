"""2단계 발화 수집기(collect_gnews / collect_youtube / collect_dc) 공통 모듈. 계약: docs/stage2_spec.md

- 대상 조회: BigQuery 뷰 v_collect_targets(sample_rank <= limit, 0 = 전원) 또는 --targets-file 로컬 jsonl
- KST 날짜, 수집 창 계산, jsonl 쓰기
- polite_get: 요청 간 최소 1초, 타임아웃 30초, 재시도 1회
- append_sentiment_input: 감성용 원문은 pipeline/tmp/sentiment_input_YYYYMMDD.jsonl 에만 둔다
  (BigQuery·아티팩트 금지, CLAUDE.md 규칙 7). pipeline/out/ 에는 집계·제목(뉴스만)·URL만.

환경변수: GCP_PROJECT(기본 offorby), BQ_DATASET(기본 offorby), BQ_LOCATION(기본 asia-northeast3), COLLECT_LIMIT(기본 20)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

UA = "offorby-collector (+https://offorby.vercel.app)"
KST = dt.timezone(dt.timedelta(hours=9))
PIPELINE_DIR = pathlib.Path(__file__).parents[1]
OUT_DIR = PIPELINE_DIR / "out"
TMP_DIR = PIPELINE_DIR / "tmp"  # gitignore + 아티팩트 업로드 금지 폴더

# Windows 콘솔(cp949)에서 이모지 등 출력 실패로 수집이 죽지 않도록
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


# ----- 날짜 -----
def kst_now() -> dt.datetime:
    return dt.datetime.now(KST)


def kst_today() -> str:
    """snapshot_date (YYYY-MM-DD, KST)."""
    return kst_now().date().isoformat()


def snapshot_tag(snapshot_date: str | None = None) -> str:
    """파일명용 YYYYMMDD."""
    return (snapshot_date or kst_today()).replace("-", "")


def window_start(since_hours: float) -> dt.datetime:
    """수집 창 시작(UTC aware)."""
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)


def to_utc_iso(d: dt.datetime) -> str:
    """BigQuery TIMESTAMP용 UTC ISO 문자열."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----- CLI -----
def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 요약만 출력(대상 조회·HTTP 요청은 수행)")
    parser.add_argument("--limit", type=int, default=None,
                        help="sample_rank <= N 인 대상만 (0 = 전원). 기본 환경변수 COLLECT_LIMIT(20)")
    parser.add_argument("--since-hours", type=float, default=24.0, help="수집 창(시간, 기본 24)")
    parser.add_argument("--targets-file", type=pathlib.Path, default=None,
                        help="BigQuery 대신 로컬 jsonl(v_collect_targets 컬럼)에서 대상을 읽는다(테스트용)")
    return parser


def resolve_limit(args: argparse.Namespace) -> int:
    if args.limit is not None:
        return args.limit
    return int(os.environ.get("COLLECT_LIMIT", "20") or 0)


# ----- 대상 -----
def load_targets(limit: int, targets_file: pathlib.Path | None = None) -> list[dict]:
    """v_collect_targets 행(person_id, name, role, party, district, query_name, sample_rank)을 sample_rank 순으로 반환."""
    if targets_file is not None:
        rows = [json.loads(l) for l in targets_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        rows = [r for r in rows if limit == 0 or int(r.get("sample_rank", 0)) <= limit]
        return sorted(rows, key=lambda r: int(r.get("sample_rank", 0)))

    from google.cloud import bigquery  # 로컬 테스트(--targets-file)에서는 import 자체를 피한다

    project = os.environ.get("GCP_PROJECT", "offorby")
    dataset = os.environ.get("BQ_DATASET", "offorby")
    location = os.environ.get("BQ_LOCATION", "asia-northeast3")
    client = bigquery.Client(project=project, location=location)
    sql = (
        f"SELECT person_id, name, role, party, district, query_name, sample_rank "
        f"FROM `{project}.{dataset}.v_collect_targets` "
        f"WHERE sample_rank <= @limit OR @limit = 0 ORDER BY sample_rank"
    )
    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]))
    return [dict(r) for r in job.result()]


# ----- HTTP -----
_last_request_at: dict[str, float] = {}


def polite_get(url: str, min_interval: float = 1.0, timeout: int = 30, retries: int = 1,
               headers: dict | None = None, host_key: str | None = None) -> bytes:
    """GET 본문(bytes). 같은 host_key(기본: 전역) 요청 간 최소 min_interval초 대기, 실패 시 retries회 재시도.
    4xx(429 제외)는 재시도하지 않고 바로 HTTPError를 올린다(호출자가 403 등을 해석한다)."""
    key = host_key or "*"
    hdrs = {"User-Agent": UA, **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        wait = _last_request_at.get(key, 0.0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at[key] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                raise
            last_err = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
        if attempt < retries:
            time.sleep(min(5.0, 2.0 * (attempt + 1)))
    assert last_err is not None
    raise last_err


def polite_get_json(url: str, **kw):
    return json.loads(polite_get(url, **kw).decode("utf-8"))


# ----- 출력 -----
def write_jsonl(path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    """rows를 jsonl로 저장(덮어씀). 모든 행에 snapshot_date가 있어야 한다(load_snapshot.py --append가 첫 줄을 읽음)."""
    for r in rows:
        if "snapshot_date" not in r:
            raise ValueError("snapshot_date 없는 행이 있습니다")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def mention_row(snapshot_date: str, person_id: str, source: str, metric: str, value: float,
                detail: dict | None = None) -> dict:
    """mentions_daily 한 행. detail은 집계 보조 정보만(원문·개인 식별자 금지). JSON 컬럼이므로 객체 그대로 둔다."""
    return {"snapshot_date": snapshot_date, "person_id": person_id, "source": source,
            "metric": metric, "value": float(value), "detail": detail or {}}


# ----- 감성 입력(원문 임시 저장, pipeline/tmp 전용) -----
def sentiment_id(source: str, text: str) -> str:
    return f"{source}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


def sentiment_input_path(snapshot_date: str | None = None) -> pathlib.Path:
    return TMP_DIR / f"sentiment_input_{snapshot_tag(snapshot_date)}.jsonl"


def make_sentiment_rows(target: dict, source: str, texts: list[str]) -> list[dict]:
    """{id, person_id, person_name, role, source, text} 행 목록(빈 문자열 제외, 같은 텍스트 중복 제거)."""
    rows, seen = [], set()
    for t in texts:
        t = " ".join((t or "").split())
        if not t:
            continue
        sid = sentiment_id(source, t)
        if sid in seen:
            continue
        seen.add(sid)
        rows.append({"id": sid, "person_id": target["person_id"], "person_name": target["name"],
                     "role": target["role"], "source": source, "text": t})
    return rows


def append_sentiment_input(rows: list[dict], snapshot_date: str | None = None) -> pathlib.Path:
    """감성 입력을 pipeline/tmp/sentiment_input_YYYYMMDD.jsonl 에 append. 이 파일은 커밋·아티팩트 금지."""
    path = sentiment_input_path(snapshot_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


# ----- 요약·종료 -----
def finish(n_ok: int, n_fail: int, notes: list[str] | None = None) -> None:
    """끝에 '성공 n / 실패 m' 요약을 찍고, 전부 실패했을 때만 종료 코드 1."""
    print(f"요약: 성공 {n_ok} / 실패 {n_fail}" + (f" | {' | '.join(notes)}" if notes else ""))
    if n_fail and n_ok == 0:
        sys.exit(1)
