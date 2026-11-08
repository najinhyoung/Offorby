"""디시인사이드 정치 관련 갤러리의 목록 페이지를 훑어 인물별 글 수·댓글 수를 집계해 일일 스냅샷(jsonl)으로 저장한다. 계약: docs/stage2_spec.md

- 검색 URL은 쓰지 않는다(302). dc_galleries.GALLERIES의 갤러리 목록 페이지(/board/lists/, /mgallery/board/lists/)를
  최근 --pages(기본 20)페이지, 요청 간 1초 이상 간격으로 읽는다(robots.txt: User-agent * Allow, 차단 갤러리는 제외).
- 목록 행에서 글번호·제목·댓글 수·작성시각만 파싱(광고·공지·설문 행 제외). 글 본문·댓글은 요청하지 않는다.
- 창 안 글의 제목에 대상 name이 포함되면 매칭(대통령도 이름 필수 — '대통령' 단독은 매칭하지 않음).
- 출력: pipeline/out/mentions_dc_YYYYMMDD.jsonl → mentions_daily (dc/posts, dc/comments; detail에 갤러리별 건수)
- 매칭 글의 제목은 감성 입력(pipeline/tmp/)에만 넣는다(CLAUDE.md 규칙 7).

사용: python pipeline/python/collect_dc.py [--dry-run] [--limit N] [--since-hours 24] [--pages 20] [--galleries id,id]
                                         [--targets-file x.jsonl]
"""
import argparse
import datetime as dt
import html
import re
import sys

import collect_common as cc
from dc_galleries import GALLERIES, LIST_URL

SOURCE = "dc"
# 브라우저 UA 뒤에 수집기 식별을 붙인다(일부 페이지가 비브라우저 UA에 다른 마크업을 준다)
HEADERS = {"User-Agent": f"Mozilla/5.0 {cc.UA}", "Accept-Language": "ko-KR,ko;q=0.9"}

ROW_RE = re.compile(r'<tr class="ub-content us-post"[^>]*data-no="(\d+)"[^>]*>(.*?)</tr>', re.S)
SUBJECT_RE = re.compile(r'<td class="gall_subject">(.*?)</td>', re.S)
TITLE_TD_RE = re.compile(r'<td class="gall_tit ub-word">(.*?)</td>', re.S)
TITLE_A_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S)
REPLY_RE = re.compile(r'<span class="reply_num">\[(\d+)\]</span>')
DATE_RE = re.compile(r'<td class="gall_date" title="(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"')
TAG_RE = re.compile(r"<[^>]+>")
SKIP_SUBJECTS = {"공지", "설문", "AD", "광고", "뉴스"}


def clean(s: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub("", s)).split())


