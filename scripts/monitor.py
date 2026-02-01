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
        args = parser.parse_args()

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
        self.setup_window_position(args)

        # Connect signals
        self.builder.connect_signals(self)
        self.window.connect("destroy", Gtk.main_quit)
        
        # Setup stdin reading
        io_channel = GLib.IOChannel(sys.stdin.fileno())
        # Priority must be lower than GDK redrawing but high enough
        GLib.io_add_watch(io_channel, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, self.on_stdin_data)

        self.window.show_all()

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
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Axes & Labels Config
        margin_left = 40  # For Temp labels
        margin_right = 40 # For % labels
        margin_bottom = 20 # For Time axis (future)
        margin_top = 10
        
        graph_w = width - margin_left - margin_right
        graph_h = height - margin_bottom - margin_top
        
        if graph_w <= 0 or graph_h <= 0: return # Too small

        # Draw Grid & Labels
        cr.set_line_width(1)
        cr.set_font_size(10)
        
        # Helper to draw text centered vertically at y
        def draw_text(text, x, y, align_right=True, color=(0.8, 0.8, 0.8)):
            cr.set_source_rgb(*color)
            extents = cr.text_extents(text)
            text_x = x - extents.width - 2 if align_right else x + 2
            text_y = y + extents.height / 2
            cr.move_to(text_x, text_y)
            cr.show_text(text)

        # Horizontal Grid (0%, 50%, 100%)
        # 0% (Bottom)
        y_0 = margin_top + graph_h
        y_50 = margin_top + graph_h / 2
        y_100 = margin_top
        
        # Grid Lines
        cr.set_source_rgba(0.3, 0.3, 0.3, 1.0)
        
        # 0% / 0C
        cr.move_to(margin_left, y_0)
        cr.line_to(width - margin_right, y_0)
        cr.stroke()
        draw_text("0°C", margin_left, y_0, align_right=True, color=(1, 0.5, 0.5))
        draw_text("0%", width - margin_right, y_0, align_right=False)
        
        # 50% / 50C
        cr.move_to(margin_left, y_50)
        cr.line_to(width - margin_right, y_50)
        cr.stroke()
        draw_text("50°C", margin_left, y_50, align_right=True, color=(1, 0.5, 0.5))
        draw_text("50%", width - margin_right, y_50, align_right=False)

        # 100% / 100C
        cr.move_to(margin_left, y_100)
        cr.line_to(width - margin_right, y_100)
        cr.stroke()
        draw_text("100°C", margin_left, y_100, align_right=True, color=(1, 0.5, 0.5))
        draw_text("100%", width - margin_right, y_100, align_right=False)

        if not self.history:
            return

        # Scaling
        # X: spread point across width
        step_x = graph_w / max(self.max_history - 1, 1)
        
        def draw_line(key, r, g, b, is_temp=False):
            cr.set_source_rgb(r, g, b)
            cr.set_line_width(2.0)
            
            first = True
            for i, data in enumerate(self.history):
                val = data.get(key, 0)
                
                # Normalize Y (Assuming 0-100 range for both % and Temp C)
                # If Temp > 100, clamp it
                normalized_val = min(max(val, 0), 100) / 100.0
                
                y = (margin_top + graph_h) - (normalized_val * graph_h)
                x = (margin_left + graph_w) - ((len(self.history) - 1 - i) * step_x)
                
                # Clip to graph area horizontally
                if x < margin_left: break
                
                if first:
                    cr.move_to(x, y)
                    first = False
                else:
                    cr.line_to(x, y)
            
            cr.stroke()

        # Draw Lines
        # Clipping area
        cr.rectangle(margin_left, margin_top, graph_w, graph_h)
        cr.clip()
        
        draw_line('gpu', 0.2, 0.8, 0.2) # Green
        draw_line('mem', 0.9, 0.9, 0.2) # Yellow
        draw_line('temp', 0.9, 0.3, 0.3, is_temp=True) # Red
        draw_line('fan', 0.3, 0.3, 0.9) # Blue
        
        # Reset clip
        cr.reset_clip()

if __name__ == "__main__":
    # Handle Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    app = MonitorNav()
    Gtk.main()
