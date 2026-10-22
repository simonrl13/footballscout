// Pure functions for the demo page (no globals: the document is passed in, so node --test can run them).
// Model output is only ever put into the page as text nodes; the only elements built from it are p, ul, li, strong.

export const MIN_LEN = 3;
export const MAX_LEN = 500;
export const WAKE_MS = 5000;
export const WAKE_TEXT = "Waking up the demo, the first answer can take about 20 s.";
export const TOOL_LABELS = {
  search_players: "Searching players…",
  get_player: "Looking up the player…",
  predict_value_change: "Reading the model's forecast…",
  compare_players: "Comparing players…",
  search_text: "Searching Wikipedia…",
};

// Calls onWake after WAKE_MS without an event; restart() on every event, stop() when the answer is complete
export function wakeWatch(onWake, ms = WAKE_MS) {
  let timer = null;
  return {
    restart() { clearTimeout(timer); timer = setTimeout(onWake, ms); },
    stop() { clearTimeout(timer); },
  };
}

// null if the question can be sent, else why not (the API enforces the same 3–500 characters)
export function questionProblem(question) {
  if (question.trim().length < MIN_LEN) return `Questions need at least ${MIN_LEN} characters.`;
  if (question.length > MAX_LEN) return `Questions can be at most ${MAX_LEN} characters.`;
  return null;
}

// Server-sent events arrive in arbitrary chunks: buffer until a blank line, then hand over each event's data
export function sseParser(onEvent) {
  let buffer = "";
  return (chunk) => {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
      if (data) onEvent(JSON.parse(data));
    }
  };
}

// A source link is built only from the structured `sources` field and only to a Wikipedia language or mobile
// subdomain over https (en.wikipedia.org, en.m.wikipedia.org). The bare wikipedia.org is rejected: it hosts only the
// portal, never a revision, and requiring a subdomain keeps the rule a plain suffix check. Anything else: no link.
export function safeSourceUrl(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  if (!url.hostname.endsWith(".wikipedia.org")) return null;
  return url.href;
}

// **bold** becomes strong; everything else stays text
function appendInline(doc, parent, line) {
  line.split(/\*\*(.+?)\*\*/).forEach((part, i) => {
    if (!part) return;
    if (i % 2) {
      const strong = doc.createElement("strong");
      strong.appendChild(doc.createTextNode(part));
      parent.appendChild(strong);
    } else {
      parent.appendChild(doc.createTextNode(part));
    }
  });
}

// The answer body as paragraphs and bullet lists. Never parses HTML: "<b>" in an answer stays the text "<b>".
export function renderBody(doc, container, body) {
  let list = null;
  for (const raw of body.split("\n")) {
    const line = raw.trim();
    if (!line) {
      list = null;
      continue;
    }
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      if (!list) list = container.appendChild(doc.createElement("ul"));
      appendInline(doc, list.appendChild(doc.createElement("li")), bullet[1]);
    } else {
      list = null;
      appendInline(doc, container.appendChild(doc.createElement("p")), line.replace(/^#+\s*/, ""));
    }
  }
}

// Sources from structured fields: "[wiki n] Player, Wikipedia revision of DATE · page history"
export function renderSources(doc, container, sources) {
  const list = doc.createElement("ul");
  for (const src of sources) {
    const item = list.appendChild(doc.createElement("li"));
    item.appendChild(doc.createTextNode(`[wiki ${Number(src.ref)}] `));
    appendLink(doc, item, src.revision_url, `${src.player}, Wikipedia revision of ${src.revision_date}`);
    item.appendChild(doc.createTextNode(" · "));
    appendLink(doc, item, src.history_url, "page history (authors)");
  }
  container.appendChild(list);
}

function appendLink(doc, parent, rawUrl, label) {
  const href = safeSourceUrl(rawUrl);
  if (!href) {
    parent.appendChild(doc.createTextNode(label));
    return;
  }
  const a = doc.createElement("a");
  a.setAttribute("href", href);
  a.setAttribute("rel", "noopener noreferrer");
  a.appendChild(doc.createTextNode(label));
  parent.appendChild(a);
}

// HTTP 429: the limits in plain words, and when to retry (Retry-After in seconds)
export function limitMessage(retryAfter, now = new Date()) {
  const seconds = Math.max(1, Number.parseInt(retryAfter, 10) || 60);
  const rule = "The demo allows 5 questions a minute and 20 a day per connection.";
  if (seconds <= 120) return `${rule} Please try again in ${seconds} seconds.`;
  const at = new Date(now.getTime() + seconds * 1000);
  const local = at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${rule} Today's questions are used up; they reset at midnight UTC (${local} your time).`;
}
