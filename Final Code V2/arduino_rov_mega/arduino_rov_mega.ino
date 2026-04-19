// ==========================================
// Arduino Mega ROV + ARM Control Code with Sensors (Robust Version)
// ==========================================

#include <Wire.h> // Required for I2C communication
#include <Adafruit_BMP280.h> // For BMP280
#include <MS5837.h> // For MS5837
#include <Adafruit_MPU6050.h> // For MPU6050
#include <Adafruit_Sensor.h> // Required for Adafruit sensors
#include <MadgwickAHRS.h> // For MPU6050 filtering (or similar AHRS library)

// =======================
// ROV MOTORS PIN MAPPING
// =======================
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

// =======================
// ARM MOTORS PIN MAPPING
// =======================
#define GRIP_R_PWM 47
#define GRIP_L_PWM 49
#define GRIP_R_IS A15
#define GRIP_L_IS A14
#define ROT_R_PWM 45
#define ROT_L_PWM 46

// =======================
// SENSOR PIN MAPPING
// =======================
#define RAIN_SENSOR_PIN A0 // Analog pin for Rain Sensor

// =======================
// SETTINGS
// =======================
#define CURRENT_LIMIT 600 // Analog read value for overcurrent threshold
#define CURRENT_CHECK_DELAY 20 // Milliseconds between current checks
unsigned long lastCheck = 0;

#define RAIN_SENSOR_THRESHOLD 500 // Adjustable threshold for leak detection

// Communication Watchdog
unsigned long last_command_time = 0;
const unsigned long COMMAND_TIMEOUT_MS = 1000; // 1 second timeout

// Rain Sensor Debounce
const int LEAK_DEBOUNCE_COUNT = 5; // Number of consecutive readings to confirm leak
int leak_confirm_count = 0;

// Depth Moving Average Filter
const int DEPTH_FILTER_SIZE = 10; // Number of samples for moving average
float depth_samples[DEPTH_FILTER_SIZE];
int depth_sample_index = 0;

// =======================
// GLOBAL SENSOR OBJECTS
// =======================
Adafruit_BMP280 bmp; // I2C
MS5837 ms5837; // I2C
Adafruit_MPU6050 mpu; // I2C
Madgwick filter; // For MPU6050 AHRS

// =======================
// GLOBAL SENSOR DATA & CONTROL FLAGS
// =======================
float temp_bmp = 0.0;
float pres_bmp = 0.0;
float pres_ms = 0.0;
float depth_ms = 0.0;
float roll_mpu = 0.0;
float pitch_mpu = 0.0;
float yaw_mpu = 0.0; // Added yaw_mpu
int leak_status = 0; // 0 = No Leak, 1 = Leak Detected
int stab_mode = 0; // 0 = OFF, 1 = ON
bool system_emergency_stop = false; // Flag for system-wide emergency stop

// Sensor status flags
bool bmp_ok = false;
bool ms5837_ok = false;
bool mpu_ok = false;

// =======================
// COMMUNICATION PROTOCOL DEFINITIONS
// =======================
#define START_DELIMITER 
#define END_DELIMITER 
#define PACKET_TYPE_MOTOR 'M'
#define PACKET_TYPE_SENSOR 'S'

// Serial buffer for incoming data
// Increased buffer size to accommodate potential longer packets and ensure safety
const int SERIAL_BUFFER_SIZE = 256; 
char serial_rx_buffer[SERIAL_BUFFER_SIZE];
int serial_rx_idx = 0;

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
// CHECKSUM CALCULATION
// =======================
// Modified to calculate checksum over packet_type and data_str only
byte calculateChecksum(char packet_type, const char* data_str) {
  byte checksum = 0;
  checksum ^= packet_type; // Include packet type in checksum
  checksum ^= '|'; // Include delimiter in checksum
  for (int i = 0; i < strlen(data_str); i++) {
    checksum ^= data_str[i];
  }
  return checksum;
}

