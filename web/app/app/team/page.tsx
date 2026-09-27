"use client";

/**
 * The people in the business.
 *
 * A shop is not one person: the owner, a manager, the boys and girls on the counter, somebody who
 * counts stock. Each of them signs in with their own account and sees only what their role allows, and
 * this screen is where the owner decides that.
 *
 * **The invitation is a link, and that is a product decision.** The API hands back the token exactly
 * once - it stores a digest and cannot read it back - and this deployment sends no email. A trader runs
 * on WhatsApp, so the screen puts the link in a WhatsApp message: the person taps it, signs up with
 * the number the owner invited, and they are in.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ArrowLeftIcon } from "@/components/icons";
import { EmptyTeamIllustration } from "@/components/illustrations";
import { Button, Card, Empty, Field, Pill, Select, Toast } from "@/components/ui";
import {
  ApiError,
  MEMBER_ROLES,
  acceptInvitation,
  cachedRead,
  changeMemberRole,
  changeMemberStatus,
  currentUser,
  firstPaint,
  getBusiness,
  inviteMember,
  listBusinesses,
  listIssuedInvitations,
  listMembers,
  listMyInvitations,
  rememberedBusinessId,
  removeMember,
  type AcceptedInvitation,
  type Member,
  type MemberRole,
  type MembershipInvitation,
  type PendingInvitation,
  type Tenant,
} from "@/lib/api";
import { explainFailure } from "@/lib/errors";
import { PinGate } from "@/components/pin-gate";
import { hasDevicePin } from "@/lib/device-pin";
import styles from "./team.module.css";

type Notice = { message: string; tone: "good" | "bad"; hint?: string };

// The API's own vocabulary, in lowercase: it serialises the enum as it stores it.
const STATUS_LABEL: Record<string, string> = {
  active: "Working",
  invited: "Invited",
  suspended: "Suspended",
  removed: "Removed",
};

export default function Team() {
  const router = useRouter();
  const [business, setBusiness] = useState<Tenant | null>(() =>
    firstPaint<Tenant>(rememberedBusinessId(), (id) => `/api/v1/tenants/${id}`),
  );
  const [members, setMembers] = useState<Member[]>(() => {
    const id = rememberedBusinessId();
    if (!id) return [];
    return cachedRead<Member[]>(`/api/v1/tenants/${id}/members`) ?? [];
  });
  const [issued, setIssued] = useState<MembershipInvitation[]>(() => {
    const id = rememberedBusinessId();
    if (!id) return [];
    return cachedRead<MembershipInvitation[]>(`/api/v1/tenants/${id}/invitations`) ?? [];
  });
  const [mine, setMine] = useState<PendingInvitation[]>(() => {
    return cachedRead<PendingInvitation[]>("/api/v1/invitations/mine") ?? [];
  });
  const [busyAction, setBusyAction] = useState<string | null>(null);
  //: The action waiting on the question, if the person holding the phone has not answered yet.
  const [gated, setGated] = useState<{ run: () => void } | null>(null);
  //: True from the instant a handler starts to the instant it finishes, which state cannot be.
  const inFlight = useRef(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [inviteRole, setInviteRole] = useState<MemberRole>("SALES");
  const [invitePhone, setInvitePhone] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteNickname, setInviteNickname] = useState("");
  const [lastInvitedName, setLastInvitedName] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);

  const [nicknames, setNicknames] = useState<Record<string, string>>({});
  const [editingNicknameId, setEditingNicknameId] = useState<string | null>(null);
  const [nicknameInput, setNicknameInput] = useState("");

  useEffect(() => {
    if (!business?.id || typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(`ahia.staff_nicknames.${business.id}`);
      if (stored) {
        setNicknames(JSON.parse(stored));
      }
    } catch {
      // Ignore parse error
    }
  }, [business?.id]);

  const saveNickname = (idOrKey: string, name: string) => {
    if (!business?.id || typeof window === "undefined") return;
    setNicknames((prev) => {
      const updated = { ...prev };
      const cleaned = name.trim();
      if (cleaned) {
        updated[idOrKey] = cleaned;
      } else {
        delete updated[idOrKey];
      }
      try {
        window.localStorage.setItem(`ahia.staff_nicknames.${business.id}`, JSON.stringify(updated));
      } catch {
        // Ignore storage quota
      }
      return updated;
    });
    setEditingNicknameId(null);
    setNicknameInput("");
  };

  const run = useCallback(
    async (key: string, action: () => Promise<void>, skipGate = false) => {
      // **A synchronous guard, because `disabled` is not one.** React applies the disabled attribute on the
      // next render, which is a tick after the press - so two presses inside that tick both get through, and
      // the measurement found exactly that: a double press on a removal caused **two** requests. A ref is read
      // and written in the same tick the handler runs in, so the second press never reaches the request.
      // **Removing somebody from the team is one of the three things the objective names for the PIN**,
      // alongside changing a price and confirming a payout: it is the only action here that takes a person's
      // livelihood away with a tap, and it is done on a phone that is often in somebody else's hand.
      if (!skipGate && key.startsWith("remove-")) {
        setGated({ run: () => void run(key, action, true) });
        return;
      }
      if (inFlight.current) return;
      inFlight.current = true;
      setBusyAction(key);
      setNotice(null);
      try {
        await action();
      } catch (error) {
        const explained = explainFailure(error);
        setNotice({ message: explained.message, hint: explained.hint, tone: "bad" });
      } finally {
        inFlight.current = false;
        setBusyAction(null);
      }
    },
    [],
  );

  const refresh = useCallback(async (tenantId: string) => {
    const [foundMembers, foundIssued] = await Promise.all([
      listMembers(tenantId),
      listIssuedInvitations(tenantId),
    ]);
    setMembers(foundMembers);
    setIssued(foundIssued);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await currentUser();
        const businesses = await listBusinesses();
        const remembered =
          typeof window === "undefined" ? null : window.localStorage.getItem("ahia.business");
        const chosen = businesses.find((candidate) => candidate.id === remembered) ?? businesses[0];
        if (!chosen) {
          router.replace("/app");
          return;
        }
        const rememberedMembers = cachedRead<Member[]>(`/api/v1/tenants/${chosen.id}/members`);
        if (rememberedMembers) setMembers(rememberedMembers);
        const rememberedIssued = cachedRead<MembershipInvitation[]>(`/api/v1/tenants/${chosen.id}/invitations`);
        if (rememberedIssued) setIssued(rememberedIssued);
        const rememberedMine = cachedRead<PendingInvitation[]>("/api/v1/invitations/mine");
        if (rememberedMine) setMine(rememberedMine);

        setBusiness(await getBusiness(chosen.id));
        await refresh(chosen.id);
        setMine(await listMyInvitations());
      } catch {
        router.replace("/start");
      }
    })();
  }, [refresh, router]);

  if (!business) {
    return <main className={styles.page} />;
  }

  // Somebody who was removed is not in the business: the API keeps the row for the audit trail, and
  // a list of who has access has no business showing it with a role and a Remove button.
  const people = members.filter((member) => member.status !== "removed");

  const inviteUrl = (token: string) =>
    `${typeof window === "undefined" ? "" : window.location.origin}/join/${token}`;

  return (
    <main className={styles.page}>
      <div className={styles.content}>
        <Link className={styles.backLink} href="/app">
          <ArrowLeftIcon size={16} />
          <span>Back to shop</span>
        </Link>

        <div>
          <h1 className={styles.title}>Who is in {business.name}</h1>
          <p className={styles.lede}>
            Every person signs in with their own account. Their role decides what they can do, so the
            person on the counter never sees the day&apos;s profit unless you want them to.
          </p>
        </div>

        {mine.length > 0 ? (
          <Card title="Invitations waiting for you">
            <ul className={styles.list}>
              {mine.map((invitation) => (
                <li key={invitation.id} className={styles.row}>
                  <div>
                    <span className={styles.rowName}>{invitation.tenant_name}</span>
                    <span className={styles.rowMeta}>as {invitation.role_name}</span>
                  </div>
                  <Button
                    busy={busyAction === `accept-${invitation.id}`}
                    onClick={() =>
                      run(`accept-${invitation.id}`, async () => {
                        // This path is for somebody already signed in whose number or address matches;
                        // it is accepted by identity rather than by the link's token.
                        await acceptInvitation(invitation.id);
                        setMine(await listMyInvitations());
                        setNotice({ message: "You are in.", tone: "good" });
                      })
                    }
                  >
                    Accept
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}

        <Card title="Invite somebody">
          <div className={styles.grid}>
            <Select
              label="What will they do?"
              id="invite_role"
              value={inviteRole}
              options={MEMBER_ROLES.map((role) => ({ value: role.value, label: role.label }))}
              onChange={(value) => setInviteRole(value as MemberRole)}
            />
            <Field
              label="Staff nickname or note"
              id="invite_nickname"
              value={inviteNickname}
              onChange={setInviteNickname}
              placeholder="e.g. Chinedu (Counter 1)"
              hint="Helps tell multiple sales staff apart."
              optional
            />
            <Field
              label="Their phone number"
              id="invite_phone"
              value={invitePhone}
              onChange={setInvitePhone}
              inputMode="tel"
              placeholder="0803 123 4567"
              hint="They sign up with this number."
            />
            <Field
              label="Their email"
              id="invite_email"
              value={inviteEmail}
              onChange={setInviteEmail}
              inputMode="email"
              optional
              placeholder="nwa@example.com"
            />
          </div>
          <p className={styles.note}>
            {MEMBER_ROLES.find((role) => role.value === inviteRole)?.description}
          </p>
          <div className={styles.actions}>
            <Button
              busy={busyAction === "invite"}
              disabled={invitePhone.trim().length < 7 && inviteEmail.trim().length < 5}
              onClick={() =>
                run("invite", async () => {
                  const cleanedNick = inviteNickname.trim();
                  const invitation = await inviteMember(business.id, {
                    role_name: inviteRole,
                    phone: invitePhone.trim() || undefined,
                    email: inviteEmail.trim() || undefined,
                  });
                  if (cleanedNick) {
                    setLastInvitedName(cleanedNick);
                    setNicknames((prev) => {
                      const updated = { ...prev };
                      if (invitation.id) updated[invitation.id] = cleanedNick;
                      if (invitePhone.trim()) updated[invitePhone.trim()] = cleanedNick;
                      if (inviteEmail.trim()) updated[inviteEmail.trim()] = cleanedNick;
                      try {
                        window.localStorage.setItem(
                          `ahia.staff_nicknames.${business.id}`,
                          JSON.stringify(updated),
                        );
                      } catch {}
                      return updated;
                    });
                  } else {
                    setLastInvitedName(null);
                  }
                  // The token exists only in this answer: the API keeps a digest and cannot read
                  // it back, so if it is missing there is no link to send and that is worth saying.
                  setInviteLink(
                    invitation.token ? inviteUrl(invitation.token) : null,
                  );
                  setInvitePhone("");
                  setInviteEmail("");
                  setInviteNickname("");
                  await refresh(business.id);
                  setNotice({
                    message: cleanedNick ? `Invitation created for ${cleanedNick}.` : "Invitation created.",
                    hint: "Send the link below - they sign up and they are in.",
                    tone: "good",
                  });
                })
              }
            >
              Create an invitation
            </Button>
          </div>

          {inviteLink ? (
            <div className={styles.inviteLink}>
              <span className={styles.linkValue}>{inviteLink}</span>
              <div className={styles.linkActions}>
                <button
                  className={styles.linkButton}
                  onClick={() => {
                    void navigator.clipboard.writeText(inviteLink).catch(() => undefined);
                    setNotice({ message: "Link copied.", tone: "good" });
                  }}
                >
                  Copy
                </button>
                <a
                  className={styles.linkButton}
                  href={`https://wa.me/?text=${encodeURIComponent(
                    lastInvitedName
                      ? `Hello ${lastInvitedName}, join ${business.name} on AHIA as ${inviteRole}: ${inviteLink}`
                      : `Join ${business.name} on AHIA: ${inviteLink}`,
                  )}`}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Send on WhatsApp
                </a>
              </div>
            </div>
          ) : null}
        </Card>

        <Card title={`People (${people.length})`}>
          {people.length === 0 ? (
            <Empty illustration={<EmptyTeamIllustration size={100} />}>
              No staff members yet. Send an invitation above to bring your sales staff, manager, or
              stock keeper on board.
            </Empty>
          ) : (
            <ul className={styles.list}>
              {people.map((member) => {
                const nick =
                  nicknames[member.id] ||
                  (member.phone && nicknames[member.phone]) ||
                  (member.email && nicknames[member.email]);
                return (
                  <li key={member.id} className={styles.memberRow}>
                    <div className={styles.memberWho}>
                      {editingNicknameId === member.id ? (
                        <div className={styles.inlineNicknameEdit}>
                          <input
                            type="text"
                            className={styles.nicknameInput}
                            value={nicknameInput}
                            onChange={(e) => setNicknameInput(e.target.value)}
                            placeholder="e.g. Chinedu (Counter 1)"
                            autoFocus
                            onKeyDown={(e) => {
                              if (e.key === "Enter") saveNickname(member.id, nicknameInput);
                              if (e.key === "Escape") setEditingNicknameId(null);
                            }}
                          />
                          <button
                            type="button"
                            className={styles.saveNickBtn}
                            onClick={() => saveNickname(member.id, nicknameInput)}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            className={styles.cancelNickBtn}
                            onClick={() => setEditingNicknameId(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className={styles.nameHeaderRow}>
                          <span className={styles.rowName}>
                            {nick ? (
                              <>
                                <span className={styles.nicknameHighlight}>{nick}</span>
                                {member.full_name ? (
                                  <span className={styles.fullNameSub}> ({member.full_name})</span>
                                ) : null}
                              </>
                            ) : (
                              member.full_name || "No name yet"
                            )}
                          </span>
                          <button
                            type="button"
                            className={styles.editNicknameBtn}
                            title="Set or change staff nickname"
                            onClick={() => {
                              setEditingNicknameId(member.id);
                              setNicknameInput(nick || member.full_name || "");
                            }}
                          >
                            {nick ? "Rename" : "+ Add name/label"}
                          </button>
                        </div>
                      )}
                      <span className={styles.rowMeta}>
                        {member.phone ?? member.email ?? "no contact"}
                      </span>
                    </div>
                    <Pill tone={member.status === "active" ? "good" : "warn"}>
                      {STATUS_LABEL[member.status] ?? member.status}
                    </Pill>
                    <Select
                      label="Role"
                      id={`role_${member.id}`}
                      value={member.role_name as MemberRole}
                      options={MEMBER_ROLES.map((role) => ({ value: role.value, label: role.label }))}
                      onChange={(value) =>
                        run(`role-${member.id}`, async () => {
                          await changeMemberRole(business.id, member.id, value as MemberRole);
                          await refresh(business.id);
                          setNotice({
                            message: `${nick || member.full_name || "Staff member"} is now ${value}.`,
                            tone: "good",
                          });
                        })
                      }
                    />
                    <div className={styles.memberActions}>
                      <button
                        className={styles.linkButton}
                        id={`member_status_${member.id}`}
                        disabled={busyAction !== null}
                        onClick={() =>
                          run(`status-${member.id}`, async () => {
                            await changeMemberStatus(
                              business.id,
                              member.id,
                              member.status === "active" ? "suspended" : "active",
                            );
                            await refresh(business.id);
                          })
                        }
                      >
                        {member.status === "active" ? "Suspend" : "Let them back in"}
                      </button>
                      <button
                        className={styles.dangerLink}
                        id={`member_remove_${member.id}`}
                        disabled={busyAction !== null}
                        onClick={() =>
                          run(`remove-${member.id}`, async () => {
                            await removeMember(business.id, member.id);
                            await refresh(business.id);
                            setNotice({
                              message: `${nick || member.full_name || "Staff member"} no longer has access.`,
                              tone: "good",
                            });
                          })
                        }
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {people.length < members.length ? (
            <p className={styles.note}>
              {members.length - people.length} removed. They no longer have access, and their record is
              kept for the audit trail.
            </p>
          ) : null}
        </Card>

        <Card title="Invitations sent">
          {issued.length === 0 ? (
            <p className={styles.note}>Nothing outstanding.</p>
          ) : (
            <ul className={styles.list}>
              {issued.map((invitation) => {
                const nick =
                  nicknames[invitation.id] ||
                  (invitation.phone && nicknames[invitation.phone]) ||
                  (invitation.email && nicknames[invitation.email]);
                return (
                  <li key={invitation.id} className={styles.row}>
                    <div>
                      <span className={styles.rowName}>
                        {nick ? `${nick} (${invitation.role_name})` : invitation.role_name}
                      </span>
                      <span className={styles.rowMeta}>
                        {invitation.phone ?? invitation.email ?? "no contact"} -{" "}
                        {invitation.accepted_at
                          ? "accepted"
                          : `expires ${new Date(invitation.expires_at).toLocaleDateString()}`}
                      </span>
                    </div>
                    <Pill tone={invitation.accepted_at ? "good" : "warn"}>
                      {invitation.accepted_at ? "Accepted" : "Waiting"}
                    </Pill>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      {notice ? (
        <Toast
          message={notice.message}
          hint={notice.hint}
          tone={notice.tone}
          onDismiss={() => setNotice(null)}
        />
      ) : null}

      {/* Taking somebody off the team is the one action on this screen that removes a person's livelihood
          with a tap, and it is done on a phone that is often in somebody else's hand. */}
      <PinGate
        open={gated !== null}
        reason="remove somebody from the team"
        onConfirmed={() => {
          gated?.run();
          setGated(null);
        }}
        onClose={() => setGated(null)}
      />
    </main>
  );
}

/** Re-exported so the type is visible where the page is read. */
export type { AcceptedInvitation, ApiError };
