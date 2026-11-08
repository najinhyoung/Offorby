# Offorby

대한민국 선출직(대통령·국회의원) 목록과 (향후) 발화 기반 100점 스코어·한줄평을 보여주는 웹. 국무위원(장관)은 대상이 아니다.
전체 계획과 단계는 `docs/PLAN.md` 참고.

## 구조
- `web/` — Next.js(App Router) + Tailwind. Vercel 배포 루트.
- `pipeline/python/` — 일반 Python 운영 스크립트(수집·적재·스코어링). LLM 호출 없음.
- `pipeline/claude/` — Claude API를 호출하는 운영 스크립트(감성 평가 등)만.
- `pipeline/sql/ddl/`, `pipeline/sql/dml/` — BigQuery SQL. **모든 DB 변경은 이 파일들로만.**
- `pipeline/python/assembly_apis.py` — 열린국회정보 API 엔드포인트 4종(인적사항·발의법률안·상임위활동·정책자료실). 키 하나(`ASSEMBLY_API_KEY`)로 모두 호출.
- GitHub Actions(`.github/workflows/daily.yml`)가 매일 실행.

## 오케스트레이션 (메인 세션의 역할)
메인 세션이 오케스트레이터다. 작업을 아래 서브에이전트(`.claude/agents/`)에 나누고, 인터페이스(테이블 스키마, API 형태)를 먼저 확정한 뒤 넘긴다.
- `frontend` — web/ 화면
- `designer` — 디자인 시스템·화면 설계(토큰·레이아웃), 코드는 frontend가 구현
- `collector` — 인물·발화(Google News·Trends·YouTube·커뮤니티) 수집 스크립트
- `db` — BigQuery 스키마·적재 SQL 작성 (실행은 하지 않음)
- `sentiment` — Claude API 감성 평가 배치
- `scoring` — 발화량·감성 기반 100점 스코어 산정

## 절대 규칙
1. **DDL/DML 실행 전 반드시 사용자 승인.** `bq`, `pipeline/python/apply_sql.py`, `pipeline/python/load_snapshot.py` 등 BigQuery에 쓰는 명령은 사용자가 SQL 파일을 확인하고 승인한 뒤에만 실행한다. 승인은 실행 1건마다 따로 받는다.
1-1. **git 배포(push) 전 반드시 사용자 승인.** `git push`는 사용자가 지시하거나 승인한 경우에만 실행한다. 커밋도 사용자 요청 시에만.
2. 수기 관리 데이터 없음. 모든 인물 데이터는 자동 수집, 변경은 SCD2 이력으로 보존.
3. 운영 파이프라인에서 LLM 호출은 감성 평가에만. 수집·적재·스코어링은 일반 코드.
4. 뉴스는 제목·요약·링크만 저장(본문 저장 금지).
5. 비밀값(API 키, 서비스계정 JSON)은 커밋 금지. 로컬은 `.env.local` / `pipeline/.env`, 운영은 Vercel·GitHub Secrets.
6. 화면에 "신용평가"라는 표현을 쓰지 않는다(신용정보법 용어). 점수 명칭은 확정 전까지 "평판등급(준비 중)".
7. **발화 원문(유튜브 댓글·커뮤니티 글 본문)은 BigQuery·아티팩트에 저장하지 않는다.** 감성 판단 후 폐기하고 라벨·집계·출처 URL만 저장한다(규칙 4의 확장).
