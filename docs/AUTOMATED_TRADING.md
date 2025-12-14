# Automated 24/7 Trading & Profit-Taking Guide

This guide explains how to run your Kalshi trading bot automatically 24/7, even when you're asleep, and how to configure automatic profit-taking.

## Quick Start

### Option 1: Shell Script (Recommended for Testing)

```bash
# Start the daemon in paper trading mode
./scripts/run_daemon.sh start

# Check status
./scripts/run_daemon.sh status

# View live logs
./scripts/run_daemon.sh logs

# Stop the daemon
./scripts/run_daemon.sh stop
```

### Option 2: Direct Python

```bash
# Start daemon
python -m kalshi_arb.daemon start

# With custom profit settings
python -m kalshi_arb.daemon start --take-profit 0.20 --stop-loss 0.08

# Live trading (CAUTION: real money!)
python -m kalshi_arb.daemon start --live
```

---

## 24/7 Automated Trading

### macOS: LaunchAgent (Survives Reboots)

1. **Copy the plist file:**
```bash
cp scripts/com.kalshi.tradingbot.plist ~/Library/LaunchAgents/
```

2. **Edit the plist to set your paths:**
```bash
nano ~/Library/LaunchAgents/com.kalshi.tradingbot.plist
```

Update:
- `ProgramArguments` → your Python path
- `WorkingDirectory` → your project path
- `PYTHONPATH` → your src directory

3. **Load the service:**
```bash
launchctl load ~/Library/LaunchAgents/com.kalshi.tradingbot.plist
```

4. **Check status:**
```bash
launchctl list | grep kalshi
```

5. **View logs:**
```bash
tail -f /tmp/kalshi_bot.out.log
tail -f /tmp/kalshi_bot.err.log
```

6. **Stop the service:**
```bash
launchctl unload ~/Library/LaunchAgents/com.kalshi.tradingbot.plist
```

### Linux: Systemd Service

Create `/etc/systemd/system/kalshi-bot.service`:

```ini
[Unit]
Description=Kalshi Trading Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/windsurf-project-2
Environment=PYTHONPATH=/path/to/windsurf-project-2/src
ExecStart=/usr/bin/python3 -m kalshi_arb.daemon start
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable kalshi-bot
sudo systemctl start kalshi-bot
sudo systemctl status kalshi-bot
```

---

## Profit-Taking Configuration

### Default Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `take_profit_pct` | 15% | Close position when profit reaches this level |
| `stop_loss_pct` | 10% | Close position when loss reaches this level |
| `trailing_stop_pct` | 5% | After hitting take-profit, trail by this amount |
| `use_trailing_stop` | True | Enable trailing stop after initial profit target |
| `min_hold_seconds` | 60 | Minimum time before profit-taking kicks in |

### How Profit-Taking Works

1. **Entry**: Bot opens a position based on signal
2. **Monitoring**: Position is tracked every scan cycle
3. **Stop-Loss**: If loss exceeds `stop_loss_pct`, position closes immediately
4. **Take-Profit**: When profit hits `take_profit_pct`:
   - If `use_trailing_stop=True`: Trailing stop activates
   - If `use_trailing_stop=False`: Position closes immediately
5. **Trailing Stop**: After activation, if price drops `trailing_stop_pct` from peak, position closes

### Tiered Profit-Taking (Advanced)

The system supports closing portions of positions at different profit levels:

```python
tiered_targets = [
    (0.10, 0.25),  # At 10% profit, close 25% of position
    (0.20, 0.50),  # At 20% profit, close 50% of remaining
    (0.30, 0.75),  # At 30% profit, close 75% of remaining
]
```

### Environment Variables

Add to your `.env` file:

```bash
# Profit-taking
KALSHI_TAKE_PROFIT_PCT=0.15
KALSHI_STOP_LOSS_PCT=0.10
KALSHI_TRAILING_STOP_PCT=0.05
KALSHI_USE_TRAILING_STOP=true
KALSHI_MIN_HOLD_SECONDS=60

# Daemon
KALSHI_DAEMON_MAX_RESTARTS=10
KALSHI_DAEMON_RESTART_DELAY=30.0
```

---

## Monitoring

### Log Files

- **Main log**: `~/.kalshi_bot.log`
- **macOS LaunchAgent**: `/tmp/kalshi_bot.out.log`, `/tmp/kalshi_bot.err.log`

### Check Bot Status

```bash
# Using shell script
./scripts/run_daemon.sh status

# Using Python
python -m kalshi_arb.daemon status
```

### PID File

The daemon writes its PID to `~/.kalshi_bot.pid` for process management.

---

## Safety Features

1. **Paper Trading Default**: Bot starts in paper mode by default
2. **Max Restarts**: Daemon stops after 10 consecutive failures
3. **Restart Delay**: 30-second delay between restart attempts
4. **Graceful Shutdown**: SIGTERM/SIGINT handled properly
5. **Drawdown Protection**: Existing risk manager pauses trading on excessive drawdown

---

## Example: Full Production Setup

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 2. Test in paper mode first
./scripts/run_daemon.sh start
./scripts/run_daemon.sh logs
# Let it run for a few hours, check behavior

# 3. When ready for live trading
./scripts/run_daemon.sh stop
./scripts/run_daemon.sh start --live --take-profit 0.12 --stop-loss 0.08

# 4. For 24/7 operation, install LaunchAgent
cp scripts/com.kalshi.tradingbot.plist ~/Library/LaunchAgents/
# Edit paths in plist, change --paper to --live
launchctl load ~/Library/LaunchAgents/com.kalshi.tradingbot.plist
```

---

## Troubleshooting

### Bot won't start
```bash
# Check if already running
./scripts/run_daemon.sh status

# Check logs
tail -50 ~/.kalshi_bot.log
```

### API authentication fails
- Verify `KALSHI_API_KEY` and `KALSHI_API_SECRET` in `.env`
- Check if using correct base URL (demo vs production)

### Positions not closing
- Check `min_hold_seconds` setting
- Verify current prices are being fetched
- Check logs for profit-taker actions

### LaunchAgent not starting
```bash
# Check for errors
launchctl list | grep kalshi
cat /tmp/kalshi_bot.err.log

# Verify paths in plist are correct
plutil -lint ~/Library/LaunchAgents/com.kalshi.tradingbot.plist
```
