import sys

from enum import Enum, auto
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Literal, Any, cast, Callable, ClassVar, TypedDict, Iterable, Self, TypeVar, Optional
from cairo import Context as CairoContext
from gi.repository import Gtk, Gdk  # type: ignore

T = TypeVar("T")


@dataclass
class Dimensions:
    class Cords(TypedDict):
        x: float
        data_series: dict[str, float]
        raw: dict[str, Any]
        step_x: float
        ts: str

    margin_left: int
    margin_right: int
    margin_bottom: int
    margin_top: int

    width: int = field(init=False)
    height: int = field(init=False)
    graph_width: int = field(init=False)
    graph_height: int = field(init=False)
    coords: list["Dimensions.Cords"] = field(default_factory=list)

    def update_size(self, widget: Gtk.Widget) -> Self:
        self.width = widget.get_allocated_width()
        self.height = widget.get_allocated_height()
        self.graph_width = self.width - self.margin_left - self.margin_right
        self.graph_height = self.height - self.margin_top - self.margin_bottom
        return self


class ColoredGraph(ABC):
    _color: tuple[float, float, float, float]
    _name: str

    @abstractmethod
    def draw(self, cr: CairoContext, d: Dimensions) -> None:
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


class DataSeries(ColoredGraph):
    # class properties
    _ctrl_box: ClassVar[Gtk.Box] = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    _ctrl_box.set_halign(Gtk.Align.CENTER)

    # Instance properties
    _show: bool
    _label: Gtk.Label
    _check: Gtk.CheckButton
    __format: Callable[[dict[str, Any], int], str]

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
    def format(self) -> Callable[[dict[str, Any], int], str]:
        return self.__format

    def __init__(
        self, name: str, color: str, builder: Gtk.Builder, format: Callable[[float, int], str], check_str: str
    ) -> None:
        super().__init__(name, color)
        self._show = True

        lbl_name = f"label_{name}"
        lbl: Gtk.Label = cast(Gtk.Label, builder.get_object(lbl_name))
        # setattr(self, lbl_name, lbl)
        lbl.set_name(lbl_name)  # For CSS targeting
        lbl.set_attributes(None)  # Clear Glade attributes to allow markup updates
        self._label = lbl
        self.__format = lambda dict_data, x: format(dict_data.get(self._name, 0), x)
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
        r, g, b, a = color_str
        return "#%02x%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255), int(a * 255))

    # Update labels with dynamic colors
    def update_label(self, dict_data: dict[str, Any]) -> None:
        text = self.format(dict_data, 0)
        color_hex = self.parse_to_pango_hex(self.color)  # originally was with string color
        self._label.set_markup(f"<span color='{color_hex}'>{text}</span>")

    def draw(self, cr: CairoContext, d: Dimensions) -> None:
        cr.set_source_rgba(*self.color)
        cr.set_line_width(2)
        first = True
        for pt in d.coords:
            if first:
                cr.move_to(pt["x"], pt["data_series"][self.name])
                first = False
            else:
                cr.line_to(pt["x"], pt["data_series"][self.name])
        cr.stroke()


class DataCairoAxis(ColoredGraph):
    class AxisProps(TypedDict):
        direction: Literal["leftToRight", "upToDown"]
        # values: tuple[float, float]
        steps: int

    class Edge(Enum):
        START = auto()
        INNER = auto()
        END = auto()

    __series: set[DataSeries]
    __props: AxisProps

    @property
    def series(self) -> set[DataSeries]:
        return self.__series

    @property
    def props(self) -> AxisProps:
        return self.__props

    @property
    def range(self) -> tuple[float, float]:
        return self.__range

    def __init__(
        self,
        name: str,
        color: str,
        range: tuple[float, float],
        series: set[DataSeries],
        props: AxisProps,
        lbl_text_fn: Callable[[Self, CairoContext, Dimensions, float, Edge], None],
    ) -> None:
        super().__init__(name, color)
        self.__series = series
        self.__props = props
        self.__lbl_text_fn = lbl_text_fn
        self.__range = range

    def draw_text(self, cr: CairoContext, text: str, x: float, y: float, align_right: bool) -> None:
        cr.set_source_rgba(*self.color)
        extents = cr.text_extents(text)
        text_x = x - extents.width - 2 if align_right else x + 2
        text_y = y + extents.height / 2
        cr.move_to(text_x, text_y)
        cr.show_text(text)

    def draw(self: Self, cr: CairoContext, d: Dimensions) -> None:
        for i in range(self.props["steps"] + 1):
            e: DataCairoAxis.Edge
            if i == 0:
                e = DataCairoAxis.Edge.START
            elif i == self.props["steps"]:
                e = DataCairoAxis.Edge.END
            else:
                e = DataCairoAxis.Edge.INNER
            r = i / float(self.props["steps"])
            self.__lbl_text_fn(self, cr, d, r, e)
        for s in [s for s in self.series if s.show]:
            s.draw(cr, d)


