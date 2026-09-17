"use client";

/**
 * Opening an invitation link.
 *
 * This is where a WhatsApp message lands: the owner invites a phone number, sends the link, and the
 * person taps it. If they have no account yet they are taken through sign-up and come back here - the
 * token travels in the address, so nothing about it is stored on their device - and then the
 * invitation is accepted and the business appears for them.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Brand, Wordmark } from "@/components/brand";
import { Button } from "@/components/ui";
import { acceptInvitation, currentUser, type AcceptedInvitation } from "@/lib/api";
import { explainFailure } from "@/lib/errors";
import styles from "./join.module.css";

export default function Join() {
  const router = useRouter();
  const token = String(useParams().token ?? "");
  const [accepted, setAccepted] = useState<AcceptedInvitation | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  //: React runs an effect twice in development, and a person can double-tap a link. Accepting twice
  //: is refused by the database now, but the second attempt would show a refusal for an invitation
  //: that was accepted a moment earlier, which reads as a broken link.
  const acceptedOnce = useRef(false);

  useEffect(() => {
    if (acceptedOnce.current) {
      return;
    }
    acceptedOnce.current = true;
    void (async () => {
      try {
        await currentUser();
      } catch {
        // No session yet: sign up (or sign in) first, and come back to this same link afterwards.
        router.replace(`/start?intent=create&next=${encodeURIComponent(`/join/${token}`)}`);
        return;
      }
      setBusy(true);
      try {
        setAccepted(await acceptInvitation(token));
      } catch (error) {
        const explained = explainFailure(error);
        setProblem(explained.hint ? `${explained.message} ${explained.hint}` : explained.message);
      } finally {
        setBusy(false);
      }
    })();
  }, [router, token]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Brand>
          <Wordmark />
        </Brand>
      </header>

      <div className={styles.card}>
        {accepted ? (
          <>
            <h1 className={styles.title}>You are in</h1>
            <p className={styles.body}>
              You have joined <strong>{accepted.tenant_name}</strong> as{" "}
              <strong>{accepted.role_name}</strong>.
            </p>
            <Button full onClick={() => router.replace("/app")}>
              Open the shop
            </Button>
          </>
        ) : problem ? (
          <>
            <h1 className={styles.title}>That invitation does not work</h1>
            <p className={styles.body}>{problem}</p>
            <Link className={styles.link} href="/app">
              Go to your shop
            </Link>
          </>
        ) : (
          <p className={styles.body}>{busy ? "Accepting your invitation..." : "Checking..."}</p>
        )}
      </div>
    </main>
  );
}
