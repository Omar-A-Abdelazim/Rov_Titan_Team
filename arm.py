import pygame
import serial
import time

PORT = "COM13"
BAUDRATE = 9600

ser = serial.Serial(PORT, BAUDRATE, timeout=1)
time.sleep(2)

pygame.init()
pygame.joystick.init()
joy = pygame.joystick.Joystick(0)
joy.init()

print("ARM CONTROL READY")

grip_mode = 1
rot_mode = 1
r1_pressed = False
l1_pressed = False

try:
    while True:
        pygame.event.pump()

        # Buttons
        R1 = joy.get_button(10)
        L1 = joy.get_button(9)

        # Toggle Grip Mode
        if R1 and not r1_pressed:
            grip_mode *= -1
            r1_pressed = True
            print(f"R1 pressed! New grip_mode = {grip_mode}")
        if not R1:
            r1_pressed = False

        # Toggle Rotation Mode
        if L1 and not l1_pressed:
            rot_mode *= -1
            l1_pressed = True
            print(f"L1 pressed! New rot_mode = {rot_mode}")
        if not L1:
            l1_pressed = False

        # Triggers
        R2 = joy.get_axis(5)
        L2 = joy.get_axis(4)

        grip_speed = int(((R2 + 1)/2)*255) * grip_mode
        rot_speed  = int(((L2 + 1)/2)*255) * rot_mode

        if abs(R2) < 0.05:
            grip_speed = 0
        if abs(L2) < 0.05:
            rot_speed = 0

        data = f"{grip_speed},{rot_speed}\n"
        ser.write(data.encode())

        print(f"\rGrip Speed: {grip_speed}, Rot Speed: {rot_speed}", end="")

        time.sleep(0.05)

except KeyboardInterrupt:
    pass

finally:
    ser.write(b"0,0\n")
    ser.close()
    pygame.quit()