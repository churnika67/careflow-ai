import type { ReactNode } from "react";
import styles from "./SyntheticDataNotice.module.css";

export function SyntheticDataNotice({ children }: { children: ReactNode }) {
  return <p className={styles.notice}>{children}</p>;
}
