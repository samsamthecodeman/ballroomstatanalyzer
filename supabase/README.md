# Supabase mobile account management

This backend is separate from the hosted Python results service. The account function handles only the signed-in user's app account, saved profile and Apple revocation credential. It does not modify competition results.

## Deploy in your own project

1. Create/configure the project and Google/Apple providers using `../mobile/README.md`.
2. Apply both migrations in order. With the Supabase CLI from the repository root:

   ```powershell
   npx supabase@latest login
   npx supabase@latest link --project-ref YOUR_PROJECT_REF
   npx supabase@latest db push
   ```

3. Copy `functions/.env.example` to `functions/.env.local` and replace the placeholders **locally**. This file is ignored by Git. Do not share its values in chat or embed them in `EXPO_PUBLIC_` configuration.
4. Configure these Edge Function secrets:

   | Secret | Value |
   |---|---|
   | `APPLE_CLIENT_ID` | Apple Services ID used by the Supabase Apple provider |
   | `APPLE_TEAM_ID` | Your Apple developer team ID |
   | `APPLE_KEY_ID` | Sign in with Apple signing-key ID |
   | `APPLE_PRIVATE_KEY_BASE64` | Base64 of the `.p8` key file, kept server-side |
   | `ACCOUNT_TOKEN_ACTIVE_KEY` | Active encryption-key identifier, for example `key1` |
   | `ACCOUNT_TOKEN_KEYRING` | JSON mapping key identifiers to base64-encoded **random 32-byte keys** |

   Generate encryption keys using a cryptographically secure local tool such as `openssl rand -base64 32`. Retain the keyring in your secret manager. Do not use the signing key, a password or a predictable string as the encryption key.

   `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are provided in the hosted Supabase function environment. They must never be mobile environment variables. The service role is used only on the server for verified-user lookups, private RPCs and hard deletion of the caller's account.

5. Upload the secrets and deploy:

   ```powershell
   npx supabase@latest secrets set --env-file supabase/functions/.env.local
   npx supabase@latest functions deploy account
   ```

   Keep `verify_jwt = true` in `config.toml`; do not deploy with `--no-verify-jwt`. The function independently verifies the user against Supabase Auth as well. Install a newly built mobile client after configuration.

## Data and authorization

- `public.profiles` has owner-only RLS policies and references `auth.users` with cascading cleanup.
- `account_private.security` is outside client-accessible schemas, has RLS enabled and no client grants. Its only access path is a `SECURITY DEFINER` RPC whose execute privilege is restricted to `service_role`. Never expose this private schema through the Data API.
- Apple refresh tokens are verified at Apple's token endpoint. Apple's signed identity token must have the configured issuer/audience/signature and match the Apple identity attached to the authenticated Supabase user.
- AES-256-GCM uses a random 96-bit nonce and authenticated data binding ciphertext to its owner, Apple subject and envelope version. Database rows contain ciphertext, not signing/encryption keys. The mobile session adapter strips provider tokens before persistence.
- Saving a credential and deleting an account require an OAuth authentication-method timestamp no older than five minutes. A token refresh alone is insufficient. Apple credentials and revocation receipts are bound to that exact sign-in session and OAuth timestamp, so a receipt for an older grant cannot skip revocation after a new Apple login. Custom JWT hooks must retain Supabase's `amr` and `session_id` claims.
- A server-generated confirmation is hashed in storage, bound to the current user/session, expires after five minutes and is consumed once. The user must also submit the literal `DELETE`. A supplied user ID never selects the account to delete.
- Request limits and a two-minute database lease prevent overlapping deletion/credential changes across function instances.
- Revocation happens before Supabase's hard account deletion. Revoked ciphertext is erased immediately; a private receipt allows retry if hard deletion fails. Successful hard deletion cascades the saved profile and private security record.
- Raw provider responses, request bodies and credentials are neither logged nor returned. A failure before revocation retains the account and credential. After an unknown network outcome, verify the account state before attempting a new sign-in, which could create a new account.

The app currently supports one attached Apple identity per account. Missing/ambiguous identity data or missing credentials fail closed. Previously created Apple accounts must sign in again to capture a revocation credential. Google-only accounts require no Apple credential; stored credentials for a previously unlinked Apple identity are still revoked on deletion.

## Key rotation and recovery

Add a new random key to `ACCOUNT_TOKEN_KEYRING`, update `ACCOUNT_TOKEN_ACTIVE_KEY`, and redeploy/restart the function. Keep older keys available while any stored envelopes reference their IDs. Removing an old key before its records are re-encrypted or removed prevents those accounts from revoking authorization. Re-encryption must run in a trusted server environment; never download plaintext tokens to a client.

The function generates five-minute Apple client-secret JWTs from the server signing key. Supabase's own Apple OAuth provider still requires its separately configured client secret to be rotated before its expiry. Coordinate Services ID/signing-key changes with existing stored grants.

Review your Supabase backup/log retention and published privacy/deletion information. Use dedicated test accounts for provider/device verification; do not test destructive flows with a personal production account.

## Tests

```powershell
npx deno@latest check --config supabase/functions/account/deno.json supabase/functions/account/index.ts
npx deno@latest test --config supabase/functions/account/deno.json supabase/functions/account
cd mobile
npm test
npm run lint
npm run typecheck
```

For database tests, create a fresh, isolated PostgreSQL database with no real users. Run `tests/bootstrap.sql`, both migrations in order, `tests/profiles.sql`, then `tests/account_security.sql`. The bootstrap creates synthetic auth tables/roles and **must not run on a real Supabase project**. The final test deletes a synthetic user solely to verify cascading cleanup.

Edge tests stub Apple/Supabase operations, use generated signing keys, and verify confirmation isolation, revocation ordering, error redaction, encryption tamper detection, key rotation, retry behavior and fresh authentication. Signed iOS/Android tests against your configured providers remain required before release.
