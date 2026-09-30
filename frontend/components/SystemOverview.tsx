"use client";

import { useSystemStatusContext } from "./SystemStatusProvider";
import { StatusBadge } from "./StatusBadge";
import styles from "./SystemOverview.module.css";

const DEPENDENCY_LABELS: Record<string, string> = {
  postgresql: "Postgres",
  qdrant: "Qdrant",
  redis: "Cache (Redis)",
};

// Redis backs an optional performance cache only -- CareFlow's own /ready
// endpoint never lets a Redis failure affect overall readiness (see
// lib/api/systemStatus.ts's module docstring), so this page says so
// explicitly rather than showing it as an equally load-bearing dependency
// next to Postgres/Qdrant.
const NON_AUTHORITATIVE_DEPENDENCIES = new Set(["redis"]);

export function SystemOverview() {
  const { status, refresh } = useSystemStatusContext();

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.heroContent}>
          <span className={styles.eyebrow}>Healthcare Intelligence Platform</span>
          <h1 className={styles.appName}>CareFlow AI</h1>
          <p className={styles.description}>
            Evidence-grounded healthcare information workflows that combine public
            Medicare coverage policy with synthetic patient and claims data — bounded
            orchestration, coordinated evidence retrieval, and a full human-review
            audit trail.
          </p>
        </div>

        <dl className={styles.stats} aria-label="Engineering metrics">
          <div className={styles.statCard}>
            <dt className={styles.statLabel}>Automated tests passing</dt>
            <dd className={styles.statNumber}>1,171</dd>
          </div>
          <div className={styles.statCard}>
            <dt className={styles.statLabel}>End-to-end browser journeys</dt>
            <dd className={styles.statNumber}>9</dd>
          </div>
          <div className={styles.statCard}>
            <dt className={styles.statLabel}>CI quality gates, every commit</dt>
            <dd className={styles.statNumber}>6</dd>
          </div>
          <div className={styles.statCard}>
            <dt className={styles.statLabel}>Real patient records used</dt>
            <dd className={styles.statNumber}>0</dd>
          </div>
        </dl>
      </section>

      <section className={styles.features} aria-label="Platform capabilities">
        <div className={styles.featureCard}>
          <span className={styles.featureIcon} aria-hidden="true">
            📄
          </span>
          <h3>Medicare Policy Retrieval</h3>
          <p>
            Evidence-grounded answers to Medicare coverage questions, cited directly
            to the source policy document.
          </p>
        </div>
        <div className={styles.featureCard}>
          <span className={styles.featureIcon} aria-hidden="true">
            🗂️
          </span>
          <h3>Synthetic Patient &amp; Claims Data</h3>
          <p>
            Structured lookups over synthetic Synthea FHIR records and CMS DE-SynPUF
            claims — never real patient data.
          </p>
        </div>
        <div className={styles.featureCard}>
          <span className={styles.featureIcon} aria-hidden="true">
            ✅
          </span>
          <h3>Human-in-the-Loop Review</h3>
          <p>
            Every flagged result routes through a reviewable queue with a full
            decision and audit trail.
          </p>
        </div>
      </section>

      <section className={styles.statusSection} aria-live="polite">
        <div className={styles.statusHeader}>
          <h2>System Status</h2>
          <button type="button" onClick={refresh} className={styles.refreshButton}>
            Refresh
          </button>
        </div>

        {status.state === "checking" && (
          <p className={styles.checkingText}>Checking system status…</p>
        )}

        {status.state === "unavailable" && (
          <div className={styles.unavailableNotice} role="alert">
            <p>CareFlow backend is currently unavailable.</p>
            {status.requestId && (
              <p className={styles.technicalDetail}>Request ID: {status.requestId}</p>
            )}
          </div>
        )}

        {(status.state === "ready" || status.state === "degraded") && status.readiness && (
          <ul className={styles.dependencyList}>
            <li>
              <span>API</span>
              <StatusBadge state="ok" label="Reachable" />
            </li>
            {Object.entries(status.readiness.dependencies).map(([key, dependency]) => (
              <li key={key}>
                <span>
                  {DEPENDENCY_LABELS[key] ?? key}
                  {NON_AUTHORITATIVE_DEPENDENCIES.has(key) && (
                    <span className={styles.optionalNote}> (optional)</span>
                  )}
                </span>
                <StatusBadge
                  state={dependency.status === "ok" ? "ok" : "unavailable"}
                  label={dependency.status === "ok" ? "Available" : "Unavailable"}
                />
              </li>
            ))}
          </ul>
        )}

        {status.state === "degraded" && !status.readiness && status.error && (
          <p className={styles.technicalDetail}>{status.error}</p>
        )}

        {(status.state === "ready" || status.state === "degraded") && status.readiness && (
          <p className={styles.readinessNote}>
            Postgres and Qdrant are required for readiness. Redis backs an optional performance
            cache only and never affects overall system status.
          </p>
        )}
      </section>

      <p className={styles.disclaimer}>
        CareFlow AI currently uses public CMS policy information and synthetic
        healthcare datasets for development and demonstration.
      </p>
    </div>
  );
}
