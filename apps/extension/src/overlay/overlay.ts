// Thin in-page overlay: best pick / next-turn risk / why. Rendered inside a shadow root so
// CBS's page styles can't leak in (and vice versa).

export function mountOverlay(): void {
  if (document.getElementById("jaaffl-overlay")) return;

  const host = document.createElement("div");
  host.id = "jaaffl-overlay";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      .panel {
        position: fixed; top: 88px; right: 16px; width: 300px; z-index: 2147483647;
        font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
        border-radius: 12px; padding: 14px 16px; box-shadow: 0 8px 30px rgba(0,0,0,.35);
      }
      h1 { font-size: 13px; margin: 0 0 6px; letter-spacing: .04em;
        text-transform: uppercase; color: #94a3b8; }
      .rec { font-size: 18px; font-weight: 700; }
      .muted { font-size: 12px; color: #94a3b8; margin-top: 8px; }
    </style>
    <div class="panel">
      <h1>JAAFFL</h1>
      <div class="rec">Waiting for draft…</div>
      <div class="muted">Recommendations appear here once the engine is wired (stage 5).</div>
    </div>`;

  document.body.appendChild(host);
}
