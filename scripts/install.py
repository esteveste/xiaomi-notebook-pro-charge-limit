#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install locally, or stage files without accessing hardware using --destdir."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from controller import check_model, configuration, probe  # noqa: E402

SERVICE = 'xiaomi-charge-limit.service'
FILES = (
    ('src/controller.py', 'usr/local/lib/xiaomi-charge-limit/controller.py', 0o644),
    ('src/ec_read.py', 'usr/local/lib/xiaomi-charge-limit/ec_read.py', 0o644),
    ('scripts/xiaomi-charge-limit', 'usr/local/bin/xiaomi-charge-limit', 0o755),
    ('systemd/xiaomi-charge-limit.service', 'etc/systemd/system/' + SERVICE, 0o644),
)


def copy_atomic(source, target, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + target.name, dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(source.read_bytes())
        os.chmod(name, mode)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def install_files(destination):
    config = destination / 'etc/xiaomi-charge-limit.json'
    configuration(config if config.exists() else ROOT / 'config/xiaomi-charge-limit.json')
    for source, target, mode in FILES:
        copy_atomic(ROOT / source, destination / target, mode)
    if not config.exists():
        copy_atomic(ROOT / 'config/xiaomi-charge-limit.json', config, 0o644)


def systemctl(*args, check=True):
    return subprocess.run(['systemctl', *args], check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destdir', type=Path,
                        help='Stage files only; skip root, hardware, and systemd operations')
    parser.add_argument('--no-start', action='store_true',
                        help='Install without enabling or starting the service')
    args = parser.parse_args()
    if args.destdir is not None:
        destination = args.destdir.resolve()
        if destination == Path('/'):
            parser.error('--destdir must be a staging directory, not /')
        install_files(destination)
        print(f'Files staged in {destination}; no hardware or service changes made.')
        return
    if os.geteuid() != 0:
        parser.error('Run the installer with sudo')
    if not Path('/usr/bin/python3').exists() or shutil.which('systemctl') is None:
        parser.error('Python 3.10+ at /usr/bin/python3 and systemd are required')
    check_model()  # Reject an unverified model/BIOS before changing installed files.
    configuration(Path('/etc/xiaomi-charge-limit.json')
                  if Path('/etc/xiaomi-charge-limit.json').exists()
                  else ROOT / 'config/xiaomi-charge-limit.json')
    if not Path('/dev/port').exists():
        parser.error('/dev/port is unavailable; no installation performed')
    was_active = systemctl('is-active', '--quiet', SERVICE, check=False).returncode == 0
    if was_active:
        systemctl('stop', SERVICE)
    try:
        probe()  # AC required; verifies charger identity without changing configuration.
        install_files(Path('/'))
        systemctl('daemon-reload')
        if not args.no_start:
            systemctl('enable', '--now', SERVICE)
    except BaseException:
        if was_active:
            systemctl('start', SERVICE, check=False)
        raise
    print('Installed. Existing configuration and ownership state were preserved.')
    if args.no_start:
        print(f'Start later with: sudo systemctl enable --now {SERVICE}')
    else:
        print('Check status with: xiaomi-charge-limit')


if __name__ == '__main__':
    main()
