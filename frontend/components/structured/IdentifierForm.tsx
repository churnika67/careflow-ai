"use client";

import styles from "./IdentifierForm.module.css";

interface IdentifierFormProps {
  inputId: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: React.FormEvent) => void;
  exampleId: string | null;
  onUseExample: () => void;
  isLoading: boolean;
  loadingLabel: string;
  submitLabel: string;
  submissionAllowed: boolean;
  blockedReason: string | null;
  validationError: string | null;
}

/** Shared identifier-entry form for both Patient Data (FHIR) and Claims
 * (SynPUF) -- same shape, different labels/example ID, per
 * docs/phase14_frontend_design.md's "Identifier strategy". */
export function IdentifierForm({
  inputId,
  label,
  value,
  onChange,
  onSubmit,
  exampleId,
  onUseExample,
  isLoading,
  loadingLabel,
  submitLabel,
  submissionAllowed,
  blockedReason,
  validationError,
}: IdentifierFormProps) {
  return (
    <form className={styles.form} onSubmit={onSubmit} noValidate>
      <label htmlFor={inputId} className={styles.label}>
        {label}
      </label>
      <div className={styles.row}>
        <input
          id={inputId}
          type="text"
          className={styles.input}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={isLoading}
          aria-invalid={validationError ? "true" : undefined}
          aria-describedby={validationError ? `${inputId}-validation` : undefined}
        />
        <button type="submit" className={styles.submitButton} disabled={isLoading || !submissionAllowed}>
          {isLoading ? loadingLabel : submitLabel}
        </button>
      </div>
      {validationError && (
        <p id={`${inputId}-validation`} className={styles.validationError} role="alert">
          {validationError}
        </p>
      )}
      {exampleId && (
        <button
          type="button"
          className={styles.exampleButton}
          onClick={onUseExample}
          disabled={isLoading}
        >
          Use example synthetic ID
        </button>
      )}
      {!submissionAllowed && blockedReason && (
        <p className={styles.blockedReason}>{blockedReason}</p>
      )}
    </form>
  );
}
