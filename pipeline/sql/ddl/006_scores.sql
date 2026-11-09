-- 3단계(100점 스코어·등급) 테이블 + 최신 점수 뷰. 계약: docs/stage3_spec.md, 방법: docs/methodology.md
-- 실행: python pipeline/python/apply_sql.py pipeline/sql/ddl/006_scores.sql --approve  (사용자 승인 필요)

-- scores: 인물별 일별 점수 이력. score.py가 매일 out/scores_YYYYMMDD.jsonl을 만들고 load_snapshot.py --append(키 snapshot_date)로 적재(멱등).
--   표본(n_samples) < 10이면 score·grade는 NULL(데이터 부족)이고 components만 남긴다. 대상 전원에 대해 행을 낸다.
CREATE TABLE IF NOT EXISTS `${project}.${dataset}.scores` (
  snapshot_date   DATE NOT NULL,     -- 계산일(KST)
  person_id       STRING NOT NULL,   -- members.member_code | 'PRESIDENT'
  score           FLOAT64,           -- 0~100 (50 + 50 × 순감성), 표본 부족 NULL
  grade           INT64,             -- 1(90~100) … 10(0~9), 표본 부족 NULL
  n_samples       INT64 NOT NULL,    -- 28일 창 안 대상 관련 판정 건수(가중 없음)
  n_eff           FLOAT64,           -- 시간 가중 표본 수
  components      JSON,              -- 소스별 순감성·표본·가중치 + 상수(window_days, half_life_days, prior_k, min_samples)
  method_version  STRING NOT NULL    -- 'v1'
)
PARTITION BY snapshot_date
CLUSTER BY person_id;

-- v_latest_scores: 인물별 가장 최근 계산일 1행. 화면(web/lib/data.ts)이 읽는다.
CREATE OR REPLACE VIEW `${project}.${dataset}.v_latest_scores` AS
SELECT person_id, snapshot_date, score, grade, n_samples, n_eff, components, method_version
FROM `${project}.${dataset}.scores`
QUALIFY ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY snapshot_date DESC) = 1;
