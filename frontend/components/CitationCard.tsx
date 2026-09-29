import type { Citation } from "@/lib/api/types";
import styles from "./CitationCard.module.css";

interface CitationCardProps {
  citation: Citation;
  /** 0-based index in response order -- displayed as "Citation N" (1-based). */
  index: number;
}

/**
 * Renders only fields backend/app/generation/models.py::Citation actually
 * has. No page number, author, publication date, confidence, or URL is
 * fabricated -- `source` is rendered as a link only because the backend
 * itself returns a real CMS URL there (see docs/phase14_frontend_design.md's
 * "Citation UX").
 */
export function CitationCard({ citation, index }: CitationCardProps) {
  return (
    <li className={styles.card}>
      <p className={styles.number}>Citation {index + 1}</p>
      <p className={styles.title}>{citation.title ?? "Untitled policy document"}</p>
      {citation.section && <p className={styles.section}>{citation.section}</p>}
      <p className={styles.meta}>
        NCD {citation.document_id} · Version {citation.document_version}
      </p>
      {citation.source && (
        <a
          href={citation.source}
          target="_blank"
          rel="noreferrer noopener"
          className={styles.link}
        >
          View source document
        </a>
      )}
    </li>
  );
}
