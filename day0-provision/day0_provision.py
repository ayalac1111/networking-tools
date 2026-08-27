#!/usr/bin/env python3
"""day0_provision.py — push a baseline config over the CONSOLE port so a
blank device becomes SSH-reachable (the day-0 chicken-and-egg).

This is a single-device console tool. It provisions one device per run over
a physical serial connection, so you already know which device you are in
front of. The YAML config + template are the source of truth for which
values a given device needs; the command line just supplies them.

Usage
-----
  # Template has no student variables:
  python3 day0_provision.py --config day0-generic.yaml --dry-run

  # Template requires {U} and {USERNAME}:
  python3 day0_provision.py --config day0-lab12.yaml \
      --u 14 --username ayal0014 --dry-run

  # Live provisioning; select device interactively when the config has several:
  python3 day0_provision.py --config day0-lab12.yaml \
      --u 14 --username ayal0014 --port /dev/ttyUSB0

  # Config carries its own `variables:` block (the SBA bundle's
  # day0-sba-<username>.yaml) — no --u / --username needed:
  python3 day0_provision.py --config day0-sba-ayal0014.yaml --device EDGE --dry-run

Behaviour
---------
  1. Load --config (required — no default, so you can never push the wrong
     definition by accident).
  2. Pick the device: one device in the YAML is selected automatically;
     several present a numbered menu (or pass --device to skip the prompt).
  3. Render the device template with whatever variables you supplied
     ({U}, {USERNAME}, ...), {DEVICE}, and {ENV:...} secrets. Any
     placeholder the template still needs but you did not supply stops the
     run before anything is sent.
  4. Safety scan: refuse templates containing erase/reload/format/delete.
  5. --dry-run (or simply omitting --port) prints the rendered config and
     stops.
  6. Otherwise: confirm, open serial, wake the console (declining the
     initial configuration dialog if it appears), send the config line by
     line, then run the verify commands and regex-check each one.

Verify checks
-------------
Each entry under a device's `verify:` list is a command plus exactly one
assertion:

    - command: "show ip ssh"
      expect: "SSH Enabled - version 2"        # regex MUST be found

    - command: "show running-config | include ip nat"
      expect_absent: "ip nat"                  # regex MUST NOT be found

`expect_absent` proves a device is *not* carrying configuration it should not
have — e.g. a previous sitting's OSPF/NAT/ACL, which would let a student pass
a checkpoint they did not build. The console echoes each command back before
its output, so the echo is stripped before matching; without that a negative
check on a pattern that appears in its own command could never pass.

Output follows the course evidence format: Action → Evidence → Success
Indicator → Failure Signal.

Author: C. Ayala — built with Laura, 2026-07-07 (roster-free rewrite 2026-07-15)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml

# --------------------------------------------------------------------------
# Placeholder rendering (self-contained — same convention as the GradeIt
# answer keys and generate_lab templates: UPPER-CASE {NAME} placeholders,
# {ENV:VAR} for secrets that must stay out of files).
# --------------------------------------------------------------------------

_ENV_RE = re.compile(r"\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")


def render(text: str, mapping: Dict[str, str]) -> str:
    """Substitute {KEY} placeholders (upper-case) from a lower-case dict.

    Unknown placeholders are left as-is so callers can detect them with
    find_unresolved().
    """
    for key, value in mapping.items():
        text = text.replace("{" + key.upper() + "}", str(value))
    return text


def find_unresolved(text: str) -> List[str]:
    """Return placeholder names still present after render() (excluding ENV)."""
    return [m for m in re.findall(r"\{([A-Z][A-Z0-9_]*)\}", text)
            if not m.startswith("ENV:")]


def resolve_env(text: str) -> str:
    """Resolve {ENV:VAR} references from the environment.

    Raises KeyError with a clear message when the variable is unset, so a
    missing password fails loudly before any device is contacted.
    """

    def _sub(match: "re.Match") -> str:
        var = match.group(1)
        if var not in os.environ:
            raise KeyError(
                f"environment variable {var} is not set "
                f"(referenced as {{ENV:{var}}})"
            )
        return os.environ[var]

    return _ENV_RE.sub(_sub, text)


FORBIDDEN = re.compile(
    r"^\s*(erase|reload|format|write\s+erase|delete\b)", re.IGNORECASE | re.MULTILINE
)

# CLI variables that a template can ask for by name — used to give a helpful
# hint when one is missing.
CLI_VARS = {"u": "--u", "username": "--username"}


def load_cfg(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        sys.exit(f"config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def select_device(cfg: Dict[str, Any], requested: str | None, config_name: str) -> str:
    """Resolve which device definition to render.

    No devices  -> configuration error.
    --device X  -> validate against the YAML (case-insensitive).
    One device  -> select it automatically.
    Several     -> numbered menu (interactive).
    """
    devices = cfg.get("devices") or {}
    names = list(devices)
    if not names:
        sys.exit(f"config '{config_name}' defines no devices.")

    if requested is not None:
        want = requested.upper()
        match = next((n for n in names if n.upper() == want), None)
        if match is None:
            sys.exit(f"device '{requested}' not in config "
                     f"(have: {', '.join(names)})")
        return match

    if len(names) == 1:
        return names[0]

    print(f"Devices available in {config_name}:\n")
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name}")
    print()
    while True:
        try:
            raw = input(f"Select a device [1-{len(names)}]: ").strip()
        except EOFError:
            sys.exit("no device selected (non-interactive run — pass --device).")
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        print(f"  please enter a number between 1 and {len(names)}.")


def render_config(cfg: Dict[str, Any], cfg_dir: Path, variables: Dict[str, str],
                  device: str) -> str:
    devices = cfg.get("devices") or {}
    if device not in devices:
        sys.exit(f"device '{device}' not in config (have: {', '.join(devices)})")
    template_rel = devices[device]["template"]
    template_path = cfg_dir / template_rel
    if not template_path.is_file():
        # A per-student config generated elsewhere (e.g. the SBA bundle's
        # day0-sba-<username>.yaml) may sit in a download folder while the
        # templates stay next to this script, which is where they are
        # pre-installed on the lab desktops. Fall back to the script's own
        # directory before giving up.
        fallback = Path(__file__).resolve().parent / template_rel
        if fallback.is_file():
            template_path = fallback
        else:
            sys.exit(f"template not found: {template_path} (also looked in "
                     f"{fallback})")
    text = template_path.read_text(encoding="utf-8")

    mapping = dict(variables)
    mapping["device"] = device
    text = render(text, mapping)
    text = resolve_env(text)

    leftover = list(dict.fromkeys(find_unresolved(text)))  # dedupe, keep order
    if leftover:
        hints = [CLI_VARS[v.lower()] for v in leftover if v.lower() in CLI_VARS]
        msg = ("template contains unresolved variables: "
               f"{{{'}, {'.join(leftover)}}}. ")
        if hints:
            msg += f"Run again with {', '.join(sorted(set(hints)))}."
        else:
            msg += ("Provide the required command-line argument or correct "
                    "the template.")
        sys.exit(msg)
    if FORBIDDEN.search(text):
        sys.exit(
            "SAFETY: template contains a destructive command "
            "(erase/reload/format/delete). day0_provision refuses to send it."
        )
    return text


def identity_label(variables: Dict[str, str]) -> str:
    """A short human label for the run, from whatever identity we were given."""
    parts: List[str] = []
    if variables.get("username"):
        parts.append(variables["username"])
    if variables.get("u"):
        parts.append(f"U={variables['u']}")
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Serial session
# --------------------------------------------------------------------------

class Console:
    """Thin pyserial wrapper for a Cisco console session."""

    def __init__(self, port: str, baud: int, timeout: float):
        try:
            import serial  # type: ignore
        except ImportError:
            sys.exit("pyserial is required for live pushes: pip install pyserial")
        self.ser = serial.Serial(port, baud, timeout=timeout)

    def read_available(self, settle: float = 0.4) -> str:
        time.sleep(settle)
        data = b""
        while self.ser.in_waiting:
            data += self.ser.read(self.ser.in_waiting)
            time.sleep(0.1)
        return data.decode(errors="ignore")

    def send_line(self, line: str, settle: float = 0.25) -> str:
        self.ser.write((line + "\r").encode())
        return self.read_available(settle)

    def wake(self) -> str:
        """Wake the console; decline the initial configuration dialog."""
        out = self.send_line("", 1.0)
        for _ in range(6):
            if "initial configuration dialog" in out.lower():
                out += self.send_line("no", 1.0)
            elif "terminate autoinstall" in out.lower():
                out += self.send_line("yes", 1.0)
            elif re.search(r"[>#]\s*$", out):
                return out
            else:
                out += self.send_line("", 1.0)
        return out

    def close(self) -> None:
        self.ser.close()


def push_config(console: Console, config_text: str, echo: bool) -> List[str]:
    """Send config line by line; collect any '%' error lines the device echoes."""
    errors: List[str] = []
    for raw in config_text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("!"):
            continue
        out = console.send_line(line)
        if echo:
            print(f"  > {line}")
        # interactive confirmations (e.g. replacing existing RSA keys)
        if re.search(r"\[yes/no\]|\? \[confirm\]", out, re.IGNORECASE):
            out += console.send_line("yes", settle=1.0)
        if "generate rsa" in line.lower():
            # key generation can take a few seconds on older gear
            out += console.read_available(settle=4.0)
        for reply in out.splitlines():
            if reply.strip().startswith("%"):
                errors.append(f"{line}  ->  {reply.strip()}")
                print(f"    ! {reply.strip()}")
    return errors


def check_assertion(chk: Dict[str, str]) -> str:
    """Return which assertion key a verify entry uses: 'expect' or
    'expect_absent'. Exits with a clear message if it is not exactly one."""
    has_expect = "expect" in chk
    has_absent = "expect_absent" in chk
    if has_expect and has_absent:
        sys.exit(f"verify check {chk.get('command','?')!r} defines both "
                 "'expect' and 'expect_absent' — use exactly one.")
    if not has_expect and not has_absent:
        sys.exit(f"verify check {chk.get('command','?')!r} defines neither "
                 "'expect' nor 'expect_absent' — use exactly one.")
    return "expect" if has_expect else "expect_absent"


def validate_checks(checks: List[Dict[str, str]], device: str) -> None:
    """Fail fast on a malformed verify list, before anything is sent."""
    for chk in checks or []:
        if not isinstance(chk, dict) or "command" not in chk:
            sys.exit(f"device '{device}': every verify entry needs a "
                     "'command' key.")
        check_assertion(chk)


def strip_echo(output: str, command: str) -> str:
    """Remove the console's echo of the command from its own output.

    The device echoes each keystroke, so the command text appears in the
    captured output ahead of the real result. A positive 'expect' rarely
    notices; a negative 'expect_absent' would *always* match its own command
    and could never pass. Dropping the echoed line(s) makes both assertions
    test the device's answer rather than the question.
    """
    needle = command.strip()
    if not needle:
        return output
    return "\n".join(line for line in output.splitlines()
                     if needle not in line)


def verify(console: Console, checks: List[Dict[str, str]],
           mapping: Dict[str, str]) -> bool:
    all_ok = True
    print("\nVerification")
    print("-" * 56)
    for chk in checks:
        key = check_assertion(chk)
        negate = key == "expect_absent"
        command = render(str(chk["command"]), mapping)
        pattern = render(str(chk[key]), mapping)
        # Optional, per-check. Every existing check omits these, so retries
        # defaults to 0 and behaviour is byte-for-byte what it was: one
        # command, one 1.2s settle, one verdict. Added for NTP (item 49):
        # sync is not instant even on a correctly configured device, and a
        # single immediate poll would false-fail the same way §4 items 1-3
        # did — this makes "not converged yet" retry instead of fail.
        retries = int(chk.get("retries", 0))
        retry_interval = float(chk.get("retry_interval", 5.0))
        attempt = 0
        while True:
            output = console.send_line(command, settle=1.2)
            # drain paged output
            while "--More--" in output:
                console.ser.write(b" ")
                output += console.read_available(0.6)
            body = strip_echo(output, command)
            found = re.search(pattern, body) is not None
            ok = (not found) if negate else found
            if ok or attempt >= retries:
                break
            attempt += 1
            print(f"     not ready yet ({attempt}/{retries}) — "
                  f"retrying in {retry_interval:.0f}s")
            time.sleep(retry_interval)
        all_ok &= ok
        mark = "✔" if ok else "✘"
        suffix = f" (after {attempt} retr{'y' if attempt == 1 else 'ies'})" if attempt else ""
        print(f"[{mark}] {command}{suffix}")
        print(f"     expected: {'MUST NOT match ' if negate else ''}{pattern}")
        if not ok and negate:
            hits = [ln.strip() for ln in body.splitlines()
                    if re.search(pattern, ln)][:5]
            print("     found (must not be present):\n       "
                  + "\n       ".join(hits))
            print("     -> this device still carries configuration from a "
                  "previous sitting; clean it and re-push.")
        elif not ok:
            tail = "\n".join(body.strip().splitlines()[-5:])
            print("     got (last lines):\n       " + tail.replace("\n", "\n       "))
    print("-" * 56)
    return all_ok


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True,
                    help="path to the provisioning YAML (required)")
    ap.add_argument("--u", help="your U number, if the template uses {U}")
    ap.add_argument("--username",
                    help="your username, if the template uses {USERNAME}")
    ap.add_argument("--device",
                    help="device role (e.g. CORE); omit to select "
                         "interactively when the config has several devices")
    ap.add_argument("--port",
                    help="serial port (e.g. /dev/ttyUSB0, COM3). Omit for a dry run.")
    ap.add_argument("--baud", type=int, default=None,
                    help="override baud (default from config or 9600)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the rendered config and send nothing "
                         "(also the default when --port is omitted)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    ap.add_argument("--quiet", action="store_true",
                    help="don't echo each line as it is sent")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_cfg(cfg_path)
    cfg_dir = cfg_path.parent

    # Build the variable mapping. A config may carry its own `variables:`
    # block — that is how a per-student config (day0-sba-<username>.yaml from
    # the SBA bundle) can be run with no flags at all:
    #
    #     python3 day0_provision.py --config day0-sba-ayal0014.yaml --device EDGE
    #
    # Command-line arguments still win, so an instructor can override one
    # value without editing the file.
    variables: Dict[str, str] = {}
    for key, value in (cfg.get("variables") or {}).items():
        variables[str(key).lower()] = str(value).strip()
    if args.u is not None:
        variables["u"] = str(args.u).strip()
    if args.username is not None:
        variables["username"] = args.username.strip().lower()

    device = select_device(cfg, args.device, cfg_path.name)
    config_text = render_config(cfg, cfg_dir, variables, device)
    checks = (cfg["devices"][device].get("verify") or [])
    # Validated here, not at verify() time, so a malformed check is caught by
    # --dry-run instead of after the config has already been pushed.
    validate_checks(checks, device)

    label = identity_label(variables)
    who = f" for {label}" if label else ""

    if args.dry_run or not args.port:
        print(f"! Rendered day-0 config — {device}{who} (dry-run)\n")
        print(config_text)
        if not args.port:
            print("\n(no --port given; nothing was sent)")
        return 0

    print("\nAbout to push a baseline over the console:")
    print(f"  Configuration: {cfg_path.name}")
    print(f"  Device:        {device}{who}")
    print(f"  Serial port:   {args.port}")
    if not args.yes:
        answer = input(f"\nType {device} to begin: ").strip().upper()
        if answer != device.upper():
            print("aborted.")
            return 1

    serial_cfg = cfg.get("serial") or {}
    baud = args.baud or int(serial_cfg.get("baud", 9600))
    timeout = float(serial_cfg.get("timeout", 3))

    console = Console(args.port, baud, timeout)
    try:
        print("Waking console ...")
        console.wake()
        print("Sending configuration ...")
        errors = push_config(console, config_text, echo=not args.quiet)
        if errors:
            print(f"\n{len(errors)} line(s) were rejected by the device:")
            for e in errors:
                print(f"  ✘ {e}")

        mapping = dict(variables)
        mapping["device"] = device
        ok = verify(console, checks, mapping) if checks else True
    finally:
        console.close()

    if ok and not errors:
        print(f"✔ {device}{who} is provisioned — "
              f"SSH should now work from the management network.")
        return 0
    print("✘ Provisioning finished with problems — review the output above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
