# Language toolchains

The Node.js module sets `PNPM_HOME` to `$XDG_DATA_HOME/pnpm` and adds
`$PNPM_HOME/bin` to PATH through environment.d for login shells and user services.
pnpm 11 and newer keep global executables in that `bin` subdirectory. The system
package owns pnpm itself; `pnpm setup` is unnecessary.

The Go module sets `GOPATH` to `$XDG_DATA_HOME/go`, so the default module cache
and `go install` binaries live there. Its build cache uses `$XDG_CACHE_HOME/go-build`;
the Go environment file remains under `$XDG_CONFIG_HOME/go`.
