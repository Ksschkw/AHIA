# AHIA mobile

The phone app, for the trader who is standing in the market with a customer waiting.

## What it is

**The same backend, the same endpoints, the same account.** Sign-in is `POST /api/v1/auth/login`, and every
authenticated call carries `Authorization: Bearer <access token>` - a path the API has always supported, and
which its own `authenticate_request` checks before it looks for the session cookie a browser would send.

What differs is **where the credential is kept**: the refresh token goes to the device keychain or keystore
(`expo-secure-store`), and the access token lives in memory. See `lib/session.ts`, which also says plainly what
that protects against and what it does not.

## Running it

    cd mobile
    npm install
    npx expo start

Then press `a` for an Android emulator or device, `i` for iOS on a Mac.

**No `npx expo install` step, and that is deliberate.** It resolves versions by asking Expo's API, which times
out on a slow connection - and it is not needed, because every version this app wants is already pinned in
`package.json` **from the list Expo ships inside the `expo` package** (`bundledNativeModules.json`). That list is
the authority: `npm view react-native version` says 0.87.1, and SDK 57 wants **0.86.3**. A version matrix kept
in somebody's head is a build failure waiting to happen.

## Status, honestly

The foundation is committed and **has not yet run on a device**: the environment this was written in cannot
install the dependencies, so the code is written but never bundled. The sign-in screen is deliberately the only
screen until it does, because a foundation that does not run is not a foundation.

## Releases he can test

Android: a workflow builds an APK and attaches it to a **GitHub Release** - a download and an install, no store
and no account. iOS cannot work that way: Apple allows TestFlight or an Ad Hoc build with registered device
identifiers, and this says so rather than promising a download that cannot exist.

## What comes next, in order

1. The shelf, read from the local store, with the outbox that makes "sell one" work with no signal.
2. The lists workbench and dispatch - where the money story lives.
3. Push notifications, after the web service worker.
