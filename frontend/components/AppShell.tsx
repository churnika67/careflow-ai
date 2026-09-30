import type { ReactNode } from "react";
import { SystemStatusProvider } from "./SystemStatusProvider";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import styles from "./AppShell.module.css";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SystemStatusProvider>
      <div className={styles.shell}>
        <div className="ambient-glow" aria-hidden="true" />
        <Sidebar />
        <div className={styles.column}>
          <Header />
          <main className={styles.main}>{children}</main>
        </div>
      </div>
    </SystemStatusProvider>
  );
}