class DataCairoGrid(ColoredGraph):
    _cairo: set[DataCairoAxis]

    @property
    def cairo(self) -> set[DataCairoAxis]:
        return self._cairo

    def __init__(self, name: str, color: str, cairo: set[DataCairoAxis]) -> None:
        super().__init__(name, color)
        self._cairo = cairo

    def _all_identical(self, iterable: Iterable[T]) -> Optional[T]:
        iterator = iter(iterable)
        try:
            first = next(iterator)
        except StopIteration:
            return None
        for item in iterator:
            if item != first:
                raise ValueError("Not all values are identical")
        return first

    def draw(self, cr: CairoContext, d: Dimensions) -> None:
        graph_w = d.graph_width
        graph_h = d.graph_height

        if graph_w <= 0 or graph_h <= 0:
            print("Graph dimensions too small to draw grid.", file=sys.stderr)
            raise RuntimeError(f"Graph dimensions too small to draw grid. width={graph_w}, height={graph_h}")

        cr.set_font_size(10)
        active_axis: dict[str, list[DataCairoAxis]] = {
            "leftToRight": list(
                axis
                for axis in self._cairo
                if axis.props["direction"] == "leftToRight" and any(s.show for s in axis.series)
            ),
            "upToDown": list(
                axis
                for axis in self._cairo
                if axis.props["direction"] == "upToDown" and any(s.show for s in axis.series)
            ),
        }
        if active_axis["upToDown"]:
            ud_steps = self._all_identical(axis.props["steps"] for axis in active_axis["upToDown"])
            if ud_steps is None:
                print("No upToDown axes found, skipping grid drawing.", file=sys.stderr)
                raise RuntimeError("No upToDown axes found, skipping grid drawing.")
            print(f"Drawing grid with {ud_steps} horizontal steps.", file=sys.stderr)
            for i in range(ud_steps + 1):
                ratio = i / float(ud_steps)
                y = d.margin_top + graph_h * (1 - ratio)  # 0 at bottom

                # Grid Line (Horizontal)
                cr.set_source_rgba(*self.color)
                cr.move_to(d.margin_left, y)
                cr.line_to(d.width - d.margin_right, y)
                cr.stroke()
            for axis in active_axis["upToDown"]:
                axis.draw(cr, d)
        if active_axis["leftToRight"]:
            lr_steps = self._all_identical(axis.props["steps"] for axis in active_axis["leftToRight"])
            if lr_steps is None:
                print("No leftToRight axes found, skipping grid drawing.", file=sys.stderr)
                raise RuntimeError("No leftToRight axes found, skipping grid drawing.")
            for i in range(lr_steps + 1):
                ratio = i / float(lr_steps)
                x = d.margin_left + graph_w * ratio

                if 0 < i < lr_steps:
                    # Grid Line (Vertical)
                    cr.set_source_rgba(*self.color)
                    cr.move_to(x, d.margin_top)
                    cr.line_to(x, d.height - d.margin_bottom)
                    cr.stroke()
            for axis in active_axis["leftToRight"]:
                axis.draw(cr, d)


