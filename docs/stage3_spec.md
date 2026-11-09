# 3단계 인터페이스 명세 — 100점 스코어·등급 (2026-11-09 확정)

메인 세션이 사용자와 확정한 계약. `scoring`·`db`·`frontend` 작업은 이 문서에 맞춘다. 충돌 시 이 문서 > `docs/PLAN.md`.
공개용 설명은 `docs/methodology.md`(화면 `/methodology`와 같은 내용).

## 결정 (사용자 확인, 2026-11-09)
- 점수: **감성만**으로 계산. 언급량은 점수가 아니라 신뢰도(표본 수)에만 쓴다.
- 소스별 순감성 → 표본이 적으면 50점 쪽으로 당김(베이지안 수축) → 최근 28일, 반감기 14일 시간 가중 → 뉴스 0.5·유튜브 0.3·디시 0.2 가중 합 → `50 + 50 × 순감성`.
- 등급: **절대 구간 10단계**. `1등급`(90~100) … `10등급`(0~9). 표본 10건 미만은 점수·등급 없음(`데이터 부족`).
- 화면에 바로 표시. 명칭은 CLAUDE.md 규칙 6에 따라 **"평판등급(준비 중)"**. "신용평가"라는 말은 쓰지 않는다.
- 매일 Actions `mentions` 잡 끝에 계산해 `scores`에 날짜별로 쌓는다(이력). 화면은 최신 날짜만 본다.

## 입력
`sentiment_daily`(snapshot_date, person_id, source, n_pos, n_neu, n_neg, n_off_target, n_sampled, intensity_avg). 대상 관련 건만 쓴다(`n_off_target` 제외).
유튜브는 의원 80명/일 순환이라 4일에 한 행만 있고 그 행이 4일치다 — 감성 **비율**만 쓰므로 창 길이 보정이 필요 없다(언급량 지표를 쓰게 되면 `mentions_daily.detail.window_hours`로 나눌 것).

## 계산 (`pipeline/python/score.py`, method_version `v1`)
기준일 `D` = KST 오늘. 창 = `D-27 .. D`(28일). 상수는 스크립트 상단에 모아 둔다.

```
HALF_LIFE_DAYS = 14      WINDOW_DAYS = 28      PRIOR_K = 20      MIN_SAMPLES = 10
SOURCE_WEIGHT = {"gnews": 0.5, "youtube": 0.3, "dc": 0.2}
```

인물 × 소스 s, 날짜 d의 행에 대해
- `n_d = n_pos + n_neu + n_neg` (대상 관련 건수)
- `f_d = clamp(intensity_avg, 1, 3) / 2` (강도 1→0.5, 2→1.0, 3→1.5; NULL이면 1.0)
- `w_d = 0.5 ** ((D - d) / HALF_LIFE_DAYS)` (시간 가중)

소스 순감성(수축 포함):
```
N_eff_s = Σ_d w_d · n_d
NET_s   = clamp( Σ_d w_d · (n_pos - n_neg) · f_d  /  (N_eff_s + PRIOR_K), -1, 1 )
```
`PRIOR_K`가 분모에 더해져 표본이 적을수록 0(=50점)으로 당겨진다. 표본 20건이면 원래 비율의 절반.

합산: `N_eff_s > 0`인 소스만 쓰고 가중치를 그 소스들 안에서 재정규화.
```
net   = Σ_s SOURCE_WEIGHT[s] · NET_s / Σ_s SOURCE_WEIGHT[s]      (존재하는 s만)
score = round(50 + 50 · net, 1)
grade = clamp(10 - floor(score / 10), 1, 10)     # 100→1, 95→1, 85→2, 50→5, 49.9→6, 0→10
n_samples = Σ_{s,d} n_d (가중 없는 건수)     n_eff = Σ_s N_eff_s
```
`n_samples < MIN_SAMPLES`이면 `score`·`grade`는 NULL로 저장(components는 저장). 대상 전원(`v_collect_targets`)에 대해 행을 낸다(감성 행이 없으면 n_samples 0).

## 출력 → 테이블 (DDL `pipeline/sql/ddl/006_scores.sql`)
```
scores (
  snapshot_date  DATE NOT NULL,     -- 계산일 D (KST). load_snapshot.py --append 멱등 키
  person_id      STRING NOT NULL,
  score          FLOAT64,           -- 0~100, 표본 부족이면 NULL
  grade          INT64,             -- 1~10, 표본 부족이면 NULL
  n_samples      INT64 NOT NULL,    -- 28일 창 안 대상 관련 판정 건수
  n_eff          FLOAT64,           -- 시간 가중 표본 수
  components     JSON,              -- {"sources":{"gnews":{"net":..,"n_eff":..,"n":..,"weight":..}, ...},
                                    --  "window_days":28,"half_life_days":14,"prior_k":20,"min_samples":10}
  method_version STRING NOT NULL    -- 'v1'
) PARTITION BY snapshot_date CLUSTER BY person_id
v_latest_scores: scores 중 person_id별 최신 snapshot_date 1행 (person_id, snapshot_date, score, grade, n_samples, n_eff, components, method_version)
```
스크립트 출력 `pipeline/out/scores_YYYYMMDD.jsonl` → `python pipeline/python/load_snapshot.py <파일> --table scores --append --approve` (키 기본 snapshot_date).
CLI: `python pipeline/python/score.py [--date YYYY-MM-DD] [--dry-run] [--top 20]` — `--dry-run`은 파일을 쓰지 않고 상위/하위 `--top`명과 분포를 출력.

## 화면 (`web/`, frontend)
- 데이터: `v_latest_scores`를 `v_current_members`/`v_current_president`에 person_id로 조인(의원 = member_code, 대통령 = 'PRESIDENT'). 조회 함수는 `web/lib/data.ts`에, 타입은 `web/lib/types.ts`에, 샘플 폴백은 `web/lib/sample.ts`에.
- 표시: 라벨 **"평판등급(준비 중)"**. 값이 있으면 `N등급 · 점수 xx.x · 표본 n건`, 없으면 `데이터 부족 (표본 n건)`. 등급 1~10에 색을 입히되 1이 좋음(초록 계열) 10이 나쁨(빨강 계열), 중간은 회색.
- 위치: 첫 화면 대통령 카드, 의원 목록 카드, 의원 상세. 목록은 등급순 정렬 옵션 하나 추가(점수 NULL은 맨 뒤).
- `/methodology` 페이지: `docs/methodology.md` 내용을 그대로 화면에(정적 페이지). 등급 옆에 "산정 방법" 링크.
- 기존 ISR·조회 방식 유지. "신용평가" 단어 금지.

## 검증 순서
1. `score.py --dry-run` 로컬: 현재 sentiment_daily 2일치로 분포 출력(대부분 데이터 부족이어야 정상).
2. DDL 006 사용자 승인 → 적용. `score.py` 실행 → 적재 승인 → `v_latest_scores` 확인.
3. 로컬 `npm run dev`로 카드·상세·`/methodology` 확인.
4. 커밋·푸시 → 다음 스케줄에서 `scores` 행 추가 확인.
