# Offorby — 대한민국 선출직 목록·평가 웹 (작업 계획)

> **2026-11-02 방향 수정** — 대상을 선출직(대통령·국회의원)으로 한정(국무위원 제거, cabinet→president 테이블 교체).
> 발화 소스를 네이버에서 Google News RSS·Google Trends·YouTube·커뮤니티(디시·에펨코리아·클리앙·루리웹)로 변경(무료 우선, 급증 시 유료 API 허용).
> 등급(AAA+~CC) 대신 **100점 만점 스코어**. 발화 원문은 저장하지 않고 라벨·집계만. 장기: 헤더/푸터 Google 광고, SEO/GEO.
> 아래 본문 중 충돌하는 부분은 이 메모와 「2단계 설계」 절이 우선한다.

## Context
빈 저장소(main, 커밋 없음)에서 시작. 목표는 대통령·장관·지역구 국회의원 목록 웹을 먼저 Vercel에 띄우고,
장기적으로 인터넷 언급량·뉴스 감성 기반 등급(AAA+~CC) → 실명 로그인 한줄평까지 확장하는 것.
확정된 선택: GCP 월 $10~30, 1단계는 목록 화면만, 감성분석은 Claude API, 프론트는 Next.js + Tailwind,
**수기 관리 없음(전부 자동 갱신)**, 스코어링도 Claude가 작업, **DDL/DML은 사용자 승인 필수**.

## 핵심 설계 판단
1. **"에이전트"를 두 종류로 나눈다**
   - *개발용 에이전트* (Claude Code 서브에이전트, `.claude/agents/*.md`): 코드를 만드는 역할. 토큰을 씀.
   - *운영 파이프라인* (Python 스크립트, GitHub Actions cron): 매일 돌아가는 수집·분석. **LLM 토큰은 감성분석에만** 씀.
   → 수집·적재·스코어링을 LLM으로 매일 돌리면 비용만 커지므로 일반 코드로 둔다.
2. **DB: BigQuery(1~3단계) → Cloud SQL Postgres 추가(4단계 로그인/댓글 시점)**
   - 목록·언급량·점수는 읽기 위주 분석 데이터 → BigQuery 무료 구간으로 충분.
   - 사이트는 Next.js ISR(일 1회 갱신 직후 재검증)로 BigQuery를 읽으므로 방문자 수와 무관하게 쿼리 비용 거의 0.
   - 회원/한줄평은 4단계에 Cloud SQL(최소 인스턴스 월 ~$10~15)로 추가 → 예산 내.
3. **매일 자동 갱신 + 이력 보존**: 모든 인물 테이블은 일일 스냅샷을 받아 변경분만 반영(유효시작/유효종료 이력, SCD2).
   의원 사퇴·보궐·장관 교체가 생기면 자동 반영되고, 변경 내역은 GitHub Issue로 알림(확인용, 수정 불필요).
4. **오케스트레이터**: 개발 측은 메인 Claude 세션 + `CLAUDE.md`(역할·규칙), 운영 측은 GitHub Actions 워크플로 하나가
   인물 갱신 → 언급량·뉴스 수집 → 감성 → 스코어링 → Vercel ISR 재검증 순서로 호출.

## DB 변경 승인 규칙 (요청 사항)
- 모든 DDL/DML은 `pipeline/sql/` 아래 파일로만 작성하고, Claude가 `bq`/BigQuery 실행 전 **반드시 사용자 승인**을 받는다.
- 강제 장치: 프로젝트 `.claude/settings.json`에서 `bq` 명령과 BigQuery 쓰기 스크립트 실행을 `ask` 권한으로 고정 + `CLAUDE.md`에 규칙 명시.
- 정기 파이프라인(Actions)의 일일 적재 SQL은 **파일 단위로 한 번 승인(PR 리뷰)** 하면 이후 자동 실행. 그 SQL이 바뀌면 다시 승인.
  (서비스계정 권한도 데이터셋 쓰기만, 테이블 생성/삭제 불가로 최소화)

