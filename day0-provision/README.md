# day0_provision

`day0_provision.py` pushes a baseline configuration onto a **blank** network device over its **console (serial) port**, so the device becomes SSH-reachable. It solves the day-0 chicken-and-egg: every SSH-based tool needs an IP that only exists after someone configures it on the console.

It is a **single-device console tool** — you provision one device per run, over the serial cable you are physically plugged into. The YAML config and the template decide which values a device needs; the command line just supplies them.

## Requirements

- Python 3.x
- `pyyaml`
- `pyserial` — only for a live push (`--port`); dry runs need only `pyyaml`

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Dry run: render and view the config, send nothing
python3 day0_provision.py --config examples/day0-generic.yaml \
    --u 14 --username ayal0014 --dry-run

# Live provisioning; pick the device from a menu when the config has several
python3 day0_provision.py --config examples/day0-generic.yaml \
    --u 14 --username ayal0014 --port /dev/ttyUSB0
```

### Options

```
Required:
  --config PATH        the provisioning YAML

Template variables (supply only what the template uses):
  --u VALUE            fills {U}
  --username VALUE     fills {USERNAME}

Device:
  --device DEVICE      one device in the YAML  -> selected automatically
                       several devices         -> numbered menu, unless
                                                  --device is given

Console:
  --port PORT          serial port (/dev/ttyUSB0, COM3, ...). Omit for a dry run.
  --baud BAUD          override the config's baud (default 9600)
  --dry-run            print the rendered config, send nothing
  --yes                skip the confirmation prompt
  --quiet              don't echo each line as it is sent
```

## How it works

1. **Load `--config`** (required — no default, so you can't push the wrong definition by accident).
2. **Pick the device.** One device is auto-selected; several prompt a menu (or pass `--device`).
3. **Render** the device template with your variables (`{U}`, `{USERNAME}`, ...), `{DEVICE}`, and `{ENV:...}` secrets. Any placeholder the template needs but you didn't supply stops the run *before anything is sent* — the template is the source of truth for what's required.
4. **Safety scan** — refuses templates containing `erase`/`reload`/`format`/`delete`.
5. **Dry run** — `--dry-run`, or simply omitting `--port`, prints the rendered config and stops. Printing a config is harmless; sending one is not, so a missing `--port` fails safe.
6. **Live push** — confirm, open serial, wake the console (declining the initial-configuration dialog if it appears), send the config line by line, then run the config's `verify:` checks and regex-match each one.

Output follows the course evidence format: Action → Evidence → Success Indicator → Failure Signal.

## Config files

`examples/day0-generic.yaml` is the L01-style baseline (CORE + EDGE, hostname, interface IPs from `{U}`, RSA key, local admin, SSHv2) — a working example to copy and adapt. Templates live in `templates/`. Placeholders are upper-case names in braces (`{U}`, `{USERNAME}`, `{DEVICE}`); `{ENV:VAR}` reads a secret from the environment at run time (`export DAY0_ADMIN_PASS='...'`), so no real password sits in a file.

## Secrets

The templates use `{ENV:DAY0_ADMIN_PASS}`. Export it before a live push:

```bash
export DAY0_ADMIN_PASS='...'
```

A missing secret fails loudly *before* any device is contacted.

## When to use this

L01 exists to teach this baseline **by hand** — this tool does not replace that. It's for pod reset/recovery, re-provisioning after a device wipe, and starting later labs (like NAT troubleshooting) from a known baseline instead of hand-typing it every time. The rendered template is itself a readable artifact — it's the exact baseline you built by hand in Week 1, as code.
