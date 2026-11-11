import { notFound } from "next/navigation";

/** Any address that is not a page: the styled 404 (not-found.tsx), in the visitor's language. */
export default function Unknown() {
  notFound();
}