## 데이터 소스 (전부 자동, 매일)
| 대상 | 소스 | 비고 |
|---|---|---|
| 국회의원·지역구·정당 | 열린국회정보 OpenAPI | 일 1회, 변경 감지 |
| 대통령 | 위키백과 「이재명 정부의 국무위원」 표의 대통령 행 + 대통령실 누리집 교차검증 | 미확인 이름 변경은 3일 연속 수집 시에만 반영(위키 훼손 방어) |
| 뉴스 | Google News RSS(`news.google.com/rss/search`, 인물당 1요청/일) | 제목·링크·언론사·시각만 저장 |
| 관심도 | Google Trends(pytrends, 비공식) 5개 묶음 + 기준어 정규화 | 선택 소스. 차단 잦아 실패해도 파이프라인 계속 |
| 유튜브 | YouTube Data API v3 search(100 unit)+commentThreads(1 unit), 일 10,000 unit | 인물 ~80명/일 순환(4일 주기). 댓글은 감성 후 폐기 |
| 커뮤니티 | 디시(정치 갤러리)·에펨코리아·클리앙·루리웹 검색 페이지 | 구현 전 robots.txt 확인, 초당 1요청 이하. 글 수 집계 + 감성 후 폐기 |
| 유료 확장 | Google Custom Search JSON API(1,000건당 $5), YouTube 쿼터 증설 | 발화량 급증·필요 시 사용자 승인 후 키 설정으로 활성화 |

## 역할 분담
| 역할 | 담당 |
|---|---|
| 오케스트레이터 | Claude 메인 세션 + CLAUDE.md / 운영은 Actions |
| 프론트엔드 엔지니어링 | Claude 서브에이전트 `frontend` |
| 인물·언급량·뉴스 수집 | Claude 서브에이전트 `collector`가 스크립트 작성 |
| DB 관리(스키마·적재 SQL) | Claude 서브에이전트 `db` 작성 → **사용자 승인 후 실행** |
| 감성 평가 | Claude 서브에이전트 `sentiment`가 Claude API(Haiku, 배치 API + 프롬프트 캐싱) 스크립트 작성 |
| 스코어링/등급 산정 | Claude 서브에이전트 `scoring`(Python) — 사용자는 방법론 검토 |
| 사용자 직접 | 계정·키 발급, SQL 승인, 등급 방법론 검토. 원하면 이후 스코어링 모델을 직접 고도화 |

## 단계·순서·작업량(대략)
| 단계 | 내용 | Claude 작업량 | 사용자 작업량 | 월 비용 |
|---|---|---|---|---|
| 0. 기반 | Next.js 스캐폴드, CLAUDE.md, `.claude/agents/`·settings, GCP 서비스계정, Vercel 연결 | 작음 (1세션) | 계정·키 설정 30분 | $0 |
| 1. 목록 웹 ★지금 | 의원·내각 자동 수집(일 1회, 이력), BigQuery 스키마, 메인/의원 목록(지역·정당 필터·검색)/상세/대통령·장관 페이지, 등급 자리 표시 | 중간 (2~4세션) | DDL·적재 SQL 승인 | $0 |
| 2. 발화·감성 | Google News·Trends·YouTube·커뮤니티 수집, Claude 감성 배치(원문 폐기) | 중간 | 감성 샘플 검수 | Claude API 수~수십 달러(기사량 따라, 일일 상한 설정) |
| 3. 스코어링 | 발화·감성 결합 100점 모델(방법론 별도 검토), `scores` 테이블, 첫 화면 점수, 방법론 공개 페이지 | 중간 | 방법론 검토 | $0 |
| 4. 로그인·한줄평 | 본인확인, Cloud SQL, 댓글·신고·관리 | 큼 | 정책 결정 | Cloud SQL ~$10~15 + 본인확인 비용 |

