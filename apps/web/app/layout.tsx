import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "JAAFFL — The Draft Room",
  description:
    "CBS Fantasy Football live-draft assistant — the transparent recommendation, decomposed.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // Theme: the design tokens default to the viewer's system preference via
  // @media (prefers-color-scheme) — no flash for system-preference users, and no inline
  // script needed. An explicit override (data-theme) is restored client-side by ThemeToggle.
  // suppressHydrationWarning because that attribute is set on <html> after hydration.
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
