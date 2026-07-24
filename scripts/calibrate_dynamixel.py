#!/usr/bin/env python3
"""Interactive calibration for preconfigured Dynamixel X-series neck motors.

This script assumes motor IDs, baud rate, and communication are already
configured. It records safe min, neutral, and max ticks for both neck axes and
writes the JSON schema used by the Sentinel neck adapter.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler

PROTOCOL_VERSION = 2.0

ADDR_HOMING_OFFSET = 20
ADDR_MAX_POSITION_LIMIT = 48
ADDR_MIN_POSITION_LIMIT = 52
ADDR_TORQUE_ENABLE = 64
ADDR_HARDWARE_ERROR = 70
ADDR_PRESENT_POSITION = 132

ENCODER_TICKS = 4096


def _decode_i32(value: int) -> int:
    return value - (1 << 32) if value & (1 << 31) else value


def _normalize_axis_ticks(
    ext_a: int,
    neutral: int,
    ext_b: int,
) -> tuple[int, int, int]:
    """Return ticks ordered as min < neutral < max.

    X-series present-position values are continuous while torque is off. Shift
    the recorded range so neutral lies within one encoder revolution while
    preserving a range that crosses the encoder boundary.
    """
    shift = (neutral // ENCODER_TICKS) * ENCODER_TICKS
    ext_a -= shift
    neutral -= shift
    ext_b -= shift

    lo, hi = min(ext_a, ext_b), max(ext_a, ext_b)
    if not (lo < neutral < hi):
        raise RuntimeError(
            "Recorded ticks are not ordered min < neutral < max after "
            f"normalization: ({ext_a}, {neutral}, {ext_b}). Move the axis "
            "between its two safe extremes without making a full turn."
        )
    return lo, neutral, hi


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calibrate a Dynamixel X-series Sentinel neck"
    )
    parser.add_argument(
        "--port",
        default="/dev/ttyACM0",
        help="Serial port (default: /dev/ttyACM0)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=1_000_000,
        help="Baud rate (default: 1000000)",
    )
    parser.add_argument(
        "--yaw-id",
        type=int,
        default=2,
        help="Yaw motor ID (default: 2)",
    )
    parser.add_argument(
        "--pitch-id",
        type=int,
        default=1,
        help="Pitch motor ID (default: 1)",
    )
    parser.add_argument(
        "--output",
        default="/config/neck_calibration.json",
        help="Output calibration JSON (default: /config/neck_calibration.json)",
    )
    return parser.parse_args()


def _check(packet, comm: int, error: int, action: str) -> None:
    if comm != COMM_SUCCESS:
        raise RuntimeError(
            f"{action}: communication error: {packet.getTxRxResult(comm)}"
        )
    if error != 0:
        raise RuntimeError(f"{action}: motor error: {packet.getRxPacketError(error)}")


def _ping_motor(port, packet, motor_id: int) -> int | None:
    model_number, result, _ = packet.ping(port, motor_id)
    if result != COMM_SUCCESS:
        return None
    return int(model_number)


def _read_position(port, packet, motor_id: int) -> int:
    raw, result, error = packet.read4ByteTxRx(
        port,
        motor_id,
        ADDR_PRESENT_POSITION,
    )
    _check(packet, result, error, f"read position from motor ID {motor_id}")
    return _decode_i32(int(raw))


def _set_torque(port, packet, motor_id: int, enabled: bool) -> None:
    result, error = packet.write1ByteTxRx(
        port,
        motor_id,
        ADDR_TORQUE_ENABLE,
        1 if enabled else 0,
    )
    _check(
        packet,
        result,
        error,
        f"set torque={int(enabled)} for motor ID {motor_id}",
    )


def main() -> int:
    args = _parse_args()
    output_path = Path(args.output).expanduser()

    print("=" * 70)
    print("Sentinel neck calibration — Dynamixel X-series")
    print("=" * 70)
    print(f"Port: {args.port}")
    print(f"Baud rate: {args.baudrate}")
    print(f"Yaw motor ID: {args.yaw_id}")
    print(f"Pitch motor ID: {args.pitch_id}")
    print()
    print("This script does not configure motor IDs or baud rate.")
    print("Move gently and stay within the mount's safe mechanical limits.")
    print()

    port = PortHandler(args.port)
    packet = PacketHandler(PROTOCOL_VERSION)

    if not port.openPort():
        print(f"Failed to open port: {args.port}")
        return 1
    if not port.setBaudRate(args.baudrate):
        print(f"Failed to set baud rate: {args.baudrate}")
        port.closePort()
        return 1

    print(f"Connected to {args.port}")
    print()

    try:
        yaw_model = _ping_motor(port, packet, args.yaw_id)
        pitch_model = _ping_motor(port, packet, args.pitch_id)
        if yaw_model is None or pitch_model is None:
            print("One or both motors did not respond at the configured IDs.")
            print(
                f"  yaw_id={args.yaw_id}: "
                f"{'OK' if yaw_model is not None else 'not found'}"
            )
            print(
                f"  pitch_id={args.pitch_id}: "
                f"{'OK' if pitch_model is not None else 'not found'}"
            )
            print("Check wiring, motor power, IDs, and baud rate.")
            return 1

        print(f"Yaw motor detected: ID {args.yaw_id}, model {yaw_model}")
        print(f"Pitch motor detected: ID {args.pitch_id}, model {pitch_model}")

        for motor_id in (args.yaw_id, args.pitch_id):
            hardware_error, result, error = packet.read1ByteTxRx(
                port,
                motor_id,
                ADDR_HARDWARE_ERROR,
            )
            _check(
                packet,
                result,
                error,
                f"read hardware status from motor ID {motor_id}",
            )
            if hardware_error != 0:
                print(
                    f"Motor ID {motor_id} has a latched hardware error "
                    f"(0x{hardware_error:02X})."
                )
                print("Fix the cause, reboot the motor, and retry.")
                return 1

        print("No motor hardware errors")
        print()

        print("Disabling torque so you can move the axes by hand...")
        _set_torque(port, packet, args.yaw_id, enabled=False)
        _set_torque(port, packet, args.pitch_id, enabled=False)
        print("Torque disabled")
        print()

        print("Resetting EEPROM position limits to one full revolution...")
        for motor_id in (args.yaw_id, args.pitch_id):
            raw_offset, result, error = packet.read4ByteTxRx(
                port,
                motor_id,
                ADDR_HOMING_OFFSET,
            )
            _check(
                packet,
                result,
                error,
                f"read homing offset from motor ID {motor_id}",
            )
            offset = _decode_i32(int(raw_offset))
            if offset != 0:
                print(f"  Motor ID {motor_id} has homing offset {offset}; keeping it")

            result, error = packet.write4ByteTxRx(
                port,
                motor_id,
                ADDR_MIN_POSITION_LIMIT,
                0,
            )
            _check(
                packet,
                result,
                error,
                f"reset minimum position limit on motor ID {motor_id}",
            )
            time.sleep(0.05)

            result, error = packet.write4ByteTxRx(
                port,
                motor_id,
                ADDR_MAX_POSITION_LIMIT,
                ENCODER_TICKS - 1,
            )
            _check(
                packet,
                result,
                error,
                f"reset maximum position limit on motor ID {motor_id}",
            )
            time.sleep(0.05)

            min_value, result, error = packet.read4ByteTxRx(
                port,
                motor_id,
                ADDR_MIN_POSITION_LIMIT,
            )
            _check(
                packet,
                result,
                error,
                f"verify minimum position limit on motor ID {motor_id}",
            )
            max_value, result, error = packet.read4ByteTxRx(
                port,
                motor_id,
                ADDR_MAX_POSITION_LIMIT,
            )
            _check(
                packet,
                result,
                error,
                f"verify maximum position limit on motor ID {motor_id}",
            )
            if min_value != 0 or max_value != ENCODER_TICKS - 1:
                raise RuntimeError(
                    f"Failed to reset position limits on motor ID {motor_id}: "
                    f"got [{min_value}, {max_value}]"
                )
        print("EEPROM position limits verified")
        print()

        print("=" * 70)
        print(f"YAW MOTOR (ID {args.yaw_id}) — left and right")
        print("=" * 70)
        input("Move yaw to its LEFTMOST safe position, then press ENTER...")
        yaw_left_ticks = _read_position(port, packet, args.yaw_id)
        print(f"Yaw left: {yaw_left_ticks} ticks")

        input("Move yaw to its RIGHTMOST safe position, then press ENTER...")
        yaw_right_ticks = _read_position(port, packet, args.yaw_id)
        print(f"Yaw right: {yaw_right_ticks} ticks")

        input("Move yaw to NEUTRAL, then press ENTER...")
        yaw_neutral_ticks = _read_position(port, packet, args.yaw_id)
        print(f"Yaw neutral: {yaw_neutral_ticks} ticks")
        print()

        print("=" * 70)
        print(f"PITCH MOTOR (ID {args.pitch_id}) — down and up")
        print("=" * 70)
        input("Move pitch to its LOWEST safe position, then press ENTER...")
        pitch_down_ticks = _read_position(port, packet, args.pitch_id)
        print(f"Pitch down: {pitch_down_ticks} ticks")

        input("Move pitch to its HIGHEST safe position, then press ENTER...")
        pitch_up_ticks = _read_position(port, packet, args.pitch_id)
        print(f"Pitch up: {pitch_up_ticks} ticks")

        input("Move pitch to NEUTRAL, then press ENTER...")
        pitch_neutral_ticks = _read_position(port, packet, args.pitch_id)
        print(f"Pitch neutral: {pitch_neutral_ticks} ticks")
        print()

        yaw_increases_right = yaw_right_ticks > yaw_left_ticks
        pitch_increases_up = pitch_up_ticks > pitch_down_ticks

        yaw_min_ticks, yaw_neutral_ticks, yaw_max_ticks = _normalize_axis_ticks(
            yaw_left_ticks,
            yaw_neutral_ticks,
            yaw_right_ticks,
        )
        pitch_min_ticks, pitch_neutral_ticks, pitch_max_ticks = (
            _normalize_axis_ticks(
                pitch_down_ticks,
                pitch_neutral_ticks,
                pitch_up_ticks,
            )
        )

        calibration = {
            "yaw_min_ticks": yaw_min_ticks,
            "yaw_neutral_ticks": yaw_neutral_ticks,
            "yaw_max_ticks": yaw_max_ticks,
            "pitch_min_ticks": pitch_min_ticks,
            "pitch_neutral_ticks": pitch_neutral_ticks,
            "pitch_max_ticks": pitch_max_ticks,
            "yaw_increases_right": yaw_increases_right,
            "pitch_increases_up": pitch_increases_up,
            "yaw_left_ticks": yaw_left_ticks,
            "yaw_right_ticks": yaw_right_ticks,
            "pitch_down_ticks": pitch_down_ticks,
            "pitch_up_ticks": pitch_up_ticks,
            "motor_backend": "dynamixel",
        }

        print("=" * 70)
        print("Calibration result")
        print("=" * 70)
        print(json.dumps(calibration, indent=2))
        print()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(calibration, indent=2),
            encoding="utf-8",
        )
        print(f"Saved calibration file: {output_path}")
        return 0

    except KeyboardInterrupt:
        print("\nCalibration cancelled.")
        return 1
    except Exception as error:
        print(f"\nCalibration failed: {error}")
        return 1
    finally:
        for motor_id in (args.yaw_id, args.pitch_id):
            try:
                _set_torque(port, packet, motor_id, enabled=False)
            except Exception:
                pass
        port.closePort()
        print("Disconnected")


if __name__ == "__main__":
    sys.exit(main())
