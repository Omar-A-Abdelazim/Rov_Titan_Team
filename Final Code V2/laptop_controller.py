import pygame
import socket
import time
import sys
import threading
import binascii

# =======================
# CONFIGURABLE SETTINGS
# =======================
RASPBERRY_PI_IP = '192.168.1.20' # IP address of the Raspberry Pi
PORT = 5000                     # Port for TCP connection
MAX_SPEED = 255                 # Maximum motor speed (0-255)
DEADZONE = 0.12                 # Joystick deadzone
RECONNECT_DELAY = 3             # Seconds to wait before attempting reconnect

# =======================
# COMMUNICATION PROTOCOL DEFINITIONS
# =======================
START_DELIMITER = b'<'
END_DELIMITER = b'>'
PACKET_TYPE_MOTOR = b'M'
PACKET_TYPE_SENSOR = b'S'

# =======================
# GLOBAL VARIABLES
# =======================
sock = None
connected = False
grip_mode = 1  # 1 for normal, -1 for inverted
rot_mode = 1   # 1 for normal, -1 for inverted
R1_pressed = False
L1_pressed = False
SELECT_pressed = False # For stabilization mode toggle

stab_mode = 0 # 0 = OFF, 1 = ON
leak_override = 0 # 0 = Normal, 1 = Emergency Stop (sent to Arduino)

# Sensor data variables (received from Arduino)
temp_bmp = 0.0
pres_bmp = 0.0
pres_ms = 0.0
depth_ms = 0.0
roll_mpu = 0.0
pitch_mpu = 0.0
leak_status = 0 # 0 = No Leak, 1 = Leak Detected (from Arduino)

# Threading events and locks
shutdown_event = threading.Event()
socket_lock = threading.Lock()

def calculate_checksum(data_bytes):
    checksum = 0
    for byte_val in data_bytes:
        checksum ^= byte_val
    return checksum

def create_motor_packet(m_values, stab, leak_ovr):
    data_payload = f"{m_values[0]},{m_values[1]},{m_values[2]},{m_values[3]},{m_values[4]},{m_values[5]},{m_values[6]},{m_values[7]},{stab},{leak_ovr}"
    data_to_checksum = PACKET_TYPE_MOTOR + b'|' + data_payload.encode('utf-8')
    checksum = calculate_checksum(data_to_checksum)
    packet = START_DELIMITER + PACKET_TYPE_MOTOR + b'|' + data_payload.encode('utf-8') + b'|' + hex(checksum)[2:].encode('utf-8') + END_DELIMITER
    return packet

def parse_sensor_packet(raw_packet):
    """Parses a raw sensor packet and validates checksum.
    Returns (temp, pres_bmp, pres_ms, depth, roll, pitch, leak_status) or None if invalid.
    """
    try:
        if not raw_packet.startswith(START_DELIMITER) or not raw_packet.endswith(END_DELIMITER):
            print(f"Malformed packet: Missing delimiters. Packet: {raw_packet}")
            return None

        content = raw_packet[len(START_DELIMITER):-len(END_DELIMITER)]
        parts = content.split(b'|')
        if len(parts) != 3 or parts[0] != PACKET_TYPE_SENSOR:
            print(f"Malformed packet structure or not a sensor packet. Packet: {raw_packet}")
            return None # Malformed packet structure or not a sensor packet

        data_section = parts[1].decode('utf-8')
        received_checksum_hex = parts[2].decode('utf-8')

        data_to_checksum = PACKET_TYPE_SENSOR + b'|' + data_section.encode('utf-8')
        calculated_checksum = calculate_checksum(data_to_checksum)
        
        received_checksum = int(received_checksum_hex, 16)

        if calculated_checksum == received_checksum:
            sensor_values = [float(x) if i < 6 else int(x) for i, x in enumerate(data_section.split(','))]
            if len(sensor_values) == 7:
                return sensor_values
            else:
                print(f"Sensor data length mismatch. Expected 7, got {len(sensor_values)}. Data: {data_section}")
        else:
            print(f"Sensor Checksum mismatch! Received: {received_checksum_hex}, Calculated: {calculated_checksum:X}. Packet: {raw_packet}")
    except Exception as e:
        print(f"Error parsing sensor packet: {e}. Packet: {raw_packet}")
    return None

