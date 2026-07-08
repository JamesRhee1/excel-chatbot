# 평가 하네스 (evals/)

골든 질의셋 기반으로 챗봇의 정확도를 회귀 측정하는 도구입니다.
"라우팅이 몇 %나 맞는가", "계획된 연산이 의도와 일치하는가",
"답이 정확한가"를 코드 변경 때마다 재확인할 수 있습니다.

## 구성

```
evals/
├── golden_queries.yaml     # 골든 질의 20개 (규칙 12 / LLM 8)
├── fixtures/
│   ├── budget_comparison.xlsx   # 예실대비표 형식 합성 데이터
│   └── generic_sales.xlsx       # 일반 표 형식 합성 데이터
├── make_fixtures.py        # 픽스처 재생성 스크립트 (openpyxl)
└── run_evals.py            # 실행기
```

픽스처는 **전부 합성 데이터**입니다. 실데이터를 커밋하지 마십시오.
픽스처를 수정하려면 `make_fixtures.py`를 고친 뒤 재생성합니다.

```bash
python evals/make_fixtures.py
```

## 실행

```bash
# 규칙 경로만 (Ollama 불필요 — CI/스모크용)
python evals/run_evals.py --no-llm

# 전체 20개 (로컬 Ollama 필요)
python evals/run_evals.py
```

출력은 질의별 결과 표(표준 출력)와 `evals/results_YYYYMMDD.json`
(gitignore 대상)입니다.

```
실행 12건 / 건너뜀 8건 | 라우팅 100% | 연산 100% | 답변 100% | 검증 100%
```

pytest에도 스모크가 연결되어 있습니다 — `tests/test_evals_smoke.py`가
`--no-llm` 기준으로 규칙 경로 질의의 라우팅·연산 일치를 항상 검증하므로,
규칙 라우터를 건드리는 변경은 CI에서 자동으로 회귀 확인됩니다.

## 지표 정의

| 지표 | 정의 |
|---|---|
| 라우팅 일치율 | 실제 `route_path`(rule/llm)가 `expected_route`와 일치한 비율. `expected_route: llm`은 `llm` 또는 `llm_fallback_clarify`와 일치 |
| 연산 일치율 | 실행된 op type 시퀀스가 `expected_ops`와 일치한 비율 |
| 답변 정확도 | `expected_answer` 스펙(스칼라 값 / 결과 행수 / 특정 셀 값)을 만족한 비율. 스펙이 없는 항목은 제외 |
| 검증 통과율 | 검증 계층(불변식 검사)을 전부 통과한 비율 |

## 골든 질의 스키마

`golden_queries.yaml`의 각 항목:

```yaml
- id: rule_aggregate
  query: "부서별 매출 합계"
  fixture: generic_sales.xlsx
  expected_route: rule            # rule | llm
  expected_ops: [exclude_summary, aggregate]
  expected_answer:                # 선택 — 아래 키 중 하나
    row_count: 3
```

`expected_answer` 지원 키 (`evals/run_evals.py` 구현 기준):

| 키 | 의미 | 예시 |
|---|---|---|
| `row_count` | 결과 DataFrame 행 수 | `row_count: 3` |
| `scalar` | 응답 메시지에 포함된 스칼라 값 | `scalar: "3000000"` |
| `cell` | 특정 셀 값 (`column`, `value`, 선택 `row_index`) | `cell: {column: "매출", value: 2500}` |

작성 규칙:

- `id`는 `rule_` / `llm_` 접두사로 기대 경로를 드러냅니다.
- `expected_route: llm` 항목은 `--no-llm`에서 건너뜁니다. 규칙 라우터가
  이 질의를 가로채기 시작하면 라우팅 불일치로 잡히므로, 규칙 확장이
  LLM 경로를 침범하는 회귀도 감지됩니다.
- clarify를 기대하는 질의(모호한 질문)도 골든셋에 포함합니다 —
  "모르면 되묻는다"도 정답 동작이기 때문입니다.

## 질의 추가 방법

1. 재현하려는 행동을 정한다 (새 라우팅 규칙, 새 연산, 버그 재발 방지 등).
2. 필요하면 `make_fixtures.py`에 데이터 케이스를 추가하고 재생성한다.
3. `golden_queries.yaml`에 항목을 추가한다. **기대 op 시퀀스는 반드시
   손으로 계산해 명시한다** — 현재 구현의 출력을 복사해 넣으면 회귀
   감지력이 사라진다.
4. `python evals/run_evals.py --no-llm`으로 확인 후 커밋한다.

버그를 수정할 때는 그 버그를 재현하는 골든 질의를 함께 추가하는 것을
원칙으로 합니다 (테스트의 회귀 케이스와 같은 역할).

## 트레이스와의 관계

평가 하네스는 **개발 시점**의 정확도를, 실행 트레이스(`traces/*.jsonl`)는
**사용 시점**의 실제 분포(규칙 적중률, LLM 폴백률, codegen 사용률,
연산별 지연시간)를 측정합니다. 트레이스에서 자주 실패하거나 clarify로
빠지는 질의 패턴을 발견하면, 그것이 다음 골든 질의와 라우팅 규칙의
후보가 됩니다.
