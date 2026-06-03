"""Manual route builder page for the Streamlit dashboard."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import pandas as pd
import streamlit as st

from railroad_frontend.components.ui_components import (
    render_page_header,
    render_empty_state,
    render_getting_started,
    render_section_header,
    render_loading_spinner,
    render_step_progress,
)
from railroad_backend.persistence.plan_storage import (
    import_manual_plan_payload,
    load_manual_plan,
    save_manual_plan,
)
from railroad_backend.services.manual_planner import (
    ManualMoveOption,
    ManualPlanConfig,
    list_available_moves,
    replay_manual_plan,
)
from railroad_frontend.components.timeline import render_timeline, render_timeline_table


@dataclass(frozen=True)
class ManualRouteSessionKeys:
    """Identifiers used inside ``st.session_state`` for manual planning."""

    config_key: str
    plan_key: str
    result_key: str
    saved_plans_key: str
    widget_keys: Mapping[str, str]


@dataclass(frozen=True)
class ManualRouteCallbacks:
    """Cross-cutting callbacks needed by the manual planner view."""

    render_schedule_network_alert: Callable[[], None]
    station_choices_provider: Callable[[], Sequence[str]]
    facing_options_provider: Callable[[str], Sequence[str]]
    manual_config_changed: Callable[[], None]
    update_manual_plan: Callable[[List[Dict[str, Any]]], None]
    force_rerun: Callable[[], None]
    persist_plan_storage: Callable[[], None]
    store_manual_result: Callable[[Optional[Any]], None]
    network_segments_provider: Callable[[], Sequence[Any]]
    timeline_order_provider: Callable[[], Sequence[str]]
    render_segment_status_table: Callable[..., None]


def render_manual_route_page(
    *,
    schedule_path: Path,
    network_file_path: Path,
    callbacks: ManualRouteCallbacks,
    session_keys: ManualRouteSessionKeys,
) -> None:
    """Render the manual planner view using the provided callbacks and state keys."""

    render_page_header(
        title="Manual Route Builder",
        icon="🎯",
        description="Create custom maintenance plans by manually defining each move and turn.",
        workflow_step="Step 3 of 4: Run Simulation"
    )
    
    callbacks.render_schedule_network_alert()
    
    render_getting_started(
        title="Build Your Plan",
        steps=[
            "Configure starting station and simulation parameters",
            "Add moves by selecting segments or add turns to flip direction",
            "Add idle periods to let MTBT accumulate",
            "Save your plan for future reuse or comparison"
        ]
    )
    state = st.session_state
    widget_keys = session_keys.widget_keys
    config = state.get(session_keys.config_key, {})
    plan: List[Dict[str, Any]] = list(state.get(session_keys.plan_key, []))

    render_section_header("⚙️ Configuration")
    
    # Wrap in form to prevent reload on every input
    with st.form(key="manual_config_form"):
        station_choices = list(callbacks.station_choices_provider()) or ["-"]
        start_value = config.get("start_station", station_choices[0])
        if start_value not in station_choices:
            start_value = station_choices[0]
        
        new_start_station = st.selectbox(
            "Start station",
            station_choices,
            index=station_choices.index(start_value),
        )
        
        facing_choices = list(callbacks.facing_options_provider(new_start_station)) or [new_start_station]
        facing_value = config.get("facing_station", facing_choices[0] if facing_choices else new_start_station)
        if facing_value not in facing_choices:
            facing_value = facing_choices[0] if facing_choices else new_start_station
        
        new_facing_station = st.selectbox(
            "Initial facing",
            facing_choices,
            index=facing_choices.index(facing_value) if facing_value in facing_choices else 0,
        )
        
        new_start_year = st.number_input(
            "Start year",
            min_value=2020,
            max_value=2040,
            value=int(config.get("start_year", 2025)),
        )
        
        new_end_year = st.number_input(
            "End year",
            min_value=int(new_start_year),
            max_value=2040,
            value=int(config.get("end_year", new_start_year + 1)),
            help="Daily MTBT values will be loaded through this year.",
        )
        
        new_second_kld = st.checkbox(
            "Second KLD installed",
            value=bool(config.get("second_kld", False)),
        )
        
        # Submit button
        config_submitted = st.form_submit_button("✅ Update Configuration", use_container_width=True, type="primary")
    
    # Apply changes and reset plan if config changed
    if config_submitted:
        config_changed = (
            config.get("start_station") != new_start_station or
            config.get("facing_station") != new_facing_station or
            config.get("start_year") != new_start_year or
            config.get("end_year") != new_end_year or
            config.get("second_kld") != new_second_kld
        )
        
        if config_changed:
            config["start_station"] = new_start_station
            config["facing_station"] = new_facing_station
            config["start_year"] = new_start_year
            config["end_year"] = new_end_year
            config["second_kld"] = new_second_kld
            state[session_keys.config_key] = config
            # Reset plan when config changes
            state[session_keys.plan_key] = []
            plan = []
            st.rerun()
    
    # Update widget keys for display
    state[widget_keys["start_station"]] = config.get("start_station", start_value)
    state[widget_keys["facing_station"]] = config.get("facing_station", facing_value)
    state[widget_keys["start_year"]] = config.get("start_year", 2025)
    state[widget_keys["end_year"]] = config.get("end_year", 2026)
    state[widget_keys["second_kld"]] = config.get("second_kld", False)

    render_section_header("📋 Planned Steps")
    st.caption("Plans execute automatically after every change.")
    plan_df = _manual_plan_dataframe(plan, config)
    if plan_df.empty:
        render_empty_state(
            icon="📋",
            title="No Steps Defined Yet",
            description="Your plan is empty. Use the controls below to add moves, turns, or idle periods.",
            action_text="💡 Tip: Start by adding a segment move or turn based on available options."
        )
    else:
        st.dataframe(plan_df, use_container_width=True, hide_index=True)
        st.markdown('<div class="button-group">', unsafe_allow_html=True)
        col_undo, col_clear = st.columns([1, 1])
        with col_undo:
            if st.button("↩️ Remove last step", use_container_width=True, key="undo_step_btn"):
                new_plan = plan[:-1]
                callbacks.update_manual_plan(new_plan)
                plan = new_plan
                callbacks.force_rerun()
        with col_clear:
            st.markdown('<div class="button-danger">', unsafe_allow_html=True)
            if st.button("🗑️ Clear plan", use_container_width=True, key="clear_plan_btn"):
                callbacks.update_manual_plan([])
                plan = []
                st.toast("✓ Plan cleared", icon="🗑️")
                callbacks.force_rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    render_section_header("💾 Plan Presets", subtitle=True)
    saved_plans = state.get(session_keys.saved_plans_key, {})
    save_col, load_col = st.columns([2, 3])
    with save_col:
        save_name = st.text_input("Save current plan as", key="manual_save_name")
        disabled = not plan
        if st.button("💾 Save plan", disabled=disabled, type="primary", use_container_width=True):
            name = save_name.strip()
            if not name:
                st.warning("Please provide a name before saving the plan. Enter a descriptive name in the input field above.")
            else:
                saved = save_manual_plan(saved_plans, name, plan)
                state[session_keys.saved_plans_key] = saved
                callbacks.persist_plan_storage()
                st.toast(f"✓ Saved plan '{name}'", icon="💾")
    with load_col:
        if saved_plans:
            saved_names = sorted(saved_plans.keys())
            selected_plan = st.selectbox(
                "Saved plans",
                saved_names,
                key="manual_load_select",
            )
            col_load, col_delete = st.columns(2)
            with col_load:
                if st.button("📂 Load plan", use_container_width=True, type="primary"):
                    loaded_plan = load_manual_plan(saved_plans, selected_plan)
                    callbacks.update_manual_plan(loaded_plan)
                    plan = loaded_plan
                    st.toast(f"✓ Loaded plan '{selected_plan}'", icon="📂")
                    callbacks.force_rerun()
            with col_delete:
                st.markdown('<div class="button-danger">', unsafe_allow_html=True)
                if st.button("🗑️ Delete", use_container_width=True, key="delete_plan_btn"):
                    saved_plans.pop(selected_plan, None)
                    state[session_keys.saved_plans_key] = saved_plans
                    callbacks.persist_plan_storage()
                    st.toast(f"✓ Deleted plan '{selected_plan}'", icon="🗑️")
                    callbacks.force_rerun()
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.caption("No saved plans yet.")

    with st.expander("Import/export manual plans", expanded=False):
        manual_snapshot = state.get(session_keys.saved_plans_key, {})
        if manual_snapshot:
            st.download_button(
                "Download manual plans JSON",
                data=json.dumps({"manual": manual_snapshot}, indent=2, ensure_ascii=False).encode("utf-8"),
                file_name="manual_plans.json",
                mime="application/json",
            )
        else:
            st.caption("No manual plans saved to export yet.")
        manual_upload = st.file_uploader(
            "Manual plans JSON",
            type="json",
            key="manual_plans_import",
        )
        if manual_upload and st.button("📥 Import manual plans", key="manual_import_button", type="primary"):
            try:
                payload = json.load(manual_upload)
                saved, imported = import_manual_plan_payload(saved_plans, payload)
                state[session_keys.saved_plans_key] = saved
                callbacks.persist_plan_storage()
                st.success(f"Imported {imported} manual plan(s).")
                callbacks.force_rerun()
            except Exception as exc:  # pragma: no cover - surface to UI
                st.error(
                    f"Failed to import manual plans: {exc}\n\n"
                    "Ensure the uploaded file is a valid JSON export from this application."
                )

    manual_config = ManualPlanConfig(
        csv_path=schedule_path,
        start_station=config.get("start_station", "TRO"),
        facing_station=config.get("facing_station", "TMI"),
        start_year=int(config.get("start_year", 2025)),
        end_year=int(config.get("end_year", 2026)),
        second_kld=bool(config.get("second_kld", False)),
        network_source=network_file_path,
    )
    
    # Show progress for manual plan replay
    if plan and len(plan) > 0:
        progress_container = st.empty()
        with progress_container.container():
            render_step_progress(1, 2, "Replaying manual route", eta_seconds=len(plan) * 2)
        
        replay_result = replay_manual_plan(manual_config, plan)
        
        with progress_container.container():
            render_step_progress(2, 2, "Generating timeline", eta_seconds=1)
        
        progress_container.empty()
    else:
        replay_result = replay_manual_plan(manual_config, plan)
    
    sim_preview = replay_result.simulator
    preview_errors = replay_result.errors
    if preview_errors:
        st.error("Manual plan contains issues:\n" + "\n".join(preview_errors))

    if preview_errors or not plan:
        callbacks.store_manual_result(None)
    else:
        callbacks.store_manual_result(sim_preview)
        manual_result_state = state.get(session_keys.result_key)
        if manual_result_state is not None:
            manual_result_state["config"] = dict(config)

    if getattr(sim_preview, "machine", None):
        st.markdown(
            f"**Current station:** {sim_preview.current_station.name}  |  "
            f"**Facing:** {sim_preview.machine.facing}  |  "
            f"**Global direction:** {sim_preview.machine.global_direction}"
        )
        st.caption(f"Simulation date: {sim_preview.simulation_date.strftime('%Y-%m-%d')}")

    st.markdown("### Add next step")
    if preview_errors:
        st.info("Resolve the plan issues above before adding more steps.")
    else:
        move_options = list_available_moves(sim_preview)
        if not move_options:
            st.warning("No moves are available from the current station. Consider adding a turn, waiting, or clearing the plan.")
        else:
            second_kld_installed = bool(getattr(getattr(sim_preview, "machine", None), "second_kld_installed", False))

            def _format_option(opt: ManualMoveOption) -> str:
                maintenance_allowed = opt.maintenance_aligned or second_kld_installed
                maintenance_note = "maintenance allowed" if maintenance_allowed else "move only"
                return f"{opt.destination} via {opt.segment} ({maintenance_note})"

            with st.form("manual_move_form", clear_on_submit=True):
                selected_option = st.selectbox("Next station", move_options, format_func=_format_option)
                action_choice = st.radio("Action", ("Move only", "Maintenance attempt"), horizontal=True)
                submitted_move = st.form_submit_button("Add move")
            if submitted_move:
                from src.models import ACTION_MAINTAIN, ACTION_MOVE
                action_code = ACTION_MAINTAIN if action_choice.startswith("Maintenance") else ACTION_MOVE
                new_plan = plan + [
                    {
                        "mode": "move",
                        "segment": selected_option.segment,
                        "destination": selected_option.destination,
                        "action": action_code,
                    }
                ]
                callbacks.update_manual_plan(new_plan)
                plan = new_plan
                callbacks.force_rerun()

        with st.form("manual_wait_form", clear_on_submit=True):
            wait_days = int(
                st.number_input(
                    "Idle days",
                    min_value=1,
                    max_value=365,
                    value=3,
                    help="Insert a pause so MTBT can accumulate before the next move.",
                )
            )
            submitted_wait = st.form_submit_button("Add idle period")
        if submitted_wait:
            new_plan = plan + [{"mode": "wait", "days": wait_days}]
            callbacks.update_manual_plan(new_plan)
            plan = new_plan
            callbacks.force_rerun()

        if plan and st.button("↩️ Remove last step", key="remove_last_step_secondary"):
            new_plan = plan[:-1]
            callbacks.update_manual_plan(new_plan)
            plan = new_plan
            callbacks.force_rerun()

        if getattr(sim_preview, "current_station", None) and sim_preview.current_station.can_turn:
            if st.button("🔄 Add turn (flip direction)", type="primary"):
                new_plan = plan + [{"mode": "turn"}]
                callbacks.update_manual_plan(new_plan)
                plan = new_plan
                callbacks.force_rerun()

    manual_result = state.get(session_keys.result_key)
    if manual_result:
        st.markdown("### Manual run results (auto-updated)")
        idle_days = manual_result.get("idle_days_total", 0)
        total_days = manual_result.get("movement_days_total", 0) + manual_result.get("maintenance_days_total", 0) + idle_days
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Steps executed", f"{len(manual_result['steps'])}")
        col_b.metric("Maintenance actions", f"{manual_result['maintenance_count']}")
        col_c.metric("Idle days", f"{idle_days}")
        col_d.metric("Total days elapsed", f"{total_days}")
        steps_df = pd.DataFrame(manual_result.get("steps", []))
        if not steps_df.empty:
            st.dataframe(steps_df, use_container_width=True)
        manual_render = render_timeline(
            steps=manual_result.get("steps", []),
            segments=callbacks.network_segments_provider(),
            timeline_order=callbacks.timeline_order_provider() or None,
            download_context="manual",
        )
        manual_plot = manual_render.plot if manual_render else None
        render_timeline_table(manual_plot, caption="Manual timeline rows")
        callbacks.render_segment_status_table(
            manual_result.get("segment_status", []),
            title="Segment load snapshot",
        )


def _manual_plan_dataframe(plan: List[Dict[str, Any]], config: Dict[str, Any]) -> pd.DataFrame:
    if not plan:
        return pd.DataFrame(columns=["Step", "Type", "Segment", "Destination", "Action", "Capability"])
    second_kld = bool(config.get("second_kld", False))
    rows = []
    for idx, step in enumerate(plan, start=1):
        if step.get("mode") == "turn":
            rows.append({
                "Step": idx,
                "Type": "Turn",
                "Segment": "-",
                "Destination": "-",
                "Action": "Flip direction",
                "Capability": "Facing change",
            })
        elif step.get("mode") == "wait":
            wait_days = int(step.get("days", 1))
            rows.append({
                "Step": idx,
                "Type": "Wait",
                "Segment": "-",
                "Destination": f"Idle for {wait_days} day(s)",
                "Action": "Idle",
                "Capability": "Hold position",
            })
        else:
            aligned = step.get("aligned")
            if aligned:
                capability = "Maintenance allowed"
            elif second_kld:
                capability = "Maintenance allowed (2nd KLD)"
            else:
                capability = "Move only"
            rows.append({
                "Step": idx,
                "Type": "Traverse",
                "Segment": step.get("segment", ""),
                "Destination": step.get("destination", ""),  # Changed from next_station
                "Action": "Maintenance" if step.get("action") in ("m", "maintain") else "Move",
                "Capability": capability,
            })
    return pd.DataFrame(rows)


__all__ = [
    "ManualRouteSessionKeys",
    "ManualRouteCallbacks",
    "render_manual_route_page",
]
