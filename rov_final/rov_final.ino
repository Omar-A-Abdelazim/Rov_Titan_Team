// ==========================================
// FULL ROV CONTROL - 6 THRUSTERS
// 4 Horizontal + 2 Vertical
// ==========================================

// =======================
// HORIZONTAL MOTORS
// =======================

// M1 - يمين قدام
#define MOTOR1_R_EN 42
#define MOTOR1_R_PWM 2
#define MOTOR1_L_EN 43
#define MOTOR1_L_PWM 5

// M2 - شمال قدام
#define MOTOR2_R_EN 53
#define MOTOR2_R_PWM 8
#define MOTOR2_L_EN 52
#define MOTOR2_L_PWM 11

// M3 - شمال ورا
#define MOTOR3_R_EN 49
#define MOTOR3_R_PWM 44
#define MOTOR3_L_EN 48
#define MOTOR3_L_PWM 45

// M4 - يمين ورا
#define MOTOR4_R_EN 40
#define MOTOR4_R_PWM 46
#define MOTOR4_L_EN 41
#define MOTOR4_L_PWM 6

// =======================
// VERTICAL MOTORS
// =======================

// Left Vertical
#define LEFT_R_EN 3
#define LEFT_R_PWM 4
#define LEFT_L_EN 23
#define LEFT_L_PWM 7

// Right Vertical
#define RIGHT_R_EN 9
#define RIGHT_R_PWM 10
#define RIGHT_L_EN 12
#define RIGHT_L_PWM 13

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

  // Horizontal motors
  pinMode(MOTOR1_R_EN, OUTPUT);
  pinMode(MOTOR1_R_PWM, OUTPUT);
  pinMode(MOTOR1_L_EN, OUTPUT);
  pinMode(MOTOR1_L_PWM, OUTPUT);

  pinMode(MOTOR2_R_EN, OUTPUT);
  pinMode(MOTOR2_R_PWM, OUTPUT);
  pinMode(MOTOR2_L_EN, OUTPUT);
  pinMode(MOTOR2_L_PWM, OUTPUT);

  pinMode(MOTOR3_R_EN, OUTPUT);
  pinMode(MOTOR3_R_PWM, OUTPUT);
  pinMode(MOTOR3_L_EN, OUTPUT);
  pinMode(MOTOR3_L_PWM, OUTPUT);

  pinMode(MOTOR4_R_EN, OUTPUT);
  pinMode(MOTOR4_R_PWM, OUTPUT);
  pinMode(MOTOR4_L_EN, OUTPUT);
  pinMode(MOTOR4_L_PWM, OUTPUT);

  // Vertical motors
  pinMode(LEFT_R_EN, OUTPUT);
  pinMode(LEFT_R_PWM, OUTPUT);
  pinMode(LEFT_L_EN, OUTPUT);
  pinMode(LEFT_L_PWM, OUTPUT);

  pinMode(RIGHT_R_EN, OUTPUT);
  pinMode(RIGHT_R_PWM, OUTPUT);
  pinMode(RIGHT_L_EN, OUTPUT);
  pinMode(RIGHT_L_PWM, OUTPUT);

  Serial.println("FULL ROV READY");
}

// =======================
// LOOP
// =======================

void loop() {

  if (Serial.available()) {

    String data = Serial.readStringUntil('\n');
    data.trim();

    int first  = data.indexOf(',');
    int second = data.indexOf(',', first + 1);
    int third  = data.indexOf(',', second + 1);
    int fourth = data.indexOf(',', third + 1);
    int fifth  = data.indexOf(',', fourth + 1);

    if (first > 0 && second > 0 && third > 0 && fourth > 0 && fifth > 0) {

      int m1 = data.substring(0, first).toInt();
      int m2 = data.substring(first + 1, second).toInt();
      int m3 = data.substring(second + 1, third).toInt();
      int m4 = data.substring(third + 1, fourth).toInt();
      int m5 = data.substring(fourth + 1, fifth).toInt();
      int m6 = data.substring(fifth + 1).toInt();

      // Horizontal
      setMotor(m1, MOTOR1_R_EN, MOTOR1_R_PWM, MOTOR1_L_EN, MOTOR1_L_PWM);
      setMotor(m2, MOTOR2_R_EN, MOTOR2_R_PWM, MOTOR2_L_EN, MOTOR2_L_PWM);
      setMotor(m3, MOTOR3_R_EN, MOTOR3_R_PWM, MOTOR3_L_EN, MOTOR3_L_PWM);
      setMotor(m4, MOTOR4_R_EN, MOTOR4_R_PWM, MOTOR4_L_EN, MOTOR4_L_PWM);

      // Vertical
      setMotor(m5, LEFT_R_EN, LEFT_R_PWM, LEFT_L_EN, LEFT_L_PWM);
      setMotor(m6, RIGHT_R_EN, RIGHT_R_PWM, RIGHT_L_EN, RIGHT_L_PWM);
    }
  }
}