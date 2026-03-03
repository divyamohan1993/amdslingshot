/**
 * JalNetra Sensor Node Firmware
 * Target: Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262)
 *
 * Reads TDS, pH, turbidity, flow, and water level sensors every 30 seconds,
 * packs data into a 32-byte LoRa packet with CRC-16, and transmits to the
 * edge gateway. Deep-sleeps between transmissions for solar viability.
 *
 * LoRa Config: 866 MHz ISM India, SF7, BW 125 kHz, CR 4/5, TX 20 dBm
 * Power Budget: ~5 mW average (deep-sleep dominant)
 */

#include <Arduino.h>
#include <LoRa.h>
#include <Wire.h>
#include <driver/adc.h>
#include <esp_sleep.h>

// ---------- Pin Definitions (Heltec WiFi LoRa 32 V3) ----------
static constexpr int PIN_LORA_SCK   = 9;
static constexpr int PIN_LORA_MISO  = 11;
static constexpr int PIN_LORA_MOSI  = 10;
static constexpr int PIN_LORA_CS    = 8;
static constexpr int PIN_LORA_RST   = 12;
static constexpr int PIN_LORA_DIO0  = 14;

static constexpr int PIN_TDS        = 1;   // ADC1_CH0 — TDS analog
static constexpr int PIN_PH         = 2;   // ADC1_CH1 — pH analog
static constexpr int PIN_TURBIDITY  = 3;   // ADC1_CH2 — turbidity analog
static constexpr int PIN_FLOW       = 4;   // GPIO4 — flow meter pulse
static constexpr int PIN_TRIG       = 5;   // GPIO5 — ultrasonic trigger
static constexpr int PIN_ECHO       = 6;   // GPIO6 — ultrasonic echo
static constexpr int PIN_BATTERY    = 7;   // ADC1_CH6 — battery voltage divider
static constexpr int PIN_LED        = 35;  // Onboard LED

// ---------- Configuration ----------
#ifndef NODE_ID
#define NODE_ID 0x0001
#endif

#ifndef LORA_FREQUENCY
#define LORA_FREQUENCY 866000000  // 866 MHz India ISM
#endif

#ifndef SENSOR_INTERVAL_MS
#define SENSOR_INTERVAL_MS 30000
#endif

static constexpr uint8_t MSG_TYPE_READING   = 0x01;
static constexpr uint8_t MSG_TYPE_HEARTBEAT = 0x02;
static constexpr uint8_t MSG_TYPE_ALERT     = 0x03;
static constexpr int     PACKET_SIZE        = 32;
static constexpr int     ADC_SAMPLES        = 16;  // Oversample for noise reduction
static constexpr float   ADC_VREF           = 3.3f;
static constexpr int     ADC_RESOLUTION     = 4095;

// ---------- Globals ----------
static volatile uint32_t g_flow_pulses = 0;
static uint32_t          g_tx_count    = 0;
static uint8_t           g_packet[PACKET_SIZE];

// ---------- Flow meter ISR ----------
void IRAM_ATTR flow_isr() {
    g_flow_pulses++;
}

// ---------- ADC Helpers ----------
static float read_adc_averaged(int pin) {
    uint32_t sum = 0;
    for (int i = 0; i < ADC_SAMPLES; i++) {
        sum += analogRead(pin);
        delayMicroseconds(100);
    }
    return static_cast<float>(sum) / ADC_SAMPLES;
}

static float adc_to_voltage(float adc_raw) {
    return (adc_raw / ADC_RESOLUTION) * ADC_VREF;
}

// ---------- Sensor Reading Functions ----------

/**
 * Read TDS (Total Dissolved Solids) from DFRobot SEN0244.
 * Converts analog voltage to ppm using manufacturer calibration curve.
 * Range: 0–1000 ppm, accuracy ±10%.
 */
static float read_tds() {
    float voltage = adc_to_voltage(read_adc_averaged(PIN_TDS));
    // DFRobot TDS meter V1.0 calibration (25°C reference)
    float compensation_coeff = 1.0f;  // Simplified — no temp compensation in prototype
    float compensated_v = voltage * compensation_coeff;
    // Polynomial fit: TDS = (133.42 * V^3 - 255.86 * V^2 + 857.39 * V) * 0.5
    float tds = (133.42f * compensated_v * compensated_v * compensated_v
               - 255.86f * compensated_v * compensated_v
               + 857.39f * compensated_v) * 0.5f;
    return max(0.0f, tds);
}

