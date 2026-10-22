// Demo page logic, with node's built-in test runner (no dependencies): node --test tests/js/
import assert from "node:assert/strict";
import { mock, test } from "node:test";

import {
  MAX_LEN, WAKE_MS, WAKE_TEXT, limitMessage, questionProblem, renderBody, renderSources, safeSourceUrl, sseParser,
  wakeWatch,
} from "../../scout/api/static/render.mjs";

// A minimal document: elements record their tag, attributes and children; text nodes hold raw strings.
// If anything parsed HTML, a tag outside the expected ones would appear in the tree.
function fakeDocument() {
  const element = (tag) => ({
    tag, attrs: {}, children: [],
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(name, value) { this.attrs[name] = value; },
  });
  return { createElement: element, createTextNode: (text) => ({ text }) };
}

function tags(node, out = new Set()) {
  if (node.tag) out.add(node.tag);
  for (const child of node.children ?? []) tags(child, out);
  return out;
}

function text(node) {
  return node.text ?? (node.children ?? []).map(text).join("");
}

test("answers render as text: HTML in an answer is never turned into elements", () => {
  const doc = fakeDocument();
  const root = doc.createElement("div");
  const evil = '<img src=x onerror="alert(1)"> <script>alert(2)</script> **<a href="javascript:x">bold</a>**';
  renderBody(doc, root, `Intro ${evil}\n\n- item <b>one</b>\n- **two**\n\n### Heading`);
  assert.deepEqual([...tags(root)].sort(), ["div", "li", "p", "strong", "ul"]);
  assert.ok(text(root).includes('<img src=x onerror="alert(1)">'));
  assert.ok(text(root).includes("<script>alert(2)</script>"));
  assert.ok(text(root).includes("<b>one</b>"));
});

test("bullets and bold use only p, ul, li and strong", () => {
  const doc = fakeDocument();
  const root = doc.createElement("div");
  renderBody(doc, root, "The model forecasts **-18.6%**.\n\n- Value: EUR 100.0m\n- Age: 23.1");
  const [p, ul] = root.children;
  assert.equal(p.tag, "p");
  assert.equal(p.children[1].tag, "strong");
  assert.equal(text(p.children[1]), "-18.6%");
  assert.equal(ul.tag, "ul");
  assert.deepEqual(ul.children.map(text), ["Value: EUR 100.0m", "Age: 23.1"]);
});

test("source links: only https Wikipedia language or mobile subdomains", () => {
  for (const ok of ["https://en.wikipedia.org/w/index.php?oldid=1358782593",
                    "https://en.wikipedia.org/w/index.php?title=Jude+Bellingham&action=history",
                    "https://en.m.wikipedia.org/w/index.php?oldid=1", "https://EN.Wikipedia.org/wiki/X"]) {
    assert.ok(safeSourceUrl(ok), ok);
  }
  for (const bad of ["https://wikipedia.org/wiki/X",  // bare domain: the portal only, never a revision (rejected)
                     "javascript:alert(1)", "data:text/html,<b>x</b>", "http://en.wikipedia.org/wiki/X",
                     "https://evil.com/wiki/X", "https://wikipedia.org.evil.com/x", "https://en.wikipedia.org@evil.com/x",
                     "https://user:pw@en.wikipedia.org/x", "https://evil.com/?u=https://en.wikipedia.org",
                     "//en.wikipedia.org/wiki/X", "https://en.wikipedia.org:8443/x", "https://enwikipedia.org/x",
                     "https://en.wikipedia.org.", "", null, undefined]) {
    assert.equal(safeSourceUrl(bad), null, String(bad));
  }
});

test("a rejected source URL renders as plain text, a good one as a link", () => {
  const doc = fakeDocument();
  const root = doc.createElement("div");
  renderSources(doc, root, [
    { ref: 1, player: "Jude Bellingham", revision_date: "2026-06-10",
      revision_url: "https://en.wikipedia.org/w/index.php?oldid=1358782593",
      history_url: "javascript:alert(1)" },
  ]);
  const links = [];
  (function walk(n) { if (n.tag === "a") links.push(n); (n.children ?? []).forEach(walk); })(root);
  assert.equal(links.length, 1);
  assert.equal(links[0].attrs.href, "https://en.wikipedia.org/w/index.php?oldid=1358782593");
  assert.equal(links[0].attrs.rel, "noopener noreferrer");
  assert.ok(text(root).includes("page history (authors)"));  // shown, but not linked
});

test("questions outside 3–500 characters are not sent", () => {
  assert.ok(questionProblem(""));
  assert.ok(questionProblem("  a "));
  assert.ok(questionProblem("x".repeat(MAX_LEN + 1)));
  assert.equal(questionProblem("Who?"), null);
  assert.equal(questionProblem("x".repeat(MAX_LEN)), null);
});

test("server-sent events split across chunks still parse", () => {
  const events = [];
  const feed = sseParser((e) => events.push(e));
  feed('data: {"type": "tool_call", "na');
  feed('me": "search_players"}\n\ndata: {"type": "answer", "body": "a\\n\\nb"}\n');
  assert.equal(events.length, 1);
  feed("\n");
  assert.deepEqual(events.map((e) => e.type), ["tool_call", "answer"]);
  assert.equal(events[1].body, "a\n\nb");
});

test("the waking notice appears after 5 s without an event and the timer restarts on each event", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let shown = "";
    const wake = wakeWatch(() => { shown = WAKE_TEXT; });  // the page's own timer (app.mjs uses the same helper)
    wake.restart();
    mock.timers.tick(WAKE_MS - 1);
    wake.restart();  // an event arrived
    mock.timers.tick(WAKE_MS - 1);
    assert.equal(shown, "");
    mock.timers.tick(1);
    assert.equal(shown, "Waking up the demo, the first answer can take about 20 s.");
    shown = "";
    wake.restart();
    wake.stop();  // the answer completed
    mock.timers.tick(WAKE_MS * 2);
    assert.equal(shown, "");
  } finally {
    mock.timers.reset();
  }
});

test("429 messages explain the limits and when to retry", () => {
  assert.match(limitMessage("42"), /5 questions a minute and 20 a day.*try again in 42 seconds/);
  assert.match(limitMessage("3600", new Date("2026-10-22T23:00:00Z")), /reset at midnight UTC/);
  assert.match(limitMessage(null), /60 seconds/);
});
