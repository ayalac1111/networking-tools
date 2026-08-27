# networking-tools

Python tools for networking students to run against their own pod's network devices. Each tool is self-contained in its own folder — download or clone this repo, `cd` into the tool you need, install its requirements, and run it.

## Tools

### [x-remote](x-remote/)

Runs a YAML-defined set of commands on your pod's devices over SSH and logs the output. Useful for collecting verification/evidence output for labs and SBAs.

**How it works**:
For each device listed in your YAML file, `x-remote` opens an SSH connection to its IP address using the credentials you provide, runs the listed commands one by one, and writes each command's output to a log file (and the screen). 
It uses `netmiko` underneath, so the same script works across multiple platforms — Cisco IOS, MikroTik RouterOS, and Linux devices are all supported by setting `device_type` per device in the YAML.

```bash
cd x-remote
pip install -r requirements.txt
python3 x_remote.py --commands examples/verification_commands.yaml
```

### [day0-provision](day0-provision/)

Pushes a baseline configuration onto a blank device over its console (serial) port, so it becomes SSH-reachable. For pod reset/recovery and starting later labs from a known baseline — not a replacement for the L01 by-hand baseline.

**How it works**: 
A brand-new device has no IP address yet, so SSH isn't an option — `day0-provision` instead talks over the physical console (serial) cable using pyserial. It renders a config template with your variables (`{U}`, `{USERNAME}`, etc.), sends it to the device line by line over the console port, then re-connects over the console to run a few verification commands and confirm the device came up correctly. Because it drives the console port directly rather than an SSH library, it works the same way regardless of whether the far end is Cisco IOS or another platform, as long as the template matches that device's CLI.

```bash
cd day0-provision
pip install -r requirements.txt
python3 day0_provision.py --config examples/day0-generic.yaml \
    --u 14 --username ayal0014 --dry-run
```

## Getting the code

```bash
git clone <this-repo-url>
```

Each tool's own README has full usage details and options.
