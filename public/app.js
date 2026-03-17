const state = {
  token: localStorage.getItem("token") || "",
  me: null,
  round: null,
  question: null,
  boardPoll: null,
  timerPoll: null,
  tabSwitches: 0,
  cheatFlags: 0,
  antiCheatEnabled: false,
};

const el = (id) => document.getElementById(id);

async function api(path, method = "GET", body = null, admin = false) {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(admin ? { "X-Admin-Token": "admin-secret" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const type = res.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error(payload.error || payload || "Request failed");
  return payload;
}

function setLoggedInUI(role) {
  el("loginCard").classList.add("hidden");
  el("app").classList.remove("hidden");
  if (role === "admin") el("adminPanel").classList.remove("hidden");
}

function renderProfile() {
  const me = state.me;
  el("profile").innerHTML = [
    `<b>${me.username}</b> (${me.role})`,
    `XP: ${me.score}`,
    `Solved: ${me.solved}`,
    `Level: ${me.current_level}`,
    `Tab Switches: ${me.tab_switches}`,
    `Badges: ${(me.badges || []).join(", ") || "None"}`,
  ].join("<br>");
  el("levelFill").style.width = `${Math.min(100, me.current_level * 33.33)}%`;
}

function setupTimer() {
  if (state.timerPoll) clearInterval(state.timerPoll);
  state.timerPoll = setInterval(async () => {
    try {
      state.round = await api("/api/round");
      const now = Math.floor(Date.now() / 1000);
      const left = Math.max(0, state.round.ends_at - now);
      el("roundStatus").textContent = `Round: ${state.round.status} (L${state.round.level})`;
      el("timer").textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
      if (left === 0 && state.round.status === "running") {
        el("result").textContent = "Round timer is over. Submissions are locked.";
      }
    } catch {}
  }, 1000);
}

async function refreshLeaderboard() {
  const rows = await api("/api/leaderboard");
  el("leaderboard").innerHTML = [
    "<tr><th>#</th><th>Player</th><th>Score</th><th>Solved</th><th>Time</th><th>Level</th></tr>",
    ...rows.map((r) => `<tr><td>${r.rank}</td><td>${r.username}</td><td>${r.score}</td><td>${r.solved}</td><td>${r.total_time}ms</td><td>${r.current_level}</td></tr>`),
  ].join("");
}

async function bootDashboard() {
  state.me = await api("/api/me");
  renderProfile();
  await refreshLeaderboard();
  setupTimer();
  if (state.boardPoll) clearInterval(state.boardPoll);
  state.boardPoll = setInterval(refreshLeaderboard, 4000);
  enableAntiCheat();
}

async function login() {
  el("loginMsg").textContent = "";
  try {
    const username = el("username").value.trim();
    const password = el("password").value.trim();
    const auth = await api("/api/login", "POST", { username, password });
    state.token = auth.token;
    localStorage.setItem("token", auth.token);
    setLoggedInUI(auth.role);
    await bootDashboard();
  } catch (err) {
    el("loginMsg").textContent = err.message;
  }
}

async function logout() {
  try { await api("/api/logout", "POST"); } catch {}
  localStorage.removeItem("token");
  location.reload();
}

async function startMission() {
  try {
    const list = await api(`/api/questions?level=${state.me.current_level}`);
    if (!list.length) {
      el("result").textContent = "No mission found for this level yet.";
      return;
    }
    state.question = list[0];
    const levelNames = ["Firewall Breach", "Algorithm Labyrinth", "Core System Hack"];
    el("missionTitle").textContent = levelNames[state.me.current_level - 1] || "Mission";
    el("question").innerHTML = `
      <h4>${state.question.title} <small>[${state.question.qtype}]</small></h4>
      <p>${state.question.statement}</p>
      <p><b>Sample Input:</b> ${state.question.sample_input || "(none)"}</p>
      <p><b>Sample Output:</b> ${state.question.sample_output || "(none)"}</p>
    `;
    el("missionPanel").classList.remove("hidden");
  } catch (err) {
    el("result").textContent = err.message;
  }
}

async function submitCode() {
  if (!state.question) return;
  try {
    const out = await api("/api/submit", "POST", {
      question_id: state.question.id,
      language: el("language").value,
      code: el("code").value,
    });
    el("result").textContent = `${out.verdict} | ${out.points >= 0 ? "+" : ""}${out.points} XP | ${out.exec_ms}ms`;
    await bootDashboard();
  } catch (err) {
    el("result").textContent = err.message;
  }
}

async function sendAntiCheat(extra = {}) {
  if (!state.antiCheatEnabled) return;
  try {
    const out = await api("/api/anti-cheat", "POST", {
      tab_switches: state.tabSwitches,
      cheat_flags: state.cheatFlags,
      ...extra,
    });
    if (out.disqualified) {
      alert("You were disqualified by anti-cheat checks.");
      await logout();
    }
  } catch {}
}

function enableAntiCheat() {
  if (state.antiCheatEnabled) return;
  state.antiCheatEnabled = true;

  window.addEventListener("contextmenu", (e) => e.preventDefault());
  ["copy", "paste", "cut"].forEach((evt) => window.addEventListener(evt, (e) => e.preventDefault()));

  window.addEventListener("keydown", (e) => {
    const ctrlBlocked = e.ctrlKey && ["c", "v", "u", "s", "p"].includes(e.key.toLowerCase());
    const keyBlocked = ["F12"].includes(e.key);
    if (ctrlBlocked || keyBlocked) {
      e.preventDefault();
      state.cheatFlags += 1;
      sendAntiCheat({ shortcut_attempt: true });
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      state.tabSwitches += 1;
      sendAntiCheat();
    }
  });

  // less aggressive detection to reduce false positives
  setInterval(() => {
    const maybeDevtools = window.outerWidth - window.innerWidth > 260 || window.outerHeight - window.innerHeight > 260;
    if (maybeDevtools) {
      state.cheatFlags += 1;
      sendAntiCheat({ devtools: true });
    }
  }, 10000);

  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(() => {});
  }
}

async function adminStartRound() {
  const out = await api("/api/admin/round", "POST", { status: "running", level: 1, duration_sec: 1200 }, true);
  el("adminOut").textContent = JSON.stringify(out, null, 2);
}

async function adminStopRound() {
  const out = await api("/api/admin/round", "POST", { status: "stopped", level: 1 }, true);
  el("adminOut").textContent = JSON.stringify(out, null, 2);
}

async function adminGenerateUsers() {
  const out = await api("/api/admin/generate-users", "POST", {
    prefix: el("userPrefix").value || "cadet",
    count: Number(el("userCount").value || "5"),
  }, true);
  el("adminOut").textContent = JSON.stringify(out, null, 2);
}

function bind() {
  el("loginBtn").addEventListener("click", login);
  el("logoutBtn").addEventListener("click", logout);
  el("startMissionBtn").addEventListener("click", startMission);
  el("submitBtn").addEventListener("click", submitCode);
  el("startRoundBtn").addEventListener("click", () => adminStartRound().catch((e) => el("adminOut").textContent = e.message));
  el("stopRoundBtn").addEventListener("click", () => adminStopRound().catch((e) => el("adminOut").textContent = e.message));
  el("generateUsersBtn").addEventListener("click", () => adminGenerateUsers().catch((e) => el("adminOut").textContent = e.message));
}

(async function init() {
  bind();
  if (!state.token) return;
  try {
    setLoggedInUI("player");
    await bootDashboard();
    if (state.me.role === "admin") el("adminPanel").classList.remove("hidden");
  } catch {
    localStorage.removeItem("token");
    location.reload();
  }
})();
