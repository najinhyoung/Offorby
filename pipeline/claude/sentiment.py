"""발화(뉴스 제목·유튜브 댓글·디시 글 제목)×인물 감성 평가 배치 — Claude Haiku + Message Batches API + 프롬프트 캐싱.

사용: python pipeline/claude/sentiment.py [--date YYYY-MM-DD] [--dry-run] [--review N] [--resume] [--keep-input]
입력: pipeline/tmp/sentiment_input_YYYYMMDD.jsonl  (한 줄 {id, person_id, person_name, role, source, text})
출력: pipeline/out/sentiment_YYYYMMDD.jsonl          (sentiment_daily 컬럼 그대로; load_snapshot.py --append로 적재)
      pipeline/out/sentiment_pending_YYYYMMDD.json  (폴링 시간 안에 배치가 끝나지 않았을 때만)

원문은 러너 메모리에서만 판단하고 집계(라벨 수)만 남긴다. 결과 파일·pending 파일에 텍스트를 쓰지 않는다(CLAUDE.md 규칙 7).
`--review N`은 사용자 검수용으로 stdout에만 텍스트를 보여준다.

환경변수:
  ANTHROPIC_API_KEY             없으면 경고 후 종료 0 (--dry-run은 키 없이 동작)
  SENTIMENT_PER_PERSON_SOURCE   인물×소스별 표본 상한 (기본 50)
  SENTIMENT_DAILY_BUDGET_KRW    일 비용 상한 ₩ (기본 3000) — 초과 시 표본을 비율로 축소
  SENTIMENT_DAILY_LIMIT         일 요청 건수 상한 (기본 0 = 제한 없음; 비용 상한과 별개의 안전장치)
  SENTIMENT_POLL_MINUTES        배치 완료 폴링 최대 분 (기본 45)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import math
import os
import pathlib
import random
import sys
import time
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
TMP_DIR = ROOT / "pipeline" / "tmp"
OUT_DIR = ROOT / "pipeline" / "out"
PROMPT_FILE = pathlib.Path(__file__).with_name("prompt_v1.md")
PROMPT_VERSION = "v1"

# 모델·단가 (출처: claude-api 스킬 SKILL.md "Current Models" 표(cached 2026-10-06) +
#   shared/model-migration.md "Migrating to Claude Haiku 5.5" + python/claude-api/batches.md).
#   Claude Haiku 5.5 표준 단가: 입력 $0.10 / 출력 $0.50 per MTok (프롬프트 100K 토큰 이하 요금표).
#   캐시 읽기 = 입력의 0.1배, 캐시 쓰기(5분 TTL) = 입력의 1.25배. Message Batches = 전 항목 50% 할인.
MODEL = "claude-haiku-5-5"
USD_PER_MTOK_INPUT = 0.10 * 0.5          # 배치 입력 $0.05
USD_PER_MTOK_OUTPUT = 0.50 * 0.5         # 배치 출력 $0.25
USD_PER_MTOK_CACHE_READ = 0.10 * 0.1 * 0.5    # 배치 캐시 읽기 $0.005
USD_PER_MTOK_CACHE_WRITE = 0.10 * 1.25 * 0.5  # 배치 캐시 쓰기(5분) $0.0625
KRW_PER_USD = 1450  # 환율 상수 (docs/stage2_spec.md)

# 토큰 추정식 (docs/stage2_spec.md): 입력 토큰 ≈ 글자수/2, 출력 ≈ 30토큰.
CHARS_PER_TOKEN = 2
EST_OUTPUT_TOKENS = 30
EST_USER_OVERHEAD_TOKENS = 40  # 사용자 메시지 틀(이름·역할·출처 라벨) + 메시지 구조 오버헤드
MAX_TOKENS = 60                # 출력 JSON 한 줄(약 30토큰)에 여유분

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "about_person": {"type": "boolean"},
        "label": {"type": "string", "enum": ["pos", "neu", "neg"]},
        "intensity": {"type": "integer", "enum": [1, 2, 3]},
    },
    "required": ["about_person", "label", "intensity"],
    "additionalProperties": False,
}

SOURCE_LABEL = {"gnews": "뉴스 제목", "youtube": "유튜브 댓글", "dc": "디시인사이드 글 제목"}
KST = dt.timezone(dt.timedelta(hours=9))


def kst_today() -> str:
    return dt.datetime.now(KST).strftime("%Y-%m-%d")


def compact(date: str) -> str:
    return date.replace("-", "")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def est_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


# ---------- 입력 · 표본 ----------

def load_input(path: pathlib.Path) -> list[dict]:
    rows, seen = [], set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not row.get("text") or row.get("id") in seen:
                continue
            seen.add(row["id"])
            rows.append(row)
    return rows


def sample_rows(rows: list[dict], cap: int, date: str) -> list[dict]:
    """인물×소스별 상한 cap, 시드=날짜로 무작위. 그룹별 순서를 섞어 두면 비율 축소 때도 앞에서 자르면 된다."""
    rng = random.Random(date)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["person_id"], r["source"])].append(r)
    out = []
    for key in sorted(groups):
        g = groups[key]
        rng.shuffle(g)
        out.extend(g[:cap])
    return out


def shrink(sampled: list[dict], ratio: float) -> list[dict]:
    """각 (인물,소스) 그룹을 같은 비율로 줄인다(그룹당 최소 1건은 남김)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in sampled:
        groups[(r["person_id"], r["source"])].append(r)
    out = []
    for key in sorted(groups):
        g = groups[key]
        out.extend(g[: max(1, math.floor(len(g) * ratio))])
    return out