/**
 * Read pH from DFRobot SEN0161-V2.
 * Linear conversion from voltage to pH.
 * Range: 0–14, accuracy ±0.1 pH.
 */
static float read_ph() {
    float voltage = adc_to_voltage(read_adc_averaged(PIN_PH));
    // SEN0161-V2: pH = 3.5 * voltage + offset (calibrated at pH 7.0 = 1.5V)
    float ph = -5.70f * voltage + 21.34f;
    return constrain(ph, 0.0f, 14.0f);
}

/**
 * Read turbidity from DFRobot SEN0189.
 * Higher voltage = clearer water. Converts to NTU.
 * Range: 0–3000 NTU.
 */
static float read_turbidity() {
    float voltage = adc_to_voltage(read_adc_averaged(PIN_TURBIDITY));
    // SEN0189: NTU = -1120.4 * V^2 + 5742.3 * V - 4352.9
    float ntu = -1120.4f * voltage * voltage + 5742.3f * voltage - 4352.9f;
    return max(0.0f, ntu);
}

/**
 * Read flow rate from YF-S201 hall-effect sensor.
 * Frequency (Hz) = 7.5 * flow_rate (L/min).
 * Accumulates pulses over the sensor interval.
 */
static float read_flow_rate() {
    uint32_t pulses = g_flow_pulses;
    g_flow_pulses = 0;
    float frequency = static_cast<float>(pulses) / (SENSOR_INTERVAL_MS / 1000.0f);
    return frequency / 7.5f;  // L/min
}

/**
 * Read water level using JSN-SR04T waterproof ultrasonic sensor.
 * Measures distance to water surface; level = tank_depth - distance.
 * Range: 25–450 cm, accuracy ±1 cm.
 */
static float read_water_level_cm() {
    digitalWrite(PIN_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(PIN_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_TRIG, LOW);

    long duration = pulseIn(PIN_ECHO, HIGH, 30000);  // 30 ms timeout
    if (duration == 0) return 0.0f;

    // Speed of sound = 343 m/s at 20°C → distance_cm = duration * 0.0343 / 2
    float distance_cm = static_cast<float>(duration) * 0.01715f;
    return constrain(distance_cm, 0.0f, 500.0f);
}

/**
 * Read battery voltage via resistor divider (100K/100K = 1:2 ratio).
 * Maps 3.0–4.2V (Li-ion range) to 0–100%.
 */
static uint8_t read_battery_pct() {
    float voltage = adc_to_voltage(read_adc_averaged(PIN_BATTERY)) * 2.0f;  // Divider ratio
    float pct = (voltage - 3.0f) / (4.2f - 3.0f) * 100.0f;
    return static_cast<uint8_t>(constrain(pct, 0.0f, 100.0f));
}

// ---------- CRC-16/CCITT-FALSE ----------
static uint16_t compute_crc16(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (int j = 0; j < 8; j++) {
            crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
        }
    }
    return crc;
}

// ---------- Packet Construction ----------

/**
 * Build 32-byte LoRa packet:
 *   [0-1]   node_id     (uint16 BE)
 *   [2]     msg_type    (uint8)
 *   [3-4]   tds         (uint16 BE, ppm)
 *   [5-6]   ph          (uint16 BE, value * 100)
 *   [7-8]   turbidity   (uint16 BE, value * 100 NTU)
 *   [9-10]  flow        (uint16 BE, value * 100 L/min)
 *   [11-12] level       (uint16 BE, cm)
 *   [13]    battery     (uint8, %)
 *   [14]    rssi        (int8, dBm — filled by receiver)
 *   [15-29] reserved    (zeros)
 *   [30-31] crc16       (uint16 BE, over bytes 0-29)
 */
