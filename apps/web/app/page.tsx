import { API_BASE } from "@/lib/api";

export default function Home() {
  return (
    <main className="wrap">
      <h1>JAAFFL</h1>
      <p>CBS Fantasy Football Live Draft Assistant — dashboard.</p>
      <p className="muted">
        Companion API: <code>{API_BASE}</code>
      </p>
      <ol>
        <li>Draft board &amp; pick log</li>
        <li>Projection distributions</li>
        <li>Manager tendencies</li>
        <li>Scenario comparison</li>
      </ol>
      <p className="muted">
        Panels populate once the data tiers (stage 4) and engine (stage 5) are wired.
      </p>
    </main>
  );
}
