import pygame
import socket
import time
import sys

# =======================
# CONFIGURABLE SETTINGS
# =======================
RASPBERRY_PI_IP = '192.168.1.20' # IP address of the Raspberry Pi
PORT = 5000                     # Port for TCP connection
MAX_SPEED = 255                 # Maximum motor speed (0-255)
DEADZONE = 0.12                 # Joystick deadzone
RECONNECT_DELAY = 3             # Seconds to wait before attempting reconnect

# =======================
# GLOBAL VARIABLES
# =======================
sock = None
connected = False
grip_mode = 1  # 1 for normal, -1 for inverted
rot_mode = 1   # 1 for normal, -1 for inverted
R1_pressed = False
L1_pressed = False

# =======================
# SOCKET FUNCTIONS
# =======================
def connect_to_raspberry_pi():
    global sock, connected
    while not connected:
        try:
            print(f"Attempting to connect to Raspberry Pi at {RASPBERRY_PI_IP}:{PORT}...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect((RASPBERRY_PI_IP, PORT))
            connected = True
            print("Connected to Raspberry Pi.")
            return True
        except socket.error as e:
            print(f"Connection failed: {e}. Retrying in {RECONNECT_DELAY} seconds...")
            time.sleep(RECONNECT_DELAY)
    return False

def send_motor_data(data):
    global sock, connected
    if not connected:
        print("Not connected to Raspberry Pi. Attempting to reconnect...")
        connect_to_raspberry_pi()
        if not connected:
            return

    try:
        sock.sendall(data.encode('utf-8'))
    except socket.error as e:
        print(f"Send failed: {e}. Connection lost. Attempting to reconnect...")
        connected = False
        sock.close()
        connect_to_raspberry_pi()

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
    global grip_mode, rot_mode, R1_pressed, L1_pressed
    joy = init_joystick()
    connect_to_raspberry_pi()

    print("FULL ROV + ARM CONTROL READY")

    try:
        while True:
            pygame.event.pump()

            # Read joystick axes
            y_axis = -apply_deadzone(joy.get_axis(1), DEADZONE)  # Left stick Y-axis
            x_axis = apply_deadzone(joy.get_axis(0), DEADZONE)   # Left stick X-axis
            z_axis = -apply_deadzone(joy.get_axis(3), DEADZONE)  # Right stick Y-axis (for vertical thrusters)

            # Calculate motor speeds for ROV thrusters (simplified differential drive for now)
            # M1, M2, M3, M4 are horizontal thrusters
            # M5, M6 are vertical thrusters
            groupA = (y_axis + x_axis) * MAX_SPEED
            groupB = (y_axis - x_axis) * MAX_SPEED

            m1 = int(groupA) # Front Left
            m2 = int(-groupB) # Front Right
            m3 = int(-groupA) # Rear Left
            m4 = int(-groupB) # Rear Right
            m5 = int(z_axis * MAX_SPEED) # Vertical Left
            m6 = int(z_axis * MAX_SPEED) # Vertical Right

            # Read arm motor controls
            # R1 (button 10) and L1 (button 9) for mode switching (if needed, currently not used as per old code)
            # R2 (axis 5) for Gripper, L2 (axis 4) for Rotation
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

            # Format data string: m1,m2,m3,m4,m5,m6,grip,rot\n
            data_to_send = f"{motors[0]},{motors[1]},{motors[2]},{motors[3]},{motors[4]},{motors[5]},{motors[6]},{motors[7]}\n"
            send_motor_data(data_to_send)
            sys.stdout.write(f"\rSending: {data_to_send.strip()}")
            sys.stdout.flush()

            time.sleep(0.05) # Small delay to prevent overwhelming the network/serial

    except KeyboardInterrupt:
        print("\nEmergency stop (Ctrl+C) detected. Stopping motors...")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        # Send stop command to all motors before exiting
        stop_data = "0,0,0,0,0,0,0,0\n"
        print(f"Sending final stop command: {stop_data.strip()}")
        send_motor_data(stop_data)
        if sock:
            sock.close()
        pygame.quit()
        print("System shut down.")

if __name__ == "__main__":
    main()
