const { applet, settings, popupMenu, main: Main } = imports.ui;
const { GLib, St, Clutter, Pango, PangoCairo, Gio } = imports.gi;

class NvidiaMonitorApplet extends applet.Applet {

    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);
        this.orientation = orientation;
        this.metadata = metadata;
        this._panel_height = panel_height;
        this.app_name = metadata.name

        // Inicializar historial
        this.history = [];
        this.max_history_points = 43200;

        this._updateLoopId = null;
        this.last_output = "";
        this._memUsedPercent = 0;
        this._gpuUtilPercent = 0;
        this._fanSpeedPercent = 0;
        this._tempValue = 0;

        this._buildUI(panel_height);
        try {
            this._buildMenu();
            if (!GLib.find_program_in_path('nvidia-smi')) {
                this.set_applet_label("nvidia-smi not found");
                return this._show_err('nvidia-smi not found in PATH.\nPlease ensure NVIDIA drivers are installed.');
            }

            this._initSettings(metadata, instance_id);

            this.set_applet_tooltip("Displays NVIDIA GPU monitor");

            this.on_settings_changed();
        } catch (e) {
            global.logError(e);
            this._show_err("Error initializing applet: " + e.message);
            this.set_applet_label("Init Error");
        }
    }

    _buildMenu() {
        try {
            if (!this.menuManager) this.menuManager = new popupMenu.PopupMenuManager(this);
            
            // Re-create menu carefully
            if (this.menu) {
                this.menuManager.removeMenu(this.menu);
                this.menu.destroy();
            }

            // Usar this.orientation para que el menú sepa hacia dónde abrirse (Arriba/Abajo)
            // Use St.Side enum or verify this.orientation is valid (usually 0 or 1)
            this.menu = new applet.AppletPopupMenu(this, this.orientation);
            
            // Important: Set the actor explicitly as source if needed, though constructor does it.
            // But if actor allocation is weird, we can force box.
            // this.menu.sourceActor = this.actor; 

            this.menuManager.addMenu(this.menu);

            // Sección de Gráfica (External Monitor)
            let monitorItem = new popupMenu.PopupMenuItem("Open Monitor Graph");
            monitorItem.connect('activate', () => this._openMonitor());
            this.menu.addMenuItem(monitorItem);

        } catch (e) {
            global.logError(e);
            this._show_err("Error building menu: " + e.message);
        }
    }

    _openMonitor() {
        if (this._monitorProc) {
            // Bring to front or just return
            return;
        }

        try {
            let scriptPath = GLib.build_filenamev([this.metadata.path, "scripts", "monitor.py"]);
            
            // Get coordinates
            // Ensure allocation is up to date
            let [x, y] = this.actor.get_transformed_position();
            let [w, h] = this.actor.get_transformed_size();
            let orientation = this.orientation; 

            // Subprocess arguments - Explicitly invoke python3
            let args = [
                "/usr/bin/python3",
                scriptPath,
                "--x", Math.round(x).toString(),
                "--y", Math.round(y).toString(),
                "--width", Math.round(w).toString(),
                "--height", Math.round(h).toString(),
                "--orientation", orientation.toString()
            ];
            
            // Log for debugging
            global.log("Nvidia Monitor: Launching " + args.join(" "));

            // Subprocess with Stdin pipe
            this._monitorProc = Gio.Subprocess.new(
                args,
                Gio.SubprocessFlags.STDIN_PIPE
            );
            
            this._monitorStdin = this._monitorProc.get_stdin_pipe();
            
            // Send existing history to populate graph immediately
            if (this.history && this.history.length > 0) {
                 global.log("Nvidia Monitor: Sending " + this.history.length + " history points.");
                 for (let point of this.history) {
                     this._sendToMonitor(point);
                 }
            }

            // Watch for exit
            this._monitorProc.wait_check_async(null, (proc, result) => {
                try {
                    proc.wait_check_finish(result);
                } catch (e) {
                   global.logError("Nvidia Monitor subprocess exited with error: " + e.message);
                }
                this._monitorProc = null;
                this._monitorStdin = null;
            });

        } catch (e) {
            global.logError("Error starting monitor: " + e.message);
            this._show_err("Could not start monitor script: " + e.message);
        }
    }

    _sendToMonitor(data) {
        if (!this._monitorProc || !this._monitorStdin) return;

        try {
            let jsonStr = JSON.stringify(data) + "\n";
            // Use GLib.Bytes for safe encoding/handling
            let bytes = GLib.Bytes.new(jsonStr);
            this._monitorStdin.write_bytes(bytes, null);
            this._monitorStdin.flush(null);
        } catch (e) {
            // Broken pipe likely
            global.logError("Error sending to monitor: " + e.message);
            this._monitorProc = null; 
            this._monitorStdin = null;
        }
    }


    _show_err(msg) {
        let icon = new St.Icon({
            icon_name: 'dialog-warning',
            icon_type: St.IconType.FULLCOLOR,
            icon_size: 36
        });
        const title = `${this.app_name} Error`;
        Main.criticalNotify(title, msg, icon);
    }

    _buildUI(panel_height) {

        // Create main container
        this._box = new St.BoxLayout({
            style_class: 'applet-box',
            y_align: Clutter.ActorAlign.CENTER
        });
        this.actor.add(this._box);

        // Separator string
        let sepText = " | ";
        this._pieChartSize = Math.max(16, panel_height - 6);

        // 1. Temp Label
        this._label = this._add_label("Initializing...");
        this._label.show();

        // 2. Sep 1
        this._sep1 = this._add_label(sepText);

        // 3. Mem Label
        this._memLabel = this._add_label("");

        // 4. Mem Pie Chart (Renamed from _pieChartArea)
        this._memPieChartArea = this._add_pieChartArea(this._drawMemPie.bind(this));

        // 5. Sep 2
        this._sep2 = this._add_label(sepText);

        // 6. GPU Label
        this._gpuLabel = this._add_label("");

        // 7. GPU Pie Chart
        this._gpuPieChartArea = this._add_pieChartArea(this._drawGpuPie.bind(this));

        // 8. Sep 3
        this._sep3 = this._add_label(sepText);

        // 9. Fan Label
        this._fanLabel = this._add_label("");

        // 10. Fan Pie Chart
        this._fanPieChartArea = this._add_pieChartArea(this._drawFanPie.bind(this));
    }

    _add_label(text) {
        const label = new St.Label({ text: text, y_align: Clutter.ActorAlign.CENTER });
        // Fix for truncation bug on restart: create CLUTTER_TEXT and disable ellipsization
        label.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
        this._add_to_box(label);
        return label;
    }

    _add_pieChartArea(fnCallback) {
        const res = new St.DrawingArea({
            width: this._pieChartSize,
            height: this._pieChartSize,
            style: 'margin-left: 2px; margin-right: 2px;'
        });
        res.connect('repaint', area => fnCallback(area));
        this._add_to_box(res);
        return res;
    }

    _add_to_box(actor) {
        this._box.add(actor, { y_fill: false, y_align: St.Align.MIDDLE });
        actor.hide();
    }

    _initSettings(metadata, instance_id) {

        this.settings = new settings.AppletSettings(this, metadata.uuid, instance_id);

        this.settings.bind("refresh-interval", "refresh_interval", () => this.on_settings_changed());
        this.settings.bind("encoding", "encoding", () => this.on_settings_changed());
        this.settings.bind("show-temp", "show_temp", () => this.on_update_display());
        this.settings.bind("temp-unit", "temp_unit", () => this.on_update_display());
        this.settings.bind("show-memory", "show_memory", () => this.on_update_display());
        this.settings.bind("memory-display-mode", "memory_display_mode", () => this.on_update_display());
        this.settings.bind("show-gpu-util", "show_gpu_util", () => this.on_update_display());
        this.settings.bind("gpu-display-mode", "gpu_display_mode", () => this.on_update_display());
        this.settings.bind("show-fan-speed", "show_fan_speed", () => this.on_update_display());
        this.settings.bind("fan-display-mode", "fan_display_mode", () => this.on_update_display());

    }

    set_applet_label(text) {
        this._label.set_text(text);
        this._label.show();
    }

    on_settings_changed() {
        if (this._updateLoopId) {
            GLib.Source.remove(this._updateLoopId);
        }
        this._decoder = new TextDecoder(this.encoding);
        this._updateLoop();
    }
    
    on_orientation_changed(orientation) {
        this.orientation = orientation;
        if (this.menu) {
            this.menu.destroy();
            this.menu = null;
            this._buildMenu();
        }
    }

    on_update_display() {
        if (this.last_output) {
            this.parse_and_display(this.last_output);
        }
    }

    _updateLoop() {
        this.update();

        let interval = Math.max(this.refresh_interval * 1000, 500);

        this._updateLoopId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, interval, () => {
            this._updateLoop();
            return false;
        });
    }

    update() {
        try {
            // Use full path to nvidia-smi
            let [success, stdout, stderr, exit_status] = GLib.spawn_command_line_sync('/usr/bin/nvidia-smi --query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu,fan.speed,timestamp --format=csv,noheader,nounits');

            if (success) {
                let output = this._decoder.decode(stdout);
                this.last_output = output;
                this.parse_and_display(output);
            } else {
                this.set_applet_label("Error");
                this._show_err(`Failed to run nvidia-smi.\n${stderr ? stderr.toString() : "Unknown"}`);
                global.logError("Nvidia Monitor: Failed to run nvidia-smi. Stderr: " + (stderr ? stderr.toString() : "Unknown"));
            }
        } catch (e) {
            global.logError(e);
            this._show_err("An unexpected error occurred while running nvidia-smi.\n" + e.message);
            this.set_applet_label("Err");
        }
    }

    _drawMemPie(area) {
        this._drawPie(area, this._memUsedPercent, "Mem");
    }

    _drawGpuPie(area) {
        this._drawPie(area, this._gpuUtilPercent, "GPU");
    }

    _drawFanPie(area) {
        this._drawPie(area, this._fanSpeedPercent, "Fan");
    }

    _drawPie(area, percent, label) {
        let [width, height] = area.get_surface_size();
        let cr = area.get_context();

        let centerX = width / 2;
        let centerY = height / 2;
        let radius = Math.min(width, height) / 2 - 1;

        // Background circle (Darker gray for better text contrast)
        cr.setSourceRGBA(0.2, 0.2, 0.2, 1.0);
        cr.arc(centerX, centerY, radius, 0, 2 * Math.PI);
        cr.fill();

        // Used portion (green to red gradient based on usage)
        let r, g, b;
        if (percent > 0) {
            // Color goes from green (low usage) to yellow to red (high usage)
            if (percent < 0.5) {
                r = percent * 2;
                g = 0.8;
                b = 0.2;
            } else {
                r = 1.0;
                g = 0.8 * (1 - (percent - 0.5) * 2);
                b = 0.2;
            }
            cr.setSourceRGBA(r, g, b, 1.0);

            // Draw pie slice starting from top (-PI/2)
            cr.moveTo(centerX, centerY);
            cr.arc(centerX, centerY, radius, -Math.PI / 2, -Math.PI / 2 + percent * 2 * Math.PI);
            cr.closePath();
            cr.fill();
        }

        // Draw Label using Pango
        if (label) {
            let layout = PangoCairo.create_layout(cr);
            layout.set_text(label, -1);

            // Dynamic font size: ~35% of diameter (increased from 25%)
            let fontSize = Math.max(8, Math.min(width, height) * 0.32);
            let desc = Pango.FontDescription.from_string("Sans Bold");
            desc.set_absolute_size(fontSize * Pango.SCALE);
            layout.set_font_description(desc);

            // Brighter Blue for contrast against dark background
            if (percent < 0.5) {
                cr.setSourceRGBA(0.7, 0.25, 0.0, 1.0);
            } else if (percent < 0.75) {
                cr.setSourceRGBA(0.15, 0.75, 0.15, 1.0);
            } else {
                cr.setSourceRGBA(1 - r, 1 - g, 1 - b, 1.0);
            }
            let [inkRect, logicalRect] = layout.get_pixel_extents();
            let textWidth = logicalRect.width;
            let textHeight = logicalRect.height;

            cr.moveTo(centerX - textWidth / 2, centerY - textHeight / 2);
            PangoCairo.show_layout(cr, layout);
        }

        // Draw border
        // Clear path to avoid connecting text end-point to the circle start (artifact fix)
        cr.newPath();
        cr.setSourceRGBA(0.7, 0.7, 0.7, 1.0);
        cr.setLineWidth(1);
        cr.arc(centerX, centerY, radius, 0, 2 * Math.PI);
        cr.stroke();

        cr.$dispose();
    }

    parse_and_display(output) {
        let parts = output.trim().split(',').map(function (s) { return s.trim(); });
        if (parts.length < 6) return;

        let temp = parts[0];
        let memUsed = parseFloat(parts[1]);
        let memTotal = parseFloat(parts[2]);
        let gpuUtil = parseFloat(parts[3]);
        let fanSpeed = parseFloat(parts[4]);
        let timestamp = parts[5].replace(/ /g, "_");

        // Calculate percentages
        this._memUsedPercent = memTotal > 0 ? memUsed / memTotal : 0;
        this._gpuUtilPercent = gpuUtil / 100.0;
        this._fanSpeedPercent = fanSpeed / 100.0;
        this._tempValue = parseFloat(temp);

        let visTemp = false;
        
        // --- POC LOGGING ---
        try {
            if (!this._logFilePath) 
                this._logFilePath = `${GLib.get_tmp_dir()}/nvidia-monitor-${Math.floor(Date.now() / 1000)}.jsonl`;
            
            let logEntry = JSON.stringify({
                ts: timestamp, 
                gpu: gpuUtil,
                mem: memUsed,
                fan: fanSpeed,
                temp: this._tempValue
            }) + "\n";

            let file = Gio.File.new_for_path(this._logFilePath);
            let outStream = file.append_to(Gio.FileCreateFlags.NONE, null);
            outStream.write_all(logEntry, null);
            outStream.close(null);
        } catch (e) {
             if (!this._logErr) { global.logError("Log error: " + e.message); this._logErr = true; }
        }

        // Guardar en historial
        this.history.push({
            gpu: gpuUtil,
            mem: this._memUsedPercent * 100,
            temp: this._tempValue,
            fan: fanSpeed
        });

        // Send to external monitor if running
        this._sendToMonitor({
            gpu: gpuUtil,
            mem: this._memUsedPercent * 100,
            temp: this._tempValue,
            fan: fanSpeed
        });

        // Temp logic
        if (this.show_temp) {
            let displayTemp = temp;
            if (this.temp_unit === "F") {
                displayTemp = (parseFloat(temp) * 9 / 5 + 32).toFixed(1);
            }
            this._label.set_text(displayTemp + "°" + this.temp_unit);
            this._label.show();
            visTemp = true;
        } else {
            this._label.hide();
        }

        const visMem = this._updateSection(
            this.show_memory,
            this.memory_display_mode,
            this._memLabel,
            this._memPieChartArea,
            Math.round(memUsed) + "MiB / " + Math.round(memTotal) + "MiB"
        );

        const visGpu = this._updateSection(
            this.show_gpu_util,
            this.gpu_display_mode,
            this._gpuLabel,
            this._gpuPieChartArea,
            "GPU: " + gpuUtil + "%"
        );

        const visFan = this._updateSection(
            this.show_fan_speed,
            this.fan_display_mode,
            this._fanLabel,
            this._fanPieChartArea,
            "Fan: " + fanSpeed + "%"
        );

        // Separators
        // Sep 1: between Temp and (Mem OR Gpu OR Fan)
        let rightOfTemp = visMem || visGpu || visFan;
        if (visTemp && rightOfTemp) this._sep1.show(); else this._sep1.hide();

        // Sep 2: between Mem and (Gpu OR Fan)
        let rightOfMem = visGpu || visFan;
        if (visMem && rightOfMem) this._sep2.show(); else this._sep2.hide();

        // Sep 3: between Gpu and Fan
        if (visGpu && visFan) this._sep3.show(); else this._sep3.hide();

        // If nothing is shown, show placeholder in Temp label
        if (!visTemp && !visMem && !visGpu && !visFan) {
            this._label.set_text("Nvidia");
            this._label.show();
        }
    }

    _updateSection(show, mode, label, pieArea, textVal) {
        if (show) {
            if (mode === 'pie') {
                label.hide();
                pieArea.show();
                pieArea.queue_repaint();
            } else {
                label.set_text(textVal);
                label.show();
                pieArea.hide();
            }
            return true;
        } else {
            label.hide();
            pieArea.hide();
            return false;
        }
    }

    on_applet_removed_from_panel() {
        if (this._updateLoopId) {
            GLib.Source.remove(this._updateLoopId);
        }
        
        if (this._monitorProc) {
             try {
                this._monitorProc.force_exit();
             } catch(e) {}
             this._monitorProc = null;
        }

        if (this.menu) {
            this.menu.destroy();
        }

        this.settings.finalize();
    }

    on_applet_clicked(event) {
        this.menu.toggle();
        global.log("Nvidia Monitor: Menu toggled on click.");
    }
}

function main(metadata, orientation, panel_height, instance_id) {
    return new NvidiaMonitorApplet(metadata, orientation, panel_height, instance_id);
}
