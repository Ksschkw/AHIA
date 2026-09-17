"use client";

/**
 * Where somebody signs in or opens a shop.
 *
 * Two modes on one screen, because a person who came to sign in and turns out to have no account
 * should not have to find the right page. Everything that can be checked here is checked here - before
 * a request goes anywhere - because a round trip to be told the password is too short is a waste of a
 * market trader's airtime. The server remains the authority; this is a courtesy, not a claim.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useMemo, useState } from "react";

import { BrandMark, Wordmark } from "@/components/brand";
import { Button, CheckList, Field, PasswordField, StrengthMeter } from "@/components/ui";
import { registerAccount, signIn } from "@/lib/api";
import { explainFailure, type Explained } from "@/lib/errors";
import {
  PASSWORD_MINIMUM_LENGTH,
  looksLikeEmail,
  looksLikeIdentifier,
  passwordChecks,
  passwordStrength,
} from "@/lib/passwords";
import styles from "./start.module.css";

type Mode = "signin" | "create";

/**
 * Where to go after signing in, but only where we said.
 *
 * `?next=` is how the invitation link survives a sign-up, and it is also how an open redirect gets
 * built: a link on somebody else's site that sends a person to ours and then straight on to a page
 * that pretends to be ours. A value that is not a path on this site is ignored.
 */
function safeNext(candidate: string | null): string | null {
  if (!candidate) {
    return null;
  }
  if (!candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes(":")) {
    return null;
  }
  return candidate;
}
type Touched = Record<string, boolean>;

