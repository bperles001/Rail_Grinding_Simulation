from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd
import streamlit as st

from railroad_frontend.components.ui_components import (
    render_page_header,
    render_getting_started,
    render_validation_message,
    render_success_toast,
    render_field_hint,
    validate_required_field,
    validate_numeric_range,
    validate_unique_in_list,
)
from railroad_backend.domain.network_editor import slugify_filename
from railroad_backend.services.network_editor import (
    _ALLOWED_DIRECTION_CHOICES,
    allowed_movements_text_from_choice,
    collect_network_editor_issues,
    infer_allowed_direction_label,
    network_editor_diff_summary,
    segment_endpoint_status,
    spur_rows_from_text,
    spur_text_from_rows,
    sync_mtbt_dataframe_with_segments,
)
from src.utils.network_loader import NetworkConfig


@dataclass(frozen=True)
class NetworkEditorCallbacks:
    """Bridge callbacks for the network editor view."""

    state_key: str
    ensure_state: Callable[[], Dict[str, Any]]
    current_config: Callable[[], NetworkConfig]
    current_path: Callable[[], Path]
    render_schedule_network_alert: Callable[[], None]
    consume_flash: Callable[[], None]
    consume_refresh_notice: Callable[[], None]
    schedule_refresh_notice: Callable[[str], None]
    dataframe_signature: Callable[[Optional[pd.DataFrame]], str]
    serialize_state: Callable[[Dict[str, Any]], Dict[str, Any]]
    write_network_payload: Callable[[Path, Dict[str, Any]], None]
    network_file_digest: Callable[[Path], str]
    set_flash: Callable[..., None]
    apply_network_change: Callable[[str, Optional[str]], None]
    clear_widgets: Callable[[], None]
    force_rerun: Callable[[], None]
    render_network_layout_controls: Callable[[Dict[str, Any]], None]
    network_figure_factory: Callable[[], Any]
    render_matplotlib_image: Callable[[Any, str], Optional[bytes]]
    create_blank_network_file: Callable[[str, Optional[str], bool], Path]
    duplicate_active_network_file: Callable[[str, Optional[str]], Path]
    import_uploaded_network: Callable[[bytes, str, Optional[str]], Path]
    delete_network_file: Callable[[Path], None]
    network_file_candidates: Callable[[], Sequence[str]]


