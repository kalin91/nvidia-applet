const Applet = imports.ui.applet;
const Mainloop = imports.mainloop;
const Lang = imports.lang;
const Settings = imports.ui.settings;
const GLib = imports.gi.GLib;
const ByteArray = imports.byteArray;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;

function NvidiaMonitorApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

NvidiaMonitorApplet.prototype = {
    __proto__: Applet.Applet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.Applet.prototype._init.call(this, orientation, panel_height, instance_id);
        
        this._panel_height = panel_height;
        
        // Create main container
        this._box = new St.BoxLayout({ 
            style_class: 'applet-box',
            y_align: Clutter.ActorAlign.CENTER
        });
        this.actor.add(this._box);
        
        // Separator string
        let sepText = " | ";

        // 1. Temp Label (existing _label)
        this._label = new St.Label({ 
            text: "Initializing...",
            y_align: Clutter.ActorAlign.CENTER
        });
        this._box.add(this._label, { y_fill: false, y_align: St.Align.MIDDLE });

        // 2. Sep 1
        this._sep1 = new St.Label({ text: sepText, y_align: Clutter.ActorAlign.CENTER });
        this._box.add(this._sep1, { y_fill: false, y_align: St.Align.MIDDLE });
        this._sep1.hide();

        // 3. Mem Label
        this._memLabel = new St.Label({ text: "", y_align: Clutter.ActorAlign.CENTER });
        this._box.add(this._memLabel, { y_fill: false, y_align: St.Align.MIDDLE });
        this._memLabel.hide();

        // 4. Mem Pie Chart
        this._pieChartSize = Math.max(16, panel_height - 6);
        this._pieChartArea = new St.DrawingArea({
            width: this._pieChartSize,
            height: this._pieChartSize,
            style: 'margin-left: 2px; margin-right: 2px;'
        });
        this._pieChartArea.connect('repaint', Lang.bind(this, this._drawPieChart));
        this._box.add(this._pieChartArea, { y_fill: false, y_align: St.Align.MIDDLE });
        this._pieChartArea.hide();

        // 5. Sep 2
        this._sep2 = new St.Label({ text: sepText, y_align: Clutter.ActorAlign.CENTER });
        this._box.add(this._sep2, { y_fill: false, y_align: St.Align.MIDDLE });
        this._sep2.hide();

        // 6. GPU Label
        this._gpuLabel = new St.Label({ text: "", y_align: Clutter.ActorAlign.CENTER });
        this._box.add(this._gpuLabel, { y_fill: false, y_align: St.Align.MIDDLE });
        this._gpuLabel.hide();

        // 7. Sep 3
        this._sep3 = new St.Label({ text: sepText, y_align: Clutter.ActorAlign.CENTER });
        this._box.add(this._sep3, { y_fill: false, y_align: St.Align.MIDDLE });
        this._sep3.hide();

        // 8. Fan Label
        this._fanLabel = new St.Label({ text: "", y_align: Clutter.ActorAlign.CENTER });
        this._box.add(this._fanLabel, { y_fill: false, y_align: St.Align.MIDDLE });
        this._fanLabel.hide();
        
        this.settings = new Settings.AppletSettings(this, metadata.uuid, instance_id);
        
        this.settings.bind("refresh-interval", "refresh_interval", this.on_settings_changed);
        this.settings.bind("show-temp", "show_temp", this.on_update_display);
        this.settings.bind("show-memory", "show_memory", this.on_update_display);
        this.settings.bind("memory-display-mode", "memory_display_mode", this.on_update_display);
        this.settings.bind("show-gpu-util", "show_gpu_util", this.on_update_display);
        this.settings.bind("show-fan-speed", "show_fan_speed", this.on_update_display);

        this._updateLoopId = null;
        this.last_output = "";
        this._memUsedPercent = 0;
        
        this.set_applet_tooltip("NVIDIA Monitor");
        
        this.on_settings_changed();
    },
    
    set_applet_label: function(text) {
        this._label.set_text(text);
        this._label.show();
        // Ensure others are hidden in error/init state if needed, 
        // but simple set_text is safe fallback.
    },

    on_settings_changed: function() {
        if (this._updateLoopId) {
            Mainloop.source_remove(this._updateLoopId);
        }
        this._updateLoop();
    },
    
    on_update_display: function() {
        if (this.last_output) {
            this.parse_and_display(this.last_output);
        }
    },

    _updateLoop: function() {
        this.update();
        
        // refresh_interval is now in milliseconds directly
        let interval = this.refresh_interval;
        if (interval < 500) interval = 500;
        
        this._updateLoopId = Mainloop.timeout_add(interval, Lang.bind(this, function() {
            this._updateLoop();
            return false;
        }));
    },

    update: function() {
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
    },

    _drawPieChart: function(area) {
        let [width, height] = area.get_surface_size();
        let cr = area.get_context();
        
        let centerX = width / 2;
        let centerY = height / 2;
        let radius = Math.min(width, height) / 2 - 1;
        
        // Background circle (total memory - gray)
        cr.setSourceRGBA(0.4, 0.4, 0.4, 1.0);
        cr.arc(centerX, centerY, radius, 0, 2 * Math.PI);
        cr.fill();
        
        // Used memory portion (green to red gradient based on usage)
        let usedPercent = this._memUsedPercent;
        if (usedPercent > 0) {
            // Color goes from green (low usage) to yellow to red (high usage)
            let r, g, b;
            if (usedPercent < 0.5) {
                r = usedPercent * 2;
                g = 0.8;
                b = 0.2;
            } else {
                r = 1.0;
                g = 0.8 * (1 - (usedPercent - 0.5) * 2);
                b = 0.2;
            }
            cr.setSourceRGBA(r, g, b, 1.0);
            
            // Draw pie slice starting from top (-PI/2)
            cr.moveTo(centerX, centerY);
            cr.arc(centerX, centerY, radius, -Math.PI / 2, -Math.PI / 2 + usedPercent * 2 * Math.PI);
            cr.closePath();
            cr.fill();
        }
        
        // Draw border
        cr.setSourceRGBA(0.7, 0.7, 0.7, 1.0);
        cr.setLineWidth(1);
        cr.arc(centerX, centerY, radius, 0, 2 * Math.PI);
        cr.stroke();
        
        cr.$dispose();
    },

    parse_and_display: function(output) {
        let parts = output.trim().split(',').map(function(s) { return s.trim(); });
        if (parts.length < 5) return;

        let temp = parts[0];
        let memUsed = parseFloat(parts[1]);
        let memTotal = parseFloat(parts[2]);
        let gpuUtil = parts[3];
        let fanSpeed = parts[4];
        
        // Calculate memory percentage for pie chart
        this._memUsedPercent = memTotal > 0 ? memUsed / memTotal : 0;

        let showTemp = this.show_temp;
        let showMem = this.show_memory;
        let memMode = this.memory_display_mode;
        let showGpu = this.show_gpu_util;
        let showFan = this.show_fan_speed;

        let visTemp = false;
        let visMem = false;
        let visGpu = false;
        let visFan = false;

        // Temp
        if (showTemp) {
            this._label.set_text(temp + "°C");
            this._label.show();
            visTemp = true;
        } else {
            this._label.hide();
        }

        // Memory
        if (showMem) {
            visMem = true;
            if (memMode === 'pie') {
                this._memLabel.hide();
                this._pieChartArea.show();
                this._pieChartArea.queue_repaint();
            } else {
                this._memLabel.set_text(Math.round(memUsed) + "MiB / " + Math.round(memTotal) + "MiB");
                this._memLabel.show();
                this._pieChartArea.hide();
            }
        } else {
            this._memLabel.hide();
            this._pieChartArea.hide();
        }

        // GPU
        if (showGpu) {
            this._gpuLabel.set_text("GPU: " + gpuUtil + "%");
            this._gpuLabel.show();
            visGpu = true;
        } else {
            this._gpuLabel.hide();
        }

        // Fan
        if (showFan) {
            this._fanLabel.set_text("Fan: " + fanSpeed + "%");
            this._fanLabel.show();
            visFan = true;
        } else {
            this._fanLabel.hide();
        }

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
    },

    on_applet_removed_from_panel: function() {
        if (this._updateLoopId) {
            Mainloop.source_remove(this._updateLoopId);
        }
        this.settings.finalize();
    }
};

function main(metadata, orientation, panel_height, instance_id) {
    return new NvidiaMonitorApplet(metadata, orientation, panel_height, instance_id);
}
