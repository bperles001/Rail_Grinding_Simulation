from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, DefaultDict, Dict, List, Optional, Sequence, Tuple, cast

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib import text as mtext
from matplotlib.ticker import NullLocator
import pandas as pd

ReportRow = Dict[str, Any]


@dataclass(frozen=True)
class TimelinePlot:
    dataframe: pd.DataFrame
    figure: Figure
    axes: Axes

class TimelineGenerator:
    _STATUS_LETTERS = {"maintenance": "A", "maintenance_curves": "C"}

    def __init__(
        self,
        report_data: Sequence[ReportRow],
        y_order: Optional[Sequence[str]] = None,
        alias_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the generator with raw simulator rows and optional ordering."""

        self.report_data: List[ReportRow] = list(report_data)
        self.y_order: List[str] = list(y_order) if y_order else []
        self.alias_map: Dict[str, str] = dict(alias_map) if alias_map else {}
        self.df: Optional[pd.DataFrame] = None
        self.fig: Optional[Figure] = None
        self.ax: Optional[Axes] = None

        # Interactive label management state
        self._label_texts: List[mtext.Text] = []
        self._label_orig_pos: Dict[mtext.Text, Tuple[float, float]] = {}
        self._label_connectors: Dict[mtext.Text, Line2D] = {}
        self._label_bar_centers: Dict[mtext.Text, Tuple[float, float]] = {}
        self._label_orig_style: Dict[mtext.Text, Tuple[object, object]] = {}
        self._dragging_text: Optional[mtext.Text] = None
        self._drag_dx: float = 0.0
        self._drag_dy: float = 0.0
        self._cid_pick: Optional[int] = None
        self._cid_motion: Optional[int] = None
        self._cid_press: Optional[int] = None
        self._cid_release: Optional[int] = None
        self._cid_key: Optional[int] = None

    def _determine_label_placement(
        self,
        duration: float,
        label_text: str,
        seq_idx: int,
        seq_count: int,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        prev_end: Any,
        next_start: Any,
    ) -> str:
        """Determine optimal label placement (left/right/top) based on bar size and neighbors."""
        small_threshold = 0.5 + 0.3 * len(label_text)
        if duration >= small_threshold:
            return 'center'

        def _gap_days(a: Any, b: Any) -> Optional[float]:
            try:
                return (pd.Timestamp(a) - pd.Timestamp(b)).total_seconds() / 86400.0
            except Exception:
                return None

        prev_gap = _gap_days(start_time, prev_end) if pd.notna(prev_end) else None
        next_gap = _gap_days(next_start, end_time) if pd.notna(next_start) else None
        close_thresh = 2.0
        has_prev_close = prev_gap is not None and prev_gap <= close_thresh
        has_next_close = next_gap is not None and next_gap <= close_thresh

        if has_prev_close and has_next_close:
            return 'top'
        elif has_next_close and not has_prev_close:
            return 'left'
        elif has_prev_close and not has_next_close:
            return 'right'
        else:
            # Fallback sequence-based pattern
            if seq_count == 1:
                return 'right'
            elif seq_count == 2:
                return 'left' if seq_idx == 0 else 'right'
            else:
                if seq_idx == 0:
                    return 'left'
                elif seq_idx == 1:
                    return 'right'
                elif seq_idx == 2:
                    return 'top'
                else:
                    return 'left' if (seq_idx % 2 == 0) else 'right'

    def _compute_label_position(
        self,
        placement: str,
        bar_left: float,
        duration: float,
        x_center: float,
        y_pos: float,
        placed_above: DefaultDict[int, List[float]],
    ) -> Tuple[float, float, str, str, List[float], List[float]]:
        """Compute label coordinates and connector line based on placement strategy."""
        side_pad = 0.25
        vert_pad = 0.10
        bar_half = 0.6 / 2.0

        if placement == 'center':
            return x_center, y_pos, 'center', 'center', [x_center, x_center], [y_pos, y_pos]
        elif placement == 'left':
            x_text = bar_left - side_pad
            y_text = float(y_pos)
            conn_x = [bar_left, x_text]
            conn_y = [y_pos, y_text]
            return x_text, y_text, 'right', 'center', conn_x, conn_y
        elif placement == 'right':
            x_text = bar_left + duration + side_pad
            y_text = float(y_pos)
            conn_x = [bar_left + duration, x_text]
            conn_y = [y_pos, y_text]
            return x_text, y_text, 'left', 'center', conn_x, conn_y
        else:  # 'top'
            x_text = x_center
            idx_row = int(y_pos)
            base_y = y_pos + bar_half
            min_dx = 1.2
            existing = placed_above[idx_row]
            close_count = sum(1 for xv in existing if abs(x_center - xv) < min_dx)
            lane_step = 0.18
            y_text = base_y + (vert_pad + lane_step * (close_count + 1))
            placed_above[idx_row].append(x_center)
            conn_x = [x_center, x_text]
            conn_y = [y_pos, y_text]
            return x_text, y_text, 'center', 'bottom', conn_x, conn_y

    def _add_bar_label(
        self,
        label_text: str,
        label_color: str,
        duration: float,
        bar_left: float,
        x_center: float,
        y_pos: float,
        row: Any,
        interactive_labels: bool,
        placed_above: DefaultDict[int, List[float]],
    ) -> None:
        """Add text label to a bar with appropriate positioning and interactivity."""
        seq_idx = int(row.get('row_seq_idx', 0))
        seq_count = int(row.get('row_seq_count', 1))
        start_time = pd.Timestamp(row['start_time'])
        end_time = pd.Timestamp(row['end_time'])
        prev_end = row.get('prev_end_time', pd.NaT)
        next_start = row.get('next_start_time', pd.NaT)

        placement = self._determine_label_placement(
            duration, label_text, seq_idx, seq_count, start_time, end_time, prev_end, next_start
        )
        x_text, y_text, ha, va, conn_x, conn_y = self._compute_label_position(
            placement, bar_left, duration, x_center, y_pos, placed_above
        )

        clip_on = placement == 'center'
        txt = self.ax.text(
            x_text, y_text, label_text,
            va=va, ha=ha, fontsize=8, fontweight='bold', color=label_color, clip_on=clip_on
        )

        if interactive_labels:
            txt.set_picker(10)
            txt.set_clip_on(False)
            self._label_texts.append(txt)
            self._label_orig_pos[txt] = (float(x_text), float(y_text))
            self._label_bar_centers[txt] = (float(x_center), float(y_pos))
            conn = self.ax.plot(conn_x, conn_y, color='#E0E0E0', lw=0.5, zorder=999)[0]
            self._label_connectors[txt] = conn

    def _should_add_label(self, status: str, mtbt_before: Any) -> Tuple[bool, Optional[str]]:
        """Determine if label should be added and what text to use."""
        if status == 'turn':
            return True, 'turn'
        elif isinstance(mtbt_before, (int, float)) and not pd.isna(mtbt_before):
            letter = self._STATUS_LETTERS.get(status)
            text = f"{letter} {mtbt_before:.0f}" if letter else f"{mtbt_before:.0f}"
            return True, text
        return False, None

    def _get_label_color(self, status: str, mtbt_before: Any, mtbt_threshold: Any) -> str:
        """Get label color based on status and MTBT threshold."""
        if status == 'turn':
            return 'black'
        if mtbt_threshold is None:
            return 'black'
        try:
            if float(mtbt_before) > float(mtbt_threshold):
                return 'red'
        except Exception:
            pass
        return 'black'

    def process_data(self) -> pd.DataFrame:
        """Process the report data into a DataFrame suitable for plotting."""

        df = pd.DataFrame(self.report_data)
        required_columns = ['step', 'start_time', 'end_time', 'status']
        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            raise ValueError(
                f"Timeline data is missing required column(s): {', '.join(missing)}. "
                f"Available columns: {', '.join(df.columns)}. "
                "Ensure simulator output includes all required fields."
            )

        # Convert to datetime once
        df['start_time'] = pd.to_datetime(df['start_time'])
        df['end_time'] = pd.to_datetime(df['end_time'])

        # Use map() instead of apply() for better performance on simple lookups
        if self.alias_map:
            df['step_label'] = df['step'].map(self.alias_map).fillna(df['step'])
        else:
            df['step_label'] = df['step']

        # Combine time calculations to reduce operations
        delta = df['end_time'] - df['start_time']
        dt_accessor = cast(Any, delta.dt)
        duration_seconds = cast(pd.Series, dt_accessor.total_seconds())
        df['duration_days'] = duration_seconds / 86400.0
        duration_days = cast(pd.Series, dt_accessor.days)
        df['duration_days_int'] = duration_days.clip(lower=1)

        # Sort once with stable algorithm
        df = df.sort_values(['step_label', 'start_time'], kind='mergesort')
        
        # Group operations - cache the groupby object to avoid recomputation
        grouped = df.groupby('step_label', sort=False)
        df['row_seq_idx'] = grouped.cumcount()
        df['row_seq_count'] = grouped['step_label'].transform('size')
        df['prev_end_time'] = grouped['end_time'].shift(1)
        df['next_start_time'] = grouped['start_time'].shift(-1)

        self.df = df
        return df

    def create_timeline_plot(
        self,
        figsize: Tuple[float, float] = (15.0, 10.0),
        interactive_labels: bool = False,
        save_key: str = 's',
        reset_key: str = 'r',
        annotated_filename: str = 'simulation_timeline_annotated.png',
    ) -> TimelinePlot:
        """
        Create the timeline visualization.
        """
        if self.df is None:
            raise RuntimeError("process_data() must be called before plotting")
        df = self.df

        # Determine label order for y-axis
        unique_labels = list(df['step_label'].unique())
        if self.y_order:
            # Keep only those in data, in the specified order, then append any others not listed
            ordered = [lbl for lbl in self.y_order if lbl in unique_labels]
            extras = [lbl for lbl in unique_labels if lbl not in ordered]
            labels = ordered + extras
        else:
            labels = unique_labels
        # Create figure and axis
        self.fig, self.ax = plt.subplots(figsize=figsize)

        # Create y-position mapping for labels
        step_positions: Dict[str, int] = {label: idx for idx, label in enumerate(labels)}
        # Track placed labels above each row to reduce overlap
        placed_above: DefaultDict[int, List[float]] = defaultdict(list)

        # Plot each step as a horizontal bar
        for _, row in df.iterrows():
            step = str(row['step_label'])
            start_val = row['start_time']
            end_val = row['end_time']
            # Handle Series objects from iterrows
            if hasattr(start_val, 'item'):
                start_val = start_val.item()  # type: ignore[union-attr]
            if hasattr(end_val, 'item'):
                end_val = end_val.item()  # type: ignore[union-attr]
            start_time = pd.Timestamp(start_val)  # type: ignore[arg-type]
            end_time = pd.Timestamp(end_val)  # type: ignore[arg-type]
            duration = cast(float, row['duration_days'])
            status = str(row['status'])
            mtbt_before = row.get('mtbt_before', None)

            y_pos = float(step_positions[step])
            bar_left = cast(float, mdates.date2num(start_time))
            x_center = bar_left + (duration / 2.0)

            # Assign color based on status + direction (carregado/vazio)
            direction = row.get('direction')
            if status == 'turn':
                color = '#777777'  # gray for turns
            elif status == 'wait':
                color = '#F2C744'  # yellow for idle periods
            elif status == 'move':
                color = '#F97316'  # orange for pure movement
            elif status in ('maintenance', 'maintenance_curves'):
                color = '#22C55E' if direction == 'vazio' else '#3B82F6'  # green=Desviada, blue=Principal (default)
            else:
                color = '#888888'

            # Create the bar
            self.ax.barh(
                y_pos,
                duration,
                left=bar_left,
                height=0.6,
                color=color,
                alpha=0.8,
                edgecolor='black',
                linewidth=0.5,
            )

            # Add label text using helper methods
            try:
                should_label, label_text = self._should_add_label(status, mtbt_before)
                if should_label and label_text:
                    label_color = self._get_label_color(status, mtbt_before, row.get('mtbt_threshold'))
                    self._add_bar_label(
                        label_text, label_color, duration, bar_left, x_center, y_pos,
                        row, interactive_labels, placed_above
                    )
            except Exception:
                pass

        # Customize the plot
        self.customize_plot(labels)

        # Enable interactive dragging and keyboard shortcuts if requested
        if interactive_labels:
            self._enable_interactivity(
                save_key=save_key,
                reset_key=reset_key,
                annotated_filename=annotated_filename,
            )
        return TimelinePlot(dataframe=df, figure=self.fig, axes=self.ax)

    def _enable_interactivity(
        self,
        save_key: str = 's',
        reset_key: str = 'r',
        annotated_filename: str = 'simulation_timeline_annotated.png',
    ) -> None:
        """Attach interactive handlers to allow dragging labels and saving/resetting positions.

        Controls:
        - Left-click a label to pick it, then drag to reposition.
        - Release mouse button to drop.
        - Press 's' to save the current figure to annotated_filename.
        - Press 'r' to reset all labels to their original computed positions.
        """
        fig = self.fig
        ax = self.ax
        if fig is None or ax is None:
            return

        # On-figure hint about interactivity
        try:
            fig.text(
                0.01, 0.99,
                "Drag labels; s=save, r=reset",
                ha='left', va='top', transform=fig.transFigure,
                fontsize=9, color='#222',
                bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', boxstyle='round,pad=0.2'),
                zorder=1000,
            )
        except Exception:
            pass

        def _to_num(x: Any) -> float:
            try:
                if isinstance(x, (pd.Timestamp, datetime)):
                    return float(mdates.date2num(pd.to_datetime(x)))
            except Exception:
                pass
            try:
                return float(x)
            except Exception:
                return 0.0

        def _to_date(xnum: Any) -> float:
            return _to_num(xnum)

        def on_pick(event: Any) -> None:
            artist = getattr(event, 'artist', None)
            me = getattr(event, 'mouseevent', None)
            if isinstance(artist, mtext.Text) and me and me.button == 1:
                self._dragging_text = artist
                # Compute offset in data coords
                x0, y0 = artist.get_position()
                x0n = _to_num(x0)
                self._drag_dx = (me.xdata - x0n) if me.xdata is not None else 0.0
                self._drag_dy = (me.ydata - y0) if me.ydata is not None else 0.0
                # Visual highlight while dragging
                try:
                    self._label_orig_style.setdefault(
                        artist,
                        (
                            cast(object, artist.get_color()),
                            cast(object, artist.get_fontweight()),
                        ),
                    )
                    artist.set_color('red')
                    artist.set_fontweight('extra bold')
                    fig.canvas.draw_idle()
                except Exception:
                    pass

        def on_motion(event: Any) -> None:
            if self._dragging_text is None:
                return
            if event.inaxes != ax:
                return
            if event.xdata is None or event.ydata is None:
                return
            new_x_num = event.xdata - self._drag_dx
            new_y = event.ydata - self._drag_dy
            self._dragging_text.set_position((_to_date(new_x_num), new_y))
            # Update connector line
            conn = self._label_connectors.get(self._dragging_text)
            bar_center = self._label_bar_centers.get(self._dragging_text)
            if conn and bar_center:
                conn.set_data([bar_center[0], _to_date(new_x_num)], [bar_center[1], new_y])
            fig.canvas.draw_idle()

        def on_press(event: Any) -> None:
            # Fallback in case pick_event didn't fire (e.g., due to backend/picker radius)
            if event.inaxes != ax or event.button != 1:
                return
            # Check if mouse press is over any text artist
            for txt in reversed(self._label_texts):  # check topmost first
                contains, _ = txt.contains(event)
                if contains:
                    self._dragging_text = txt
                    x0, y0 = txt.get_position()
                    x0n = _to_num(x0)
                    self._drag_dx = (event.xdata - x0n) if event.xdata is not None else 0.0
                    self._drag_dy = (event.ydata - y0) if event.ydata is not None else 0.0
                    try:
                        self._label_orig_style.setdefault(
                            txt,
                            (
                                cast(object, txt.get_color()),
                                cast(object, txt.get_fontweight()),
                            ),
                        )
                        txt.set_color('red')
                        txt.set_fontweight('extra bold')
                        fig.canvas.draw_idle()
                    except Exception:
                        pass
                    break

        def on_release(event: Any) -> None:
            if event.button != 1:
                return
            if self._dragging_text is not None:
                # restore original style
                try:
                    orig = self._label_orig_style.get(self._dragging_text)
                    if orig:
                        color_value, weight_value = orig
                        self._dragging_text.set_color(cast(Any, color_value))
                        self._dragging_text.set_fontweight(cast(Any, weight_value))
                except Exception:
                    pass
                self._dragging_text = None
                fig.canvas.draw_idle()

        def on_key(event: Any) -> None:
            if event.key == save_key:
                try:
                    self.save_plot(filename=annotated_filename, dpi=300)
                except Exception:
                    pass
            elif event.key == reset_key:
                # Reset all tracked labels to their original positions
                for txt in self._label_texts:
                    pos = self._label_orig_pos.get(txt)
                    if pos:
                        txt.set_position(pos)
                        # Reset connector line
                        conn = self._label_connectors.get(txt)
                        bar_center = self._label_bar_centers.get(txt)
                        if conn and bar_center:
                            conn.set_data([bar_center[0], pos[0]], [bar_center[1], pos[1]])
                fig.canvas.draw_idle()
            elif event.key == 'd':
                # Delete selected label and its connector
                if self._dragging_text is not None:
                    txt = self._dragging_text
                    conn = self._label_connectors.get(txt)
                    if conn:
                        conn.remove()
                        del self._label_connectors[txt]
                    if txt in self._label_texts:
                        self._label_texts.remove(txt)
                    if txt in self._label_orig_pos:
                        del self._label_orig_pos[txt]
                    if txt in self._label_bar_centers:
                        del self._label_bar_centers[txt]
                    txt.remove()
                    self._dragging_text = None
                    fig.canvas.draw_idle()

        # Connect callbacks
        self._cid_pick = fig.canvas.mpl_connect('pick_event', on_pick)
        self._cid_motion = fig.canvas.mpl_connect('motion_notify_event', on_motion)
        self._cid_press = fig.canvas.mpl_connect('button_press_event', on_press)
        self._cid_release = fig.canvas.mpl_connect('button_release_event', on_release)
        self._cid_key = fig.canvas.mpl_connect('key_press_event', on_key)
        return None

    def customize_plot(self, unique_steps: Sequence[str]) -> None:
        """Customize axes, labels, and legend for the timeline figure."""

        df = self.df
        if self.ax is None or df is None:
            return

        # Set y-axis
        self.ax.set_yticks(range(len(unique_steps)))
        self.ax.set_yticklabels(list(unique_steps))
        self.ax.set_ylabel('Steps', fontsize=12, fontweight='bold')

        # Set x-axis (dates) with monthly locator/formatter as requested
        self.ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

        # Disable minor ticks to avoid extremely dense tick generation
        self.ax.minorticks_off()
        self.ax.xaxis.set_minor_locator(NullLocator())

        # Rotate date labels
        plt.xticks(rotation=45)
        self.ax.set_xlabel('Time', fontsize=12, fontweight='bold')

        # Set title
        self.ax.set_title('Simulation Timeline', fontsize=16, fontweight='bold', pad=20)

        # Add grid
        self.ax.grid(True, alpha=0.3, axis='x')

        # Dynamic legend for statuses+directions present (outside the plot area on the right)
        maintenance_mask = df['status'].isin(['maintenance', 'maintenance_curves'])
        has_carregado = bool((maintenance_mask & (df['direction'] != 'vazio')).any())
        has_vazio = bool((maintenance_mask & (df['direction'] == 'vazio')).any())
        present = set(df['status'].unique().tolist())
        handles = []
        if has_carregado:
            handles.append(mpatches.Patch(color='#3B82F6', label='Manutenção Principal/Carregado'))
        if has_vazio:
            handles.append(mpatches.Patch(color='#22C55E', label='Manutenção Desviada/Vazio'))
        if 'move' in present:
            handles.append(mpatches.Patch(color='#F97316', label='Movimento'))
        if 'wait' in present:
            handles.append(mpatches.Patch(color='#F2C744', label='Espera'))
        if 'turn' in present:
            handles.append(mpatches.Patch(color='#777777', label='Giro'))
        if has_carregado or has_vazio:
            handles.append(mpatches.Patch(facecolor='none', edgecolor='none', label='C = só curva · A = completa'))
        if handles:
            self.ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.02, 1.0), frameon=True, borderaxespad=0.0)

        # Adjust layout; leave space on the right for the legend
        plt.tight_layout(rect=(0.0, 0.0, 0.86, 1.0))
        return None

    def save_plot(self, filename: str = 'simulation_timeline.png', dpi: int = 300) -> None:
        """Save the current figure to disk if one has been generated."""
        if self.fig is None:
            print("No plot created. Please run create_timeline_plot() first.")
            return

        self.fig.savefig(filename, dpi=dpi, bbox_inches='tight')
        print(f"Plot saved as {filename}")
        return None

    def show_plot(self) -> None:
        """Display the timeline figure if one exists."""
        if self.fig is None:
            print("No plot created. Please run create_timeline_plot() first.")
            return

        plt.show()
        return None