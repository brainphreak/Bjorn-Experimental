#!/bin/bash
# Title: Bjorn
# Description: Autonomous network reconnaissance companion (Tamagotchi-style)
# Author: infinition (ported by brAinphreAk)
# Version: 1.0
# Category: Reconnaissance

PAYLOAD_DIR="/root/payloads/user/reconnaissance/pager_bjorn"

#
# Setup paths for Python and shared library
#
export PYTHONPATH="$PAYLOAD_DIR:$PYTHONPATH"
export LD_LIBRARY_PATH="$PAYLOAD_DIR:$LD_LIBRARY_PATH"

#
# Check for Python3 + required modules
#
check_python() {
    NEED_PYTHON=false
    NEED_CTYPES=false

    if ! command -v python3 >/dev/null 2>&1; then
        NEED_PYTHON=true
        NEED_CTYPES=true
    elif ! python3 -c "import ctypes" 2>/dev/null; then
        NEED_CTYPES=true
    fi

    if [ "$NEED_PYTHON" = true ] || [ "$NEED_CTYPES" = true ]; then
        LOG ""
        LOG "red" "=== PYTHON3 REQUIRED ==="
        LOG ""
        if [ "$NEED_PYTHON" = true ]; then
            LOG "Python3 is not installed."
        else
            LOG "Python3-ctypes is not installed."
        fi
        LOG ""
        LOG "Bjorn requires Python3 + ctypes for pagerctl."
        LOG ""
        LOG "green" "GREEN = Install Python3 (requires internet)"
        LOG "red" "RED   = Exit"
        LOG ""

        while true; do
            BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
            case "$BUTTON" in
                "GREEN"|"A")
                    LOG ""
                    LOG "Updating package lists..."
                    opkg update 2>&1 | while IFS= read -r line; do LOG "  $line"; done
                    LOG ""
                    LOG "Installing Python3 + ctypes..."
                    opkg install python3 python3-ctypes 2>&1 | while IFS= read -r line; do LOG "  $line"; done
                    LOG ""
                    if command -v python3 >/dev/null 2>&1 && python3 -c "import ctypes" 2>/dev/null; then
                        LOG "green" "Python3 installed successfully!"
                        sleep 1
                        return 0
                    else
                        LOG "red" "Failed to install Python3"
                        LOG "Check internet connection."
                        sleep 2
                        return 1
                    fi
                    ;;
                "RED"|"B")
                    LOG "Exiting."
                    exit 0
                    ;;
            esac
        done
    fi
    return 0
}

#
# Check network connectivity and select interface
#
SELECTED_INTERFACE=""
SELECTED_IP=""

check_network() {
    LOG ""
    LOG "Checking network connectivity..."

    # Get interfaces with IP addresses (exclude loopback)
    INTERFACES=()
    IPS=()

    while IFS= read -r line; do
        if [[ "$line" =~ ^[0-9]+:\ ([^:]+): ]]; then
            CURRENT_IFACE="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ inet\ ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+) ]]; then
            IP="${BASH_REMATCH[1]}"
            if [[ "$IP" != "127.0.0.1" && -n "$CURRENT_IFACE" ]]; then
                INTERFACES+=("$CURRENT_IFACE")
                IPS+=("$IP")
            fi
        fi
    done < <(ip addr 2>/dev/null)

    NUM_IFACES=${#INTERFACES[@]}

    if [ "$NUM_IFACES" -eq 0 ]; then
        LOG ""
        LOG "red" "=== NO NETWORK CONNECTED ==="
        LOG ""
        LOG "Bjorn requires a network connection to scan."
        LOG "Please connect to a network first:"
        LOG "  - WiFi client mode (wlan0cli)"
        LOG "  - Ethernet/USB (br-lan)"
        LOG ""
        LOG "Press any button to exit..."
        WAIT_FOR_INPUT >/dev/null 2>&1
        exit 1
    elif [ "$NUM_IFACES" -eq 1 ]; then
        SELECTED_INTERFACE="${INTERFACES[0]}"
        SELECTED_IP="${IPS[0]}"
        LOG "green" "Network found: $SELECTED_INTERFACE ($SELECTED_IP)"
    else
        LOG ""
        LOG "Multiple networks detected:"
        LOG ""
        for i in "${!INTERFACES[@]}"; do
            NUM=$((i + 1))
            LOG "  $NUM) ${INTERFACES[$i]} - ${IPS[$i]}"
        done
        LOG ""
        LOG "Use UP/DOWN to select, GREEN to confirm"
        LOG ""

        SELECTION=0
        while true; do
            # Highlight current selection
            for i in "${!INTERFACES[@]}"; do
                if [ "$i" -eq "$SELECTION" ]; then
                    LOG "green" "> ${INTERFACES[$i]} - ${IPS[$i]}"
                else
                    LOG "  ${INTERFACES[$i]} - ${IPS[$i]}"
                fi
            done

            BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
            case "$BUTTON" in
                "UP")
                    SELECTION=$((SELECTION - 1))
                    if [ "$SELECTION" -lt 0 ]; then
                        SELECTION=$((NUM_IFACES - 1))
                    fi
                    ;;
                "DOWN")
                    SELECTION=$((SELECTION + 1))
                    if [ "$SELECTION" -ge "$NUM_IFACES" ]; then
                        SELECTION=0
                    fi
                    ;;
                "GREEN"|"A")
                    SELECTED_INTERFACE="${INTERFACES[$SELECTION]}"
                    SELECTED_IP="${IPS[$SELECTION]}"
                    LOG ""
                    LOG "green" "Selected: $SELECTED_INTERFACE ($SELECTED_IP)"
                    break
                    ;;
                "RED"|"B")
                    LOG "Exiting."
                    exit 0
                    ;;
            esac
        done
    fi
}

