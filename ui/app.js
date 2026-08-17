/* Config editor.
 *
 * Nothing about providers is hardcoded here. The stage sections, their dropdowns,
 * and the fields under each dropdown are all built from GET /api/providers, which
 * is generated from the provider catalogue in Python. Adding a provider to that
 * table makes it appear here with no change to this file.
 */

const STAGES = [
  { key: "stt", title: "Speech to text" },
  { key: "llm", title: "Language model" },
  { key: "tts", title: "Text to speech" },
  { key: "vad", title: "Voice activity detection" },
];

const state = {
  catalogue: null, // stage -> [providerSpec]
  selectedId: null,
  room: null, // live LiveKit Room while a call is up
  muted: false,
  callId: null, // room name of the call in flight, used to fetch its log after
};

/* ---------- helpers ---------- */

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

async function api(path, options) {
  const res = await fetch(path, options);
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  return { ok: res.ok, status: res.status, body };
}

function fieldId(stage, name) {
  return `field-${stage}-${name}`;
}

/* ---------- rendering ---------- */

function renderStages() {
  for (const { key, title } of STAGES) {
    const card = $(`stage-${key}`);
    card.replaceChildren();
    card.appendChild(el("h3", { text: title }));

    const select = el("select", { id: `provider-${key}` });
    for (const provider of state.catalogue[key]) {
      const label = provider.available
        ? provider.label
        : `${provider.label} — needs ${provider.credential}`;
      select.appendChild(
        el("option", {
          value: provider.name,
          text: label,
          disabled: provider.available ? null : "disabled",
        }),
      );
    }
    select.addEventListener("change", () => renderStageFields(key, {}));

    card.appendChild(
      el("label", { class: "field" }, [
        el("span", { class: "label", text: "Provider" }),
        select,
        el("span", { class: "error", "data-error-for": `provider-${key}` }),
      ]),
    );
    card.appendChild(el("div", { class: "stage-fields", id: `fields-${key}` }));
    renderStageFields(key, {});
  }
}

function renderStageFields(stage, values) {
  const providerName = $(`provider-${stage}`).value;
  const provider = state.catalogue[stage].find((p) => p.name === providerName);
  const host = $(`fields-${stage}`);
  host.replaceChildren();
  if (!provider) return;

  if (!provider.available) {
    host.appendChild(
      el("p", {
        class: "unavailable",
        text: `Set ${provider.credential} in .env to use this provider.`,
      }),
    );
  }

  for (const field of provider.fields) {
    const id = fieldId(stage, field.name);
    const current = values[field.name] ?? field.default ?? "";

    let input;
    if (field.choices) {
      input = el("select", { id });
      for (const choice of field.choices) {
        input.appendChild(el("option", { value: choice, text: choice }));
      }
      input.value = current;
    } else if (field.type === "float" || field.type === "int") {
      input = el("input", {
        id,
        type: "number",
        step: field.type === "float" ? "0.1" : "1",
        value: current,
      });
    } else {
      input = el("input", { id, type: "text", value: current });
    }
    input.dataset.stage = stage;
    input.dataset.field = field.name;
    input.dataset.ftype = field.type;

    host.appendChild(
      el("label", { class: "field" }, [
        el("span", { class: "label" }, [
          document.createTextNode(field.name),
          ...(field.required
            ? [el("span", { class: "req", text: " required" })]
            : []),
        ]),
        input,
        ...(field.description
          ? [el("span", { class: "hint", text: field.description })]
          : []),
        el("span", { class: "error", "data-error-for": id }),
      ]),
    );
  }
}

function renderConfigList(configs) {
  const list = $("config-list");
  list.replaceChildren();
  if (configs.length === 0) {
    list.appendChild(el("li", { class: "empty", text: "Nothing saved yet." }));
    return;
  }
  for (const config of configs) {
    const button = el("button", {
      type: "button",
      class: config.id === state.selectedId ? "selected" : "",
    }, [
      el("span", { class: "cfg-name", text: config.name }),
      el("span", {
        class: "cfg-meta",
        text: `${config.id.slice(config.name.length + 1)} · ${config.llm}/${config.tts}`,
      }),
    ]);
    button.addEventListener("click", () => loadConfig(config.id));
    list.appendChild(el("li", {}, [button]));
  }
}

