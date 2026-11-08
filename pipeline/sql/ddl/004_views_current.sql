-- 화면용 현재 뷰 2개(현 시점 정본). 프로젝트 이전(offofby → offorby) 시 테이블은 bq cp로 복사하고 뷰는 이 파일로 만든다.
-- 실행: python pipeline/python/apply_sql.py pipeline/sql/ddl/004_views_current.sql --approve  (사용자 승인 필요)

CREATE SCHEMA IF NOT EXISTS `${project}.${dataset}`
OPTIONS (location = 'asia-northeast3');

CREATE OR REPLACE VIEW `${project}.${dataset}.v_current_members` AS
SELECT * EXCEPT (row_hash, valid_to, is_current)
FROM `${project}.${dataset}.members`
WHERE is_current;

CREATE OR REPLACE VIEW `${project}.${dataset}.v_current_president` AS
SELECT position, name, start_date, verified, valid_from
FROM `${project}.${dataset}.president`
WHERE is_current;
