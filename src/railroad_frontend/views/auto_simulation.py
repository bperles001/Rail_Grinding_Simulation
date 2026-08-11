from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import numpy as np

from railroad_frontend.components.ui_components import (
    render_page_header,
    render_help_tooltip,
    render_getting_started,
    render_section_header,
    render_progress_tracker,
    render_success_toast,
    render_validation_message,
    render_step_progress,
    render_loading_spinner,
    render_skeleton_card,
    render_skeleton_metric,
    render_result_summary,
    render_kpi_card,
    render_aria_live_region,
    render_alert_banner,
)
from railroad_backend.persistence.plan_storage import (
    clone_auto_result,
    import_auto_run_payload,
    save_auto_run_entry,
)
from railroad_backend.services.auto_planner import run_auto_plan_from_args
from railroad_frontend.components.timeline import render_timeline


@dataclass(frozen=True)
class AutoSimulationSessionKeys:
    """Session key names used by the auto simulation tab."""

    config_key: str
    result_key: str
    saved_runs_key: str


@dataclass(frozen=True)
class AutoSimulationCallbacks:
    """Bridges Streamlit helpers into the auto simulation view."""

    render_schedule_network_alert: Callable[[], None]
    schedule_path_provider: Callable[[], Path]
    ensure_auto_state: Callable[[], Dict[str, Any]]
    station_choices_provider: Callable[[], Sequence[str]]
    facing_options_provider: Callable[[str], Sequence[str]]
    network_file_path_provider: Callable[[], Path]
    network_segments_provider: Callable[[], Sequence[Any]]
    timeline_order_provider: Callable[[], Sequence[str]]
    segment_status_builder: Callable[[Any], List[Dict[str, Any]]]
    render_segment_status_table: Callable[[List[Dict[str, Any]], str], None]
    persist_plan_storage: Callable[[], None]
    force_rerun: Callable[[], None]