def parse_list(page_html: str) -> list[dict]:
    """목록 페이지 → [{no, subject, title, comments, posted_at(KST aware)}]. 공지·광고·설문 행은 제외."""
    posts = []
    for no, body in ROW_RE.findall(page_html):
        m_sub = SUBJECT_RE.search(body)
        subject = clean(m_sub[1]) if m_sub else ""
        if subject in SKIP_SUBJECTS or "icon_notice" in body:
            continue
        m_td = TITLE_TD_RE.search(body)
        m_date = DATE_RE.search(body)
        if not m_td or not m_date:
            continue
        m_a = TITLE_A_RE.search(m_td[1])
        title = clean(m_a[1]) if m_a else ""
        if not title:
            continue
        m_reply = REPLY_RE.search(m_td[1])
        posted_at = dt.datetime.strptime(m_date[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=cc.KST)
        posts.append({"no": int(no), "subject": subject, "title": title,
                      "comments": int(m_reply[1]) if m_reply else 0, "posted_at": posted_at})
    return posts


def scan_gallery(gall: str, kind: str, pages: int, start: dt.datetime) -> tuple[list[dict], int]:
    """창 안 글 목록과 읽은 페이지 수. 글은 번호 내림차순이므로 한 페이지가 전부 창 밖이면 중단."""
    kept, read = [], 0
    for page in range(1, pages + 1):
        url = LIST_URL[kind].format(gall=gall, page=page)
        posts = parse_list(cc.polite_get(url, min_interval=1.0, headers=HEADERS, host_key="gall.dcinside.com").decode("utf-8", "ignore"))
        read += 1
        if not posts:
            break
        in_window = [p for p in posts if p["posted_at"] >= start]
        kept.extend(in_window)
        if not in_window:
            break
    return kept, read


def match_targets(posts: list[dict], targets: list[dict]) -> dict[str, list[dict]]:
    """제목에 name이 포함된 글을 인물별로 모은다(이름 필수, 직함 단독 매칭 없음)."""
    hits: dict[str, list[dict]] = {t["person_id"]: [] for t in targets}
    for p in posts:
        for t in targets:
            if t["name"] and t["name"] in p["title"]:
                hits[t["person_id"]].append(p)
    return hits


def main() -> None:
    parser = cc.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    parser.add_argument("--pages", type=int, default=20, help="갤러리당 읽을 최근 페이지 수(기본 20)")
    parser.add_argument("--galleries", default=None, help="dc_galleries.GALLERIES 중 이 id들만(쉼표 구분, 테스트용)")
    args = parser.parse_args()
    limit = cc.resolve_limit(args)
    snapshot_date = cc.kst_today()
    start = cc.window_start(args.since_hours)

    galleries = GALLERIES
    if args.galleries:
        want = set(args.galleries.split(","))
        galleries = [g for g in GALLERIES if g[0] in want]
        unknown = want - {g[0] for g in GALLERIES}
        if unknown:
            sys.exit(f"dc_galleries.GALLERIES에 없는 id: {', '.join(sorted(unknown))}")

    targets = cc.load_targets(limit, args.targets_file)
    print(f"{snapshot_date}: 대상 {len(targets)}명 (limit {limit}), 창 {cc.to_utc_iso(start)} 이후, "
          f"갤러리 {len(galleries)}개 × 최대 {args.pages}페이지")

    # 갤러리별로 창 안 글을 모은다(갤러리 하나 실패해도 계속)
    per_gallery: dict[str, list[dict]] = {}
    n_ok = n_fail = 0
    for gall, kind in galleries:
        try:
            posts, read = scan_gallery(gall, kind, args.pages, start)
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            print(f"  실패 {gall}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        n_ok += 1
        per_gallery[gall] = posts
        print(f"  {gall}({kind}): {read}페이지 읽음, 창 안 글 {len(posts)}건, 댓글 합 {sum(p['comments'] for p in posts):,}")

    # 인물별 매칭 → 집계
    mention_rows, sentiment_rows = [], []
    for t in targets:
        by_gall = {g: match_targets(posts, [t])[t["person_id"]] for g, posts in per_gallery.items()}
        n_posts = sum(len(v) for v in by_gall.values())
        n_comments = sum(p["comments"] for v in by_gall.values() for p in v)
        detail = {"window_hours": args.since_hours, "pages": args.pages,
                  "galleries": {g: {"posts": len(v), "comments": sum(p["comments"] for p in v)} for g, v in by_gall.items()}}
        mention_rows.append(cc.mention_row(snapshot_date, t["person_id"], SOURCE, "dc/posts", n_posts, detail))
        mention_rows.append(cc.mention_row(snapshot_date, t["person_id"], SOURCE, "dc/comments", n_comments, detail))
        sentiment_rows.extend(cc.make_sentiment_rows(t, SOURCE, [p["title"] for v in by_gall.values() for p in v]))
        if n_posts:
            print(f"  {t['name']} ({t['role']}): 글 {n_posts}건, 댓글 {n_comments:,} "
                  f"[{', '.join(f'{g} {len(v)}' for g, v in by_gall.items() if v)}]")
    matched = sum(1 for r in mention_rows if r["metric"] == "dc/posts" and r["value"] > 0)
    notes = [f"매칭 인물 {matched}/{len(targets)}"]

    if args.dry_run:
        print(f"드라이런: mentions {len(mention_rows)}행, 감성 입력 {len(sentiment_rows)}건 (파일 미저장)")
    else:
        tag = cc.snapshot_tag(snapshot_date)
        if mention_rows and per_gallery:
            print(f"저장: {cc.write_jsonl(cc.OUT_DIR / f'mentions_dc_{tag}.jsonl', mention_rows)} ({len(mention_rows)}행)")
        if sentiment_rows:
            print(f"감성 입력 추가: {cc.append_sentiment_input(sentiment_rows, snapshot_date)} (+{len(sentiment_rows)}건)")
    cc.finish(n_ok, n_fail, notes)


if __name__ == "__main__":
    main()
