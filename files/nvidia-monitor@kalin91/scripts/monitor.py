#!/usr/bin/env python3

from re import I
import sys
from dataclasses import dataclass, field
import os
import json
import math
import signal
import argparse
from abc import ABC, abstractmethod
from typing import Literal, Any, cast, Callable, ClassVar, TypedDict, Iterable, Self
from gi import require_version
from cairo import Context as CairoContext
from gi.repository import Gtk, GLib, Gdk  # , Pango #type: ignore

require_version("Gtk", "3.0")


@dataclass
class Dimensions:
    margin_left: int
    margin_right: int
    margin_bottom: int
    margin_top: int
    width: int
    height: int

    graph_width: int = field(init=False)
    graph_height: int = field(init=False)

    def __post_init__(self):
        self.graph_width = self.width - self.margin_left - self.margin_right
        self.graph_height = self.height - self.margin_top - self.margin_bottom


class ColoredData(ABC):
    _color: tuple[float, float, float, float]
    _name: str

    @abstractmethod
    def draw(self, cr: CairoContext) -> None:
        pass

    @property
    def color(self) -> tuple:
        return self._color

    @color.setter
    def color(self, value: tuple) -> None:
        self._color = value

    @property
    def name(self) -> str:
        return self._name

    def __init__(self, name: str, color: str) -> None:
        self._color = self._hex_to_rgb(color)
        self._name = name

    def _hex_to_rgb(self, color_str: str) -> tuple[float, float, float, float]:

        try:
            c = color_str.strip("'\" ")
            # Handle hex
            if c.startswith("#"):
                hex_s = c.lstrip("#")
                if len(hex_s) == 3:
                    hex_s = "".join(x * 2 for x in hex_s)
                if len(hex_s) >= 6:
                    r = int(hex_s[0:2], 16) / 255.0
                    g = int(hex_s[2:4], 16) / 255.0
                    b = int(hex_s[4:6], 16) / 255.0
                    a = 1.0
                    if len(hex_s) == 8:
                        a = int(hex_s[6:8], 16) / 255.0
                    return (r, g, b, a)

            # Handle rgb/rgba
            elif c.startswith("rgb"):
                content = c.split("(")[1].split(")")[0]
                parts = [x.strip() for x in content.split(",")]
                if len(parts) >= 3:
                    vals = [float(x) for x in parts]
                    r, g, b = vals[0], vals[1], vals[2]
                    a = vals[3] if len(vals) > 3 else 1.0
                    # Normalize if 0-255 range
                    if r > 1.0 or g > 1.0 or b > 1.0:
                        r /= 255.0
                        g /= 255.0
                        b /= 255.0
                    return (r, g, b, a)
        except Exception as e:
            print(f"Error parsing color '{color_str}': {e}", file=sys.stderr)
            return (1.0, 0.0, 1.0, 1.0)  # Error magenta

        return (1.0, 1.0, 1.0, 1.0)  # Fallback white


