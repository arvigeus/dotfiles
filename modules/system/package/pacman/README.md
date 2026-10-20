# Package maintenance

After package transactions, hooks report orphan packages and services still
using replaced executable files. They do not remove packages or restart services.

Review orphans with `pacman -Qtd`. Keep a wanted dependency with
`sudo pacman -D --asexplicit <package>`.

[Topgrade](../topgrade/README.md) offers interactive removal and service restarts
after updating, with Meld configuration review before restarts. Run
`package-maintenance` to repeat that review independently.
See [implementation notes](ARCHITECTURE.md) for hook behavior.
