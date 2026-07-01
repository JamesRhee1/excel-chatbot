"""Streamlit chat UI for Excel analysis — thin wrapper around agent.executor.run()."""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.executor import run  # noqa: E402
from core.reader import load_excel, summarize  # noqa: E402

MODEL_OPTIONS = [
    "qwen3:8b",
    "qwen2.5:7b",
    "qwen3:32b",
    "llama3.3:latest",
    "gemma4:latest",
]


def _init_session_state() -> None:
    defaults = {
        "messages": [],
        "file_path": None,
        "uploaded_name": None,
        "file_summary": None,
        "preview_df": None,
        "last_result_df": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _save_upload(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="upload_")
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    return tmp.name


def _format_operation(op: dict) -> str:
    op_type = op.get("type", "?")
    if op_type == "filter":
        return f"필터 — `{op['column']}` {op['op']} {op['value']}"
    if op_type == "sort":
        direction = "오름차순" if op.get("ascending", True) else "내림차순"
        return f"정렬 — `{op['column']}` {direction}"
    if op_type == "select":
        cols = ", ".join(f"`{c}`" for c in op.get("columns", []))
        return f"컬럼 선택 — {cols}"
    if op_type == "aggregate":
        group = ", ".join(f"`{c}`" for c in op.get("group_by", []))
        return (
            f"집계 — {group} 기준 `{op['agg_column']}` "
            f"{op.get('agg_func', '')}"
        )
    return str(op)


def _operations_summary(operations: list[dict]) -> str:
    if not operations:
        return "실행된 작업이 없습니다."
    lines = [f"{i + 1}. {_format_operation(op)}" for i, op in enumerate(operations)]
    return "\n".join(lines)


def _render_file_summary() -> None:
    summary = st.session_state.file_summary
    if not summary:
        return

    st.subheader("파일 요약")
    col1, col2, col3 = st.columns(3)
    col1.metric("행", summary["rows"])
    col2.metric("열", summary["columns"])
    col3.metric("컬럼 수", len(summary["column_names"]))
    st.caption("컬럼: " + ", ".join(f"`{c}`" for c in summary["column_names"]))

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
        st.session_state.file_summary = summarize(df)
        st.session_state.preview_df = df.head(10)


def _render_chat_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("operations_summary"):
                st.info(message["operations_summary"])
            if message.get("dataframe") is not None:
                st.dataframe(message["dataframe"], use_container_width=True)


def _process_user_message(user_message: str, model: str) -> None:
    st.session_state.messages.append({"role": "user", "content": user_message})

    with st.spinner("요청을 처리하는 중..."):
        result = run(st.session_state.file_path, user_message, model=model)

    if result["success"]:
        ops_text = _operations_summary(result["operations"])
        assistant_parts = ["요청을 처리했습니다.", "", "**실행된 작업**", ops_text]

        if result["df"] is not None:
            st.session_state.last_result_df = result["df"]
            assistant_parts.extend(["", f"결과: **{len(result['df'])}행**"])
        else:
            assistant_parts.append("")
            assistant_parts.append("_(dry-run 또는 작업만 파싱됨 — 표시할 데이터 없음)_")

        if result["saved_path"]:
            assistant_parts.append(f"\n저장 경로: `{result['saved_path']}`")
        if result["backup_path"]:
            assistant_parts.append(f"백업 경로: `{result['backup_path']}`")

        assistant_content = "\n".join(assistant_parts)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "operations_summary": ops_text,
                "dataframe": result["df"],
            }
        )
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"처리하지 못했습니다.\n\n{result['error']}",
            }
        )


def main() -> None:
    st.set_page_config(page_title="Excel Chatbot", page_icon="📊", layout="wide")
    st.title("📊 Excel 분석 챗봇")
    st.caption("자연어로 Excel을 분석·수정합니다. 숫자는 코드가, 말은 LLM이.")

    _init_session_state()

    with st.sidebar:
        st.header("설정")
        model = st.selectbox("Ollama 모델", MODEL_OPTIONS, index=0)
        st.divider()
        st.markdown("**사용 예시**")
        st.markdown(
            "- 매출 1500 이상만 보여줘\n"
            "- 부서별 매출 합계\n"
            "- 매출 기준 내림차순 정렬\n"
            "- 이름과 매출만 선택해줘"
        )

    uploaded_file = st.file_uploader(
        "Excel 파일 업로드 (.xlsx)",
        type=["xlsx"],
        help="업로드 후 파일 요약과 미리보기가 표시됩니다.",
    )
    _handle_upload(uploaded_file)

    if st.session_state.file_path:
        _render_file_summary()
        st.divider()

        _render_chat_history()

        if prompt := st.chat_input("Excel에 대해 요청하세요..."):
            _process_user_message(prompt, model)
            st.rerun()

        if st.session_state.last_result_df is not None:
            buffer = io.BytesIO()
            st.session_state.last_result_df.to_excel(buffer, index=False, engine="openpyxl")
            buffer.seek(0)
            st.download_button(
                label="결과 Excel 다운로드",
                data=buffer,
                file_name="result.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.info("시작하려면 Excel 파일(.xlsx)을 업로드하세요.")


if __name__ == "__main__":
    main()
