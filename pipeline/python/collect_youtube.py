"""YouTube Data API v3로 인물별 영상 수·조회수·댓글 수를 집계해 일일 스냅샷(jsonl)으로 저장한다. 계약: docs/stage2_spec.md

호출(인물 1명 ≈ 104 unit):
  search.list(q=query_name, type=video, publishedAfter=창 시작, regionCode=KR, relevanceLanguage=ko, order=date, maxResults=50) 100 unit
  → videos.list(part=statistics, 최대 50 id) 1 unit
  → commentThreads.list(videoId, maxResults=100, order=relevance, textFormat=plainText) 1 unit × 댓글 많은 상위 3개 영상
일 쿼터 예산 YOUTUBE_DAILY_UNITS(기본 9000)를 넘기기 전에 남은 인물을 건너뛴다.
순환(YOUTUBE_ROTATE, 기본 80): 대통령은 매일, 의원은 sample_rank 순으로 80명씩 묶어 날짜에 따라 번갈아 수집한다
(299명 → 4묶음 → 4일 주기). 순환 대상의 수집 창은 주기만큼 늘려(--since-hours × 주기) 빠진 날을 덮는다. 0이면 순환 없음.

- 출력: pipeline/out/mentions_youtube_YYYYMMDD.jsonl → mentions_daily (youtube/videos, youtube/views, youtube/comments; detail에 video_ids = 공개 식별자)
- 댓글 텍스트는 감성 입력(pipeline/tmp/)에만 넣고 어디에도 저장하지 않는다(CLAUDE.md 규칙 7)
- YOUTUBE_API_KEY 없으면 경고 후 종료 코드 0

사용: python pipeline/python/collect_youtube.py [--dry-run] [--limit N] [--since-hours 24] [--targets-file x.jsonl]
                                              [--units 9000] [--comment-videos 3] [--rotate 80]
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse

import collect_common as cc

SOURCE = "youtube"
API = "https://www.googleapis.com/youtube/v3/"
COST = {"search": 100, "videos": 1, "commentThreads": 1}


class QuotaExceeded(Exception):
    pass


class YouTube:
    def __init__(self, key: str, budget: int):
        self.key, self.budget, self.used = key, budget, 0

    def call(self, method: str, **params) -> dict:
        cost = COST[method]
        if self.used + cost > self.budget:
            raise QuotaExceeded(f"쿼터 예산 {self.budget} unit 초과 직전(사용 {self.used}, 필요 {cost})")
        self.used += cost
        q = urllib.parse.urlencode({**params, "key": self.key})
        # API 호출은 외부 사이트 크롤링이 아니므로 간격 0.2초만 둔다
        return cc.polite_get_json(f"{API}{method}?{q}", min_interval=0.2, host_key="youtube-api")

    def reserve(self, units: int) -> bool:
        return self.used + units <= self.budget


def api_error_reason(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read().decode("utf-8"))
        return body["error"]["errors"][0].get("reason", "")
    except Exception:  # noqa: BLE001
        return ""


def collect_person(yt: YouTube, target: dict, start_iso: str, n_comment_videos: int) -> tuple[dict, list[str], list[str]]:
    """(집계, video_ids, 댓글 텍스트 목록)."""
    found = yt.call("search", part="id", q=target["query_name"], type="video", publishedAfter=start_iso,
                    regionCode="KR", relevanceLanguage="ko", maxResults=50, order="date")
    video_ids = [it["id"]["videoId"] for it in found.get("items", []) if it.get("id", {}).get("videoId")]
    stats: dict[str, dict] = {}
    if video_ids:
        res = yt.call("videos", part="statistics", id=",".join(video_ids[:50]), maxResults=50)
        for v in res.get("items", []):
            stats[v["id"]] = v.get("statistics", {})
    views = sum(int(s.get("viewCount", 0) or 0) for s in stats.values())
    comments = sum(int(s.get("commentCount", 0) or 0) for s in stats.values())

    # 댓글 많은 영상 상위 N개의 최상위 댓글만 감성 입력으로(댓글 비활성 403은 건너뜀)
    ranked = sorted(((int(s.get("commentCount", 0) or 0), vid) for vid, s in stats.items()), reverse=True)
    texts: list[str] = []
    for n, vid in ranked[:n_comment_videos]:
        if n <= 0:
            break
        try:
            res = yt.call("commentThreads", part="snippet", videoId=vid, maxResults=100, order="relevance",
                          textFormat="plainText")
        except urllib.error.HTTPError as e:
            if e.code == 403 and api_error_reason(e) in ("commentsDisabled", "forbidden"):
                continue
            raise
        for th in res.get("items", []):
            texts.append(th.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay", ""))
    return {"videos": len(video_ids), "views": views, "comments": comments}, video_ids, texts


def rotate_targets(targets: list[dict], per_day: int, snapshot_date: str) -> tuple[list[dict], int, int]:
    """대통령은 매일, 의원은 sample_rank 순 per_day명 묶음을 날짜(KST 일수 % 묶음 수)로 골라 반환.
    반환 (선택된 대상, 주기 일수, 이번 묶음 번호). per_day 0이거나 의원이 한 묶음에 다 들어가면 주기 1(순환 없음)."""
    presidents = [t for t in targets if t["role"] == "대통령"]
    members = sorted((t for t in targets if t["role"] != "대통령"), key=lambda t: int(t["sample_rank"]))
    if per_day <= 0 or len(members) <= per_day:
        return presidents + members, 1, 0
    n_slices = -(-len(members) // per_day)  # ceil
    idx = dt.date.fromisoformat(snapshot_date).toordinal() % n_slices
    return presidents + members[idx * per_day:(idx + 1) * per_day], n_slices, idx


def main() -> None:
    parser = cc.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    parser.add_argument("--units", type=int, default=int(os.environ.get("YOUTUBE_DAILY_UNITS", "9000")),
                        help="이번 실행 쿼터 예산(unit). 기본 환경변수 YOUTUBE_DAILY_UNITS(9000)")
    parser.add_argument("--comment-videos", type=int, default=3, help="인물당 댓글을 읽을 영상 수(기본 3)")
    parser.add_argument("--rotate", type=int, default=int(os.environ.get("YOUTUBE_ROTATE", "80")),
                        help="하루에 수집할 의원 수(대통령은 매일). 0 = 순환 없이 전원. 기본 환경변수 YOUTUBE_ROTATE(80)")
    args = parser.parse_args()

    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        print("경고: YOUTUBE_API_KEY 미설정 — YouTube 수집을 건너뜁니다.", file=sys.stderr)
        return

    limit = cc.resolve_limit(args)
    snapshot_date = cc.kst_today()
    all_targets = cc.load_targets(limit, args.targets_file)
    targets, cycle_days, slice_idx = rotate_targets(all_targets, args.rotate, snapshot_date)
    # 매일 수집하는 대통령은 기본 창, 순환 대상은 주기만큼 넓힌 창(빠진 날을 덮는다)
    start_daily = cc.to_utc_iso(cc.window_start(args.since_hours))
    start_rotated = cc.to_utc_iso(cc.window_start(args.since_hours * cycle_days))
    yt = YouTube(key, args.units)
    per_person = COST["search"] + COST["videos"] + COST["commentThreads"] * args.comment_videos
    rot = f"순환 {slice_idx + 1}/{cycle_days}묶음(의원 {args.rotate}명/일, 창 {args.since_hours * cycle_days:g}h)" if cycle_days > 1 else "순환 없음"
    print(f"{snapshot_date}: 대상 {len(targets)}/{len(all_targets)}명 (limit {limit}, {rot}), 창 {start_daily} 이후, 예산 {args.units} unit (≈{per_person}/명)")

    mention_rows, sentiment_rows, skipped = [], [], []
    n_ok = n_fail = 0
    for t in targets:
        if not yt.reserve(per_person):
            skipped.append(t["name"])
            continue
        try:
            daily = t["role"] == "대통령" or cycle_days == 1
            agg, video_ids, texts = collect_person(yt, t, start_daily if daily else start_rotated, args.comment_videos)
        except QuotaExceeded as e:
            print(f"  중단: {e}", file=sys.stderr)
            skipped.append(t["name"])
            continue
        except Exception as e:  # noqa: BLE001 - 한 인물 실패는 건너뛰고 계속
            n_fail += 1
            msg = f"{type(e).__name__}: {e}"
            if isinstance(e, urllib.error.HTTPError):
                msg += f" ({api_error_reason(e)})"
            print(f"  실패 {t['name']}({t['person_id']}): {msg}", file=sys.stderr)
            continue
        n_ok += 1
        detail = {"window_hours": args.since_hours if daily else args.since_hours * cycle_days, "video_ids": video_ids}
        for metric in ("videos", "views", "comments"):
            mention_rows.append(cc.mention_row(snapshot_date, t["person_id"], SOURCE, f"youtube/{metric}", agg[metric], detail))
        sentiment_rows.extend(cc.make_sentiment_rows(t, SOURCE, texts))
        print(f"  {t['name']} ({t['role']}): 영상 {agg['videos']}, 조회 {agg['views']:,}, 댓글 {agg['comments']:,}, 감성 입력 {len(texts)}건")

    notes = [f"쿼터 사용 {yt.used}/{yt.budget} unit"]
    if skipped:
        notes.append(f"예산 초과로 건너뜀 {len(skipped)}명: {', '.join(skipped[:10])}{' …' if len(skipped) > 10 else ''}")
    if args.dry_run:
        print(f"드라이런: mentions {len(mention_rows)}행, 감성 입력 {len(sentiment_rows)}건 (파일 미저장)")
    else:
        tag = cc.snapshot_tag(snapshot_date)
        if mention_rows:
            print(f"저장: {cc.write_jsonl(cc.OUT_DIR / f'mentions_youtube_{tag}.jsonl', mention_rows)} ({len(mention_rows)}행)")
        if sentiment_rows:
            print(f"감성 입력 추가: {cc.append_sentiment_input(sentiment_rows, snapshot_date)} (+{len(sentiment_rows)}건)")
    cc.finish(n_ok, n_fail, notes)


if __name__ == "__main__":
    main()