/* ---------- form <-> config ---------- */

function collectConfig() {
  const config = {
    version: 1,
    name: $("field-name").value.trim(),
    prompt: {
      instructions: $("field-prompt-instructions").value,
      greeting: $("field-prompt-greeting").value,
    },
    tools: [],
  };

  for (const { key } of STAGES) {
    const stage = { provider: $(`provider-${key}`).value };
    for (const input of $(`fields-${key}`).querySelectorAll("[data-field]")) {
      const raw = input.value;
      if (input.dataset.ftype === "float" || input.dataset.ftype === "int") {
        // Send the raw string when it is not a number, so the backend — not the
        // browser — decides what counts as invalid and reports it consistently.
        stage[input.dataset.field] = raw === "" || isNaN(Number(raw))
          ? raw
          : Number(raw);
      } else {
        stage[input.dataset.field] = raw;
      }
    }
    config[key] = stage;
  }
  return config;
}

function fillForm(config) {
  $("field-name").value = config.name ?? "";
  $("field-prompt-instructions").value = config.prompt?.instructions ?? "";
  $("field-prompt-greeting").value = config.prompt?.greeting ?? "";

  for (const { key } of STAGES) {
    const stage = config[key] ?? {};
    const { provider, ...values } = stage;
    const select = $(`provider-${key}`);
    if (provider) select.value = provider;
    renderStageFields(key, values);
  }
}

function blankConfig() {
  return {
    name: "",
    prompt: { instructions: "", greeting: "" },
    stt: {},
    llm: {},
    tts: {},
    vad: {},
  };
}

/* ---------- errors ---------- */

function clearErrors() {
  for (const node of document.querySelectorAll(".error")) {
    node.textContent = "";
    node.classList.remove("show");
  }
  for (const node of document.querySelectorAll(".field.invalid")) {
    node.classList.remove("invalid");
  }
  $("banner").hidden = true;
  $("banner").className = "banner";
}

function targetIdFor(loc) {
  if (loc.length === 1) return loc[0] === "name" ? "field-name" : null;
  const [head, tail] = loc;
  if (head === "prompt") return `field-prompt-${tail}`;
  if (tail === "provider") return `provider-${head}`;
  return fieldId(head, tail);
}

function showErrors(errors) {
  clearErrors();
  const orphans = [];

  for (const { loc, msg } of errors) {
    const id = targetIdFor(loc);
    const slot = id && document.querySelector(`[data-error-for="${id}"]`);
    if (slot) {
      slot.textContent = msg;
      slot.classList.add("show");
      slot.closest(".field")?.classList.add("invalid");
    } else {
      orphans.push(`${loc.join(".") || "config"}: ${msg}`);
    }
  }

  const banner = $("banner");
  banner.className = "banner error";
  banner.hidden = false;
  banner.replaceChildren(
    el("strong", { text: `${errors.length} problem${errors.length === 1 ? "" : "s"} to fix` }),
    ...(orphans.length
      ? [el("ul", {}, orphans.map((t) => el("li", { text: t })))]
      : []),
  );
}

function showSuccess(message) {
  clearErrors();
  const banner = $("banner");
  banner.className = "banner success";
  banner.hidden = false;
  banner.textContent = message;
}

/* ---------- actions ---------- */

async function loadConfig(id) {
  const { ok, body } = await api(`/api/configs/${encodeURIComponent(id)}`);
  if (!ok) {
    showErrors([{ loc: [], msg: `could not load ${id}` }]);
    return;
  }
  state.selectedId = id;
  fillForm(body);
  clearErrors();
  updateCredsNote(body.missing_credentials ?? []);
  refreshRunButton();
  await refreshList();
}

async function refreshList() {
  const { ok, body } = await api("/api/configs");
  if (ok) renderConfigList(body);
}

function updateCredsNote(missing) {
  $("creds-note").textContent = missing.length
    ? `Missing credentials: ${missing.join(", ")}`
    : "";
}

/* Run needs a *saved* config — the backend hands the worker a config by id, so
 * unsaved form edits have nothing to reference. */