def render_auto_simulation_page(
    *,
    callbacks: AutoSimulationCallbacks,
    session_keys: AutoSimulationSessionKeys,
) -> None:
    """Render the auto simulation tab."""

    render_page_header(
        title="Auto Simulation",
        icon="🤖",
        description="Automatically generate an optimal maintenance plan using intelligent heuristics.",
        workflow_step="Step 3 of 4: Run Simulation"
    )
    
    callbacks.render_schedule_network_alert()
    
    render_getting_started(
        title="How Auto Simulation Works",
        steps=[
            "Configure your starting position and simulation parameters",
            "The algorithm prioritizes segments above MTBT threshold",
            "Automatically handles direction changes and corridor navigation",
            "Stops when reaching year limit or step limit"
        ]
    )
    
    render_section_header("⚙️ Simulation Configuration")
    
    schedule_path = callbacks.schedule_path_provider()
    config = dict(callbacks.ensure_auto_state())
    col_form, col_chart = st.columns([1, 2])
    with col_form:
        # Wrap configuration in a form to prevent rerun on every input change
        with st.form(key="auto_config_form"):
            st.markdown("**Starting Position**")
            station_choices = list(callbacks.station_choices_provider()) or ["-"]
            start_station_default = config.get("start_station", station_choices[0])
            if start_station_default not in station_choices:
                start_station_default = station_choices[0]
            start_station = st.selectbox(
                "Start station",
                station_choices,
                index=station_choices.index(start_station_default),
            )

            facing_choices = list(callbacks.facing_options_provider(start_station)) or [start_station]
            facing_default = config.get("facing_station", facing_choices[0])
            if facing_default not in facing_choices:
                facing_default = facing_choices[0]
            facing_station = st.selectbox(
                "Initial facing",
                facing_choices,
                index=facing_choices.index(facing_default),
            )

            st.markdown("---")
            st.markdown("**Time Period**")
            start_year_default = int(config.get("start_year", 2025))
            start_year = int(
                st.number_input("Start year", min_value=2020, max_value=2040, value=start_year_default, step=1)
            )

            end_year_default = int(config.get("end_year", min(2040, start_year + 1)))
            if end_year_default < start_year:
                end_year_default = start_year
            end_year = int(
                st.number_input(
                    "End year",
                    min_value=start_year,
                    max_value=2040,
                    value=end_year_default,
                    step=1,
                    help="The simulation stops once it reaches this year or the step limit, whichever comes first.",
                )
            )

            st.markdown("---")
            st.markdown("**Simulation Limits**")
            steps_default = int(config.get("steps", 20))
            steps_default = min(max(steps_default, 5), 80)
            steps = int(st.slider("Steps to simulate", min_value=5, max_value=80, value=steps_default))

            second_kld = bool(st.checkbox("Second KLD installed", value=bool(config.get("second_kld", False))))

            st.markdown("---")
            st.markdown("**Strategy**")
            strategy_choices = {"Greedy (atual)": "greedy", "Rolling-horizon ILP": "rolling_ilp"}
            strategy_default_label = next(
                (label for label, value in strategy_choices.items() if value == config.get("strategy", "greedy")),
                "Greedy (atual)",
            )
            strategy_label = st.selectbox(
                "Auto planning strategy",
                list(strategy_choices.keys()),
                index=list(strategy_choices.keys()).index(strategy_default_label),
            )
            strategy = strategy_choices[strategy_label]

            ilp_window_days = int(config.get("ilp_window_days", 60))
            ilp_weight_coverage = float(config.get("ilp_weight_coverage", 10.0))
            ilp_weight_travel = float(config.get("ilp_weight_travel", 1.0))
            ilp_weight_proximity = float(config.get("ilp_weight_proximity", 0.5))
            if strategy == "rolling_ilp":
                ilp_window_days = int(
                    st.slider("Planning window (days)", min_value=14, max_value=180, value=ilp_window_days)
                )
                ilp_weight_coverage = float(
                    st.slider("Weight: coverage (avoid missed MTBT)", min_value=0.0, max_value=50.0, value=ilp_weight_coverage, step=0.5)
                )
                ilp_weight_travel = float(
                    st.slider("Weight: travel cost", min_value=0.0, max_value=10.0, value=ilp_weight_travel, step=0.1)
                )
                ilp_weight_proximity = float(
                    st.slider("Weight: proximity to MTBT limit", min_value=0.0, max_value=5.0, value=ilp_weight_proximity, step=0.1)
                )

            # Form submit button
            form_submitted = st.form_submit_button("✅ Update Configuration", use_container_width=True, type="primary")

        # Only update config when form is submitted
        if form_submitted:
            config["start_station"] = start_station
            config["facing_station"] = facing_station
            config["start_year"] = start_year
            config["end_year"] = end_year
            config["steps"] = steps
            config["second_kld"] = second_kld
            config["strategy"] = strategy
            config["ilp_window_days"] = ilp_window_days
            config["ilp_weight_coverage"] = ilp_weight_coverage
            config["ilp_weight_travel"] = ilp_weight_travel
            config["ilp_weight_proximity"] = ilp_weight_proximity

        # Run button outside the form
        run_clicked = st.button("▶️ Run Auto Plan", type="primary", use_container_width=True)

    st.session_state[session_keys.config_key] = config
    auto_result = st.session_state.get(session_keys.result_key)
    if run_clicked:
        # Clear previous results
        st.session_state[session_keys.result_key] = None
        
        # Show step-by-step progress
        progress_container = st.empty()
        
        # Step 1: Initialization
        with progress_container.container():
            render_step_progress(1, 4, "Initializing simulation", eta_seconds=15)
        
        # Step 2: Planning
        with progress_container.container():
            render_step_progress(2, 4, "Computing optimal route", eta_seconds=10)
        
        # Step 3: Running simulation
        with progress_container.container():
            render_step_progress(3, 4, "Running simulation", eta_seconds=5)
            
        with st.spinner(""):
            plan_result = run_auto_plan_from_args(
                schedule_path,
                start_station=config["start_station"],
                facing_station=config["facing_station"],
                start_year=config["start_year"],
                end_year=config["end_year"],
                steps=config["steps"],
                second_kld=config["second_kld"],
                network_source=callbacks.network_file_path_provider(),
                strategy=config.get("strategy", "greedy"),
                ilp_window_days=config.get("ilp_window_days", 60),
                ilp_weight_coverage=config.get("ilp_weight_coverage", 10.0),
                ilp_weight_travel=config.get("ilp_weight_travel", 1.0),
                ilp_weight_proximity=config.get("ilp_weight_proximity", 0.5),
            )
        
        # Step 4: Generating results
        with progress_container.container():
            render_step_progress(4, 4, "Generating results", eta_seconds=2)
        
        progress_container.empty()
        
        simulator = plan_result.simulator
        if not getattr(simulator, "steps", []):
            st.warning(
                "The simulator could not execute any moves with the current configuration. "
                "Try:\\n"
                "- Checking the network has segments connecting stations\\n"
                "- Verifying the start station has outgoing connections\\n"
                "- Reviewing station and segment configuration in Network Editor"
            )
            st.session_state[session_keys.result_key] = None
            auto_result = None
        else:
            stop_details = dict(plan_result.stop_details)
            result_payload = {
                "steps": [dict(step) for step in simulator.steps],
                "movement_days_total": simulator.movement_days_total,
                "maintenance_days_total": simulator.maintenance_days_total,
                "idle_days_total": getattr(simulator, "idle_days_total", 0),
                "maintenance_count": simulator.maintenance_count,
                "stop_reason": plan_result.stop_reason,
                "stop_details": dict(stop_details),
                "config": dict(config),
                "segment_status": callbacks.segment_status_builder(simulator),
                "strategy": plan_result.strategy_name,
            }
            st.session_state[session_keys.result_key] = result_payload
            auto_result = result_payload
            render_success_toast(
                f"Simulation complete! {len(simulator.steps)} steps, {simulator.maintenance_count} maintenance actions",
                icon="🎉"
            )
            st.toast(f"✓ Simulation complete: {len(simulator.steps)} steps, {simulator.maintenance_count} maintenance actions", icon="✅")
            
            # Announce completion to screen readers
            render_aria_live_region(
                f"Auto simulation completed successfully. Generated {len(simulator.steps)} steps with {simulator.maintenance_count} maintenance actions.",
                priority="assertive"
            )

    with col_chart:
        if auto_result:
            _render_auto_run_details(auto_result, callbacks)
        else:
            st.caption("Run an auto plan to see metrics, logs, and the timeline.")

    _render_auto_saved_runs_section(auto_result, callbacks, session_keys)


