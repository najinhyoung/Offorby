"""collect_dc.py가 훑는 디시인사이드 갤러리 목록(정치 관련). (id, kind) — kind는 'major'(/board/lists/) 또는 'minor'(/mgallery/board/lists/).

선정 기준(2026-11-08 확인):
- 목록 페이지가 200으로 응답하고 글 행(<tr class="ub-content us-post">)이 파싱된다
- https://gall.dcinside.com/robots.txt 의 갤러리 차단 목록(47, cat, dog, stock_new, stock_new2, baseball_new8,
  m_entertainer1, ib_new, d_fighter_new1, produce48, sportsseoul, metakr, salgoonews, singo, rezero)에 없다.
  일반 봇(User-agent: *)은 Allow: / 이며 검색 URL은 302 → 목록 페이지만 사용.
- 최근 글이 확인 당일 기준 며칠 안에 있다(활성 갤러리). 진보·보수 양쪽을 포함한다.

제외한 후보(2026-11-08): government(=공무원 갤러리, 2021년 종료), politics(=정치 게임 갤러리), president(=대물 갤러리),
news_new(2019년 종료), political(정치유머, 최근 글 2026-10-19로 저활성), uspolitics(미국 정치), conservative·sisa·chokuk(저활성).
"""

GALLERIES = [
    # (갤러리 id, 종류)                 # 갤러리명             최근 글 확인
    ("leejaemyung", "minor"),          # 이재명 마이너 갤러리   2026-11-06 (2026-11-08 확인)
    ("minjudang", "minor"),            # 더불어민주당 마이너 갤러리 2026-11-08 (2026-11-08 확인)
    ("jinbo", "minor"),                # 진보정치 마이너 갤러리 2026-11-07 (2026-11-08 확인)
    ("bosu", "minor"),                 # 보수정치 마이너 갤러리 2026-11-06 (2026-11-08 확인)
]

# 예비(활성이지만 아직 미사용): ("rightwing", "minor") 국내보수 마이너 갤러리 2026-11-07, ("minjoodang", "minor") 민주당 마이너 갤러리 2026-11-07

LIST_URL = {
    "major": "https://gall.dcinside.com/board/lists/?id={gall}&page={page}",
    "minor": "https://gall.dcinside.com/mgallery/board/lists/?id={gall}&page={page}",
}
