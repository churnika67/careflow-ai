"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./Sidebar.module.css";

interface NavItem {
  label: string;
  href?: string;
}

// Ask CareFlow (Slice 2), Patient Data/Claims (Slice 3), CareFlow
// Assistant (Slice 4), Evidence Workflow (Slice 5), and Reviews (Slice 6)
// are functional. Analytics remains visibly present but clearly inactive
// (no href, aria-disabled, a "Coming soon" note) -- never a fake
// functional screen.
const NAV_ITEMS: NavItem[] = [
  { label: "System Overview", href: "/" },
  { label: "Ask CareFlow", href: "/ask" },
  { label: "Patient Data", href: "/patient-data" },
  { label: "Claims", href: "/claims" },
  { label: "CareFlow Assistant", href: "/assistant" },
  { label: "Evidence Workflow", href: "/workflow" },
  { label: "Reviews", href: "/reviews" },
  { label: "Analytics" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className={styles.sidebar} aria-label="Primary">
      <ul>
        {NAV_ITEMS.map((item) => {
          if (!item.href) {
            return (
              <li key={item.label}>
                <span className={styles.disabledLink} aria-disabled="true">
                  <span>{item.label}</span>
                  <span className={styles.comingSoon}>Coming soon</span>
                </span>
              </li>
            );
          }
          // Exact match for a leaf route; prefix match for a route with
          // its own sub-pages (e.g. /reviews/[reviewId] should still
          // highlight "Reviews") -- "/" is deliberately never treated as
          // a prefix, or every route would match it.
          const isCurrent =
            pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`));
          return (
            <li key={item.label}>
              <Link
                href={item.href}
                className={isCurrent ? styles.activeLink : styles.inactiveLink}
                aria-current={isCurrent ? "page" : undefined}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
