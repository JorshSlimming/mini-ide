#!/bin/bash
# limit-cpu.sh — CPU power profiles (AMD p-state)
# Usage: sudo limit-cpu.sh [mild|fresh|full|cycle|status]
#   mild   (default): boost OFF, balance_power, 75% of max freq  <- recommended
#   fresh           : boost OFF, power,          65% of max freq  <- maximum savings
#   full            : boost ON,  balance_performance, max freq
#   cycle           : cycles full -> mild -> fresh -> full
#   status          : shows the current profile
CPS="/sys/devices/system/cpu/cpufreq"
MODE="${1:-mild}"
POLICY0="$CPS/policy0"

if [ ! -d "$CPS" ] || [ ! -e "$CPS/boost" ] || [ ! -e "$POLICY0/scaling_max_freq" ]; then
    echo "ERROR: cpufreq sysfs not available ($CPS). Unsupported machine." >&2
    exit 1
fi

HW_MAX=$(cat "$POLICY0/cpuinfo_max_freq" 2>/dev/null)
case "$HW_MAX" in
    ''|*[!0-9]*)
        echo "ERROR: cannot read cpuinfo_max_freq." >&2
        exit 1
        ;;
esac
[ "$HW_MAX" -gt 0 ] || { echo "ERROR: invalid cpuinfo_max_freq ($HW_MAX)." >&2; exit 1; }

pct_max() { awk -v h="$HW_MAX" -v p="$1" 'BEGIN { printf "%d", h * p }'; }

MILD_MAX=$(pct_max 0.75)
FRESH_MAX=$(pct_max 0.65)
FULL_MAX="$HW_MAX"

fail() { echo "ERROR: could not apply profile '$MODE' (run as root? unsupported driver?)." >&2; exit 1; }

apply() {  # $1=boost $2=epp $3=max_khz $4=label
    echo "$1" > "$CPS/boost" || fail
    for p in "$CPS"/policy*; do
        if [ -w "$p/energy_performance_preference" ]; then
            echo "$2" > "$p/energy_performance_preference" 2>/dev/null || fail
        fi
        if [ -w "$p/scaling_max_freq" ]; then
            echo "$3" > "$p/scaling_max_freq" 2>/dev/null || fail
        fi
    done
    got=$(cat "$POLICY0/scaling_max_freq" 2>/dev/null)
    case "$got" in
        ''|*[!0-9]*) fail ;;
    esac
    ok=$(awk -v g="$got" -v w="$3" 'BEGIN { d = g - w; if (d < 0) d = -d; print (d <= 100000) ? 1 : 0 }')
    [ "$ok" = "1" ] || fail
    echo "PROFILE: $4"
}

current() {
    EPP=$(cat "$POLICY0/energy_performance_preference" 2>/dev/null)
    BOOST=$(cat "$CPS/boost" 2>/dev/null)
    MAX=$(cat "$POLICY0/scaling_max_freq" 2>/dev/null)
}

case "$MODE" in
    mild)
        apply 0 balance_power "$MILD_MAX" "medium (boost OFF, balance_power, $((MILD_MAX/1000)) MHz)"
        ;;
    fresh)
        apply 0 power "$FRESH_MAX" "minimum (boost OFF, power, $((FRESH_MAX/1000)) MHz)"
        ;;
    full)
        apply 1 balance_performance "$FULL_MAX" "maximum (boost ON, balance_performance, $((FULL_MAX/1000)) MHz)"
        ;;
    cycle)
        current
        if [ "$EPP" = "balance_performance" ]; then
            apply 0 balance_power "$MILD_MAX" "medium (boost OFF, balance_power, $((MILD_MAX/1000)) MHz)"
        elif [ "$EPP" = "balance_power" ]; then
            apply 0 power "$FRESH_MAX" "minimum (boost OFF, power, $((FRESH_MAX/1000)) MHz)"
        else
            apply 1 balance_performance "$FULL_MAX" "maximum (boost ON, balance_performance, $((FULL_MAX/1000)) MHz)"
        fi
        ;;
    status)
        current
        echo "epp=$EPP boost=$BOOST max=$((MAX/1000)) MHz"
        ;;
    *)
        echo "Usage: $0 [mild|fresh|full|cycle|status]" >&2
        exit 2
        ;;
esac
