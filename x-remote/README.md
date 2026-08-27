# x_remote

`x_remote.py` collects configuration and verification output from your pod's network devices (Cisco, MikroTik, Linux) over SSH. You give it a YAML file listing which devices to connect to and which commands to run on each one; it logs everything to a file and prints it to the screen as it goes.

This is the same tool used for evidence collection in lab verification — running it against your own pod's devices is a fast way to capture the `show` output a lab or SBA asks you to submit.

## Requirements

- Python 3.x
- `pyyaml`, `paramiko`, `netmiko`

```bash
pip install -r requirements.txt
```

## Usage

```bash
python3 x_remote.py --commands my_commands.yaml
python3 x_remote.py my_commands.yaml        # positional form works too
python3 x_remote.py --help
```

### Writing the YAML file

See `examples/verification_commands.yaml` for a working starting point. Structure:

```yaml
output_file: /path/to/output.log
devices:
  - device_info:
      device_type: cisco_ios
      ip: 192.0.2.1
      username: admin
      password: "{ENV:LAB_PASS}"
    commands:
      - show ip interface brief | exclude unassigned
      - show running-config
```

**Layout rules (the #1 source of errors):**

- `device_info:` is an indented mapping (`key: value`), **not** a dashed list (`- key: value`).
- `commands:` belongs to the same list item as its `device_info:` — same indentation, no leading dash.
- `password: "{ENV:LAB_PASS}"` reads the password from an environment variable at run time (`export LAB_PASS='...'`) so no real password sits in the file. A literal password also works, but avoid committing one.

### Validate before connecting

```bash
python3 x_remote.py --check my_commands.yaml
```

This checks the YAML structure and reports problems (missing fields, wrong layout) without opening any SSH connection.

### Output

- Saved to the `output_file` named in the YAML, or to `log_YYYY-MM-DD_HH-MM-SS.txt` if none is given.
- Also printed to the screen as each command runs.
