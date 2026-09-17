/**
 * What a person reads when something goes wrong.
 *
 * The API answers with a code, a safe message and a correlation ID. That is the right shape for an
 * engineer and the wrong shape for a trader: "INVALID_CREDENTIALS: Invalid credentials.
 * (correlation id 16024ab1a8f6427abd47f002b3f38744)" is a sentence that tells them nothing they can
 * act on and makes the product look broken.
 *
 * So there are two views here, like the backend has two views of the same error:
 *
 * - **the sentence**, which says what happened and what to do about it, in the smallest number of
 *   words that is actually true;
 * - **the reference**, the correlation ID, which is real and useful - to support, when somebody
 *   quotes it - and is therefore shown *next to* the sentence rather than inside it, understated
 *   enough that nobody reads it as part of the message.
 *
 * The mapping is exhaustive over the codes the API can return, and anything unmapped falls back to a
 * sentence that is honest about not knowing more.
 */

import { ApiError } from "./api";

type Explanation = {
  /** One sentence, in the second person, that a trader can act on. */
  message: string;
  /** A shorter nudge, when there is something specific to do next. */
  hint?: string;
};

const BY_CODE: Record<string, Explanation> = {
  INVALID_CREDENTIALS: {
    message: "That email, phone number and password do not match.",
    hint: "Check the spelling, or create an account if you are new here.",
  },
  UNAUTHENTICATED: {
    message: "You have been signed out.",
    hint: "Sign in again to carry on.",
  },
  FORBIDDEN: {
    message: "You do not have permission to do that.",
    hint: "Ask the owner of the business to give you access.",
  },
  NOT_FOUND: {
    message: "We could not find that.",
    hint: "It may have been removed, or the link may be wrong.",
  },
  CONFLICT: {
    message: "That is already taken.",
    hint: "Try a different name or address.",
  },
  INVALID_REQUEST: {
    message: "Some of what you entered is not right.",
    hint: "Check the highlighted fields and try again.",
  },
  INVALID_MEDIA: {
    message: "That file cannot be used.",
    hint: "Use a JPEG, PNG, WebP or AVIF image.",
  },
  BUSINESS_RULE_VIOLATION: {
    message: "That is not allowed for this business.",
    hint: "Check the details and try again.",
  },
  RESOURCE_LIMIT_EXCEEDED: {
    message: "This business has reached its limit.",
    hint: "Remove something you no longer need, or ask us to raise it.",
  },
  STORAGE_QUOTA_EXCEEDED: {
    message: "There is no room left for more photos.",
    hint: "Delete some photos and try again.",
  },
  RATE_LIMITED: {
    message: "Too many attempts in a row.",
    hint: "Wait a minute, then try again.",
  },
  DEPENDENCY_UNAVAILABLE: { message: "A service we rely on is not answering." },
  STORAGE_UNAVAILABLE: { message: "The photo service is not answering." },
  DEPENDENCY_TIMEOUT: { message: "That took too long and was stopped." },
  DEPENDENCY_BUSY: { message: "The service is busy. Try again in a moment." },
  STORAGE_ERROR: { message: "The photo could not be saved. Try again." },
  UNREACHABLE: {
    message: "We could not reach the server.",
    hint: "Check your connection - what you typed is still here.",
  },
  INTERNAL_ERROR: {
    message: "Something went wrong on our side.",
    hint: "Try again. If it keeps happening, send us the reference below.",
  },
  CONFIGURATION_ERROR: { message: "Something went wrong on our side." },
  UNKNOWN: { message: "Something went wrong. Try again." },
};

export type Explained = {
  message: string;
  hint?: string;
  /** Shown as a small reference, not as part of the sentence. */
  reference?: string;
};

export function explainFailure(error: unknown): Explained {
  if (error instanceof ApiError) {
    const known = BY_CODE[error.code] ?? BY_CODE.UNKNOWN;
    return {
      message: known.message,
      hint: known.hint,
      // A correlation ID is worth quoting only when the cause is ours; for a wrong password it is
      // noise, and showing it invites the reader to think the problem is theirs to decode.
      reference:
        error.code === "INTERNAL_ERROR" || error.code === "UNKNOWN" || error.status >= 500
          ? (error.correlationId ?? undefined)
          : undefined,
    };
  }
  if (error instanceof Error) {
    // A sentence a screen wrote for itself (a name already taken, a password that does not match) is
    // already in the second person, and is passed through unchanged.
    return { message: error.message };
  }
  return { message: BY_CODE.UNKNOWN.message };
}
