import type { Citation } from "@/lib/api/types";
import { CitationCard } from "../CitationCard";
import styles from "./PolicyAnswer.module.css";

/**
 * Shared policy answer/abstention rendering -- extracted in Phase 14
 * Slice 4 so both /ask (POST /query's full RAGAnswer) and /assistant
 * (POST /orchestrate's route=policy, which only ever returns `answer` +
 * `citations`, never the other RAGAnswer fields) render identically
 * without a second citation implementation. Deliberately typed on just
 * the two fields actually used, not the full RAGAnswer shape, so both
 * callers can pass exactly what they have.
 */
export function PolicyAnswerResult({
  answer,
  citations,
}: {
  answer: string;
  citations: Citation[];
}) {
  return (
    <div className={styles.result}>
      <section>
        <h2 className={styles.resultHeading}>Answer</h2>
        <p className={styles.answerText}>{answer}</p>
      </section>
      <section>
        <h2 className={styles.resultHeading}>Evidence</h2>
        <ul className={styles.citationList}>
          {citations.map((citation, index) => (
            <CitationCard key={`${citation.chunk_id}-${index}`} citation={citation} index={index} />
          ))}
        </ul>
      </section>
    </div>
  );
}

/** The dedicated, non-alarming "insufficient evidence" message -- the
 * exact same wording regardless of whether the policy pipeline was
 * reached via /query directly or via /orchestrate's route=policy. */
export function PolicyAbstainedResult() {
  return (
    <div className={styles.abstained} role="status">
      <p>
        CareFlow couldn&apos;t find enough evidence in the indexed Medicare policy documents to
        answer this question reliably.
      </p>
      <p className={styles.abstainedHint}>Try asking a more specific Medicare policy question.</p>
    </div>
  );
}
