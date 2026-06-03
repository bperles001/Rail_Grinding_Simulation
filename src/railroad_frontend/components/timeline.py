"""Reusable timeline rendering components."""
from __future__ import annotations

import base64
import io
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from railroad_backend.domain.simulator import prepare_timeline_rows
from src.utils.timeline_generator import TimelineGenerator, TimelinePlot


@dataclass(frozen=True)
class TimelineAssets:
    png_bytes: Optional[bytes]
    csv_bytes: Optional[bytes]


@dataclass(frozen=True)
class RenderedTimeline:
    plot: TimelinePlot
    assets: TimelineAssets


def render_timeline(
    *,
    steps: Sequence[Dict[str, Any]],
    segments: Optional[Sequence[Any]] = None,
    timeline_order: Optional[Sequence[str]] = None,
    download_context: str = "timeline",
    generator_kwargs: Optional[Dict[str, Any]] = None,
) -> Optional[RenderedTimeline]:
    timeline_data, y_order, alias_map = prepare_timeline_rows(
        steps, segments=segments, timeline_order=timeline_order
    )
    if not timeline_data:
        st.info("No steps were recorded for this run yet.")
        return None
    generator = TimelineGenerator(timeline_data, y_order=y_order, alias_map=alias_map)
    generator.process_data()
    kwargs = {"figsize": (14, 6), "interactive_labels": False}
    if generator_kwargs:
        kwargs.update(generator_kwargs)
    plot = generator.create_timeline_plot(**kwargs)  # type: ignore[arg-type]
    assets = _offer_timeline_downloads(plot, download_context=download_context)
    return RenderedTimeline(plot=plot, assets=assets)


def _figure_to_png_bytes(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)
    return buffer.getvalue()


def _render_matplotlib_image(fig, *, alt_text: str = "Plot") -> Optional[bytes]:
    if fig is None:
        st.info("Unable to generate the requested figure.")
        return None
    png_bytes = _figure_to_png_bytes(fig)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    st.markdown(
        f'<img src="data:image/png;base64,{encoded}" alt="{alt_text}" '
        "style='max-width:100%; height:auto; display:block; margin:auto;' />",
        unsafe_allow_html=True,
    )
    plt.close(fig)
    return png_bytes


def _offer_timeline_downloads(plot: TimelinePlot, *, download_context: str) -> TimelineAssets:
    ctx = download_context.replace(" ", "_") or "timeline"
    png_bytes = _render_matplotlib_image(plot.figure, alt_text="Simulation timeline")
    if png_bytes:
        st.download_button(
            "Download timeline PNG",
            data=png_bytes,
            file_name=f"{ctx}_timeline.png",
            mime="image/png",
            key=f"download_btn_{ctx}_png",
        )
    df = plot.dataframe
    csv_bytes: Optional[bytes] = None
    if df is not None and not df.empty:
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download timeline CSV",
            data=csv_bytes,
            file_name=f"{ctx}_timeline.csv",
            mime="text/csv",
            key=f"download_btn_{ctx}_csv",
        )
    return TimelineAssets(png_bytes=png_bytes, csv_bytes=csv_bytes)


def render_timeline_table(plot: Optional[TimelinePlot], *, caption: str) -> None:
    if not plot or plot.dataframe is None or plot.dataframe.empty:
        return
    st.caption(caption)
    st.dataframe(plot.dataframe, use_container_width=True, hide_index=True)


def build_comparison_archive(
    *,
    metrics_df: pd.DataFrame,
    auto_plot: Optional[TimelinePlot],
    auto_assets: Optional[TimelineAssets],
    manual_plot: Optional[TimelinePlot],
    manual_assets: Optional[TimelineAssets],
) -> Optional[bytes]:
    payloads: Dict[str, bytes] = {}

    if not metrics_df.empty:
        payloads["metrics.csv"] = metrics_df.to_csv(index=False).encode("utf-8")
        payloads["metrics.json"] = metrics_df.to_json(orient="records").encode("utf-8")

    def _timeline_payload(
        plot: Optional[TimelinePlot],
        assets: Optional[TimelineAssets],
        prefix: str,
    ) -> None:
        if not plot or plot.dataframe is None or plot.dataframe.empty:
            return
        df = plot.dataframe
        csv_bytes = assets.csv_bytes if assets and assets.csv_bytes else df.to_csv(index=False).encode("utf-8")
        payloads[f"{prefix}_timeline.csv"] = csv_bytes
        payloads[f"{prefix}_timeline.json"] = df.to_json(orient="records", date_format="iso").encode("utf-8")
        if assets and assets.png_bytes:
            payloads[f"{prefix}_timeline.png"] = assets.png_bytes

    _timeline_payload(auto_plot, auto_assets, "auto")
    _timeline_payload(manual_plot, manual_assets, "manual")

    if not payloads:
        return None

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in payloads.items():
            bundle.writestr(name, content)
    buffer.seek(0)
    return buffer.getvalue()


__all__ = [
    "TimelineAssets",
    "RenderedTimeline",
    "render_timeline",
    "render_timeline_table",
    "build_comparison_archive",
]