def _render_auto_run_details(auto_result: Dict[str, Any], callbacks: AutoSimulationCallbacks) -> None:
    st.markdown("### 🎯 Auto run results")
    st.caption(f"Strategy: {auto_result.get('strategy', 'greedy')}")
    idle_days = auto_result.get("idle_days_total", 0)
    total_days = auto_result["movement_days_total"] + auto_result["maintenance_days_total"] + idle_days
    
    # Simple metrics display using Streamlit's native metric component
    col_a, col_b, col_c, col_d = st.columns(4)
    
    with col_a:
        st.metric(
            label="Total Days",
            value=total_days,
            help="Movement + Maintenance + Idle"
        )
    
    with col_b:
        st.metric(
            label="Maintenance Actions",
            value=auto_result['maintenance_count'],
            help="Segments maintained"
        )
    
    with col_c:
        st.metric(
            label="Movement Days",
            value=auto_result['movement_days_total'],
            help="Days spent traveling"
        )
    
    with col_d:
        st.metric(
            label="Idle Days",
            value=idle_days,
            help="Days without activity"
        )
    
    st.success(f"✅ Simulation completed successfully! Total of {len(auto_result['steps'])} steps executed.")
    
    # Export buttons section
    st.markdown("---")
    st.markdown("### 📥 Export Results")
    export_col1, export_col2, export_col3 = st.columns(3)
    
    with export_col1:
        steps_json = json.dumps(auto_result, indent=2, ensure_ascii=False)
        st.download_button(
            "📄 Download Full Results (JSON)",
            data=steps_json,
            file_name="auto_simulation_results.json",
            mime="application/json",
            use_container_width=True,
            help="Download complete simulation results including all steps and metrics"
        )
    
    with export_col2:
        if auto_result.get("steps"):
            steps_df = pd.DataFrame(auto_result["steps"])
            steps_csv = steps_df.to_csv(index=False)
            st.download_button(
                "📊 Download Steps (CSV)",
                data=steps_csv,
                file_name="auto_simulation_steps.csv",
                mime="text/csv",
                use_container_width=True,
                help="Download step-by-step log as CSV"
            )
    
    with export_col3:
        # Placeholder for future timeline export (will be added below)
        st.caption("Timeline exports available in Timeline section below")
    
    st.markdown("---")
    
    config = auto_result.get("config", {})
    if config:
        st.caption(
            f"Start {config.get('start_station')} → Facing {config.get('facing_station')}  |  "
            f"Years {config.get('start_year')}–{config.get('end_year')}  |  "
            f"Step limit {config.get('steps')}  |  Second KLD {'yes' if config.get('second_kld') else 'no'}"
        )
    stop_reason = auto_result.get("stop_reason")
    if stop_reason:
        details = auto_result.get("stop_details", {})
        if stop_reason == "year_limit":
            st.info(
                f"Stopped after reaching the configured end year ({details.get('limit_date', 'n/a')})."
            )
        elif stop_reason == "steps_limit":
            st.info(
                f"Stopped after completing {details.get('steps_completed')} of {details.get('steps_requested')} steps."
            )
        elif stop_reason == "stalled":
            st.warning("No further moves were possible from the current configuration.")
    steps_df = pd.DataFrame(auto_result["steps"])
    if not steps_df.empty:
        st.markdown("### Step log")
        st.dataframe(steps_df, use_container_width=True)
    st.markdown("### Timeline")
    auto_timeline = render_timeline(
        steps=auto_result["steps"],
        segments=callbacks.network_segments_provider(),
        timeline_order=callbacks.timeline_order_provider() or None,
        download_context="auto",
    )
    if auto_timeline and auto_timeline.assets.png_bytes:
        st.download_button(
            "Download timeline PNG (auto)",
            data=auto_timeline.assets.png_bytes,
            file_name="auto_timeline.png",
            mime="image/png",
            key="auto_view_png",
        )
    if auto_timeline and auto_timeline.assets.csv_bytes:
        st.download_button(
            "Download timeline CSV (auto)",
            data=auto_timeline.assets.csv_bytes,
            file_name="auto_timeline.csv",
            mime="text/csv",
            key="auto_view_csv",
        )
    callbacks.render_segment_status_table(auto_result.get("segment_status", []), title="Segment load snapshot")  # type: ignore[call-arg]


