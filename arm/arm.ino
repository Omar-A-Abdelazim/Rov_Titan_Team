// =======================
// ARM PINS
// =======================

// Grip Motor
#define GRIP_R_EN 10
#define GRIP_R_PWM 11
#define GRIP_L_EN 12
#define GRIP_L_PWM 13

// Rotation Motor
#define ROT_R_EN 22
#define ROT_R_PWM 23
#define ROT_L_EN 24
#define ROT_L_PWM 25

// =======================
// MOTOR FUNCTION
// =======================

void setMotor(int speed, int r_en, int r_pwm, int l_en, int l_pwm) {

  int abs_speed = abs(speed);
  abs_speed = constrain(abs_speed, 0, 255);

  digitalWrite(r_en, HIGH);
  digitalWrite(l_en, HIGH);

  if (speed > 0) {
    analogWrite(r_pwm, abs_speed);
    analogWrite(l_pwm, 0);
  }
  else if (speed < 0) {
    analogWrite(r_pwm, 0);
    analogWrite(l_pwm, abs_speed);
  }
  else {
    analogWrite(r_pwm, 0);
    analogWrite(l_pwm, 0);
  }
}

// =======================
// SETUP
// =======================

void setup() {

  Serial.begin(9600);
  delay(2000);

  pinMode(GRIP_R_EN, OUTPUT);
  pinMode(GRIP_R_PWM, OUTPUT);
  pinMode(GRIP_L_EN, OUTPUT);
  pinMode(GRIP_L_PWM, OUTPUT);

  pinMode(ROT_R_EN, OUTPUT);
  pinMode(ROT_R_PWM, OUTPUT);
  pinMode(ROT_L_EN, OUTPUT);
  pinMode(ROT_L_PWM, OUTPUT);

  Serial.println("ARM READY");
}

// =======================
// LOOP
// =======================

void loop() {

  if (Serial.available()) {

    String data = Serial.readStringUntil('\n');
    data.trim();

    int comma = data.indexOf(',');

    if (comma > 0) {

      int grip = data.substring(0, comma).toInt();
      int rot  = data.substring(comma + 1).toInt();

      setMotor(grip, GRIP_R_EN, GRIP_R_PWM, GRIP_L_EN, GRIP_L_PWM);
      setMotor(rot, ROT_R_EN, ROT_R_PWM, ROT_L_EN, ROT_L_PWM);
    }
  }
}