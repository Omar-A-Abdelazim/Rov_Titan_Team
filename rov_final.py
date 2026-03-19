import pygame
import serial
import time

# =============================
# CONFIG
# =============================
PORT = "COM13"
BAUDRATE = 9600
MAX_SPEED = 255
DEADZONE = 0.12

# =============================
# SERIAL
# =============================
ser = serial.Serial(PORT, BAUDRATE, timeout=1)
time.sleep(2)

# =============================
# JOYSTICK
# =============================
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("No joystick detected!")
    exit()

joy = pygame.joystick.Joystick(0)
joy.init()

print("FULL ROV CONTROL READY")

# =============================
# MAIN LOOP
# =============================
try:
    while True:

        pygame.event.pump()

        # Horizontal movement
        y = -joy.get_axis(1)   # Forward / Back
        x = joy.get_axis(0)    # Turning

        # Vertical movement
        z = -joy.get_axis(3)   # Up / Down

        # Deadzone
        if abs(y) < DEADZONE: y = 0
        if abs(x) < DEADZONE: x = 0
        if abs(z) < DEADZONE: z = 0

        # Horizontal mixing
        groupA = (y + x) * MAX_SPEED
        groupB = (y - x) * MAX_SPEED

        m1 = int(groupA)
        m2 = int(-groupB)
        m3 = int(-groupA)
        m4 = int(-groupB)

        # Vertical motors
        m5 = int((z) * MAX_SPEED)
        m6 = int((z) * MAX_SPEED)

        # Clamp values
        motors = [m1, m2, m3, m4, m5, m6]
        motors = [max(-255, min(255, m)) for m in motors]

        # Send data
        data = f"{motors[0]},{motors[1]},{motors[2]},{motors[3]},{motors[4]},{motors[5]}\n"
        ser.write(data.encode())

        print(f"\r{data}", end="")

        time.sleep(0.05)

except KeyboardInterrupt:
    pass

finally:
    ser.write(b"0,0,0,0,0,0\n")
    ser.close()
    pygame.quit()