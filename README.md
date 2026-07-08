# Excel Chatbot (로컬 LLM 기반 Excel 분석/수정)

Ollama 로컬 LLM을 활용해 자연어로 Excel 파일을 분석·수정하는 챗봇 프로젝트입니다.

## 핵심 원칙

> **숫자는 코드가, 말은 LLM이**

LLM은 사용자 의도를 구조화된 JSON 명령으로 변환만 하고, 실제 Excel 데이터 조작·계산은 검증된 순수 함수(pandas)가 수행합니다.

## 기능

### 단일 파일 분석

Excel 파일 1개를 업로드하면 자연어로 질문할 수 있습니다.

- 예실대비표 xlsx 자동 정규화 (2행 헤더 → 분석용 DataFrame)
- rule-based 라우팅 + LLM intent 파싱
- 간결한 자연어 답변 + 핵심 컬럼 표시

**예시 질문**

- "데이터에 대해서 설명"
- "당해예산 중에 가장 높은 행 찾아줘"
- "인쇄비가 얼마지"
- "비목분류별 당년도예산 합계 보여줘"

### 여러 파일 통합·비교 분석

Excel 파일 2개 이상을 업로드하면 다중 파일 모드로 전환됩니다.

- 파일별 로드·정규화 (실패한 파일은 건너뜀)
- `source_file` 컬럼이 추가된 통합 DataFrame 생성
- 파생 지표: 집행률, 잔액률, 예산대비집행차이
- 통합 CSV / Excel 다운로드

**예시 질문**

- "이 파일들 통합해줘"
- "파일별 당년도예산 합계 비교해줘"
- "인쇄비를 파일별로 비교해줘"
- "각 파일에서 당년도예산이 가장 높은 항목 알려줘"
- "전체 파일에서 예산잔액이 가장 큰 항목 5개 보여줘"
- "파일별 집행률 비교해줘"

## 프로젝트 구조

```
excel_chatbot/
├── core/              # 순수 함수: Excel 조작, 정규화, 다중 파일 연산
│   ├── reader.py
│   ├── budget_table_normalizer.py
│   ├── multi_loader.py
│   ├── dataset_builder.py
│   ├── derived_metrics.py
│   └── multi_operations.py
├── llm/               # Ollama 연동 + intent 파싱
├── agent/             # 오케스트레이션
│   ├── executor.py          # 단일 파일 (run)
│   └── multi_executor.py    # 다중 파일 (run_multi)
├── ui/                # Streamlit 챗봇 UI
└── tests/
```

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ollama]"
```

Ollama Python SDK가 필요 없으면 `pip install -e ".[dev]"` 만 설치해도 됩니다 (`requests` fallback 사용).

## Streamlit UI 실행

Ollama가 실행 중이어야 합니다 (`http://localhost:11434`).

```bash
cd excel_chatbot
source .venv/bin/activate
streamlit run ui/app.py
```

브라우저에서 열리면 Excel 파일을 업로드하고 채팅으로 요청하세요.

- **파일 1개**: 기존 단일 파일 분석 (`agent.executor.run`)
- **파일 2개 이상**: 다중 파일 통합·비교 (`agent.multi_executor.run_multi`)

## 테스트

```bash
pytest
```

## 구현 현황

- [x] 단일 파일 분석 (`executor.run`)
- [x] 예실대비표 자동 정규화
- [x] 간결한 응답 포맷 (`response_formatter`)
- [x] 다중 파일 로드·통합 (`multi_loader`, `dataset_builder`)
- [x] 다중 파일 비교·집계 (`multi_operations`, `multi_executor`)
- [x] 통합 CSV/XLSX 다운로드
