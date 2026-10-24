"""Read the current Steam account's artwork and local play statistics."""
from datetime import datetime


def account(backend, root):
    from spaces.games.backend import parse_vdf
    try:
        users = parse_vdf((root / "config/loginusers.vdf").read_text()).get("users", {})
        recent = [key for key, value in users.items() if value.get("MostRecent") == "1"]
        if len(recent) == 1 and recent[0].isdigit():
            return root / "userdata" / str(int(recent[0]) - 76561197960265728)
    except (OSError, ValueError, AttributeError):
        pass
    paths = [path for path in (root / "userdata").glob("*") if path.is_dir() and path.name.isdigit()]
    return paths[0] if len(paths) == 1 else None


def read(backend, app_id):
    from spaces.games.backend import parse_vdf
    if not app_id:
        return {}
    base = "https://shared.steamstatic.com/store_item_assets/steam/apps/" + app_id + "/"
    result = {"logo": base + "logo.png", "hero": base + "library_hero.jpg", "appId": app_id}
    for root in backend._steam_roots():
        user = account(backend, root)
        cache = root / "appcache/librarycache"
        for field, suffix, kind in (("logo", "_logo", "logo"), ("hero", "_hero", "library_hero"), ("cover", "p", "library_600x900")):
            candidates = []
            if user:
                candidates.extend(user / "config/grid" / (app_id + suffix + ext) for ext in (".png", ".jpg", ".webp"))
            candidates.extend(sorted(cache.glob(app_id + "_" + kind + ".*")))
            candidates.extend(sorted((cache / app_id).glob("*" + kind + ".*")))
            for path in candidates:
                try:
                    if path.is_file() and 0 < path.stat().st_size <= 20 * 1024 * 1024:
                        result[field] = path.resolve().as_uri() + "?v=" + str(path.stat().st_mtime_ns)
                        break
                except OSError:
                    continue
        if not user:
            continue
        try:
            config = user / "config/localconfig.vdf"
            if config.stat().st_size > 32 * 1024 * 1024:
                continue
            data = parse_vdf(config.read_text())
            data = data.get("UserLocalConfigStore", {}).get("Software", {}).get("Valve", {}).get("Steam", {}).get("apps", {}).get(app_id, {})
            minutes = max(0, int(data.get("Playtime", 0)))
            last_played = max(0, int(data.get("LastPlayed", 0)))
            result["playHours"] = round(minutes / 60, 1)
            result["lastPlayed"] = datetime.fromtimestamp(last_played).strftime("%d %b %Y") if last_played else ""
        except (OSError, ValueError, TypeError, OverflowError):
            pass
    return result
