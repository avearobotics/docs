#!/usr/bin/env python3
"""Interactive calibration for preconfigured XLERobotNeck motors.

This script assumes motor IDs and communication settings are already configured.
It only records calibration tick values and writes a runtime-compatible JSON file.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import scservo_sdk as scs

TORQUE_ENABLE_ADDR = 40
MIN_POSITION_LIMIT_ADDR = 9
MAX_POSITION_LIMIT_ADDR = 11
PRESENT_POSITION_ADDR = 56
ENCODER_TICKS = 4096  # STS3215 / SCS-series: 12-bit encoder (0–4095)


def _normalize_axis_ticks(ext_a: int, neutral: int, ext_b: int) -> tuple[int, int, int]:
    """Return (min_ticks, neutral_ticks, max_ticks) satisfying min < neutral < max.

    Handles encoder wrap-around: when the motor's operating range crosses the
    0/ENCODER_TICKS boundary, the neutral position may fall outside the direct
    [min(ext_a, ext_b), max(ext_a, ext_b)] interval.  In that case the wrap-side
    extreme is returned as a *negative* value (extreme - ENCODER_TICKS) so that
    the invariant min < neutral < max still holds.

    The controller converts any negative tick value to a valid motor position via
    ``tick % ENCODER_TICKS`` before writing to hardware.
    """
    lo, hi = min(ext_a, ext_b), max(ext_a, ext_b)
    if lo < neutral < hi:
        return lo, neutral, hi

    # Wrap case: determine which extreme is reached by going *increasing* from
    # neutral (direct path) vs *decreasing* (wrapping through 0 → ENCODER_TICKS).
    dist_a_inc = (ext_a - neutral) % ENCODER_TICKS
    dist_b_inc = (ext_b - neutral) % ENCODER_TICKS
    if dist_a_inc < dist_b_inc:
        # ext_a is on the direct (increasing) side; ext_b wraps
        return ext_b - ENCODER_TICKS, neutral, ext_a
    else:
        # ext_b is on the direct (increasing) side; ext_a wraps
        return ext_a - ENCODER_TICKS, neutral, ext_b


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate XLERobotNeck (calibration-only workflow)")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    parser.add_argument("--baudrate", type=int, default=1_000_000, help="Serial baudrate (default: 1000000)")
    parser.add_argument("--yaw-id", type=int, default=2, help="Yaw motor ID (default: 2)")
    parser.add_argument("--pitch-id", type=int, default=1, help="Pitch motor ID (default: 1)")
    parser.add_argument(
        "--output",
        default="/config/neck_calibration.json",
        help="Output calibration JSON path (default: /config/neck_calibration.json)",
    )
    return parser.parse_args()


def _ping_motor(port_handler, packet_handler, motor_id: int) -> int | None:
    model_num, result, _ = packet_handler.ping(port_handler, motor_id)
    if result != scs.COMM_SUCCESS:
        return None
    return int(model_num)


def _read_position(port_handler, packet_handler, motor_id: int) -> int:
    position, result, error = packet_handler.read2ByteTxRx(port_handler, motor_id, PRESENT_POSITION_ADDR)
    if result != scs.COMM_SUCCESS:
        raise RuntimeError(f"Failed to read position from motor ID {motor_id}: {packet_handler.getTxRxResult(result)}")
    if error != 0:
        raise RuntimeError(f"Motor ID {motor_id} returned error while reading position: 0x{error:02x}")
    return int(position)


def _set_torque(port_handler, packet_handler, motor_id: int, enabled: bool) -> None:
    value = 1 if enabled else 0
    result, error = packet_handler.write1ByteTxRx(port_handler, motor_id, TORQUE_ENABLE_ADDR, value)
    if result != scs.COMM_SUCCESS:
        raise RuntimeError(
            f"Failed to set torque={value} for motor ID {motor_id}: {packet_handler.getTxRxResult(result)}"
        )
    if error != 0:
        raise RuntimeError(f"Motor ID {motor_id} returned error while setting torque: 0x{error:02x}")


def main() -> int:
    args = _parse_args()
    output_path = Path(args.output).expanduser()

    print("=" * 70)
    print("XLERobotNeck Calibration (Calibration-Only)")
    print("=" * 70)
    print(f"Port: {args.port}")
    print(f"Baudrate: {args.baudrate}")
    print(f"Yaw motor ID: {args.yaw_id}")
    print(f"Pitch motor ID: {args.pitch_id}")
    print()
    print("This script does NOT configure motor IDs, baudrate, or other setup values.")
    print("It only records calibration ticks for motors that are already configured.")
    print()
    print("Move gently and stay within safe mechanical limits.")
    print()

    port_handler = scs.PortHandler(args.port)
    packet_handler = scs.PacketHandler(scs.SCS_END)

    if not port_handler.openPort():
        print(f"✗ Failed to open port: {args.port}")
        return 1
    if not port_handler.setBaudRate(args.baudrate):
        print(f"✗ Failed to set baudrate: {args.baudrate}")
        port_handler.closePort()
        return 1

    print(f"✓ Connected to {args.port}")
    print()

    try:
        yaw_model = _ping_motor(port_handler, packet_handler, args.yaw_id)
        pitch_model = _ping_motor(port_handler, packet_handler, args.pitch_id)
        if yaw_model is None or pitch_model is None:
            print("✗ One or both motors did not respond at configured IDs.")
            print(f"  - yaw_id={args.yaw_id}: {'OK' if yaw_model is not None else 'not found'}")
            print(f"  - pitch_id={args.pitch_id}: {'OK' if pitch_model is not None else 'not found'}")
            print("Check wiring/power/IDs and retry.")
            return 1

        print(f"✓ Yaw motor detected (ID {args.yaw_id}, model {yaw_model})")
        print(f"✓ Pitch motor detected (ID {args.pitch_id}, model {pitch_model})")
        print()

        print("Disabling torque so you can move motors by hand...")
        _set_torque(port_handler, packet_handler, args.yaw_id, enabled=False)
        _set_torque(port_handler, packet_handler, args.pitch_id, enabled=False)
        print("✓ Torque disabled")
        print()

        print("Resetting EEPROM position limits to full range...")
        for motor_id in [args.yaw_id, args.pitch_id]:
            packet_handler.write2ByteTxRx(port_handler, motor_id, MIN_POSITION_LIMIT_ADDR, 0)
            time.sleep(0.05)
            port_handler.clearPort()
            packet_handler.write2ByteTxRx(port_handler, motor_id, MAX_POSITION_LIMIT_ADDR, ENCODER_TICKS - 1)
            time.sleep(0.05)
            port_handler.clearPort()
            # Verify the writes took effect
            min_val, _, _ = packet_handler.read2ByteTxRx(port_handler, motor_id, MIN_POSITION_LIMIT_ADDR)
            max_val, _, _ = packet_handler.read2ByteTxRx(port_handler, motor_id, MAX_POSITION_LIMIT_ADDR)
            if min_val != 0 or max_val != ENCODER_TICKS - 1:
                raise RuntimeError(
                    f"Failed to reset EEPROM limits for motor {motor_id}: "
                    f"got [{min_val}, {max_val}], expected [0, {ENCODER_TICKS - 1}]"
                )
        print("✓ EEPROM limits verified [0, 4095]")
        print()

        print("=" * 70)
        print(f"YAW MOTOR (ID {args.yaw_id}) - Left/Right")
        print("=" * 70)
        input("Move yaw to LEFTMOST safe position, then press ENTER...")
        yaw_left_ticks = _read_position(port_handler, packet_handler, args.yaw_id)
        print(f"✓ Yaw left: {yaw_left_ticks} ticks")

        input("Move yaw to RIGHTMOST safe position, then press ENTER...")
        yaw_right_ticks = _read_position(port_handler, packet_handler, args.yaw_id)
        print(f"✓ Yaw right: {yaw_right_ticks} ticks")

        input("Move yaw to NEUTRAL position, then press ENTER...")
        yaw_neutral_ticks = _read_position(port_handler, packet_handler, args.yaw_id)
        print(f"✓ Yaw neutral: {yaw_neutral_ticks} ticks")
        print()

        print("=" * 70)
        print(f"PITCH MOTOR (ID {args.pitch_id}) - Up/Down")
        print("=" * 70)
        input("Move pitch to LOWEST (down) safe position, then press ENTER...")
        pitch_down_ticks = _read_position(port_handler, packet_handler, args.pitch_id)
        print(f"✓ Pitch down: {pitch_down_ticks} ticks")

        input("Move pitch to HIGHEST (up) safe position, then press ENTER...")
        pitch_up_ticks = _read_position(port_handler, packet_handler, args.pitch_id)
        print(f"✓ Pitch up: {pitch_up_ticks} ticks")

        input("Move pitch to NEUTRAL position, then press ENTER...")
        pitch_neutral_ticks = _read_position(port_handler, packet_handler, args.pitch_id)
        print(f"✓ Pitch neutral: {pitch_neutral_ticks} ticks")
        print()

        # Determine if motors increase in the expected direction
        # Standard conventions:
        # - Yaw: positive angle = LEFT, negative angle = RIGHT
        # - Pitch: positive angle = UP, negative angle = DOWN
        yaw_increases_right = yaw_right_ticks > yaw_left_ticks
        pitch_increases_up = pitch_up_ticks > pitch_down_ticks

        # Normalize tick values so that min_ticks < neutral_ticks < max_ticks.
        # If the motor's operating range crosses the 0/ENCODER_TICKS encoder boundary
        # (wrap-around), the wrap-side extreme is stored as a negative value
        # (extreme - ENCODER_TICKS).  The controller applies modulo before sending to
        # hardware so the physical motor position is always valid (0–4095).
        yaw_min_ticks, _, yaw_max_ticks = _normalize_axis_ticks(
            yaw_left_ticks, yaw_neutral_ticks, yaw_right_ticks
        )
        pitch_min_ticks, _, pitch_max_ticks = _normalize_axis_ticks(
            pitch_down_ticks, pitch_neutral_ticks, pitch_up_ticks
        )

        if yaw_min_ticks < 0:
            print(
                f"⚠  Yaw encoder wrap detected: neutral ({yaw_neutral_ticks}) is on the arc\n"
                f"   crossing the 0/{ENCODER_TICKS} boundary between "
                f"left ({yaw_left_ticks}) and right ({yaw_right_ticks}).\n"
                f"   Stored as logical min={yaw_min_ticks}; "
                f"controller converts to motor ticks via % {ENCODER_TICKS} at runtime."
            )
        if pitch_min_ticks < 0:
            print(
                f"⚠  Pitch encoder wrap detected: neutral ({pitch_neutral_ticks}) is on the arc\n"
                f"   crossing the 0/{ENCODER_TICKS} boundary between "
                f"down ({pitch_down_ticks}) and up ({pitch_up_ticks}).\n"
                f"   Stored as logical min={pitch_min_ticks}; "
                f"controller converts to motor ticks via % {ENCODER_TICKS} at runtime."
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
        }

        print("=" * 70)
        print("Calibration Result")
        print("=" * 70)
        print(json.dumps(calibration, indent=2))
        print()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
        print(f"✓ Saved calibration file: {output_path}")
        print("✓ Calibration complete")
        return 0

    except KeyboardInterrupt:
        print("\nCancelled by user.")
        return 1
    except Exception as exc:
        print(f"\n✗ Calibration failed: {exc}")
        return 1
    finally:
        try:
            _set_torque(port_handler, packet_handler, args.yaw_id, enabled=False)
        except Exception:
            pass
        try:
            _set_torque(port_handler, packet_handler, args.pitch_id, enabled=False)
        except Exception:
            pass
        port_handler.closePort()
        print("✓ Disconnected")


if __name__ == "__main__":
    sys.exit(main())
