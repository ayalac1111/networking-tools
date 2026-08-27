#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
x_remote: A utility to execute a set of commands on different devices using SSH.
The script reads a YAML file with device information and commands to execute.

Usage:
    python x_remote.py --commands verification_commands.yaml
    python x_remote.py verification_commands.yaml
    python x_remote.py --help

Author: C. Ayala - ayalac@algonquincollege.com
Date: September 16th 2024

"""
# TODO:  1. Rename script to xremote.
# TODO:  2. Create a hash to write into the file to ensure uniqueness in the execution of the commands

import os
import re
import sys
import yaml
import argparse
import logging
from datetime import datetime


def parse_arguments():
    """Parse the command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="x_remote.py",
        description="Execute YAML-defined command sets on network devices over SSH.",
        epilog=(
            "Examples:\n"
            "  python x_remote.py --commands verification_commands.yaml\n"
            "  python x_remote.py verification_commands.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "yaml_file",
        nargs="?",
        help="YAML file with devices and commands to run.",
    )
    parser.add_argument(
        "-c",
        "--commands",
        dest="commands_file",
        help="YAML file with devices and commands to run.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the YAML file structure and exit. Connects to nothing.",
    )

    args = parser.parse_args()

    if args.yaml_file and args.commands_file:
        parser.error("provide the YAML file once, either as a positional argument or with --commands.")

    args.commands = args.commands_file or args.yaml_file

    if not args.commands:
        parser.error("no YAML file provided. Use --commands FILE.yaml or run with --help.")

    if not args.commands.lower().endswith((".yaml", ".yml")):
        parser.error(f"commands file must be a .yaml or .yml file: {args.commands}")

    return args


def read_yaml_commands(commands):
    """Read devices and commands from the YAML file."""

    if not os.path.isfile(commands):
        logging.error(f"Commands file {commands} does not exist.")
        sys.exit(1)

    with open(commands, 'r') as file:
        try:
            data = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            logging.error(f"Error reading YAML file: {exc}")
            sys.exit(1)

    # Extract output_file
    output_file = data.get('output_file', None)

    # Extract the device info and commands
    devices = []
    for device_entry in data.get('devices', []):
        device_info = device_entry.get('device_info')
        commands = device_entry.get('commands', [])
        devices.append((device_info, commands))

    return devices, output_file


