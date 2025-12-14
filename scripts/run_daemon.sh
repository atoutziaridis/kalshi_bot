#!/bin/bash
# Kalshi Trading Bot Daemon Runner
# This script runs the trading bot as a background process

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/venv"
LOG_FILE="$HOME/.kalshi_bot.log"
PID_FILE="$HOME/.kalshi_bot.pid"

# Activate virtual environment if it exists
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi

cd "$PROJECT_DIR"

case "$1" in
    start)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Daemon already running (PID $(cat "$PID_FILE"))"
            exit 1
        fi
        
        echo "Starting Kalshi Trading Daemon..."
        nohup python -m kalshi_arb.daemon start "$@" >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "Daemon started (PID $!)"
        echo "Log file: $LOG_FILE"
        ;;
    
    stop)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "Stopping daemon (PID $PID)..."
                kill -TERM "$PID"
                rm -f "$PID_FILE"
                echo "Daemon stopped"
            else
                echo "Daemon not running (stale PID file)"
                rm -f "$PID_FILE"
            fi
        else
            echo "Daemon not running"
        fi
        ;;
    
    restart)
        $0 stop
        sleep 2
        $0 start "${@:2}"
        ;;
    
    status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Daemon is running (PID $(cat "$PID_FILE"))"
            echo "Log file: $LOG_FILE"
            echo ""
            echo "Last 10 log lines:"
            tail -10 "$LOG_FILE" 2>/dev/null || echo "(no logs yet)"
        else
            echo "Daemon is not running"
        fi
        ;;
    
    logs)
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "No log file found"
        fi
        ;;
    
    *)
        echo "Usage: $0 {start|stop|restart|status|logs} [options]"
        echo ""
        echo "Options for start:"
        echo "  --live           Enable live trading (default: paper)"
        echo "  --take-profit N  Take profit percentage (default: 0.15)"
        echo "  --stop-loss N    Stop loss percentage (default: 0.10)"
        echo "  --trailing-stop N  Trailing stop percentage (default: 0.05)"
        exit 1
        ;;
esac