static void build_packet(
    uint16_t node_id, uint8_t msg_type,
    float tds, float ph, float turbidity,
    float flow_rate, float level_cm, uint8_t battery
) {
    memset(g_packet, 0, PACKET_SIZE);

    // Node ID (big-endian)
    g_packet[0] = (node_id >> 8) & 0xFF;
    g_packet[1] = node_id & 0xFF;
    g_packet[2] = msg_type;

    // TDS (ppm, uint16)
    uint16_t tds_u = static_cast<uint16_t>(constrain(tds, 0.0f, 65535.0f));
    g_packet[3] = (tds_u >> 8) & 0xFF;
    g_packet[4] = tds_u & 0xFF;

    // pH (* 100, uint16)
    uint16_t ph_u = static_cast<uint16_t>(constrain(ph * 100.0f, 0.0f, 1400.0f));
    g_packet[5] = (ph_u >> 8) & 0xFF;
    g_packet[6] = ph_u & 0xFF;

    // Turbidity (* 100, uint16)
    uint16_t turb_u = static_cast<uint16_t>(constrain(turbidity * 100.0f, 0.0f, 65535.0f));
    g_packet[7] = (turb_u >> 8) & 0xFF;
    g_packet[8] = turb_u & 0xFF;

    // Flow rate (* 100, uint16)
    uint16_t flow_u = static_cast<uint16_t>(constrain(flow_rate * 100.0f, 0.0f, 65535.0f));
    g_packet[9] = (flow_u >> 8) & 0xFF;
    g_packet[10] = flow_u & 0xFF;

    // Water level (cm, uint16)
    uint16_t level_u = static_cast<uint16_t>(constrain(level_cm, 0.0f, 65535.0f));
    g_packet[11] = (level_u >> 8) & 0xFF;
    g_packet[12] = level_u & 0xFF;

    // Battery percentage
    g_packet[13] = battery;
    // Byte 14 (RSSI) is filled by receiver side
    // Bytes 15-29 reserved

    // CRC-16 over first 30 bytes
    uint16_t crc = compute_crc16(g_packet, 30);
    g_packet[30] = (crc >> 8) & 0xFF;
    g_packet[31] = crc & 0xFF;
}

// ---------- LoRa Transmission ----------
static bool transmit_packet() {
    if (!LoRa.beginPacket()) return false;
    LoRa.write(g_packet, PACKET_SIZE);
    return LoRa.endPacket(true);  // async mode
}

// ---------- Setup ----------
void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.printf("\n[JalNetra] Sensor Node v1.0 | ID: 0x%04X\n", NODE_ID);

    // Pin configuration
    pinMode(PIN_LED, OUTPUT);
    pinMode(PIN_TRIG, OUTPUT);
    pinMode(PIN_ECHO, INPUT);
    pinMode(PIN_FLOW, INPUT_PULLUP);

    // ADC configuration
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    // Flow meter interrupt
    attachInterrupt(digitalPinToInterrupt(PIN_FLOW), flow_isr, RISING);

    // LoRa initialization
    SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);
    LoRa.setPins(PIN_LORA_CS, PIN_LORA_RST, PIN_LORA_DIO0);

    if (!LoRa.begin(LORA_FREQUENCY)) {
        Serial.println("[ERROR] LoRa init failed!");
        // Blink LED rapidly to indicate error
        for (int i = 0; i < 20; i++) {
            digitalWrite(PIN_LED, !digitalRead(PIN_LED));
            delay(100);
        }
        esp_deep_sleep(10000000);  // Retry after 10s
    }

    LoRa.setSpreadingFactor(7);
    LoRa.setSignalBandwidth(125000);
    LoRa.setCodingRate4(5);
    LoRa.setTxPower(20);
    LoRa.enableCrc();

    Serial.printf("[LoRa] Initialized: %d MHz, SF7, BW125, TX20dBm\n", LORA_FREQUENCY / 1000000);
}

// ---------- Main Loop ----------
void loop() {
    unsigned long start = millis();
    digitalWrite(PIN_LED, HIGH);

    // Read all sensors
    float tds       = read_tds();
    float ph        = read_ph();
    float turbidity = read_turbidity();
    float flow_rate = read_flow_rate();
    float level     = read_water_level_cm();
    uint8_t battery = read_battery_pct();

    Serial.printf("[Reading #%lu] TDS=%.0f pH=%.2f Turb=%.1f Flow=%.2f Level=%.1f Batt=%d%%\n",
                  ++g_tx_count, tds, ph, turbidity, flow_rate, level, battery);

    // Build and transmit packet
    build_packet(NODE_ID, MSG_TYPE_READING, tds, ph, turbidity, flow_rate, level, battery);

    if (transmit_packet()) {
        Serial.printf("[LoRa] TX OK (%d bytes)\n", PACKET_SIZE);
    } else {
        Serial.println("[LoRa] TX FAILED");
    }

    digitalWrite(PIN_LED, LOW);

    // Calculate time spent, sleep for remainder of interval
    unsigned long elapsed = millis() - start;
    if (elapsed < SENSOR_INTERVAL_MS) {
        // Use deep sleep for power savings (wake via timer)
        uint64_t sleep_us = static_cast<uint64_t>(SENSOR_INTERVAL_MS - elapsed) * 1000ULL;
        Serial.printf("[Sleep] Deep sleep for %llu ms\n", sleep_us / 1000);
        Serial.flush();
        esp_deep_sleep(sleep_us);
    }
}
