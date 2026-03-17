# Hack & Crack

Hack & Crack is a cyber-themed coding battle platform for college competitions.

## Run locally

```bash
python3 app.py
```

Open: `http://localhost:8080`

## Default login

- Admin username: `admin`
- Admin password: `admin123`

## What this build includes

- Reliable username/password authentication with one active session per user.
- SQLite-backed storage for users, sessions, rounds, questions, test cases, submissions, and badges.
- 3-level flow:
  - Level 1: Firewall Breach
  - Level 2: Algorithm Labyrinth
  - Level 3: Core System Hack
- Multi-language judge: C, C++, Java, Python, JavaScript.
- Hidden test case execution and scoring:
  - Correct = +100
  - Fast bonus = +50
  - First solver = +75
  - Wrong = -5
- Timer-based rounds and submission lock after round end.
- Anti-cheat system with tab switch tracking, copy/paste and right-click block, key shortcut block, devtools heuristic, fullscreen request.
- Real-time leaderboard and admin controls (round start/stop, participant generation).

## Admin API auth

Use header:

`X-Admin-Token: admin-secret`

Or set your own token with env variable:

`ADMIN_TOKEN=<your-secret>`
