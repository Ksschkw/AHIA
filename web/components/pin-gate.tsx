"use client";

/**
 * The question a sensitive action asks before it happens.
 *
 * It is deliberately a question and not a lock screen: the app stays open, a trader keeps using it, and only
 * the things that change money or people stop to ask who is holding the phone. Asking for a PIN to open the
 * app would be a tax on every glance at the shelf; asking for it before a price changes costs one moment and
 * prevents the case this exists for.
 */

import { useState } from "react";

import { hasDevicePin, setDevicePin, SHORTEST_PIN, verifyDevicePin } from "@/lib/device-pin";
import { Button, Field, Sheet } from "@/components/ui";

export function PinGate({
  open,
  reason,
  onConfirmed,
  onClose,
}: {
  open: boolean;
  /** What is about to happen, in the trader's words: "change a price", "remove somebody from the team". */
  reason: string;
  onConfirmed: () => void;
  onClose: () => void;
}) {
  const [pin, setPin] = useState("");
  const [confirming, setConfirming] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setting = !hasDevicePin();

  async function proceed() {
    setProblem(null);
    if (pin.length < SHORTEST_PIN) {
      setProblem(`A PIN needs at least ${SHORTEST_PIN} digits.`);
      return;
    }
    setBusy(true);
    try {
      if (setting) {
        if (pin !== confirming) {
          setProblem("The two did not match.");
          return;
        }
        await setDevicePin(pin);
        setPin("");
        setConfirming("");
        onConfirmed();
        return;
      }
      if (await verifyDevicePin(pin)) {
        setPin("");
        onConfirmed();
        return;
      }
      // Deliberately not "wrong PIN" with a count of attempts: a person who mistyped knows they mistyped,
      // and a person who did not should learn nothing about how close they were.
      setProblem("That is not the PIN for this phone.");
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} title={setting ? "Set a PIN for this phone" : "Enter your PIN"} onClose={onClose}>
      <p style={{ fontSize: 14, color: "var(--ink-2)", marginBottom: 12 }}>
        {setting
          ? `You are about to ${reason}. Put a PIN on this phone and it will be asked for whenever something like that is done.`
          : `Enter your PIN to ${reason}.`}
      </p>
      <Field
        label="PIN"
        id="device-pin"
        value={pin}
        onChange={setPin}
        type="password"
        inputMode="numeric"
        autoComplete="off"
      />
      {setting ? (
        <Field
          label="PIN again"
          id="device-pin-again"
          value={confirming}
          onChange={setConfirming}
          type="password"
          inputMode="numeric"
          autoComplete="off"
        />
      ) : null}
      {problem ? <p style={{ fontSize: 14, color: "var(--danger)", marginBottom: 8 }}>{problem}</p> : null}
      <Button full busy={busy} onClick={() => void proceed()}>
        {setting ? "Set it and continue" : "Continue"}
      </Button>
      {setting ? (
        <p style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 8 }}>
          This keeps an assistant or a customer from changing your prices while you are holding the shelf.
          It is not a password and it does not protect the account: your sign-in does that.
        </p>
      ) : null}
    </Sheet>
  );
}
