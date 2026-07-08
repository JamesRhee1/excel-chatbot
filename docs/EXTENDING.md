# 확장 가이드 — 새 연산·새 도메인 팩 추가

이 프로젝트의 두 가지 확장 축은 **연산(operation)**과 **도메인 팩**입니다.
둘 다 레지스트리 등록 방식이므로, 기존 코드 수정을 최소화하며 추가할 수
있습니다.

---

## 1. 새 연산 추가

예시: 결측 행만 추출하는 `filter_missing` 연산을 추가한다고 가정합니다.

### 1-1. 순수 함수 구현 — `core/operations.py`

```python
def filter_missing_rows(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """지정 컬럼이 결측인 행만 반환. 입력은 불변."""
    _require_columns(df, [column])
    return df[df[column].isna()].copy()
```

규칙:
- **입력 DataFrame을 절대 변형하지 않는다** (`.copy()` 반환).
- LLM·Streamlit·전역 상태에 의존하지 않는다.
- 잘못된 입력은 `KeyError`(컬럼 미존재) 또는 `ValueError`(인자 오류)로
  올린다 — executor가 한국어 안내로 변환한다.

### 1-2. 스키마 등록 — `core/op_spec.py`

`OPERATION_SPECS`에 OpSpec을 추가합니다.

```python
OpSpec(
    "filter_missing",
    required_fields=("column",),
    input_type="table",
    output_type="table",
    prompt_example='{"type": "filter_missing", "column": "<expr>"}',
    include_in_llm_prompt=True,   # LLM이 계획에 쓸 수 있게 노출
),
```

이 한 곳 등록으로 intent 검증, 파이프라인 타입 검사, LLM 프롬프트의
스키마 예시가 모두 갱신됩니다. `include_in_llm_prompt=False`로 두면
내부 전용(규칙 라우터 전용) 연산이 됩니다.

### 1-3. 디스패치 연결 — `agent/tools.py`

핸들러를 작성하고 디스패치 테이블에 등록합니다. 컬럼 인자는 반드시
`resolve_column`을 거쳐 동의어·fuzzy 매칭이 적용되게 합니다.

```python
def _apply_filter_missing(df, op, profile):
    resolved: dict[str, str] = {}
    column = resolve_column(op["column"], df, profile)
    _track_resolution(resolved, op["column"], column)
    return _result_df(filter_missing_rows(df, column), resolved)
```

### 1-4. 검증 규칙 추가 — `core/verification.py`

해당 연산의 불변식을 정의합니다. filter 계열이면:

- 결과 행수 ≤ 입력 행수
- 컬럼 집합 동일

불변식을 정의하기 어려운 연산이라도 등록을 생략하지 말고, 가능한 가장
약한 검사(예: 컬럼 존재)라도 넣는 것을 권장합니다. 미등록 op는 "검사
부재"로 표기되어 검증 배지의 신뢰도를 떨어뜨립니다.

### 1-5. (선택) 규칙 라우팅 — `agent/router.py`

정형 한국어 패턴이 명확할 때만 규칙을 추가합니다.

```
"~이(가) 비어있는 행" → filter_missing
```

규칙 추가 시 주의: 패턴이 넓으면 LLM이 처리해야 할 질의를 잘못
가로챕니다. 골든 질의셋의 `expected_route: llm` 항목들이 이 회귀를
감지하므로, 규칙 추가 후 반드시 eval을 돌립니다.

### 1-6. 테스트와 골든 질의

- `tests/test_operations.py` — 순수 함수 단위 테스트 (정상/컬럼 미존재/빈 결과)
- `tests/test_verification.py` — 불변식 통과 + 오염 출력 감지 케이스
- `evals/golden_queries.yaml` — 자연어 질의 1개 이상 추가
  ([EVALUATION.md](EVALUATION.md) 참고)

### 체크리스트

```
[ ] core/operations.py 순수 함수 (입력 불변)
[ ] core/op_spec.py OpSpec 등록 (input/output_type 선언)
[ ] agent/tools.py 핸들러 + resolve_column 경유
[ ] core/verification.py 불변식
[ ] (선택) agent/router.py 규칙
[ ] 단위 테스트 + 검증 테스트 + 골든 질의
[ ] pytest && python evals/run_evals.py --no-llm 통과
```

