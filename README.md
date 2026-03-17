# Hack & Crack

Hack & Crack is a cyber-themed coding battle platform for college competitions.

## Run locally

```bash
python3 app.py
```

Then open: `http://localhost:8080`

## Key capabilities

- User authentication with admin/player roles and SQLite persistence.
- Admin-generated credentials and one-active-session-per-user enforcement.
- 3 game levels:
  - Level 1: Firewall Breach
  - Level 2: Algorithm Labyrinth
  - Level 3: Core System Hack
- Multi-language judging for C, C++, Java, Python, and JavaScript.
- Hidden testcase execution with verdict + execution time.
- XP game scoring:
  - Correct: +100
  - Fast bonus: +50
  - First solver bonus: +75
  - Wrong: -5
- Badge + level-unlock progression.
- Round timer and submission lock once timer expires.
- Anti-cheat controls (tab switch limits, shortcut blocking, copy/paste disable, right-click disable, fullscreen request, devtools heuristic).
- Live leaderboard (polling) with rank, score, solved, level, and time.
- Admin tools:
  - Start/stop rounds
  - Generate users
  - Add/edit questions via API
  - Upload hidden testcases
  - View submissions
  - Export CSV results

## API snippets

- Login: `POST /api/login`
- Submit solution: `POST /api/submit`
- Leaderboard: `GET /api/leaderboard`
- Round state: `GET /api/round`
- Admin token header: `X-Admin-Token: admin-secret`

## Default admin account

- Username: `admin`
- Password: `admin123`