function refreshRunButton() {
  $("run").disabled = !state.selectedId || state.room !== null;
  $("run").title = state.selectedId
    ? "Start a call with the selected config"
    : "Save a config first, or pick one from the list.";
}

async function save(event) {
  event.preventDefault();
  const button = $("save");
  button.disabled = true;
  try {
    const { ok, status, body } = await api("/api/configs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectConfig()),
    });

    if (ok) {
      state.selectedId = body.id;
      showSuccess(`Saved as ${body.id}.json`);
      updateCredsNote(body.missing_credentials ?? []);
      refreshRunButton();
      await refreshList();
    } else if (status === 422 || status === 400) {
      showErrors(body?.errors ?? [{ loc: [], msg: "validation failed" }]);
    } else {
      showErrors([{ loc: [], msg: `server returned ${status}` }]);
    }
  } finally {
    button.disabled = false;
  }
}

/* ---------- the call ---------- */

function setCallStatus(text, kind = "") {
  const node = $("call-status");
  node.textContent = text;
  node.className = `call-status ${kind}`;
}

function setCallControls(inCall) {
  $("mute").disabled = !inCall;
  $("hangup").disabled = !inCall;
}

function transcriptLine(speaker) {
  const li = el("li", { class: speaker === "agent" ? "agent interim" : "interim" }, [
    el("span", { class: "who", text: speaker === "agent" ? "Agent" : "You" }),
    el("span", { class: "what" }),
  ]);
  $("transcript-empty").hidden = true;
  $("transcript").appendChild(li);
  return li;
}

function scrollTranscript() {
  const list = $("transcript");
  list.scrollTop = list.scrollHeight;
}

/* Agent and user speech both arrive as text streams on `lk.transcription`.
 * Each stream is one utterance: chunks land as they are recognised, and the
 * stream closes when that utterance is final. */
function attachTranscription(room) {
  room.registerTextStreamHandler("lk.transcription", async (reader, participant) => {
    const identity = participant?.identity ?? reader.info?.attributes?.identity;
    const isLocal = identity === room.localParticipant.identity;
    const line = transcriptLine(isLocal ? "you" : "agent");
    const body = line.querySelector(".what");

    let text = "";
    try {
      for await (const chunk of reader) {
        text += chunk;
        body.textContent = text;
        scrollTranscript();
      }
    } catch (err) {
      console.error("transcription stream failed", err);
    }

    if (text.trim() === "") {
      line.remove();
      return;
    }
    line.classList.remove("interim");
    body.textContent = text;
    scrollTranscript();
  });
}

/* ---------- after-call artifacts ---------- */

/* The worker writes the call record on shutdown, which happens a moment after the
 * browser disconnects — so the record does not exist yet when we ask for it.
 * Poll until it lands rather than guessing at a fixed delay. */
const LOG_POLL_INTERVAL_MS = 700;
const LOG_POLL_TIMEOUT_MS = 20000;

function resetArtifacts() {
  $("artifacts").hidden = true;
  $("artifacts-pending").hidden = false;
  $("artifacts-ready").hidden = true;
  $("artifacts-failed").hidden = true;
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function renderArtifacts(record) {
  const stats = [
    ["duration", fmtDuration(record.duration_seconds)],
    ["turns", `${record.user_turns}/${record.agent_turns}`],
    ["tokens", (record.totals?.tokens?.total_tokens ?? 0).toLocaleString()],
    ["tool calls", (record.tools ?? []).reduce((n, t) => n + t.calls, 0)],
  ];
  $("artifacts-stats").replaceChildren(
    ...stats.map(([label, value]) =>
      el("div", {}, [el("dt", { text: label }), el("dd", { text: String(value) })]),
    ),
  );
  // A separate page, opened in a new tab — the call panel stays where it is.
  $("view-logs").href = `/logs.html?call=${encodeURIComponent(record.call_id)}`;
  $("artifacts-pending").hidden = true;
  $("artifacts-ready").hidden = false;
}

async function waitForCallRecord(callId) {
  $("artifacts").hidden = false;
  $("artifacts-pending").hidden = false;
  $("artifacts-ready").hidden = true;
  $("artifacts-failed").hidden = true;

  const deadline = Date.now() + LOG_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const { ok, body } = await api(`/api/calls/${encodeURIComponent(callId)}`);
    if (ok && body) {
      renderArtifacts(body);
      return;
    }
    await new Promise((r) => setTimeout(r, LOG_POLL_INTERVAL_MS));
  }

  $("artifacts-pending").hidden = true;
  $("artifacts-failed").hidden = false;
  $("artifacts-failed").textContent =
    "No log was written for this call. Check the worker output.";
}