#
# Check and install Bjorn dependencies automatically
#
check_dependencies() {
    LOG ""
    LOG "Checking dependencies..."

    MISSING=""

    # Check for nmap
    if ! command -v nmap >/dev/null 2>&1; then
        MISSING="$MISSING nmap"
    fi

    # Check for python-nmap
    if ! python3 -c "import nmap" 2>/dev/null; then
        MISSING="$MISSING python-nmap"
    fi

    # Check for paramiko (for SSH)
    if ! python3 -c "import paramiko" 2>/dev/null; then
        MISSING="$MISSING paramiko"
    fi

    if [ -n "$MISSING" ]; then
        LOG ""
        LOG "red" "Missing dependencies:$MISSING"
        LOG ""
        LOG "Installing dependencies automatically..."
        LOG ""
        opkg update 2>&1 | while IFS= read -r line; do LOG "  $line"; done
        opkg install nmap python3-pip 2>&1 | while IFS= read -r line; do LOG "  $line"; done
        LOG ""
        LOG "Installing Python packages via pip..."
        pip3 install python-nmap paramiko pysmb pymysql 2>&1 | while IFS= read -r line; do LOG "  $line"; done
        LOG ""
        LOG "green" "Dependencies installed!"
        sleep 1
    else
        LOG "green" "All dependencies found!"
    fi
}

# ============================================================
# CLEANUP
# ============================================================

cleanup() {
    # Restart pager service if not running
    if ! pgrep -x pineapple >/dev/null; then
        /etc/init.d/pineapplepager start 2>/dev/null
    fi
}

# Ensure pager service restarts on exit
trap cleanup EXIT

# ============================================================
# MAIN
# ============================================================

# Check Python first (required)
check_python || exit 1

# Check if libpagerctl.so exists
if [ ! -f "$PAYLOAD_DIR/libpagerctl.so" ]; then
    LOG ""
    LOG "red" "ERROR: libpagerctl.so not found!"
    LOG ""
    LOG "Build and deploy from your computer:"
    LOG "  cd pagerctl && make remote-build"
    LOG "  Then copy libpagerctl.so to pager_bjorn/"
    LOG ""
    LOG "Press any button to exit..."
    WAIT_FOR_INPUT >/dev/null 2>&1
    exit 1
fi

# Check dependencies automatically
check_dependencies

# Check network connectivity
check_network

# Show menu
LOG ""
LOG "green" "=========================================="
LOG "green" "              BJORN"
LOG "green" "   Autonomous Network Reconnaissance"
LOG "green" "=========================================="
LOG ""
LOG "Tamagotchi-style hacking companion."
LOG "Scans networks, finds vulnerabilities,"
LOG "and collects credentials automatically."
LOG ""
LOG "Network: $SELECTED_INTERFACE ($SELECTED_IP)"
LOG ""
LOG "green" "  GREEN = Start Bjorn"
LOG "red" "  RED   = Exit"
LOG ""

# Wait for selection
BUTTON=$(WAIT_FOR_INPUT 2>/dev/null)
case "$BUTTON" in
    "GREEN"|"A")
        LOG ""
        LOG "Starting Bjorn..."
        /etc/init.d/pineapplepager stop 2>/dev/null
        sleep 0.3
        cd "$PAYLOAD_DIR"
        export BJORN_INTERFACE="$SELECTED_INTERFACE"
        export BJORN_IP="$SELECTED_IP"
        python3 Bjorn.py
        /etc/init.d/pineapplepager start 2>/dev/null
        ;;
    "RED"|"B"|*)
        LOG ""
        LOG "Exiting."
        ;;
esac

exit 0
