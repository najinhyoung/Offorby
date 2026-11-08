# pipeline/claude — Claude API를 호출하는 운영 스크립트

LLM(Claude API)으로 처리하는 단계만 여기에 둔다. 일반 Python 처리(수집·적재·스코어링)는 `pipeline/python/`.

## `sentiment.py` — 발화×인물 감성 평가 배치 (2단계)

수집기가 `pipeline/tmp/sentiment_input_YYYYMMDD.jsonl`(한 줄 `{id, person_id, person_name, role, source, text}`)에 모아 둔 텍스트를
Claude Haiku(`claude-haiku-5-5`) + Message Batches API(50% 할인) + 시스템 프롬프트 캐싱으로 판정하고,
`(snapshot_date, person_id, source)` 집계만 `pipeline/out/sentiment_YYYYMMDD.jsonl`에 남긴다(`sentiment_daily` 컬럼 그대로).
원문은 메모리에서만 쓰고 완료 후 입력 파일을 지운다(CLAUDE.md 규칙 7). 프롬프트 원문은 `prompt_v1.md`(= `prompt_version`).

판정 형식(구조화 출력으로 강제): `{"about_person": bool, "label": "pos|neu|neg", "intensity": 1|2|3}`.
`about_person=false`(이름만 스쳐간 글)는 `n_off_target`으로만 세고 긍/부정 집계에서 뺀다. 파싱 실패·거부는 `n_parse_fail` 등으로 로그만.

```
python pipeline/claude/sentiment.py                 # KST 오늘 입력 → 배치 → 집계 → 입력 삭제
python pipeline/claude/sentiment.py --dry-run       # 표본 수·추정 비용만 (API 키 불필요)
python pipeline/claude/sentiment.py --review 100    # 결과 100건을 원문과 함께 stdout에만 출력(검수용)
python pipeline/claude/sentiment.py --resume        # 미완 배치(out/sentiment_pending_*.json) 회수만
python pipeline/claude/sentiment.py --date 2026-11-08 --keep-input
```

동작 순서: 표본 추출(인물×소스별 상한, 시드=날짜) → 비용 추정(예산 초과 시 표본을 비율로 축소) → pending 배치가 있으면 먼저 회수
→ 새 배치 생성 → 30초 간격 폴링(최대 45분) → 집계 저장. 폴링 시간 안에 안 끝나면 `out/sentiment_pending_YYYYMMDD.json`에
`{batch_id, date, n_requests, sampled:[id, person_id, source]}`를 남기고 종료 코드 0, 다음 실행이 회수한다.

환경변수:

| 변수 | 기본 | 뜻 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | 없으면 경고 후 종료 0 (`--dry-run`은 키 없이 동작) |
| `SENTIMENT_PER_PERSON_SOURCE` | 50 | 인물×소스별 표본 상한 |
| `SENTIMENT_DAILY_BUDGET_KRW` | 3000 | 일 비용 상한(₩). 추정이 넘으면 표본 축소 |
| `SENTIMENT_DAILY_LIMIT` | 0(없음) | 일 요청 건수 상한(비용 상한과 별개의 안전장치) |
| `SENTIMENT_POLL_MINUTES` | 45 | 배치 완료 대기 최대 분 |

비용 추정식(`sentiment.py` 상수, 단가 출처는 주석 참고): 입력 토큰 ≈ 글자수/2 + 40, 출력 30토큰, 시스템 프롬프트는 1회 캐시 쓰기 + (n−1)회 캐시 읽기.
Haiku 5.5 배치 단가 $0.05/MTok 입력, $0.25/MTok 출력, 캐시 읽기 $0.005, 캐시 쓰기 $0.0625; 환율 1,450 KRW/USD.

적재: `python pipeline/python/load_snapshot.py pipeline/out/sentiment_YYYYMMDD.jsonl --table sentiment_daily --append --approve`
