#!/usr/bin/env python3
"""Test neck movement to calibrated limits."""

import argparse
import json
import sys
import time
from pathlib import Path
import scservo_sdk as scs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test XLERobotNeck movements using saved calibration")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    parser.add_argument("--baudrate", type=int, default=1_000_000, help="Serial baudrate (default: 1000000)")
    parser.add_argument("--yaw-id", type=int, default=2, help="Yaw motor ID (default: 2)")
    parser.add_argument("--pitch-id", type=int, default=1, help="Pitch motor ID (default: 1)")
    parser.add_argument(
        "--calibration-file",
        default="/config/neck_calibration.json",
        help="Calibration JSON file path (default: /config/neck_calibration.json)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    print("=" * 70)
    print("XLERobotNeck Limit Test")
    print("=" * 70)
    print()

    # Load calibration
    calibration_file = Path(args.calibration_file).expanduser()
    if not calibration_file.exists():
        print("✗ No calibration found!")
        print("  Run: python3 calibrate.py")
        return 1

    with open(calibration_file) as f:
        cal = json.load(f)

    print(f"✓ Loaded calibration: {calibration_file}")
    print()
    print("Calibration values:")
    print(f"  Yaw:   min={cal['yaw_min_ticks']}, neutral={cal['yaw_neutral_ticks']}, max={cal['yaw_max_ticks']}")
    print(f"  Pitch: min={cal['pitch_min_ticks']}, neutral={cal['pitch_neutral_ticks']}, max={cal['pitch_max_ticks']}")
    print()

    print(f"Port: {args.port}")
    print(f"Baudrate: {args.baudrate}")
    print(f"Yaw motor ID: {args.yaw_id}")
    print(f"Pitch motor ID: {args.pitch_id}")
    print()

    # Open port
    port_handler = scs.PortHandler(args.port)
    packet_handler = scs.PacketHandler(scs.SCS_END)

    if not port_handler.openPort():
        print(f"✗ Failed to open {args.port}")
        return 1

    if not port_handler.setBaudRate(args.baudrate):
        print(f"✗ Failed to set baudrate")
        port_handler.closePort()
        return 1

    print(f"✓ Connected to {args.port}")
    print()

    try:
        OPERATING_MODE_ADDR = 33
        TORQUE_ENABLE_ADDR = 40
        GOAL_POSITION_ADDR = 42
        PRESENT_POSITION_ADDR = 56

        NUM_RETRY = 3

        # Mirrors the production motor_bus.py pattern: writeTxRx with
        # serialized byte data and retry, no clearPort hacks.
        def _serialize(value, length):
            return [scs.SCS_LOBYTE(scs.SCS_LOWORD(value)),
                    scs.SCS_HIBYTE(scs.SCS_LOWORD(value))][:length]

        def write_reg(motor_id, addr, length, value):
            data = _serialize(value, length)
            for attempt in range(1 + NUM_RETRY):
                comm, error = packet_handler.writeTxRx(port_handler, motor_id, addr, length, data)
                if comm == scs.COMM_SUCCESS:
                    return
            print(f"   ⚠ write failed motor {motor_id} addr {addr}: {packet_handler.getTxRxResult(comm)}")

        def read_position(motor_id):
            for attempt in range(1 + NUM_RETRY):
                try:
                    position, comm, error = packet_handler.read2ByteTxRx(
                        port_handler, motor_id, PRESENT_POSITION_ADDR
                    )
                    if comm == scs.COMM_SUCCESS:
                        return position
                except IndexError:
                    pass
            print(f"   ⚠ read failed motor {motor_id}: {packet_handler.getTxRxResult(comm)}")
            return None

        def write_position(motor_id, ticks):
            write_reg(motor_id, GOAL_POSITION_ADDR, 2, ticks)

        # Disable torque first (required to write EPROM registers)
        print("Disabling torque...")
        for motor_id in [args.yaw_id, args.pitch_id]:
            write_reg(motor_id, TORQUE_ENABLE_ADDR, 1, 0)
        print("✓ Torque disabled")
        print()

        # Set motors to position mode (Operating_Mode = 0)
        print("Setting motors to position mode...")
        for motor_id in [args.yaw_id, args.pitch_id]:
            write_reg(motor_id, OPERATING_MODE_ADDR, 1, 0)
        print("✓ Operating mode set to POSITION (0)")
        print()

        # Enable torque
        print("Enabling torque...")
        for motor_id in [args.yaw_id, args.pitch_id]:
            write_reg(motor_id, TORQUE_ENABLE_ADDR, 1, 1)
        print("✓ Torque enabled")
        print()

        print("=" * 70)
        print("Testing movements...")
        print("=" * 70)
        print()

        # Use directional calibration keys (yaw_left/right, pitch_down/up)
        # instead of min/max which lose directional meaning after normalization.

        # 1. Neutral
        print("1. Moving to NEUTRAL...")
        write_position(args.yaw_id, cal['yaw_neutral_ticks'])
        write_position(args.pitch_id, cal['pitch_neutral_ticks'])
        time.sleep(2)
        yaw_pos = read_position(args.yaw_id)
        pitch_pos = read_position(args.pitch_id)
        print(f"   Yaw: {yaw_pos}, Pitch: {pitch_pos}")
        print()

        # 2. Yaw left
        print("2. Moving YAW LEFT...")
        write_position(args.yaw_id, cal['yaw_left_ticks'])
        time.sleep(2)
        yaw_pos = read_position(args.yaw_id)
        print(f"   Yaw: {yaw_pos}")
        print()

        # 3. Yaw right
        print("3. Moving YAW RIGHT...")
        write_position(args.yaw_id, cal['yaw_right_ticks'])
        time.sleep(2)
        yaw_pos = read_position(args.yaw_id)
        print(f"   Yaw: {yaw_pos}")
        print()

        # 4. Yaw neutral
        print("4. Yaw back to NEUTRAL...")
        write_position(args.yaw_id, cal['yaw_neutral_ticks'])
        time.sleep(2)
        yaw_pos = read_position(args.yaw_id)
        print(f"   Yaw: {yaw_pos}")
        print()

        # 5. Pitch down
        print("5. Moving PITCH DOWN...")
        write_position(args.pitch_id, cal['pitch_down_ticks'])
        time.sleep(2)
        pitch_pos = read_position(args.pitch_id)
        print(f"   Pitch: {pitch_pos}")
        print()

        # 6. Pitch up
        print("6. Moving PITCH UP...")
        write_position(args.pitch_id, cal['pitch_up_ticks'])
        time.sleep(2)
        pitch_pos = read_position(args.pitch_id)
        print(f"   Pitch: {pitch_pos}")
        print()

        # 7. Pitch neutral
        print("7. Pitch back to NEUTRAL...")
        write_position(args.pitch_id, cal['pitch_neutral_ticks'])
        time.sleep(2)
        pitch_pos = read_position(args.pitch_id)
        print(f"   Pitch: {pitch_pos}")
        print()

        print("=" * 70)
        print("✓ Test complete!")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Disable torque
        print("\nDisabling torque...")
        TORQUE_ENABLE_ADDR = 40
        try:
            for motor_id in [args.yaw_id, args.pitch_id]:
                packet_handler.write1ByteTxRx(port_handler, motor_id, TORQUE_ENABLE_ADDR, 0)
        except:
            pass
        port_handler.closePort()
        print("✓ Disconnected")


if __name__ == "__main__":
    sys.exit(main())
