"""Allowlisted, recoverable storage cleanup. Never accepts paths or shell commands."""
import errno
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


def run(*args):
    result = subprocess.run(args, cwd=Path.home(), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError((result.stderr.strip() or result.stdout.strip() or
                            f"{args[0]} failed.")[-1200:])
    return result.stdout.strip()


def location(name, fallback):
    return Path(os.path.abspath(Path(os.environ.get(name) or fallback).expanduser()))


def catalog():
    home = Path.home()
    cache = location("XDG_CACHE_HOME", home / ".local/cache")
    data = location("XDG_DATA_HOME", home / ".local/share")
    cargo = location("CARGO_HOME", data / "cargo")
    mise_data = location("MISE_DATA_DIR", data / "mise")
    # Each path has one owner. No blanket XDG cache or app-profile deletion.
    return [
        dict(id="pacman", admin=True, title="System packages", detail="Removes offline rollback copies.", command=["pkexec", "/usr/bin/paccache", "--remove", "--keep", "0"], requires=["pkexec", "paccache"]),
        dict(id="paru", title="AUR packages", detail="Archives only; keeps source edits.", paths=[cache / "paru"], archives=True),
        dict(id="mise-cache", title="Mise cache", detail="Keeps installed tools.", paths=[location("MISE_CACHE_DIR", cache / "mise"), mise_data / "downloads"]),
        dict(id="npm", title="npm cache", detail="Downloaded packages.", paths=[location("npm_config_cache", cache / "npm") / "_cacache"]),
        dict(id="pnpm", title="pnpm store", detail="Unused packages only.", command=["pnpm", "store", "prune"]),
        dict(id="bun", title="Bun cache", detail="Downloaded packages.", command=["bun", "pm", "cache", "rm"]),
        dict(id="pip", title="pip cache", detail="Downloaded packages & wheels.", paths=[location("PIP_CACHE_DIR", cache / "pip")]),
        dict(id="uv", title="uv cache", detail="Keeps environments.", command=["uv", "cache", "clean"]),
        dict(id="cargo", title="Cargo cache", detail="Crate archives only.", paths=[cargo / "registry/cache"]),
        dict(id="browser", title="Browser cache", detail="Close browsers first.", paths=[cache / "google-chrome", cache / "chromium", cache / "mozilla", home / ".var/app/com.google.Chrome/cache/google-chrome", home / ".var/app/org.chromium.Chromium/cache/chromium", home / ".var/app/org.mozilla.firefox/cache/mozilla"]),
        dict(id="thumbnails", title="Thumbnails & shaders", detail="Previews & shaders rebuild as needed.", paths=[cache / "thumbnails", cache / "mesa_shader_cache", cache / "mesa_shader_cache_db", cache / "mesa_shader_cache_sf", cache / "nvidia/GLCache"]),
        dict(id="podman", title="Podman images", detail="Unused registry images only.", command=["podman"], special="podman"),
        dict(id="flatpak-user", title="Flatpak runtimes · user", detail="Unused runtimes only.", command=["flatpak", "uninstall", "--user", "--unused", "--noninteractive"]),
        dict(id="flatpak-system", admin=True, title="Flatpak runtimes · system", detail="Unused runtimes only.", command=["flatpak", "uninstall", "--system", "--unused", "--noninteractive"]),
        dict(id="mise-unused", title="Unused Mise versions", detail="One-off versions may need reinstalling.", command=["mise", "prune", "--tools", "--yes"], group="Installed tools"),
        dict(id="mise-tools", title="All Mise tools", detail="Run mise install to restore tools.", command=["mise", "uninstall", "--all", "--yes"], group="Installed tools"),
    ]


def inventory():
    rows = []
    for entry in catalog():
        needed = entry.get("requires", entry.get("command", [])[:1])
        available = all(shutil.which(tool) for tool in needed) if needed else any(p.exists() and not p.is_symlink() for p in entry["paths"])
        rows.append({key: entry[key] for key in ("id", "title", "detail")} |
                    dict(group=entry.get("group", "Caches and downloads"), available=bool(available), admin=entry.get("admin", False)))
    return rows


def clear_path(path, archives=False):
    # Open every ancestor without following symlinks, then operate by directory fd.
    # A redirected cache must never turn into a traversal of personal files.
    path = Path(os.path.abspath(path))
    protected = [Path.home(), location("XDG_CONFIG_HOME", Path.home() / ".config"),
                 location("XDG_DATA_HOME", Path.home() / ".local/share")]
    if path == Path("/") or any(path == item or path in item.parents for item in protected):
        raise ValueError("Refusing to remove a home, configuration or data directory.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in path.absolute().parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        clear_directory(fd, archives)
    except FileNotFoundError:
        pass
    finally:
        os.close(fd)


def clear_directory(fd, archives=False):
    for name in os.listdir(fd):
        try:
            if archives:
                try:
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError as error:
                    if error.errno not in (errno.ENOTDIR, errno.ELOOP):
                        raise
                    if re.fullmatch(r".+\.pkg\.tar\.(?:zst|xz|gz|bz2)(?:\.sig)?", name):
                        os.unlink(name, dir_fd=fd)
                else:
                    try:
                        clear_directory(child, True)
                    finally:
                        os.close(child)
            else:
                # shutil's fd-based implementation prevents symlink substitution.
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise RuntimeError("Safe cache removal is unavailable on this platform.")
                try:
                    shutil.rmtree(name, dir_fd=fd)
                except NotADirectoryError:
                    os.unlink(name, dir_fd=fd)
                except OSError:
                    # rmtree rejects symlinks; unlink only the link itself.
                    if stat.S_ISLNK(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                        os.unlink(name, dir_fd=fd)
                    else:
                        raise
        except FileNotFoundError:
            pass


def podman_images():
    images = json.loads(run("podman", "images", "--no-trunc", "--format", "json"))
    candidates = []
    for image in images:
        identity = image.get("Id") or image.get("ID") or image.get("id", "")
        if not re.fullmatch(r"(?:sha256:)?[a-f0-9]{64}", identity):
            continue
        records = json.loads(run("podman", "image", "inspect", identity))
        if not records or not records[0].get("RepoDigests"):
            continue
        # Ancestor includes derived-image users and stopped containers too.
        if run("podman", "ps", "--all", "--quiet", "--filter", "ancestor=" + identity):
            continue
        candidates.append(identity)
    for identity in dict.fromkeys(candidates):
        # Never force: Podman rechecks container use/dependent images at removal.
        run("podman", "rmi", identity)


def failure_message(error):
    """Keep terminal diagnostics out of desktop notifications."""
    text = str(error).lower()
    if isinstance(error, subprocess.TimeoutExpired):
        return "Cleanup took too long. Try again."
    if any(word in text for word in ("not authorized", "not authorised", "authentication", "authorization", "cancelled", "canceled")):
        return "Administrator approval was not granted. Try again and approve the authentication request."
    if isinstance(error, PermissionError) or "permission denied" in text:
        return "Some cached files could not be removed because you do not have permission."
    if isinstance(error, FileNotFoundError):
        return "The cleanup tool is no longer available. Install it and try again."
    if isinstance(error, OSError) and error.errno in (errno.ELOOP, errno.ENOTDIR):
        return "The cache location points elsewhere and was left untouched."
    if "refusing to remove" in text:
        return "The cache location includes personal settings or data and was left untouched."
    return "Cleanup could not finish. Try again."


def clean(selected, emit):
    entries = {row["id"]: row for row in catalog()}
    if (not isinstance(selected, list) or not selected or
            any(not isinstance(key, str) or key not in entries for key in selected) or
            len(selected) != len(set(selected))):
        raise ValueError("Choose valid cleanup categories.")
    if "mise-tools" in selected and "mise-unused" in selected:
        selected = [key for key in selected if key != "mise-unused"]
    # Remove runtimes last, even when their checkbox was selected first.
    selected = [key for key in entries if key in selected]
    results = []
    for key in selected:
        entry = entries[key]
        emit(dict(progress=entry["title"]))
        try:
            if entry.get("special") == "podman":
                podman_images()
            elif "command" in entry:
                run(*entry["command"])
            else:
                for path in dict.fromkeys(entry["paths"]):
                    clear_path(path, entry.get("archives", False))
            results.append(dict(id=key, title=entry["title"], ok=True))
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            results.append(dict(id=key, title=entry["title"], ok=False, error=failure_message(error)))
    return dict(ok=all(row["ok"] for row in results), results=results)


def main():
    def emit(value):
        print(json.dumps(value), flush=True)
    try:
        request = json.loads(sys.stdin.readline())
        if request.get("op") == "scan":
            emit(dict(ok=True, entries=inventory()))
        elif request.get("op") == "clean":
            emit(clean(request.get("selected"), emit))
        else:
            raise ValueError("Unknown cleanup operation.")
    except (OSError, ValueError, RuntimeError) as error:
        emit(dict(ok=False, error=failure_message(error)))


if __name__ == "__main__":
    main()
