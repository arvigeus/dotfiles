"""Load explicitly configured command packages without importing their code."""

import json
import re
import shlex
from pathlib import Path


class ProviderError(Exception):
    pass


def _path(value, base, description):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ProviderError(f"Command provider {description} must be a path.")
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _env(value):
    if not isinstance(value, dict) or not all(
        isinstance(key, str)
        and key
        and "=" not in key
        and "\0" not in key
        and isinstance(item, str)
        and "\0" not in item
        for key, item in value.items()
    ):
        raise ProviderError("Command provider env must map environment names to text values.")
    return value


def _env_file(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise ProviderError("Cannot read Command provider environment file.") from None
    values = {}
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, separator, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        try:
            if value.startswith(("'", '"')):
                parts = shlex.split(value, comments=True, posix=True)
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
                parts = [value] if value else []
                if any(c.isspace() for c in value):
                    raise ValueError()
        except ValueError:
            raise ProviderError(
                f"Invalid Command provider environment assignment on line {number}."
            ) from None
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or len(parts) > 1:
            raise ProviderError(
                f"Invalid Command provider environment assignment on line {number}."
            )
        # Values are literal: no variable, command, or shell expansion.
        values[key] = parts[0] if parts else ""
    return _env(values)


def configured_providers(config, base_dir=None):
    base = Path(base_dir or Path.cwd())
    rows = config.get("providers", [])
    if not isinstance(rows, list):
        raise ProviderError("Provider configuration providers must be a list.")
    providers, names = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderError("Each Command provider must be an object.")
        name = row.get("name")
        if not isinstance(name, str) or not name.strip() or any(ord(c) < 32 for c in name):
            raise ProviderError("Each Command provider needs a single-line name.")
        name = name.strip()
        if name in names:
            raise ProviderError("Command provider names must be unique.")
        command, root = row.get("command"), base
        if "plugin" in row:
            if "command" in row:
                raise ProviderError("Choose either a Command provider plugin or command.")
            root = _path(row["plugin"], base, "plugin").resolve()
            try:
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                raise ProviderError("Cannot read Command provider plugin manifest.") from None
            if (
                not isinstance(manifest, dict)
                or type(manifest.get("api_version")) is not int
                or manifest["api_version"] != 1
            ):
                raise ProviderError("Command provider plugin requires api_version 1.")
            command = manifest.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part and "\0" not in part for part in command)
        ):
            raise ProviderError("Each Command provider command must be a nonempty argument array.")
        if "plugin" in row:
            command = [part.replace("{plugin_dir}", str(root)) for part in command]
        env = _env_file(_path(row["env_file"], root, "env_file")) if "env_file" in row else {}
        env.update(_env(row.get("env", {})))
        names.add(name)
        providers.append({"name": name, "command": command, "env": env})
    return providers