def _render_auto_saved_runs_section(
    auto_result: Optional[Dict[str, Any]],
    callbacks: AutoSimulationCallbacks,
    session_keys: AutoSimulationSessionKeys,
) -> None:
    st.markdown("### Saved auto runs")
    saved_runs = st.session_state.get(session_keys.saved_runs_key, {})
    save_col, load_col = st.columns([2, 3])
    with save_col:
        save_name = st.text_input("Save current auto run as", key="auto_save_name")
        disabled = not auto_result
        if st.button("💾 Save auto run", disabled=disabled, type="primary"):
            name = save_name.strip()
            if not name:
                st.warning("Please provide a name before saving the auto run. Enter a descriptive name in the input field above.")
            else:
                saved_runs = save_auto_run_entry(
                    st.session_state.get(session_keys.saved_runs_key, {}),
                    name,
                    auto_result,
                )
                st.session_state[session_keys.saved_runs_key] = saved_runs
                callbacks.persist_plan_storage()
                st.toast(f"✓ Saved auto run '{name}'", icon="💾")
    with load_col:
        if saved_runs:
            saved_names = sorted(saved_runs.keys())
            selected_run = st.selectbox("Saved auto runs", saved_names, key="auto_saved_select")
            col_load, col_delete = st.columns(2)
            if col_load.button("Load run", use_container_width=True):
                entry = saved_runs[selected_run]
                st.session_state[session_keys.config_key] = dict(entry["config"])
                st.session_state[session_keys.result_key] = clone_auto_result(entry["result"])
                st.toast(f"✓ Loaded auto run '{selected_run}'", icon="📂")
                callbacks.force_rerun()
            if col_delete.button("Delete run", use_container_width=True):
                saved_runs.pop(selected_run, None)
                st.session_state[session_keys.saved_runs_key] = saved_runs
                callbacks.persist_plan_storage()
                st.toast(f"✓ Deleted auto run '{selected_run}'", icon="🗑️")
                callbacks.force_rerun()
        else:
            st.caption("No saved auto runs yet.")

    with st.expander("Import/export auto runs", expanded=False):
        auto_snapshot = st.session_state.get(session_keys.saved_runs_key, {})
        if auto_snapshot:
            st.download_button(
                "Download auto runs JSON",
                data=json.dumps({"auto": auto_snapshot}, indent=2, ensure_ascii=False).encode("utf-8"),
                file_name="auto_runs.json",
                mime="application/json",
            )
        else:
            st.caption("No auto runs saved to export yet.")
        auto_upload = st.file_uploader(
            "Auto runs JSON",
            type="json",
            key="auto_runs_import",
        )
        if auto_upload and st.button("📥 Import auto runs", key="auto_import_button", type="primary"):
            try:
                payload = json.load(auto_upload)
                saved_runs, imported = import_auto_run_payload(
                    st.session_state.get(session_keys.saved_runs_key, {}),
                    payload,
                )
                st.session_state[session_keys.saved_runs_key] = saved_runs
                callbacks.persist_plan_storage()
                st.success(f"Imported {imported} auto run(s).")
                callbacks.force_rerun()
            except Exception as exc:  # pragma: no cover - surface errors to the UI
                st.error(
                    f"Failed to import auto runs: {exc}\n\n"
                    "Ensure the uploaded file is a valid JSON export from this application."
                )
    if saved_runs:
        rows = []
        for name, entry in saved_runs.items():
            config = entry["config"]
            result = entry["result"]
            rows.append({
                "Name": name,
                "Start": config.get("start_station"),
                "Facing": config.get("facing_station"),
                "Years": f"{config.get('start_year')}–{config.get('end_year')}",
                "Steps": len(result.get("steps", [])),
                "Idle days": result.get("idle_days_total", 0),
                "Total days": (
                    result.get("movement_days_total", 0)
                    + result.get("maintenance_days_total", 0)
                    + result.get("idle_days_total", 0)
                ),
                "Maint. count": result.get("maintenance_count", 0),
                "Saved at": entry.get("saved_at"),
            })
        runs_df = pd.DataFrame(rows)
        if not runs_df.empty:
            runs_df = runs_df.set_index("Name")
            st.dataframe(runs_df, use_container_width=True)