# ---------- 비용 ----------

def estimate_cost(sampled: list[dict], system_tokens: int) -> dict:
    n = len(sampled)
    user_tokens = sum(est_tokens(r["text"]) + EST_USER_OVERHEAD_TOKENS for r in sampled)
    out_tokens = n * EST_OUTPUT_TOKENS
    # 시스템 프롬프트는 첫 요청이 캐시에 쓰고 나머지는 읽는다고 가정. 캐시가 전혀 안 맞는 경우(worst)도 함께 계산.
    cached_usd = (
        system_tokens * USD_PER_MTOK_CACHE_WRITE
        + system_tokens * max(0, n - 1) * USD_PER_MTOK_CACHE_READ
        + user_tokens * USD_PER_MTOK_INPUT
        + out_tokens * USD_PER_MTOK_OUTPUT
    ) / 1e6
    worst_usd = ((system_tokens * n + user_tokens) * USD_PER_MTOK_INPUT + out_tokens * USD_PER_MTOK_OUTPUT) / 1e6
    return {
        "n": n,
        "system_tokens": system_tokens,
        "user_tokens": user_tokens,
        "output_tokens": out_tokens,
        "krw": cached_usd * KRW_PER_USD,
        "krw_no_cache": worst_usd * KRW_PER_USD,
    }


def actual_cost_krw(usage: dict) -> float:
    usd = (
        usage["input_tokens"] * USD_PER_MTOK_INPUT
        + usage["output_tokens"] * USD_PER_MTOK_OUTPUT
        + usage["cache_read_input_tokens"] * USD_PER_MTOK_CACHE_READ
        + usage["cache_creation_input_tokens"] * USD_PER_MTOK_CACHE_WRITE
    ) / 1e6
    return usd * KRW_PER_USD


# ---------- 요청 ----------

def user_message(row: dict) -> str:
    return (
        f"대상 인물: {row['person_name']} ({row['role']})\n"
        f"출처: {SOURCE_LABEL.get(row['source'], row['source'])}\n"
        f"텍스트:\n{row['text']}"
    )


