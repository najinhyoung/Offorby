-- stg_news(오늘 KST 스냅샷) → news: 아직 없는 (url, person_id)만 INSERT (멱등 — 두 번 실행해도 추가 없음)
-- 유일 키는 (url, person_id): 한 기사가 여러 인물에 걸리면 인물별로 1건씩 남는다(인물별 기사 목록 화면용).
-- 같은 날 stg 안에서 (url, person_id)가 중복되면 published_at이 가장 늦은 1건만 남긴다.
-- 날짜는 @d 파라미터 대신 CURRENT_DATE('Asia/Seoul') (apply_sql.py는 파라미터 없음).
-- 실행: python pipeline/python/apply_sql.py pipeline/sql/dml/merge_news.sql --approve  (사용자 승인 필요)

INSERT INTO `${project}.${dataset}.news`
  (snapshot_date, person_id, source, title, url, publisher, published_at, first_seen_date)
SELECT
  s.snapshot_date,
  s.person_id,
  s.source,
  s.title,
  s.url,
  s.publisher,
  s.published_at,
  s.snapshot_date AS first_seen_date
FROM `${project}.${dataset}.stg_news` s
WHERE s.snapshot_date = CURRENT_DATE('Asia/Seoul')
  AND NOT EXISTS (
    SELECT 1 FROM `${project}.${dataset}.news` n WHERE n.url = s.url AND n.person_id = s.person_id
  )
QUALIFY ROW_NUMBER() OVER (PARTITION BY s.url, s.person_id ORDER BY s.published_at DESC) = 1;
