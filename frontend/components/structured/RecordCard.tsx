import type { ReactNode } from "react";
import styles from "./RecordCard.module.css";

export function RecordCard({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <li className={styles.card}>
      {title && <p className={styles.title}>{title}</p>}
      {children}
    </li>
  );
}
