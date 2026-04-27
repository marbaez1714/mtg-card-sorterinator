#include <Arduino.h>
#include <Arduino_LED_Matrix.h>

namespace {
constexpr unsigned long kSerialWaitMs = 3000;
constexpr unsigned long kHeartbeatMs = 2000;
constexpr uint8_t kRows = 8;
constexpr uint8_t kCols = 12;

// 12×8 matrix: [row][col], 1 = LED on (Arduino_LED_Matrix / MatrixFrameBuffer
// example)
static uint8_t kSmiley[kRows][kCols] = {
    {0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0}, {0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0},
    {1, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1}, {1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1},
    {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1}, {1, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 1},
    {1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1}, {0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0},
};
} // namespace

static ArduinoLEDMatrix g_matrix;

void setup() {
  Serial.begin(115200);
  const unsigned long t0 = millis();
  while (!Serial && millis() - t0 < kSerialWaitMs) {
    delay(10);
  }

  Serial.println();
  Serial.println(F("=== LED matrix ==="));
  Serial.println(F("Smiley on 12x8 matrix"));

  g_matrix.begin();
  g_matrix.renderBitmap(kSmiley, kRows, kCols);
}

void loop() {
  static unsigned long lastTick = 0;
  const unsigned long now = millis();
  if (now - lastTick < kHeartbeatMs) {
    return;
  }
  lastTick = now;

  // Refresh static frame (keeps framebuffer in sync if anything cleared it)
  g_matrix.renderBitmap(kSmiley, kRows, kCols);

  Serial.print(F("OK "));
  Serial.print(now / 1000);
  Serial.println(F(" s (smiley on matrix)"));
}
