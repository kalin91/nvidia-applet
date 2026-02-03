#!/usr/bin/env python3

import sys
import os
import json
import gi
import signal
import argparse

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk

class MonitorNav:
    def __init__(self):
        self.history = []
        self.max_history = 120 # Keep 2 minutes of history @ 1s interval (adjustable)
        
        # Parse Args
        parser = argparse.ArgumentParser()
        parser.add_argument("--x", type=float, default=0)
        parser.add_argument("--y", type=float, default=0)
        parser.add_argument("--width", type=float, default=0)
        parser.add_argument("--height", type=float, default=0)
        parser.add_argument("--orientation", type=int, default=1) # Default BOTTOM
        # Settings Args
        parser.add_argument("--interval", type=float, default=1.5)
        parser.add_argument("--color-gpu", type=str, default="#0ed815")
        parser.add_argument("--color-mem", type=str, default="#fbff07")
        parser.add_argument("--color-temp", type=str, default="#f51717")
        parser.add_argument("--color-fan", type=str, default="#7805e4")
        parser.add_argument("--color-bg", type=str, default="#000000")
        parser.add_argument("--ysteps", type=int, default=3)
        parser.add_argument("--xunit", type=str, default="seconds")
        parser.add_argument("--xlength", type=float, default=60)
        
        self.args = parser.parse_args()

        # Config derived from args
        self.interval = max(0.5, self.args.interval)
        self.max_history = int(self.args.xlength / self.interval) if self.args.xunit == 'seconds' else \
                           int((self.args.xlength * 60) / self.interval) if self.args.xunit == 'minutes' else \
                           int((self.args.xlength * 3600) / self.interval)
        
        self.colors = {
            'gpu': self.hex_to_rgb(self.args.color_gpu),
            'mem': self.hex_to_rgb(self.args.color_mem),
            'temp': self.hex_to_rgb(self.args.color_temp),
            'fan': self.hex_to_rgb(self.args.color_fan),
            'bg': self.hex_to_rgb(self.args.color_bg),
            'text': self.get_inverse_color(self.args.color_bg)
        }

        # Visibility states (default all true)
        self.show_gpu = True
        self.show_mem = True
        self.show_temp = True
        self.show_fan = True
        
        # Load UI
        curr_dir = os.path.dirname(os.path.realpath(__file__))
        glade_file = os.path.join(curr_dir, "../ui/monitor_window.glade")
        
        self.builder = Gtk.Builder()
        self.builder.add_from_file(glade_file)
        
        self.window = self.builder.get_object("monitor_window")
        self.graph_area = self.builder.get_object("graph_area")
        
        self.label_gpu = self.builder.get_object("label_gpu")
        self.label_mem = self.builder.get_object("label_mem")
        self.label_temp = self.builder.get_object("label_temp")
        self.label_fan = self.builder.get_object("label_fan")

        # Position Window
        self.setup_window_position(self.args)

        # Add toggle controls
        self.add_controls()

        # Connect signals
        self.builder.connect_signals(self)
        self.window.connect("destroy", Gtk.main_quit)
        self.graph_area.connect("draw", self.on_draw)
        
        # Tooltip interactions
        self.graph_area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.graph_area.connect("motion-notify-event", self.on_mouse_move)
        self.graph_area.connect("leave-notify-event", self.on_mouse_leave)
        self.tooltip_idx = -1
        
        # Setup stdin reading
        io_channel = GLib.IOChannel(sys.stdin.fileno())
        GLib.io_add_watch(io_channel, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, self.on_stdin_data)

        self.window.show_all()

    def hex_to_rgb(self, color_str):
        # Handle rgb(r,g,b) format
        if color_str.startswith("rgb"):
            try:
                # Extract content inside parens: rgb(224,27,36) -> 224,27,36
                content = color_str.split('(')[1].split(')')[0]
                parts = content.split(',')
                if len(parts) >= 3:
                     return (int(parts[0])/255.0, int(parts[1])/255.0, int(parts[2])/255.0)
            except Exception as e:
                print(f"Error parsing RGB string '{color_str}': {e}", file=sys.stderr)
                return (1.0, 0.0, 1.0) # Error magenta

        # Handle hex format
        hex_str = color_str.lstrip('#')
        try:
            if len(hex_str) < 6: return (1.0, 1.0, 1.0) # fallback
            return tuple(int(hex_str[i:i+2], 16)/255.0 for i in (0, 2, 4))
        except ValueError:
             return (1.0, 1.0, 1.0)
        
    def get_inverse_color(self, hex_bg):
        r, g, b = self.hex_to_rgb(hex_bg)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b)
        return (0, 0, 0) if luminance > 0.5 else (1, 1, 1)

    def add_controls(self):
        # Insert a new HBox at the top of the window vbox for toggles
        # Glade structure: window -> box_main -> (box_header, graph_area, ...)
        # We will insert between header and graph or just append to graph area
        pass
        # Since I can't easily see the GLADE structure ID names, I'll try to find the parent of graph_area
        parent = self.graph_area.get_parent()
        if isinstance(parent, Gtk.Box):
            ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            ctrl_box.set_halign(Gtk.Align.CENTER)
            
            # Helper to create styled checkbox
            def create_chk(label, key, color):
                chk = Gtk.CheckButton.new_with_label(label)
                chk.set_active(True)
                chk.connect("toggled", self.on_toggle_visibility, key)
                # Try to colorize (limited in standard GTK3 without custom CSS provider)
                # We can wrap the label in a colored markup if we want, but keeping it simple for now.
                return chk

            self.chk_gpu = create_chk("GPU", 'gpu', self.colors['gpu'])
            self.chk_mem = create_chk("RAM", 'mem', self.colors['mem'])
            self.chk_temp = create_chk("Temp", 'temp', self.colors['temp'])
            self.chk_fan = create_chk("Fan", 'fan', self.colors['fan'])
            
            ctrl_box.pack_start(self.chk_gpu, False, False, 0)
            ctrl_box.pack_start(self.chk_mem, False, False, 0)
            ctrl_box.pack_start(self.chk_temp, False, False, 0)
            ctrl_box.pack_start(self.chk_fan, False, False, 0)
            
            # Find index of graph_area to insert before/after
            # Not crucial, just pack at start (top) or end (bottom)
            # Parent is likely vertical box. Let's put it at the bottom.
            parent.pack_start(ctrl_box, False, False, 0)

    def on_toggle_visibility(self, button, name):
        if name == 'gpu': self.show_gpu = button.get_active()
        elif name == 'mem': self.show_mem = button.get_active()
        elif name == 'temp': self.show_temp = button.get_active()
        elif name == 'fan': self.show_fan = button.get_active()
        self.graph_area.queue_draw()

    def on_mouse_leave(self, widget, event):
        self.tooltip_idx = -1
        widget.queue_draw()

    def on_mouse_move(self, widget, event):
        rect = widget.get_allocation()
        x = event.x
        
        if len(self.history) < 2:
            return
            
        # Determine index corresponding to X
        # Width per data point
        points_to_show = min(len(self.history), self.max_history)
        if points_to_show < 2: return
        
        step_x = rect.width / (self.max_history - 1)
        
        # Cursor X relative to right edge (since graph moves left)
        # But we render from right to left? No, usually left to right for history or right-anchored.
        # Let's check draw logic. Assuming standard time graph: T-max ... T-0
        # If we draw newest at right:
        # data[0] is oldest?
        
        # Let's rely on on_draw to confirm order.
        # For now, just calculate step and trigger redraw with mouse pos
        self.mouse_x = x
        self.graph_area.queue_draw()

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
        screen_w = screen.get_width()
        screen_h = screen.get_height()

        if orientation == 0: # TOP
            target_x = x_applet + (w_applet / 2) - (win_w / 2)
            target_y = y_applet + h_applet + 5 # Little margin
        elif orientation == 1: # BOTTOM
            target_x = x_applet + (w_applet / 2) - (win_w / 2)
            target_y = y_applet - win_h - 5
        elif orientation == 2: # LEFT
            target_x = x_applet + w_applet + 5
            target_y = y_applet + (h_applet / 2) - (win_h / 2)
        elif orientation == 3: # RIGHT
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
            
        return True # Continue watching

    def process_data(self, line):
        try:
            data = json.loads(line)
            # Expected format: {"gpu": float, "mem": float, "temp": float, "fan": float}
            
            self.history.append(data)
            # print(f"DEBUG DATA: {data}", file=sys.stderr)
            if len(self.history) > self.max_history:
                self.history.pop(0)
            
            # Update labels
            self.label_gpu.set_text(f"GPU: {data.get('gpu', 0):.0f}%")
            self.label_mem.set_text(f"Mem: {data.get('mem', 0):.0f}%")
            self.label_temp.set_text(f"Temp: {data.get('temp', 0):.0f}°C")
            self.label_fan.set_text(f"Fan: {data.get('fan', 0):.0f}%")
            
            self.graph_area.queue_draw()
            
        except json.JSONDecodeError:
            pass # Ignore partial lines
        except Exception as e:
            print(f"Error processing data: {e}", file=sys.stderr)

    def on_draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        
        # Background
        cr.set_source_rgb(*self.colors['bg'])
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Axes & Labels Config
        margin_left = 40  # For Temp labels
        margin_right = 40 # For % labels
        margin_bottom = 20 # For Time axis
        margin_top = 10
        
        graph_w = width - margin_left - margin_right
        graph_h = height - margin_bottom - margin_top
        
        if graph_w <= 0 or graph_h <= 0: return # Too small

        self.draw_grid_and_labels(cr, width, height, graph_h, margin_left, margin_right, margin_top, margin_bottom)
        
        coords = self.calculate_coords(width, height, graph_w, graph_h, margin_top, margin_right)
        if not coords: return

        self.draw_data_lines(cr, coords)
        self.draw_tooltip(cr, width, height, margin_top, margin_bottom, coords)

    def draw_grid_and_labels(self, cr, width, height, graph_h, margin_left, margin_right, margin_top, margin_bottom):
        # Text Color
        text_col = self.colors['text']

        # Helper to draw text
        cr.set_font_size(10)
        def draw_text(text, x, y, align_right=True, color=text_col):
            cr.set_source_rgb(*color)
            extents = cr.text_extents(text)
            text_x = x - extents.width - 2 if align_right else x + 2
            text_y = y + extents.height / 2
            cr.move_to(text_x, text_y)
            cr.show_text(text)

        # Draw Grid & Y-Axis Labels
        cr.set_line_width(1)
        steps = max(1, self.args.ysteps)
        
        for i in range(steps + 1):
            ratio = i / float(steps)
            y = margin_top + graph_h * (1 - ratio) # 0 at bottom
            
            # Grid Line
            cr.set_source_rgba(0.3, 0.3, 0.3, 0.5)
            cr.move_to(margin_left, y)
            cr.line_to(width - margin_right, y)
            cr.stroke()
            
            # Labels
            # Left: Temp (0 - 100 C assumed)
            temp_val = int(ratio * 100)
            draw_text(f"{temp_val}°C", margin_left, y, align_right=True, color=self.colors['temp'])
            
            # Right: Unit % (0 - 100 %)
            pct_val = int(ratio * 100)
            draw_text(f"{pct_val}%", width - margin_right, y, align_right=False)

        # X-Axis Labels (Time)
        cr.set_source_rgb(*text_col)
        draw_text("Now", width - margin_right, height - 5, align_right=True)
        draw_text(f"{self.args.xlength} {self.args.xunit} ago", margin_left, height - 5, align_right=False)

    def calculate_coords(self, width, height, graph_w, graph_h, margin_top, margin_right):
        if not self.history: return []

        # How many points fit?
        # self.max_history is the capacity for the visible window
        step_x = float(graph_w) / (self.max_history - 1) if self.max_history > 1 else graph_w
        points_to_draw = min(len(self.history), self.max_history)
        
        coords = []
        for i in range(points_to_draw):
            data_idx = len(self.history) - 1 - i
            data = self.history[data_idx]
            
            x = (width - margin_right) - (i * step_x)
            
            def get_y(val):
                return margin_top + graph_h * (1 - (val / 100.0))
            
            coords.append({
                'x': x,
                'gpu': get_y(data.get('gpu', 0)),
                'mem': get_y(data.get('mem', 0)),
                'temp': get_y(data.get('temp', 0)),
                'fan': get_y(data.get('fan', 0)),
                'raw': data,
                'step_x': step_x 
            })
        return coords

    def draw_data_lines(self, cr, coords):
        # Draw Paths
        def draw_line(key, color):
            cr.set_source_rgb(*color)
            cr.set_line_width(2)
            first = True
            for pt in coords:
                if first:
                    cr.move_to(pt['x'], pt[key])
                    first = False
                else:
                    cr.line_to(pt['x'], pt[key])
            cr.stroke()

        if self.show_gpu: draw_line('gpu', self.colors['gpu'])
        if self.show_mem: draw_line('mem', self.colors['mem'])
        if self.show_temp: draw_line('temp', self.colors['temp'])
        if self.show_fan: draw_line('fan', self.colors['fan'])

    def draw_tooltip(self, cr, width, height, margin_top, margin_bottom, coords):
        # Tooltip / Hover Cursor
        if hasattr(self, 'mouse_x') and coords:
             # Need step_x value which we stored in coords
            step_x = coords[0]['step_x']
            margin_right = width - coords[0]['x'] # approx
            # Better: recalculate or check range
            # Range check:
            min_x = coords[-1]['x']
            max_x = coords[0]['x']

            if min_x <= self.mouse_x <= max_x:
                # Find closest point
                # Simple distance check or index calc
                # We can reuse the index calc logic but coords are inverted order in list vs screen X
                # Let's just search closest X
                closest_pt = min(coords, key=lambda pt: abs(pt['x'] - self.mouse_x))
                
                # Draw vertical line
                cr.set_source_rgba(1, 1, 1, 0.5)
                cr.set_line_width(1)
                cr.move_to(closest_pt['x'], margin_top)
                cr.line_to(closest_pt['x'], height - margin_bottom)
                cr.stroke()
                
                # Draw Info Box
                lines = []
                data = closest_pt['raw']
                if self.show_gpu: lines.append((f"GPU: {data.get('gpu', 0):.1f}%", self.colors['gpu']))
                if self.show_mem: lines.append((f"MEM: {data.get('mem', 0):.1f}%", self.colors['mem']))
                if self.show_temp: lines.append((f"TMP: {data.get('temp', 0):.1f}°C", self.colors['temp']))
                if self.show_fan: lines.append((f"FAN: {data.get('fan', 0):.1f}%", self.colors['fan']))
                
                # Box dims
                box_w = 100
                box_h = len(lines) * 15 + 10
                box_x = closest_pt['x'] + 10
                box_y = margin_top + 10
                
                # Flip if too close to edge
                if box_x + box_w > width:
                    box_x = closest_pt['x'] - box_w - 10
                
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
                    cr.set_source_rgb(*col)
                    cr.move_to(box_x + 5, ty)
                    cr.show_text(text)
                    ty += 15


if __name__ == "__main__":
    # Handle Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    app = MonitorNav()
    Gtk.main()
