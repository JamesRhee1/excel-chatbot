# Excel Chatbot (로컬 LLM 기반 Excel 분석/수정)

Ollama 로컬 LLM을 활용해 자연어로 Excel 파일을 분석·수정하는 챗봇 프로젝트입니다.

## 핵심 원칙

> **숫자는 코드가, 말은 LLM이**

LLM은 사용자 의도를 구조화된 JSON 명령으로 변환만 하고, 실제 Excel 데이터 조작·계산은 검증된 순수 함수(pandas)가 수행합니다. LLM 환각으로 인한 데이터 손상을 원천 차단합니다.

## 프로젝트 구조

```
excel_chatbot/
├── core/              # 순수 함수: Excel 조작 (LLM 의존성 없음)
├── llm/               # Ollama 연동 + intent 파싱
├── agent/             # 오케스트레이션 (executor.run)
├── ui/                # Streamlit 챗봇 UI
│   └── app.py
└── tests/
```

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Streamlit UI 실행

Ollama가 실행 중이어야 합니다 (`http://localhost:11434`).

```bash
cd excel_chatbot
source .venv/bin/activate
streamlit run ui/app.py
```

브라우저에서 열리면 Excel 파일을 업로드하고, 사이드바에서 모델을 선택한 뒤 채팅으로 요청하세요.

모델 기본값은 사이드바 드롭다운에서 선택합니다. 환경변수로 기본 모델을 바꾸려면:

```bash
OLLAMA_MODEL=qwen3:8b streamlit run ui/app.py
```

## 테스트

```bash
# mock 테스트 (기본)
pytest tests/ -v

# Ollama 연동 테스트
pytest tests/ -v -m integration
```

## 구현 현황

- [x] `core/` — Excel 읽기/조작/저장
- [x] `llm/` — Ollama 연동, intent JSON 파싱
- [x] `agent/` — `executor.run()` 오케스트레이션
- [x] `ui/app.py` — Streamlit 챗봇 UI
