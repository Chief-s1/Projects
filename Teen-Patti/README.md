# Teen Patti — Realtime Multiplayer LAN Game

A server-authoritative multiplayer **Teen Patti** web application built with **Streamlit, FastAPI, WebSockets, SQLAlchemy, SQLite, and OpenPyXL/Pandas**.

The project is designed for a group of players connected to the same LAN. Streamlit provides the visible application shell, while FastAPI owns the game state and WebSocket connections. The browser never becomes the authority for cards, balances, turns, timers, winners, or payouts.

> **Status:** LAN-focused single-host deployment. The default configuration is intended for one machine running the backend and Streamlit server, with other players connecting through the host machine's LAN IP.

---

## Features

### Multiplayer

- Up to **15 players per table**.
- Host creates a table with:
  - Host/player name
  - Starting chips
  - Boot amount
- A unique **4-digit table code** is generated automatically.
- Joining players enter only:
  - Player name
  - Table code
- Starting chips are configured by the host and are **not selectable by joining players**.
- Player joins are pushed to connected clients through WebSockets.
- Reconnection restores the player's authoritative state.

### Server-authoritative gameplay

The server is authoritative for:

- Player balances
- Cards
- Current player
- Turn order
- Turn deadline
- Current bid
- Pot
- Player status
- Side Show validation
- Showdown result
- Winner
- Winner payout
- Replay state

The client cannot submit its own cards, balance, winner, or turn state.

### Teen Patti gameplay

Implemented hand hierarchy:

1. Trail / Trio
2. Pure Sequence
3. Sequence
4. Color
5. Pair
6. High Card

The engine also handles the **A-2-3** sequence and hand tie-breakers.

### Blind and seen-card play

- Every player receives three server-generated cards.
- Players can initially play blind.
- A player can make up to **3 blind plays**.
- After the third blind play, the player must see their cards.
- Once cards are seen, the player cannot return to blind mode.
- Seen-card play follows the configured 2× bid rule.

### Private cards

Each player sees only their own cards during normal play.

Other players are represented by profile/name tiles rather than visible card backs. Hidden cards are never included in another player's private state payload.

The exception is a **SHOW** showdown: when exactly two active players remain and the current player chooses SHOW, both hands are intentionally revealed to everyone at the table.

### Turn timer

- Default turn length: **30 seconds**.
- The server stores `turn_started_at` and `turn_deadline`.
- The browser displays the remaining time using whole seconds.
- The active player's tile displays a green timer border that fades as the deadline approaches.
- When the server deadline expires, the player is automatically packed.
- The next player receives a fresh 30-second deadline.

The browser timer is visual only. Changing the browser clock cannot extend a turn.

### Pack

A player can pack during their own turn.

The server:

1. Marks the player inactive.
2. Selects the next active player.
3. Creates a new authoritative turn deadline.
4. Broadcasts the updated state.

The same transition is used for automatic timeout packing.

### Side Show

Side Show is available only when the server determines that:

- The current player has seen their cards.
- The immediately previous active player has seen their cards.
- Both players are still active.
- No conflicting Side Show request is pending.

The request is sent **only to the immediately previous active player** and contains the requester's name.

Example:

```text
Rahul wants a Side Show.

[Accept] [Decline]
```

The other players receive no Side Show request popup.

The **requester pays the Side Show cost**. The responding player is not charged.

### SHOW

When exactly **two active players remain**, SHOW becomes available to the current player.

When SHOW is selected:

1. The server retrieves both players' actual cards.
2. The server compares the hands.
3. Both hands are revealed to every connected player.
4. The winner receives the entire pot.
5. The match is finished.
6. The final result remains visible while replay decisions are collected.

### Winner payout

The winner receives the complete pot as chips.

For example:

```text
Player A balance: 8,000
Pot:              1,200

A wins

Player A balance: 9,200
```

The awarded amount is recorded in the match state and reporting data.

### Replay / next match

After a match finishes, the table enters a replay decision window.

- There is **one winner popup**.
- The popup also contains the new-match banner.
- Players default to **Yes**.
- Players can switch to **No** during the replay window.
- The replay decision window is **10 seconds**.
- A player who changes to No receives a **Thank you for playing** state and a highlighted **Download Scores** action.
- If enough players remain opted in, the next match starts automatically after the replay countdown.
- If everyone opts out, the table ends and the score workbook is saved on the admin/host machine.
- Players who continue carry their current chip balances into the next match.

The host's starting-chip setting is an initial table configuration; it is not reset after every match.

---

## Architecture

