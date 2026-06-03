"""Comparison page rendering for manual versus auto runs."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from railroad_frontend.components.timeline import (
    RenderedTimeline,
    build_comparison_archive,
    render_timeline,
    render_timeline_table,
)
from railroad_frontend.components.ui_components import (
    render_metric_card,
    render_status_banner,
    render_page_header,
    render_empty_state,
    render_skeleton_card,
    render_skeleton_metric,
    render_loading_spinner,
    render_kpi_card,
    render_result_summary,
    render_comparison_badge,
    render_aria_live_region,
    render_alert_banner,
)


def _comparison_metrics(auto_result: Dict[str, Any], manual_result: Dict[str, Any]) -> pd.DataFrame:
    """Build comparison metrics dataframe from auto and manual results.

    Args:
        auto_result: Auto planning result dictionary.
        manual_result: Manual planning result dictionary.

    Returns:
        DataFrame with Metric, Auto, Manual, Delta, and Change columns.
    """
    auto_idle = auto_result.get("idle_days_total", 0)
    manual_idle = manual_result.get("idle_days_total", 0)
    rows = [
        {
            "Metric": "Steps",
            "Auto": len(auto_result.get("steps", [])),
            "Manual": len(manual_result.get("steps", [])),
        },
        {
            "Metric": "Maintenance actions",
            "Auto": auto_result.get("maintenance_count", 0),
            "Manual": manual_result.get("maintenance_count", 0),
        },
        {
            "Metric": "Movement days",
            "Auto": auto_result.get("movement_days_total", 0),
            "Manual": manual_result.get("movement_days_total", 0),
        },
        {
            "Metric": "Maintenance days",
            "Auto": auto_result.get("maintenance_days_total", 0),
            "Manual": manual_result.get("maintenance_days_total", 0),
        },
        {
            "Metric": "Idle days",
            "Auto": auto_idle,
            "Manual": manual_idle,
        },
        {
            "Metric": "Total days",
            "Auto": auto_result.get("movement_days_total", 0)
            + auto_result.get("maintenance_days_total", 0)
            + auto_idle,
            "Manual": manual_result.get("movement_days_total", 0)
            + manual_result.get("maintenance_days_total", 0)
            + manual_idle,
        },
    ]
    df = pd.DataFrame(rows)
    df["Delta"] = df["Manual"] - df["Auto"]
    
    # Calculate percentage change
    df["Change %"] = df.apply(
        lambda row: f"{((row['Manual'] - row['Auto']) / row['Auto'] * 100):.1f}%" 
        if row['Auto'] != 0 else "N/A",
        axis=1
    )
    return df


def render_comparison_page(
    manual_result: Optional[Dict[str, Any]],
    auto_result: Optional[Dict[str, Any]],
    *,
    render_schedule_network_alert: Callable[[], None],
    segments: Sequence[Any],
    timeline_order: Optional[Sequence[str]] = None,
) -> None:
    """Render the comparison tab showing manual versus auto plans."""
    if not manual_result or not auto_result:
        render_empty_state(
            icon="⚖️",
            title="No Comparison Available",
            description="You need to run both the Auto Simulation and Manual Route Builder before comparing results.",
            action_text="Navigate to Auto Simulation or Manual Route to generate plans first."
        )
        return
    
    render_page_header(
        title="Plan Comparison",
        icon="⚖️",
        description="Compare auto-generated and manual plans to determine the optimal maintenance strategy.",
        workflow_step="Step 4 of 4: Analyze Results"
    )
    
    # ARIA announcement for screen readers
    render_aria_live_region(
        "Comparison page loaded. Auto and manual plan metrics are now available.",
        priority="polite"
    )
    
    render_schedule_network_alert()
    metrics = _comparison_metrics(auto_result, manual_result)
    
    # Determine winner based on total days (lower is better)
    total_days_row = metrics[metrics["Metric"] == "Total days"].iloc[0]
    auto_total = total_days_row["Auto"]
    manual_total = total_days_row["Manual"]
    
    # Announce comparison result
    if manual_total < auto_total:
        improvement_pct = ((auto_total - manual_total) / auto_total * 100)
        result_message = f"Manual plan is better: {improvement_pct:.1f}% improvement, saving {int(auto_total - manual_total)} days"
    elif auto_total < manual_total:
        improvement_pct = ((manual_total - auto_total) / manual_total * 100)
        result_message = f"Auto plan is better: {improvement_pct:.1f}% improvement, saving {int(manual_total - auto_total)} days"
    else:
        result_message = "Both plans have equal performance"
    
    render_aria_live_region(result_message, priority="polite")
    
    # Display winner badge
    if manual_total < auto_total:
        improvement_pct = ((auto_total - manual_total) / auto_total * 100)
        render_comparison_badge(
            f"Manual Plan: {improvement_pct:.1f}% Better ({int(auto_total - manual_total)} days saved)",
            comparison_type="better",
            icon="🏆"
        )
    elif auto_total < manual_total:
        improvement_pct = ((manual_total - auto_total) / manual_total * 100)
        render_comparison_badge(
            f"Auto Plan: {improvement_pct:.1f}% Better ({int(manual_total - auto_total)} days saved)",
            comparison_type="better",
            icon="🏆"
        )
    else:
        render_comparison_badge(
            "Tie: Both plans perform equally",
            comparison_type="equal",
            icon="⚖️"
        )
    
    st.markdown("---")
    
    # KPI Cards for key metrics
    st.markdown("### 📊 Key Performance Indicators")
    
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    # Total Days KPI
    with kpi_col1:
        delta_days = manual_total - auto_total
        if delta_days < 0:
            badge = "✓ Better"
            badge_type = "better"
            change_type = "positive"
        elif delta_days > 0:
            badge = "⚠ Worse"
            badge_type = "worse"
            change_type = "negative"
        else:
            badge = "= Equal"
            badge_type = "neutral"
            change_type = "neutral"
        
        st.metric(
            label=f"Total Days (Manual) {badge}",
            value=manual_total,
            delta=f"{delta_days:+d} vs Auto",
            delta_color="inverse"
        )
    
    # Maintenance Actions KPI
    maintenance_row = metrics[metrics["Metric"] == "Maintenance actions"].iloc[0]
    with kpi_col2:
        delta_maint = maintenance_row["Delta"]
        if delta_maint < 0:
            badge = "✓ Better"
            badge_type = "better"
            change_type = "positive"
        elif delta_maint > 0:
            badge = "⚠ More"
            badge_type = "worse"
            change_type = "negative"
        else:
            badge = "= Equal"
            badge_type = "neutral"
            change_type = "neutral"
        
        st.metric(
            label=f"Maintenance Actions {badge}",
            value=int(maintenance_row['Manual']),
            delta=f"{delta_maint:+.0f} vs Auto",
            delta_color="inverse"
        )
    
    # Movement Days KPI
    movement_row = metrics[metrics["Metric"] == "Movement days"].iloc[0]
    with kpi_col3:
        delta_move = movement_row["Delta"]
        st.metric(
            label="Movement Days",
            value=int(movement_row['Manual']),
            delta=f"{delta_move:+.0f} vs Auto",
            delta_color="inverse"
        )
    
    # Idle Days KPI
    idle_row = metrics[metrics["Metric"] == "Idle days"].iloc[0]
    with kpi_col4:
        delta_idle = idle_row["Delta"]
        st.metric(
            label="Idle Days",
            value=int(idle_row['Manual']),
            delta=f"{delta_idle:+.0f} vs Auto",
            delta_color="inverse"
        )
    
    st.markdown("---")
    
    # Detailed comparison table (expanded by default)
    with st.expander("📋 Detailed Comparison Table", expanded=True):
        st.dataframe(
            metrics,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Delta": st.column_config.NumberColumn(
                    "Delta",
                    help="Manual - Auto (negative means manual is better)",
                    format="%d"
                ),
                "Change %": st.column_config.TextColumn(
                    "Change %",
                    help="Percentage difference"
                )
            }
        )
    
    st.markdown("---")
    
    # Interactive visualizations
    st.markdown("### 📊 Visual Analysis")
    
    # Create comparison charts
    viz_tab1, viz_tab2, viz_tab3 = st.tabs(["Bar Comparison", "Breakdown Chart", "Segment Status"])
    
    with viz_tab1:
        st.markdown("#### Metric Comparison")
        _render_comparison_bar_chart(metrics)
    
    with viz_tab2:
        st.markdown("#### Time Breakdown")
        col_breakdown1, col_breakdown2 = st.columns(2)
        with col_breakdown1:
            st.markdown("**Auto Plan**")
            _render_time_breakdown_pie(auto_result, "Auto")
        with col_breakdown2:
            st.markdown("**Manual Plan**")
            _render_time_breakdown_pie(manual_result, "Manual")
    
    with viz_tab3:
        st.markdown("#### Segment Load Comparison")
        _render_segment_status_heatmap(auto_result, manual_result)
    
    st.markdown("---")
    st.markdown("### 📅 Timeline Comparison")
    auto_timeline: Optional[RenderedTimeline] = None
    manual_timeline: Optional[RenderedTimeline] = None
    auto_plot = None
    manual_plot = None
    col_auto, col_manual = st.columns(2)
    with col_auto:
        st.markdown("#### Auto timeline")
        auto_timeline = render_timeline(
            steps=auto_result["steps"],
            segments=segments,
            timeline_order=timeline_order or None,
            download_context="comparison_auto",
        )
        auto_plot = auto_timeline.plot if auto_timeline else None
        render_timeline_table(auto_plot, caption="Auto timeline rows")
    with col_manual:
        st.markdown("#### Manual timeline")
        manual_timeline = render_timeline(
            steps=manual_result["steps"],
            segments=segments,
            timeline_order=timeline_order or None,
            download_context="comparison_manual",
        )
        manual_plot = manual_timeline.plot if manual_timeline else None
        render_timeline_table(manual_plot, caption="Manual timeline rows")

    auto_assets = auto_timeline.assets if auto_timeline else None
    manual_assets = manual_timeline.assets if manual_timeline else None
    archive_bytes = build_comparison_archive(
        metrics_df=metrics,
        auto_plot=auto_plot,
        auto_assets=auto_assets,
        manual_plot=manual_plot,
        manual_assets=manual_assets,
    )
    if archive_bytes:
        st.download_button(
            "Download comparison bundle (CSV/JSON)",
            data=archive_bytes,
            file_name="comparison_artifacts.zip",
            mime="application/zip",
            key="comparison_bundle_download",
        )


def _render_comparison_bar_chart(metrics_df):
    """Render interactive bar chart comparing auto vs manual metrics."""
    # RUMO Brand colors
    RUMO_BLUE = "#003865"
    RUMO_LIGHT_BLUE = "#32A6E6"
    
    # Filter numeric metrics for visualization
    key_metrics = ["Total Days", "Maintenance Actions", "Total Segments", "Avg Days per Segment"]
    chart_data = metrics_df[metrics_df["Metric"].isin(key_metrics)].copy()
    
    if chart_data.empty:
        st.info("No metrics available for visualization")
        return
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Set bar positions
    x = np.arange(len(chart_data))
    width = 0.35
    
    # Create bars
    auto_bars = ax.bar(x - width/2, chart_data["Auto"], width, label='Auto Plan', 
                       color=RUMO_BLUE, alpha=0.8)
    manual_bars = ax.bar(x + width/2, chart_data["Manual"], width, label='Manual Plan', 
                         color=RUMO_LIGHT_BLUE, alpha=0.8)
    
    # Customize chart
    ax.set_xlabel('Metrics', fontsize=12, fontweight='bold')
    ax.set_ylabel('Value', fontsize=12, fontweight='bold')
    ax.set_title('Auto vs Manual Plan Comparison', fontsize=14, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(chart_data["Metric"], rotation=15, ha='right')
    ax.legend(loc='upper right', framealpha=0.9)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    # Add value labels on bars
    for bars in [auto_bars, manual_bars]:
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(height)}',
                   ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()


def _render_time_breakdown_pie(result, plan_type):
    """Render pie chart showing time breakdown for a plan."""
    RUMO_COLORS = ["#003865", "#32A6E6", "#1E9F7F", "#7FE06C", "#FBD300", "#F78344"]
    
    # Extract segment durations
    if not hasattr(result, 'schedule') or not result.schedule:
        st.info(f"No schedule data available for {plan_type} plan")
        return
    
    segment_data = {}
    for entry in result.schedule:
        seg_name = entry.get("segment", "Unknown")
        duration = entry.get("duration", 0)
        segment_data[seg_name] = segment_data.get(seg_name, 0) + duration
    
    if not segment_data:
        st.info(f"No segment data available for {plan_type} plan")
        return
    
    # Sort by duration and take top 6
    sorted_segments = sorted(segment_data.items(), key=lambda x: x[1], reverse=True)
    top_segments = sorted_segments[:6]
    
    # If more than 6, group the rest as "Others"
    if len(sorted_segments) > 6:
        others_total = sum(duration for _, duration in sorted_segments[6:])
        top_segments.append(("Others", others_total))
    
    labels = [seg for seg, _ in top_segments]
    sizes = [duration for _, duration in top_segments]
    
    # Create pie chart
    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%',
                                        colors=RUMO_COLORS[:len(sizes)],
                                        startangle=90, textprops={'fontsize': 9})
    
    # Enhance text
    for text in texts:
        text.set_fontweight('bold')
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontweight('bold')
    
    ax.set_title(f'{plan_type} Plan - Time Distribution', fontsize=12, fontweight='bold', pad=15)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()


def _render_segment_status_heatmap(auto_result, manual_result):
    """Render heatmap comparing segment load between auto and manual plans."""
    # Extract segment maintenance counts
    auto_segments = {}
    manual_segments = {}
    
    if hasattr(auto_result, 'schedule') and auto_result.schedule:
        for entry in auto_result.schedule:
            seg = entry.get("segment", "Unknown")
            auto_segments[seg] = auto_segments.get(seg, 0) + 1
    
    if hasattr(manual_result, 'schedule') and manual_result.schedule:
        for entry in manual_result.schedule:
            seg = entry.get("segment", "Unknown")
            manual_segments[seg] = manual_segments.get(seg, 0) + 1
    
    # Get all unique segments
    all_segments = sorted(set(list(auto_segments.keys()) + list(manual_segments.keys())))
    
    if not all_segments:
        st.info("No segment data available for comparison")
        return
    
    # Prepare data for heatmap
    auto_counts = [auto_segments.get(seg, 0) for seg in all_segments]
    manual_counts = [manual_segments.get(seg, 0) for seg in all_segments]
    diff_counts = [manual_counts[i] - auto_counts[i] for i in range(len(all_segments))]
    
    # Create comparison table
    data_matrix = np.array([auto_counts, manual_counts, diff_counts])
    
    # Create heatmap
    fig, ax = plt.subplots(figsize=(12, 4))
    
    im = ax.imshow(data_matrix, cmap='RdYlGn_r', aspect='auto')
    
    # Set ticks
    ax.set_xticks(np.arange(len(all_segments)))
    ax.set_yticks(np.arange(3))
    ax.set_xticklabels(all_segments, rotation=45, ha='right', fontsize=9)
    ax.set_yticklabels(['Auto Plan', 'Manual Plan', 'Difference'], fontsize=10, fontweight='bold')
    
    # Add values to cells
    for i in range(3):
        for j in range(len(all_segments)):
            text = ax.text(j, i, int(data_matrix[i, j]),
                          ha="center", va="center", color="white" if abs(data_matrix[i, j]) > max(auto_counts + manual_counts) / 2 else "black",
                          fontweight='bold', fontsize=9)
    
    ax.set_title('Segment Maintenance Load Comparison', fontsize=14, fontweight='bold', pad=20)
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Maintenance Actions', rotation=270, labelpad=20, fontweight='bold')
    
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()