---

## 2. 새 도메인 팩 추가

예시: "월별 매출 보고서" 양식을 지원한다고 가정합니다.

### 2-1. 팩 파일 생성 — `domains/monthly_sales.py`

`DomainPack`을 상속(또는 인스턴스 구성)하여 다음을 정의합니다.

```python
from domains.base import DomainPack, SummaryRowConfig

class MonthlySalesPack(DomainPack):
    def detect(self, raw_df) -> bool:
        # 헤더 행에서 이 양식 고유의 마커를 찾는다.
        # 주의: 마커는 충분히 특이해야 한다. 범용 단어("합계", "금액")로
        # 감지하면 다른 파일을 오탐한다.
        ...

    def normalize_raw(self, raw_df):
        # 병합 헤더 평탄화, 행 태깅 등 → 분석용 DataFrame
        ...

MONTHLY_SALES_PACK = MonthlySalesPack(
    name="monthly_sales",
    synonyms={"매출액": "월매출", "판매액": "월매출"},
    summary_row_config=SummaryRowConfig(...),
    example_queries=("월별 매출 합계 보여줘", ...),
)
```

핵심 필드:

| 필드 | 역할 |
|---|---|
| `detect(raw_df)` | 원본 시트가 이 양식인지 판별 (보수적으로) |
| `normalize_raw(raw_df)` | 원본 → 분석용 DataFrame 변환 |
| `synonyms` | 사용자 표현 → 실제 컬럼명 매핑 (column_resolver가 사용) |
| `summary_row_config` | 합계/소계 행 식별 방법 (자동 제외에 사용) |
| `example_queries` | 도움말·안내 문구에 노출되는 예시 질문 |
| `add_derived_metrics(df)` | 로드 시 자동 추가할 파생 컬럼 (선택) |

### 2-2. 레지스트리 등록 — `domains/registry.py`

```python
_REGISTERED_PACKS = (BUDGET_COMPARISON_PACK, MONTHLY_SALES_PACK, GENERIC_PACK)
```

**순서가 중요합니다.** `match_pack()`은 첫 번째로 `detect()`에 성공한
팩을 선택하며, `generic`은 항상 마지막 폴백입니다. 두 팩의 감지 조건이
겹칠 수 있다면 더 특이한(엄격한) 팩을 앞에 둡니다.

### 2-3. 제약 사항

- `domains/`는 **core·llm·agent를 import할 수 없습니다.** 팩에 필요한
  유틸리티는 pandas 표준 기능 또는 domains 내부에 둡니다.
- 팩은 상태를 갖지 않습니다 (모듈 레벨 싱글턴, 요청 간 공유).

### 2-4. 테스트

`tests/test_domains.py`에 최소 3종을 추가합니다.

1. 해당 양식 시트에서 `detect()` 성공 + 정규화 결과 검증
2. 다른 양식(기존 팩 픽스처)에서 `detect()` 실패 — **오탐 방지**
3. 정규화 후 라우팅·연산이 정상 동작 (executor 경유 1케이스)

### 체크리스트

```
[ ] domains/<pack>.py — detect / normalize_raw / synonyms / config
[ ] domains/registry.py 등록 (generic보다 앞, 특이도 순)
[ ] core·llm·agent import 없음 확인
[ ] tests/test_domains.py 감지 성공/오탐 방지/실행 케이스
[ ] (권장) evals 픽스처 + 골든 질의 추가
[ ] pytest 통과
```

---

## 3. 공통 원칙

- **레지스트리 밖에서 특수 처리하지 않는다.** "이 도메인일 때만
  executor에서 분기" 같은 코드는 도메인 팩 격리를 무너뜨립니다. 필요한
  차이는 팩 필드나 OpSpec으로 표현합니다.
- **하드코딩 감지 명령**으로 수시 점검합니다.

```bash
grep -rn "특정_도메인_용어" core/ agent/ llm/   # 결과 0건이어야 함
```

- 확장 작업도 커밋 단위를 작게 유지합니다: 연산 1개 = 커밋 1개.
