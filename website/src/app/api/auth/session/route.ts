import { offline } from "@/lib/server/guard";
import { apiFetch, Offline } from "@/lib/server/session";

/** The signed-in user and company (or 401). Refreshes the session when needed. */
export async function GET() {
  try {
    const response = await apiFetch("/auth/me");
    return new Response(await response.text(), { status: response.status, headers: { "content-type": "application/json" } });
  } catch (error) {
    if (error instanceof Offline) return offline();
    throw error;
  }
}