```text
                         LAN
                          │
                ┌─────────▼─────────┐
                │   Player Browser  │
                │ Streamlit UI shell│
                └─────────┬─────────┘
                          │
                    WebSocket / HTTP
                          │
              ┌───────────▼───────────┐
              │       FastAPI         │
              │  API + WebSocket hub  │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │    Match Service      │
              │ authoritative state  │
              └───────┬───────┬───────┘
                      │       │
             ┌────────▼─┐ ┌──▼────────────┐
             │Game Engine│ │State Manager  │
             │cards/rules│ │WS connections │
             └──────────┘ └──────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │ SQLite / SQL DB │
                         │   SQLAlchemy    │
                         └─────────────────┘
```

### Streamlit

Streamlit is the visible application shell. It handles:

- Create table screen
- Join table screen
- Session information
- Embedded realtime game interface
- Excel download controls

The actual game loop does **not** depend on Streamlit reruns.

### FastAPI

FastAPI provides:

- Table creation
- Table joining
- State retrieval
- Match start
- Player actions
- Side Show responses
- Excel reporting
- WebSocket connections

### WebSockets

Every connected player maintains a WebSocket to:

```text
ws://<host-ip>:8000/ws/<table-id>/<player-id>?token=<session-token>
```

Actions travel to the server once. Valid state changes are then pushed to connected clients.

There is no 100 ms database polling loop and no gameplay implementation based on repeated `st.rerun()` calls.

### Game engine

`backend/game_engine.py` contains the card/ranking logic:

- Standard 52-card deck
- Secure shuffle
- Hand evaluation
- Hand comparison
- Teen Patti ranking
- A-2-3 handling
- Tie-breakers

### State manager

`backend/state_manager.py` maintains active WebSocket connections and broadcasts server-generated state updates.

### Match service

`services/match_service.py` is the main gameplay coordinator. It handles:

- Table creation
- Joining
- Match start
- Betting
- Blind/seen state
- Pack
- Timeout
- Side Show
- SHOW
- Winner payout
- Replay window
- Reconnection

Per-table asynchronous locking prevents simultaneous actions from producing multiple conflicting state transitions.

### Database

SQLAlchemy is used as the persistence layer. SQLite is configured with:

- WAL mode
- Foreign keys
- Busy timeout
- Transactional state changes

The database stores tables, players, matches, game state, cards, actions, contributions, and Side Show requests.

---

## Project structure

```text
teen_patti/
│
├── app.py                       # Streamlit shell and embedded game UI
├── run.py                       # Starts FastAPI + Streamlit together
├── config.py                    # Environment-based configuration
├── requirements.txt
├── .env.example
├── .gitignore
│
├── .streamlit/
│   └── config.toml              # Light Streamlit theme
│
├── backend/
│   ├── api.py                   # REST + WebSocket endpoints
│   ├── auth.py                  # Session-token hashing/verification
│   ├── events.py                # Realtime event helpers
│   ├── game_engine.py           # Cards and Teen Patti rules
│   └── state_manager.py         # WebSocket connection manager
│
├── database/
│   ├── database.py              # SQLAlchemy engine/session/SQLite setup
│   └── models.py                # Relational database models
│
└── services/
    ├── excel_service.py         # Excel report generation
    └── match_service.py         # Core gameplay orchestration
```

Development-only test suites, pytest configuration, caches, and unused service wrappers are intentionally **not included in the distribution package**.

---

## Requirements

- Python **3.11+** recommended
- A Windows or Linux machine acting as the LAN host
- Modern Chromium/Edge/Firefox/Safari browser on each player device
- All devices must be able to reach the host on TCP ports **8501** and **8000**

No Redis server is required for the default single-host deployment.

---

## Installation — Windows

### 1. Clone the repository

```powershell
git clone <your-repository-url>
cd teen_patti
```

### 2. Create a virtual environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, either adjust the execution policy for the current user or activate the environment through `cmd.exe`.

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Create configuration

```powershell
copy .env.example .env
```

Edit `.env` and set a strong `SECRET_KEY`.

### 5. Start the application

```powershell
python run.py
```

The host should expose:

```text
Streamlit: http://<host-ip>:8501
FastAPI:   http://<host-ip>:8000
```

FastAPI health check:

```text
http://<host-ip>:8000/health
```

---

## Installation — Linux

```bash
git clone <your-repository-url>
cd teen_patti

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

python run.py
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

---

## Windows Firewall

The host must allow inbound TCP connections on ports **8501** and **8000**.

Run PowerShell as Administrator:

```powershell
New-NetFirewallRule `
  -DisplayName "Teen Patti Streamlit" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8501 `
  -Action Allow

New-NetFirewallRule `
  -DisplayName "Teen Patti FastAPI WebSocket" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8000 `
  -Action Allow