# =======================
# SOCKET FUNCTIONS
# =======================
def connect_to_raspberry_pi():
    global sock, connected
    # Only one thread should attempt to connect at a time
    with socket_lock:
        if connected: # Already connected by another thread
            return True
        if sock: # Close existing socket if any
            sock.close()
        sock = None
        connected = False

        while not shutdown_event.is_set() and not connected:
            try:
                print(f"Attempting to connect to Raspberry Pi at {RASPBERRY_PI_IP}:{PORT}...")
                new_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                new_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                new_sock.settimeout(1.0) # Set a timeout for initial connection
                new_sock.connect((RASPBERRY_PI_IP, PORT))
                new_sock.settimeout(0.1) # Set a non-blocking timeout for recv in telemetry thread
                sock = new_sock
                connected = True
                print("Connected to Raspberry Pi.")
                return True
            except socket.error as e:
                print(f"Connection failed: {e}. Retrying in {RECONNECT_DELAY} seconds...")
                time.sleep(RECONNECT_DELAY)
        return False

def send_motor_data(packet):
    global sock, connected
    # Ensure connection before sending
    if not connected:
        print("Not connected to Raspberry Pi. Attempting to reconnect...")
        if not connect_to_raspberry_pi(): # Attempt to reconnect
            print("Failed to re-establish connection, cannot send data.")
            return

    with socket_lock:
        if not connected or not sock: # Re-check after acquiring lock
            print("Socket not available for sending after reconnection attempt.")
            return
        try:
            sock.sendall(packet + b'\n') # Add newline for Raspberry Pi's read_until
        except socket.error as e:
            print(f"Send failed: {e}. Connection lost. Attempting to reconnect...")
            connected = False
            if sock:
                sock.close()
                sock = None
            # Reconnection will be handled by the next call or telemetry thread

def telemetry_receiver():
    global sock, connected, temp_bmp, pres_bmp, pres_ms, depth_ms, roll_mpu, pitch_mpu, leak_status, leak_override
    buffer = b''
    while not shutdown_event.is_set():
        if not connected or not sock:
            time.sleep(0.1)
            continue

        try:
            data = sock.recv(1024)
            if not data:
                print("Telemetry: Raspberry Pi disconnected.")
                connected = False
                with socket_lock:
                    if sock:
                        sock.close()
                        sock = None
                continue
            
            buffer += data

            while True:
                start_idx = buffer.find(START_DELIMITER)
                end_idx = buffer.find(END_DELIMITER, start_idx if start_idx != -1 else 0)

                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    raw_packet = buffer[start_idx : end_idx + len(END_DELIMITER)]
                    sensor_values = parse_sensor_packet(raw_packet)

                    if sensor_values:
                        temp_bmp, pres_bmp, pres_ms, depth_ms, roll_mpu, pitch_mpu, leak_status = sensor_values
                        if leak_status == 1:
                            leak_override = 1 # Laptop also registers leak for display/safety
                        # IMPORTANT: leak_override should only be set to 0 if leak_status is 0
                        # and no other emergency stop condition is active from the laptop side.
                        # For simplicity, we mirror Arduino's leak_status here.
                        else:
                            leak_override = 0
                    
                    buffer = buffer[end_idx + len(END_DELIMITER):]
                else:
                    break

            if len(buffer) > 2048: # Prevent buffer overflow
                print("Telemetry buffer overflow, clearing...")
                buffer = b'' # Clear buffer to prevent memory issues, acknowledge potential data loss

        except socket.timeout:
            pass # No data received, continue loop
        except socket.error as e:
            print(f"Telemetry receive error: {e}. Reconnecting...")
            connected = False
            with socket_lock:
                if sock:
                    sock.close()
                    sock = None
            connect_to_raspberry_pi() # Attempt to reconnect from telemetry thread
        except Exception as e:
            print(f"An unexpected error in telemetry receiver: {e}")
            time.sleep(0.1)

# =======================
# JOYSTICK FUNCTIONS
# =======================
def init_joystick():
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No joystick detected!")
        sys.exit()
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"Joystick detected: {joy.get_name()}")
    return joy

def apply_deadzone(value, deadzone):
    if abs(value) < deadzone:
        return 0.0
    return value

def clamp(value, min_val, max_val):
    return max(min_val, min(value, max_val))