def _render_timeline_gantt(result):
    """Render Gantt-style timeline of maintenance activities."""
    RUMO_BLUE = "#003865"
    RUMO_GREEN = "#1E9F7F"
    RUMO_ORANGE = "#F78344"
    
    steps = result.get("steps", [])
    if not steps:
        st.info("No steps available to visualize")
        return
    
    # Prepare data - limit to first 20 steps for readability
    display_steps = steps[:20]
    segments = []
    start_days = []
    durations = []
    colors = []
    
    for step in display_steps:
        if step.get("action") == "maintain":
            segments.append(step.get("segment", "Unknown"))
            start_days.append(step.get("day", 0))
            durations.append(step.get("duration", 0))
            colors.append(RUMO_BLUE)
        elif step.get("action") == "move":
            segments.append(f"Move to {step.get('to_station', 'Unknown')}")
            start_days.append(step.get("day", 0))
            durations.append(step.get("duration", 0))
            colors.append(RUMO_ORANGE)
    
    if not segments:
        st.info("No maintenance/movement activities to display")
        return
    
    # Create horizontal bar chart
    fig, ax = plt.subplots(figsize=(12, max(6, len(segments) * 0.3)))
    
    y_pos = np.arange(len(segments))
    ax.barh(y_pos, durations, left=start_days, color=colors, alpha=0.8, height=0.6)
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(segments, fontsize=9)
    ax.set_xlabel('Day', fontsize=12, fontweight='bold')
    ax.set_ylabel('Activity', fontsize=12, fontweight='bold')
    ax.set_title(f'Maintenance Timeline (First {len(display_steps)} Steps)', fontsize=14, fontweight='bold', pad=20)
    ax.grid(axis='x', alpha=0.3, linestyle='--')
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=RUMO_BLUE, alpha=0.8, label='Maintenance'),
        Patch(facecolor=RUMO_ORANGE, alpha=0.8, label='Movement')
    ]
    ax.legend(handles=legend_elements, loc='upper right')
    
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()
    
    if len(steps) > 20:
        st.info(f"Showing first 20 of {len(steps)} total steps")


