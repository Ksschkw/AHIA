# AHIA mobile

The phone app, for the trader who is standing in the market with a customer waiting.

## What it is

**The same backend, the same endpoints, the same account.** Nothing is duplicated for mobile: sign-in is
`POST /api/v1/auth/login`, and every authenticated call carries `Authorization: Bearer <access token>` - a path
the API has always supported, and which its own `authenticate_request` checks before it looks for the session
cookie a browser would send.

The only thing that differs is **where the credential is kept**: the refresh token goes to the device keychain
or keystore (`expo-secure-store`), and the access token lives in memory. See `lib/session.ts`, which also says
plainly what that does and does not protect against.

## Getting it running

Dependencies are resolved by Expo rather than pinned by hand, because only Expo knows which `react-native` and
`react` a given SDK expects:

    cd mobile
    npm install
    npx expo install expo-router expo-secure-store expo-sqlite expo-status-bar react-native react react-dom
    npx expo start

Then press `a` for an Android emulator or device, or `i` for iOS on a Mac.

## Status, honestly

The foundation is committed and **has not been run**: this environment cannot install the dependencies (its npm
cache is read-only and the Node version here trips the scaffolder), so the code has been written but never
type-checked on a device. The first person to run `npm install` should expect to fix something small, and the
sign-in screen is deliberately the only screen until that is done.

## Releases he can test

Android: a workflow builds an APK and attaches it to a **GitHub Release**, so it is a download and an install -
no store, no account, no waiting. iOS cannot work that way: Apple allows TestFlight or an Ad Hoc build with
registered device identifiers, and the plan says so rather than promising a download that cannot exist.

## What comes next, in order

1. The shelf, read from the local store, with the outbox that makes "sell one" work with no signal.
2. The lists workbench and dispatch - where the money story lives.
3. Push notifications, after the web service worker.