function AuthScreen() {
  const router = useRouter();
  const parameters = useSearchParams();
  const intent = parameters.get("intent");
  const next = safeNext(parameters.get("next"));

  const [mode, setMode] = useState<Mode>(intent === "create" ? "create" : "signin");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [emailAddress, setEmailAddress] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Explained | null>(null);
  const [touched, setTouched] = useState<Touched>({});

  const strength = useMemo(() => passwordStrength(password), [password]);
  const checks = useMemo(() => passwordChecks(password), [password]);
  const identifierOk = looksLikeIdentifier(identifier);
  const phoneOk = phoneNumber.trim().length === 0 || looksLikeIdentifier(phoneNumber.trim());
  const emailOk = emailAddress.trim().length === 0 || looksLikeEmail(emailAddress.trim());
  const hasAContact = phoneNumber.trim().length > 0 || emailAddress.trim().length > 0;
  const passwordsMatch = confirmation.length > 0 && confirmation === password;
  const creating = mode === "create";

  const errors = {
    firstName: creating && touched.firstName && firstName.trim().length < 2 ? "Tell us your first name." : undefined,
    lastName: creating && touched.lastName && lastName.trim().length < 2 ? "Tell us your surname." : undefined,
    phone: creating && touched.phone && !phoneOk ? "A phone number looks like 0803 123 4567." : undefined,
    email: creating && touched.email && !emailOk ? "An email address looks like ada@example.com." : undefined,
    contact:
      creating && touched.contact && !hasAContact
        ? "Leave us a phone number or an email address - either one is enough."
        : undefined,
    identifier: touched.identifier
      ? identifierOk
        ? undefined
        : "Enter an email address like ada@example.com, or a phone number like 08031234567."
      : undefined,
    password: touched.password
      ? password.length < PASSWORD_MINIMUM_LENGTH
        ? `Use at least ${PASSWORD_MINIMUM_LENGTH} characters.`
        : undefined
      : undefined,
    confirmation: creating && touched.confirmation && !passwordsMatch ? "The two passwords are not the same." : undefined,
  };

  const canSubmit = creating
    ? firstName.trim().length >= 2 &&
      lastName.trim().length >= 2 &&
      hasAContact &&
      phoneOk &&
      emailOk &&
      password.length >= PASSWORD_MINIMUM_LENGTH &&
      passwordsMatch
    : identifierOk && password.length >= PASSWORD_MINIMUM_LENGTH;

  const submit = useCallback(async () => {
    setBusy(true);
    setFailure(null);
    setTouched({ firstName: true, lastName: true, identifier: true, password: true, confirmation: true });
    try {
      if (creating) {
        await registerAccount({
          first_name: firstName.trim(),
          last_name: lastName.trim(),
          phone: phoneNumber.trim() || undefined,
          email: emailAddress.trim() || undefined,
          password,
        });
      } else {
        await signIn({ identifier: identifier.trim(), password });
      }
      router.replace(next ?? "/app");
    } catch (caught) {
      if (caught instanceof Error && "code" in caught && caught.code === "CONFLICT") {
        setFailure({
          message: "An account already uses that email address.",
          hint: "Sign in instead, or use a different address.",
        });
      } else {
        setFailure(explainFailure(caught));
      }
      // A failed password attempt most likely means the password, so put the cursor where the fix is.
      if (mode === "signin") {
        setPassword("");
      }
    } finally {
      setBusy(false);
    }
  }, [
    confirmation,
    creating,
    emailAddress,
    firstName,
    identifier,
    lastName,
    mode,
    password,
    phoneNumber,
    router,
  ]);

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <Link className={styles.brandLink} href="/">
          <BrandMark size={46} />
          <h1 className={styles.title}>
            <Wordmark size="large" />
          </h1>
        </Link>

        <div className={styles.tabs}>
          <button
            type="button"
            className={mode === "signin" ? styles.tabActive : styles.tab}
            onClick={() => {
              setMode("signin");
              setFailure(null);
            }}
          >
            Sign in
          </button>
          <button
            type="button"
            className={mode === "create" ? styles.tabActive : styles.tab}
            onClick={() => {
              setMode("create");
              setFailure(null);
            }}
          >
            Create account
          </button>
        </div>

        <p className={styles.intro}>
          {mode === "signin"
            ? "Welcome back. Sign in with the email address or phone number you registered."
            : "Two minutes and you are recording sales. Only your name and an email are needed."}
        </p>

        <form
          className={styles.form}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit && !busy) {
              void submit();
            } else {
              setTouched({ firstName: true, lastName: true, identifier: true, password: true, confirmation: true });
            }
          }}
        >
          {creating ? (
            <div className={styles.nameRow}>
              <Field
                label="First name"
                id="first_name"
                value={firstName}
                onChange={setFirstName}
                onBlur={() => setTouched((t) => ({ ...t, firstName: true }))}
                placeholder="Ada"
                autoComplete="given-name"
                error={errors.firstName}
                autoFocus
              />
              <Field
                label="Surname"
                id="last_name"
                value={lastName}
                onChange={setLastName}
                onBlur={() => setTouched((t) => ({ ...t, lastName: true }))}
                placeholder="Obi"
                autoComplete="family-name"
                error={errors.lastName}
              />
            </div>
          ) : null}

          {creating ? (
            <>
              <Field
                label="Phone number"
                id="phone"
                value={phoneNumber}
                onChange={setPhoneNumber}
                onBlur={() => setTouched((t) => ({ ...t, phone: true, contact: true }))}
                inputMode="tel"
                autoComplete="tel"
                placeholder="0803 123 4567"
                hint="How you sign in, and how customers reach you. Any form works: 0901..., 0803 123 4567, +234901..."
                error={errors.phone}
              />
              <Field
                label="Email address"
                id="email"
                value={emailAddress}
                onChange={setEmailAddress}
                onBlur={() => setTouched((t) => ({ ...t, email: true, contact: true }))}
                inputMode="email"
                autoComplete="email"
                optional
                placeholder="ada@example.com"
                hint="Where receipts and reports are sent, if you want them by mail."
                error={errors.email ?? errors.contact}
              />
            </>
          ) : (
            <Field
              label="Phone number or email"
              id="identifier"
              value={identifier}
              onChange={setIdentifier}
              onBlur={() => setTouched((t) => ({ ...t, identifier: true }))}
              autoComplete="username"
              placeholder="0803 123 4567 or ada@example.com"
              error={errors.identifier}
            />
          )}

          <PasswordField
            label="Password"
            id="password"
            value={password}
            onChange={setPassword}
            onBlur={() => setTouched((t) => ({ ...t, password: true }))}
            autoComplete={creating ? "new-password" : "current-password"}
            hint={creating ? undefined : "At least 8 characters."}
            error={errors.password}
          />

          {creating ? (
            <>
              <StrengthMeter score={strength.score} label={strength.label} />
              <CheckList checks={checks} />
              <PasswordField
                label="Type it again"
                id="confirm_password"
                value={confirmation}
                onChange={setConfirmation}
                onBlur={() => setTouched((t) => ({ ...t, confirmation: true }))}
                autoComplete="new-password"
                placeholder="The same password once more"
                error={errors.confirmation}
              />
            </>
          ) : null}

          <Button type="submit" full busy={busy} disabled={!canSubmit}>
            {creating ? "Create my account" : "Sign in"}
          </Button>
        </form>

        {failure ? (
          <p className={styles.failure} role="alert">
            <strong>{failure.message}</strong>
            {failure.hint ? <span>{failure.hint}</span> : null}
            {failure.reference ? <span className={styles.reference}>Reference {failure.reference}</span> : null}
          </p>
        ) : null}

        <p className={styles.alternate}>
          {creating ? "Already have an account? " : "New here? "}
          <button
            type="button"
            className={styles.alternateLink}
            onClick={() => {
              setMode(creating ? "signin" : "create");
              setFailure(null);
            }}
          >
            {creating ? "Sign in" : "Create one"}
          </button>
        </p>

        <Link className={styles.back} href="/">
          Back to the front page
        </Link>
      </div>
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
