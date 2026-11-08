# 2단계 인터페이스 명세 — 발화 수집·감성 (2026-11-08 확정)

메인 세션이 확정한 계약. `db`·`collector`·`sentiment` 에이전트는 이 문서에 맞춰 각자 파일을 만든다.
충돌 시 이 문서 > `docs/PLAN.md`.

## 결정 (사용자 확인, 2026-11-08)
- 소스: **Google News RSS, YouTube Data API v3, 디시인사이드(정치 관련 갤러리 목록 스캔)**. 에펨코리아·클리앙·루리웹은 robots.txt가 검색 수집을 금지 → 제외. Google Trends 제외.
- 범위: **샘플 20명**(대통령 1 + 의원 19)으로 시작, 검증 후 전원. 환경변수 `COLLECT_LIMIT`(기본 20, 0 = 전원).
- 감성: Claude Haiku(`claude-haiku-5-5`), Message Batches API + 프롬프트 캐싱. **일 비용 상한 ₩3,000**(`SENTIMENT_DAILY_BUDGET_KRW`), 넘으면 표본을 줄여서 맞춤.
- 원문(유튜브 댓글·디시 제목·뉴스 제목 중 감성용 텍스트)은 `pipeline/tmp/`에만 두고 **BigQuery·Actions 아티팩트에 올리지 않는다**(CLAUDE.md 규칙 7). 뉴스 제목·링크는 규칙 4에 따라 `news` 테이블에 저장 가능.

## 인물 식별
- `person_id`: 의원 = `members.member_code`, 대통령 = `'PRESIDENT'`.
- 뷰 `v_collect_targets`(db 작성): 현재 인물 전원 + 결정적 샘플 순서.
  ```
  person_id, name, role('대통령'|'국회의원'), party, district,
  query_name  -- 검색어: "이름" 대통령 / "이름" 의원 (따옴표 포함)
  sample_rank -- 1 = 대통령, 2.. = 의원을 정당별 ROW_NUMBER(이름순) → (rn, party) 순으로 번갈아 배치
  ```
  수집기는 `SELECT * FROM v_collect_targets WHERE sample_rank <= @limit OR @limit = 0 ORDER BY sample_rank`.
  (수기 명단 없음 — 규칙 2. 정당 섞인 20명이 재현 가능하게 뽑힘.)

## 날짜
- 모든 2단계 테이블은 `snapshot_date DATE`(KST 수집일)로 파티션. `load_snapshot.py --append`가 첫 줄의 `snapshot_date`로 같은 날짜를 지우고 다시 넣으므로 재실행 멱등.
- 수집 창: 직전 수집일 이후 ~ 현재(기본 24시간). `published_at`은 UTC TIMESTAMP.

## 테이블 (DDL `pipeline/sql/ddl/005_mentions.sql`, db 작성)
```
stg_news        (snapshot_date DATE, person_id STRING, source STRING, title STRING, url STRING,
                 publisher STRING, published_at TIMESTAMP)              PARTITION BY snapshot_date
news            (같은 컬럼 + first_seen_date DATE)  PARTITION BY first_seen_date CLUSTER BY person_id
                 -- url 기준 유일. merge_news.sql이 stg_news에서 새 url만 INSERT
mentions_daily  (snapshot_date DATE, person_id STRING, source STRING, metric STRING, value FLOAT64,
                 detail JSON)                                            PARTITION BY snapshot_date CLUSTER BY person_id, source
sentiment_daily (snapshot_date DATE, person_id STRING, source STRING,
                 n_pos INT64, n_neu INT64, n_neg INT64, n_off_target INT64, n_sampled INT64,
                 intensity_avg FLOAT64, model STRING, prompt_version STRING, batch_id STRING)
                                                                        PARTITION BY snapshot_date CLUSTER BY person_id
v_collect_targets  (위)
```
- `source` 값: `gnews`, `youtube`, `dc`.
- `metric` 값: `gnews/articles`, `youtube/videos`, `youtube/views`, `youtube/comments`, `dc/posts`, `dc/comments`.
  `detail`에는 집계 보조 정보만(예: 갤러리별 글 수, 영상 id 목록 **아님** — 원문·식별자 최소화. 영상 id는 공개 식별자라 허용).
- DML `pipeline/sql/dml/merge_news.sql`: `INSERT INTO news SELECT ... FROM stg_news s WHERE snapshot_date = (오늘) AND NOT EXISTS (news.url = s.url)`.
  오늘 날짜는 `@d` 파라미터가 아니라 `CURRENT_DATE('Asia/Seoul')` 기준(apply_sql.py는 파라미터 없음).

## 수집기 (`pipeline/python/`, collector 작성)
공통: 표준 라이브러리 + `google-cloud-bigquery`만(요청은 `urllib`; 추가 패키지가 꼭 필요하면 `pipeline/requirements.txt`에 넣고 이유를 docstring에). UA `offorby-collector (+https://offorby.vercel.app)`. 출력 jsonl 한 줄 = 테이블 한 행, `snapshot_date`는 KST 오늘. `--dry-run`은 BigQuery·파일 쓰기 없이 요약 출력. `--limit N`은 `COLLECT_LIMIT` 덮어쓰기. 실패한 인물은 건너뛰고 끝에 요약(전체 실패 아님). 환경변수 `GCP_PROJECT`, `BQ_DATASET`.

