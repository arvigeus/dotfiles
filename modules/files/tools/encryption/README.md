# Encryption tools

Use **Open with → Encryption tools**, the launcher, or `encryption-tools PATH…`.

Encrypt with recipient keys or a password, sign (including detached signatures),
sign and encrypt, decrypt, verify signatures, and inspect/import key files. Your
existing GnuPG identities appear in the app; GnuPG's secure prompt handles
passphrases. Importing keys leaves owner trust unchanged.

Folders become tar archives before encryption/signing. Decrypting restores the
archive without extracting it; open it with Ark. Originals are kept and existing
outputs are never overwritten. Detached signatures require an original file for
verification; select it in the Verify tab.

See [ARCHITECTURE.md](ARCHITECTURE.md) for key and process handling.