class DataSeries(ColoredData):
    # class properties
    _ctrl_box: ClassVar[Gtk.Box] = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    _ctrl_box.set_halign(Gtk.Align.CENTER)

    # Instance properties
    _show: bool
    _label: Gtk.Label
    _check: Gtk.CheckButton

    @classmethod
    def get_ctrl_box(cls) -> Gtk.Box:
        return cls._ctrl_box

    @property
    def show(self) -> bool:
        return self._show

    @show.setter
    def show(self, value: bool) -> None:
        self._show = value

    @property
    def format(self) -> Callable[[dict[str, Any]], None]:
        return self._format

    def __init__(
        self, name: str, color: str, builder: Gtk.Builder, format: Callable[[float], str], check_str: str
    ) -> None:
        super().__init__(name, color)
        self._show = True

        lbl_name = f"label_{name}"
        lbl: Gtk.Label = cast(Gtk.Label, builder.get_object(lbl_name))
        # setattr(self, lbl_name, lbl)
        lbl.set_name(lbl_name)  # For CSS targeting
        lbl.set_attributes(None)  # Clear Glade attributes to allow markup updates
        self._label = lbl
        self._format = lambda dict_data: self._set_lbl(format(dict_data[self._name]))
        chk: Gtk.CheckButton = Gtk.CheckButton.new_with_label(check_str)
        chk.set_active(True)
        self._check = chk

    def add_control(self, parent_draw: Gtk.DrawingArea) -> None:
        self._check.connect("toggled", self._on_toggle, parent_draw)
        self.get_ctrl_box().pack_start(self._check, False, False, 0)

    def _on_toggle(self, button, parent_draw: Gtk.DrawingArea) -> None:
        self.show = button.get_active()
        parent_draw.queue_draw()

    def parse_to_pango_hex(self, color_str):
        """Converts rgba/rgb string to Pango hex color #RRGGBBAA using consistent parser"""
        r, g, b, a = self._hex_to_rgb(color_str)
        return "#%02x%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255), int(a * 255))

    # Update labels with dynamic colors
    def _set_lbl(self, text):
        color_hex = self.parse_to_pango_hex(self.color)  # originally was with string color
        self._label.set_markup(f"<span color='{color_hex}'>{text}</span>")

    def draw(self, cr: CairoContext) -> None:
        pass  # Placeholder for interface consistency


class DataCairoAxis(ColoredData):
    class AxisProps(TypedDict):
        direction: Literal["leftToRight", "upToDown"]
        # values: tuple[float, float]
        steps: int

    __graph_dimensions: Dimensions
    __series: set[DataSeries]
    __props: AxisProps

    @property
    def series(self) -> set[DataSeries]:
        return self.__series

    @property
    def props(self) -> AxisProps:
        return self.__props

    @property
    def graph_dimensions(self) -> Dimensions:
        return self.__graph_dimensions

    def __init__(
        self,
        name: str,
        color: str,
        series: set[DataSeries],
        props: AxisProps,
        graph_dimensions: Dimensions,
        lbl_text_fn: Callable[[Self, CairoContext], None],
    ) -> None:
        super().__init__(name, color)
        self.__series = series
        self.__props = props
        self.__graph_dimensions = graph_dimensions
        self.__lbl_text_fn = lbl_text_fn

    def draw_text(self, cr: CairoContext, text: str, x: float, y: float, align_right: bool) -> None:
        cr.set_source_rgba(*self.color)
        extents = cr.text_extents(text)
        text_x = x - extents.width - 2 if align_right else x + 2
        text_y = y + extents.height / 2
        cr.move_to(text_x, text_y)
        cr.show_text(text)

    def draw(self: Self, cr: CairoContext) -> None:
        self.__lbl_text_fn(self, cr)


def tuples_equal(a: tuple[float, ...], b: tuple[float, ...], tol=1e-9) -> bool:
    return all(math.isclose(x, y, rel_tol=tol, abs_tol=tol) for x, y in zip(a, b))


