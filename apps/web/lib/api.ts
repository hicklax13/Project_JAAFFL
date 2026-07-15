import type { Recommendation } from "@jaaffl/shared";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8787";

/** Fetch the current recommendation from the companion service (backend Stage 5). */
export async function fetchRecommendation(leagueId: string): Promise<Recommendation | null> {
  const res = await fetch(`${API_BASE}/recommendation?league_id=${encodeURIComponent(leagueId)}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as Recommendation;
}