def _render_segment_workload_chart(result):
    """Render bar chart of maintenance count per segment."""
    RUMO_BLUE = "#003865"
    RUMO_LIGHT_BLUE = "#32A6E6"
    
    steps = result.get("steps", [])
    if not steps:
        st.info("No steps available to visualize")
        return
    
    # Count maintenance actions per segment
    segment_counts = {}
    for step in steps:
        if step.get("action") == "maintain":
            seg = step.get("segment", "Unknown")
            segment_counts[seg] = segment_counts.get(seg, 0) + 1
    
    if not segment_counts:
        st.info("No maintenance activities to display")
        return
    
    # Sort by count
    sorted_segments = sorted(segment_counts.items(), key=lambda x: x[1], reverse=True)
    segments, counts = zip(*sorted_segments) if sorted_segments else ([], [])
    
    # Limit to top 15 for readability
    if len(segments) > 15:
        segments = segments[:15]
        counts = counts[:15]
    
    # Create bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    
    bars = ax.bar(range(len(segments)), counts, color=RUMO_BLUE, alpha=0.8)
    
    # Highlight top 3
    if len(bars) >= 3:
        for i in range(min(3, len(bars))):
            bars[i].set_color(RUMO_LIGHT_BLUE)
            bars[i].set_alpha(0.9)
    
    ax.set_xlabel('Segment', fontsize=12, fontweight='bold')
    ax.set_ylabel('Maintenance Count', fontsize=12, fontweight='bold')
    ax.set_title('Segment Maintenance Workload', fontsize=14, fontweight='bold', pad=20)
    ax.set_xticks(range(len(segments)))
    ax.set_xticklabels(segments, rotation=45, ha='right', fontsize=9)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Add value labels
    for i, (bar, count) in enumerate(zip(bars, counts)):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
               f'{int(count)}',
               ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()


def _render_efficiency_metrics(result, total_days, maintenance_actions, idle_days):
    """Render efficiency and utilization metrics."""
    RUMO_COLORS = ["#1E9F7F", "#FBD300", "#F78344"]
    
    # Calculate metrics
    movement_days = result.get("movement_days_total", 0)
    maintenance_days = result.get("maintenance_days_total", 0)
    
    # Time breakdown
    time_breakdown = {
        "Maintenance": maintenance_days,
        "Movement": movement_days,
        "Idle": idle_days
    }
    
    # Create pie chart
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # Pie chart - Time distribution
    labels = list(time_breakdown.keys())
    sizes = list(time_breakdown.values())
    
    wedges, texts, autotexts = ax1.pie(sizes, labels=labels, autopct='%1.1f%%',
                                         colors=RUMO_COLORS, startangle=90,
                                         textprops={'fontsize': 10})
    for text in texts:
        text.set_fontweight('bold')
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontweight('bold')
    
    ax1.set_title('Time Distribution', fontsize=12, fontweight='bold', pad=15)
    
    # Bar chart - Efficiency metrics
    efficiency_metrics = {
        'Utilization %': round((maintenance_days / total_days * 100) if total_days > 0 else 0, 1),
        'Avg Days/Action': round(maintenance_days / maintenance_actions, 1) if maintenance_actions > 0 else 0,
        'Idle %': round((idle_days / total_days * 100) if total_days > 0 else 0, 1)
    }
    
    metric_names = list(efficiency_metrics.keys())
    metric_values = list(efficiency_metrics.values())
    
    bars = ax2.bar(range(len(metric_names)), metric_values, color=["#1E9F7F", "#32A6E6", "#F78344"], alpha=0.8)
    ax2.set_ylabel('Value', fontsize=12, fontweight='bold')
    ax2.set_title('Efficiency Metrics', fontsize=12, fontweight='bold', pad=15)
    ax2.set_xticks(range(len(metric_names)))
    ax2.set_xticklabels(metric_names, fontsize=10, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Add value labels
    for bar, value in zip(bars, metric_values):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{value:.1f}',
                ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()


__all__ = [
    "AutoSimulationCallbacks",
    "AutoSimulationSessionKeys",
    "render_auto_simulation_page",
]

