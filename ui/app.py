"""Streamlit chat UI for adaptive Excel analysis."""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.executor import run  # noqa: E402
from core.profiler import profile_dataframe  # noqa: E402
from core.reader import load_excel  # noqa: E402

MODEL_OPTIONS = [
    "qwen2.5:7b",
    "qwen3:8b",
    "qwen3:32b",
    "llama3.3:latest",
    "gemma4:latest",
]

# Bump when response/UI behavior changes so stale chat sessions reset.
APP_VERSION = "2026-07-02-concise-response"


def _init_session_state() -> None:
    defaults = {
        "messages": [],
        "file_path": None,
        "uploaded_name": None,
        "profile": None,
        "preview_df": None,
        "last_result_df": None,
        "app_version": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.app_version != APP_VERSION:
        st.session_state.app_version = APP_VERSION
        st.session_state.messages = []
        st.session_state.last_result_df = None


def _save_upload(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="upload_")
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    return tmp.name


def _format_operation(op: dict) -> str:
    op_type = op.get("type", "?")
    mapping = {
        "filter": lambda o: f"필터 — `{o['column']}` {o['op']} {o['value']}",
        "sort": lambda o: f"정렬 — `{o['column']}` {'오름차순' if o.get('ascending', True) else '내림차순'}",
        "select": lambda o: f"컬럼 선택 — {', '.join(f'`{c}`' for c in o.get('columns', []))}",
        "aggregate": lambda o: f"집계 — {', '.join(o.get('group_by', []))} / `{o.get('agg_column')}` {o.get('agg_func')}",
        "top_n": lambda o: f"상위 {o.get('n', 1)}행 — `{o['column']}`",
        "lookup": lambda o: f"검색 — `{o['query']}`",
        "describe_dataset": lambda o: "데이터셋 설명",
        "value_answer": lambda o: f"금액 조회 — `{o.get('row_query', '')}`",
        "help": lambda o: "도움말",
        "exclude_summary": lambda o: "합계/소계 행 제외",
        "filter_row_type": lambda o: f"행구분 필터 — {', '.join(o.get('row_types', []))}",
        "clarify": lambda o: "답변 불가",
    }
    fn = mapping.get(op_type)
    return fn(op) if fn else str(op)


def _operations_summary(operations: list[dict]) -> str | None:
    if not operations:
        return None
    return "\n".join(f"{i + 1}. {_format_operation(op)}" for i, op in enumerate(operations))


def _format_error_message(error: str) -> str:
    if "컬럼" in error and "찾" in error:
        category = "컬럼 없음"
    elif "json" in error.lower() or "분석하지 못" in error:
        category = "질문 분석 실패"
    elif "ollama" in error.lower() or "연결" in error:
        category = "Ollama 연결 실패"
    else:
        category = "처리 오류"
    return f"**[{category}]** {error}"


def _render_profile_summary() -> None:
    profile = st.session_state.profile
    if not profile:
        return

    st.subheader("파일 프로필")
    col1, col2, col3 = st.columns(3)
    col1.metric("행", profile["rows"])
    col2.metric("열", profile["columns"])
    col3.metric("금액 컬럼", len(profile.get("likely_amount_columns", [])))

    if profile.get("likely_amount_columns"):
        st.caption("금액/예산: " + ", ".join(f"`{c}`" for c in profile["likely_amount_columns"]))
    if profile.get("likely_name_columns"):
        st.caption("항목/이름: " + ", ".join(f"`{c}`" for c in profile["likely_name_columns"]))
    if profile.get("likely_category_columns"):
        st.caption("분류: " + ", ".join(f"`{c}`" for c in profile["likely_category_columns"]))

    with st.expander("이 파일에서 해볼 수 있는 질문 예시"):
        examples = [
            "데이터에 대해서 설명",
            "니가 할 수 있는게 뭐야",
            "당해예산 중에 가장 높은 값인 행을 찾아줘",
            "인쇄비가 얼마지",
        ]
        if profile.get("likely_category_columns") and profile.get("likely_amount_columns"):
            examples.append(
                f"{profile['likely_category_columns'][0]}별 "
                f"{profile['likely_amount_columns'][0]} 합계 보여줘"
            )
        for ex in examples:
            st.markdown(f"- {ex}")

    if st.session_state.preview_df is not None:
        st.dataframe(st.session_state.preview_df, use_container_width=True)


def _handle_upload(uploaded_file) -> None:
    if uploaded_file is None:
        return
    if uploaded_file.name != st.session_state.uploaded_name:
        st.session_state.file_path = _save_upload(uploaded_file)
        st.session_state.uploaded_name = uploaded_file.name
        st.session_state.messages = []
        st.session_state.last_result_df = None
        df = load_excel(st.session_state.file_path)
        st.session_state.profile = profile_dataframe(df)
        st.session_state.preview_df = df.head(10)


def _render_chat_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("dataframe") is not None:
                st.dataframe(message["dataframe"], use_container_width=True)
            if message.get("raw_df") is not None:
                with st.expander("전체 결과 보기"):
                    st.dataframe(message["raw_df"], use_container_width=True)
            debug_logs = message.get("debug_logs") or []
            ops_text = message.get("operations_summary")
            if debug_logs or ops_text:
                with st.expander("처리 과정 보기"):
                    if ops_text:
                        st.markdown(ops_text)
                    for log in debug_logs:
                        st.caption(log)


def _process_user_message(user_message: str, model: str) -> None:
    st.session_state.messages.append({"role": "user", "content": user_message})
    if not st.session_state.file_path:
        st.session_state.messages.append({"role": "assistant", "content": "엑셀 파일을 먼저 업로드하세요."})
        return

    with st.spinner("데이터를 분석하는 중..."):
        result = run(st.session_state.file_path, user_message, model=model)

    if result["success"]:
        content = result.get("message") or "요청을 처리했습니다."
        ops_text = _operations_summary(result.get("operations", []))
        raw_df = result.get("raw_df")
        display_df = result.get("df")
        if raw_df is not None or display_df is not None:
            st.session_state.last_result_df = raw_df if raw_df is not None else display_df
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": content,
                "operations_summary": ops_text,
                "dataframe": display_df,
                "raw_df": raw_df,
                "debug_logs": result.get("debug_logs", []),
            }
        )
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": _format_error_message(result.get("error") or "알 수 없는 오류"),
            }
        )


def main() -> None:
    st.set_page_config(page_title="Excel Chatbot", page_icon="📊", layout="wide")
    st.title("📊 Excel 분석 챗봇")
    st.caption("숫자는 pandas가 계산하고, LLM이 결과를 설명합니다.")

    _init_session_state()

    with st.sidebar:
        st.header("설정")
        model = st.selectbox("Ollama 모델", MODEL_OPTIONS, index=0)

    uploaded_file = st.file_uploader("Excel 파일 업로드 (.xlsx)", type=["xlsx"])
    _handle_upload(uploaded_file)

    if st.session_state.file_path:
        _render_profile_summary()
        st.divider()
        _render_chat_history()
        if prompt := st.chat_input("Excel에 대해 요청하세요..."):
            _process_user_message(prompt, model)
            st.rerun()
        if st.session_state.last_result_df is not None:
            buffer = io.BytesIO()
            st.session_state.last_result_df.to_excel(buffer, index=False, engine="openpyxl")
            buffer.seek(0)
            st.download_button("결과 Excel 다운로드", buffer, file_name="result.xlsx")
    else:
        st.info("시작하려면 Excel 파일(.xlsx)을 업로드하세요.")


if __name__ == "__main__":
    main()
