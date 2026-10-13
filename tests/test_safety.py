# SPDX-License-Identifier: MIT
"""Guard and transport tests; all hardware operations are mocked."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from controller import Charger, Policy, Sample, configuration, probe
from ec_read import ECReader


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'data.json'

    def test_configuration_rejects_invalid_types_ranges_and_intervals(self):
        for changes in ({'start_percent': True}, {'stop_percent': 80.5},
                        {'start_percent': 80}, {'stop_percent': 101},
                        {'poll_seconds': True}, {'poll_seconds': 1},
                        {'poll_seconds': 61}, {'poll_seconds': '10'}):
            with self.subTest(changes=changes):
                value = {'start_percent': 65, 'stop_percent': 80, 'poll_seconds': 10}
                self.path.write_text(json.dumps({**value, **changes}))
                with self.assertRaises(ValueError):
                    configuration(self.path)

    def test_configuration_accepts_boundaries(self):
        for interval in (2, 10, 60):
            self.path.write_text(json.dumps({'start_percent': 65, 'stop_percent': 80,
                                            'poll_seconds': interval}))
            self.assertEqual(configuration(self.path), (65, 80, interval))

    def test_invalid_state_is_rejected(self):
        valid = {'version': 1, 'paused': True, 'owned': True, 'baseline': 0x8108}
        for changes in ({'version': True}, {'paused': 1}, {'owned': 1},
                        {'baseline': True}, {'baseline': -2}, {'baseline': 0x10000},
                        {'baseline': 0x8109}, {'owned': False}):
            with self.subTest(changes=changes):
                self.path.write_text(json.dumps({**valid, **changes}))
                with self.assertRaises(RuntimeError):
                    Policy(path=self.path)
        for value in ([], {}, None):
            self.path.write_text(json.dumps(value))
            with self.assertRaises(RuntimeError):
                Policy(path=self.path)

    def test_model_mismatch_prevents_lock_or_port_open(self):
        for values in (['OTHER'], ['TM1701', 'OTHER-BIOS']):
            with patch('ec_read.Path.read_text', side_effect=values), \
                    patch('ec_read.os.open') as port, patch('builtins.open') as lock:
                with self.assertRaises(RuntimeError):
                    with ECReader():
                        self.fail('Unsupported hardware should never open the transport')
                port.assert_not_called()
                lock.assert_not_called()

    def test_probe_without_ac_never_opens_transport(self):
        with patch('controller.check_model'), patch('controller.Path.read_text', return_value='0'), \
                patch('controller.Charger') as transport:
            with self.assertRaises(RuntimeError):
                probe()
            transport.assert_not_called()


class TransportTests(unittest.TestCase):
    def test_write_can_only_change_inhibit_bit(self):
        ec = Charger()
        for current, enabled, desired in [(0x8108, True, 0x8109),
                                          (0x8109, False, 0x8108)]:
            with self.subTest(enabled=enabled), \
                    patch.object(ec, 'read_charger_word', side_effect=[current, desired]), \
                    patch.object(ec, 'read', side_effect=[0, 0x80]), \
                    patch.object(ec, '_write_parameter') as write:
                self.assertEqual(ec.set_inhibit(enabled, 0x8108), desired)
                self.assertEqual([call.args for call in write.call_args_list],
                                 [(0x63, 0x12), (0x64, desired & 255),
                                  (0x65, desired >> 8), (0x62, 0x12), (0x60, 8)])

    def test_native_change_prevents_write(self):
        ec = Charger()
        with patch.object(ec, 'read_charger_word', return_value=0x8909), \
                patch.object(ec, '_write_parameter') as write:
            with self.assertRaises(RuntimeError):
                ec.set_inhibit(False, 0x8108)
            write.assert_not_called()

    def test_write_errors_and_readback_mismatch_are_reported(self):
        ec = Charger()
        for observed, status in [(0x8108, 0x80), (0x8909, 0x80), (0x8109, 0x81)]:
            with self.subTest(observed=observed, status=status), \
                    patch.object(ec, 'read_charger_word', side_effect=[0x8108, observed]), \
                    patch.object(ec, 'read', side_effect=[0, status]), \
                    patch.object(ec, '_write_parameter'):
                with self.assertRaises(RuntimeError):
                    ec.set_inhibit(True, 0x8108)

    def test_pending_transaction_prevents_mailbox_write(self):
        ec = Charger()
        with patch.object(ec, 'read_charger_word', return_value=0x8108), \
                patch.object(ec, 'read', return_value=9), \
                patch.object(ec, '_write_parameter') as write:
            with self.assertRaises(RuntimeError):
                ec.set_inhibit(True, 0x8108)
            write.assert_not_called()

    def test_invalid_write_parameters_never_touch_io(self):
        ec = Charger()
        with patch('controller.os.pwrite') as io:
            for register, value in [(0x61, 0), (0x60, 9), (0x62, 0x16),
                                    (0x63, 0x14), (0x64, 256), (0x65, -1)]:
                with self.assertRaises(ValueError):
                    ec._write_parameter(register, value)
            for enabled, baseline in [(1, 0x8108), (False, 0x8109), (True, -2)]:
                with self.assertRaises(ValueError):
                    ec.set_inhibit(enabled, baseline)
            io.assert_not_called()

    def test_read_word_decodes_little_endian_and_only_starts_read(self):
        ec = ECReader()
        with patch.object(ec, 'read', side_effect=[0, 0x80, 0x08, 0x81]), \
                patch.object(ec, '_read_mailbox_parameter') as write:
            self.assertEqual(ec.read_charger_word(0x12), 0x8108)
            self.assertEqual([call.args for call in write.call_args_list],
                             [(0x63, 0x12), (0x62, 0x12), (0x60, 9)])


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('uninstaller', ROOT / 'scripts/uninstall.py')
        cls.uninstaller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.uninstaller)

    def test_uninstall_keeps_files_when_release_is_deferred(self):
        uninstall = self.uninstaller
        with patch.object(uninstall.os, 'geteuid', return_value=0), \
                patch.object(uninstall, 'owns_inhibit', return_value=True), \
                patch.object(uninstall.subprocess, 'run') as commands, \
                patch.object(uninstall.Path, 'unlink') as remove:
            with self.assertRaises(SystemExit) as exc:
                uninstall.main()
            self.assertIn('Files and ownership state were retained', str(exc.exception))
            remove.assert_not_called()
            self.assertFalse(any('disable' in call.args[0] for call in commands.call_args_list))

    def test_uninstall_rejects_corrupt_state_even_when_owned_is_false(self):
        uninstall = self.uninstaller
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text('{"owned": false}')
            with patch.object(uninstall, 'STATE', state):
                with self.assertRaises(RuntimeError):
                    uninstall.owns_inhibit()

    def test_release_without_ac_or_with_alarm_keeps_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Policy(path=Path(directory) / 'state.json')
            policy.state.update(owned=True, baseline=0x8108, paused=True)
            ec = unittest.mock.Mock()
            samples = [Sample(70, False, 30, 0x80, 2304, 8688, 0, None),
                       Sample(70, True, 44, 0x80, 2304, 8688, 0, 0x8109)]
            for sample in samples:
                self.assertTrue(policy.release(sample, ec).startswith('release_deferred'))
                self.assertTrue(policy.state['owned'])
            ec.set_inhibit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