# =======================
# MAIN LOOP
# =======================
def main():
    global grip_mode, rot_mode, R1_pressed, L1_pressed, SELECT_pressed, stab_mode, leak_override
    joy = init_joystick()
    connect_to_raspberry_pi()

    # Start telemetry receiver thread
    telemetry_thread = threading.Thread(target=telemetry_receiver)
    telemetry_thread.daemon = True
    telemetry_thread.start()

    print("FULL ROV + ARM CONTROL READY")

    try:
        while not shutdown_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.JOYBUTTONDOWN:
                    # Assuming 'SELECT' button is button 8 on a PS4 controller
                    if event.button == 8 and not SELECT_pressed: 
                        stab_mode = 1 - stab_mode # Toggle stabilization mode
                        print(f"Stabilization Mode: {'ON' if stab_mode == 1 else 'OFF'}")
                        SELECT_pressed = True
                elif event.type == pygame.JOYBUTTONUP:
                    if event.button == 8:
                        SELECT_pressed = False

            # Read joystick axes
            y_axis = -apply_deadzone(joy.get_axis(1), DEADZONE)  # Left stick Y-axis
            x_axis = apply_deadzone(joy.get_axis(0), DEADZONE)   # Left stick X-axis
            z_axis = -apply_deadzone(joy.get_axis(3), DEADZONE)  # Right stick Y-axis (for vertical thrusters)

            # Calculate motor speeds for ROV thrusters (simplified differential drive for now)
            groupA = (y_axis + x_axis) * MAX_SPEED
            groupB = (y_axis - x_axis) * MAX_SPEED

            m1 = int(groupA) # Front Left
            m2 = int(-groupB) # Front Right
            m3 = int(-groupA) # Rear Left
            m4 = int(-groupB) # Rear Right
            m5 = int(z_axis * MAX_SPEED) # Vertical Left
            m6 = int(z_axis * MAX_SPEED) # Vertical Right

            # Read arm motor controls
            current_R1 = joy.get_button(10)
            current_L1 = joy.get_button(9)

            if current_R1 and not R1_pressed:
                grip_mode *= -1
                R1_pressed = True
            elif not current_R1:
                R1_pressed = False

            if current_L1 and not L1_pressed:
                rot_mode *= -1
                L1_pressed = True
            elif not current_L1:
                L1_pressed = False

            R2_axis = joy.get_axis(5) # Right trigger
            L2_axis = joy.get_axis(4) # Left trigger

            grip_val = 0
            if abs(R2_axis) > 0.05: # Apply deadzone for triggers
                grip_val = int(((R2_axis + 1) / 2) * MAX_SPEED) * grip_mode
            
            rot_val = 0
            if abs(L2_axis) > 0.05: # Apply deadzone for triggers
                rot_val = int(((L2_axis + 1) / 2) * MAX_SPEED) * rot_mode

            # Clamp all motor values to -255 to 255
            motors = [
                clamp(m1, -MAX_SPEED, MAX_SPEED),
                clamp(m2, -MAX_SPEED, MAX_SPEED),
                clamp(m3, -MAX_SPEED, MAX_SPEED),
                clamp(m4, -MAX_SPEED, MAX_SPEED),
                clamp(m5, -MAX_SPEED, MAX_SPEED),
                clamp(m6, -MAX_SPEED, MAX_SPEED),
                clamp(grip_val, -MAX_SPEED, MAX_SPEED),
                clamp(rot_val, -MAX_SPEED, MAX_SPEED)
            ]

            # Apply emergency stop if leak detected by Arduino (reflected in leak_override)
            if leak_override == 1:
                motors = [0, 0, 0, 0, 0, 0, 0, 0]

            # Create and send motor command packet
            motor_packet = create_motor_packet(motors, stab_mode, leak_override)
            send_motor_data(motor_packet)
            
            # Display sensor data and motor commands
            sys.stdout.write(f"\rSending: {motor_packet.decode('utf-8').strip()} | "
                             f"BMP Temp: {temp_bmp:.2f}C, Pres: {pres_bmp:.2f}hPa | "
                             f"MS5837 Pres: {pres_ms:.2f}mbar, Depth: {depth_ms:.2f}m | "
                             f"MPU Roll: {roll_mpu:.2f}, Pitch: {pitch_mpu:.2f} | "
                             f"Leak: {'YES' if leak_status == 1 else 'NO'} | "
                             f"Stab: {'ON' if stab_mode == 1 else 'OFF'}")
            sys.stdout.flush()

            time.sleep(0.05) # Small delay to prevent overwhelming the network/serial

    except KeyboardInterrupt:
        print("\nEmergency stop (Ctrl+C) detected. Stopping motors...")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        shutdown_event.set() # Signal telemetry thread to stop
        # Send final stop command
        stop_motors = [0, 0, 0, 0, 0, 0, 0, 0]
        stop_packet = create_motor_packet(stop_motors, 0, 1) # Send leak_override=1 to ensure stop
        print(f"Sending final stop command: {stop_packet.decode('utf-8').strip()}")
        send_motor_data(stop_packet)
        if sock:
            with socket_lock:
                sock.close()
        pygame.quit()
        print("System shut down.")

if __name__ == "__main__":
    main()
