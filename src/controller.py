#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Software charge thresholds for the verified TM1701 / BIOS 0906 / BQ24780S."""
import argparse
import json
import logging
import os
import signal
import socket
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from ec_read import ECReader, check_model

CONFIG = Path('/etc/xiaomi-charge-limit.json')
STATE = Path('/var/lib/xiaomi-charge-limit/state.json')
STATUS = Path('/run/xiaomi-charge-limit/status.json')
LOG = logging.getLogger('xiaomi-charge-limit')
BATTERY_ALARMS = 0xD800


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def check_chip(ec):
    if ec.read_charger_word(0xFE) != 0x40 or ec.read_charger_word(0xFF) != 0x30:
        raise RuntimeError('BQ24780S charger identity mismatch')


@dataclass
class Sample:
    capacity: int
    ac_online: bool
    temperature_c: float
    battery_status: int
    requested_current_ma: int
    requested_voltage_mv: int
    battery_current_ma: int
    options: int | None

    def safe_to_resume(self):
        # Defer resumption during battery alarms, an error response, full-charge
        # indication, absent charge request, or outside a conservative range.
        return (5 <= self.temperature_c <= 40
                and not self.battery_status & (BATTERY_ALARMS | 0x20 | 0xF)
                and 0 < self.requested_current_ma < 65535
                and 0 < self.requested_voltage_mv < 65535)


class Charger(ECReader):
    def _write_parameter(self, register, value):
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError('Mailbox parameters must be bytes')
        if register not in {0x60, 0x62, 0x63, 0x64, 0x65}:
            raise ValueError('Not a charger mailbox register')
        if register == 0x60 and value != 8:
            raise ValueError('Only SMBUS_WRITE_WORD is permitted')
        if register in {0x62, 0x63} and value != 0x12:
            raise ValueError('Only BQ24780S ChargeOption0 writes are permitted')
        self.wait(2, 0)
        if self.status() & 1:
            raise RuntimeError('Unread EC output is pending')
        os.pwrite(self.fd, b'\x81', 0x66)
        self.wait(2, 0)
        os.pwrite(self.fd, bytes([register]), 0x62)
        self.wait(2, 0)
        os.pwrite(self.fd, bytes([value]), 0x62)
        self.wait(2, 0)

    def set_inhibit(self, enabled, expected_upper):
        if (type(enabled) is not bool or type(expected_upper) is not int
                or not 0 <= expected_upper <= 0xFFFF or expected_upper & 1):
            raise ValueError('Invalid charge-inhibit update')
        current = self.read_charger_word(0x12)
        if current & ~1 != expected_upper:
            raise RuntimeError('Native charger options changed; refusing stale update')
        desired = current | 1 if enabled else current & ~1
        if desired == current:
            return current
        if self.read(0x60):
            raise RuntimeError('SMBus transaction pending')
        for register, value in [(0x63, 0x12), (0x64, desired & 255),
                                (0x65, desired >> 8), (0x62, 0x12), (0x60, 8)]:
            self._write_parameter(register, value)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            status = self.read(0x61)
            if status & 0x80:
                if status & 0x1F:
                    raise RuntimeError(f'SMBus write error: {status:#x}')
                observed = self.read_charger_word(0x12)
                if bool(observed & 1) != enabled:
                    raise RuntimeError('Charge-inhibit readback did not match')
                if observed & ~1 != expected_upper:
                    raise RuntimeError('Native charger options changed during the update')
                return observed
            time.sleep(0.01)
        raise TimeoutError('SMBus write timeout')

    def sample(self):
        ac = (Path('/sys/class/power_supply/ADP0/online').read_text().strip() == '1')
        capacity = self.read_battery_word(0x0D)
        if not 0 <= capacity <= 100:
            raise RuntimeError(f'Invalid battery capacity: {capacity}')
        temperature = round(self.read_battery_word(8) / 10 - 273.15, 2)
        status = self.read_battery_word(0x16)
        request_current = self.read_battery_word(0x14)
        request_voltage = self.read_battery_word(0x15)
        current = self.read_battery_word(0x0A)
        if current & 0x8000:
            current -= 65536
        if ac:
            check_chip(self)
            options = self.read_charger_word(0x12)
        else:
            options = None
        return Sample(capacity, ac, temperature, status, request_current,
                      request_voltage, current, options)