## 1단계 파일 구조(예정)
```
/web                  Next.js(App Router) + Tailwind
  app/page.tsx        첫 화면(대통령·장관 요약 + 의원 검색, 등급 자리)
  app/members/...     목록·상세
  lib/bigquery.ts     서버 전용 BigQuery 조회
/pipeline             Python
  collect_assembly.py 열린국회 API 수집
  collect_cabinet.py  위키백과 + 부처 페이지 교차검증
  sql/ddl/*.sql       테이블 정의(승인 후 실행)
  sql/dml/*.sql       MERGE(SCD2) 적재
/.github/workflows/daily.yml   일 1회 (KST 새벽)
/.claude/agents/      frontend, collector, db, sentiment, scoring
/.claude/settings.json  bq 실행 ask 권한
CLAUDE.md
```

## 추가로 필요한 것 / 결정할 것
1. **명칭·법적 리스크**: "신용평가등급"은 신용정보법 용어와 겹치고 명예훼손 소지 → "의정평판등급" 등 다른 명칭 + 산정 방법론 공개 권장. 선거기간 게시판 실명확인 의무(공직선거법)는 4단계 전 법률 검토.
2. **실명 인증**: PASS·KCB 등 본인확인기관 연동은 사업자 등록·계약·건당 비용 필요. 초기엔 카카오/네이버 로그인 + 선택적 본인확인 권장.
3. **계정·키**: 열린국회정보 API 키, 네이버 개발자 API 키(2단계), Anthropic API 키(2단계), GCP 프로젝트·서비스계정, GitHub 원격 저장소, Vercel 프로젝트.
4. 범위: 비례대표 포함 여부(현재 계획은 300명 전체 수집, 화면 기본 필터는 지역구), 차관·처장급 포함 여부.

## 검증
- 수집 스크립트 dry-run → 결과 CSV로 의원 수(지역구 254명)·장관 수 확인 후, 승인 받아 BigQuery 적재.
- 변경 감지 테스트: 스냅샷 하나를 임의 수정해 SCD2 이력·Issue 알림 생성 확인.
- `npm run dev` + 브라우저 패널로 목록·필터·상세·모바일 폭 확인, Vercel 프리뷰에서 ISR 재검증 확인.


## 2단계 설계 (2026-11-02 확정)
- person_id: 의원 `member_code`, 대통령 `PRESIDENT`. 쿼리 `"이름" 의원` / `"이름" 대통령`.
- 테이블(모두 date 파티션): `news(person_id, source, title, url, publisher, published_at, collected_date)`,
  `mentions_daily(person_id, source, metric, date, value)`, `sentiment_daily(person_id, source, date, n_pos, n_neu, n_neg, n_sampled, model, prompt_version)`,
  이후 `scores(person_id, date, score_0_100, components JSON, method_version)`.
- 감성: `pipeline/claude/sentiment.py` — Haiku + Message Batches API + 프롬프트 캐싱. 출력 `{about_person, label, intensity}`. 인물당·전체 일 표본 상한. 샘플 100건 사용자 검수.
- Actions: `daily.yml`에 발화 수집 잡을 인물 잡과 분리해 병렬. Secrets `YOUTUBE_API_KEY`, `ANTHROPIC_API_KEY`(선택 `GOOGLE_CSE_KEY`).

## 3단계 메모 — 100점 스코어
후보 골격: 소스별 긍부정 비율 → 표본 수 베이지안 수축 → 시간 감쇠 → 소스 가중 평균 → 0~100 정규화. `docs/methodology.md`로 공개. 방법론은 별도 세션에서 사용자와 확정.

## 장기 메모
- **광고**: 헤더/푸터 광고 슬롯 자리 예약. AdSense 승인에 개인정보처리방침·이용약관·쿠키 동의·UGC 운영정책 필요 → 4단계와 함께.
- **SEO/GEO**: 의원 상세 정적 생성(`generateStaticParams`), `generateMetadata`, `sitemap.ts`/`robots.ts`, `schema.org/Person` JSON-LD, 방법론 페이지, `/llms.txt`. 점수 공개 시점에 일괄.