def render_network_editor_page(*, callbacks: NetworkEditorCallbacks) -> None:
    """Render the network editor tab."""

    config = callbacks.current_config()
    path = callbacks.current_path()
    state = callbacks.ensure_state()
    
    render_page_header(
        title="Network Editor",
        icon="🛤️",
        description="Configure stations, segments, and corridor layout for your railroad network.",
        workflow_step="Step 1 of 4: Configure Network"
    )
    
    callbacks.render_schedule_network_alert()
    callbacks.consume_flash()
    callbacks.consume_refresh_notice()
    
    render_getting_started(
        title="Configure Your Network",
        steps=[
            "Add stations and mark which ones allow turns",
            "Define segments connecting your stations",
            "Set 'Allowed direction' for each segment",
            "Save your changes when ready"
        ]
    )
    st.markdown("### Display name")
    display_name_input = st.text_input(
        "Sidebar display name",
        value=state.get("display_name", config.name),
        help="This label appears in the sidebar network selector.",
    )
    if display_name_input != state.get("display_name"):
        state["display_name"] = display_name_input
        state["dirty"] = True
    current_display = (config.name or "").strip()
    pending_display = display_name_input.strip()
    if pending_display != current_display:
        st.caption(
            f"Pending rename: {current_display or '(unnamed)'} → {pending_display or '(blank)'}"
        )
    col_stats = st.columns(2)
    col_stats[0].metric("Stations", f"{len(state['stations_df'])}")
    col_stats[1].metric("Segments", f"{len(state['segments_df'])}")

    if state.get("dirty"):
        st.warning("You have unsaved network changes.")

    st.markdown("### ⚙️ Stations")
    st.caption("Define the stations in your network. Enable 'Can turn' for stations where the grinder can reverse direction.")
    
    prev_station_df = state["stations_df"].copy(deep=True)
    station_source = prev_station_df.copy(deep=True)
    prev_station_sig = state.get("_stations_signature") or callbacks.dataframe_signature(prev_station_df)
    
    with st.form("station_editor_form", clear_on_submit=False):
        station_editor = st.data_editor(
            station_source,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "Name": st.column_config.TextColumn("Name", help="Station code (must be unique). Use short codes (e.g., AAA, BBB)."),
                "Can turn": st.column_config.CheckboxColumn("Can turn", help="Enable if the grinder can flip here."),
            },
        )
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            station_submit = st.form_submit_button("Apply Station Changes", use_container_width=True)
    
    if station_submit:
        station_editor = station_editor.copy(deep=True)
        station_editor["Name"] = station_editor["Name"].astype(str)
        station_editor["Can turn"] = station_editor["Can turn"].fillna(False).astype(bool)
        station_editor = station_editor.reset_index(drop=True)
        prev_station_df = prev_station_df.reset_index(drop=True)
        
        # Real-time validation for stations
        validation_errors = []
        station_names = station_editor["Name"].astype(str).tolist()
        
        for idx, name in enumerate(station_names):
            name = name.strip()
            # Check for empty names
            if not name:
                validation_errors.append(f"Row {idx + 1}: Station name is required")
            # Check for duplicates
            elif station_names.count(name) > 1:
                validation_errors.append(f"Row {idx + 1}: Station name '{name}' is duplicated")
        
        if validation_errors:
            for error in validation_errors[:3]:  # Show max 3 errors
                render_validation_message(error, type="error")
            if len(validation_errors) > 3:
                render_validation_message(f"... and {len(validation_errors) - 3} more error(s)", type="warning")
        
        current_station_sig = callbacks.dataframe_signature(station_editor)
        state["stations_df"] = station_editor.copy(deep=True)
        state["_stations_signature"] = current_station_sig
        if current_station_sig != prev_station_sig:
            state["dirty"] = True
            st.session_state[callbacks.state_key] = state
            st.rerun()

    st.markdown("### 🛤️ Segments")
    st.caption("Define the segments connecting your stations. Each segment represents a section of track that can be maintained.")
    
    prev_segment_df = state["segments_df"].copy(deep=True)
    segment_source = prev_segment_df.copy(deep=True)
    station_name_values = state["stations_df"]["Name"].astype(str).tolist()
    station_sequence = [name.strip() for name in station_name_values if name and name.strip()]
    station_options = sorted(station_sequence)
    if not station_options:
        station_options = [""]
    if not segment_source.empty:
        segment_source["Allowed direction"] = segment_source.apply(
            lambda row: infer_allowed_direction_label(
                str(row.get("Allowed movements", "")),
                str(row.get("Start", "")).strip(),
            str(row.get("End", "")).strip(),
            ),
            axis=1,
        )
        segment_source["Endpoint status"] = segment_source.apply(
            lambda row: segment_endpoint_status(
                str(row.get("Start", "")),
                str(row.get("End", "")),
                station_options,
        ),
        axis=1,
    )
    else:
        segment_source["Allowed direction"] = []
        segment_source["Endpoint status"] = []
    prev_segment_sig = state.get("_segments_signature") or callbacks.dataframe_signature(prev_segment_df)
    
    with st.form("segment_editor_form", clear_on_submit=False):
        segment_editor = st.data_editor(
            segment_source,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_order=[
                "Name",
                "Start",
                "End",
                "Length (km)",
                "Curve length (km)",
                "Tangent length (km)",
                "MTBT threshold",
                "Move days",
                "Maintenance days",
                "Move billed days",
                "Maintenance billed days",
                "Allowed direction",
                "Allowed movements",
                "Endpoint status",
            ],
            column_config={
                "Name": st.column_config.TextColumn("Name", help="Segment identifier."),
                "Start": st.column_config.SelectboxColumn(
                    "Start",
                    options=station_options,
                    help="Choose the origin station from the table above.",
                ),
                "End": st.column_config.SelectboxColumn(
                    "End",
                    options=station_options,
                    help="Choose the destination station from the table above.",
                ),
                "Length (km)": st.column_config.NumberColumn("Length (km)", min_value=0.0, step=0.1),
                "Curve length (km)": st.column_config.NumberColumn(
                    "Curve length (km)", min_value=0.0, step=0.1,
                    help="Extensão em curva dentro deste segmento (para separar o ciclo de esmerilhamento de curva x tangente).",
                ),
                "Tangent length (km)": st.column_config.NumberColumn(
                    "Tangent length (km)", min_value=0.0, step=0.1,
                    help="Extensão em tangente dentro deste segmento.",
                ),
                "MTBT threshold": st.column_config.NumberColumn("MTBT threshold", min_value=0.0, step=10.0),
                "Move days": st.column_config.NumberColumn("Move days", min_value=0, step=1, help="Dias corridos de deslocamento."),
                "Maintenance days": st.column_config.NumberColumn("Maintenance days", min_value=0, step=1, help="Dias corridos de manutenção."),
                "Move billed days": st.column_config.NumberColumn(
                    "Move billed days", min_value=0.0, step=0.5,
                    help="Diárias pagas de deslocamento (pode ser menor que os dias corridos).",
                ),
                "Maintenance billed days": st.column_config.NumberColumn(
                    "Maintenance billed days", min_value=0.0, step=0.5,
                    help="Diárias pagas de manutenção/operação (pode ser menor que os dias corridos).",
                ),
                "Allowed direction": st.column_config.SelectboxColumn(
                    "Allowed direction",
                    options=list(_ALLOWED_DIRECTION_CHOICES),
                    help="Pick which direction(s) this segment is traversable for maintenance heuristics.",
                ),
                "Allowed movements": st.column_config.TextColumn(
                    "Allowed movements",
                    help="Derived from Allowed direction. Adjust via the dropdown.",
                    disabled=True,
                ),
                "Endpoint status": st.column_config.TextColumn(
                    "Endpoint status",
                    help="Shows whether the selected Start/End still exist in the station table.",
                    disabled=True,
                ),
            },
        )
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            segment_submit = st.form_submit_button("Apply Segment Changes", use_container_width=True)
    
    if segment_submit:
        segment_editor = segment_editor.copy(deep=True)
        for col in ("Name", "Start", "End", "Allowed movements"):
            segment_editor[col] = segment_editor[col].astype(str)
    for col in ("Length (km)", "Curve length (km)", "Tangent length (km)", "MTBT threshold", "Move billed days", "Maintenance billed days"):
        segment_editor[col] = pd.to_numeric(segment_editor[col], errors="coerce").fillna(0.0)
    for col in ("Move days", "Maintenance days"):
        segment_editor[col] = pd.to_numeric(segment_editor[col], errors="coerce").fillna(0).astype(int)
    
    # Real-time validation for segments
    validation_errors = []
    segment_names = segment_editor["Name"].astype(str).tolist()
    
    for idx in segment_editor.index:
        row_num = idx + 1
        name = str(segment_editor.at[idx, "Name"]).strip()
        start = str(segment_editor.at[idx, "Start"]).strip()
        end = str(segment_editor.at[idx, "End"]).strip()
        length = segment_editor.at[idx, "Length (km)"]
        mtbt = segment_editor.at[idx, "MTBT threshold"]
        
        # Validate segment name
        if not name:
            validation_errors.append(f"Row {row_num}: Segment name is required")
        elif segment_names.count(name) > 1:
            validation_errors.append(f"Row {row_num}: Segment '{name}' is duplicated")
        
        # Validate start/end stations
        if not start or start not in station_sequence:
            validation_errors.append(f"Row {row_num}: Invalid Start station '{start}'")
        if not end or end not in station_sequence:
            validation_errors.append(f"Row {row_num}: Invalid End station '{end}'")
        
        # Validate numeric fields
        if length <= 0:
            validation_errors.append(f"Row {row_num}: Length must be greater than 0")
        if mtbt < 0:
            validation_errors.append(f"Row {row_num}: MTBT threshold cannot be negative")
    
    if validation_errors:
        for error in validation_errors[:3]:  # Show max 3 errors
            render_validation_message(error, type="error")
        if len(validation_errors) > 3:
            render_validation_message(f"... and {len(validation_errors) - 3} more error(s)", type="warning")
    
    if "Allowed direction" in segment_editor.columns:
        for idx, label in segment_editor["Allowed direction"].items():
            start_val = str(segment_editor.at[idx, "Start"]).strip()
            end_val = str(segment_editor.at[idx, "End"]).strip()
            prev_text = str(segment_editor.at[idx, "Allowed movements"]).strip()
            segment_editor.at[idx, "Allowed movements"] = allowed_movements_text_from_choice(
                str(label or ""),
                start_val,
                end_val,
                prev_text,
            )
        segment_editor.drop(columns=["Allowed direction"], inplace=True, errors="ignore")
        segment_editor.drop(columns=["Endpoint status"], inplace=True, errors="ignore")
        segment_editor = segment_editor.reset_index(drop=True)
        prev_segment_df = prev_segment_df.reset_index(drop=True)
        current_segment_sig = callbacks.dataframe_signature(segment_editor)
        state["segments_df"] = segment_editor.copy(deep=True)
        sync_mtbt_dataframe_with_segments(state)
        state["_segments_signature"] = current_segment_sig
        if current_segment_sig != prev_segment_sig:
            state["dirty"] = True
            st.session_state[callbacks.state_key] = state
            st.rerun()

    # ── Timeline display order ──────────────────────────────────────────────
    with st.expander("📊 Timeline display order", expanded=False):
        st.caption(
            "Set the top-to-bottom order of segments in the Simulation Timeline chart. "
            "Edit the **Order** column — lower numbers appear first. "
            "Click **Apply order** to save your changes."
        )
        seg_names_current = state["segments_df"]["Name"].astype(str).tolist()
        seg_names_current = [n.strip() for n in seg_names_current if n.strip()]

        stored_order: list = list(state.get("timeline_order") or [])
        # Rebuild rows: keep stored positions, append any new segments at end
        order_map = {name: idx for idx, name in enumerate(stored_order)}
        next_pos = len(stored_order)
        order_rows = []
        for name in seg_names_current:
            if name in order_map:
                order_rows.append({"Order": order_map[name], "Segment": name})
            else:
                order_rows.append({"Order": next_pos, "Segment": name})
                next_pos += 1
        order_rows.sort(key=lambda r: r["Order"])

        with st.form("timeline_order_form", clear_on_submit=False):
            order_editor = st.data_editor(
                pd.DataFrame(order_rows),
                num_rows="fixed",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Order": st.column_config.NumberColumn("Order", min_value=0, step=1,
                        help="Lower = higher in the chart. Numbers don't need to be consecutive."),
                    "Segment": st.column_config.TextColumn("Segment", disabled=True),
                },
            )
            if st.form_submit_button("Apply order", use_container_width=False):
                sorted_rows = order_editor.sort_values("Order")
                new_order = sorted_rows["Segment"].astype(str).tolist()
                state["timeline_order"] = new_order
                state["dirty"] = True
                st.session_state[callbacks.state_key] = state
                st.rerun()

    # State already persisted after each editor
    with st.expander("⚠️ Validation & change preview", expanded=state.get("dirty", False)):
        issues = collect_network_editor_issues(state)
        has_errors = bool(issues["errors"])
        if issues["errors"]:
            st.error("Validation issues detected:\n" + "\n".join(f"• {msg}" for msg in issues["errors"]))
        elif issues["warnings"]:
            st.warning("Warnings:\n" + "\n".join(f"• {msg}" for msg in issues["warnings"]))
        else:
            st.success("✔️ No validation issues detected")

        preview_payload: Optional[Dict[str, Any]] = None
        preview_error: Optional[str] = None
        if state.get("dirty") and not has_errors:
            try:
                preview_payload = callbacks.serialize_state(state)
            except ValueError as exc:
                preview_error = str(exc)

        if state.get("dirty"):
            st.markdown("#### Change preview")
            if has_errors:
                st.info("Resolve validation errors before previewing changes.")
            elif preview_error:
                st.warning(f"Unable to build preview yet: {preview_error}")
            elif preview_payload is None:
                st.caption("No preview available.")
            else:
                summary = network_editor_diff_summary(state.get("raw_payload", {}), preview_payload)
                if summary:
                    st.markdown("\n".join(f"- {line}" for line in summary))
                else:
                    st.caption("No differences detected versus the saved file.")
        else:
            st.caption("✔️ All changes saved")

    with st.expander("🗺️ Network sketch & layout", expanded=False):
        if state.get("dirty"):
            st.info("Sketch uses the last saved network. Save your edits to refresh the preview.")
            st.caption("Layout tweaks still apply to the saved network state shown below.")
        else:
            st.caption("Up-to-date view of the persisted network, identical to the overview tab.")
        callbacks.render_network_layout_controls(state)
        callbacks.render_matplotlib_image(callbacks.network_figure_factory(), alt_text="Network sketch preview")  # type: ignore[call-arg]

    save_col, reload_col = st.columns([2, 1])
    save_disabled = not state.get("dirty")
    if has_errors:
        save_col.warning("⚠️ Network has validation errors. Save anyway, but simulations may fail.")
    if save_col.button("Save network changes", type="primary", disabled=save_disabled):
        try:
            payload = callbacks.serialize_state(state)
        except ValueError as exc:
            st.error(
                f"Unable to save network changes: {exc}\n\n"
                "Check console logs for detailed error information."
            )
        else:
            try:
                callbacks.write_network_payload(path, payload)
            except Exception as exc:  # pragma: no cover - defensive
                st.error(
                    f"Failed to write network file: {exc}\n\n"
                    "Ensure you have write permissions to the data/networks directory."
                )
            else:
                render_success_toast(f"Network '{state.get('display_name', path.stem)}' saved successfully!", icon="✅")
                callbacks.set_flash("Network file updated.", level="success")
                st.toast("✓ Network saved successfully", icon="✅")
                st.session_state.pop(callbacks.state_key, None)
                callbacks.clear_widgets()
                callbacks.force_rerun()
    if reload_col.button("Discard changes & reload", disabled=not state.get("dirty")):
        st.session_state.pop(callbacks.state_key, None)
        callbacks.clear_widgets()
        st.toast("✓ Changes discarded, reloaded from disk", icon="🔄")
        callbacks.set_flash("Reloaded network from disk.", level="info")
        callbacks.force_rerun()

    with st.expander("📂 File operations (export, duplicate, create, delete)", expanded=False):
        st.markdown("#### Export & duplicate")
        export_col, duplicate_col = st.columns([1, 2])
    export_col.download_button(
        "Download active JSON",
        data=path.read_text(encoding="utf-8"),
        file_name=path.name,
        mime="application/json",
    )
    default_dup_name = f"{config.name} Copy"
    with duplicate_col:
        dup_name = st.text_input("New display name", value=default_dup_name, key="network_dup_name")
        dup_slug = st.text_input(
            "Filename hint (optional, .json added)",
            value=slugify_filename(default_dup_name),
            key="network_dup_slug",
        )
        if st.button("📋 Duplicate active network", key="network_dup_button", type="primary"):
            cleaned_name = dup_name.strip()
            if not cleaned_name:
                st.warning("Please provide a display name for the duplicate network. Enter a name in the input field above.")
            else:
                try:
                    new_path = callbacks.duplicate_active_network_file(cleaned_name, dup_slug.strip() or None)
                except Exception as exc:  # pragma: no cover - defensive
                    st.error(
                        f"Failed to duplicate network: {exc}\n\n"
                        "The network file may be corrupted or inaccessible."
                    )
                else:
                    callbacks.set_flash(
                        f"Created duplicate network at {new_path.name}.",
                        level="success",
                    )
                    callbacks.apply_network_change(str(new_path), label_hint=cleaned_name)  # type: ignore[call-arg]

        st.markdown("#### Create new network")
        st.caption("Spin up a fresh JSON file directly from the editor, then add stations and segments before saving.")
        create_name = st.text_input("Display name", key="network_create_name", placeholder="e.g. Northern Corridor")  # type: ignore[call-arg]
        create_slug = st.text_input(
            "Filename hint (optional, .json added automatically)",
            key="network_create_slug",
            placeholder="Auto-generated from the display name",
        )
        include_sample = st.checkbox(
            "Start with example stations/segment",
            value=True,
            key="network_create_include_sample",
            help="Adds two placeholder stations and a sample segment you can edit or delete.",
        )
        if st.button("✨ Create new network file", key="network_create_button", type="primary"):
            cleaned_name = create_name.strip()
            if not cleaned_name:
                st.warning("Please provide a display name before creating a new network. Enter a name in the input field above.")
            else:
                try:
                    new_path = callbacks.create_blank_network_file(
                        cleaned_name,
                        create_slug.strip() or None,
                        include_sample,
                    )  # type: ignore[call-arg]
                except Exception as exc:  # pragma: no cover - defensive
                    st.error(
                        f"Failed to create network: {exc}\n\n"
                        "Ensure the data/networks directory exists and is writable."
                    )
                else:
                    st.toast(f"✓ Created new network '{cleaned_name}'", icon="✨")
                    callbacks.set_flash(
                        f"Created new network '{cleaned_name}' at {new_path.name}. Use the tables above to add your real data, then save.",
                        level="success",
                    )
                    callbacks.apply_network_change(str(new_path), cleaned_name)  # type: ignore[call-arg]

        st.markdown("#### Delete network")
        st.caption("Permanently delete the current JSON file. This cannot be undone and removes any unsaved edits.")
        delete_cols = st.columns([3, 1])
        delete_confirmation = delete_cols[0].text_input(
            "Type the filename to confirm",
            key="network_delete_confirm",
            placeholder=path.name,
            help=f"Enter '{path.name}' to enable deletion.",
        )
        if state.get("dirty"):
            st.warning("Deleting now will discard unsaved edits that haven't been saved to disk.")
        delete_button = delete_cols[1].button("Delete network file", type="secondary")
        if delete_button:
            typed = delete_confirmation.strip()
            if typed.casefold() != path.name.casefold():
                st.warning(f"Type '{path.name}' exactly to confirm deletion.")
            else:
                try:
                    callbacks.delete_network_file(path)
                except Exception as exc:  # pragma: no cover - defensive
                    st.error(
                        f"Failed to delete network: {exc}\n\n"
                        "The file may be in use or you may lack delete permissions."
                    )
                else:
                    fallback_path: Optional[str] = None
                    fallback_label: Optional[str] = None
                    for candidate in callbacks.network_file_candidates():
                        if Path(candidate).exists():
                            fallback_path = candidate
                            break
                    if fallback_path is None:
                        fallback_label = "New Network"
                        fallback_path = str(callbacks.create_blank_network_file(fallback_label, None, False))  # type: ignore[call-arg]
                    st.toast(f"✓ Deleted network file {path.name}", icon="🗑️")
                    callbacks.set_flash(
                        f"Deleted network file {path.name}.",
                        level="warning",
                    )
                    callbacks.apply_network_change(fallback_path, fallback_label)  # type: ignore[call-arg]

        st.markdown("#### Import network JSON")
        upload = st.file_uploader("Upload network JSON", type="json", key="network_upload_editor")
        upload_display = st.text_input("Display name", key="network_upload_display")  # type: ignore[call-arg]
        upload_slug = st.text_input("Filename hint", key="network_upload_slug")  # type: ignore[call-arg]
        if upload is None:
            st.caption("Select a JSON file to import.")
        else:
            raw_bytes = upload.getvalue()
            try:
                parsed = json.loads(raw_bytes.decode("utf-8"))
            except Exception as exc:
                st.error(f"Uploaded file is not valid JSON: {exc}")
            else:
                display_name = upload_display.strip() or str(parsed.get("name") or "Imported Network")
                if not display_name:
                    display_name = "Imported Network"
                try:
                    new_path = callbacks.import_uploaded_network(raw_bytes, display_name, upload_slug.strip() or None)
                except Exception as exc:  # pragma: no cover - defensive
                    st.error(f"Failed to import network: {exc}")
                else:
                    st.toast(f"✓ Imported network '{display_name}'", icon="📥")
                    callbacks.set_flash(
                        f"Added network '{display_name}' as {new_path.name}.",
                        level="success",
                    )
                    callbacks.apply_network_change(str(new_path), display_name)  # type: ignore[call-arg]


__all__ = [
    "NetworkEditorCallbacks",
    "render_network_editor_page",
]