class DataCairoGrid(ColoredData):
    _cairo: set[DataCairoAxis]
    _dimensions: Dimensions

    @property
    def cairo(self) -> set[DataCairoAxis]:
        return self._cairo

    @property
    def dimensions(self) -> Dimensions:
        return self._dimensions

    def __init__(self, name: str, color: str, cairo: set[DataCairoAxis], dimensions: Dimensions) -> None:
        super().__init__(name, color)
        self._cairo = cairo
        self._dimensions = dimensions

    def _all_identical(self, iterable: Iterable) -> bool:
        iterator = iter(iterable)
        try:
            first = next(iterator)
        except StopIteration:
            return True  # Vacío: se considera "todos iguales"
        for item in iterator:
            if item != first:
                raise ValueError("Not all values are identical")
        return True

    def draw(self, cr: CairoContext) -> None:
        graph_w = self._dimensions.graph_width
        graph_h = self._dimensions.graph_height

        if graph_w <= 0 or graph_h <= 0:
            print("Graph dimensions too small to draw grid.", file=sys.stderr)
            raise RuntimeError("Graph dimensions too small to draw grid.")

        cr.set_font_size(10)
        axis_prescence = {
            "leftToRight": self._all_identical(
                iterable=(
                    axis.props["steps"] if any(s.show for s in axis.series) else 0
                    for axis in self._cairo
                    if axis.props["direction"] == "leftToRight"
                )
            ),
            "upToDown": self._all_identical(
                iterable=(
                    axis.props["steps"] if any(s.show for s in axis.series) else 0
                    for axis in self._cairo
                    if axis.props["direction"] == "upToDown"
                )
            ),
        }
        if axis_prescence["upToDown"]:
            for i in range(axis_prescence["upToDown"] + 1):
                ratio = i / float(axis_prescence["steps"])
                y = self._dimensions.margin_top + graph_h * (1 - ratio)  # 0 at bottom

                # Grid Line (Horizontal)
                cr.set_source_rgba(*self.color)
                cr.move_to(self._dimensions.margin_left, y)
                cr.line_to(self._dimensions.width - self._dimensions.margin_right, y)
                cr.stroke()
            for i in range(axis_prescence["leftToRight"] + 1):
                ratio = i / float(axis_prescence["steps"])
                x = self._dimensions.margin_left + graph_w * ratio

                if 0 < i < axis_prescence["leftToRight"]:
                    # Grid Line (Vertical)
                    cr.set_source_rgba(*self.color)
                    cr.move_to(x, self._dimensions.margin_top)
                    cr.line_to(x, self._dimensions.height - self._dimensions.margin_bottom)
                    cr.stroke()

        for axis in self._cairo:
            if any(s.show for s in axis.series):
                axis.draw(cr)


class DataGraph(ColoredData):
    _graph: Gtk.DrawingArea
    _history: list[dict[str, Any]]
    _grid: DataCairoGrid

    @property
    def graph(self) -> Gtk.DrawingArea:
        return self._graph

    @property
    def history(self) -> list[dict[str, Any]]:
        return self._history

    @property
    def max_history(self) -> int:
        return self._max_history

    @max_history.setter
    def max_history(self, value: int) -> None:
        self._max_history = value

    @property
    def grid(self) -> DataCairoGrid:
        return self._grid

    def _on_mouse_leave(self, widget, _event) -> None:
        self.tooltip_idx = -1
        widget.queue_draw()

    def _on_mouse_move(self, widget, event) -> None:
        rect = widget.get_allocation()
        x = event.x

        if len(self.history) < 2:
            return

        # Determine index corresponding to X
        # Width per data point
        points_to_show = min(len(self.history), self.max_history)
        if points_to_show < 2:
            return

        step_x = rect.width / (self.max_history - 1)

        # Cursor X relative to right edge (since graph moves left)
        # But we render from right to left? No, usually left to right for history or right-anchored.
        # Let's check draw logic. Assuming standard time graph: T-max ... T-0
        # If we draw newest at right:
        # data[0] is oldest?

        # Let's rely on on_draw to confirm order.
        # For now, just calculate step and trigger redraw with mouse pos
        self.mouse_x = x
        self.graph.queue_draw()

    def __init__(self, name: str, color: str, graph: Gtk.DrawingArea, grid: DataCairoGrid) -> None:
        super().__init__(name, color)
        self.tooltip_idx = -1
        self._history = []
        self._max_history = 120  # Keep 2 minutes of history @ 1s interval (adjustable)
        self._graph = graph
        self._grid = grid
        self._graph.connect("draw", self.on_draw)

        # Tooltip interactions
        self._graph.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self._graph.connect("motion-notify-event", self._on_mouse_move)
        self._graph.connect("leave-notify-event", self._on_mouse_leave)

    def draw(self, cr: CairoContext) -> None:
        cr.set_source_rgba(*self.color)
        cr.rectangle(0, 0, self._graph.get_allocated_width(), self._graph.get_allocated_height())
        cr.fill()
        self._grid.draw(cr)

    def draw_data(self, new_data: dict[str, Any]) -> None:
        self.history.append(new_data)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        for series in set().union(*(c.series for c in self.grid.cairo)):
            series.format(new_data)
        self.graph.queue_draw()

    def add_controls(self) -> None:
        for series in set().union(*(c.series for c in self.grid.cairo)):
            series.add_control(self.graph)
        parent = self.graph.get_parent()
        if not parent or not isinstance(parent, Gtk.Box):
            raise RuntimeError("Graph has no parent Box to add controls to.")
        parent.pack_start(DataSeries.get_ctrl_box(), False, False, 0)