// =======================
// SENSOR READING FUNCTIONS
// =======================
void readBMP280() {
  if (bmp_ok) {
    temp_bmp = bmp.readTemperature();
    pres_bmp = bmp.readPressure() / 100.0F; // Convert Pa to hPa
  }
}

void readMS5837() {
  if (ms5837_ok) {
    ms5837.read();
    pres_ms = ms5837.pressure();
    float current_depth = ms5837.depth();

    // Moving average filter for depth
    depth_samples[depth_sample_index] = current_depth;
    depth_sample_index = (depth_sample_index + 1) % DEPTH_FILTER_SIZE;

    float sum_depth = 0;
    for (int i = 0; i < DEPTH_FILTER_SIZE; i++) {
      sum_depth += depth_samples[i];
    }
    depth_ms = sum_depth / DEPTH_FILTER_SIZE;
  }
}

void readMPU6050() {
  if (mpu_ok) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    // Update Madgwick filter with gyroscope and accelerometer data
    // Gyroscope values are in rad/s, accelerometer in m/s^2
    filter.updateIMU(g.gyro.x, g.gyro.y, g.gyro.z, a.acceleration.x, a.acceleration.y, a.acceleration.z);

    // Get Euler angles from the filter
    roll_mpu = filter.getRoll();
    pitch_mpu = filter.getPitch();
    yaw_mpu = filter.getYaw(); 
  }
}

void checkRainSensor() {
  // Assuming the rain sensor outputs HIGH when dry, LOW when wet (leak detected)
  int rainSensorValue = analogRead(RAIN_SENSOR_PIN);
  if (rainSensorValue < RAIN_SENSOR_THRESHOLD) { // Use configurable threshold
    leak_confirm_count++;
    if (leak_confirm_count >= LEAK_DEBOUNCE_COUNT) {
      if (leak_status == 0) { // Only trigger if it was previously not leaking
        leak_status = 1; // Leak Detected
        Serial.println("LEAK DETECTED! Initiating emergency stop.");
        system_emergency_stop = true;
      }
    }
  } else {
    leak_confirm_count = 0; // Reset counter if dry
    leak_status = 0; // No Leak
  }
}

// =======================
// SETUP
// =======================
void setup() {
  Serial.begin(9600);
  while (!Serial) { 
    delay(10);
  }
  Serial.println("Arduino Mega ROV + ARM with Sensors Initializing...");

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

  // Initialize Rain Sensor pin
  pinMode(RAIN_SENSOR_PIN, INPUT); // Assuming analog input for now

  // Initialize I2C sensors
  Wire.begin();

  // BMP280
  if (!bmp.begin()) {
    Serial.println(F("Could not find a valid BMP280 sensor, check wiring!"));
    bmp_ok = false;
  } else {
    Serial.println("BMP280 found.");
    bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,     // Operating Mode
                     Adafruit_BMP280::SAMPLING_X2,     // Temp. oversampling
                     Adafruit_BMP280::SAMPLING_X16,    // Pressure oversampling
                     Adafruit_BMP280::FILTER_X16,      // Filtering
                     Adafruit_BMP280::STANDBY_MS_500); // Standby time
    bmp_ok = true;
  }

  // MS5837
  if (!ms5837.init()) {
    Serial.println("MS5837 sensor not found.");
    ms5837_ok = false;
  } else {
    ms5837.setModel(MS5837::MS5837_30BA); // Or MS5837_02BA depending on your sensor
    ms5837.setFluidDensity(1000); // kg/m^3 (freshwater)
    Serial.println("MS5837 found.");
    ms5837_ok = true;
  }

  // MPU6050
  if (!mpu.begin()) {
    Serial.println("Failed to find MPU6050 chip");
    mpu_ok = false;
  } else {
    Serial.println("MPU6050 found!");
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    mpu_ok = true;
    filter.begin(50); // Initialize Madgwick filter with update rate (Hz)
  }

  // Initialize depth filter samples
  for (int i = 0; i < DEPTH_FILTER_SIZE; i++) {
    depth_samples[i] = 0.0;
  }

  Serial.println("Arduino Mega ROV + ARM with Sensors READY");
  last_command_time = millis(); // Initialize watchdog timer
}

