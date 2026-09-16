"use client";

/**
 * Where somebody signs in or opens a shop.
 *
 * One screen with two modes rather than two routes: a person who came to sign in and realises they
 * have no account should not have to find the right page. The success path always ends at `/app`,
 * which owns the session check - so this screen does not have to ask the API anything before it can
 * be used.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useState } from "react";

import { Brand, BrandMark, Wordmark } from "@/components/brand";
import { Button, Field, Toast } from "@/components/ui";
import { ApiError, registerAccount, signIn } from "@/lib/api";
import styles from "./start.module.css";

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.describe()}`;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

function AuthScreen() {
  const router = useRouter();
  const intent = useSearchParams().get("intent");
  const [mode, setMode] = useState<"signin" | "create">(
    intent === "create" ? "create" : "signin",
  );
  const [name, setName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    identifier.trim().length >= 3 && password.length >= 8 && (mode === "signin" || name.trim().length > 0);

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === "create") {
        await registerAccount({
          first_name: name.trim(),
          last_name: "Owner",
          email: identifier.trim(),
          password,
        });
      } else {
        await signIn({ identifier: identifier.trim(), password });
      }
      router.replace("/app");
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setBusy(false);
    }
  }, [identifier, mode, name, password, router]);

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <Link className={styles.brandLink} href="/">
          <BrandMark size={46} />
          <h1 className={styles.title}>
            <Wordmark size="large" />
          </h1>
        </Link>
        <p className={styles.tagline}>
          Sell, stock and keep the books - one screen, even when the network is not.
        </p>

        <div className={styles.tabs}>
          <button
            className={mode === "signin" ? styles.tabActive : styles.tab}
            onClick={() => setMode("signin")}
          >
            Sign in
          </button>
          <button
            className={mode === "create" ? styles.tabActive : styles.tab}
            onClick={() => setMode("create")}
          >
            Create account
          </button>
        </div>

        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit && !busy) {
              void submit();
            }
          }}
        >
          {mode === "create" ? (
            <Field
              label="Your name"
              id="first_name"
              value={name}
              onChange={setName}
              placeholder="Ada"
              autoFocus
            />
          ) : null}
          <Field
            label={mode === "create" ? "Email address" : "Email or phone"}
            id="identifier"
            value={identifier}
            onChange={setIdentifier}
            inputMode={mode === "create" ? "email" : "text"}
            placeholder={mode === "create" ? "ada@example.com" : "ada@example.com or 08031234567"}
          />
          <Field
            label="Password"
            id="password"
            value={password}
            onChange={setPassword}
            type="password"
            placeholder="at least 8 characters"
          />
          <Button type="submit" full busy={busy} disabled={!canSubmit}>
            {mode === "create" ? "Create my shop" : "Sign in"}
          </Button>
        </form>

        <Link className={styles.back} href="/">
          Back to the front page
        </Link>
      </div>

      {error ? <Toast message={error} tone="bad" onDismiss={() => setError(null)} /> : null}
    </main>
  );
}

export default function StartPage() {
  return (
    <Suspense fallback={null}>
      <AuthScreen />
    </Suspense>
  );
}
