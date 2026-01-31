const Applet = imports.ui.applet;
const Mainloop = imports.mainloop;
const Lang = imports.lang;
const Settings = imports.ui.settings;
const GLib = imports.gi.GLib;
const ByteArray = imports.byteArray;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const Pango = imports.gi.Pango;
const PangoCairo = imports.gi.PangoCairo;

class NvidiaMonitorApplet extends Applet.Applet {

    constructor(metadata, orientation, panel_height, instance_id) {
        super(orientation, panel_height, instance_id);

        this._panel_height = panel_height;

        this._updateLoopId = null;
        this.last_output = "";
        this._memUsedPercent = 0;
        this._gpuUtilPercent = 0;
        this._fanSpeedPercent = 0;

        this._buildUI(panel_height);
        this._initSettings(metadata, instance_id);

        this.set_applet_tooltip("NVIDIA Monitor");

        this.on_settings_changed();
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

        this.settings = new Settings.AppletSettings(this, metadata.uuid, instance_id);

        this.settings.bind("refresh-interval", "refresh_interval", () => this.on_settings_changed());
        this.settings.bind("show-temp", "show_temp", () => this.on_update_display());
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
            Mainloop.source_remove(this._updateLoopId);
        }
        this._updateLoop();
    }

    on_update_display() {
        if (this.last_output) {
            this.parse_and_display(this.last_output);
        }
    }

    _updateLoop() {
        this.update();

        let interval = Math.max(this.refresh_interval, 500);

        this._updateLoopId = Mainloop.timeout_add(interval, () => {
            this._updateLoop();
            return false;
        });
    }

    update() {
        try {
            // Use full path to nvidia-smi
            let [success, stdout, stderr, exit_status] = GLib.spawn_command_line_sync('/usr/bin/nvidia-smi --query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu,fan.speed --format=csv,noheader,nounits');

            if (success) {
                let output = "";
                if (stdout instanceof Uint8Array) {
                    output = ByteArray.toString(stdout);
                } else {
                    output = stdout.toString();
                }
                this.last_output = output;
                this.parse_and_display(output);
            } else {
                this.set_applet_label("Error");
                global.logError("Nvidia Monitor: Failed to run nvidia-smi. Stderr: " + (stderr ? stderr.toString() : "Unknown"));
            }
        } catch (e) {
            global.logError(e);
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
        if (parts.length < 5) return;

        let temp = parts[0];
        let memUsed = parseFloat(parts[1]);
        let memTotal = parseFloat(parts[2]);
        let gpuUtil = parseFloat(parts[3]);
        let fanSpeed = parseFloat(parts[4]);

        // Calculate percentages
        this._memUsedPercent = memTotal > 0 ? memUsed / memTotal : 0;
        this._gpuUtilPercent = gpuUtil / 100.0;
        this._fanSpeedPercent = fanSpeed / 100.0;

        let visTemp = false;

        // Temp logic
        if (this.show_temp) {
            this._label.set_text(temp + "°C");
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
            Mainloop.source_remove(this._updateLoopId);
        }
        this.settings.finalize();
    }
}

function main(metadata, orientation, panel_height, instance_id) {
    return new NvidiaMonitorApplet(metadata, orientation, panel_height, instance_id);
}
