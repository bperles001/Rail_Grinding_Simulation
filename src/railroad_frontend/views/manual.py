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

_REPLAY_MEMO_KEY = "_manual_replay_memo"


def _file_sig(path: Any) -> str:
    try:
        info = Path(path).stat()
        return f"{info.st_mtime_ns}:{info.st_size}"
    except OSError:
        return "?"


def _replay_memo_key(manual_config: ManualPlanConfig, plan: List[Dict[str, Any]]) -> str:
    return json.dumps(
        {
            "csv": [str(manual_config.csv_path), _file_sig(manual_config.csv_path)],
            "net": [str(manual_config.network_source), _file_sig(manual_config.network_source)],
            "start": manual_config.start_station,
            "facing": manual_config.facing_station,
            "years": [manual_config.start_year, manual_config.end_year],
            "kld2": manual_config.second_kld,
            "plan": plan,
        },
        sort_keys=True,
        default=str,
    )


def _replay_memo_lookup(key: str):
    """Return the cached replay for `key`, or None. The replay rebuilds the
    whole simulation (~100ms) and is deterministic in (config, plan, schedule
    file, network file), so reruns with unchanged inputs reuse the result."""
    memo = st.session_state.get(_REPLAY_MEMO_KEY)
    if memo and memo.get("key") == key:
        return memo["result"]
    return None


