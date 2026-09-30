"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getReviewQueue } from "@/lib/api/reviewsApi";
import styles from "./Sidebar.module.css";

export interface NavItem {
  label: string;
  href: string;
  icon: string;
}

// Ask CareFlow (Slice 2), Patient Data/Claims (Slice 3), CareFlow
// Assistant (Slice 4), Evidence Workflow (Slice 5), Reviews (Slice 6), and
// Analytics (Phase 15 Slice 1 -- a foundation shell, not yet the full
// dashboard) are all functional. Every nav item now links somewhere real;
// there is no remaining disabled/"Coming soon" placeholder link.
export const NAV_ITEMS: NavItem[] = [
  { label: "System Overview", href: "/", icon: "grid" },
  { label: "Ask CareFlow", href: "/ask", icon: "message" },
  { label: "Patient Data", href: "/patient-data", icon: "user" },
  { label: "Claims", href: "/claims", icon: "file" },
  { label: "CareFlow Assistant", href: "/assistant", icon: "spark" },
  { label: "Evidence Workflow", href: "/workflow", icon: "flow" },
  { label: "Reviews", href: "/reviews", icon: "check" },
  { label: "Analytics", href: "/analytics", icon: "chart" },
];

const ICON_PATHS: Record<string, string> = {
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  message: "M4 5h16v11H8l-4 4z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  file: "M6 3h9l5 5v13H6zM14 3v6h6",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18",
  flow: "M5 6h5v5H5zM14 6h5v5h-5zM9.5 8.5H14M9.5 8.5v8M9.5 16.5h9.5v-5",
  check: "M5 12.5 10 17l9-10",
  chart: "M5 19V9M12 19V5M19 19v-7",
};

function NavIcon({ name }: { name: string }) {
  return (
    <svg
      className={styles.icon}
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

// Fetched once on mount, best-effort: a real live count of currently
// pending reviews (capped by `limit`), not a fabricated number. A failed
// fetch just leaves the badge hidden rather than showing a stale/fake
// count.
function usePendingReviewCount(): number | null {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    getReviewQueue({ status: "pending", limit: 50 }, controller.signal).then((outcome) => {
      if (cancelled || outcome.kind !== "ok") return;
      setCount(outcome.page.reviews.length);
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  return count;
}

export function Sidebar() {
  const pathname = usePathname();
  const pendingReviewCount = usePendingReviewCount();

  return (
    <nav className={styles.sidebar} aria-label="Primary">
      <Link href="/" className={styles.brand}>
        <span className={styles.logo} aria-hidden="true">
          C
        </span>
        <div>
          <p className={styles.brandTitle}>CareFlow AI</p>
          <p className={styles.brandSubtitle}>Healthcare Intelligence</p>
        </div>
      </Link>

      <ul className={styles.navList}>
        {NAV_ITEMS.map((item) => {
          // Exact match for a leaf route; prefix match for a route with
          // its own sub-pages (e.g. /reviews/[reviewId] should still
          // highlight "Reviews") -- "/" is deliberately never treated as
          // a prefix, or every route would match it.
          const isCurrent =
            pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`));
          const showBadge = item.href === "/reviews" && !!pendingReviewCount && pendingReviewCount > 0;
          return (
            <li key={item.label}>
              <Link
                href={item.href}
                className={isCurrent ? styles.activeLink : styles.inactiveLink}
                aria-current={isCurrent ? "page" : undefined}
              >
                <NavIcon name={item.icon} />
                <span className={styles.navLabel}>{item.label}</span>
                {showBadge && (
                  <span className={styles.navBadge} aria-label={`${pendingReviewCount} pending`}>
                    {pendingReviewCount > 9 ? "9+" : pendingReviewCount}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
