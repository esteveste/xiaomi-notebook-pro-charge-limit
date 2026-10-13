"""Policy tests with a fake charger; no hardware access."""
# SPDX-License-Identifier: MIT
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from controller import Policy, Sample


class FakeCharger:
    def __init__(self):
        self.writes = []

    def set_inhibit(self, enabled, expected_upper):
        self.writes.append((enabled, expected_upper))


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'
        self.policy = Policy(path=self.path)
        self.ec = FakeCharger()
        self.sample = Sample(99, True, 30, 0x80, 2304, 8688, 1000, 0x8108)

    def paused(self):
        self.assertEqual(self.policy.apply(self.sample, self.ec), 'charging_paused')
        return replace(self.sample, options=0x8109)

    def test_hysteresis_and_persisted_state(self):
        held = self.paused()
        self.assertEqual(self.ec.writes, [(True, 0x8108)])
        self.policy = Policy(path=self.path)  # Restart keeps the paused state.
        for capacity in (80, 79, 72, 66):
            self.policy.apply(replace(held, capacity=capacity), self.ec)
        self.assertEqual(len(self.ec.writes), 1)
        self.policy.apply(replace(held, capacity=65), self.ec)
        self.assertEqual(self.ec.writes[-1], (False, 0x8108))
        for capacity in (66, 72, 79):
            self.policy.apply(replace(self.sample, capacity=capacity), self.ec)
        self.assertEqual(len(self.ec.writes), 2)
        self.policy.apply(replace(self.sample, capacity=80), self.ec)
        self.assertEqual(self.ec.writes[-1], (True, 0x8108))

    def test_native_inhibit_is_never_cleared(self):
        sample = replace(self.sample, capacity=60, options=0x8109)
        self.assertEqual(self.policy.apply(sample, self.ec), 'native_inhibition')
        self.assertEqual(self.ec.writes, [])

    def test_battery_safety_blocks_resumption(self):
        held = replace(self.paused(), capacity=60)
        for change in [{'temperature_c': 44}, {'temperature_c': 0},
                       {'battery_status': 0x1080}, {'battery_status': 0x4080},
                       {'battery_status': 0x81}, {'requested_current_ma': 0},
                       {'requested_voltage_mv': 0}]:
            self.assertEqual(self.policy.apply(replace(held, **change), self.ec),
                             'waiting_for_safe_charge_request')
        self.assertEqual(self.ec.writes, [(True, 0x8108)])
        self.policy.apply(held, self.ec)
        self.assertEqual(self.ec.writes[-1], (False, 0x8108))

    def test_native_options_changes_revoke_ownership(self):
        held = replace(self.paused(), capacity=60, options=0x8909)
        self.assertEqual(self.policy.apply(held, self.ec), 'native_inhibition')
        self.assertFalse(self.policy.state['owned'])
        self.assertEqual(len(self.ec.writes), 1)

    def test_firmware_reset_reapplies_hold(self):
        self.paused()
        self.assertEqual(self.policy.apply(self.sample, self.ec), 'charging_paused')
        self.assertEqual(self.ec.writes, [(True, 0x8108), (True, 0x8108)])

    def test_stop_restores_owned_bit_only(self):
        held = self.paused()
        self.assertEqual(self.policy.release(held, self.ec), 'released')
        self.assertFalse(self.policy.state['owned'])
        self.assertEqual(self.ec.writes[-1], (False, 0x8108))
        self.assertEqual(self.policy.release(held, self.ec), 'nothing_owned')

    def test_native_options_change_is_preserved_on_stop(self):
        held = replace(self.paused(), options=0x8909)
        self.assertEqual(self.policy.release(held, self.ec), 'preserved_native_options')
        self.assertEqual(len(self.ec.writes), 1)

    def test_ac_disconnected_causes_no_writes(self):
        sample = replace(self.sample, ac_online=False, options=None)
        self.assertEqual(self.policy.apply(sample, self.ec), 'on_battery')
        self.assertEqual(self.ec.writes, [])

    def test_startup_mid_band_pauses_until_start_threshold(self):
        self.policy.apply(replace(self.sample, capacity=72), self.ec)
        self.assertEqual(self.ec.writes, [(True, 0x8108)])

    def test_invalid_limits_are_rejected(self):
        for start, stop in [(80, 65), (80, 80), (0, 80), (65, 101)]:
            with self.assertRaises(ValueError):
                Policy(start, stop, self.path)


if __name__ == '__main__':
    unittest.main()
