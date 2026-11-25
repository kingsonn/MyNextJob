"""Customer desk and staff console markup. Role checks stay in the routes."""

from __future__ import annotations

_CUSTOMER_CSS = """
body { margin: 0; background: #f3efe6; color: #1c1917;
  font: 16px/1.45 "Segoe UI", sans-serif; }
a { color: #0f3d3e; }
.top { display: flex; justify-content: space-between; align-items: center;
  padding: 1rem 1.5rem; background: #142022; color: #f3efe6; }
.top a { color: #d7e4e2; }
.layout { display: grid; grid-template-columns: 1fr 18rem; gap: 1rem;
  max-width: 68rem; margin: 0 auto; padding: 1.25rem; }
.stage, .rail, .composer { background: #fffdf8; border: 1px solid #ddd4c4; }
.stage { min-height: 70vh; display: flex; flex-direction: column; }
#state { margin: 0; padding: 0.8rem 1rem; background: #0f3d3e; color: #f3efe6; }
#thread { flex: 1; padding: 1rem; }
.bubble { margin: 0.45rem 0; padding: 0.55rem 0.75rem; max-width: 36rem; }
.you { background: #efe7d8; }
.agent { background: #e5f0ef; }
.composer { display: flex; gap: 0.5rem; padding: 0.8rem; align-items: end; }
textarea { flex: 1; min-height: 4.5rem; border: 1px solid #cfc4b0; padding: 0.5rem; }
button { border: 0; background: #0f3d3e; color: #fff; padding: 0.7rem 1rem; cursor: pointer; }
button:disabled { background: #b7b1a6; }
#hangup { background: #7a2e2e; }
.rail { padding: 0.8rem 1rem; }
#steps { padding-left: 1.1rem; }
#vadlog { font: 12px/1.35 ui-monospace, monospace; max-height: 16rem;
  overflow: auto; white-space: pre-wrap; background: #f6f1e6; padding: 0.4rem; }
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; }
}
"""

_STAFF_CSS = """
body { margin: 0; background: #f6f4f1; color: #1c1917;
  font: 15px/1.45 "Segoe UI", sans-serif; }
a { color: #0f3d3e; }
.shell { display: grid; grid-template-columns: 14rem 1fr; min-height: 100vh; }
nav { background: #142022; color: #f3efe6; padding: 1.2rem 1rem; }
nav a { display: block; color: #d7e4e2; margin: 0.7rem 0; text-decoration: none; }
main { padding: 1.5rem 1.75rem; }
table { width: 100%; border-collapse: collapse; background: white; }
th, td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid #e4ddd2; }
form.stack { display: grid; gap: 0.45rem; max-width: 32rem; background: white;
  padding: 1rem; border: 1px solid #e4ddd2; }
input, button { padding: 0.45rem 0.55rem; }
button { background: #0f3d3e; color: white; border: 0; cursor: pointer; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.8rem; }
.card { background: white; border: 1px solid #e4ddd2; padding: 0.9rem; }
.card strong { display: block; font-size: 1.4rem; }
@media (max-width: 800px) {
  .shell { grid-template-columns: 1fr; }
  .cards { grid-template-columns: 1fr; }
}
"""

_DESK = """
<header class="top">
  <strong>ClaimPilot</strong>
  <a href="/admin">Staff desk</a>
</header>
<div class="layout">
  <section class="stage">
    <p id="state">Idle. Start a call, or type.</p>
    <div id="thread"></div>
    <div class="composer">
      <textarea id="said">what is the status of clm_000001</textarea>
      <button type="button" id="call">Start call</button>
      <button type="button" id="hangup" disabled>End call</button>
      <button type="button" id="send">Send text</button>
    </div>
  </section>
  <aside class="rail">
    <h2>This turn</h2>
    <p>The microphone stays open for the whole call. Steps stay here. Only the answer is spoken.</p>
    <ul id="steps"></ul>
    <h2>Listening</h2>
    <pre id="vadlog"></pre>
  </aside>
</div>
<script src="/voice/desk.js"></script>
"""


def customer_page() -> str:
    return _document("ClaimPilot", _CUSTOMER_CSS, _DESK)


def login_page() -> str:
    body = """
    <main>
      <h1>Staff desk</h1>
      <p>Operators sign in here. Customers stay on the other desk.</p>
      <p><a href="/">Customer desk</a></p>
      <form class="stack" method="post" action="/admin/login">
        <label>Staff token <input name="token" autocomplete="off"></label>
        <button>Open the console</button>
      </form>
      <p>Use the admin token from deploy/env.example.</p>
    </main>
    """
    return _document("Staff desk", _STAFF_CSS, body)


def staff_page(title: str, body: str) -> str:
    nav = """
    <nav>
      <strong>ClaimPilot</strong>
      <a href="/admin">Overview</a>
      <a href="/admin/claims">Claims</a>
      <a href="/admin/documents">Policies</a>
      <a href="/admin/traces">Traces</a>
      <a href="/admin/audit-log">Audit</a>
      <a href="/">Customer desk</a>
    </nav>
    """
    return _document(title, _STAFF_CSS, f'<div class="shell">{nav}<main>{body}</main></div>')


def _document(title: str, css: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{css}</style></head><body>{body}</body></html>"
    )
