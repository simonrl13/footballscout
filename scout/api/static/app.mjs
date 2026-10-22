// Demo page wiring: the question form, the /ask stream, the waking notice and the limit messages.
import {
  TOOL_LABELS, WAKE_TEXT, limitMessage, questionProblem, renderBody, renderSources, sseParser, wakeWatch,
} from "./render.mjs";

const form = document.getElementById("ask");
const input = document.getElementById("question");
const button = document.getElementById("send");
const counter = document.getElementById("count");
const status = document.getElementById("status");
const answer = document.getElementById("answer");
const asOf = document.getElementById("as-of");

function setStatus(text) {
  status.textContent = text;
}

const wake = wakeWatch(() => setStatus(WAKE_TEXT));

function showMessage(text, kind) {
  answer.replaceChildren();
  answer.className = `answer ${kind}`;
  const p = document.createElement("p");
  p.textContent = text;
  answer.appendChild(p);
  answer.hidden = false;
}

function showAnswer(event) {
  answer.replaceChildren();
  answer.className = "answer";
  const body = document.createElement("div");
  renderBody(document, body, event.body ?? event.text);
  answer.appendChild(body);
  if (event.sources?.length) {
    const heading = document.createElement("p");
    heading.className = "sources-title";
    heading.textContent = "Sources (Wikipedia, public text, not model output)";
    answer.appendChild(heading);
    renderSources(document, answer, event.sources);
    const license = document.createElement("p");
    license.className = "muted";
    license.textContent = "Wikipedia text is available under CC BY-SA 4.0.";
    answer.appendChild(license);
  }
  if (event.notice) {
    const notice = document.createElement("p");
    notice.className = "notice";
    notice.textContent = event.notice;
    answer.appendChild(notice);
  }
  answer.hidden = false;
}

function onEvent(event) {
  wake.restart();
  if (event.type === "tool_call") setStatus(TOOL_LABELS[event.name] ?? "Working…");
  else if (event.type === "tool_error") setStatus("Retrying a lookup…");
  else if (event.type === "answer") showAnswer(event);
  else if (event.type === "refused" || event.type === "blocked") showMessage(event.text, "declined");
}

async function ask(question) {
  button.disabled = true;
  answer.hidden = true;
  setStatus("Sending…");
  wake.restart();
  try {
    const response = await fetch("/ask", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question }),
    });
    if (response.status === 429) return showMessage(limitMessage(response.headers.get("Retry-After")), "error");
    if (response.status === 422) return showMessage("Questions need 3 to 500 characters.", "error");
    if (!response.ok || !response.body) return showMessage("Something went wrong. Please try again.", "error");
    const parse = sseParser(onEvent);
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      parse(value);
    }
  } catch {
    showMessage("The connection dropped. Please try again.", "error");
  } finally {
    wake.stop();
    setStatus("");
    button.disabled = false;
  }
}

function updateCount() {
  counter.textContent = `${input.value.length}/500`;
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const problem = questionProblem(input.value);
  if (problem) return showMessage(problem, "error");  // never sent: the API would answer 422
  ask(input.value.trim());
});

input.addEventListener("input", updateCount);

for (const example of document.querySelectorAll("[data-example]")) {
  example.addEventListener("click", () => {
    input.value = example.textContent;
    updateCount();
    input.focus();
  });
}

fetch("/meta")
  .then((r) => (r.ok ? r.json() : Promise.reject()))
  .then((meta) => { asOf.textContent = `Data as of ${meta.data_as_of}.`; })
  .catch(() => { asOf.textContent = ""; });
