"""Streamlit chat UI for adaptive Excel analysis."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from agent.executor import run
from agent.multi_executor import run_multi
from core.multi_loader import load_multiple_excels
from core.profiler import profile_dataframe
from core.reader import load_excel, load_excel_with_domain, list_sheets, summarize

MODEL_OPTIONS = [
    "qwen2.5:7b",
    "qwen3:8b",
    "qwen3:32b",
    "llama3.3:latest",
    "gemma4:latest",
]

APP_VERSION = "2026-07-02-multi-file"


def _init_session_state() -> None:
    defaults = {
        "messages": [],
        "file_path": None,
        "uploaded_name": None,
        "profile": None,
        "preview_df": None,
        "last_result_df": None,
        "app_version": None,
        "multi_mode": False,
        "uploaded_files_info": [],
        "file_results": [],
        "combined_df": None,
        "last_combined_df": None,
        "last_multi_result_df": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.app_version != APP_VERSION:
        st.session_state.app_version = APP_VERSION
        st.session_state.messages = []
        st.session_state.last_result_df = None
        st.session_state.last_combined_df = None
        st.session_state.last_multi_result_df = None


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
        "filter_row_type": lambda o: f"행 유형 필터 — {', '.join(o.get('row_types', []))}",
        "combine_dataset": lambda o: "다중 파일 통합",
        "summarize_by_file": lambda o: f"파일별 집계 — `{o.get('value_column', '')}`",
        "compare_item_across_files": lambda o: f"파일별 항목 비교 — `{o.get('item_query', '')}`",
        "top_n_by_file": lambda o: f"파일별 상위 — `{o.get('value_column', '')}`",
        "top_n_overall": lambda o: f"전체 상위 — `{o.get('value_column', '')}`",
        "multi_summary": lambda o: "다중 파일 요약",
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


def _render_single_profile_summary() -> None:
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
        ]
        examples.extend(profile.get("domain_example_queries", [])[:4])
        if not profile.get("domain_example_queries") and profile.get("likely_category_columns") and profile.get("likely_amount_columns"):
            examples.append(
                f"{profile['likely_category_columns'][0]}별 "
                f"{profile['likely_amount_columns'][0]} 합계 보여줘"
            )
        for ex in examples:
            st.markdown(f"- {ex}")

    if st.session_state.preview_df is not None:
        st.dataframe(st.session_state.preview_df, use_container_width=True)


def _render_multi_profile_summary() -> None:
    st.subheader("다중 파일 모드")
    file_results = st.session_state.file_results
    if not file_results:
        return

    ok_count = sum(1 for r in file_results if r["success"])
    st.caption(f"업로드 {len(file_results)}개 · 성공 {ok_count}개 · 실패 {len(file_results) - ok_count}개")

    rows = []
    for r in file_results:
        rows.append(
            {
                "파일명": r["file_name"],
                "상태": "성공" if r["success"] else "실패",
                "행 수": len(r["normalized_df"]) if r["success"] and r["normalized_df"] is not None else "-",
                "오류": r.get("error") or "",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    combined = st.session_state.combined_df
    if combined is not None:
        st.metric("통합 데이터셋 행 수", len(combined))
        st.dataframe(combined.head(10), use_container_width=True)

    with st.expander("다중 파일 질문 예시"):
        multi_examples = ["이 파일들 통합해줘"]
        combined_profile = st.session_state.get("combined_profile") or {}
        multi_examples.extend(combined_profile.get("domain_multi_example_queries", [])[:5])
        if not combined_profile.get("domain_multi_example_queries"):
            multi_examples.extend([
                "파일별 금액 합계 비교해줘",
                "항목을 파일별로 비교해줘",
            ])
        for ex in multi_examples:
            st.markdown(f"- {ex}")


def _handle_uploads(uploaded_files: list | None) -> None:
    if not uploaded_files:
        return

    names = tuple(f.name for f in uploaded_files)
    if names == tuple(st.session_state.uploaded_files_info):
        return

    st.session_state.uploaded_files_info = list(names)
    st.session_state.messages = []
    st.session_state.last_result_df = None
    st.session_state.last_multi_result_df = None
    st.session_state.last_combined_df = None

    if len(uploaded_files) == 1:
        st.session_state.multi_mode = False
        st.session_state.file_results = []
        st.session_state.combined_df = None
        f = uploaded_files[0]
        st.session_state.file_path = _save_upload(f)
        st.session_state.uploaded_name = f.name
        df, domain = load_excel_with_domain(st.session_state.file_path)
        st.session_state.profile = profile_dataframe(df, domain=domain)
        st.session_state.preview_df = df.head(10)
        return

    st.session_state.multi_mode = True
    st.session_state.file_path = None
    st.session_state.uploaded_name = None
    st.session_state.profile = None
    st.session_state.preview_df = None

    file_results = load_multiple_excels(uploaded_files)
    st.session_state.file_results = file_results

    # Build combined preview for multi mode
    try:
        from core.dataset_builder import build_combined_dataset
        from domains.registry import apply_derived_metrics

        combined = build_combined_dataset(file_results)
        domain = profile_dataframe(combined).get("domain", "generic")
        combined = apply_derived_metrics(combined, domain)
        st.session_state.combined_df = combined
        st.session_state.last_combined_df = combined
    except ValueError:
        st.session_state.combined_df = None


def _render_chat_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("dataframe") is not None:
                st.dataframe(message["dataframe"], use_container_width=True)
            if message.get("raw_df") is not None:
                with st.expander("전체 결과 보기"):
                    st.dataframe(message["raw_df"], use_container_width=True)
            if message.get("combined_df") is not None:
                with st.expander("통합 데이터 전체 보기"):
                    st.dataframe(message["combined_df"], use_container_width=True)
            debug_logs = message.get("debug_logs") or []
            ops_text = message.get("operations_summary")
            if debug_logs or ops_text:
                with st.expander("처리 과정 보기"):
                    if ops_text:
                        st.markdown(ops_text)
                    for log in debug_logs:
                        st.caption(log)


def _append_assistant_message(result: dict) -> None:
    content = result.get("message") or "요청을 처리했습니다."
    ops_text = _operations_summary(result.get("operations", []))
    raw_df = result.get("raw_df")
    display_df = result.get("df")
    combined_df = result.get("combined_df")

    if display_df is not None:
        st.session_state.last_result_df = display_df
    if combined_df is not None:
        st.session_state.last_combined_df = combined_df
        st.session_state.combined_df = combined_df
    if raw_df is not None:
        st.session_state.last_multi_result_df = raw_df

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": content,
            "operations_summary": ops_text,
            "dataframe": display_df,
            "raw_df": raw_df,
            "combined_df": combined_df if combined_df is not None and display_df is not combined_df else None,
            "debug_logs": result.get("debug_logs", []),
        }
    )


def _process_user_message(user_message: str, model: str) -> None:
    st.session_state.messages.append({"role": "user", "content": user_message})

    if st.session_state.multi_mode:
        if not st.session_state.file_results:
            st.session_state.messages.append({"role": "assistant", "content": "엑셀 파일을 먼저 업로드하세요."})
            return
        with st.spinner("다중 파일을 분석하는 중..."):
            result = run_multi(st.session_state.file_results, user_message, model=model)
    else:
        if not st.session_state.file_path:
            st.session_state.messages.append({"role": "assistant", "content": "엑셀 파일을 먼저 업로드하세요."})
            return
        with st.spinner("데이터를 분석하는 중..."):
            result = run(st.session_state.file_path, user_message, model=model)

    if result["success"]:
        _append_assistant_message(result)
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": _format_error_message(result.get("error") or "알 수 없는 오류"),
            }
        )


def _render_download_buttons() -> None:
    if st.session_state.multi_mode and st.session_state.last_combined_df is not None:
        combined = st.session_state.last_combined_df
        csv_buffer = io.BytesIO()
        combined.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
        csv_buffer.seek(0)
        st.download_button(
            "통합 CSV 다운로드",
            csv_buffer,
            file_name="combined_budget_dataset.csv",
            mime="text/csv",
        )
        xlsx_buffer = io.BytesIO()
        combined.to_excel(xlsx_buffer, index=False, engine="openpyxl")
        xlsx_buffer.seek(0)
        st.download_button(
            "통합 Excel 다운로드",
            xlsx_buffer,
            file_name="combined_budget_dataset.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    elif not st.session_state.multi_mode and st.session_state.last_result_df is not None:
        buffer = io.BytesIO()
        st.session_state.last_result_df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        st.download_button("결과 Excel 다운로드", buffer, file_name="result.xlsx")


def main() -> None:
    st.set_page_config(page_title="Excel Chatbot", page_icon="📊", layout="wide")
    st.title("📊 Excel 분석 챗봇")
    st.caption("숫자는 pandas가 계산하고, LLM이 결과를 설명합니다.")

    _init_session_state()

    with st.sidebar:
        st.header("설정")
        model = st.selectbox("Ollama 모델", MODEL_OPTIONS, index=0)
        if st.session_state.multi_mode:
            st.info("다중 파일 모드")

    uploaded_files = st.file_uploader(
        "Excel 파일 업로드 (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True,
    )
    _handle_uploads(uploaded_files)

    has_data = st.session_state.file_path or (
        st.session_state.multi_mode and st.session_state.file_results
    )

    if has_data:
        if st.session_state.multi_mode:
            _render_multi_profile_summary()
        else:
            _render_single_profile_summary()
        st.divider()
        _render_chat_history()
        if prompt := st.chat_input("Excel에 대해 요청하세요..."):
            _process_user_message(prompt, model)
            st.rerun()
        _render_download_buttons()
    else:
        st.info("시작하려면 Excel 파일(.xlsx)을 업로드하세요. 여러 파일을 선택하면 통합·비교 분석 모드로 전환됩니다.")


if __name__ == "__main__":
    main()