```

Find the host LAN address with:

```powershell
ipconfig
```

Players should then open:

```text
http://<HOST-LAN-IP>:8501
```

For example:

```text
http://192.168.1.20:8501
```

Do **not** tell other players to use `localhost`. On another device, `localhost` means that player's own device.

---

## Linux firewall

With UFW:

```bash
sudo ufw allow 8501/tcp
sudo ufw allow 8000/tcp
sudo ufw status
```

Then open:

```text
http://<HOST-LAN-IP>:8501
```

---

## Configuration

`.env.example`:

```env
HOST=0.0.0.0
PORT=8501
WEBSOCKET_PORT=8000
DATABASE_URL=sqlite:///./teen_patti.db
SECRET_KEY=replace-with-a-long-random-secret
MAX_PLAYERS=15
TURN_SECONDS=30
DISCONNECT_GRACE_SECONDS=60
LOG_LEVEL=INFO
```

### Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `HOST` | `0.0.0.0` | Bind address for Streamlit/FastAPI |
| `PORT` | `8501` | Streamlit port |
| `WEBSOCKET_PORT` | `8000` | FastAPI/API/WebSocket port |
| `DATABASE_URL` | `sqlite:///./teen_patti.db` | SQLAlchemy database URL |
| `SECRET_KEY` | development placeholder | Session/security secret |
| `MAX_PLAYERS` | `15` | Maximum players per table |
| `TURN_SECONDS` | `30` | Server-authoritative turn duration |
| `DISCONNECT_GRACE_SECONDS` | `60` | Reconnection grace configuration |
| `LOG_LEVEL` | `INFO` | Application logging level |

### Secret key

For any real deployment, replace the development value:

```env
SECRET_KEY=your-long-random-secret
```

A suitable value can be generated with Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## Starting a table

The host creates the table and chooses:

```text
Host name
Starting chips
Boot amount
```

Example:

```text
Host name: Rahul
Starting chips: 10000
Boot: 100
```

The server creates a four-digit table code, for example:

```text
5832
```

The host shares the code with the other players.

### Joining

A joining player enters only:

```text
Player name
Table code
```

The server assigns the table's configured starting chip amount.

Players cannot choose a different starting balance through the client.

---

## Match lifecycle

```text
LOBBY
  │
  │ Host presses Start Game
  ▼
PLAYING
  │
  ├── Player actions
  ├── Turn changes
  ├── Pack / timeout
  ├── Side Show
  └── SHOW when 2 active players remain
  │
  ▼
MATCH FINISHED
  │
  ▼
REPLAY WINDOW
  │
  ├── Players default to YES
  ├── Player can change to NO
  └── 10-second decision window
  │
  ├── 2+ eligible players → new match
  │
  └── insufficient players → table finished + score export
```

---

## Realtime protocol

### Client → server

Normal player action:

```json
{
  "type": "ACTION",
  "action": "BID",
  "request_id": "unique-request-id"
}
```

Side Show response:

```json
{
  "type": "SIDE_SHOW_RESPONSE",
  "request_id": "side-show-request-id",
  "accept": true
}
```

The server identifies the authenticated player from the WebSocket/session context. Client-supplied game state is not trusted.

### Server → client

Typical events include:

```text
STATE_SYNC
PLAYER_JOINED
PLAYER_LEFT
MATCH_STARTED
CARDS_DEALT
TURN_CHANGED
CARDS_REVEALED
BID_PLACED
PLAYER_PACKED
TIMEOUT
SIDE_SHOW_REQUEST
SIDE_SHOW_ACCEPTED
SIDE_SHOW_DECLINED
SIDE_SHOW_RESOLVED
MATCH_FINISHED
REPLAY_STARTED
REPLAY_UPDATED
REPLAY_ENDED
ERROR
```

Every state-changing event is associated with a monotonically increasing `state_version` so reconnecting clients can receive the latest authoritative snapshot.

---

## Timer design

The server stores:

```text
turn_started_at
turn_deadline
current_player_id
```

Example:

```text
turn_started_at = 17:10:00
turn_deadline    = 17:10:30
```

The browser calculates a smooth visual countdown from the server timestamp/deadline. It does not decide whether the turn is valid.

At the deadline:

```text
TURN EXPIRED
     ↓
AUTO PACK
     ↓
NEXT ACTIVE PLAYER
     ↓
NEW 30-SECOND DEADLINE
```

This prevents a client from extending its turn by changing local time or manipulating the countdown.

---

## Security model

The application is intended for an intranet game, but game state is still server-authoritative.

### Session authentication

Each joined player receives a random session token. A hash of the token is stored in the database.

The server validates:

- Token
- Player ID
- Table membership
- WebSocket membership
- Action legality

### Hidden cards

A player's private state contains only that player's cards when permitted.

The server does not broadcast opponents' hidden cards during ordinary play.

### Balance protection

Clients cannot submit a new balance.

All chip changes happen inside server-side game transitions.

### Winner protection

Clients cannot submit a winner. The server calculates winners from stored cards.

