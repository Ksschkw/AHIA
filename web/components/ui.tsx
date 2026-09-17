/**
 * The small pieces the screens are built from.
 *
 * One file rather than a folder of one-component files: these are twelve-line components that only
 * make sense together, and a reader looking for "the button" should not have to guess which of five
 * files it is in.
 */

"use client";

import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";

import styles from "./ui.module.css";

type ButtonTone = "primary" | "quiet" | "danger";

export function Button({
  children,
  onClick,
  tone = "primary",
  disabled,
  busy,
  type = "button",
  full,
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: ButtonTone;
  disabled?: boolean;
  busy?: boolean;
  type?: "button" | "submit";
  full?: boolean;
}) {
  return (
    <button
      type={type}
      className={`${styles.button} ${styles[tone]} ${full ? styles.full : ""}`}
      onClick={onClick}
      disabled={disabled || busy}
    >
      {busy ? <span className={styles.spinner} aria-hidden /> : null}
      {children}
    </button>
  );
}

export function Field({
  label,
  id,
  value,
  onChange,
  type = "text",
  placeholder,
  autoFocus,
  inputMode,
  hint,
  error,
  autoComplete,
  optional,
  onBlur,
  children,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  autoFocus?: boolean;
  inputMode?: "text" | "decimal" | "numeric" | "email" | "tel";
  onBlur?: () => void;
  /** What the field expects, said before it is filled in rather than after. */
  hint?: string;
  /** What is wrong with what is in it, said once and in the second person. */
  error?: string;
  autoComplete?: string;
  optional?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel} htmlFor={id}>
        {label}
        {optional ? <span className={styles.fieldOptional}>optional</span> : null}
      </label>
      <div className={`${styles.inputWrap} ${error ? styles.inputWrapError : ""}`}>
        <input
          id={id}
          className={styles.input}
          value={value}
          type={type}
          inputMode={inputMode}
          placeholder={placeholder}
          autoFocus={autoFocus}
          autoComplete={autoComplete}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
        />
        {children}
      </div>
      {error ? (
        <span className={styles.fieldError} id={`${id}-error`}>
          {error}
        </span>
      ) : hint ? (
        <span className={styles.fieldHint} id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

/**
 * A password field with a way to look at it.
 *
 * Typing a password blind on a phone keyboard is how people end up locked out of their own account,
 * so the reveal is next to the field rather than hidden in a settings page somewhere.
 */
export function PasswordField({
  label,
  id,
  value,
  onChange,
  hint,
  error,
  autoComplete,
  onBlur,
  placeholder,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  error?: string;
  autoComplete?: string;
  onBlur?: () => void;
  placeholder?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <Field
      label={label}
      id={id}
      value={value}
      onChange={onChange}
      type={revealed ? "text" : "password"}
      hint={hint}
      error={error}
      autoComplete={autoComplete}
      onBlur={onBlur}
      placeholder={placeholder}
    >
      <button
        type="button"
        className={styles.reveal}
        onClick={() => setRevealed((current) => !current)}
        aria-label={revealed ? "Hide the password" : "Show the password"}
        title={revealed ? "Hide the password" : "Show the password"}
      >
        {revealed ? "Hide" : "Show"}
      </button>
    </Field>
  );
}

/** How strong the password is, as a meter and a word - not as a scolding. */
export function StrengthMeter({ score, label }: { score: number; label: string }) {
  return (
    <div className={styles.strength} aria-live="polite">
      <span className={styles.strengthTrack}>
        {[1, 2, 3, 4].map((step) => (
          <span
            key={step}
            className={`${styles.strengthStep} ${step <= score ? styles[`strength${score}`] : ""}`}
          />
        ))}
      </span>
      <span className={styles.strengthLabel}>{label}</span>
    </div>
  );
}

/** The requirements, ticked as they are met. */
export function CheckList({ checks }: { checks: { label: string; satisfied: boolean }[] }) {
  return (
    <ul className={styles.checks}>
      {checks.map((check) => (
        <li key={check.label} className={check.satisfied ? styles.checkDone : styles.check}>
          <span aria-hidden className={styles.checkMark}>
            {check.satisfied ? (
              // Drawn rather than typed: a tick is a shape, and the source of this project is ASCII.
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M1.5 5.2 4 7.5l4.5-5" />
              </svg>
            ) : null}
          </span>
          {check.label}
        </li>
      ))}
    </ul>
  );
}

export function Select({
  label,
  id,
  value,
  options,
  onChange,
}: {
  label: string;
  id: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className={styles.field} htmlFor={id}>
      <span className={styles.fieldLabel}>{label}</span>
      <select
        id={id}
        className={styles.input}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "plain",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "plain" | "good" | "warn";
}) {
  return (
    <div className={`${styles.stat} ${styles[`stat_${tone}`]}`}>
      <span className={styles.statLabel}>{label}</span>
      <span className={`${styles.statValue} tabular`}>{value}</span>
      {hint ? <span className={styles.statHint}>{hint}</span> : null}
    </div>
  );
}

export function Pill({ children, tone }: { children: ReactNode; tone: "good" | "warn" | "bad" }) {
  return <span className={`${styles.pill} ${styles[`pill_${tone}`]}`}>{children}</span>;
}

/** A sheet that slides up from the bottom on a phone and centres on a desktop. */
export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div className={styles.scrim} onClick={onClose} role="presentation">
      <div
        className={styles.sheet}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.sheetHeader}>
          <h2 className={styles.sheetTitle}>{title}</h2>
          <button className={styles.close} onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>
        <div className={styles.sheetBody}>{children}</div>
      </div>
    </div>
  );
}

export function Toast({
  message,
  hint,
  reference,
  tone,
  onDismiss,
}: {
  message: string;
  hint?: string;
  reference?: string;
  tone: "good" | "bad";
  onDismiss: () => void;
}) {
  useEffect(() => {
    // A success can fade; a failure should not. A trader who missed the message has no way to find
    // out what happened, and a message that disappears while a screenshot is taken is a message that
    // cannot be diagnosed either.
    if (tone !== "good") {
      return;
    }
    const timer = window.setTimeout(onDismiss, 6000);
    return () => window.clearTimeout(timer);
  }, [message, tone, onDismiss]);

  return (
    <div className={`${styles.toast} ${tone === "good" ? styles.toastGood : styles.toastBad}`}>
      <span className={styles.toastText}>
        <span className={styles.toastMessage}>{message}</span>
        {hint ? <span className={styles.toastHint}>{hint}</span> : null}
        {reference ? <span className={styles.toastReference}>Reference {reference}</span> : null}
      </span>
      <button className={styles.toastClose} onClick={onDismiss} aria-label="Dismiss">
        Dismiss
      </button>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className={styles.empty}>{children}</p>;
}

export function Card({
  title,
  action,
  children,
  style,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <section className={styles.card} style={style}>
      {title ? (
        <header className={styles.cardHeader}>
          <h2 className={styles.cardTitle}>{title}</h2>
          {action}
        </header>
      ) : null}
      {children}
    </section>
  );
}
