import { offline } from "@/lib/server/guard";
import { Offline, socketToken, socketUrl } from "@/lib/server/session";

/**
 * A short-lived access token (15 minutes) and the address of the chat's live channel.
 * The page keeps the token in memory only and sends it as the socket's first message.
 * Only a page of this site can read the answer (no CORS headers are sent).
 */
export async function GET(request: Request) {
  if (request.headers.get("x-oa-request") !== "1") {
    return Response.json({ detail: "Cross-site request refused" }, { status: 403 });
  }
  try {
    const token = await socketToken();
    if (!token) return Response.json({ detail: "Not signed in" }, { status: 401 });
    return Response.json({ token, url: socketUrl() }, { headers: { "cache-control": "no-store" } });
  } catch (error) {
    if (error instanceof Offline) return offline();
    throw error;
  }
}
