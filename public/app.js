const state = {
  token: localStorage.getItem("token") || "",
  me: null,
  round: null,
  currentQuestion: null,
  timerInterval: null,
  boardInterval: null,
  tabSwitches: 0,
  cheatFlags: 0,
};

async function api(path, method = "GET", body = null, useAdmin = false) {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(useAdmin ? { "X-Admin-Token": "admin-secret" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let message = "Request failed";
    try {
      const err = await response.json();
      message = err.error || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }

  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response.text();
}

function byId(id) { return document.getElementById(id); }

async function login() {
  const username = byId("username").value.trim();
  const password = byId("password").value.trim();
  const data = await api("/api/login", "POST", { username, password });
  state.token = data.token;
  localStorage.setItem("token", data.token);
  byId("loginCard").classList.add("hidden");
  byId("app").classList.remove("hidden");
  if (data.role === "admin") byId("adminPanel").classList.remove("hidden");
  await refreshAll();
}

async function logout() {
  try { await api("/api/logout", "POST"); } catch {}
  localStorage.removeItem("token");
  location.reload();
}

function updateProfile() {
  const me = state.me;
  byId("profile").innerHTML = [
    `<b>${me.username}</b> (${me.role})`,
    `XP: ${me.score}`,
    `Solved: ${me.solved}`,
    `Level: ${me.current_level}`,
    `Cheat flags: ${me.cheat_flags} | Tab switches: ${me.tab_switches}`,
    `Badges: ${(me.badges || []).join(", ") || "None"}`,
  ].join("<br>");
  byId("levelProgress").firstElementChild.style.width = `${Math.min(100, me.current_level * 33.33)}%`;
}

async function refreshLeaderboard() {
  const rows = await api("/api/leaderboard");
  byId("leaderboard").innerHTML = `
    <tr><th>Rank</th><th>User</th><th>XP</th><th>Solved</th><th>Time</th><th>Level</th></tr>
    ${rows.map(r => `<tr><td>${r.rank}</td><td>${r.username}</td><td>${r.score}</td><td>${r.solved}</td><td>${r.total_time}ms</td><td>${r.current_level}</td></tr>`).join("")}
  `;
}

function startTimer() {
  if (state.timerInterval) clearInterval(state.timerInterval);
  state.timerInterval = setInterval(() => {
    if (!state.round) return;
    const now = Math.floor(Date.now() / 1000);
    const left = Math.max(0, state.round.ends_at - now);
    const mm = String(Math.floor(left / 60)).padStart(2, "0");
    const ss = String(left % 60).padStart(2, "0");
    byId("timer").textContent = `${mm}:${ss}`;
    byId("roundStatus").textContent = `Round: ${state.round.status} (L${state.round.level})`;
    if (left === 0 && state.round.status === "running") {
      byId("result").textContent = "Time up. Submissions are blocked.";
    }
  }, 1000);
}

async function refreshRound() {
  state.round = await api("/api/round");
  startTimer();
}

async function refreshAll() {
  state.me = await api("/api/me");
  updateProfile();
  await refreshRound();
  await refreshLeaderboard();

  if (state.boardInterval) clearInterval(state.boardInterval);
  state.boardInterval = setInterval(refreshLeaderboard, 4000);
}

async function startMission() {
  const qs = await api(`/api/questions?level=${state.me.current_level}`);
  if (!qs.length) {
    byId("result").textContent = "No question available for your level yet.";
    return;
  }
  const names = ["Firewall Breach", "Algorithm Labyrinth", "Core System Hack"];
  state.currentQuestion = qs[0];
  byId("missionPanel").classList.remove("hidden");
  byId("missionTitle").textContent = names[state.me.current_level - 1] || "Mission";
  byId("question").innerHTML = `
    <h4>${state.currentQuestion.title} <small>[${state.currentQuestion.qtype}]</small></h4>
    <p>${state.currentQuestion.statement}</p>
    <p><b>Sample Input:</b> ${state.currentQuestion.sample_input || "(none)"}</p>
    <p><b>Sample Output:</b> ${state.currentQuestion.sample_output || "(none)"}</p>
  `;
}

async function submitCode() {
  if (!state.currentQuestion) return;
  const payload = {
    question_id: state.currentQuestion.id,
    language: byId("language").value,
    code: byId("code").value,
  };
  try {
    const out = await api("/api/submit", "POST", payload);
    byId("result").textContent = `${out.verdict} | ${out.points >= 0 ? "+" : ""}${out.points} XP | ${out.exec_ms}ms`;
    await refreshAll();
  } catch (err) {
    byId("result").textContent = err.message;
  }
}

async function antiCheatPing(extra = {}) {
  try {
    const out = await api("/api/anti-cheat", "POST", {
      tab_switches: state.tabSwitches,
      cheat_flags: state.cheatFlags,
      ...extra,
    });
    if (out.disqualified) {
      alert("Disqualified due to anti-cheat violations.");
      await logout();
    }
  } catch {}
}

async function adminStartRound() {
  const out = await api("/api/admin/round", "POST", { status: "running", level: 1, duration_sec: 1200 }, true);
  byId("adminOut").textContent = JSON.stringify(out, null, 2);
  await refreshRound();
}

async function adminStopRound() {
  const out = await api("/api/admin/round", "POST", { status: "stopped", level: 1 }, true);
  byId("adminOut").textContent = JSON.stringify(out, null, 2);
  await refreshRound();
}

async function adminGenerateUsers() {
  const count = Number(byId("userCount").value || "5");
  const prefix = byId("userPrefix").value || "cadet";
  const out = await api("/api/admin/generate-users", "POST", { count, prefix }, true);
  byId("adminOut").textContent = JSON.stringify(out, null, 2);
}

async function adminAddQuestion() {
  let testCases = [];
  try {
    testCases = JSON.parse(byId("qTests").value || "[]");
  } catch {
    byId("adminOut").textContent = "Invalid testcase JSON";
    return;
  }
  const payload = {
    title: byId("qTitle").value,
    level: Number(byId("qLevel").value),
    qtype: byId("qType").value,
    statement: byId("qStatement").value,
    sample_input: byId("qSampleIn").value,
    sample_output: byId("qSampleOut").value,
    test_cases: testCases,
  };
  const out = await api("/api/admin/questions", "POST", payload, true);
  byId("adminOut").textContent = JSON.stringify(out, null, 2);
}

async function adminSubmissions() {
  const out = await api("/api/admin/submissions", "GET", null, true);
  byId("adminOut").textContent = JSON.stringify(out.slice(0, 25), null, 2);
}

async function adminExport() {
  const out = await api("/api/admin/export", "GET", null, true);
  byId("adminOut").textContent = out;
}

function registerAntiCheat() {
  window.addEventListener("contextmenu", e => e.preventDefault());
  ["copy", "paste", "cut"].forEach(name => window.addEventListener(name, e => e.preventDefault()));

  window.addEventListener("keydown", e => {
    const blockCtrl = e.ctrlKey && ["c", "v", "u", "s", "p"].includes(e.key.toLowerCase());
    const blockKey = ["F12"].includes(e.key);
    if (blockCtrl || blockKey) {
      e.preventDefault();
      state.cheatFlags += 1;
      antiCheatPing({ shortcut_attempt: true });
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      state.tabSwitches += 1;
      antiCheatPing();
      if (state.tabSwitches > 3) alert("Warning: tab switch limit exceeded.");
    }
  });

  setInterval(() => {
    const devtoolsLikely = (window.outerWidth - window.innerWidth > 160) || (window.outerHeight - window.innerHeight > 160);
    if (devtoolsLikely) {
      state.cheatFlags += 1;
      antiCheatPing({ devtools: true });
    }
  }, 3500);

  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen().catch(() => {});
  }
}

function bindEvents() {
  byId("loginBtn").addEventListener("click", () => login().catch(e => alert(e.message)));
  byId("logoutBtn").addEventListener("click", logout);
  byId("startMissionBtn").addEventListener("click", () => startMission().catch(e => byId("result").textContent = e.message));
  byId("submitBtn").addEventListener("click", submitCode);

  byId("startRoundBtn").addEventListener("click", () => adminStartRound().catch(e => byId("adminOut").textContent = e.message));
  byId("stopRoundBtn").addEventListener("click", () => adminStopRound().catch(e => byId("adminOut").textContent = e.message));
  byId("generateUsersBtn").addEventListener("click", () => adminGenerateUsers().catch(e => byId("adminOut").textContent = e.message));
  byId("addQuestionBtn").addEventListener("click", () => adminAddQuestion().catch(e => byId("adminOut").textContent = e.message));
  byId("loadSubmissionsBtn").addEventListener("click", () => adminSubmissions().catch(e => byId("adminOut").textContent = e.message));
  byId("exportBtn").addEventListener("click", () => adminExport().catch(e => byId("adminOut").textContent = e.message));
}

(async function boot() {
  bindEvents();
  registerAntiCheat();

  if (!state.token) return;
  byId("loginCard").classList.add("hidden");
  byId("app").classList.remove("hidden");
  try {
    await refreshAll();
    if (state.me.role === "admin") byId("adminPanel").classList.remove("hidden");
  } catch {
    localStorage.removeItem("token");
    location.reload();
  }
})();
