"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { day: null, days: [], polling: null };

// ---------------------------------------------------------------- utilities
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3600);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

function busy(btn, on) {
  btn.disabled = on;
  btn.setAttribute("aria-busy", String(on));
}

// ---------------------------------------------------------------- rendering
function renderShipper(s) {
  const pill = $("#ship-pill");
  const text = $("#ship-text");
  pill.classList.remove("live", "off", "bad");

  if (!s.enabled) {
    pill.classList.add("off");
    text.textContent = "CloudWatch off — files only";
    pill.title = s.last_error || "";
    return;
  }
  if (s.last_error) {
    pill.classList.add("bad");
    text.textContent = "CloudWatch error";
    pill.title = s.last_error;
    return;
  }
  pill.classList.add("live");
  const dropped = s.dropped_too_old + s.dropped_too_new;
  text.textContent =
    `${s.shipped.toLocaleString()} shipped · ${s.streams.length} streams` +
    (dropped ? ` · ${dropped} dropped (age limit)` : "");
  pill.title = s.last_flush ? `last flush ${s.last_flush}` : "";
}

function renderTimeline(days) {
  const max = Math.max(1, ...days.map((d) => d.events));
  $("#timeline").innerHTML = days
    .map(
      (d) => `
    <li class="day ${d.scenario}">
      <div class="when">${d.label}<b>${d.date}</b></div>
      <div class="bar" role="img"
           aria-label="${d.events} events on ${d.date}, ${d.scenario}">
        <span style="width:${Math.round((d.events / max) * 100)}%"></span>
      </div>
      <div class="count"><b>${d.events.toLocaleString()}</b>
        <span class="badge ${d.scenario}">${d.scenario}</span></div>
    </li>`
    )
    .join("");
}

function renderTabs(days) {
  if (!state.day && days.length) state.day = days[0].date;
  $("#tabs").innerHTML = days
    .map(
      (d) => `<button class="tab" role="tab" data-date="${d.date}"
        aria-selected="${d.date === state.day}">${d.label}</button>`
    )
    .join("");
}

function renderLines(payload) {
  const stream = $("#stream");
  $("#file-path").textContent = payload.file || "";
  if (!payload.lines.length) {
    stream.innerHTML = `<span class="empty">No lines yet for ${payload.date}. Generate some traffic.</span>`;
    return;
  }
  const esc = (s) =>
    s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  stream.innerHTML = payload.lines
    .map((ln) => {
      const m = ln.match(/\b(CRITICAL|ERROR|WARNING|INFO)\b/);
      return `<span class="ln ${m ? m[1] : "INFO"}">${esc(ln)}</span>`;
    })
    .join("");
  stream.scrollTop = stream.scrollHeight;
}

// ---------------------------------------------------------------- data flow
async function refresh() {
  try {
    const stats = await api("/api/stats");
    state.days = stats.days;
    renderShipper(stats.shipper);
    renderTimeline(stats.days);
    renderTabs(stats.days);
    const total = stats.days.reduce((a, d) => a + d.events, 0);
    $("#totals").textContent =
      `${stats.visits} visit(s) · ${total.toLocaleString()} events in ${stats.days.length} daily files · ` +
      `instance ${stats.instance} · dir ${stats.log_dir}`;
    await loadLines();
  } catch (err) {
    toast(err.message, true);
  }
}

async function loadLines() {
  if (!state.day) return;
  renderLines(await api(`/api/logs?date=${state.day}&limit=300`));
}

// ---------------------------------------------------------------- wiring
document.addEventListener("click", async (ev) => {
  const route = ev.target.closest(".route");
  if (route) {
    busy(route, true);
    try {
      const r = await api("/api/visit", {
        method: "POST",
        body: JSON.stringify({ route: route.dataset.route }),
      });
      toast(`${r.events_generated} events across ${r.days_touched} dates`);
      await refresh();
    } catch (err) {
      toast(err.message, true);
    } finally {
      busy(route, false);
    }
    return;
  }

  const tab = ev.target.closest(".tab");
  if (tab) {
    state.day = tab.dataset.date;
    renderTabs(state.days);
    await loadLines();
    $("#stream").focus();
  }
});

$("#burst-count").addEventListener("input", (e) => {
  $("#burst-out").value = e.target.value;
});

$("#burst-go").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  busy(btn, true);
  try {
    const r = await api("/api/burst", {
      method: "POST",
      body: JSON.stringify({ count: Number($("#burst-count").value) }),
    });
    toast(`${r.visits} visits → ${r.events_generated} events`);
    await refresh();
  } catch (err) {
    toast(err.message, true);
  } finally {
    busy(btn, false);
  }
});

refresh();
state.polling = setInterval(refresh, 5000);
document.addEventListener("visibilitychange", () => {
  clearInterval(state.polling);
  if (!document.hidden) {
    refresh();
    state.polling = setInterval(refresh, 5000);
  }
});
