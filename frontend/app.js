const form = document.getElementById("generate-form");
const promptInput = document.getElementById("prompt");
const terminal = document.getElementById("terminal");
const statusNode = document.getElementById("status");
const submitButton = document.getElementById("submit-btn");

let eventSource = null;
let statusTimer = null;

function appendLine(agent, level, message) {
  const line = document.createElement("div");
  line.className = `line ${level || "info"}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] [${agent}] [${level}] ${message}`;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}

function setStatus(text, isError = false) {
  statusNode.className = `status ${isError ? "err" : "ok"}`;
  statusNode.textContent = text;
}

async function pollStatus(runId) {
  try {
    const response = await fetch(`/runs/${runId}/status`);
    if (!response.ok) return;
    const data = await response.json();
    if (data.status === "success") {
      setStatus("Run completed successfully");
      if (data.deployed_url) {
        const link = document.createElement("a");
        link.href = data.deployed_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = data.deployed_url;
        const wrap = document.createElement("div");
        wrap.className = "line";
        wrap.appendChild(document.createTextNode("Live URL: "));
        wrap.appendChild(link);
        terminal.appendChild(wrap);
      }
      stopWatchers();
      submitButton.disabled = false;
    } else if (data.status === "failed") {
      setStatus("Run failed", true);
      appendLine("orchestrator", "error", "Generation failed. Check logs above for details.");
      stopWatchers();
      submitButton.disabled = false;
    } else {
      setStatus(`Current status: ${data.status}`);
    }
  } catch (err) {
    appendLine("frontend", "warning", `Status polling issue: ${err.message}`);
  }
}

function stopWatchers() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (statusTimer) {
    clearInterval(statusTimer);
    statusTimer = null;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  stopWatchers();
  terminal.innerHTML = "";
  submitButton.disabled = true;
  setStatus("Submitting request...");

  try {
    const response = await fetch("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: promptInput.value.trim() }),
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "Failed to start run");
    }

    const { run_id: runId } = await response.json();
    appendLine("orchestrator", "info", `Run created with ID ${runId}`);
    setStatus("Run started");

    eventSource = new EventSource(`/runs/${runId}/logs`);
    eventSource.onmessage = (e) => {
      const row = JSON.parse(e.data);
      appendLine(row.agent, row.level, row.message);
    };
    eventSource.addEventListener("done", () => {
      appendLine("orchestrator", "info", "Log stream completed");
    });
    eventSource.onerror = () => {
      appendLine("frontend", "warning", "Log stream interrupted; polling continues");
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };

    statusTimer = setInterval(() => pollStatus(runId), 2500);
  } catch (err) {
    setStatus("Unable to start run", true);
    appendLine("frontend", "error", err.message);
    submitButton.disabled = false;
  }
});
