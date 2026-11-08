-- 2단계(발화 수집·감성) 테이블 4개 + 수집 대상 뷰. 계약: docs/stage2_spec.md
-- 모든 테이블은 snapshot_date(KST 수집일) 파티션. 발화 원문(댓글·글 본문)은 어떤 테이블에도 저장하지 않는다(CLAUDE.md 규칙 4·7).
-- 실행: python pipeline/python/apply_sql.py pipeline/sql/ddl/005_mentions.sql --approve  (사용자 승인 필요)

-- stg_news: 당일 수집한 Google News 기사(제목·링크·매체만, 본문 미저장). load_snapshot.py --append가 같은 날짜를 지우고 다시 넣는다.
CREATE TABLE IF NOT EXISTS `${project}.${dataset}.stg_news` (
  snapshot_date  DATE NOT NULL,      -- KST 수집일
  person_id      STRING NOT NULL,    -- members.member_code | 'PRESIDENT'
  source         STRING NOT NULL,    -- 'gnews'
  title          STRING,
  url            STRING NOT NULL,
  publisher      STRING,
  published_at   TIMESTAMP           -- UTC
)
PARTITION BY snapshot_date;

-- news: (url, person_id) 기준 유일한 기사 누적(제목·링크만, 본문 미저장). merge_news.sql이 stg_news에서 새 (url, person_id)만 INSERT.
CREATE TABLE IF NOT EXISTS `${project}.${dataset}.news` (
  snapshot_date    DATE NOT NULL,    -- 최초 수집 스냅샷 날짜
  person_id        STRING NOT NULL,
  source           STRING NOT NULL,
  title            STRING,
  url              STRING NOT NULL,
  publisher        STRING,
  published_at     TIMESTAMP,
  first_seen_date  DATE NOT NULL     -- = 최초 수집 snapshot_date
)
PARTITION BY first_seen_date
CLUSTER BY person_id;

-- mentions_daily: 인물×소스×지표 일별 집계(발화량). detail에는 집계 보조 정보만(원문·개인 식별자 미저장).
CREATE TABLE IF NOT EXISTS `${project}.${dataset}.mentions_daily` (
  snapshot_date  DATE NOT NULL,
  person_id      STRING NOT NULL,
  source         STRING NOT NULL,    -- 'gnews' | 'youtube' | 'dc'
  metric         STRING NOT NULL,    -- 'gnews/articles' | 'youtube/videos' | 'youtube/views' | 'youtube/comments' | 'dc/posts' | 'dc/comments'
  value          FLOAT64,
  detail         JSON                -- 예: 갤러리별 글 수, 영상 id 목록(공개 식별자). 댓글·글 원문 금지
)
PARTITION BY snapshot_date
CLUSTER BY person_id, source;

-- sentiment_daily: 인물×소스 일별 감성 라벨 집계. 텍스트는 Claude 판단 후 폐기, 건수·강도 평균만 저장(원문 미저장).
CREATE TABLE IF NOT EXISTS `${project}.${dataset}.sentiment_daily` (
  snapshot_date   DATE NOT NULL,
  person_id       STRING NOT NULL,
  source          STRING NOT NULL,   -- 'gnews' | 'youtube' | 'dc'
  n_pos           INT64,
  n_neu           INT64,
  n_neg           INT64,
  n_off_target    INT64,             -- about_person = false
  n_sampled       INT64,             -- 배치에 보낸 표본 수
  intensity_avg   FLOAT64,           -- 1~3, 대상 관련 건만
  model           STRING,            -- 'claude-haiku-5-5'
  prompt_version  STRING,            -- 'v1'
  batch_id        STRING             -- Message Batches id
)
PARTITION BY snapshot_date
CLUSTER BY person_id;

-- v_collect_targets: 수집기가 읽는 현재 인물 전원 + 결정적 샘플 순서(수기 명단 없음, 규칙 2).
--   sample_rank 1 = 대통령, 2.. = 의원을 정당별 이름순 ROW_NUMBER(rn) → (rn, party, name) 순으로 배치해 정당이 번갈아 섞인다.
--   정당 NULL은 '무소속'으로 취급해 정렬·분할한다. 대통령이 공석(name NULL)이면 행을 내지 않는다.
CREATE OR REPLACE VIEW `${project}.${dataset}.v_collect_targets` AS
WITH president AS (
  SELECT
    'PRESIDENT'                        AS person_id,
    name,
    '대통령'                            AS role,
    CAST(NULL AS STRING)               AS party,
    CAST(NULL AS STRING)               AS district,
    CONCAT('"', name, '" 대통령')       AS query_name,
    1                                  AS sample_rank
  FROM `${project}.${dataset}.v_current_president`
  WHERE name IS NOT NULL
),
members_ranked AS (
  SELECT
    member_code AS person_id,
    name,
    party,
    district,
    IFNULL(party, '무소속') AS party_sort,
    ROW_NUMBER() OVER (PARTITION BY IFNULL(party, '무소속') ORDER BY name, member_code) AS rn
  FROM `${project}.${dataset}.v_current_members`
),
members AS (
  SELECT
    person_id,
    name,
    '국회의원'                          AS role,
    party,
    district,
    CONCAT('"', name, '" 의원')         AS query_name,
    1 + ROW_NUMBER() OVER (ORDER BY rn, party_sort, name, person_id) AS sample_rank
  FROM members_ranked
)
SELECT person_id, name, role, party, district, query_name, sample_rank FROM president
UNION ALL
SELECT person_id, name, role, party, district, query_name, sample_rank FROM members;