공통 모듈 `collect_common.py`: 대상 조회(`load_targets(limit)`), KST 날짜, jsonl 쓰기, 1초 간격 요청 헬퍼, 감성 입력 쓰기(`append_sentiment_input(rows)` → `pipeline/tmp/sentiment_input_YYYYMMDD.jsonl`, 한 줄 `{id, person_id, person_name, role, source, text}`; `id` = `source:해시`).

1. `collect_gnews.py` — `https://news.google.com/rss/search?q={query_name}&hl=ko&gl=KR&ceid=KR:ko`. 창 안의 기사만. 출력 `out/news_YYYYMMDD.jsonl`(→ stg_news) + `out/mentions_gnews_YYYYMMDD.jsonl`(gnews/articles). 제목을 감성 입력에 추가.
2. `collect_youtube.py` — `search.list(q=query_name, type=video, publishedAfter=창 시작, regionCode=KR, relevanceLanguage=ko, maxResults=50, order=date)` 100 unit → `videos.list(part=statistics)` 1 unit/50개 → 조회수 합·댓글 수 합. `commentThreads.list(videoId, maxResults=100, order=relevance, textFormat=plainText)` 1 unit씩, 인물당 상위 3개 영상. 댓글 텍스트는 감성 입력에만. `YOUTUBE_API_KEY` 없으면 경고 후 종료(0). 일 쿼터 예산 `YOUTUBE_DAILY_UNITS`(기본 9,000) 넘기 전에 중단. 출력 `out/mentions_youtube_YYYYMMDD.jsonl`.
3. `collect_dc.py` — robots.txt: 일반 봇 허용, 검색 URL은 불가 → **갤러리 목록 페이지**(`/board/lists/?id={gall}&page={n}`, 마이너 갤러리는 `/mgallery/board/lists/`)를 최근 N페이지(기본 20) 훑어 창 안 글의 제목에서 대상 이름을 매칭. 갤러리 ID 목록은 `dc_galleries.py`에 상수로(정치 관련 2~4개; 구현 시 실제 응답으로 ID 확인하고 robots의 갤러리 차단 목록과 대조). 요청 간격 1초 이상. 집계 `dc/posts`(글 수), `dc/comments`(목록의 댓글 수 합). 제목만 감성 입력에(본문 요청 안 함). 출력 `out/mentions_dc_YYYYMMDD.jsonl`.

## 감성 (`pipeline/claude/sentiment.py`, sentiment 작성)
- 입력: `pipeline/tmp/sentiment_input_YYYYMMDD.jsonl`. 인물×소스별 표본 상한(`SENTIMENT_PER_PERSON_SOURCE`, 기본 50) 넘으면 무작위 추출(시드 = 날짜).
- 비용 추정: (입력 토큰 ≈ 글자수/2 + 캐시된 시스템 프롬프트, 출력 ≈ 30토큰) × Haiku 배치 단가 → ₩ 환산(환율 상수 1,450) → `SENTIMENT_DAILY_BUDGET_KRW`(기본 3000) 초과 시 전체 표본을 비율로 줄인 뒤 다시 추정. 실제 사용량도 로그.
- 호출: Message Batches API, 요청 1건 = 텍스트 1건, 시스템 프롬프트에 `cache_control`. 모델 `claude-haiku-5-5`. 출력 JSON `{"about_person": bool, "label": "pos|neu|neg", "intensity": 1|2|3}`. 파싱 실패는 `neu`로 두지 않고 제외(n_sampled에서 빼지 않음, 별도 카운트 로그).
- 폴링 최대 45분. 미완이면 배치 id를 `out/sentiment_pending_YYYYMMDD.json`에 쓰고 종료 코드 0(다음 실행이 `--resume` 없이도 그 파일을 보면 먼저 회수).
- 출력 `out/sentiment_YYYYMMDD.jsonl` → `sentiment_daily`. `prompt_version` 상수 `v1`. 완료 후 `pipeline/tmp/` 입력 파일 삭제.
- `--dry-run`: 비용 추정과 표본 수만 출력, API 호출 없음. `--review N`(로컬 전용): 결과 중 N건을 텍스트와 함께 stdout에 출력(파일 저장 안 함) — 사용자 검수용.
- `ANTHROPIC_API_KEY` 없으면 경고 후 종료(0).

## Actions (`daily.yml`, 메인 세션 작성)
- 새 잡 `mentions`(인물 잡 `daily`와 병렬, `needs` 없음). 단계: 수집 3종(각 `continue-on-error: true`) → `stg_news`·`mentions_daily` 적재(`load_snapshot.py --append`) → `merge_news.sql` → `sentiment.py` → `sentiment_daily` 적재. env `COLLECT_LIMIT: 20`.
- 아티팩트 업로드는 `pipeline/out/`만. `pipeline/tmp/`는 gitignore + 업로드 금지.

## 검증 순서
1. `collect_gnews.py --dry-run --limit 3`, `collect_dc.py --dry-run --limit 3` 로컬(키 불필요).
2. `sentiment.py --dry-run` 로컬(키 없이 비용 추정만).
3. DDL 005 사용자 승인 → 실행. 하루치 수집 → 적재 승인 → 실행.
4. Actions `mentions` 잡 수동 실행 → 테이블 행 확인.
5. 감성 샘플 100건 사용자 검수(`--review 100`, 로컬).
