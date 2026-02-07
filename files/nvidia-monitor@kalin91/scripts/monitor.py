#!/usr/bin/env python3

import sys
from dataclasses import dataclass
import os
import json
import signal
import argparse
from typing import cast
from gi import require_version
from cairo import Context as CairoContext
from gi.repository import Gtk, GLib, Gdk  # type: ignore
from colored_graph import DataCanvas, DataSeries, DataCairoGrid, DataCairoAxis, Dimensions

require_version("Gtk", "3.0")


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
    __window: Gtk.Window
    __graph_area: DataCanvas

    @property
    def args(self) -> AppletArgs:
        return self._args

    @property
    def window(self) -> Gtk.Window:
        return self.__window

    @property
    def graph_area(self) -> DataCanvas:
        return self.__graph_area

    def __init__(self, builder: Gtk.Builder):
        try:
            # Parse Args
            parser = argparse.ArgumentParser()
            for f in AppletArgs.__dataclass_fields__.values():
                parser.add_argument(
                    f"--{f.name.replace('_', '-')}",
                    type=f.type,
                    default=f.default,
                )

            self._args = parser.parse_args(namespace=AppletArgs())

            # Config derived from args
            self.interval = max(0.5, self.args.interval)
            max_history = (
                int(self.args.xlength / self.interval)
                if self.args.xunit == "seconds"
                else (
                    int((self.args.xlength * 60) / self.interval)
                    if self.args.xunit == "minutes"
                    else int((self.args.xlength * 3600) / self.interval)
                )
            )

            def temp_format(v: float, x: int) -> str:
                if self.args.temp_unit == "F":
                    return f"TMP: {(v * 9 / 5) + 32:.{x}f}°F"
                else:
                    return f"TMP: {v:.{x}f}°C"

            series: list[DataSeries] = [
                DataSeries("gpu", self.args.color_gpu, builder, lambda v, x: f"GPU: {v:.{x}f}%", "GPU"),
                DataSeries("mem", self.args.color_mem, builder, lambda v, x: f"RAM: {v:.{x}f}%", "RAM"),
                DataSeries("fan", self.args.color_fan, builder, lambda v, x: f"Fan: {v:.{x}f}%", "Fan"),
                DataSeries("temp", self.args.color_temp, builder, temp_format, "Temp"),
            ]
            graph = cast(Gtk.DrawingArea, builder.get_object("graph_area"))

            dimensions = Dimensions(
                40,  # For Temp labels
                40,  # For % labels
                20,  # For Time axis
                10,
            )
            # Load UI
            self.__window = cast(Gtk.Window, builder.get_object("monitor_window"))
            self.__graph_area = DataCanvas(
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
                            (0, 110),
                            {series[3]},
                            {"steps": self.args.ysteps, "direction": "upToDown"},
                            self.temp_label_text,
                        ),  # TEMP only
                        DataCairoAxis(
                            "axis_pct",
                            self.args.color_axis_pct,
                            (0, 100),
                            set(series[:3]),
                            {"steps": self.args.ysteps, "direction": "upToDown"},
                            self.pct_label_text,
                        ),  # GPU, MEM, FAN
                        DataCairoAxis(
                            "axis_x",
                            self.args.color_axis_x,
                            (self.args.xlength, 0),
                            set(series),
                            {"steps": self.args.xsteps, "direction": "leftToRight"},
                            self.x_label_text,
                        ),
                    },
                ),
                dimensions,
                max_history,
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
        except Exception as e:
            print(f"Error parsing arguments: {e}", file=sys.stderr)
            raise RuntimeError(f"Error parsing arguments: {e}")

    def temp_label_text(
        self, inst: DataCairoAxis, cr: CairoContext, d: Dimensions, ratio: float, _edge: DataCairoAxis.Edge
    ) -> None:
        temp_val_c = int(ratio * 110)
        y = d.margin_top + d.graph_height * (1 - ratio)
        x = d.margin_left
        text = f"{temp_val_c}°C"
        if self.args.temp_unit == "F":
            text = f"{int((temp_val_c * 9 / 5) + 32)}°F"
        inst.draw_text(cr, text, x, y, align_right=True)

    def pct_label_text(
        self, inst: DataCairoAxis, cr: CairoContext, d: Dimensions, ratio: float, edge: DataCairoAxis.Edge
    ) -> None:
        pct_val = int(ratio * 100)
        y = d.margin_top + d.graph_height * (1 - ratio)
        x = d.width - d.margin_right
        text = f"{pct_val}%"
        inst.draw_text(cr, text, x, y, align_right=False)

    def x_label_text(
        self, inst: DataCairoAxis, cr: CairoContext, d: Dimensions, ratio: float, edge: DataCairoAxis.Edge
    ) -> None:
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

        x = d.margin_left + d.graph_width * ratio
        y = d.height - d.margin_bottom + 5
        if edge == DataCairoAxis.Edge.INNER:
            # Manual centering hack
            cr.set_source_rgba(*inst.color)
            ext = cr.text_extents(text)
            cur_x = x - ext.width / 2
            cur_y = d.height - 5 + ext.height / 2
            cr.move_to(cur_x, cur_y)
            cr.show_text(text)
        else:
            align_right = edge == DataCairoAxis.Edge.END
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
            raise RuntimeError(f"Error reading stdin: {e}") from e

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
