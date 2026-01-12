# NVIDIA Monitor Applet for Cinnamon

A simple applet to monitor NVIDIA GPU statistics (Temperature, Memory, Utilization, Fan Speed).

## Installation

1.  Copy or symlink this folder to `~/.local/share/cinnamon/applets/`
2.  Enable the applet from "System Settings" -> "Applets".

## Requirements

-   NVIDIA Drivers installed
-   `nvidia-smi` command available in path

## Configuration

Right-click the applet to configure:
-   Refresh Interval (seconds)
-   Toggle visibility of:
    -   Temperature
    -   Memory Usage
    -   GPU Utilization
    -   Fan Speed
