#!/bin/bash
# limit-cpu-genmon.sh — salida para xfce4-genmon-plugin (barra del sistema)
EPP=$(cat /sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference 2>/dev/null)
case "$EPP" in
    balance_performance) NAME="máximo";;
    balance_power)       NAME="medio";;
    power)               NAME="mínimo";;
    *)                   NAME="$EPP";;
esac
echo "<txt>CPU: $NAME</txt>"
echo "<tool>Perfil de energía: $NAME — clic para alternar (máximo/medio/mínimo)</tool>"
echo "<txtclick>/usr/bin/sudo /home/jorsh/.local/bin/limit-cpu.sh cycle</txtclick>"
