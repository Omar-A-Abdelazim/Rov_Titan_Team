#include <Wire.h>
#include <Adafruit_BMP280.h>
#include <MS5837.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// =======================
// PIN MAPPING
// =======================
// ROV THRUSTERS
#define M1_R_PWM 13
#define M1_L_PWM 12
#define M2_R_PWM 11
#define M2_L_PWM 10
#define M3_R_PWM 44
#define M3_L_PWM 8
#define M4_R_PWM 3
#define M4_L_PWM 2
#define M5_R_PWM 7
#define M5_L_PWM 6
#define M6_R_PWM 5
#define M6_L_PWM 4

// ARM MOTORS
#define GRIP_R_PWM 47
#define GRIP_L_PWM 49
#define ROT_R_PWM 45
#define ROT_L_PWM 46

// LEAK SENSOR
#define RAIN_SENSOR_PIN A0

// =======================
// SENSOR OBJECTS
// =======================
Adafruit_BMP280 bmp;
MS5837 ms5837;
Adafruit_MPU6050 mpu;

bool bmp_ok = false;
bool ms5837_ok = false;
bool mpu_ok = false;

// =======================
// MOTOR CONTROL FUNCTION
// =======================
void setMotor(int speed, int r_pwm_pin, int l_pwm_pin) {
  int abs_speed = constrain(abs(speed), 0, 255);
  if (speed > 0) {
    analogWrite(r_pwm_pin, abs_speed);
    analogWrite(l_pwm_pin, 0);
  } else if (speed < 0) {
    analogWrite(r_pwm_pin, 0);
    analogWrite(l_pwm_pin, abs_speed);
  } else {
    analogWrite(r_pwm_pin, 0);
    analogWrite(l_pwm_pin, 0);
  }
}

void stopAllMotors() {
  setMotor(0, M1_R_PWM, M1_L_PWM);
  setMotor(0, M2_R_PWM, M2_L_PWM);
  setMotor(0, M3_R_PWM, M3_L_PWM);
  setMotor(0, M4_R_PWM, M4_L_PWM);
  setMotor(0, M5_R_PWM, M5_L_PWM);
  setMotor(0, M6_R_PWM, M6_L_PWM);
  setMotor(0, GRIP_R_PWM, GRIP_L_PWM);
  setMotor(0, ROT_R_PWM, ROT_L_PWM);
}

// =======================
// SAFETY CHECK
// =======================
bool checkLeak() {
  if (analogRead(RAIN_SENSOR_PIN) < 500) {
    stopAllMotors();
    Serial.println(F("EMERGENCY LEAK STOP"));
    return true;
  }
  return false;
}

// =======================
// TEST STEP HELPER
// =======================
void runTestStep(void (*motorFunc)(int), int speed, const char* msg) {
  if (checkLeak()) return;
  Serial.println(msg);
  motorFunc(speed);
  
  unsigned long start = millis();
  while (millis() - start < 2000) {
    if (checkLeak()) return;
    delay(10);
  }
  
  stopAllMotors();
  delay(1000);
}

// =======================
// MOTOR TEST WRAPPERS
// =======================
void allThrusters(int speed) {
  setMotor(speed, M1_R_PWM, M1_L_PWM);
  setMotor(speed, M2_R_PWM, M2_L_PWM);
  setMotor(speed, M3_R_PWM, M3_L_PWM);
  setMotor(speed, M4_R_PWM, M4_L_PWM);
  setMotor(speed, M5_R_PWM, M5_L_PWM);
  setMotor(speed, M6_R_PWM, M6_L_PWM);
}

void gripperTest(int speed) { setMotor(speed, GRIP_R_PWM, GRIP_L_PWM); }
void rotationTest(int speed) { setMotor(speed, ROT_R_PWM, ROT_L_PWM); }

// =======================
// SETUP
// =======================
void setup() {
  Serial.begin(9600);
  while (!Serial) delay(10);
  Serial.println(F("=== ROV SYSTEM TEST STARTING ==="));

  pinMode(RAIN_SENSOR_PIN, INPUT);
  int motorPins[] = {M1_R_PWM, M1_L_PWM, M2_R_PWM, M2_L_PWM, M3_R_PWM, M3_L_PWM, 
                     M4_R_PWM, M4_L_PWM, M5_R_PWM, M5_L_PWM, M6_R_PWM, M6_L_PWM,
                     GRIP_R_PWM, GRIP_L_PWM, ROT_R_PWM, ROT_L_PWM};
  for (int i = 0; i < 16; i++) pinMode(motorPins[i], OUTPUT);
  stopAllMotors();

  Wire.begin();
  if (!bmp.begin()) Serial.println(F("Sensor BMP280 FAILED")); else bmp_ok = true;
  if (!ms5837.init()) Serial.println(F("Sensor MS5837 FAILED")); else { ms5837.setModel(MS5837::MS5837_30BA); ms5837_ok = true; }
  if (!mpu.begin()) Serial.println(F("Sensor MPU6050 FAILED")); else mpu_ok = true;

  Serial.println(F("=== SENSOR TEST ==="));
  for (int i = 0; i < 4; i++) {
    if (checkLeak()) break;
    Serial.print(F("Temp: ")); Serial.print(bmp_ok ? bmp.readTemperature() : 0);
    Serial.print(F(" | Pres BMP: ")); Serial.print(bmp_ok ? bmp.readPressure() / 100.0 : 0);
    if (ms5837_ok) { ms5837.read(); Serial.print(F(" | Pres MS: ")); Serial.print(ms5837.pressure()); Serial.print(F(" | Depth: ")); Serial.print(ms5837.depth()); }
    if (mpu_ok) { sensors_event_t a, g, t; mpu.getEvent(&a, &g, &t); Serial.print(F(" | Roll: ")); Serial.print(a.acceleration.x); Serial.print(F(" | Pitch: ")); Serial.print(a.acceleration.y); }
    Serial.print(F(" | Leak: ")); Serial.println(analogRead(RAIN_SENSOR_PIN) < 500 ? "YES" : "NO");
    delay(500);
  }

  Serial.println(F("=== THRUSTER TEST ==="));
  runTestStep(allThrusters, 150, "All Thrusters Forward");
  runTestStep(allThrusters, -150, "All Thrusters Reverse");

  Serial.println(F("=== ARM TEST ==="));
  runTestStep(gripperTest, 150, "Gripper Open");
  runTestStep(gripperTest, -150, "Gripper Close");
  runTestStep(rotationTest, 150, "Rotation Clockwise");
  runTestStep(rotationTest, -150, "Rotation Counter-Clockwise");

  Serial.println(F("=== TEST COMPLETE ==="));
}

void loop() {
  checkLeak();
  delay(100);
}
