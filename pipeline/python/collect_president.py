"""현직 대통령을 수집해 일일 스냅샷(jsonl)으로 저장한다.

1차 소스: 한국어 위키백과 「이재명 정부의 국무위원」 표의 '대통령' 행(MediaWiki API, wikitext 파싱)
2차 소스: 대통령실 누리집(president_sites.py)에 그 이름이 실려 있는지 확인 → verified
공석(권한대행 체제 등)은 name=NULL. 이름이 바뀌었는데 verified가 아니면
MERGE(merge_president.sql)가 며칠간 같은 값이 유지될 때까지 반영을 보류한다.

사용: python pipeline/python/collect_president.py [--dry-run] [--skip-verify]
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

from president_sites import PRESIDENT_SITES

WIKI_API = "https://ko.wikipedia.org/w/api.php"
WIKI_PAGE = "이재명 정부의 국무위원"  # 정부가 바뀌면 이 문서명만 바꾼다
WIKI_URL = f"https://ko.wikipedia.org/wiki/{urllib.parse.quote(WIKI_PAGE)}"
UA = {"User-Agent": "offorby-collector (+https://offorby.vercel.app)"}
OUT_DIR = pathlib.Path(__file__).parents[1] / "out"


def fetch_wikitext() -> str:
    query = urllib.parse.urlencode({"action": "parse", "page": WIKI_PAGE, "prop": "wikitext",
                                    "format": "json", "formatversion": 2})
    req = urllib.request.Request(f"{WIKI_API}?{query}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["parse"]["wikitext"]


def strip_links(text: str) -> str:
    # [[문서|표시]] → 표시, [[문서]] → 문서, '''강조''' 제거
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    return text.replace("'''", "").strip()


def parse_period(text: str) -> str | None:
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def parse_president(wikitext: str) -> dict:
    """표에서 직위가 '대통령'인 행 하나를 찾는다."""
    start = wikitext.find('{| class="wikitable')
    end = wikitext.find("\n|}", start)
    if start < 0 or end < 0:
        raise RuntimeError("위키 문서에서 국무위원 표를 찾지 못했습니다.")
    for block in wikitext[start:end].split("|-")[1:]:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        head = next((l for l in lines if l.startswith("!")), None)
        cells = [l[1:].strip() for l in lines if l.startswith("|")]
        if not head or not cells:
            continue
        position = re.sub(r"\s*\((의장|부의장)\)\s*", "", strip_links(head[1:]))
        if position != "대통령":
            continue
        name = strip_links(cells[0])
        period = cells[2] if len(cells) > 2 else ""
        return {"position": position, "name": None if name in ("", "공석") else name,
                "start_date": parse_period(period)}
    raise RuntimeError("표에 '대통령' 행이 없습니다. 표 구조 변경 여부 확인 필요")


def page_mentions(url: str, name: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 " + UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return name in resp.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001 - 누리집 장애는 '미확인'일 뿐 수집 실패가 아니다
        print(f"  확인 실패 {url}: {type(e).__name__}", file=sys.stderr)
        return False


def verify(row: dict, skip: bool) -> dict:
    hit = None
    if row["name"] and not skip:
        hit = next((u for u in PRESIDENT_SITES if page_mentions(u, row["name"])), None)
    return {**row, "verified": hit is not None, "source_urls": [WIKI_URL] + ([hit] if hit else [])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 출력")
    parser.add_argument("--skip-verify", action="store_true", help="누리집 교차검증 생략(미확인)")
    args = parser.parse_args()

    row = verify(parse_president(fetch_wikitext()), args.skip_verify)
    snapshot_date = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    print(f"{snapshot_date}: 대통령 {row['name'] or '(공석)'} 취임 {row['start_date']} "
          f"{'누리집 확인' if row['verified'] else '미확인'}")

    if args.dry_run:
        return
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"president_{snapshot_date.replace('-', '')}.jsonl"
    out.write_text(json.dumps({**row, "snapshot_date": snapshot_date}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
