import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Next's router hooks, for components rendered outside Next
export const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
export const search = { params: new URLSearchParams() };

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => search.params,
  usePathname: () => "/en",
  useParams: () => ({ lang: "en" }),
}));

afterEach(() => {
  cleanup();
  search.params = new URLSearchParams();
  router.push.mockReset();
  router.refresh.mockReset();
});
