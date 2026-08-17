/* The call log page.
 *
 * Its own page rather than a panel in the editor: a log is read alongside the
 * thing you are changing, so it has to survive navigation and be linkable. The
 * call id lives in the query string, which makes every log a URL you can paste.
 *
 * Presented as a log, not a dashboard — monospace, aligned label/value rows,
 * everything flowing downwards. Nothing scrolls sideways.
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

/** One `label   value` line. */
function rows(host, entries) {
  $(host).replaceChildren(
    ...entries
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([label, value, cls]) =>
        el("div", { class: "log-row" }, [
          el("span", { class: "log-key", text: label }),
          el("span", { class: `log-val ${cls ?? ""}`, text: String(value) }),
        ]),
      ),
  );
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return null;
  const s = Math.round(seconds);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function fmtTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

const num = (v) => (v ?? 0).toLocaleString();

function render(record) {
  document.title = `${record.config_name} — call log`;

  $("log-title").textContent = record.call_id;
  const when = fmtTime(record.started_at);
  const dur = fmtDuration(record.duration_seconds);
  $("log-sub").textContent = [record.outcome, when, dur].filter(Boolean).join("  ·  ");
  $("log-sub").className = `log-sub ${record.outcome === "error" ? "bad" : ""}`;

  const p = record.providers ?? {};
  rows("rows-call", [
    ["config", `${record.config_name}  (${record.config_id})`],
    ["started", fmtTime(record.started_at)],
    ["ended", fmtTime(record.ended_at)],
    ["duration", fmtDuration(record.duration_seconds)],
    ["outcome", record.outcome, record.outcome === "error" ? "bad" : "good"],
    ["error", record.error, "bad"],
    ["shutdown", record.shutdown_reason],
    ["turns", `you ${record.user_turns}  ·  agent ${record.agent_turns}`],
    ["stt", p.stt],
    ["llm", p.llm],
    ["tts", p.tts],
    ["vad", p.vad],
  ]);

  const t = record.totals?.tokens ?? {};
  rows("rows-usage", [
    ["prompt tokens", num(t.prompt_tokens)],
    ["cached prompt", num(t.prompt_cached_tokens)],
    ["completion tokens", num(t.completion_tokens)],
    ["total tokens", num(t.total_tokens)],
    ["llm requests", num(record.totals?.llm_requests)],
    ["tts characters", num(record.totals?.tts_characters)],
    ["stt audio", `${num(record.totals?.stt_audio_seconds)}s`],
  ]);

  const tools = record.tools ?? [];
  if (tools.length) {
    $("section-tools").hidden = false;
    rows(
      "rows-tools",
      tools.map((tool) => [
        tool.name,
        `calls ${tool.calls}  ·  errors ${tool.errors}`,
        tool.errors > 0 ? "bad" : "good",
      ]),
    );

    // A tool the model called but that was never registered lands here as an
    // error. Any answer it then gave came from the model, not from your data.
    const failed = tools.filter((tool) => tool.errors > 0);
    const warn = $("tools-warning");
    warn.hidden = failed.length === 0;
    if (failed.length) {
      const names = failed.map((tool) => tool.name).join(", ");
      warn.textContent = (record.config?.tools ?? []).length
        ? `${names} failed during this call — answers that needed it were not grounded.`
        : `The model tried to call ${names}, but this config enables no tools. Any answer it gave was ungrounded.`;
    }
  }

  $("config-json").textContent = JSON.stringify(record.config ?? {}, null, 2);
  $("log-status").hidden = true;
  $("log-body").hidden = false;
}

async function main() {
  const callId = new URLSearchParams(location.search).get("call");
  if (!callId) {
    $("log-status").className = "log-status bad";
    $("log-status").textContent = "No call id in the URL.";
    return;
  }

  const res = await fetch(`/api/calls/${encodeURIComponent(callId)}`);
  if (!res.ok) {
    $("log-status").className = "log-status bad";
    $("log-status").textContent =
      res.status === 404
        ? `No log found for ${callId}.`
        : `Could not load the log (${res.status}).`;
    return;
  }
  render(await res.json());
}

main();