class DataCanvas(ColoredGraph):
    __graph: Gtk.DrawingArea
    __history: list[dict[str, Any]]
    __max_history: int
    __grid: DataCairoGrid
    __mouse_x: float

    @property
    def graph(self) -> Gtk.DrawingArea:
        return self.__graph

    @property
    def history(self) -> list[dict[str, Any]]:
        return self.__history

    @property
    def max_history(self) -> int:
        return self.__max_history

    @max_history.setter
    def max_history(self, value: int) -> None:
        self.__max_history = value

    @property
    def grid(self) -> DataCairoGrid:
        return self.__grid

    @property
    def mouse_x(self) -> float:
        return self.__mouse_x

    def _on_mouse_leave(self, widget, _event) -> None:
        self.tooltip_idx = -1
        widget.queue_draw()

    def _on_mouse_move(self, widget, event: Gdk.EventMotion) -> None:
        x = event.x

        if len(self.history) < 2:
            return

        # Determine index corresponding to X
        # Width per data point
        points_to_show = min(len(self.history), self.max_history)
        if points_to_show < 2:
            return

        self.__mouse_x = x
        self.graph.queue_draw()

    def _calculate_coords(self, d: Dimensions) -> None:
        d.coords.clear()

        if not self.history:
            return

        y_axis: set[DataCairoAxis] = {axis for axis in self.grid.cairo if axis.props["direction"] == "upToDown"}

        step_x = float(d.graph_width) / (self.max_history - 1) if self.max_history > 1 else d.graph_width
        points_to_draw = min(len(self.history), self.max_history)
        coords = d.coords
        for i in range(points_to_draw):
            data_idx = len(self.history) - 1 - i
            data = self.history[data_idx]

            x = (d.width - d.margin_right) - (i * step_x)

            ts = data.get("ts", "")
            if ts:
                try:
                    ts = ts.split("_")[1].split(".")[0]  # Extract HH:MM:SS
                except Exception:
                    pass  # Keep original if format unexpected
            else:
                ts = "N/A"

            body: "Dimensions.Cords" = {
                "x": x,
                "ts": ts,
                "raw": data,
                "step_x": step_x,
                "data_series": {},
            }

            def get_y(val, max_val=100.0):
                return d.margin_top + d.graph_height * (1 - (val / max_val))

            for axis in y_axis:
                for series in axis.series:
                    body["data_series"][series.name] = get_y(data.get(series.name, 0), axis.range[1])

            coords.append(body)

    def _draw_tooltip(self, cr: CairoContext, d: Dimensions) -> None:
        if self.mouse_x and d.coords:
            min_x = d.coords[-1]["x"]
            max_x = d.coords[0]["x"]

            if min_x <= self.mouse_x <= max_x:
                y_series_set = set(
                    series
                    for x in self.grid.cairo
                    if x.props["direction"] == "upToDown"
                    for series in x.series
                    if series.show
                )
                x_axis_set = set(x for x in self.grid.cairo if x.props["direction"] == "leftToRight")
                if len(x_axis_set) != 1:
                    print("Tooltip logic currently only supports exactly 1 leftToRight axis.", file=sys.stderr)
                    raise RuntimeError("Tooltip logic currently only supports exactly 1 leftToRight axis.")
                x_axis = next(iter(x_axis_set))

                # Find closest point
                # Simple distance check or index calc
                # We can reuse the index calc logic but coords are inverted order in list vs screen X
                # Let's just search closest X
                closest_pt = min(d.coords, key=lambda pt: abs(pt["x"] - self.mouse_x))

                # Draw vertical line
                cr.set_source_rgba(1, 1, 1, 0.5)
                cr.set_line_width(1)
                cr.move_to(closest_pt["x"], d.margin_top)
                cr.line_to(closest_pt["x"], d.height - d.margin_bottom)
                cr.stroke()

                # Draw Info Box
                lines = []
                data = closest_pt["raw"]

                # Time
                ts = closest_pt["ts"]
                lines.append((f"Time: {ts}", x_axis.color))

                for series in y_series_set:
                    lines.append((series.format(data, 1), series.color))

                # Box dims
                box_w = 100
                box_h = len(lines) * 15 + 10
                box_x = closest_pt["x"] + 10
                box_y = d.margin_top + 10

                # Flip if too close to edge
                if box_x + box_w > d.width:
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

    def __init__(
        self, name: str, color: str, graph: Gtk.DrawingArea, grid: DataCairoGrid, d: Dimensions, max_history: int
    ) -> None:
        super().__init__(name, color)
        self.__mouse_x = 0.0
        self.tooltip_idx = -1
        self.__history = []
        self.__max_history = max_history
        self.__graph = graph
        self.__grid = grid
        self.__graph.connect("draw", lambda w, cr: self.draw(cr, d.update_size(w)))

        # Tooltip interactions
        self.__graph.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.__graph.connect("motion-notify-event", self._on_mouse_move)
        self.__graph.connect("leave-notify-event", self._on_mouse_leave)

    def draw(self, cr: CairoContext, d: Dimensions) -> None:
        try:
            self._calculate_coords(d)
            if not d.coords:
                return
            cr.set_source_rgba(*self.color)
            cr.rectangle(0, 0, self.__graph.get_allocated_width(), self.__graph.get_allocated_height())
            cr.fill()
            self.__grid.draw(cr, d)
            self._draw_tooltip(cr, d)
        except Exception as e:
            print(f"Error during draw: {e}", file=sys.stderr)
            raise RuntimeError(f"Error during draw: {e}")

    def draw_data(self, new_data: dict[str, Any]) -> None:
        self.history.append(new_data)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        for series in set().union(*(c.series for c in self.grid.cairo)):
            series.update_label(new_data)
        self.graph.queue_draw()

    def add_controls(self) -> None:
        for series in set().union(*(c.series for c in self.grid.cairo)):
            series.add_control(self.graph)
        parent = self.graph.get_parent()
        if not parent or not isinstance(parent, Gtk.Box):
            raise RuntimeError("Graph has no parent Box to add controls to.")
        parent.pack_start(DataSeries.get_ctrl_box(), False, False, 0)
