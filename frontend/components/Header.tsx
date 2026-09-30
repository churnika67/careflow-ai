"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { StatusBadge, type BadgeState } from "./StatusBadge";
import { NAV_ITEMS } from "./Sidebar";
import type { SystemStatusState } from "@/lib/api/systemStatus";
import styles from "./Header.module.css";

const STATE_TO_BADGE: Record<SystemStatusState, { state: BadgeState; label: string }> = {
  checking: { state: "checking", label: "Checking system status…" },
  ready: { state: "ok", label: "Ready" },
  degraded: { state: "degraded", label: "Degraded" },
  unavailable: { state: "unavailable", label: "Unavailable" },
};

// Branding lives in the sidebar (Sidebar.tsx) now, not here -- this is a
// slim top bar for the content column only, carrying quick page search and
// system status.
export function Header() {
  const { status } = useSystemStatusContext();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const badge = STATE_TO_BADGE[status.state];

  // A real, working jump-to-page search -- matches nav item labels against
  // the typed text and navigates to the first match on submit. Not a
  // decorative placeholder: it does nothing it doesn't actually do.
  const match = query.trim().length > 0
    ? NAV_ITEMS.find((item) => item.label.toLowerCase().includes(query.trim().toLowerCase()))
    : null;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (match) {
      router.push(match.href);
      setQuery("");
    }
  }

  return (
    <header className={styles.header}>
      <form className={styles.searchForm} onSubmit={handleSubmit} role="search">
        <svg
          className={styles.searchIcon}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="search"
          className={styles.searchInput}
          placeholder="Search pages…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search CareFlow pages"
        />
        {match && (
          <span className={styles.searchHint}>
            Press Enter for <strong>{match.label}</strong>
          </span>
        )}
      </form>
      <div aria-live="polite">
        <StatusBadge state={badge.state} label={badge.label} />
      </div>
    </header>
  );
}
