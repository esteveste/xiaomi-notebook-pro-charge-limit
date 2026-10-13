#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stop the controller and remove it only after any owned inhibit is released."""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from controller import Policy

SERVICE = 'xiaomi-charge-limit.service'
STATE = Path('/var/lib/xiaomi-charge-limit/state.json')
CONTROLLER = Path('/usr/local/lib/xiaomi-charge-limit/controller.py')


def owns_inhibit():
    return Policy(path=STATE).state['owned']


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run the uninstaller with sudo')
    subprocess.run(['systemctl', 'stop', SERVICE], check=True)
    if owns_inhibit():
        subprocess.run(['/usr/bin/python3', str(CONTROLLER), 'release'], check=False)
    if owns_inhibit():
        raise SystemExit('Cleanup is still pending. Files and ownership state were retained. '
                         'Connect AC, resolve any battery protection condition, then retry. '
                         'Resume the controller with: sudo systemctl start ' + SERVICE)
    subprocess.run(['systemctl', 'disable', SERVICE], check=True)
    for name in ('/etc/systemd/system/' + SERVICE, '/usr/local/bin/xiaomi-charge-limit',
                 str(CONTROLLER), '/usr/local/lib/xiaomi-charge-limit/ec_read.py', str(STATE)):
        Path(name).unlink(missing_ok=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print('Removed controller. Kept /etc/xiaomi-charge-limit.json and any empty directories.')


if __name__ == '__main__':
    main()