ENV_REF = re.compile(r"\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_env_values(device_info):
    """Resolve {ENV:VAR} references in device_info values.

    Lets a YAML say  password: "{ENV:LAB_PASS}"  so real passwords never
    sit in the file. Raises KeyError when the variable is unset.
    """
    resolved = {}
    for key, value in device_info.items():
        if isinstance(value, str):
            def _sub(match, _key=key):
                var = match.group(1)
                if var not in os.environ:
                    raise KeyError(
                        f"environment variable {var} is not set (used by '{_key}')"
                    )
                return os.environ[var]
            value = ENV_REF.sub(_sub, value)
        resolved[key] = value
    return resolved


def check_yaml(devices, output_file, commands_path):
    """Validate the YAML structure without connecting (--check).

    Returns True when every device entry is usable. Catches the classic
    mistake of writing device_info fields as a dashed list instead of a
    mapping (see README for the correct layout).
    """
    ok = True
    if not devices:
        print(f"FAIL {commands_path}: no devices found. Check indentation: "
              "each entry under devices: needs device_info: and commands:.")
        return False
    for i, (device_info, commands) in enumerate(devices, 1):
        if not isinstance(device_info, dict):
            print(f"FAIL device #{i}: device_info is not a mapping "
                  f"(got {type(device_info).__name__}). Write its fields as "
                  "'key: value' lines, NOT '- key: value' list items.")
            ok = False
            continue
        label = f"device #{i} ({device_info.get('ip', 'no ip')})"
        entry_ok = True
        missing = [k for k in ("device_type", "ip", "username", "password")
                   if k not in device_info]
        if missing:
            print(f"FAIL {label}: missing fields: {', '.join(missing)}")
            entry_ok = False
        if not commands:
            print(f"FAIL {label}: no commands listed")
            entry_ok = False
        elif not all(isinstance(c, str) for c in commands):
            print(f"FAIL {label}: every command must be a plain string")
            entry_ok = False
        if entry_ok:
            print(f"OK   {label}: {len(commands)} command(s)")
        ok = ok and entry_ok
    print(f"Output file: {output_file or '(default log_<timestamp>.txt)'}")
    return ok


def establish_ssh_connection(device_info):
    """Establish SSH connection to the device using netmiko."""

    try:
        from netmiko import (
            ConnectHandler,
            NetMikoAuthenticationException,
            NetMikoTimeoutException,
        )
    except ImportError:
        logging.error("The netmiko package is required to connect to devices. Install it with: pip install netmiko")
        return None

    try:
        device_info = resolve_env_values(device_info)
    except KeyError as exc:
        logging.error(str(exc))
        return None

    try:
        logging.info(f"Connecting to {device_info['ip']}...")
        connection = ConnectHandler(**device_info)
        logging.info(f"Successfully connected to {device_info['ip']}.")
        return connection
    except NetMikoTimeoutException:
        logging.error(f"Connection timed out for {device_info['ip']}.")
    except NetMikoAuthenticationException:
        logging.error(f"Authentication failed for {device_info['ip']}.")
    except Exception as e:
        logging.error(f"An error occurred while connecting to {device_info['ip']}: {str(e)}")
    return None


def execute_commands(connection, commands, log_file):
    """Execute the list of commands on the device and log the output."""
    output = []  # To collect all outputs before writing to the log

    for command in commands:
        # Write the command to the output
        output.append('\n' + '+' + '-' * 80)
        output.append(f"|Command: {command}")
        output.append('+' + '-' * 80)

        # Execute the command
        result = connection.send_command(command)

        # Append the result of the command to the output
        output.append(result)

        # Write the collected output to the log file and print to the screen
        log_file.write("\n".join(output))  # Write everything to the log
        log_file.flush()  # Ensure data is written to the file

        print("\n".join(output))  # Display everything on the screen

        # Clear the output list after writing/printing for the next command
        output.clear()


def main():
    """Main function for the command_master script."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Parse arguments
    args = parse_arguments()

    # Read devices and commands from the YAML file
    devices, output_file = read_yaml_commands(args.commands)

    # --check: validate and exit without connecting to anything
    if args.check:
        sys.exit(0 if check_yaml(devices, output_file, args.commands) else 1)

    # If no output file is specified in the YAML, use a default log file name
    if not output_file:
        current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        output_file = f"log_{current_time}.txt"

    # Open the log file for writing (overwriting any existing content)
    with open(output_file, 'w') as log_file:
        # TODO: Write file header

        for device_info, commands in devices:  # Unpack the tuple here
            output = []
            if not isinstance(device_info, dict) or 'ip' not in device_info:
                logging.error("Skipping a device entry with malformed device_info "
                              "(run with --check to see what is wrong).")
                continue
            ip = device_info['ip']
            logging.info(f"Connecting to {ip}...")

            # Establish SSH connection
            connection = establish_ssh_connection(device_info)

            if connection:
                # Execute commands and write the output to the log file
                # Write device ip address into the file
                logging.info(f"Collecting information from {ip}...")
                output.append('\n' + '=' * 80 + '\n')
                output.append(f" Device: {ip}\n")
                output.append('=' * 80 + '\n')

                log_file.write("\n".join(output))
                log_file.flush()  # Ensure data is written to the file

                # print on the screen the device name
                print("\n".join(output))

                execute_commands(connection, commands, log_file)
                connection.disconnect()
            else:
                logging.error(f"| Failed to connect to {ip}")

        footer = ['\n' + '*' * 80, "*  END OF DATA COLLECTION", '*' * 80]
        log_file.write("\n".join(footer))
        log_file.flush()  # Ensure data is written to the file
        print("\n".join(footer))

    logging.info(f"All commands executed. Output saved to {output_file}")


if __name__ == "__main__":
    main()