// =======================
// LOOP
// =======================
void loop() {
  // Check for leak first (HIGH PRIORITY)
  checkRainSensor();

  // Read sensor data periodically
  static unsigned long lastSensorReadTime = 0;
  if (millis() - lastSensorReadTime > 50) { // Read sensors every 50ms (20Hz)
    readBMP280();
    readMS5837();
    readMPU6050();
    lastSensorReadTime = millis();
  }

  // Communication Watchdog
  if (millis() - last_command_time > COMMAND_TIMEOUT_MS) {
    if (!system_emergency_stop) {
      Serial.println("COMMUNICATION TIMEOUT! Initiating emergency stop.");
      system_emergency_stop = true;
    }
  }

  // Handle incoming serial data with robust parsing
  while (Serial.available()) {
    char inChar = Serial.read();
    if (inChar == START_DELIMITER) {
      serial_rx_idx = 0;
      // Ensure buffer doesn't overflow if START_DELIMITER is received repeatedly without END_DELIMITER
      if (serial_rx_idx < SERIAL_BUFFER_SIZE) {
        serial_rx_buffer[serial_rx_idx++] = inChar; // Store START_DELIMITER for checksum calculation
      }
    } else if (inChar == END_DELIMITER) {
      if (serial_rx_idx > 0 && serial_rx_buffer[0] == START_DELIMITER) { // Ensure a START_DELIMITER was received
        serial_rx_buffer[serial_rx_idx] = '\0'; // Null-terminate the string
        
        // Packet format: <TYPE|DATA|CHECKSUM>
        // Example: <M|100,0,0,0,0,0,0,0,0,0|AB>
        char packet_type = serial_rx_buffer[1]; // Skip '<'
        char* data_start = serial_rx_buffer + 3; // Skip '<', TYPE, and '|'
        char* checksum_start = strrchr(data_start, '|');

        if (checksum_start != NULL) {
          *checksum_start = '\0'; // Null-terminate data_start
          checksum_start++; // Move past '|'
          
          byte received_checksum = (byte)strtol(checksum_start, NULL, 16);
          // Calculate checksum over packet_type and data_start
          byte calculated_checksum = calculateChecksum(packet_type, data_start);

          if (received_checksum == calculated_checksum) {
            // Valid packet received
            last_command_time = millis(); // Reset watchdog
            // Only clear system_emergency_stop if it was due to watchdog, not leak
            if (!leak_status && !system_emergency_stop) { // Only clear if no leak and no current emergency stop
                 system_emergency_stop = false;
            }

            if (packet_type == PACKET_TYPE_MOTOR) {
              // Parse motor command data
              int m_values[10];
              char* token;
              int i = 0;
              // Use a copy of data_start as strtok modifies the string
              char data_copy[SERIAL_BUFFER_SIZE];
              strncpy(data_copy, data_start, SERIAL_BUFFER_SIZE);
              data_copy[SERIAL_BUFFER_SIZE - 1] = '\0'; // Ensure null-termination

              token = strtok(data_copy, ",");
              while (token != NULL && i < 10) {
                m_values[i++] = atoi(token);
                token = strtok(NULL, ",");
              }

              if (i == 10) { // Ensure all 10 values are parsed
                int m1 = m_values[0];
                int m2 = m_values[1];
                int m3 = m_values[2];
                int m4 = m_values[3];
                int m5 = m_values[4];
                int m6 = m_values[5];
                int grip = m_values[6];
                int rot = m_values[7];
                stab_mode = m_values[8];
                int leak_override_from_laptop = m_values[9];

                // Highest priority safety: Leak detection or Laptop emergency override
                if (leak_status == 1 || leak_override_from_laptop == 1) {
                  m1 = m2 = m3 = m4 = m5 = m6 = grip = rot = 0;
                  system_emergency_stop = true; // Ensure local flag is set
                } else if (system_emergency_stop && !leak_status) { 
                   // If emergency stop was due to watchdog and no leak, clear it now
                   system_emergency_stop = false;
                }

                // Stabilization Logic for M5, M6
                if (stab_mode == 1 && mpu_ok && !system_emergency_stop) {
                  float Kp_roll = 5; // Proportional constant for roll (tune this)
                  float Kp_pitch = 5; // Proportional constant for pitch (tune this)

                  int roll_correction = (int)(roll_mpu * Kp_roll);
                  int pitch_correction = (int)(pitch_mpu * Kp_pitch);

                  m5 = constrain(m5 + pitch_correction - roll_correction, -255, 255);
                  m6 = constrain(m6 + pitch_correction + roll_correction, -255, 255);
                }

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
              } else {
                Serial.println("Error: Malformed MOTOR packet data length.");
              }
            } else {
              Serial.print("Error: Unknown packet type received: ");
              Serial.println(packet_type);
            }
          } else {
            Serial.print("Checksum mismatch! Received: ");
            Serial.print(received_checksum, HEX);
            Serial.print(", Calculated: ");
            Serial.println(calculated_checksum, HEX);
          }
        } else {
          Serial.println("Error: Checksum delimiter not found.");
        }
      } else { // Malformed packet (no START_DELIMITER or empty)
        Serial.println("Error: Malformed packet received (no START_DELIMITER or empty).");
      }
      serial_rx_idx = 0; // Reset buffer index
    } else {
      if (serial_rx_idx < SERIAL_BUFFER_SIZE - 1) {
        serial_rx_buffer[serial_rx_idx++] = inChar;
      } else {
        Serial.println("Error: Serial RX buffer overflow. Clearing buffer.");
        serial_rx_idx = 0; // Clear buffer on overflow
      }
    }
  }

  // If system is in emergency stop, ensure all motors are off
  if (system_emergency_stop) {
    setMotor(0, M1_R_PWM, M1_L_PWM);
    setMotor(0, M2_R_PWM, M2_L_PWM);
    setMotor(0, M3_R_PWM, M3_L_PWM);
    setMotor(0, M4_R_PWM, M4_L_PWM);
    setMotor(0, M5_R_PWM, M5_L_PWM);
    setMotor(0, M6_R_PWM, M6_L_PWM);
    setMotor(0, GRIP_R_PWM, GRIP_L_PWM);
    setMotor(0, ROT_R_PWM, ROT_L_PWM);
  }

  // Send sensor data to Raspberry Pi periodically
  static unsigned long lastSensorSendTime = 0;
  if (millis() - lastSensorSendTime > 200) { // Send sensor data every 200ms
    char sensor_data_payload[SERIAL_BUFFER_SIZE]; // Use a buffer for payload
    int len = snprintf(sensor_data_payload, SERIAL_BUFFER_SIZE, "%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d",
                       bmp_ok ? temp_bmp : 0.0,
                       bmp_ok ? pres_bmp : 0.0,
                       ms5837_ok ? pres_ms : 0.0,
                       ms5837_ok ? depth_ms : 0.0,
                       mpu_ok ? roll_mpu : 0.0,
                       mpu_ok ? pitch_mpu : 0.0,
                       mpu_ok ? yaw_mpu : 0.0, // Include yaw_mpu
                       leak_status);
    
    // Ensure snprintf didn't truncate
    if (len >= SERIAL_BUFFER_SIZE || len < 0) {
      Serial.println("Error: Sensor data payload too long or snprintf error.");
      // Handle error, perhaps send an empty or error packet
    } else {
      byte checksum = calculateChecksum(PACKET_TYPE_SENSOR, sensor_data_payload);

      Serial.print(START_DELIMITER);
      Serial.print(PACKET_TYPE_SENSOR);
      Serial.print("|");
      Serial.print(sensor_data_payload);
      Serial.print("|");
      Serial.print(checksum, HEX);
      Serial.println(END_DELIMITER);
    }
    lastSensorSendTime = millis();
  }
}
