
// ==========================================
// Arduino Mega ROV + ARM Control Code
// ==========================================

// =======================
// ROV MOTORS PIN MAPPING
// M1 -> Front Left Thruster
// M2 -> Front Right Thruster
// M3 -> Rear Left Thruster
// M4 -> Rear Right Thruster
// M5 -> Vertical Left
// M6 -> Vertical Right
// =======================
#define M1_R_PWM 13
#define M1_L_PWM 12
#define M2_R_PWM 11
#define M2_L_PWM 10
#define M3_R_PWM 44
#define M3_L_PWM 8
#define M4_R_PWM 3
#define M4_L_PWM 2
#define M5_R_PWM 7  // Assuming LEFT_R_PWM from old code maps to M5
#define M5_L_PWM 6  // Assuming LEFT_L_PWM from old code maps to M5
#define M6_R_PWM 5  // Assuming RIGHT_R_PWM from old code maps to M6
#define M6_L_PWM 4  // Assuming RIGHT_L_PWM from old code maps to M6

// =======================
// ARM MOTORS PIN MAPPING
// GRIP -> Gripper open/close
// ROT -> Wrist rotation
// =======================
#define GRIP_R_PWM 47
#define GRIP_L_PWM 49
#define GRIP_R_IS A15
#define GRIP_L_IS A14
#define ROT_R_PWM 45
#define ROT_L_PWM 46

// =======================
// SETTINGS
// =======================
#define CURRENT_LIMIT 600 // Analog read value for overcurrent threshold
#define CURRENT_CHECK_DELAY 20 // Milliseconds between current checks
unsigned long lastCheck = 0;

// =======================
// MOTOR CONTROL FUNCTION
// =======================
void setMotor(int speed, int r_pwm_pin, int l_pwm_pin) {
  int abs_speed = abs(speed);
  abs_speed = constrain(abs_speed, 0, 255); // PWM range 0-255

  if (speed > 0) { // Forward
    analogWrite(r_pwm_pin, abs_speed);
    analogWrite(l_pwm_pin, 0);
  } else if (speed < 0) { // Reverse
    analogWrite(r_pwm_pin, 0);
    analogWrite(l_pwm_pin, abs_speed);
  } else { // Stop
    analogWrite(r_pwm_pin, 0);
    analogWrite(l_pwm_pin, 0);
  }
}

// =======================
// CURRENT PROTECTION FOR GRIPPER
// =======================
bool checkGripOverCurrent(int speed) {
  if (millis() - lastCheck < CURRENT_CHECK_DELAY)
    return false;
  lastCheck = millis();

  int currentValue = 0;
  if (speed > 0) { // Gripper opening
    currentValue = analogRead(GRIP_R_IS);
  } else if (speed < 0) { // Gripper closing
    currentValue = analogRead(GRIP_L_IS);
  } else { // Gripper stopped
    return false;
  }

  if (currentValue > CURRENT_LIMIT) {
    // Stop gripper motor
    analogWrite(GRIP_R_PWM, 0);
    analogWrite(GRIP_L_PWM, 0);
    Serial.println("GRIP OVERCURRENT - STOPPED");
    return true;
  }
  return false;
}

// =======================
// SETUP
// =======================
void setup() {
  Serial.begin(9600);
  delay(2000); // Wait for serial to initialize

  // Initialize motor pins as OUTPUT
  pinMode(M1_R_PWM, OUTPUT);
  pinMode(M1_L_PWM, OUTPUT);
  pinMode(M2_R_PWM, OUTPUT);
  pinMode(M2_L_PWM, OUTPUT);
  pinMode(M3_R_PWM, OUTPUT);
  pinMode(M3_L_PWM, OUTPUT);
  pinMode(M4_R_PWM, OUTPUT);
  pinMode(M4_L_PWM, OUTPUT);
  pinMode(M5_R_PWM, OUTPUT);
  pinMode(M5_L_PWM, OUTPUT);
  pinMode(M6_R_PWM, OUTPUT);
  pinMode(M6_L_PWM, OUTPUT);
  
  pinMode(GRIP_R_PWM, OUTPUT);
  pinMode(GRIP_L_PWM, OUTPUT);
  pinMode(ROT_R_PWM, OUTPUT);
  pinMode(ROT_L_PWM, OUTPUT);

  // Initialize current sensor pins as INPUT
  pinMode(GRIP_R_IS, INPUT);
  pinMode(GRIP_L_IS, INPUT);

  Serial.println("Arduino Mega ROV + ARM READY");
}

// =======================
// LOOP
// =======================
void loop() {
  if (Serial.available()) {
    String data = Serial.readStringUntil('\n');
    data.trim();

    // Expected format: m1,m2,m3,m4,m5,m6,grip,rot\n
    int values[8];
    int lastIndex = 0;
    int commaIndex;

    for (int i = 0; i < 8; i++) {
      commaIndex = data.indexOf(',', lastIndex);
      if (commaIndex == -1 && i < 7) { // Not enough values
        Serial.println("Error: Malformed data packet");
        return;
      }
      if (i == 7) { // Last value
        values[i] = data.substring(lastIndex).toInt();
      } else {
        values[i] = data.substring(lastIndex, commaIndex).toInt();
        lastIndex = commaIndex + 1;
      }
    }

    int m1 = values[0];
    int m2 = values[1];
    int m3 = values[2];
    int m4 = values[3];
    int m5 = values[4];
    int m6 = values[5];
    int grip = values[6];
    int rot = values[7];

    // Control ROV thrusters
    setMotor(m1, M1_R_PWM, M1_L_PWM);
    setMotor(m2, M2_R_PWM, M2_L_PWM);
    setMotor(m3, M3_R_PWM, M3_L_PWM);
    setMotor(m4, M4_R_PWM, M4_L_PWM);
    setMotor(m5, M5_R_PWM, M5_L_PWM);
    setMotor(m6, M6_R_PWM, M6_L_PWM);

    // Control robotic arm motors with overcurrent protection for gripper
    bool overload = checkGripOverCurrent(grip);
    if (!overload) {
      setMotor(grip, GRIP_R_PWM, GRIP_L_PWM);
    }
    setMotor(rot, ROT_R_PWM, ROT_L_PWM);
  }
}