### Turn protection

Clients cannot select another player's turn or extend a deadline.

### Side Show protection

The server determines the immediately previous active player and creates the Side Show request itself.

---

## Excel reporting

The application generates Excel reports with `pandas` and `openpyxl`.

The workbook contains:

### Player Scores

Player balances and match contribution information.

### Match History

Match IDs, start/end timestamps, boot, pot, and winner.

### Ownership Ledger

Contribution amounts associated with each winner.

### Action Log

Recorded gameplay actions with timestamps and amounts.

### Player download

The player-facing download endpoint generates the workbook directly in memory and streams it as an `.xlsx` response. It does not depend on reopening a temporary relative file path.

### Host score file

When a table ends because the replay window has no viable continuation, the host can save the table score workbook under:

```text
scores/
```

with a Windows-safe timestamped filename such as:

```text
17-25-28-Sep-26_score_list.xlsx
```

`:` is intentionally replaced with `-` because Windows does not permit `:` in filenames.

---

## Database

The default database is:

```text
teen_patti.db
```

The database is created automatically when the application starts.

### Main tables

```text
tables
players
matches
game_state
player_cards
actions
match_contributions
side_show_requests
```

### SQLite settings

The application enables:

```text
WAL
Foreign keys
Busy timeout
```

This is appropriate for a single backend process serving a LAN table workload.

### PostgreSQL

For a larger deployment, configure PostgreSQL through SQLAlchemy. Add the appropriate PostgreSQL driver to `requirements.txt`, then set:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/teen_patti
```

For multiple backend processes, the realtime layer should also use a shared broker such as Redis rather than relying on in-process connection state.

---

## Latency considerations

The application is designed to avoid unnecessary synchronization overhead:

- One persistent WebSocket per player
- Server-pushed state changes
- No 100 ms database polling
- No gameplay loop based on `st.rerun()`
- Per-table action serialization
- Lightweight JSON state payloads

A target of **<100 ms state propagation on a normal LAN** is reasonable under normal conditions, but it is not a mathematical guarantee. Actual latency depends on Wi-Fi quality, browser scheduling, host CPU load, database contention, and network hardware.

---

## Troubleshooting

### Streamlit opens but says backend connection failed

Check that FastAPI is listening:

```text
http://127.0.0.1:8000/health
```

Expected response:

```json
{
  "ok": true,
  "service": "teen-patti",
  "websocket_port": 8000
}
```

If this fails, start the application with:

```bash
python run.py
```

### Other devices cannot open the game

Check:

1. They are on the same LAN.
2. The host is using its LAN IP, not `localhost`.
3. TCP 8501 is allowed through the firewall.
4. TCP 8000 is allowed through the firewall.
5. `HOST=0.0.0.0` is configured.

### Game stays on Connecting

Check FastAPI first:

```text
http://<HOST-IP>:8000/health
```

Then check the browser developer console for WebSocket errors.

The WebSocket endpoint is:

```text
ws://<HOST-IP>:8000/ws/<table-id>/<player-id>?token=<token>
```

### Score download fails

Make sure the backend has been restarted after updating the project. The current player download endpoint streams the workbook directly from memory.

### Port already in use

Check Windows:

```powershell
netstat -ano | findstr :8000
netstat -ano | findstr :8501
```

Linux:

```bash
ss -ltnp | grep -E ':8000|:8501'
```

Either stop the existing process or change the ports in `.env`.

### Database problems after changing schemas

For a development LAN deployment, stop the application and back up `teen_patti.db` before making schema changes. Do not delete the database if you need historical match records.

---

## Development notes

The distributed repository intentionally excludes:

- Unit-test files
- pytest configuration
- pytest cache
- Python bytecode
- Virtual environments
- Local `.env`
- Local SQLite database
- Generated score files
- Unused service wrappers
- Empty UI package placeholders

For contributors, tests can be maintained in a separate development branch or added back under `tests/` without changing the runtime architecture.

---

## Production hardening

Before exposing the application outside a trusted LAN, consider:

- HTTPS/WSS termination
- Strong secret management
- PostgreSQL
- Redis for multi-process realtime fan-out
- Reverse proxy such as Nginx/Caddy
- Authentication beyond temporary table sessions
- Rate limiting
- Structured audit logging
- Backups
- Database migrations
- Process supervision with systemd/Windows service
- Restricting CORS instead of allowing all origins

The current project is intentionally optimized for a controlled LAN game rather than public Internet hosting.

---

## License

Add the license you want to use before publishing the repository. If this project is intended to be open source, an `LICENSE` file should be committed alongside this README.

---

## Quick start

For the shortest possible setup:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Then open:

```text
http://<HOST-LAN-IP>:8501
```

Create a table, share the 4-digit code, and let the host start the match when ready.
