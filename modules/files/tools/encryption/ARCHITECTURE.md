# Encryption tools implementation

`encryption_tasks.py` invokes the existing GnuPG installation/keyring. Startup
reads public and secret key listings asynchronously using machine-readable colon
records; revoked/expired/invalid/disabled primary keys are omitted. Recipients and
signing controls pass full fingerprints as distinct argv entries, with no shell.
Native GnuPG trust checks remain active. Sign/encrypt select the chosen identity;
agent/pinentry owns passphrases, without loopback mode, password fields, command
line secrets or automatic owner-trust elevation.

Directory inputs become tar files inside a private output staging directory,
with symlinks archived as links. Output-inside-source directories and detached
folder signatures are rejected. Decryption publishes bytes as a file, and never
extracts paths supplied by an archive. Verification uses GnuPG's exit status and
status diagnostics; failures stay visible. Import is an explicit operation;
key inspection and normal opening never import or change trust. The key lists
refresh after an import.

See the [shared runtime](../common/ARCHITECTURE.md) for cancellation/publication.
Isolated GnuPG tests generate temporary keys and prove encryption/decryption,
detached signature verification/tamper detection and unchanged import owner trust.
