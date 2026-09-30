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
        <div className={styles.heroGrid}>
          <div className={styles.heroContent}>
            <span className={styles.eyebrow}>Evidence-Grounded · Multi-Source · Human-Reviewed</span>
            <h1 className={`${styles.appName} gradient-text`}>
              CareFlow AI
              <br />
              Healthcare Intelligence
              <br />
              with Real Evidence
            </h1>
            <p className={styles.description}>
              Combine Medicare policy, synthetic patient data, and claims data with bounded
              AI workflows, validated citations, and human-in-the-loop review.
            </p>
          </div>
          <ArchitectureDiagram />
        </div>
      </section>

      <dl className={styles.stats} aria-label="Engineering metrics">
        <div className={styles.statCard}>
          <span className={styles.statIcon} data-tone="ok" aria-hidden="true">
            <CheckIcon />
          </span>
          <dd className={styles.statNumber}>1,171</dd>
          <dt className={styles.statLabel}>Automated Tests Passing</dt>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statIcon} data-tone="primary" aria-hidden="true">
            <PlayIcon />
          </span>
          <dd className={styles.statNumber}>9</dd>
          <dt className={styles.statLabel}>End-to-End Browser Journeys</dt>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statIcon} data-tone="amber" aria-hidden="true">
            <NetworkIcon />
          </span>
          <dd className={styles.statNumber}>6</dd>
          <dt className={styles.statLabel}>CI Quality Gates Every Commit</dt>
        </div>
        <div className={styles.statCard}>
          <span className={styles.statIcon} data-tone="muted" aria-hidden="true">
            <ShieldIcon />
          </span>
          <dd className={styles.statNumber}>0</dd>
          <dt className={styles.statLabel}>Real Patient Records Used</dt>
        </div>
      </dl>

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

function CheckIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12.5 10 17l9-10" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  );
}

function NetworkIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="5" r="2.2" />
      <circle cx="5" cy="19" r="2.2" />
      <circle cx="19" cy="19" r="2.2" />
      <path d="M12 7.2v4.3M12 11.5 6.4 17M12 11.5 17.6 17" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3.5 5 6v6c0 4.5 3 7.5 7 8.5 4-1 7-4 7-8.5V6z" />
      <path d="m9.5 12 1.8 1.8L15 10.2" />
    </svg>
  );
}

// A restrained, decorative-but-accurate diagram of CareFlow's real
// architecture: two real evidence sources (CMS Policy RAG, FHIR Patient
// Data) plus one more (DE-SynPUF Claims), all routed through one
// orchestration node -- mirrors the Mermaid diagram in the project README,
// not an invented information architecture.
function ArchitectureDiagram() {
  return (
    <svg
      className={styles.diagram}
      viewBox="0 0 340 300"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path d="M170 150 L100 95" stroke="rgba(255,255,255,0.28)" strokeWidth="1.5" strokeDasharray="3 4" />
      <path d="M170 150 L250 95" stroke="rgba(255,255,255,0.28)" strokeWidth="1.5" strokeDasharray="3 4" />
      <path d="M170 150 L250 210" stroke="rgba(255,255,255,0.28)" strokeWidth="1.5" strokeDasharray="3 4" />

      <Hexagon cx={100} cy={95} label="CMS Policy" sublabel="RAG" tone="primary" />
      <Hexagon cx={250} cy={95} label="FHIR" sublabel="Patient Data" tone="teal" />
      <Hexagon cx={250} cy={210} label="DE-SynPUF" sublabel="Claims Data" tone="amber" />
      <Hexagon cx={170} cy={150} label="CareFlow AI" sublabel="Orchestration" tone="core" large />
    </svg>
  );
}

const HEX_POINTS = "0,-30 26,-15 26,15 0,30 -26,15 -26,-15";
const HEX_FILL: Record<string, string> = {
  primary: "rgba(84, 81, 224, 0.55)",
  teal: "rgba(45, 212, 191, 0.4)",
  amber: "rgba(245, 165, 36, 0.4)",
  core: "rgba(255, 255, 255, 0.16)",
};

function Hexagon({
  cx,
  cy,
  label,
  sublabel,
  tone,
  large,
}: {
  cx: number;
  cy: number;
  label: string;
  sublabel: string;
  tone: string;
  large?: boolean;
}) {
  const scale = large ? 1.15 : 1;
  return (
    <g transform={`translate(${cx} ${cy})`}>
      <polygon
        points={HEX_POINTS}
        transform={`scale(${scale})`}
        fill={HEX_FILL[tone]}
        stroke="rgba(255,255,255,0.45)"
        strokeWidth="1.5"
      />
      <text textAnchor="middle" y={-2} fontSize="9.5" fontWeight="700" fill="#ffffff">
        {label}
      </text>
      <text textAnchor="middle" y={10} fontSize="8" fill="rgba(255,255,255,0.75)">
        {sublabel}
      </text>
    </g>
  );
}