def _replay_and_store(key: str, manual_config: ManualPlanConfig, plan: List[Dict[str, Any]]):
    result = replay_manual_plan(manual_config, plan)
    st.session_state[_REPLAY_MEMO_KEY] = {"key": key, "result": result}
    return result


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

    render_section_header("📂 Plano")
    saved_plans = state.get(session_keys.saved_plans_key, {})
    plan_mode = st.radio(
        "Plano",
        ("Novo plano", "Abrir plano salvo"),
        horizontal=True,
        label_visibility="collapsed",
        key="manual_plan_mode",
    )
    if plan_mode == "Abrir plano salvo":
        if saved_plans:
            saved_names = sorted(saved_plans.keys())
            open_selected = st.selectbox("Plano salvo", saved_names, key="manual_open_plan_select")
            if st.button("📂 Carregar", type="primary", key="manual_open_plan_button"):
                loaded_config, loaded_steps = load_manual_plan(saved_plans, open_selected)
                state[session_keys.config_key] = loaded_config
                callbacks.update_manual_plan(loaded_steps)
                st.toast(f"✓ Plano '{open_selected}' carregado (config + passos)", icon="📂")
                callbacks.force_rerun()
        else:
            st.caption("Nenhum plano salvo ainda.")

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
    plan_df = _manual_plan_dataframe(plan, config, callbacks.network_segments_provider())
    if plan_df.empty:
        render_empty_state(
            icon="📋",
            title="No Steps Defined Yet",
            description="Your plan is empty. Use the controls below to add moves, turns, or idle periods.",
            action_text="💡 Tip: Start by adding a segment move or turn based on available options."
        )
    else:
        st.caption(
            "**Action** é somente leitura — pra mudar a ação de um passo, remova-o "
            "e recrie pelo formulário abaixo. Edite **Days** e clique Apply pra salvar."
        )
        # Wrapped in a form (matches the Network Editor's Stations/Segments/Layout
        # tables): a bare data_editor reruns on every keystroke and rebuilds its
        # own `data=` baseline from the state the previous keystroke just wrote,
        # which makes Streamlit discard the edit buffer (same bug fixed for the
        # layout table on 2026-08-04). Gating behind an explicit submit avoids it.
        with st.form("plan_step_editor_form", clear_on_submit=False):
            edited_df = st.data_editor(
                plan_df,
                key="plan_step_editor",
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Step": st.column_config.NumberColumn(disabled=True),
                    "Type": st.column_config.TextColumn(disabled=True),
                    "Segment": st.column_config.TextColumn(disabled=True),
                    "Destination": st.column_config.TextColumn(disabled=True),
                    "Action": st.column_config.TextColumn(disabled=True),
                    "Days": st.column_config.NumberColumn(
                        "Days",
                        min_value=1,
                        max_value=365,
                        step=1,
                    ),
                    "Capability": st.column_config.TextColumn(disabled=True),
                },
            )
            step_changes_submitted = st.form_submit_button("Apply step changes")

        if step_changes_submitted:
            _segments_by_name = {seg.name: seg for seg in callbacks.network_segments_provider()}
            _new_plan = list(plan)
            _changed = False
            for _i, _row in edited_df.iterrows():
                _step = _new_plan[_i]
                _mode = _step.get("mode")
                if _mode == "move":
                    _step_segment_names = _step.get("segments") or ([_step["segment"]] if "segment" in _step else [])
                    _step_seg_objs = [_segments_by_name[name] for name in _step_segment_names if name in _segments_by_name]
                    _segment_actions = _step.get("segment_actions", {})
                    _base_days = sum(
                        (o.maintenance_time_days if _segment_actions.get(o.name, "none") != "none" else o.move_time_days)
                        for o in _step_seg_objs
                    ) if _step_seg_objs else None
                    try:
                        _edited_days = int(_row.get("Days")) if _row.get("Days") is not None else _base_days
                    except (TypeError, ValueError):
                        _edited_days = _base_days
                    if _edited_days is not None and _edited_days != _base_days:
                        if _step.get("days_override") != _edited_days:
                            _new_plan[_i] = {**_step, "days_override": _edited_days}
                            _changed = True
                    elif "days_override" in _step:
                        _new_plan[_i] = {k: v for k, v in _step.items() if k != "days_override"}
                        _changed = True
                elif _mode == "wait":
                    try:
                        _new_days = max(1, min(365, int(_row.get("Days") or _step.get("days", 1))))
                    except (TypeError, ValueError):
                        _new_days = _step.get("days", 1)
                    if _new_days != _step.get("days"):
                        _new_plan[_i] = {**_step, "days": _new_days}
                        _changed = True
            if _changed:
                callbacks.update_manual_plan(_new_plan)
            callbacks.force_rerun()

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
    
    # Replay only when inputs changed; memo hit skips progress UI entirely
    replay_key = _replay_memo_key(manual_config, plan)
    replay_result = _replay_memo_lookup(replay_key)
    if replay_result is None:
        if plan and len(plan) > 0:
            progress_container = st.empty()
            with progress_container.container():
                render_step_progress(1, 2, "Replaying manual route", eta_seconds=len(plan) * 2)
            replay_result = _replay_and_store(replay_key, manual_config, plan)
            with progress_container.container():
                render_step_progress(2, 2, "Generating timeline", eta_seconds=1)
            progress_container.empty()
        else:
            replay_result = _replay_and_store(replay_key, manual_config, plan)
    
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
            def _format_option(opt: ManualMoveOption) -> str:
                via = " + ".join(opt.segments)
                if all(opt.segment_alignment.values()):
                    note = "leitura OK"
                elif any(opt.segment_alignment.values()):
                    note = "leitura parcial"
                else:
                    note = "sem leitura KLD"
                return f"{opt.destination} via {via} ({note})"

            _ACTION_TOKENS = {"Nada": "none", "Só curva": "curva", "Completa": "completa"}

            with st.form("manual_move_form", clear_on_submit=True):
                selected_option = st.selectbox("Next station", move_options, format_func=_format_option)
                segment_choices: Dict[str, str] = {}
                # Chave por POSICAO (nao pelo nome do segmento): widgets dentro
                # de um st.form nao rerenderizam quando o selectbox muda (so no
                # submit). Se a chave dependesse do nome do segmento, trocar o
                # destino sem antes recarregar o formulario faria o Streamlit
                # tratar o radio como nunca visto (chave nova) e voltar pro
                # default "Nada" -- perdendo a escolha do usuario em silencio.
                # Chave estavel por posicao preserva o valor que o usuario
                # marcou, mesmo que o destino tenha mudado nesse meio-tempo.
                for idx, seg_name in enumerate(selected_option.segments):
                    aligned = selected_option.segment_alignment.get(seg_name, False)
                    warning = "" if aligned else " — ⚠ sem leitura KLD se manutenido"
                    choice = st.radio(
                        f"{_segment_role_label(seg_name)} ({seg_name}){warning}",
                        ("Nada", "Só curva", "Completa"),
                        horizontal=True,
                        key=f"manual_move_action_{idx}",
                    )
                    segment_choices[seg_name] = choice
                submitted_move = st.form_submit_button("Add move")
            if submitted_move:
                new_step = {
                    "mode": "move",
                    "segments": list(selected_option.segments),
                    "destination": selected_option.destination,
                    "segment_actions": {
                        seg_name: _ACTION_TOKENS[choice] for seg_name, choice in segment_choices.items()
                    },
                }
                new_plan = plan + [new_step]
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
        result_steps = manual_result.get("steps", [])
        steps_df = pd.DataFrame(result_steps)
        if not steps_df.empty:
            steps_df["Leitura KLD"] = [_kld_reading_label(s) for s in result_steps]
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


