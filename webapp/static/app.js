"use strict";

const $ = (sel) => document.querySelector(sel);

async function checkHealth() {
  const pill = $("#health-pill");
  const text = $("#health-text");
  try {
    const res = await fetch("/health");
    if (!res.ok) throw new Error(`${res.status}`);
    pill.classList.remove("off");
    pill.classList.add("live");
    text.textContent = "server ok";
  } catch (err) {
    pill.classList.remove("live");
    pill.classList.add("off");
    text.textContent = "server unreachable";
  }
}

checkHealth();
let polling = setInterval(checkHealth, 10000);
document.addEventListener("visibilitychange", () => {
  clearInterval(polling);
  if (!document.hidden) {
    checkHealth();
    polling = setInterval(checkHealth, 10000);
  }
});

// ---------------------------------------------------------------- neural network background
(function neuralBackground() {
  const canvas = document.getElementById("neural-bg");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let w, h, nodes;
  const NODE_COUNT = 60;

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }

  function makeNodes() {
    nodes = Array.from({ length: NODE_COUNT }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.35,
      vy: (Math.random() - 0.5) * 0.35,
    }));
  }

  function step() {
    ctx.clearRect(0, 0, w, h);
    for (const n of nodes) {
      n.x += n.vx;
      n.y += n.vy;
      if (n.x < 0 || n.x > w) n.vx *= -1;
      if (n.y < 0 || n.y > h) n.vy *= -1;
    }
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 140) {
          ctx.strokeStyle = `rgba(79, 209, 197, ${0.14 * (1 - dist / 140)})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    for (const n of nodes) {
      ctx.fillStyle = "rgba(124, 156, 255, 0.55)";
      ctx.beginPath();
      ctx.arc(n.x, n.y, 1.8, 0, Math.PI * 2);
      ctx.fill();
    }
    if (!reduceMotion) requestAnimationFrame(step);
  }

  window.addEventListener("resize", () => {
    resize();
    makeNodes();
  });
  resize();
  makeNodes();
  step();
})();

// ---------------------------------------------------------------- AI agent terminal typing effect
(function agentTerminal() {
  const el = document.getElementById("terminal-body");
  if (!el) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const lines = [
    "$ agent watch --scope multicloud",
    "> observing AWS, Azure, GCP telemetry...",
    "! anomaly detected: p99 latency +340% on orders-api (us-east-1)",
    "> reasoning: correlating traces, logs, deploy history...",
    "> root cause: connection pool exhaustion after v2.14.0 rollout",
    "> action: scaling pool size, triggering canary rollback",
    "✔ remediation applied in 8.2s — service healthy",
    "> generating incident summary with GenAI copilot...",
    "✔ report ready: /reports/incident-2026-09-05.md",
  ];

  if (reduceMotion) {
    el.textContent = lines.join("\n");
    return;
  }

  let lineIndex = 0;
  let charIndex = 0;
  let rendered = "";

  function typeNext() {
    if (lineIndex >= lines.length) {
      setTimeout(() => {
        rendered = "";
        lineIndex = 0;
        charIndex = 0;
        el.textContent = "";
        typeNext();
      }, 2600);
      return;
    }
    const current = lines[lineIndex];
    if (charIndex <= current.length) {
      el.textContent = rendered + current.slice(0, charIndex) + "▌";
      charIndex++;
      setTimeout(typeNext, 18 + Math.random() * 28);
    } else {
      rendered += current + "\n";
      el.textContent = rendered;
      lineIndex++;
      charIndex = 0;
      setTimeout(typeNext, 420);
    }
  }

  typeNext();
})();

// ---------------------------------------------------------------- DB connectivity check
(function dbConnectivityForm() {
  const form = document.getElementById("db-form");
  if (!form) return;
  const result = document.getElementById("db-result");
  const submitBtn = document.getElementById("db-submit");
  const portInput = document.getElementById("db-port");
  const engineSelect = document.getElementById("db-engine");

  const defaultPorts = { mysql: 3306, postgres: 5432 };
  engineSelect.addEventListener("change", () => {
    portInput.placeholder = String(defaultPorts[engineSelect.value] || "");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.setAttribute("aria-busy", "true");
    result.className = "db-result";
    result.textContent = "Testing connection…";

    const payload = {
      engine: engineSelect.value,
      host: document.getElementById("db-host").value.trim(),
      port: portInput.value ? Number(portInput.value) : undefined,
      database: document.getElementById("db-name").value.trim(),
      user: document.getElementById("db-user").value.trim(),
      password: document.getElementById("db-pass").value,
    };

    try {
      const res = await fetch("/api/db/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));

      if (res.ok && data.ok) {
        result.className = "db-result ok";
        result.textContent = `✔ Connected successfully (${data.latency_ms} ms). Logged to access log.`;
      } else {
        result.className = "db-result fail";
        result.textContent = `✖ Connection failed: ${data.error || "unknown error"}. Logged to error log.`;
      }
    } catch (err) {
      result.className = "db-result fail";
      result.textContent = `✖ Request failed: ${err.message}`;
    } finally {
      submitBtn.disabled = false;
      submitBtn.removeAttribute("aria-busy");
    }
  });
})();


