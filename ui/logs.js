/* The call log page.
 *
 * Deliberately its own page rather than a panel in the editor: a log is something
 * you read alongside the thing you are changing, so it needs to survive you
 * navigating around, and it needs to be linkable. The call id is in the query
 * string, which makes every log a URL you can paste to someone.
 */

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

function pairs(host, entries) {
  $(host).replaceChildren(
    ...entries.map(([label, value]) =>
      el("div", {}, [
        el("dt", { text: label }),
        el("dd", { text: value === null || value === undefined ? "—" : String(value) }),
      ]),
    ),
  );
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function num(value) {
  return (value ?? 0).toLocaleString();
}

function render(record) {
  document.title = `${record.config_name} — call log`;
  $("call-id").textContent = record.call_id;

  const providers = record.providers ?? {};
  pairs("overview", [
    ["started", fmtTime(record.started_at)],
    ["ended", fmtTime(record.ended_at)],
    ["duration", fmtDuration(record.duration_seconds)],
    ["outcome", record.outcome],
    ["config", record.config_name],
    ["config id", record.config_id],
    ["your turns", record.user_turns],
    ["agent turns", record.agent_turns],
    ["stt", providers.stt],
    ["llm", providers.llm],
    ["tts", providers.tts],
    ["vad", providers.vad],
  ]);

  const tokens = record.totals?.tokens ?? {};
  pairs("usage", [
    ["prompt tokens", num(tokens.prompt_tokens)],
    ["cached prompt", num(tokens.prompt_cached_tokens)],
    ["completion tokens", num(tokens.completion_tokens)],
    ["total tokens", num(tokens.total_tokens)],
    ["llm requests", num(record.totals?.llm_requests)],
    ["tts characters", num(record.totals?.tts_characters)],
    ["stt audio (s)", num(record.totals?.stt_audio_seconds)],
  ]);

  const tools = record.tools ?? [];
  if (tools.length) {
    $("tools-card").hidden = false;
    // A tool the model called but that was never registered shows up here as an
    // error. The answer it then gave came from the model, not from your data.
    const failed = tools.filter((t) => t.errors > 0);
    const warn = $("tools-warning");
    warn.hidden = failed.length === 0;
    if (failed.length) {
      const enabled = (record.config?.tools ?? []).length;
      warn.textContent = enabled
        ? `${failed.map((t) => t.name).join(", ")} failed during this call — answers that needed it were not grounded.`
        : `The model tried to call ${failed.map((t) => t.name).join(", ")}, but this config enables no tools. Any answer it gave was ungrounded.`;
    }
    $("tools-table").querySelector("tbody").replaceChildren(
      ...tools.map((t) =>
        el("tr", {}, [
          el("td", {}, [el("code", { text: t.name })]),
          el("td", { class: "num-col", text: String(t.calls) }),
          el("td", { class: "num-col", text: String(t.errors) }),
        ]),
      ),
    );
  }

  $("config-json").textContent = JSON.stringify(record.config ?? {}, null, 2);

  if (record.error) {
    $("log-status").hidden = false;
    $("log-status").className = "log-status error";
    $("log-status").textContent = `This call reported an error: ${record.error}`;
  } else {
    $("log-status").hidden = true;
  }
  $("log-body").hidden = false;
}

async function main() {
  const callId = new URLSearchParams(location.search).get("call");
  if (!callId) {
    $("log-status").className = "log-status error";
    $("log-status").textContent = "No call id in the URL.";
    return;
  }

  const res = await fetch(`/api/calls/${encodeURIComponent(callId)}`);
  if (!res.ok) {
    $("log-status").className = "log-status error";
    $("log-status").textContent =
      res.status === 404
        ? `No log found for ${callId}.`
        : `Could not load the log (${res.status}).`;
    return;
  }
  render(await res.json());
}

main();