def custom_id(row_id: str) -> str:
    """배치 custom_id는 [a-zA-Z0-9_-] 64자만 허용 → 입력 id의 ':'(source:hash)를 '_'로 바꾼다."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", row_id)[:64]


def build_requests(sampled: list[dict], system_prompt: str) -> list[dict]:
    system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    return [
        {
            "custom_id": custom_id(r["id"]),
            "params": {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                # Haiku 5.5는 기본으로 생각(thinking)을 하고 그 토큰이 max_tokens에 포함된다.
                # 분류 1건에 60토큰만 주므로 생각을 끄고(effort high 이하에서 허용) effort low.
                "thinking": {"type": "disabled"},
                "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                "system": system,
                "messages": [{"role": "user", "content": user_message(r)}],
            },
        }
        for r in sampled
    ]


# ---------- 배치 회수 · 집계 ----------

def parse_result(result) -> tuple[dict | None, str]:
    """(판정 dict 또는 None, 상태) — 상태 ∈ ok | errored | refusal | parse_fail."""
    if result.result.type != "succeeded":
        return None, "errored"
    msg = result.result.message
    if msg.stop_reason == "refusal":
        return None, "refusal"
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(text)
        label, intensity = data["label"], int(data["intensity"])
        if label not in ("pos", "neu", "neg") or intensity not in (1, 2, 3) or not isinstance(data["about_person"], bool):
            raise ValueError("schema")
        return {"about_person": data["about_person"], "label": label, "intensity": intensity}, "ok"
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None, "parse_fail"


def collect_results(client, batch_id: str, id_meta: dict[str, tuple[str, str]], date: str) -> tuple[list[dict], dict, list[tuple]]:
    """배치 결과 → (sentiment_daily 행 목록, 요약, 검수용 [(id, 판정)])."""
    agg: dict[tuple, dict] = defaultdict(lambda: {"pos": 0, "neu": 0, "neg": 0, "off": 0, "sampled": 0, "int_sum": 0, "int_n": 0})
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    counts = {"ok": 0, "errored": 0, "refusal": 0, "parse_fail": 0, "unknown_id": 0}
    judged: list[tuple] = []
    for result in client.messages.batches.results(batch_id):
        meta = id_meta.get(result.custom_id)
        if meta is None:
            counts["unknown_id"] += 1
            continue
        a = agg[meta]
        a["sampled"] += 1
        data, status = parse_result(result)
        counts[status] += 1
        if result.result.type == "succeeded":
            u = result.result.message.usage
            usage["input_tokens"] += u.input_tokens or 0
            usage["output_tokens"] += u.output_tokens or 0
            usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
            usage["cache_creation_input_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        if data is None:
            continue
        judged.append((result.custom_id, data))
        if not data["about_person"]:
            a["off"] += 1
            continue
        a[data["label"]] += 1
        a["int_sum"] += data["intensity"]
        a["int_n"] += 1

    rows = []
    for (person_id, source), a in sorted(agg.items()):
        rows.append({
            "snapshot_date": date,
            "person_id": person_id,
            "source": source,
            "n_pos": a["pos"],
            "n_neu": a["neu"],
            "n_neg": a["neg"],
            "n_off_target": a["off"],
            "n_sampled": a["sampled"],
            "intensity_avg": round(a["int_sum"] / a["int_n"], 3) if a["int_n"] else None,
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
            "batch_id": batch_id,
        })
    return rows, {"usage": usage, "counts": counts}, judged


def poll_batch(client, batch_id: str, minutes: int):
    deadline = time.monotonic() + minutes * 60
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        c = batch.request_counts
        print(f"  배치 {batch_id}: {batch.processing_status} (처리중 {c.processing}, 성공 {c.succeeded}, 오류 {c.errored})", flush=True)
        if time.monotonic() >= deadline:
            return None
        time.sleep(30)


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def print_review(judged: list[tuple], texts: dict[str, dict], n: int) -> None:
    """검수용: stdout에만 출력(파일 저장 금지)."""
    print(f"\n=== 검수 {min(n, len(judged))}건 (stdout 전용, 저장 안 함) ===")
    for cid, d in judged[:n]:
        row = texts.get(cid)
        if row:
            who = f"{row['person_name']}({row['role']})/{row['source']}"
            text = row["text"].replace("\n", " ")
        else:
            who, text = "?", "(원문 없음 — 입력 파일이 이미 삭제됨)"
        tag = f"{d['label']}{d['intensity']}" if d["about_person"] else "off"
        print(f"[{tag:>4}] {who} | {text}")


def finish(client, batch_id: str, date: str, id_meta: dict, texts: dict, args, pending_path: pathlib.Path | None) -> None:
    rows, summary, judged = collect_results(client, batch_id, id_meta, date)
    out_path = OUT_DIR / f"sentiment_{compact(date)}.jsonl"
    write_jsonl(out_path, rows)
    c, u = summary["counts"], summary["usage"]
    print(f"결과: {out_path} ({len(rows)}행, 인물×소스)")
    print(f"  판정 {c['ok']} / 오류 {c['errored']} / 거부 {c['refusal']} / n_parse_fail {c['parse_fail']} / 미상 id {c['unknown_id']}")
    print(f"  실제 토큰: 입력 {u['input_tokens']:,} · 캐시읽기 {u['cache_read_input_tokens']:,} · 캐시쓰기 {u['cache_creation_input_tokens']:,} · 출력 {u['output_tokens']:,}")
    print(f"  실제 추정 비용: ₩{actual_cost_krw(u):,.1f}")
    if args.review:
        print_review(judged, texts, args.review)
    if pending_path and pending_path.exists():
        pending_path.unlink()
    input_path = TMP_DIR / f"sentiment_input_{compact(date)}.jsonl"
    if input_path.exists() and not args.keep_input:
        input_path.unlink()
        print(f"입력 파일 삭제: {input_path}")


def resume_pending(client, pending_path: pathlib.Path, args, wait: bool) -> bool:
    """pending 파일의 배치를 회수. 끝났으면 집계·저장하고 True. wait=True면 폴링 시간만큼 기다린다."""
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    batch_id, date = pending["batch_id"], pending["date"]
    id_meta = {cid: (pid, src) for cid, pid, src in pending["sampled"]}
    print(f"미완 배치 회수 시도: {batch_id} ({date}, {pending['n_requests']}건)")
    batch = poll_batch(client, batch_id, args.poll_minutes if wait else 0)
    if batch is None:
        print("  아직 처리 중 — pending 유지")
        return False
    input_path = TMP_DIR / f"sentiment_input_{compact(date)}.jsonl"
    texts = {custom_id(r["id"]): r for r in load_input(input_path)} if input_path.exists() else {}
    finish(client, batch_id, date, id_meta, texts, args, pending_path)
    return True


# ---------- main ----------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=kst_today(), help="처리 날짜 YYYY-MM-DD (기본 KST 오늘)")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 표본 수·추정 비용만 출력")
    parser.add_argument("--review", type=int, default=0, metavar="N", help="결과 N건을 텍스트와 함께 stdout에 출력(검수용, 저장 안 함)")
    parser.add_argument("--resume", action="store_true", help="pending 배치 회수만 수행(폴링 시간만큼 대기), 새 배치는 만들지 않음")
    parser.add_argument("--keep-input", action="store_true", help="완료 후 입력 파일을 삭제하지 않음")
    parser.add_argument("--poll-minutes", type=int, default=env_int("SENTIMENT_POLL_MINUTES", 45))
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    date = args.date
    cap = env_int("SENTIMENT_PER_PERSON_SOURCE", 50)
    budget_krw = float(os.environ.get("SENTIMENT_DAILY_BUDGET_KRW") or 3000)
    daily_limit = env_int("SENTIMENT_DAILY_LIMIT", 0)
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()
    system_tokens = est_tokens(system_prompt)
    print(f"모델 {MODEL} · 프롬프트 {PROMPT_VERSION}(≈{system_tokens} 토큰) · 날짜 {date}")

    # 1) 표본 추출 + 비용 추정 (키 불필요)
    input_path = TMP_DIR / f"sentiment_input_{compact(date)}.jsonl"
    sampled: list[dict] = []
    est = None
    if input_path.exists():
        rows = load_input(input_path)
        sampled = sample_rows(rows, cap, date)
        print(f"입력 {len(rows)}건(중복 제거) → 표본 {len(sampled)}건 (인물×소스 상한 {cap})")
        if daily_limit and len(sampled) > daily_limit:
            sampled = shrink(sampled, daily_limit / len(sampled))
            print(f"  SENTIMENT_DAILY_LIMIT={daily_limit} 적용 → {len(sampled)}건")
        est = estimate_cost(sampled, system_tokens)
        while est["krw"] > budget_krw and est["n"] > 0:
            before, before_krw = est["n"], est["krw"]
            sampled = shrink(sampled, budget_krw / est["krw"] * 0.95)
            est = estimate_cost(sampled, system_tokens)
            print(f"  추정 ₩{before_krw:,.1f} > 예산 ₩{budget_krw:,.1f} → 표본 {before} → {est['n']}건으로 축소, 재추정 ₩{est['krw']:,.1f}")
            if est["n"] == before:  # 그룹당 최소 1건 때문에 더 못 줄임
                break
        print(
            f"추정: 요청 {est['n']}건 · 입력 {est['user_tokens']:,} + 시스템 {est['system_tokens']}×{est['n']}(캐시) · 출력 {est['output_tokens']:,} 토큰"
            f" → 약 ₩{est['krw']:,.1f} (캐시 미적중 시 ₩{est['krw_no_cache']:,.1f})"
        )
        if est["krw"] > budget_krw:
            print("  경고: 그룹당 최소 1건으로도 예산을 넘습니다. 상한/예산을 조정하세요.")
    else:
        print(f"입력 없음: {input_path}")

    if args.dry_run:
        print("dry-run: API 호출 없음")
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("경고: ANTHROPIC_API_KEY 없음 — 감성 평가 건너뜀")
        return
    import anthropic  # 키가 있을 때만 import (dry-run은 SDK 없이도 동작)

    client = anthropic.Anthropic()

    # 2) pending 회수
    pendings = sorted(OUT_DIR.glob("sentiment_pending_*.json"))
    for p in pendings:
        try:
            resume_pending(client, p, args, wait=args.resume)
        except anthropic.NotFoundError:
            print(f"  배치를 찾을 수 없음 — pending 파일 삭제: {p}")
            p.unlink()
    if args.resume:
        if not pendings:
            print("회수할 pending 배치 없음")
        return

    # 3) 새 배치
    if not sampled:
        print("보낼 표본 없음 — 종료")
        return
    requests = build_requests(sampled, system_prompt)
    try:
        batch = client.messages.batches.create(requests=requests)
    except anthropic.RateLimitError as e:
        sys.exit(f"배치 생성 실패(429): {e.message}")
    except anthropic.APIStatusError as e:
        sys.exit(f"배치 생성 실패({e.status_code}): {e.message}")
    except anthropic.APIConnectionError as e:
        sys.exit(f"배치 생성 실패(네트워크): {e}")
    print(f"배치 생성: {batch.id} ({len(requests)}건) — 최대 {args.poll_minutes}분 폴링")

    pending_path = OUT_DIR / f"sentiment_pending_{compact(date)}.json"
    id_meta = {custom_id(r["id"]): (r["person_id"], r["source"]) for r in sampled}
    # 폴링 중 러너가 죽어도 다음 실행이 회수할 수 있도록 먼저 기록(텍스트 없음, id·인물·소스만)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(
        json.dumps({"batch_id": batch.id, "date": date, "n_requests": len(requests),
                    "sampled": [[custom_id(r["id"]), r["person_id"], r["source"]] for r in sampled]}, ensure_ascii=False),
        encoding="utf-8",
    )

    done = poll_batch(client, batch.id, args.poll_minutes)
    if done is None:
        print(f"{args.poll_minutes}분 안에 끝나지 않음 — {pending_path}에 기록, 다음 실행에서 회수")
        return
    texts = {custom_id(r["id"]): r for r in sampled}
    finish(client, batch.id, date, id_meta, texts, args, pending_path)


if __name__ == "__main__":
    main()