class Policy:
    def __init__(self, start=65, stop=80, path=STATE):
        if type(start) is not int or type(stop) is not int or not 0 < start < stop <= 100:
            raise ValueError('Require 0 < start < stop <= 100')
        self.start, self.stop, self.path = start, stop, path
        self.state = {'version': 1, 'paused': None, 'owned': False, 'baseline': None}
        if path.exists():
            stored = json.loads(path.read_text())
            if (not isinstance(stored, dict)
                    or type(stored.get('version')) is not int or stored['version'] != 1
                    or 'paused' not in stored
                    or (stored['paused'] is not None and type(stored['paused']) is not bool)
                    or type(stored.get('owned')) is not bool
                    or (stored['owned'] and (type(stored.get('baseline')) is not int
                        or not 0 <= stored['baseline'] <= 0xFFFF or stored['baseline'] & 1))
                    or (not stored['owned'] and stored.get('baseline') is not None)):
                raise RuntimeError('Invalid ownership state; refusing charger changes')
            self.state.update(stored)

    def save(self):
        atomic_json(self.path, self.state)

    def disown(self):
        self.state['owned'] = False
        self.state['baseline'] = None
        self.save()

    def apply(self, sample, ec):
        old = self.state['paused']
        if sample.capacity >= self.stop:
            self.state['paused'] = True
        elif sample.capacity <= self.start:
            self.state['paused'] = False
        elif old is None:
            # With no history, don't top up a battery already above the start threshold.
            self.state['paused'] = True
        if old != self.state['paused']:
            self.save()
        if not sample.ac_online:
            return 'on_battery'
        options = sample.options
        if self.state['owned'] and (not options & 1
                                     or options & ~1 != self.state['baseline']):
            self.disown()
        if options & 0x20:
            return 'native_learn_mode'
        if self.state['paused']:
            if not options & 1:
                # Record ownership before the write, for crash recovery.
                self.state['baseline'] = options & ~1
                self.state['owned'] = True
                self.save()
                ec.set_inhibit(True, self.state['baseline'])
                return 'charging_paused'
            return 'charging_paused' if self.state['owned'] else 'native_inhibition'
        if self.state['owned']:
            if not sample.safe_to_resume():
                return 'waiting_for_safe_charge_request'
            ec.set_inhibit(False, self.state['baseline'])
            self.disown()
            return 'charging_permitted'
        return 'native_inhibition' if options & 1 else 'charging_permitted'

    def release(self, sample, ec):
        if not self.state['owned']:
            return 'nothing_owned'
        if not sample.ac_online:
            return 'release_deferred_until_ac'
        if not sample.options & 1:
            self.disown()
            return 'already_released'
        if sample.options & ~1 != self.state['baseline']:
            self.disown()
            return 'preserved_native_options'
        if not sample.safe_to_resume():
            return 'release_deferred_for_battery_protection'
        ec.set_inhibit(False, self.state['baseline'])
        self.disown()
        return 'released'


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        return
    if address.startswith('@'):
        address = '\0' + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(message.encode(), address)


def configuration(path=CONFIG):
    conf = json.loads(path.read_text())
    start, stop = conf['start_percent'], conf['stop_percent']
    interval = conf.get('poll_seconds', 10)
    if (type(start) is not int or type(stop) is not int or not 0 < start < stop <= 100
            or type(interval) is not int or not 2 <= interval <= 60):
        raise ValueError('Invalid charge-limit configuration')
    return start, stop, interval


def probe():
    check_model()
    if Path('/sys/class/power_supply/ADP0/online').read_text().strip() != '1':
        raise RuntimeError('Connect AC power before probing the charger identity')
    with Charger() as ec:
        return ec.sample()


def release():
    check_model()
    start, stop, _ = configuration()
    policy = Policy(start, stop)
    if not policy.state['owned']:
        return 'nothing_owned'
    with Charger() as ec:
        result = policy.release(ec.sample(), ec)
    LOG.info('Cleanup: %s', result)
    return result


def run():
    check_model()
    start, stop, interval = configuration()
    policy = Policy(start, stop)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *unused: stopped.set())
    signal.signal(signal.SIGINT, lambda *unused: stopped.set())
    failures = 0
    ready = False
    last = None
    try:
        while not stopped.is_set():
            try:
                with Charger() as ec:
                    sample = ec.sample()
                    action = policy.apply(sample, ec)
                status = {**asdict(sample), 'action': action,
                          'paused': policy.state['paused'], 'owned': policy.state['owned'],
                          'start_percent': start, 'stop_percent': stop,
                          'updated_at': time.time(), 'service_pid': os.getpid()}
                atomic_json(STATUS, status)
                if action != last:
                    LOG.info('%s: battery %s%%, AC %s, temperature %.2f C',
                             action, sample.capacity, sample.ac_online, sample.temperature_c)
                    last = action
                if not ready:
                    notify('READY=1')
                    ready = True
                notify(f'WATCHDOG=1\nSTATUS={sample.capacity}%: {action}; stop {stop}%, start {start}%')
                failures = 0
            except Exception as exc:
                failures += 1
                LOG.exception('Controller cycle failed (%s/3)', failures)
                atomic_json(STATUS, {'error': str(exc), 'updated_at': time.time(),
                                     'start_percent': start, 'stop_percent': stop})
                if failures >= 3:
                    raise
                notify('WATCHDOG=1')
            stopped.wait(interval)
    finally:
        try:
            release()
        except Exception:
            LOG.exception('Cleanup incomplete; ExecStopPost will retry')


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'status', 'release', 'check', 'probe'])
    parser.add_argument('--json', action='store_true', help='Show full status data')
    parser.add_argument('--config', type=Path, default=CONFIG,
                        help='Configuration path for the offline check command only')
    args = parser.parse_args()
    if args.command != 'check' and args.config != CONFIG:
        parser.error('--config is only supported by check')
    if args.command == 'run':
        run()
    elif args.command == 'release':
        result = release()
        print(result)
        if result.startswith('release_deferred'):
            raise SystemExit(3)
    elif args.command == 'check':
        start, stop, interval = configuration(args.config)
        print(f'Configuration valid: resume {start}%, stop {stop}%, poll {interval}s')
    elif args.command == 'probe':
        print(json.dumps(asdict(probe()), indent=2))
    else:
        if not STATUS.exists():
            raise SystemExit('No controller status is available. Check systemctl status xiaomi-charge-limit.')
        status = json.loads(STATUS.read_text())
        status['age_seconds'] = round(time.time() - status['updated_at'], 1)
        if args.json:
            print(json.dumps(status, indent=2))
        elif 'error' in status:
            print(f"Controller error: {status['error']}")
            print(f"Last update: {status['age_seconds']} seconds ago")
        else:
            action = status['action'].replace('_', ' ')
            print(f"Battery: {status['capacity']}% | AC: {'connected' if status['ac_online'] else 'disconnected'}")
            print(f"Charging: {action}")
            print(f"Limits: stop at {status['stop_percent']}%, resume at {status['start_percent']}%")
            print(f"Battery current: {status['battery_current_ma']} mA | last update: {status['age_seconds']} seconds ago")


if __name__ == '__main__':
    main()
