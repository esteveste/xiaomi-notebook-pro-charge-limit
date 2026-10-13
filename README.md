# Xiaomi Notebook Pro charge limit

Linux battery charging limits for the **Xiaomi Mi Notebook Pro TM1701**, using
its existing embedded-controller SMBus mailbox. Default behavior: **stop at
80%, resume at 65%**. No firmware flashing or kernel module is required.

**Experimental; verified on one laptop with BIOS XMAKB5R0P0906.** Other models
and BIOS versions are rejected before EC access. Matching these identifiers
alone does not prove that every hardware revision is compatible.

## Verified hardware

| Component | Tested configuration |
| --- | --- |
| Laptop / DMI product | Xiaomi Mi Notebook Pro / Timi TM1701 |
| BIOS | XMAKB5R0P0906 |
| Charger | Texas Instruments BQ24780S, IDs `0x0040` / `0x0030` |
| Battery | SUNWODA R15B01W |
| Operating system | openSUSE Tumbleweed, Linux with systemd |

The controller uses Python 3.10+ and its standard library. Installation requires
systemd, Python at `/usr/bin/python3`, root access to `/dev/port`, and AC power
for the initial identity check. It does not change sudo permissions.

## Install

Clone or download this repository, inspect the source, then run from its root:

```sh
python3 -m unittest discover -s tests -v
sudo ./install.sh
xiaomi-charge-limit
```

The installer checks the model, BIOS, configuration, and live charger identity,
then enables and starts `xiaomi-charge-limit.service`. It preserves an existing
configuration and ownership state. For installation without enabling or
starting the service, use `sudo ./install.sh --no-start`.

These are **software thresholds while the Linux service runs**. They do not
guarantee a cap while suspended, shut down, or booted into another OS. A battery
already above 80% is held from further charging; it is not forcibly discharged.

## Behavior and configuration

At or above the stop threshold, charging pauses. At or below the start
threshold, charging is permitted if the battery checks allow it. Between those
thresholds, the previous decision persists across service restarts. On a first
start with no saved history in that band, it pauses until the start threshold.
Permitting charging does not guarantee that the firmware will start charging.

Edit `/etc/xiaomi-charge-limit.json` with `sudoedit`:

```json
{
  "start_percent": 65,
  "stop_percent": 80,
  "poll_seconds": 10
}
```

Use integer values with `0 < start_percent < stop_percent <= 100` and a poll
interval of 2–60 seconds. Validate and apply changes:

```sh
xiaomi-charge-limit check
sudo systemctl restart xiaomi-charge-limit.service
```

## Status and diagnostics

```sh
xiaomi-charge-limit
xiaomi-charge-limit status --json
systemctl status xiaomi-charge-limit.service
sudo journalctl -u xiaomi-charge-limit.service -n 50 --no-pager
```

Linux's ordinary `BAT0/status` can still say `Charging` when charging is paused.
This tool reports direct Smart Battery current: positive means charging;
zero or small negative readings were observed during the verified pause.
Check the status timestamp; a stale file is not proof of a running controller.

To probe the supported hardware before installation, connect AC and run:

```sh
sudo python3 src/controller.py probe
```

The probe reads battery data and charger identity without changing charger
configuration. It writes EC mailbox parameters to request those reads and
cannot run simultaneously with another holder of this project's EC lock.

## Disable or remove

Stop and disable the controller:

```sh
sudo systemctl disable --now xiaomi-charge-limit.service
```

Stopping requests release of the inhibit bit owned by the controller. Release
can be deferred when AC is absent, a battery protection check is active, or
hardware access fails. Check the journal. Once AC is connected and the battery
checks allow resumption, retry while the service is stopped:

```sh
sudo xiaomi-charge-limit release
```

`release` exits with code 3 when cleanup is deferred. Do not delete ownership
state to bypass this condition. To remove the installation, run:

```sh
sudo ./uninstall.sh
```

The uninstaller retains the controller and ownership state if cleanup remains
pending. On successful removal it keeps the configuration file for reuse.

## Scope and limitations

The controller changes only `CHRG_INHIBIT`, bit 0 of charger `ChargeOption0`.
It does not write charge voltage, charge current, battery calibration, or
firmware. Before clearing its own inhibit it checks battery alarms/errors,
full-charge indication, charge requests, and a conservative 5–40°C temperature
range. It preserves other option bits and inhibits it did not set.

These checks are not a complete substitute for a vendor-supported charging
interface. A native inhibit requested while this tool already holds the same
single bit cannot be distinguished independently. The advisory lock coordinates
this project's processes, not firmware or other kernel/EC tools. Do not run
other raw EC writers alongside it. Hardware access errors stop normal operation
and trigger cleanup attempts; abrupt process or power loss can prevent cleanup.

Live charging pause/resume and service stop/start were tested. A complete
physical 80% → 65% → 80% cycle, reboot, suspend, and long-term operation have
**not** been validated. Other models and BIOS versions need their own protocol
and hardware evidence before support is added.

## Research and development

[Research notes](docs/research.md) explain the firmware analysis and live
results. [Contributing](CONTRIBUTING.md) describes how to report compatibility
and propose support for additional hardware. The implementation independently
combines documented building blocks; no claim of a first discovery is made.

Tests simulate hardware and never access `/dev/port`:

```sh
python3 -m unittest discover -s tests -v
python3 src/controller.py check --config config/xiaomi-charge-limit.json
```

To inspect installed file layout without root or hardware access:

```sh
./install.sh --destdir ./build/staging
```

Source is under [MIT](LICENSE). [References and attribution](docs/references.md)
identify the protocol documentation and research tools. Vendor firmware,
machine dumps, and compiled third-party binaries are not included.
