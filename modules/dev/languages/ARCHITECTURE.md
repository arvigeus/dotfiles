# Language toolchains

The Go module sets `GOPATH` to `$XDG_DATA_HOME/go`, so the default module cache
and `go install` binaries live there. Its build cache uses `$XDG_CACHE_HOME/go-build`;
the Go environment file remains under `$XDG_CONFIG_HOME/go`.
