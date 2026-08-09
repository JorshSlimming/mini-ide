#!/bin/bash
# limit-cpu-genmon.sh — output for xfce4-genmon-plugin (system panel)
EPP=$(cat /sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference 2>/dev/null)
case "$EPP" in
    balance_performance) NAME="max";;
    balance_power)       NAME="medium";;
    power)               NAME="min";;
    *)                   NAME="$EPP";;
esac
echo "<txt>CPU: $NAME</txt>"
echo "<tool>CPU power profile: $NAME — click to cycle (max/medium/min)</tool>"
echo "<txtclick>/usr/bin/sudo /home/jorsh/.local/bin/limit-cpu.sh cycle</txtclick>"
