"use client";

/**
 * The person's own account, and the business they are working in.
 *
 * Two things live here because they are the same question from a trader's point of view: "who am I in
 * this system, and what does my shop say about itself". Your name and how you sign in; your password;
 * the shop's name, phone and address; and the businesses you belong to with the role you hold in each.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Brand, Wordmark } from "@/components/brand";
import { Button, Card, Field, Pill, PasswordField, Toast } from "@/components/ui";
import {
  ApiError,
  changePassword,
  currentUser,
  getBusiness,
  listBusinesses,
  updateBusiness,
  updateProfile,
  type Tenant,
  type TenantSummary,
  type UserProfile,
} from "@/lib/api";
import { explainFailure, type Explained } from "@/lib/errors";
import {
  PASSWORD_MINIMUM_LENGTH,
  passwordChecks,
  passwordStrength,
} from "@/lib/passwords";
import { CheckList, StrengthMeter } from "@/components/ui";
import styles from "./profile.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

export default function Profile() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [businesses, setBusinesses] = useState<TenantSummary[]>([]);
  const [business, setBusiness] = useState<Tenant | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  // Your details
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");

  // The business's details
  const [businessName, setBusinessName] = useState("");
  const [businessPhone, setBusinessPhone] = useState("");
  const [businessAddress, setBusinessAddress] = useState("");
  const [businessCity, setBusinessCity] = useState("");
  const [businessState, setBusinessState] = useState("");

  // Password
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const report = useCallback((error: unknown) => {
    const explained: Explained = explainFailure(error);
    setNotice({ message: explained.message, hint: explained.hint, tone: "bad" });
  }, []);

  const run = useCallback(
    async (key: string, action: () => Promise<void>) => {
      setBusyAction(key);
      setNotice(null);
      try {
        await action();
      } catch (error) {
        report(error);
      } finally {
        setBusyAction(null);
      }
    },
    [report],
  );

  useEffect(() => {
    void (async () => {
      try {
        const [profile, found] = await Promise.all([currentUser(), listBusinesses()]);
        setUser(profile);
        setFirstName(profile.first_name);
        setLastName(profile.last_name ?? "");
        setPhone(profile.phone ?? "");
        setEmail(profile.email ?? "");
        setBusinesses(found);
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = found.find((candidate) => candidate.id === remembered) ?? found[0];
        if (chosen) {
          const detail = await getBusiness(chosen.id);
          setBusiness(detail);
          setBusinessName(detail.name);
          setBusinessPhone(detail.phone ?? "");
          setBusinessAddress(detail.address ?? "");
          setBusinessCity(detail.city ?? "");
          setBusinessState(detail.state ?? "");
        }
      } catch {
        router.replace("/start");
      }
    })();
  }, [router]);

  const strength = passwordStrength(newPassword);
  const checks = passwordChecks(newPassword);
  const passwordsMatch = confirmation.length > 0 && confirmation === newPassword;

  if (!user) {
    return (
      <main className={styles.page}>
        <header className={styles.topbar}>
          <Brand>
            <Wordmark />
          </Brand>
        </header>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Brand>
          <Wordmark />
        </Brand>
        <Link className={styles.back} href="/app">
          Back to the shop
        </Link>
      </header>

      <div className={styles.content}>
        <div className={styles.identity}>
          <span className={styles.avatar} aria-hidden>
            {(user.first_name[0] ?? "").toUpperCase()}
            {(user.last_name ?? "").slice(0, 1).toUpperCase()}
          </span>
          <div>
            <h1 className={styles.name}>
              {user.first_name} {user.last_name}
            </h1>
            <p className={styles.identityMeta}>
              {businesses.length === 1
                ? "One business"
                : `${businesses.length} businesses`}{" "}
              on this account
            </p>
          </div>
        </div>

        <Card title="Your details">
          <div className={styles.grid}>
            <Field label="First name" id="first_name" value={firstName} onChange={setFirstName} autoComplete="given-name" />
            <Field label="Surname" id="last_name" value={lastName} onChange={setLastName} autoComplete="family-name" />
            <Field
              label="Phone number"
              id="phone"
              value={phone}
              onChange={setPhone}
              inputMode="tel"
              autoComplete="tel"
              hint="This is how you sign in, and how customers reach you."
            />
            <Field
              label="Email address"
              id="email"
              value={email}
              onChange={setEmail}
              inputMode="email"
              autoComplete="email"
              optional
              hint="Receipts and reports are sent here."
            />
          </div>
          <div className={styles.actions}>
            <Button
              busy={busyAction === "profile"}
              onClick={() =>
                run("profile", async () => {
                  const saved = await updateProfile({
                    first_name: firstName.trim(),
                    last_name: lastName.trim(),
                    phone: phone.trim() || undefined,
                    email: email.trim() || undefined,
                  });
                  setUser(saved);
                  setNotice({ message: "Your details are saved.", tone: "good" });
                })
              }
            >
              Save my details
            </Button>
          </div>
        </Card>

        {business ? (
          <Card title={`About ${business.name}`}>
            <div className={styles.grid}>
              <Field label="Business name" id="business_name" value={businessName} onChange={setBusinessName} />
              <Field
                label="Business phone"
                id="business_phone"
                value={businessPhone}
                onChange={setBusinessPhone}
                inputMode="tel"
                hint="Shown to customers on the shop page."
              />
              <Field label="Street address" id="business_address" value={businessAddress} onChange={setBusinessAddress} />
              <Field label="City" id="business_city" value={businessCity} onChange={setBusinessCity} />
              <Field label="State" id="business_state" value={businessState} onChange={setBusinessState} />
            </div>
            <p className={styles.note}>
              Money is recorded in {business.currency}, and the shop&apos;s public address is{" "}
              <strong>{business.public_path}</strong>.
            </p>
            <div className={styles.actions}>
              <Button
                busy={busyAction === "business"}
                onClick={() =>
                  run("business", async () => {
                    const saved = await updateBusiness(business.id, {
                      name: businessName.trim(),
                      phone: businessPhone.trim() || undefined,
                      address: businessAddress.trim() || undefined,
                      city: businessCity.trim() || undefined,
                      state: businessState.trim() || undefined,
                    });
                    setBusiness(saved);
                    setNotice({ message: "The business details are saved.", tone: "good" });
                  })
                }
              >
                Save the business details
              </Button>
            </div>
          </Card>
        ) : null}

        <Card title="Your businesses">
          <ul className={styles.businessList}>
            {businesses.map((candidate) => (
              <li key={candidate.id} className={styles.businessRow}>
                <div>
                  <span className={styles.businessName}>{candidate.name}</span>
                  <span className={styles.businessSlug}>{candidate.public_path}</span>
                </div>
                <Pill tone={candidate.is_active ? "good" : "bad"}>
                  {candidate.role_name || "member"}
                </Pill>
              </li>
            ))}
          </ul>
          <p className={styles.note}>
            Everyone in a business signs in with their own account, and their role decides what they can
            do. Inviting people arrives next.
          </p>
        </Card>

        <Card title="Password">
          <div className={styles.grid}>
            <PasswordField
              label="Current password"
              id="current_password"
              value={currentPassword}
              onChange={setCurrentPassword}
              autoComplete="current-password"
            />
            <PasswordField
              label="New password"
              id="new_password"
              value={newPassword}
              onChange={setNewPassword}
              autoComplete="new-password"
            />
            <PasswordField
              label="New password again"
              id="confirm_new_password"
              value={confirmation}
              onChange={setConfirmation}
              autoComplete="new-password"
            />
          </div>
          {newPassword.length > 0 ? (
            <>
              <StrengthMeter score={strength.score} label={strength.label} />
              <CheckList checks={checks} />
            </>
          ) : null}
          {confirmation.length > 0 && !passwordsMatch ? (
            <p className={styles.mismatch}>The two new passwords are not the same.</p>
          ) : null}
          <div className={styles.actions}>
            <Button
              busy={busyAction === "password"}
              disabled={
                currentPassword.length === 0 ||
                newPassword.length < PASSWORD_MINIMUM_LENGTH ||
                !passwordsMatch
              }
              onClick={() =>
                run("password", async () => {
                  await changePassword({
                    current_password: currentPassword,
                    new_password: newPassword,
                  });
                  setCurrentPassword("");
                  setNewPassword("");
                  setConfirmation("");
                  setNotice({
                    message: "Your password is changed.",
                    hint: "Other devices stay signed in until their session ends.",
                    tone: "good",
                  });
                })
              }
            >
              Change my password
            </Button>
          </div>
        </Card>
      </div>

      {notice ? (
        <Toast message={notice.message} hint={notice.hint} tone={notice.tone} onDismiss={() => setNotice(null)} />
      ) : null}
    </main>
  );
}