async function startCall() {
  if (!state.selectedId) {
    showErrors([{ loc: [], msg: "save this config first, then hit Run" }]);
    return;
  }

  $("run").disabled = true;
  $("transcript").replaceChildren();
  $("transcript-empty").hidden = false;
  $("call-note").textContent = "";
  resetArtifacts();
  setCallStatus("connecting…");

  const { ok, status, body } = await api("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config_id: state.selectedId }),
  });

  if (!ok) {
    setCallStatus("failed", "error");
    $("call-note").textContent = body?.detail ?? `server returned ${status}`;
    // The config was deleted while this page had it selected. Drop the stale
    // selection and reload the list so the sidebar stops offering it.
    if (status === 404) {
      state.selectedId = null;
      $("call-note").textContent =
        "That config no longer exists — it was deleted. Pick another from the list.";
      await refreshList();
    }
    refreshRunButton();
    return;
  }

  state.callId = body.room;
  const room = new LivekitClient.Room({ adaptiveStream: true, dynacast: true });
  state.room = room;

  room.on(LivekitClient.RoomEvent.Disconnected, () => endCall("disconnected"));
  room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
    // The agent's voice. Attaching creates an <audio> element that plays it.
    if (track.kind === LivekitClient.Track.Kind.Audio) {
      track.attach();
    }
  });
  attachTranscription(room);

  try {
    await room.connect(body.url, body.token);
    await room.localParticipant.setMicrophoneEnabled(true);
    state.muted = false;
    $("mute").textContent = "Mute";
    setCallControls(true);
    setCallStatus(`live · ${body.config_name}`, "live");
    $("call-note").textContent = `room ${body.room}`;
  } catch (err) {
    console.error(err);
    setCallStatus("failed", "error");
    $("call-note").textContent =
      `${err.message} — is the worker running? (make worker)`;
    endCall("failed");
  }
}

async function endCall(reason) {
  const room = state.room;
  state.room = null;
  if (room) {
    try {
      await room.disconnect();
    } catch {
      /* already gone */
    }
  }
  setCallControls(false);
  refreshRunButton();
  if (reason === "disconnected") {
    setCallStatus("ended");
  }
  // Only a call that actually connected leaves a record behind.
  if (room && state.callId) {
    const callId = state.callId;
    state.callId = null;
    waitForCallRecord(callId);
  }
}

function toggleMute() {
  if (!state.room) return;
  state.muted = !state.muted;
  state.room.localParticipant.setMicrophoneEnabled(!state.muted);
  $("mute").textContent = state.muted ? "Unmute" : "Mute";
  setCallStatus(state.muted ? "live · muted" : "live", "live");
}

function newConfig() {
  state.selectedId = null;
  fillForm(blankConfig());
  clearErrors();
  updateCredsNote([]);
  refreshRunButton();
  renderConfigList([]);
  refreshList();
  $("field-name").focus();
}

/* ---------- boot ---------- */

async function main() {
  const health = await api("/api/health");
  $("health").textContent = health.ok
    ? `configs in ${health.body.configs}/`
    : "backend unreachable";

  const providers = await api("/api/providers");
  if (!providers.ok) {
    showErrors([{ loc: [], msg: "could not load the provider catalogue" }]);
    return;
  }
  state.catalogue = providers.body;

  renderStages();
  await refreshList();

  $("config-form").addEventListener("submit", save);
  $("new-config").addEventListener("click", newConfig);
  $("run").addEventListener("click", startCall);
  $("mute").addEventListener("click", toggleMute);
  $("hangup").addEventListener("click", () => endCall("disconnected"));
  refreshRunButton();
  setCallControls(false);
}

main();
