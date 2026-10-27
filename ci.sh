#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: ./ci.sh [--check|--fix]

Check formatting and source files without changing them (default), or format
supported files before running the same checks.
EOF
}

mode=check
case ${1:-} in
    '') ;;
    --check) mode=check ;;
    --fix) mode=fix ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { usage >&2; exit 2; }

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$repo_dir"

python_files=()
shell_files=()
qml_files=()
json_files=()
jsonc_files=()
mapfile -d '' -t repo_files < <(git ls-files -z --cached --others --exclude-standard)

for file in "${repo_files[@]}"; do
    [[ -f $file && ! -L $file ]] || continue
    case $file in
        *.py) python_files+=("$file") ;;
        *.qml) qml_files+=("$file") ;;
        *.json) json_files+=("$file") ;;
        *.jsonc) jsonc_files+=("$file") ;;
        *.sh|*.bash|*.bashrc) shell_files+=("$file") ;;
        *)
            if [[ -x $file ]]; then
                IFS= read -r shebang < "$file" || true
                if [[ $shebang =~ ^\#!.*(bash|dash|ksh|zsh|sh)([[:space:]]|$) ]]; then
                    shell_files+=("$file")
                fi
            fi
            ;;
    esac
done

require_tool() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'Missing required tool: %s\n' "$1" >&2
        return 1
    }
}

if ((${#python_files[@]})); then
    require_tool ruff
    if [[ $mode == fix ]]; then
        ruff format --config "format.quote-style = 'single'" "${python_files[@]}"
    fi
    ruff format --check --config "format.quote-style = 'single'" "${python_files[@]}"
    ruff check --output-format concise "${python_files[@]}"
fi

if ((${#shell_files[@]})); then
    require_tool shfmt
    require_tool shellcheck
    if [[ $mode == fix ]]; then
        shfmt -w -i 4 -ci -sr "${shell_files[@]}"
    fi
    shfmt -d -i 4 -ci -sr "${shell_files[@]}"
    for file in "${shell_files[@]}"; do
        bash -n "$file"
    done
    shellcheck "${shell_files[@]}"
fi

if ((${#qml_files[@]})); then
    require_tool qmlformat
    if [[ $mode == fix ]]; then
        qmlformat --newline unix --inplace "${qml_files[@]}"
    else
        formatted=$(mktemp)
        trap 'rm -f -- "$formatted"' EXIT
        formatting_failed=0
        for file in "${qml_files[@]}"; do
            qmlformat --newline unix "$file" > "$formatted"
            if ! cmp -s -- "$file" "$formatted"; then
                printf 'QML formatting required: %s\n' "$file" >&2
                formatting_failed=1
            fi
        done
        ((formatting_failed == 0)) || exit 1
    fi
fi

if ((${#json_files[@]})); then
    require_tool python3
    python3 - "$mode" "${json_files[@]}" <<'PY'
import difflib
import json
import pathlib
import sys

mode, *names = sys.argv[1:]
failed = False
for name in names:
    path = pathlib.Path(name)
    original = path.read_text(encoding="utf-8")
    try:
        formatted = json.dumps(json.loads(original), indent=4) + "\n"
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        print(f"{path}: {error}", file=sys.stderr)
        failed = True
        continue
    if mode == "fix":
        path.write_text(formatted, encoding="utf-8")
    elif original != formatted:
        sys.stderr.writelines(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                formatted.splitlines(keepends=True),
                fromfile=f"{path} (current)",
                tofile=f"{path} (formatted)",
            )
        )
        failed = True
if failed:
    raise SystemExit(1)
PY
fi

if ((${#jsonc_files[@]})); then
    require_tool python3
    python3 - "$repo_dir/generate-config.py" "${jsonc_files[@]}" <<'PY'
import importlib.util
import json
import pathlib
import sys

generator, *names = sys.argv[1:]
spec = importlib.util.spec_from_file_location("generate_config", generator)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
failed = False
for name in names:
    path = pathlib.Path(name)
    try:
        json.loads(module.strip_comments(path.read_text(encoding="utf-8")),
                   object_pairs_hook=module.unique_keys)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print(f"{path}: {error}", file=sys.stderr)
        failed = True
if failed:
    raise SystemExit(1)
PY
fi

printf 'CI checks passed.\n'
