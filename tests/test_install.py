# SPDX-License-Identifier: MIT
"""Installer staging tests; never install into the host or access hardware."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_staging_installs_expected_files_and_preserves_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            with patch.object(installer, 'probe') as probe, \
                    patch.object(installer, 'systemctl') as services:
                installer.install_files(destination)
                for source, target, mode in installer.FILES:
                    installed = destination / target
                    self.assertEqual(installed.read_bytes(), (ROOT / source).read_bytes())
                    self.assertEqual(installed.stat().st_mode & 0o777, mode)
                config = destination / 'etc/xiaomi-charge-limit.json'
                custom = json.dumps({'start_percent': 60, 'stop_percent': 75, 'poll_seconds': 20})
                config.write_text(custom)
                installer.install_files(destination)
                self.assertEqual(config.read_text(), custom)
                probe.assert_not_called()
                services.assert_not_called()

    def test_invalid_existing_configuration_prevents_replacing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            (destination / 'etc').mkdir()
            (destination / 'etc/xiaomi-charge-limit.json').write_text(
                '{"start_percent":80,"stop_percent":65}')
            with self.assertRaises(ValueError):
                installer.install_files(destination)
            self.assertFalse((destination / 'usr').exists())


if __name__ == '__main__':
    unittest.main()
