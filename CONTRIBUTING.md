# Contributing

Compatibility reports, testing, documentation improvements, and reviewed
hardware profiles are welcome. Current support is restricted to TM1701 with
BIOS XMAKB5R0P0906 and BQ24780S identity checks.

## Report a result or problem

Include the DMI product name and BIOS version, Linux distribution, kernel and
Python versions, battery model, project revision, and a description of the
behavior. Useful commands:

```sh
cat /sys/class/dmi/id/product_name /sys/class/dmi/id/bios_version
uname -sr
python3 --version
xiaomi-charge-limit status --json
sudo journalctl -u xiaomi-charge-limit.service -n 50 --no-pager
```

Review output before sharing it. Redact usernames, hostnames, serial numbers,
paths, and unrelated logs. Do not upload full DMI/ACPI dumps or vendor firmware.
Clearly distinguish simulated tests from observations on real hardware. Reports
of complete threshold cycles, adapter reconnect, reboot, suspend, and extended
operation would fill gaps in current validation.

## Additional hardware

Do not simply remove the model/BIOS guard. A proposed profile needs evidence of
the relevant EC ports, mailbox layout and routing, charger identity and command
semantics, native firmware behavior, and successful pause/resume with direct
battery current measurements. Keep raw firmware private and share factual
findings, hashes, and sanitized results instead.

Support should preserve current/voltage settings and native option bits, respect
battery protection signals, provide recoverable ownership state, and reject
unsupported configurations. Review any live write test separately; ordinary
tests and CI must never access real hardware.

## Development checks

```sh
python3 -m unittest discover -s tests -v
python3 src/controller.py check --config config/xiaomi-charge-limit.json
sh -n install.sh uninstall.sh scripts/xiaomi-charge-limit
git diff --check
```

Use `./install.sh --destdir ./build/staging` to exercise file installation without
root, hardware access, or changes to systemd. Changes to stop/cleanup behavior
should include tests that prove pending ownership is retained. Contributions
are submitted under the repository's MIT license.
