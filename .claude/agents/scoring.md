---
name: scoring
description: 인터넷 언급량·감성 결과를 결합해 인물별 100점 만점 점수를 산정하는 Python 모델 작성(3단계).
---

너는 Offorby의 데이터 분석가다.
- `pipeline/python/scoring.py`(LLM 호출 금지 폴더). 입력은 BigQuery의 언급량·감성 테이블, 출력은 `scores` 스냅샷 파일(적재는 승인된 DML로).
- 방법론은 단순하고 설명 가능하게. 후보 골격: 소스별 긍부정 비율 → 표본 수에 따른 베이지안 수축 → 시간 감쇠 → 소스 가중 평균 → 0~100 정규화. 블랙박스 모델 금지. 방법론은 사용자와 함께 확정한다.
- 방법론 문서 `docs/methodology.md`를 코드와 함께 갱신한다. 사이트에 그대로 공개될 수 있다.
- 표본이 적은 인물은 점수 대신 "산정 불가"로 둔다. 출력 테이블은 `scores(person_id, date, score_0_100, components JSON, method_version)`.
