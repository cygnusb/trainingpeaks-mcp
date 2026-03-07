# TrainingPeaks MCP Server

Connect TrainingPeaks to Claude and other AI assistants via the Model Context Protocol (MCP). Query your workouts, analyze training load, compare power data, and track fitness trends through natural conversation.

**No API approval required.** The official Training Peaks API is approval-gated, but this server uses secure cookie authentication that any user can set up in minutes. Your cookie is stored in your system keyring, never transmitted anywhere except to TrainingPeaks.

## What You Can Do

Use your AI assistant for:
- **Workout lookup and drill-down:** list planned/completed sessions, inspect single workouts, and review session PRs.
- **Workout analysis:** analyze one workout with totals, power/HR/cadence zones, laps, and full time-series export.
- **Fitness and form trends:** track CTL/ATL/TSB over custom ranges to assess load, fatigue, and readiness.
- **Health metric checks:** pull daily sleep/recovery/body metrics and trend them with rolling means and normal ranges.
- **Cross-check training vs metrics:** correlate hard weeks/sessions with sleep, HRV, and form to spot useful patterns.
- **Planning and editing:** create, move/update, and delete planned workouts directly from chat.
- **Structured workout editing:** create, read und update structured interval sets (including targets and rests) in TrainingPeaks.

Example prompts:
- "Check my current body state, sleep and training load. I am feeling a bit tired today. How should I proceed with the planned workout tomorrow?"
- "Analyze workout of today and summarize interval quality vs target."
- "Compare my FTP progression this year vs last year and show CTL trend around the best block."
- "Show the last 30 days of sleep and HRV and compare with my form (TSB)."
- "Insert 20s set rests between the main swim blocks on the workout today."
- "Update tomorrow's run to structured 6x3min threshold with 2min recoveries."

## Features

| Tool | Description |
|------|-------------|
| `tp_get_workouts` | Query workouts by date range (planned and completed) |
| `tp_get_workout` | Get detailed metrics for a single workout |
| `tp_analyze_workout` | Get full workout analysis: power/HR zones, lap data, time-series |
| `tp_get_peaks` | Compare power PRs (5sec to 90min) and running PRs (400m to marathon) |
| `tp_get_fitness` | Track CTL, ATL, and TSB (fitness, fatigue, form) |
| `tp_get_workout_prs` | See personal records set in a specific session |
| `tp_get_profile` | Get athlete profile details (ID, name, account type) |
| `tp_create_workout` | Create new planned workouts on your calendar |
| `tp_update_workout` | Modify existing planned workouts |
| `tp_delete_workout` | Remove workouts from your calendar |
| `tp_refresh_auth` | Re-authenticate if your session expires (extracts fresh cookie from browser) |

---

## Setup Options

### Option A: Auto-Setup with Claude Code

