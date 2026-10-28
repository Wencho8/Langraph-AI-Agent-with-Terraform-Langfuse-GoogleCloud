# User approval

Registered accounts require approval before signing in. Users have two independent flags:

- `is_admin`: defaults to `false`; grants access to the user administration screen.
- `blocked`: defaults to `true`; prevents login, chat access, and model calls.

Registration creates a pending account without a session cookie. The form displays an approval message. Login checks the password before reporting that an account needs approval.

An approved administrator can open **Administrar usuarios**, list registered accounts, and approve or block them. The backend checks current administrator privileges on every action and requires the existing CSRF protection for changes. The dashboard cannot change administrator roles or block the current administrator's own account.

Blocking revokes the target user's sessions. Active chat streams check account/session access periodically and stop when access is revoked. Tokens already generated or an in-flight provider request may still have a cost. Approving an account requires a fresh login; it never restores revoked sessions.

## First deployment and administrator setup

Migration `0004_user_approval` adds both columns, blocks existing accounts, and revokes existing sessions. It preserves users and conversations. Nobody is automatically made an administrator.

After the migration, manually promote your own account from Cloud SQL using its normalized, lowercase username:

```sql
UPDATE public.users
SET is_admin = TRUE, blocked = FALSE
WHERE username = 'your_username'
RETURNING id, username, is_admin, blocked;
```

Confirm that exactly the intended account was returned, then sign in again. Other users remain blocked until approved. There is no administrator password or promotion endpoint in the application.

## Review and release

For local review, rebuild the backend/frontend, run `make migrate`, and restart the application using the existing Makefile commands. Apply the SQL above to the local database to test administration. This change does not apply a migration to your ordinary local database automatically.

A subsequent push to `main` changes both application components, so the existing workflow tests both, builds the backend image, runs the migration job, deploys the backend, and publishes the frontend. Review the Actions logs and verify pending registration, approval, login, blocking, and preserved history in production.

The first release changes an access policy: the previous backend image does not enforce these flags. Until the new backend is deployed, the previous revision can still allow login. Rolling back to a revision from before this feature also removes enforcement, even though the database columns remain. The pipeline does not automatically reverse database migrations.
