from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st

from railroad_frontend.components.ui_components import render_page_header, render_help_tooltip
from railroad_backend.services.network_editor import (
    add_month_with_backfill,
    default_segment_name_sequence,
    month_label,
    network_file_digest,
    serialize_network_editor_state,
    set_state_mtbt_df,
    sync_mtbt_dataframe_with_segments,
)
from railroad_backend.services.schedule_service import (
    MONTH_COLUMN_PATTERN,
    blank_mtbt_dataframe,
    normalize_mtbt_dataframe,
)


@dataclass(frozen=True)
class MtbtEditorCallbacks:
    """Bridges the Streamlit app state into the MTBT editor view."""

    state_key: str
    ensure_state: Callable[[], Dict[str, Any]]
    render_schedule_network_alert: Callable[[], None]
    force_rerun: Callable[[], None]
    current_network_file_path: Callable[[], Path]
    parse_schedule_bytes: Callable[[bytes], pd.DataFrame]


def render_mtbt_editor_page(*, default_schedule: Path, callbacks: MtbtEditorCallbacks) -> None:
    """Render the MTBT editor tab within the Streamlit app."""

    state = callbacks.ensure_state()
    sync_mtbt_dataframe_with_segments(state)
    df = normalize_mtbt_dataframe(state.get("mtbt_df", pd.DataFrame()).copy(deep=True))
    
    render_page_header(
        title="MTBT Schedule Editor",
        icon="📅",
        description="Define maintenance schedules and Mean Time Between Tests (MTBT) for each segment.",
        workflow_step="Step 2 of 4: Set MTBT"
    )
    
    callbacks.render_schedule_network_alert()
    
    render_help_tooltip(
        "MTBT values represent maintenance thresholds for each segment. The schedule automatically syncs with your network segments."
    )

    def _apply_df_update(updated: pd.DataFrame) -> None:
        """Update the MTBT dataframe in state and mark as dirty (unsaved)."""
        normalized = normalize_mtbt_dataframe(updated)
        if not normalized.equals(state.get("mtbt_df", pd.DataFrame())):
            set_state_mtbt_df(state, normalized)
            state["dirty"] = True

    helper_cols = st.columns([1, 3])
    if helper_cols[0].button("Reset from segments", use_container_width=True):
        fresh = blank_mtbt_dataframe(
            default_segment_name_sequence(state),
            default_schedule=default_schedule,
        )
        _apply_df_update(fresh)
        st.success("Rebuilt MTBT table using the current segment list.")
        callbacks.force_rerun()
    helper_cols[1].markdown("Initial Load stays pinned next to Segment Name—set it to 0 when unused.")

    month_cols = sorted(col for col in df.columns if MONTH_COLUMN_PATTERN.match(str(col)))
    if month_cols:
        last_label = month_cols[-1]
        last_year = int(last_label.split("-")[0])
        last_month = int(last_label.split("-")[1])
        if last_month == 12:
            default_year = last_year + 1
            default_month = 1
        else:
            default_year = last_year
            default_month = last_month + 1
    else:
        now = datetime.now()
        default_year = now.year
        default_month = now.month

    pending_year = st.session_state.pop("_mtbt_pending_year", None)
    pending_month = st.session_state.pop("_mtbt_pending_month", None)
    st.session_state.setdefault("mtbt_year", default_year)
    st.session_state.setdefault("mtbt_month", default_month)
    if pending_year is not None:
        st.session_state["mtbt_year"] = pending_year
    if pending_month is not None:
        st.session_state["mtbt_month"] = pending_month
    st.session_state["mtbt_year"] = max(2020, min(2050, st.session_state.get("mtbt_year", default_year)))
    st.session_state["mtbt_month"] = max(1, min(12, st.session_state.get("mtbt_month", default_month)))

    add_cols = st.columns([1, 1, 1, 1])
    year_value = int(
        add_cols[0].number_input(
            "Year",
            min_value=2020,
            max_value=2050,
            value=st.session_state["mtbt_year"],
            step=1,
            key="mtbt_year",
        )
    )
    month_value = int(
        add_cols[1].selectbox(
            "Month",
            options=list(range(1, 13)),
            format_func=lambda m: _MONTH_LABELS[m - 1],
            index=st.session_state["mtbt_month"] - 1,
            key="mtbt_month",
        )
    )
    default_mtbt = add_cols[2].number_input(
        "Default MTBT",
        min_value=0.0,
        value=10.0,
        step=5.0,
        key="editor_default_mtbt",
    )
    if add_cols[3].button("Add month column", use_container_width=True):
        updated_df, inserted = add_month_with_backfill(df, year_value, month_value, float(default_mtbt))
        if not inserted and month_label(year_value, month_value) in df.columns:
            pass  # Month already exists
        else:
            _apply_df_update(updated_df)
            df = normalize_mtbt_dataframe(updated_df.copy(deep=True))
            inserted_msg = ", ".join(inserted) if inserted else month_label(year_value, month_value)
            st.success(f"Added column(s): {inserted_msg}")
            next_year, next_month = year_value, month_value + 1
            if next_month == 13:
                next_month = 1
                next_year += 1
            st.session_state["_mtbt_pending_year"] = max(2020, min(2050, next_year))
            st.session_state["_mtbt_pending_month"] = next_month
            callbacks.force_rerun()

    st.markdown("### Delete column")
    delete_candidates = [col for col in df.columns if col not in {"Segment Name", "Initial Load"}]
    if delete_candidates:
        col_del = st.columns([3, 1])
        column_to_delete = col_del[0].selectbox("Select column to delete", delete_candidates, key="editor_delete_column")
        if col_del[1].button("Delete column", key="editor_delete_button"):
            df = normalize_mtbt_dataframe(df.drop(columns=[column_to_delete]))
            _apply_df_update(df)
            st.success(f"Deleted column '{column_to_delete}'.")
    # else: No removable columns

    st.markdown("### Schedule data")
    edited_df = st.data_editor(
        df,
        key="mtbt_editor_table",
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Segment Name": st.column_config.TextColumn(
                "Segment Name",
                help="Segment names are controlled by the network editor.",
                disabled=True,
            ),
            "Initial Load": st.column_config.NumberColumn(
                "Initial Load",
                help="Always available; set to 0 if you don't track initial loads.",
                min_value=0.0,
                step=1.0,
            ),
        },
    )
    if not edited_df.equals(df):
        normalized = normalize_mtbt_dataframe(edited_df.copy())
        _apply_df_update(normalized)
        df = normalized

    st.markdown("### Import/export")
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    col_download, col_apply = st.columns(2)
    col_download.download_button(
        "Download embedded CSV",
        data=csv_bytes,
        file_name=f"{state.get('display_name', 'network')}_mtbt.csv",
        mime="text/csv",
    )
    upload_col, action_col = st.columns([3, 1])
    uploaded_editor_file = upload_col.file_uploader("Upload CSV to replace", type="csv", key="editor_upload")
    if action_col.button("Replace table", disabled=uploaded_editor_file is None):
        if uploaded_editor_file is None:
            st.warning("Select a file before loading.")
        else:
            new_bytes = uploaded_editor_file.getvalue()
            try:
                new_df = normalize_mtbt_dataframe(callbacks.parse_schedule_bytes(new_bytes))
            except ValueError as exc:
                st.error(f"Uploaded schedule is invalid: {exc}")
            else:
                _apply_df_update(new_df)
                sync_mtbt_dataframe_with_segments(state)
                st.success(f"Loaded {uploaded_editor_file.name} into the editor.")
                callbacks.force_rerun()

    save_cols = st.columns([2, 3])
    save_disabled = not state.get("dirty")
    
    if save_cols[0].button("💾 Save MTBT to network file", disabled=save_disabled, use_container_width=True):
        path_str = state.get("path") or str(callbacks.current_network_file_path())
        path = Path(path_str)
        try:
            payload = serialize_network_editor_state(state)
            _write_network_payload(path, payload)
            state["dirty"] = False
            state["raw_payload"] = payload
            state["digest"] = network_file_digest(path)
            st.session_state[callbacks.state_key] = state
            st.success(f"✅ MTBT schedule saved to {path.name}")
            st.rerun()
        except ValueError as exc:
            st.error(f"❌ Unable to build network payload: {exc}")
        except Exception as exc:
            st.error(f"❌ Failed to write network file: {exc}")
    
    if save_disabled:
        save_cols[1].caption("✓ All changes saved")
    else:
        save_cols[1].caption("⚠️ You have unsaved changes")
    
    st.caption("MTBT changes live inside the network JSON—save them when you're satisfied.")
    st.session_state[callbacks.state_key] = state


def _write_network_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


_MONTH_LABELS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


__all__ = [
    "MtbtEditorCallbacks",
    "render_mtbt_editor_page",
]