If you have [Claude Code](https://claude.ai/code), paste this prompt:

```
Set up the TrainingPeaks MCP server from https://github.com/cygnusb/trainingpeaks-mcp - clone it, create a venv, install it, then walk me through getting my TrainingPeaks cookie from my browser and run tp-mcp auth. Finally, add it to my Claude Desktop config.
```

Claude will handle the installation and guide you through authentication step-by-step.

### Option B: Manual Setup

#### Step 1: Install

```bash
git clone https://github.com/cygnusb/trainingpeaks-mcp.git
cd trainingpeaks-mcp
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

#### Step 2: Authenticate

**Option A: Auto-extract from browser (easiest)**

If you're logged into TrainingPeaks in your browser:

```bash
pip install tp-mcp[browser]  # One-time: install browser support
tp-mcp auth --from-browser chrome  # Or: firefox, safari, edge, auto
```

> **macOS note:** You may see security prompts for Keychain or Full Disk Access. This is normal - browser cookies are encrypted and require permission to read.

**Option B: Manual cookie entry**

1. Log into [app.trainingpeaks.com](https://app.trainingpeaks.com)
2. Open DevTools (`F12`) → **Application** tab → **Cookies**
3. Find `Production_tpAuth` and copy its value
4. Run `tp-mcp auth` and paste when prompted

**Other auth commands:**
```bash
tp-mcp auth-status  # Check if authenticated
tp-mcp auth-clear   # Remove stored cookie
```

#### Step 4: Add to Claude Desktop

Run this to get your config snippet:

```bash
tp-mcp config
```

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows) and paste it inside `mcpServers`. Example with multiple servers:

```json
{
  "mcpServers": {
    "some-other-server": {
      "command": "npx",
      "args": ["some-other-mcp"]
    },
    "trainingpeaks": {
      "command": "/Users/you/trainingpeaks-mcp/.venv/bin/tp-mcp",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop. You're ready to go!

---

## Tool Reference

### tp_get_workouts
List workouts in a date range. Max 90 days per query.

```json
{ "start_date": "2026-01-01", "end_date": "2026-01-07", "type": "completed" }
```

### tp_get_workout
Get full details for one workout including power, HR, cadence, TSS.

```json
{ "workout_id": "123456789" }
```

### tp_get_peaks
Get ranked personal records. Bike: power metrics. Run: pace/speed metrics.

```json
{ "sport": "Bike", "pr_type": "power20min", "days": 365 }
```

**Bike types:** `power5sec`, `power1min`, `power5min`, `power10min`, `power20min`, `power60min`, `power90min`

**Run types:** `speed400Meter`, `speed1K`, `speed5K`, `speed10K`, `speedHalfMarathon`, `speedMarathon`

### tp_get_fitness
Get training load metrics over time.

```json
{ "days": 90 }
```

Returns daily CTL (chronic training load / fitness), ATL (acute training load / fatigue), and TSB (training stress balance / form).

### tp_get_metrics
Get daily health & sleep metrics synced from your wearable (e.g. Coros, Garmin).

```json
{ "days": 30 }
```

Returns per-day entries with all available metric types such as Sleep Hours, Time in Deep/REM/Light Sleep, HRV, Body Weight, etc.

### tp_get_metrics_insights
Get health metric trends with rolling mean and normal range.

```json
{ "days": 30 }
```

Returns a time-series per metric type (e.g. Sleep Hours) with rolling mean and normal range (`rangeLow`/`rangeHigh`) once enough data is available. Useful for spotting trends.

### tp_get_workout_prs
Get PRs set during a specific workout.

```json
{ "workout_id": "123456789" }
```

### tp_analyze_workout
Get detailed workout analysis from the Peaksware analysis engine: totals (TSS, NP, IF, …), per-channel stats (min/max/avg) and zone distributions for power, heart rate, cadence, etc., lap data, and a full time-series saved to a local JSON file.

```json
{ "workout_id": "123456789" }
```

Returns inline summary plus a `data_file` path to the complete time-series for further analysis.

### tp_get_profile
Get details about the authenticated athlete.

```json
{}
```

### tp_create_workout
Create a new planned workout on the athlete's calendar.

```json
{
  "date": "2026-03-10",
  "sport": "Bike",
  "title": "Easy Recovery Ride",
  "duration_planned": 3600,
  "description": "Keep it in Zone 1"
}
```

### tp_update_workout
Update an existing planned workout.

```json
{
  "workout_id": "123456789",
  "title": "Updated Ride Title",
  "tss_planned": 45
}
```

### tp_delete_workout
Delete a workout from the calendar.

```json
{ "workout_id": "123456789" }
```

## What is MCP?

[Model Context Protocol](https://modelcontextprotocol.io) is an open standard for connecting AI assistants to external data sources. MCP servers expose tools that AI models can call to fetch real-time data, enabling assistants like Claude to access your Training Peaks account through natural language.

## Security

**TL;DR: Your cookie is encrypted on disk, exchanged for short-lived OAuth tokens, never shown to Claude, and only ever sent to TrainingPeaks. This server supports read/write for workouts and has no network ports.**

This server is designed with defense-in-depth. Your TrainingPeaks session cookie is sensitive - it grants access to your training data - so we treat it accordingly.

### Cookie Storage

| Platform | Primary Storage | Fallback |
|----------|----------------|----------|
| macOS | System Keychain | Encrypted file |
| Windows | Windows Credential Manager | Encrypted file |
| Linux | Secret Service (GNOME/KDE) | Encrypted file |

Your cookie is **never** stored in plaintext. The encrypted file fallback uses Fernet symmetric encryption with a machine-specific key.

### Cookie Never Leaks to AI

The AI assistant (Claude) **never sees your cookie value**. Multiple layers ensure this:

1. **Return value sanitization**: Tool results are scrubbed for any keys containing `cookie`, `token`, `auth`, `credential`, `password`, or `secret` before being sent to Claude
2. **Masked repr()**: The `BrowserCookieResult` class overrides `__repr__` to show `cookie=<present>` instead of the actual value
3. **Sanitized exceptions**: Error messages use only exception type names, never full messages that could contain data
4. **No logging**: Cookie values are never written to any log

### Domain Hardcoding (Cannot Be Changed)

The browser cookie extraction **only** accesses `.trainingpeaks.com`:

```python
# From src/tp_mcp/auth/browser.py - HARDCODED, not a parameter
cj = func(domain_name=".trainingpeaks.com")
```

Claude cannot modify this via tool parameters. The only parameter is `browser` (chrome/firefox/etc), not the domain. To change the domain would require modifying the source code.

### Read/Write Access

This server provides access to TrainingPeaks:
- ✅ Query workouts, fitness metrics, personal records
- ✅ Create, modify, or delete planned workouts
- ❌ Cannot change account settings
- ❌ Cannot access billing or payment info

### No Network Exposure

The MCP server uses **stdio transport only** - it communicates with Claude Desktop via stdin/stdout, not over the network. There is no HTTP server, no open ports, no remote access.

### What This Server Cannot Do

| Action | Possible? |
|--------|-----------|
| Read your workouts | ✅ Yes |
| Read your fitness metrics | ✅ Yes |
| Create/Modify/Delete planned workouts | ✅ Yes |
| Access other websites | ❌ No (domain hardcoded) |
| Send your cookie/token anywhere except TrainingPeaks | ❌ No |
| Expose your cookie to Claude | ❌ No (sanitized) |
| Open network ports | ❌ No (stdio only) |

### Open Source

This server is fully open source. You can audit every line of code before running it. Key security files:
- [`src/tp_mcp/auth/browser.py`](src/tp_mcp/auth/browser.py) - Cookie extraction with hardcoded domain
- [`src/tp_mcp/tools/refresh_auth.py`](src/tp_mcp/tools/refresh_auth.py) - Result sanitization
- [`tests/test_tools/test_refresh_auth_security.py`](tests/test_tools/test_refresh_auth_security.py) - Security tests

## Authentication Flow

The server uses a two-step authentication process:

1. **Cookie → OAuth Token**: Your stored cookie is exchanged for a short-lived OAuth access token (expires in 1 hour)
2. **Automatic Refresh**: Tokens are cached in memory and automatically refreshed before expiry

This means:
- You only need to authenticate once with `tp-mcp auth`
- API calls use proper Bearer token auth, not cookies
- If your session cookie expires (typically after several weeks), use `tp_refresh_auth` in Claude or run `tp-mcp auth` again

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
mypy src/
ruff check src/
```

## License

MIT

---

## Credits

Originally based on the [TrainingPeaks MCP Server](https://github.com/JamsusMaximus/trainingpeaks-mcp) by JamsusMaximus.
