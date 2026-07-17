"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

function current(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Dark/light toggle. The tokens default to the viewer's system preference via
 * @media (prefers-color-scheme), so system-preference users see no flash. An EXPLICIT override
 * (data-theme in localStorage) is restored client-side in the effect below — so a user who has
 * pinned a theme against their OS setting sees a brief flash to their override on load (we
 * deliberately avoid an inline pre-paint script). This flips + persists the data-theme attribute.
 */
export function ThemeToggle(): React.ReactElement {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    // Restore an explicit override saved from a previous visit, else follow the system theme.
    let saved: string | null = null;
    try {
      saved = localStorage.getItem("jaaffl-theme");
    } catch {
      /* private mode — ignore */
    }
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
    setTheme(current());
  }, []);

  const toggle = (): void => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("jaaffl-theme", next);
    } catch {
      /* private mode — ignore */
    }
    setTheme(next);
  };

  return (
    <button
      type="button"
      className="btn"
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
