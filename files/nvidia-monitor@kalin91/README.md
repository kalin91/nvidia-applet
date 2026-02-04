# NVIDIA Monitor Applet for Cinnamon

A simple applet to monitor NVIDIA GPU statistics (Temperature, Memory, Utilization, Fan Speed).

## Installation

1. Copy or symlink this folder to `~/.local/share/cinnamon/applets/` ensuring the folder name matches the UUID `nvidia-monitor@kalin`.

    ```bash
    ln -s /path/to/nvidia-applet ~/.local/share/cinnamon/applets/nvidia-monitor@kalin
    ```

2. Enable the applet from "System Settings" -> "Applets".

## Requirements

- NVIDIA Drivers installed
- `nvidia-smi` command available in path

## Configuration

Right-click the applet to configure:

- Refresh Interval (seconds)
- Toggle visibility of:
  - Temperature
  - Memory Usage
  - GPU Utilization
  - Fan Speed
