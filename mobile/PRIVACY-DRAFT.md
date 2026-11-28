# Mobile privacy notice — owner review required

This is an unpublished draft. Add the responsible operator, privacy/support contact, effective date, retention periods, deletion procedures and jurisdiction-specific disclosures before distribution.

The app retrieves public competition results from the hosted Ballroom Stats Analyzer service, using Ballroom Comp Express and O2CM results. Search terms and a randomly generated installation-specific visitor ID are sent to that service for retrieval and traffic limits. A public dancer name is not a verified identity claim.

Optional Google/Apple sign-in uses Supabase. Supabase processes the account identity, email where supplied, and app authentication session. On installed mobile apps the session is stored with encrypted operating-system storage. Provider passwords are entered in system-browser login flows, not an app form.

A signed-in user may save a public dancer name and optional BCE ID to their account. Database policies restrict access to that profile to its owner. The Explore tab displays the website and external scoresheet links under those sites' existing policies.

No advertising or analytics SDK is included. Hosting providers and Supabase may maintain operational/security logs. This draft does not promise that no such logs exist.

For Apple sign-in, an authorization credential is sent over HTTPS to the app owner's Supabase account-management function. Its Apple identity is checked and the credential is encrypted in server-only database storage. Encryption/signing keys are kept outside the database in server secrets. The app does not persist provider tokens in its mobile session storage.

Signed-in users can request deletion in Account settings after fresh sign-in and typing DELETE. The server revokes Apple authorization first, then permanently removes the app account, saved profile and private credential records. Public competition results remain public. If revocation fails, the account is retained for retry; if revocation succeeds but account removal fails, the encrypted credential is erased and a private revocation receipt supports retry.

Operational logs and encrypted records in hosting backups may remain under the provider's retention policy. Set and disclose actual retention periods and support/deletion contact information before publishing this notice. Real provider/device verification is required after the Supabase account-management function is deployed.
