"""Build combined dataset from multiple file load results."""

from __future__ import annotations

import pandas as pd


def build_combined_dataset(file_results: list[dict]) -> pd.DataFrame:
    """Concatenate successful normalized DataFrames with source metadata columns."""
    frames: list[pd.DataFrame] = []

    for result in file_results:
        if not result.get("success"):
            continue
        df = result.get("normalized_df")
        if df is None or df.empty:
            continue

        part = df.copy()
        part.insert(0, "source_file", result.get("file_name", "unknown"))
        sheet = result.get("sheet_name")
        if sheet is not None:
            part.insert(1, "source_sheet", sheet)
        frames.append(part)

    if not frames:
        raise ValueError("통합할 수 있는 파일이 없습니다. 모든 파일 로드에 실패했습니다.")

    combined = pd.concat(frames, ignore_index=True, sort=False)
    return combined.reset_index(drop=True)