_ACTION_LABELS = {"none": "Nada", "curva": "Curva", "completa": "Completa"}


def _segment_role_label(name: str) -> str:
    if name.endswith(("-LP", "-C")):
        return "Pátio Carregado (LP)"
    if name.endswith(("-LD", "-V")):
        return "Pátio Vazio (LD)"
    return "Singela"


def _segment_actions_summary(segment_actions: Mapping[str, str]) -> str:
    parts = [
        f"{_segment_role_label(name)}: {_ACTION_LABELS.get(token, token)}"
        for name, token in segment_actions.items()
    ]
    return " · ".join(parts) if parts else "—"


def _kld_reading_label(step: Dict[str, Any]) -> str:
    kld_reading = step.get("kld_reading") or {}
    if not kld_reading:
        return "—"
    return "OK" if all(kld_reading.values()) else "⚠ sem leitura"


def _manual_plan_dataframe(plan: List[Dict[str, Any]], config: Dict[str, Any], segments: Sequence[Any]) -> pd.DataFrame:
    if not plan:
        return pd.DataFrame(columns=["Step", "Type", "Segment", "Destination", "Action", "Days", "Capability"])
    segments_by_name = {seg.name: seg for seg in segments}
    rows = []
    for idx, step in enumerate(plan, start=1):
        if step.get("mode") == "turn":
            rows.append({
                "Step": idx,
                "Type": "Turn",
                "Segment": "-",
                "Destination": "-",
                "Action": "—",
                "Days": None,
                "Capability": "Facing change",
            })
        elif step.get("mode") == "wait":
            wait_days = int(step.get("days", 1))
            rows.append({
                "Step": idx,
                "Type": "Wait",
                "Segment": "-",
                "Destination": "-",
                "Action": "—",
                "Days": wait_days,
                "Capability": "Hold position",
            })
        else:
            segment_actions = step.get("segment_actions", {})
            step_segment_names = step.get("segments") or ([step["segment"]] if "segment" in step else [])
            step_seg_objs = [segments_by_name[name] for name in step_segment_names if name in segments_by_name]
            base_days = sum(
                (
                    seg_obj.maintenance_time_days
                    if segment_actions.get(seg_obj.name, "none") != "none"
                    else seg_obj.move_time_days
                )
                for seg_obj in step_seg_objs
            ) if step_seg_objs else None
            rows.append({
                "Step": idx,
                "Type": "Traverse",
                "Segment": " + ".join(step_segment_names),
                "Destination": step.get("destination", ""),
                "Action": _segment_actions_summary(segment_actions),
                "Days": step.get("days_override", base_days),
                "Capability": "—",
            })
    return pd.DataFrame(rows)


__all__ = [
    "ManualRouteSessionKeys",
    "ManualRouteCallbacks",
    "render_manual_route_page",
]
