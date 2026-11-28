# Account deletion and Apple revocation — approval pending

This is a reviewable design, not implemented behavior. The current app does not forward or persist Apple/Google provider refresh tokens; its storage adapter excludes them from persisted app sessions.

Proposed operation, requiring explicit approval:

1. After Apple OAuth, transmit Apple's provider refresh token over HTTPS to an authenticated **Supabase Edge Function in the app owner's Supabase project**. Use it solely to support authorization revocation when the app user requests account deletion.
2. Verify the caller's Supabase JWT with the auth service. Exchange/validate the Apple token server-side and verify that Apple's subject matches the Apple identity attached to that caller. A different user's token must never be accepted.
3. Encrypt the provider token in the project's server-only secret storage, indexed by that user's ID. No client-readable database policy, client bundle, analytics event, error log, or browser dashboard may expose it. Apple private signing keys and Supabase administrative credentials remain server-only.
4. Add Delete account to Account settings. Require fresh authentication and an explicit destructive-action confirmation. The signed-in user may request deletion only of their own account.
5. Revoke that user's Apple authorization through Apple's official revocation endpoint before deleting the Supabase account and its saved profile. If revocation fails, retain the account so the user can retry. Public competition results are unaffected. Google accounts require deletion of the app account, without deleting the user's Google identity.
6. Implement rate limiting, failure/retry handling, no-token logging, profile cleanup, and tests proving caller/subject isolation. Publish retention and deletion information before store submission.

Risks: this adds persistent storage of a sensitive provider credential to the owner's Supabase backend and an irreversible account-deletion operation when the app user explicitly confirms it. The provider token could be misused if that backend's secrets were compromised. Administrative credentials must not be embedded in the app.

Automatic approval review rejected the initial code proposal because provider-token handling and account deletion had not been explicitly approved. Approval of this design would authorize implementing these controls; no actual user account would be deleted as part of development or testing.
