# Copilot Instructions for nvidia-applet (Detailed Technical Spec)

This document provides deep technical details on the implementation strategies used in `applet.js` (Cinnamon JS/GJS) and `monitor.py` (Python GTK3).
**Note for guest developers:** This document is designed not only to guide the AI but to help you understand the *why* behind our architectural choices. Use this as a learning resource for understanding IPC, GIO, and Cinnamon applet design.

## 1. Applet Architecture & IPC (Inter-Process Communication)

The applet does not perform heavy graphing itself. It spawns a persistent Python subprocess (`monitor.py`) and feeds it real-time data via `stdin`.

**Why this architecture?**
Cinnamon applets run in the main Cinnamon process. Any heavy computation, blocking I/O, or complex plotting done directly in JS could block the Cinnamon main loop and make the UI unresponsive (the user's input would stop responding!). By offloading the visualization to a separate Python process, we ensure:
1.  **Isolation:** If the monitor crashes, Cinnamon stays alive.
2.  **Performance:** The heavy lifting of drawing graphed lines is done by Python/GTK, leaving the main Cinnamon process free for window management.

### 1.1 Spawning the Monitor Process
The applet uses `Gio.Subprocess` to launch the Python script. Arguments are passed to configure initial state (colors, axis units), but live data flows strictly over stdin.

**File:** `files/nvidia-monitor@kalin91/applet.js`
**Method:** `_openMonitor()`

**Technical Insight:**
We use `STDIN_PIPE` to establish a direct communication channel. This avoids the overhead of writing to temporary files on disk.

```javascript
// Arguments are constructed from current settings
let args = [
    "/usr/bin/python3",
    scriptPath,
    "--x", Math.round(x).toString(), // Absolute screen position
    "--color-gpu", this.gpu_color,   // Settings-defined colors
    // ... many other flags
];

// Spawn with STDIN_PIPE to allow streaming data
this._monitorProc = Gio.Subprocess.new(
    args,
    Gio.SubprocessFlags.STDIN_PIPE
);

this._monitorStdin = this._monitorProc.get_stdin_pipe();
```

### 1.2 Data Streaming Protocol
Data is gathered via `nvidia-smi`, parsed into a JSON object, and written to the pipe as a newline-delimited string. `GLib.Bytes` is used for safe buffer handling.

**Why GLib.Bytes?**
When working with GIO streams (`this._monitorStdin`), data must be passed as `GLib.Bytes` or raw byte arrays. `GLib.Bytes` provides an immutable wrapper around the data, which is efficient for passing memory between GLib functions. It helps avoid unnecessary copies and provides safe memory handling.

**Method:** `_sendToMonitor(data)`

```javascript
// data is an object: { ts, gpu, mem, temp, fan }
/* We use JSON because it is native to both JS and Python, making parsing trivial. */
let jsonStr = JSON.stringify(data) + "\n";
let bytes = GLib.Bytes.new(jsonStr);

// Writes to the Python process's standard input
/* flush() is critical to ensure the data is sent immediately and not buffered,
   minimizing latency on the graph. */
this._monitorStdin.write_bytes(bytes, null);
this._monitorStdin.flush(null);
```

## 2. Panel UI Custom drawing (Cairo/St)

The applet uses a hybrid approach for the panel UI: standard `St.Label` for text and `St.DrawingArea` for custom drawn elements (Pie charts, Vertical text).

**Why St and Cairo?**
*   **St (Shell Toolkit):** The standard library for Cinnamon UI widgets. Ideally, we use this for everything (buttons, layout).
*   **Cairo:** A 2D vector graphics library. We drop down to Cairo when we need to draw shapes (pies) or perform transformations (rotation) that standard St widgets don't support natively.

### 2.1 Vertical Orientation Handling
The applet explicitly supports `APPLET_ORIENT_LEFT` and `APPLET_ORIENT_RIGHT` by rotating text or reformatting strings.

**Strategy:**
1.  **Flag:** `this._turn_over` is set true for vertical panels.
2.  **Container:** `St.BoxLayout` switches `vertical: true` and alignment.
3.  **Text Rotation:** Uses `PangoCairo` to render text to a path, then rotates the context.

**Why PangoCairo?**
Drawing text purely with Cairo is difficult (you have to calculate font curves manually). **Pango** is a text layout engine that handles font selection, kerning, and Unicode. `PangoCairo` is the bridge that lets us draw Pango layouts onto a Cairo surface.

**Method:** `_draw_label`

```javascript
_draw_label = (actor, area) => {
    let cr = actor.get_context();
    let [w, h] = actor.get_surface_size();
    
    // Create layout
    let layout = PangoCairo.create_layout(cr);
    layout.set_text(area._custom_text || "", -1);

    // Rotate 90 degrees
    // We translate to center first to rotate around the center point, not the top-left corner.
    cr.translate(w / 2, h / 2);
    cr.rotate(Math.PI / 2); // 90 deg rotation

    // Center text visual
    cr.moveTo(-textWidth / 2, -textHeight / 2);
    PangoCairo.show_layout(cr, layout);
}
```

### 2.2 Pie Chart Rendering
Pie charts are drawn dynamically on `repaint` events using Cairo arcs.

**Method:** `_drawPie(area, percent, label)`

```javascript
// Background
cr.setSourceRGBA(0.2, 0.2, 0.2, 1.0);
cr.arc(centerX, centerY, radius, 0, 2 * Math.PI);
cr.fill();

// Data Slice (Green -> Red gradient logic)
if (percent > 0) {
    // Dynamic color calculation based on load
    if (percent < 0.5) { /* Green-ish */ } else { /* Red-ish */ }
    
    // Cairo uses a state-machine model. You set the source color, move the "pen",
    // describe the path (arc), and then fill it.
    cr.setSourceRGBA(r, g, b, 1.0);
    cr.moveTo(centerX, centerY);
    // Draw arc from -90deg (top) to load amount
    cr.arc(centerX, centerY, radius, -Math.PI / 2, -Math.PI / 2 + percent * 2 * Math.PI);
    cr.fill();
}
```

## 3. Monitor Backend (Python/GTK3)

The `monitor.py` script is a standalone GTK application that reads from stdin without blocking the UI.

### 3.1 Non-blocking Input Loop
It uses `GLib.io_add_watch` to listen for IO events on `sys.stdin`. This is critical for integrating file descriptor events with the GTK main loop.

**Critical Concept:**
Traditional python scripts use `input()` or `sys.stdin.read()`, but these block the program until data arrives. If we did that here, the window would freeze and not redraw or respond to clicks.
Instead, we use `GLib.io_add_watch` to tell the MAIN LOOP: "Call this function (`on_stdin_data`) only when there is data ready to read."

**File:** `files/nvidia-monitor@kalin91/scripts/monitor.py`
**Setup:**

```python
io_channel = GLib.IOChannel(sys.stdin.fileno())
# Watch for IN (data available) or HUP (pipe closed/parent died)
GLib.io_add_watch(io_channel, GLib.PRIORITY_DEFAULT, 
                  GLib.IOCondition.IN | GLib.IOCondition.HUP, 
                  self.on_stdin_data)
```

**Callback:** `on_stdin_data`

```python
def on_stdin_data(self, source, condition):
    if condition & GLib.IOCondition.HUP:
        Gtk.main_quit() # Exit if parent applet dies
        return False

    # Non-blocking read because we know data is waiting
    status, line, length, _ = source.read_line()
    if status == GLib.IOStatus.NORMAL and line:
        self.process_data(line) # Parse JSON and update state
    return True # Return True to keep the watch active
```

### 3.2 Graph Coordinate Calculation
The graph is redrawn on draw event (or data update). Coordinates are calculated mapping time/data-value to pixel space X/Y.

**Method:** `calculate_coords`

```python
def calculate_coords(self, width, height, graph_w, graph_h, margin_top, margin_right):
    coords = []
    # Calculate step per history point
    step_x = float(graph_w) / (self.max_history - 1)
    
    for i in range(points_to_draw):
        data = self.history[len(self.history) - 1 - i]
        
        # X: Right-aligned (Newest data at right edge)
        x = (width - margin_right) - (i * step_x)
        
        # Y: Inverted (0 at bottom, Height at top)
        # GTK coordinate system starts at (0,0) in top-left.
        # We need to invert the value so 100% load is at the top (low Y value).
        # val / max_val gives ratio (0.0 to 1.0)
        # (1 - ratio) flips it so 100% is at top (margin_top)
        def get_y(val, max_val=100.0):
             return margin_top + graph_h * (1 - (val / max_val))
        
        coords.append({ 'x': x, 'gpu': get_y(data['gpu']), ... })
    return coords
```

### 3.3 Dynamic Positioning
The window attempts to place itself adjacent to the panel, respecting screen boundaries.

**Method:** `setup_window_position`

```python
if orientation == 0: # TOP Panel
    target_x = x_applet + (w_applet / 2) - (win_w / 2) # Center horizontally on applet
    target_y = y_applet + h_applet + 5                 # Below panel
elif orientation == 1: # BOTTOM Panel
    target_y = y_applet - win_h - 5                    # Above panel

# Clamp to screen edges
target_x = max(0, min(target_x, screen_w - win_w))
target_y = max(0, min(target_y, screen_h - win_h))
self.window.move(int(target_x), int(target_y))
```

## 4. Settings Management

Settings are defined in `settings-schema.json` and bound in `applet.js`.

**Pattern:**
1.  **Schema:** JSON defines layout, widgets (combobox, spinbutton, colorchooser).
2.  **Binding:** Keys are bound to properties on the `applet` instance. Setting a bound property updates the variable automatically.
3.  **Reactivity:** A callback function triggers side effects (UI rebuild or Monitor reset).

**Why use settings.bind?**
It automates the tedious task of reading config files and updating variables. It also handles two-way binding: if the code changes the value, the settings UI updates, and if the user changes the UI, the variable updates.

```javascript
/* applet.js */
// AppletSettings is a wrapper provided by Cinnamon to simplify Gio.Settings usage
this.settings = new settings.AppletSettings(this, this._uuid, this._instance_id);

// Bind key "temp-color" to this.temp_color
// On change: call _resetMonitor() to restart python process with new args
this.settings.bind("temp-color", "temp_color", () => this._resetMonitor());

// Bind key "show-temp" to this.show_temp
// On change: call _on_update_display() to toggle label visibility immediately
this.settings.bind("show-temp", "show_temp", () => this._on_update_display());
```
