import support
import sys
sys.path.insert(0,str(support.DESKTOP))
import io
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from spaces.pictures import backend as pictures


class WallpaperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_CACHE_HOME": str(self.root / "cache"),
                "XDG_DATA_HOME": str(self.root / "data"),
                "XDG_DATA_HOME": str(self.root / "data"),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.item = {
            "provider": "wallhaven",
            "id": "abc123",
            "path": "https://w.wallhaven.cc/full/ab/wallhaven-abc123.png",
        }

    def cached_wallpaper(self):
        path = pictures.wallpaper_file(pictures.clean_item(self.item))
        path.write_bytes(b"cached image")
        return path

    def response(self, content=b"image"):
        response = io.BytesIO(content)
        response.headers = Message()
        response.headers["Content-Type"] = "image/png"
        return response

    def test_set_updates_shell_setting_without_external_services(self):
        path = self.cached_wallpaper()
        with (
            patch.object(pictures, "urlopen") as network,
        ):
            result = pictures.run({"op": "set", "wallpaper": self.item})
        network.assert_not_called()
        self.assertEqual(result["service"], "desktop shell")
        setting = self.root / "config/quickshell/desktop/spaces/pictures/wallpaper.json"
        self.assertEqual(
            json.loads(setting.read_text()), {"image": (self.root / "data/quickshell/desktop/spaces/pictures/current-wallpaper").as_uri(), "provider": "wallhaven"}
        )
        self.assertEqual(list(setting.parent.glob(".wallpaper-*")), [])

    def test_failed_setting_write_preserves_previous_wallpaper(self):
        path = self.cached_wallpaper()
        pictures.apply_shell_wallpaper(path)
        setting = self.root / "config/quickshell/desktop/spaces/pictures/wallpaper.json"
        before = setting.read_bytes()
        other = self.root / "other image.png"
        other.write_bytes(b"new wallpaper")
        with patch.object(pictures.os, "replace", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                pictures.apply_shell_wallpaper(self.root / "other image.png")
        self.assertEqual(setting.read_bytes(), before)
        self.assertEqual(list(setting.parent.glob(".wallpaper-*")), [])

    def test_current_provider_uses_saved_identity(self):
        setting = self.root / "config/quickshell/desktop/spaces/pictures/wallpaper.json"
        setting.parent.mkdir(parents=True)
        cases = [
            ({}, "wallhaven"),
            ({"image": "file:///wallpapers/wallhaven-abc123.png"}, "wallhaven"),
            ({"image": "file:///wallpapers/bing-daily%20image.jpg"}, "wallhaven"),
            ({"provider": "bing", "image": "file:///custom.jpg"}, "bing"),
            (
                {"mode": "wallpaper_engine", "image": "file:///wallhaven-old.png"},
                "wallpaper_engine",
            ),
            ({"provider": "unknown"}, "wallhaven"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                setting.write_text(json.dumps(value))
                self.assertEqual(pictures.run({"op": "providers"})["currentProvider"], expected)
        setting.write_text("invalid json")
        self.assertEqual(pictures.current_wallpaper_provider(), "wallhaven")

    def test_download_saves_original_and_cleans_temporary_file(self):
        item = pictures.clean_item(self.item)
        with patch.object(pictures, "urlopen", return_value=self.response()) as request:
            path = pictures.download_wallpaper(item)
        self.assertEqual(path.read_bytes(), b"image")
        self.assertEqual(request.call_args.kwargs["timeout"], 10)
        self.assertEqual(list(path.parent.glob("*.download")), [])

    def test_slow_download_expires_even_while_receiving_data(self):
        item = pictures.clean_item(self.item)
        path = pictures.wallpaper_file(item)
        with (
            patch.object(pictures, "urlopen", return_value=self.response()),
            patch.object(pictures.time, "monotonic", side_effect=[0, 1, 61]),
        ):
            with self.assertRaisesRegex(ValueError, "download timed out"):
                pictures.download_wallpaper(item)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.glob("*.download")), [])

    def test_invalid_target_does_not_download(self):
        with patch.object(pictures, "download_wallpaper") as download:
            with self.assertRaisesRegex(ValueError, "Unknown wallpaper target"):
                pictures.set_wallpaper({"wallpaper": self.item, "target": "invalid"})
        download.assert_not_called()

    def test_random_command_defaults_to_shell(self):
        item = pictures.clean_item(self.item)
        for target in ("shell",):
            argv = ["backend.py", "--random"] + (
                ["--target=desktop"] if target == "desktop" else []
            )
            with (
                self.subTest(target=target),
                patch.object(pictures.sys, "argv", argv),
                patch.object(pictures, "random_wallpaper", return_value=item),
                patch.object(
                    pictures, "set_wallpaper", return_value={"service": "test", "path": "/image"}
                ) as apply,
                patch("builtins.print"),
            ):
                self.assertEqual(pictures.command_line(), 0)
            apply.assert_called_once_with({"wallpaper": item, "target": target})

    def test_repeated_wallpapers_update_shared_still(self):
        first = self.cached_wallpaper()
        pictures.set_wallpaper({"wallpaper": self.item})
        link = self.root / "data/quickshell/desktop/spaces/pictures/current-wallpaper"
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_bytes(), first.read_bytes())
        item = dict(self.item, id="def456")
        second = pictures.wallpaper_file(pictures.clean_item(item))
        second.write_bytes(b"new wallpaper")
        pictures.set_wallpaper({"wallpaper": item})
        self.assertEqual(link.read_bytes(), second.read_bytes())
        self.assertEqual(list(link.parent.glob(".lock-wallpaper-*")), [])


    def test_random_action_pins_wallhaven_and_updates_both_surfaces(self):
        image = self.cached_wallpaper()
        item = pictures.clean_item(self.item)
        with patch.object(pictures, 'random_wallpaper', return_value=item) as random:
            result = pictures.run({'op': 'randomSet', 'provider': 'bing'})
        random.assert_called_once_with({'provider': 'wallhaven', 'filters': {'purity': '100'}})
        self.assertIn('Lock screen updated', result['message'])
        self.assertEqual((self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper').read_bytes(), image.read_bytes())

    def test_preferences_are_private_and_reject_oversized_data(self):
        values = dict(grid=True, provider='bing', filters={'bing': {'country': 'VN'}})
        pictures.run({'op': 'savePreferences', 'values': values})
        self.assertEqual(pictures.run({'op': 'preferences'}), values)
        target = self.root / 'config/quickshell/desktop/spaces/pictures/pictures-ui.json'
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        for bad in ({'grid': 'yes'}, dict(values, filters={'query': 'x' * 65000})):
            with self.assertRaises(ValueError):
                pictures.run({'op': 'savePreferences', 'values': bad})

    def test_wallhaven_filters_pagination_and_sfw_random(self):
        params = pictures.search_parameters({'filters': {'categories': '010', 'sorting': 'toplist', 'ratio': '16x9', 'resolution': '2560x1440', 'tagQuery': 'id:37'}, 'query': 'forest'})
        self.assertEqual(params['purity'], '100')
        self.assertEqual(params['categories'], '010')
        self.assertIn('id:37', params['q'])
        with patch.object(pictures, 'api_request', return_value={'data': [self.item], 'meta': {'current_page': 1, 'last_page': 2, 'total': 24}}):
            result = pictures.browse({'provider': 'wallhaven'})
        self.assertEqual(result['next'], 2)
        self.assertEqual(result['items'][0]['id'], 'abc123')

    def test_failed_json_commit_restores_previous_shared_still(self):
        first = self.cached_wallpaper()
        pictures.set_wallpaper({'wallpaper': self.item})
        other = self.root / 'other.png'; other.write_bytes(b'new wallpaper')
        original = pictures.atomic_write
        def write(path, content, *args, **kwargs):
            if path.name == 'wallpaper.json':
                raise OSError('cannot commit')
            original(path, content, *args, **kwargs)
        with patch.object(pictures, 'atomic_write', side_effect=write), self.assertRaises(OSError):
            pictures.apply_shell_wallpaper(other)
        self.assertEqual((self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper').read_bytes(), first.read_bytes())
