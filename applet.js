const Applet = imports.ui.applet;
const Mainloop = imports.mainloop;
const Lang = imports.lang;
const Settings = imports.ui.settings;
const GLib = imports.gi.GLib;
const ByteArray = imports.byteArray;

function NvidiaMonitorApplet(metadata, orientation, panel_height, instance_id) {
    this._init(metadata, orientation, panel_height, instance_id);
}

NvidiaMonitorApplet.prototype = {
    __proto__: Applet.TextApplet.prototype,

    _init: function(metadata, orientation, panel_height, instance_id) {
        Applet.TextApplet.prototype._init.call(this, orientation, panel_height, instance_id);
        
        this.settings = new Settings.AppletSettings(this, metadata.uuid, instance_id);
        
        this.settings.bind("refresh-interval", "refresh_interval", this.on_settings_changed);
        this.settings.bind("show-temp", "show_temp", this.on_update_display);
        this.settings.bind("show-memory", "show_memory", this.on_update_display);
        this.settings.bind("show-gpu-util", "show_gpu_util", this.on_update_display);
        this.settings.bind("show-fan-speed", "show_fan_speed", this.on_update_display);

        this._updateLoopId = null;
        this.last_output = "";
        
        this.set_applet_label("Initializing...");
        this.set_applet_tooltip("NVIDIA Monitor");
        
        this.on_settings_changed();
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

    parse_and_display: function(output) {
        let parts = output.trim().split(',').map(function(s) { return s.trim(); });
        if (parts.length < 5) return;

        let temp = parts[0];
        let memUsed = parts[1];
        let memTotal = parts[2];
        let gpuUtil = parts[3];
        let fanSpeed = parts[4];

        let label_parts = [];

        if (this.show_temp) {
            label_parts.push(temp + "°C");
        }
        if (this.show_memory) {
            label_parts.push(memUsed + "MiB / " + memTotal + "MiB");
        }
        if (this.show_gpu_util) {
            label_parts.push("GPU: " + gpuUtil + "%");
        }
        if (this.show_fan_speed) {
            label_parts.push("Fan: " + fanSpeed + "%");
        }
        
        if (label_parts.length === 0) {
            this.set_applet_label("Nvidia");
        } else {
            this.set_applet_label(label_parts.join(" | "));
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