@dataclass
class AppletArgs:
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    orientation: int = 1

    interval: float = 1.5
    color_gpu: str = "#0ed815"
    color_mem: str = "#fbff07"
    color_temp: str = "#f51717"
    color_fan: str = "#7805e4"
    color_bg: str = "#000000"
    color_axis_temp: str = "#ffffff"
    color_axis_pct: str = "#ffffff"
    color_axis_x: str = "#ffffff"
    color_grid: str = "rgba(255,255,255,0.3)"
    ysteps: int = 3
    temp_unit: str = "C"
    xsteps: int = 3
    xunit: str = "seconds"
    xlength: float = 60


class MonitorNav:
    _color_components: set[ColoredData]
    _window: Gtk.Window
    _graph_area: DataGraph

    @property
    def args(self) -> AppletArgs:
        return self._args

    @property
    def color_components(self) -> set[ColoredData]:
        return self._color_components

    @property
    def window(self) -> Gtk.Window:
        return self._window

    @property
    def graph_area(self) -> DataGraph:
        return self._graph_area

    @property
    def history(self) -> list[dict[str, Any]]:
        return self.graph_area.history

    @property
    def max_history(self) -> int:
        return self.graph_area.max_history

    @max_history.setter
    def max_history(self, value: int) -> None:
        self.graph_area.max_history = value

    def __init__(self, builder: Gtk.Builder):
        self.max_history = 120

        # Parse Args
        parser = argparse.ArgumentParser()
        for field in AppletArgs.__dataclass_fields__.values():
            parser.add_argument(
                f"--{field.name.replace('_', '-')}",
                type=field.type,
                default=field.default,
            )

        self._args = parser.parse_args(namespace=AppletArgs())

        # Config derived from args
        self.interval = max(0.5, self.args.interval)
        self.max_history = (
            int(self.args.xlength / self.interval)
            if self.args.xunit == "seconds"
            else (
                int((self.args.xlength * 60) / self.interval)
                if self.args.xunit == "minutes"
                else int((self.args.xlength * 3600) / self.interval)
            )
        )

        def temp_format(v: float) -> str:
            if self.args.temp_unit == "F":
                return f"Temp: {(v * 9 / 5) + 32:.0f}°F"
            else:
                return f"Temp: {v:.0f}°C"

        series: list[DataSeries] = [
            DataSeries("gpu", self.args.color_gpu, builder, lambda v: f"GPU: {v:.0f}%", "GPU"),
            DataSeries("mem", self.args.color_mem, builder, lambda v: f"RAM: {v:.0f}%", "RAM"),
            DataSeries("fan", self.args.color_fan, builder, lambda v: f"Fan: {v:.0f}%", "Fan"),
            DataSeries("temp", self.args.color_temp, builder, temp_format, "Temp"),
        ]
        graph = cast(Gtk.DrawingArea, builder.get_object("graph_area"))

        dimensions = Dimensions(
            40,  # For Temp labels
            40,  # For % labels
            20,  # For Time axis
            10,
            graph.get_allocated_height(),
            graph.get_allocated_width(),
        )
        # Load UI
        self._window = cast(Gtk.Window, builder.get_object("monitor_window"))
        self._graph_area = DataGraph(
            "bg",
            self.args.color_bg,
            graph,
            DataCairoGrid(
                "grid",
                self.args.color_grid,
                {
                    DataCairoAxis(
                        "axis_temp",
                        self.args.color_axis_temp,
                        {series[3]},
                        {"steps": self.args.ysteps, "direction": "upToDown"},
                        dimensions,
                        self.temp_label_text,
                    ),  # TEMP only
                    DataCairoAxis(
                        "axis_pct",
                        self.args.color_axis_pct,
                        set(series[:3]),
                        {"steps": self.args.ysteps, "direction": "upToDown"},
                        dimensions,
                        self.pct_label_text,
                    ),  # GPU, MEM, FAN
                    DataCairoAxis(
                        "axis_x",
                        self.args.color_axis_x,
                        set(series),
                        {"steps": self.args.xsteps, "direction": "leftToRight"},
                        dimensions,
                        self.x_label_text,
                    ),
                },
                dimensions,
            ),
        )
        # Position Window
        self.setup_window_position(self.args)

        # Add toggle controls
        self.graph_area.add_controls()

        # Connect signals
        builder.connect_signals(self)
        self.window.connect("destroy", Gtk.main_quit)

        # Setup stdin reading
        io_channel = GLib.IOChannel.unix_new(sys.stdin.fileno())
        GLib.io_add_watch(
            io_channel, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, self.on_stdin_data
        )

        self.window.show_all()

    def temp_label_text(self, inst: DataCairoAxis, cr: CairoContext) -> None:
        ysteps = inst.props["steps"]
        for i in range(ysteps + 1):
            ratio = i / float(ysteps)
            temp_val_c = int(ratio * 110)
            y = inst.graph_dimensions.margin_top + inst.graph_dimensions.graph_height * (1 - ratio)
            x = inst.graph_dimensions.margin_left
            text = f"{temp_val_c}°C"
            if self.args.temp_unit == "F":
                text = f"{int((temp_val_c * 9 / 5) + 32)}°F"
            inst.draw_text(cr, text, x, y, align_right=True)

    def pct_label_text(self, inst: DataCairoAxis, cr: CairoContext) -> None:
        ysteps = inst.props["steps"]
        for i in range(ysteps + 1):
            ratio = i / float(ysteps)
            pct_val = int(ratio * 100)
            y = inst.graph_dimensions.margin_top + inst.graph_dimensions.graph_height * (1 - ratio)
            x = inst.graph_dimensions.width - inst.graph_dimensions.margin_right
            text = f"{pct_val}%"
            inst.draw_text(cr, text, x, y, align_right=False)

    def x_label_text(self, inst: DataCairoAxis, cr: CairoContext) -> None:
        xsteps = inst.props["steps"]
        for i in range(xsteps + 1):
            ratio = i / float(xsteps)
            time_val = self.args.xlength * (1 - ratio)
            unit_char = self.args.xunit[0]
            if unit_char == "s":
                text = f"{int(time_val)}s"
            elif unit_char == "m":
                if time_val < 1:
                    text = f"{int(time_val * 60)}s"
                else:
                    text = f"{time_val:.1f}m".replace(".0m", "m")
            else:
                text = f"{time_val:.1f}h".replace(".0h", "h")

            x = inst.graph_dimensions.margin_left + inst.graph_dimensions.graph_width * ratio
            y = inst.graph_dimensions.height - inst.graph_dimensions.margin_bottom + 5
            if 0 < i < xsteps:
                # Manual centering hack
                cr.set_source_rgba(*inst.color)
                ext = cr.text_extents(text)
                cur_x = x - ext.width / 2
                cur_y = inst.graph_dimensions.height - 5 + ext.height / 2
                cr.move_to(cur_x, cur_y)
                cr.show_text(text)
            else:
                align_right = i == xsteps
                inst.draw_text(cr, text, x, y, align_right=align_right)

    def setup_window_position(self, args):
        # We need the window size to calculate position properly,
        # but window isn't realized/sized yet.
        # We can use default size from glade for initial calc
        win_w = 600
        win_h = 350

        # Args: applet position and size
        x_applet = args.x
        y_applet = args.y
        w_applet = args.width
        h_applet = args.height
        orientation = args.orientation

        # Cinnamon Side: TOP=0, BOTTOM=1, LEFT=2, RIGHT=3
        target_x = 0
        target_y = 0

        screen = Gdk.Screen.get_default()
        if not screen:
            print("Error: Unable to get default screen.", file=sys.stderr)
            raise RuntimeError("Unable to get default screen.")
        screen_w = screen.get_width()
        screen_h = screen.get_height()

        if orientation == 0:  # TOP
            target_x = x_applet + (w_applet / 2) - (win_w / 2)
            target_y = y_applet + h_applet + 5  # Little margin
        elif orientation == 1:  # BOTTOM
            target_x = x_applet + (w_applet / 2) - (win_w / 2)
            target_y = y_applet - win_h - 5
        elif orientation == 2:  # LEFT
            target_x = x_applet + w_applet + 5
            target_y = y_applet + (h_applet / 2) - (win_h / 2)
        elif orientation == 3:  # RIGHT
            target_x = x_applet - win_w - 5
            target_y = y_applet + (h_applet / 2) - (win_h / 2)

        # Clamp to screen
        target_x = max(0, min(target_x, screen_w - win_w))
        target_y = max(0, min(target_y, screen_h - win_h))

        self.window.move(int(target_x), int(target_y))

        # Ensure it's not behind panel if possible?
        # self.window.set_keep_above(True)

    def on_delete_event(self, *args):
        Gtk.main_quit()
        return True

    def on_stdin_data(self, source, condition):
        if condition & GLib.IOCondition.HUP:
            print("Parent closed pipe, exiting...", file=sys.stderr)
            Gtk.main_quit()
            return False

        try:
            # GLib.IOChannel.read_line returns (status, line, length, terminator_pos)
            # We need to unpack 4 values
            result = source.read_line()
            if len(result) == 4:
                status, line, length, terminator_pos = result
            elif len(result) == 3:
                status, line, terminator_pos = result
            else:
                # Fallback if unsure
                status = result[0]
                line = result[1]

            if status == GLib.IOStatus.NORMAL and line:
                self.process_data(line)
        except Exception as e:
            print(f"Error reading stdin: {e}", file=sys.stderr)

        return True  # Continue watching

    def process_data(self, line):
        try:
            data = json.loads(line)

            # Handle commands
            if "command" in data:
                cmd = data["command"]
                if cmd == "present":
                    self.window.present()
                return

            self.graph_area.draw_data(data)

        except json.JSONDecodeError:
            pass  # Ignore partial lines, review later
        except Exception as e:
            print(f"Error processing data: {e}", file=sys.stderr)

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        # Background
        cr.set_source_rgba(*self.colors["bg"])
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Axes & Labels Config
        margin_left = 40  # For Temp labels
        margin_right = 40  # For % labels
        margin_bottom = 20  # For Time axis
        margin_top = 10

        graph_w = width - margin_left - margin_right
        graph_h = height - margin_bottom - margin_top

        if graph_w <= 0 or graph_h <= 0:
            return  # Too small

        self.draw_grid_and_labels(cr, width, height, graph_h, margin_left, margin_right, margin_top, margin_bottom)

        coords = self.calculate_coords(width, height, graph_w, graph_h, margin_top, margin_right)
        if not coords:
            return

        self.draw_data_lines(cr, coords)
        self.draw_tooltip(cr, width, height, margin_top, margin_bottom, coords)

    def draw_grid_and_labels(self, cr, width, height, graph_h, margin_left, margin_right, margin_top, margin_bottom):
        # Colors from settings
        pass

    def calculate_coords(self, width, height, graph_w, graph_h, margin_top, margin_right):
        if not self.history:
            return []

        # How many points fit?
        # self.max_history is the capacity for the visible window
        step_x = float(graph_w) / (self.max_history - 1) if self.max_history > 1 else graph_w
        points_to_draw = min(len(self.history), self.max_history)

        coords = []
        for i in range(points_to_draw):
            data_idx = len(self.history) - 1 - i
            data = self.history[data_idx]

            x = (width - margin_right) - (i * step_x)

            def get_y(val, max_val=100.0):
                return margin_top + graph_h * (1 - (val / max_val))

            coords.append(
                {
                    "x": x,
                    "gpu": get_y(data.get("gpu", 0)),
                    "mem": get_y(data.get("mem", 0)),
                    "temp": get_y(data.get("temp", 0), 110.0),  # Temp max 110
                    "fan": get_y(data.get("fan", 0)),
                    "raw": data,
                    "step_x": step_x,
                }
            )
        return coords

    def draw_data_lines(self, cr, coords):
        # Draw Paths
        def draw_line(key, color):
            cr.set_source_rgba(*color)
            cr.set_line_width(2)
            first = True
            for pt in coords:
                if first:
                    cr.move_to(pt["x"], pt[key])
                    first = False
                else:
                    cr.line_to(pt["x"], pt[key])
            cr.stroke()

        if self.show_gpu:
            draw_line("gpu", self.colors["gpu"])
        if self.show_mem:
            draw_line("mem", self.colors["mem"])
        if self.show_temp:
            draw_line("temp", self.colors["temp"])
        if self.show_fan:
            draw_line("fan", self.colors["fan"])

    def draw_tooltip(self, cr, width, height, margin_top, margin_bottom, coords):
        # Tooltip / Hover Cursor
        if hasattr(self, "mouse_x") and coords:
            # Need step_x value which we stored in coords
            step_x = coords[0]["step_x"]
            margin_right = width - coords[0]["x"]  # approx
            # Better: recalculate or check range
            # Range check:
            min_x = coords[-1]["x"]
            max_x = coords[0]["x"]

            if min_x <= self.mouse_x <= max_x:
                # Find closest point
                # Simple distance check or index calc
                # We can reuse the index calc logic but coords are inverted order in list vs screen X
                # Let's just search closest X
                closest_pt = min(coords, key=lambda pt: abs(pt["x"] - self.mouse_x))

                # Draw vertical line
                cr.set_source_rgba(1, 1, 1, 0.5)
                cr.set_line_width(1)
                cr.move_to(closest_pt["x"], margin_top)
                cr.line_to(closest_pt["x"], height - margin_bottom)
                cr.stroke()

                # Draw Info Box
                lines = []
                data = closest_pt["raw"]

                # Time
                ts_str = data.get("ts", "")  # e.g. 2024/02/02_12:00:00.000
                if ts_str:
                    # Clean format. Assuming YYYY/MM/DD_HH:MM:SS.msec
                    # Extract HH:MM:SS
                    try:
                        time_part = ts_str.split("_")[1].split(".")[0]
                        lines.append((f"Time: {time_part}", self.colors["axis_x"]))
                    except:
                        lines.append((f"Time: {ts_str}", self.colors["axis_x"]))

                if self.show_gpu:
                    lines.append((f"GPU: {data.get('gpu', 0):.1f}%", self.colors["gpu"]))
                if self.show_mem:
                    lines.append((f"MEM: {data.get('mem', 0):.1f}%", self.colors["mem"]))
                if self.show_temp:
                    t_val = data.get("temp", 0)
                    t_s = f"{t_val:.1f}°C"
                    if self.args.temp_unit == "F":
                        t_s = f"{(t_val * 9 / 5) + 32:.1f}°F"
                    lines.append((f"TMP: {t_s}", self.colors["temp"]))
                if self.show_fan:
                    lines.append((f"FAN: {data.get('fan', 0):.1f}%", self.colors["fan"]))

                # Box dims
                box_w = 100
                box_h = len(lines) * 15 + 10
                box_x = closest_pt["x"] + 10
                box_y = margin_top + 10

                # Flip if too close to edge
                if box_x + box_w > width:
                    box_x = closest_pt["x"] - box_w - 10

                # Box BG
                cr.set_source_rgba(0, 0, 0, 0.8)
                cr.rectangle(box_x, box_y, box_w, box_h)
                cr.fill()
                cr.set_source_rgb(1, 1, 1)
                cr.rectangle(box_x, box_y, box_w, box_h)
                cr.stroke()

                # Text
                ty = box_y + 12
                for text, col in lines:
                    cr.set_source_rgba(*col)
                    cr.move_to(box_x + 5, ty)
                    cr.show_text(text)
                    ty += 15


if __name__ == "__main__":
    # Handle Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # Create GTK Builder
    builder = Gtk.Builder()
    curr_dir = os.path.dirname(os.path.realpath(__file__))
    glade_file = os.path.join(curr_dir, "../ui/monitor_window.glade")
    builder.add_from_file(glade_file)
    app = MonitorNav(builder)
    del builder  # Free builder memory
    Gtk.main()
