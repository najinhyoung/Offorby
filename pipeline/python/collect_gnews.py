"""Google News RSS에서 인물별 기사(제목·링크·언론사·날짜만)를 수집해 일일 스냅샷(jsonl)으로 저장한다. 계약: docs/stage2_spec.md

- 검색어는 v_collect_targets.query_name('"이름" 의원' / '"이름" 대통령', 동명이인 대응)
- 출력 1: pipeline/out/news_YYYYMMDD.jsonl            → stg_news (본문 미저장, CLAUDE.md 규칙 4)
- 출력 2: pipeline/out/mentions_gnews_YYYYMMDD.jsonl  → mentions_daily (metric gnews/articles)
- 기사 제목은 감성 입력(pipeline/tmp/sentiment_input_YYYYMMDD.jsonl)에도 추가

사용: python pipeline/python/collect_gnews.py [--dry-run] [--limit N] [--since-hours 24] [--targets-file x.jsonl]
"""
import argparse
import datetime as dt
import email.utils
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

import collect_common as cc

SOURCE = "gnews"
RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


def rss_url(query_name: str) -> str:
    return RSS.format(q=urllib.parse.quote(query_name))


def strip_publisher_suffix(title: str, publisher: str | None) -> str:
    """구글 뉴스 RSS 제목은 '기사 제목 - 언론사' 형태. 언론사 접미를 제거한다."""
    title = title.strip()
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(publisher) - 3].rstrip()
    # 언론사 태그와 표기가 다를 때(예: 'KBS 뉴스' vs 'KBS')는 마지막 ' - ' 뒤를 잘라낸다
    m = re.match(r"^(.*\S)\s+-\s+[^-]{1,40}$", title)
    return m[1] if m else title


def parse_pubdate(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        d = email.utils.parsedate_to_datetime(text)  # RFC 2822
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def parse_items(xml_bytes: bytes) -> list[dict]:
    """RSS item → {title, url, publisher, published_at(datetime|None)}."""
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.iter("item"):
        src = item.find("source")
        publisher = (src.text or "").strip() if src is not None else None
        title = strip_publisher_suffix(item.findtext("title") or "", publisher)
        url = (item.findtext("link") or "").strip()
        if not url:
            continue
        out.append({"title": title, "url": url, "publisher": publisher or None,
                    "published_at": parse_pubdate(item.findtext("pubDate"))})
    return out


def collect_person(target: dict, start: dt.datetime) -> list[dict]:
    """창 안 기사만, url 기준 중복 제거."""
    items = parse_items(cc.polite_get(rss_url(target["query_name"]), host_key="news.google.com"))
    seen, kept = set(), []
    for it in items:
        if it["published_at"] is None or it["published_at"] < start or it["url"] in seen:
            continue
        seen.add(it["url"])
        kept.append(it)
    return kept


def main() -> None:
    parser = cc.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    args = parser.parse_args()
    limit = cc.resolve_limit(args)
    snapshot_date = cc.kst_today()
    start = cc.window_start(args.since_hours)

    targets = cc.load_targets(limit, args.targets_file)
    print(f"{snapshot_date}: 대상 {len(targets)}명 (limit {limit}), 창 {cc.to_utc_iso(start)} 이후")

    news_rows, mention_rows, sentiment_rows = [], [], []
    n_ok = n_fail = 0
    for t in targets:
        try:
            articles = collect_person(t, start)
        except Exception as e:  # noqa: BLE001 - 한 인물 실패는 건너뛰고 계속
            n_fail += 1
            print(f"  실패 {t['name']}({t['person_id']}): {type(e).__name__}: {e}", file=sys.stderr)
            continue
        n_ok += 1
        publishers: dict[str, int] = {}
        for a in articles:
            publishers[a["publisher"] or "(미상)"] = publishers.get(a["publisher"] or "(미상)", 0) + 1
            news_rows.append({"snapshot_date": snapshot_date, "person_id": t["person_id"], "source": SOURCE,
                              "title": a["title"], "url": a["url"], "publisher": a["publisher"],
                              "published_at": cc.to_utc_iso(a["published_at"])})
        mention_rows.append(cc.mention_row(snapshot_date, t["person_id"], SOURCE, "gnews/articles", len(articles),
                                           {"window_hours": args.since_hours, "publishers": publishers}))
        sentiment_rows.extend(cc.make_sentiment_rows(t, SOURCE, [a["title"] for a in articles]))
        print(f"  {t['name']} ({t['role']}): 기사 {len(articles)}건, 언론사 {len(publishers)}곳")

    if args.dry_run:
        print(f"드라이런: news {len(news_rows)}행, mentions {len(mention_rows)}행, 감성 입력 {len(sentiment_rows)}건 (파일 미저장)")
    else:
        tag = cc.snapshot_tag(snapshot_date)
        if mention_rows:
            print(f"저장: {cc.write_jsonl(cc.OUT_DIR / f'news_{tag}.jsonl', news_rows)} ({len(news_rows)}행)")
            print(f"저장: {cc.write_jsonl(cc.OUT_DIR / f'mentions_gnews_{tag}.jsonl', mention_rows)} ({len(mention_rows)}행)")
        if sentiment_rows:
            print(f"감성 입력 추가: {cc.append_sentiment_input(sentiment_rows, snapshot_date)} (+{len(sentiment_rows)}건)")
    cc.finish(n_ok, n_fail)


if __name__ == "__main__":
    main()
