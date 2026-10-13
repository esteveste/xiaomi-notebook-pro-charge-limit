#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read reviewed TM1701 EC and SMBus registers.

SMBus reads use EC_WRITE to set mailbox parameters, but do not write battery
or charger configuration. Even a probe accesses the live EC transport.
"""
import argparse
import fcntl
import json
import os
import time
from pathlib import Path

ALLOWED = {0x94, 0x95, 0xA4} | set(range(0x60, 0x88))


def check_model():
    for name, expected in [('product_name', 'TM1701'),
                           ('bios_version', 'XMAKB5R0P0906')]:
        actual = (Path('/sys/class/dmi/id') / name).read_text().strip()
        if actual != expected:
            raise RuntimeError(f'Unsupported {name}: {actual!r}; refusing EC access')


class ECReader:
    def __enter__(self):
        check_model()
        self.lock = open('/run/lock/xiaomi-tm1701-ec.lock', 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd = os.open('/dev/port', os.O_RDWR)
        except BaseException:
            self.lock.close()
            raise
        return self

    def __exit__(self, *unused):
        os.close(self.fd)
        self.lock.close()

    def status(self):
        return os.pread(self.fd, 1, 0x66)[0]

    def wait(self, mask, expected):
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            status = self.status()
            if status == 0xFF:
                raise RuntimeError('EC port is not responding')
            if status & mask == expected:
                return
            time.sleep(0.001)
        raise TimeoutError(f'EC status wait timed out: 0x{self.status():02x}')

    def read(self, register):
        if register not in ALLOWED:
            raise ValueError('Register has not been reviewed for reading')
        self.wait(2, 0)
        if self.status() & 1:
            raise RuntimeError('Unread EC output is pending; refusing to consume it')
        os.pwrite(self.fd, b'\x80', 0x66)  # ACPI EC_READ opcode
        self.wait(2, 0)
        os.pwrite(self.fd, bytes([register]), 0x62)
        self.wait(1, 1)
        return os.pread(self.fd, 1, 0x62)[0]

    def _read_mailbox_parameter(self, register, value):
        """Set only parameters needed for an SMBus READ_WORD transaction."""
        allowed = {0x62: {0x12, 0x16},
                   0x63: {0xFE, 0xFF, 0x12, 0x14, 0x15, 0x08, 0x0A, 0x0B, 0x0D, 0x16},
                   0x60: {0x09}}
        if register not in allowed or value not in allowed[register]:
            raise ValueError('Not an approved read-only SMBus parameter')
        self.wait(2, 0)
        if self.status() & 1:
            raise RuntimeError('Unread EC output is pending')
        os.pwrite(self.fd, b'\x81', 0x66)  # EC_WRITE, mailbox parameters only
        self.wait(2, 0)
        os.pwrite(self.fd, bytes([register]), 0x62)
        self.wait(2, 0)
        os.pwrite(self.fd, bytes([value]), 0x62)
        self.wait(2, 0)

    def read_charger_word(self, command):
        if command not in {0xFE, 0xFF, 0x12, 0x14, 0x15}:
            raise ValueError('Charger register has not been approved for reading')
        return self._read_word(0x12, command)

    def read_battery_word(self, command):
        if command not in {0x08, 0x0A, 0x0B, 0x0D, 0x14, 0x15, 0x16}:
            raise ValueError('Battery register has not been approved for reading')
        return self._read_word(0x16, command)

    def _read_word(self, address, command):
        if self.read(0x60):
            raise RuntimeError('Another SMBus transaction is pending')
        self._read_mailbox_parameter(0x63, command)
        self._read_mailbox_parameter(0x62, address)  # Charger 0x09 / battery 0x0b, channel 0
        self._read_mailbox_parameter(0x60, 0x09)  # SMBUS_READ_WORD, never WRITE_WORD
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            status = self.read(0x61)
            if status & 0x80:
                if status & 0x1F:
                    raise RuntimeError(f'SMBus read failed: status 0x{status:02x}')
                return self.read(0x64) | (self.read(0x65) << 8)
            time.sleep(0.01)
        raise TimeoutError(f'SMBus read did not complete: status 0x{status:02x}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('register', nargs='+', type=lambda s: int(s, 0))
    args = parser.parse_args()
    with ECReader() as ec:
        result = {f'0x{register:02x}': ec.read(register) for register in args.register}
    print(json.dumps(result, indent=2))
