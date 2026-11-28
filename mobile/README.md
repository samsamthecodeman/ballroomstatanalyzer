# Ballroom Stats Analyzer mobile

Expo / React Native / TypeScript client for the hosted website, targeting iOS and Android.

## Implementation status

Implemented: native individual/couple search and three-character suggestions; combined BCE/O2CM statistics; cancellable searches; multiple-style, competition, category and uncontested filters; sortable results; native Texas/national individual/couple leaderboards; light/dark appearance; saved account profiles; and Google/Apple OAuth with PKCE, system-browser login, cold/warm callbacks, encrypted mobile sessions, refresh and sign-out.

The Explore tab embeds the full hosted dashboard for comparisons, proficiency points and upcoming schedules. CSV/PDF downloads open the website in the system browser; the search may need to be repeated because web and native sessions are independent.

**Not yet provisioned:** Supabase project, Google/Apple provider credentials, Expo project/signing, installable IPA/APK, physical-device verification, TestFlight or store listings. JavaScript bundles are not installable applications. Public results work without sign-in; account buttons require the public Supabase configuration below.

Account deletion and secure Apple credential storage are implemented: users sign in again, type DELETE, and confirm a short-lived request. Apple authorization is revoked before the app account and saved profile are removed. The credential is encrypted in a server-only Supabase table and is excluded from persistent mobile sessions. See [the account flow](ACCOUNT-DELETION-PROPOSAL.md) and [server deployment instructions](../supabase/README.md).

**Deployment still required:** apply both migrations, deploy the account Edge Function and configure its server secrets before enabling Apple login. Physical-device/provider checks and published privacy/support/deletion information remain prerequisites for store submission. This is a development app, not a store-ready release.

## Development

Use Node 22. From this directory:

```powershell
npm ci
Copy-Item .env.example .env
npm run typecheck
npm test
npm run doctor
npm run bundle
npx expo start --dev-client
```

OAuth needs an installed development build with the app's registered scheme; Expo Go does not provide this callback identity. Native requests go directly to `https://bsa.sam-moran.com`, sharing the website's existing cache and traffic limits.

For a browser layout/API preview, start the existing Docker website on `127.0.0.1:8765`, then:

```powershell
npm run preview:build
npm run preview
```

Open `http://127.0.0.1:8081`. This local-only server proxies a fixed list of public API endpoints. Login intentionally requires a native build. Native apps never depend on this preview server.

## Supabase

1. Create a project in your Supabase account, choosing region and plan deliberately.
2. Apply both files in `../supabase/migrations/` in order, or link your project and use `supabase db push` from the repository root. They create account-scoped profiles and server-only encrypted credential/confirmation storage; public results are unaffected.
3. Fill in `mobile/.env`:

   ```dotenv
   EXPO_PUBLIC_API_URL=https://bsa.sam-moran.com
   EXPO_PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
   EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=YOUR-PUBLISHABLE-KEY
   ```

   These values are embedded in the app. Use only the publishable key. Never embed service-role keys, Google client secrets, Apple private keys/client secrets or provider refresh tokens. The local `.env` is ignored by Git.

4. In **Authentication → URL Configuration**, add this exact additional redirect URL:

   ```text
   com.sammoran.ballroomstats://auth/callback
   ```

5. Configure both providers below and follow [account-function deployment](../supabase/README.md). Set the public mobile environment values in your EAS build environment before cloud builds; do not assume an ignored local `.env` is uploaded. Server signing/encryption secrets belong only in Supabase Edge Function secrets.

The app scheme, iOS bundle ID and Android package default to `com.sammoran.ballroomstats`. Verify these identifiers belong to your accounts before registering. If changing them, update `app.json`, `src/auth.ts`, `src/results.ts`, callback tests and the Supabase allow list together.

### Google

Configure the OAuth consent screen in Google Cloud, including support contact, privacy URL and test users. Create a **Web application** OAuth client for Supabase's hosted exchange. Register this authorized redirect URI:

```text
https://YOUR-PROJECT.supabase.co/auth/v1/callback
```

Enable Google in Supabase Authentication Providers and enter the client ID and secret **there**, not in the app. Test both native platforms. This implementation uses browser OAuth, not the native Google SDK.

Reference: [Supabase Google sign-in](https://supabase.com/docs/guides/auth/social-sign-in/auth-google).

### Apple

Register the bundle ID with Sign in with Apple enabled in Apple Developer. Create an associated **Services ID** for browser OAuth, register the Supabase authentication domain and exact callback URI above, and create a Sign in with Apple key. Generate a client-secret JWT from the team ID, key ID, Services ID and `.p8` signing key, then configure the Apple provider in Supabase. Keep signing material out of the repository and app.

The iOS app displays Apple's native button; authentication uses the system browser on both platforms. The user's full name is not assumed to be returned. Saved dancer selection is independent of login identity. Test ordinary email and Hide My Email. Rotate Apple's OAuth client secret before its six-month expiry.

References: [Supabase Apple sign-in](https://supabase.com/docs/guides/auth/social-sign-in/auth-apple), [Expo authentication](https://docs.expo.dev/guides/authentication/).

## Signed builds

Using your own Expo account:

```powershell
npx eas-cli login
npx eas-cli init
npx eas-cli build --profile development --platform android
npx eas-cli build --profile development --platform ios
```

Apple Developer signing/provisioning is needed for iOS device and TestFlight builds. Google Play distribution requires a Play developer account. Review Expo build quotas/costs before launching cloud builds.

`--profile preview --platform android` produces an internally installable APK. Production builds use `--profile production` (Android AAB / signed iOS distribution). Complete the release blockers before `eas submit`.

## Verification and release

- Run type checks, mobile tests, Expo dependency checks, `npm audit`, and all-platform bundling.
- Run `../supabase/tests/bootstrap.sql`, both migrations, then `../supabase/tests/profiles.sql` and `../supabase/tests/account_security.sql` **only in an isolated PostgreSQL database**. Never run the test bootstrap on a real Supabase project. Run Edge Function tests using the commands in `../supabase/README.md`.
- On physical iOS and Android devices, test guest search/cancellation, both providers, cancelled/denied login, warm/cold callbacks, session restore, sign-out, two-device profile sync, cross-account isolation and offline recovery.
- On signed devices, verify typed confirmation, cancellation, wrong-account reauthentication, Apple failure/retry and successful cleanup with dedicated test accounts. Publish reviewed privacy, support and account-deletion information. Complete App Privacy and Google Play Data Safety disclosures for identity, saved-profile data and encrypted Apple revocation credentials. No advertising/analytics SDK is included.
- Review provider button branding, accessibility, screenshots, app identifiers and signing before release.

`@expo/fingerprint` has a scoped `minimatch` override to avoid a known vulnerable older major. Recheck native fingerprint generation and bundling when updating dependencies.
