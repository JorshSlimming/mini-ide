#!/bin/bash
# limit-cpu.sh — CPU power profiles (AMD p-state)
# Usage: sudo limit-cpu.sh [mild|fresh|full|cycle|status]
#   mild   (default): boost OFF, balance_power, max 3.5 GHz  <- recommended
#   fresh           : boost OFF, power,          max 3.0 GHz  <- maximum savings
#   full            : boost ON,  balance_performance, 4.63 GHz
#   cycle           : cycles full -> mild -> fresh -> full
#   status          : shows the current profile
CPS="/sys/devices/system/cpu/cpufreq"
MODE="${1:-mild}"

set_cpu() {  # $1=boost(0/1) $2=epp $3=max_khz
    echo "$1" > "$CPS/boost" 2>/dev/null
    for p in "$CPS"/policy*; do
        echo "$2" > "$p/energy_performance_preference" 2>/dev/null
        echo "$3" > "$p/scaling_max_freq" 2>/dev/null
    done
}

current() {
    EPP=$(cat "$CPS/policy0/energy_performance_preference" 2>/dev/null)
    BOOST=$(cat "$CPS/boost" 2>/dev/null)
    MAX=$(cat "$CPS/policy0/scaling_max_freq" 2>/dev/null)
}

case "$MODE" in
    mild)
        set_cpu 0 balance_power 3500000
        echo "PROFILE: medium (boost OFF, balance_power, 3.5 GHz)"
        ;;
    fresh)
        set_cpu 0 power 3000000
        echo "PROFILE: minimum (boost OFF, power, 3.0 GHz)"
        ;;
    full)
        set_cpu 1 balance_performance 4629000
        echo "PROFILE: maximum (boost ON, balance_performance, 4.63 GHz)"
        ;;
    cycle)
        current
        if [ "$EPP" = "balance_performance" ]; then
            set_cpu 0 balance_power 3500000
            echo "PROFILE: medium (boost OFF, balance_power, 3.5 GHz)"
        elif [ "$EPP" = "balance_power" ]; then
            set_cpu 0 power 3000000
            echo "PROFILE: minimum (boost OFF, power, 3.0 GHz)"
        else
            set_cpu 1 balance_performance 4629000
            echo "PROFILE: maximum (boost ON, balance_performance, 4.63 GHz)"
        fi
        ;;
    status)
        current
        echo "epp=$EPP boost=$BOOST max=$((MAX/1000)) MHz"
        ;;
    *)
        echo "Usage: $0 [mild|fresh|full|cycle|status]"
        ;;
esac
