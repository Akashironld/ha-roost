/*
 * OpenTherm protocol implementation. Originally taken from https://github.com/jpraus/arduino-opentherm, but
 * heavily modified to comply with ESPHome coding standards and provide better logging.
 * Original code is licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
 * Public License, which is compatible with GPLv3 license, which covers C++ part of ESPHome project.
 */

#include "opentherm.h"
#include "esphome/core/helpers.h"
#include <cinttypes>
#ifdef USE_ESP32
#include "esp_err.h"
#endif
#ifdef ESP8266
#include "Arduino.h"
#endif
#include <string>

namespace esphome::opentherm {

using std::string;

static const char *const TAG = "opentherm";

#ifdef ESP8266
OpenTherm *OpenTherm::instance = nullptr;
#endif

OpenTherm::OpenTherm(InternalGPIOPin *in_pin, InternalGPIOPin *out_pin, int32_t device_timeout)
    : in_pin_(in_pin),
      out_pin_(out_pin),
      mode_(OperationMode::IDLE),
      error_type_(ProtocolErrorType::NO_ERROR),
      capture_(0),
      clock_(0),
      data_(0),
      bit_pos_(0),
      timeout_counter_(-1),
      device_timeout_(device_timeout) {
  this->isr_in_pin_ = in_pin->to_isr();
  this->isr_out_pin_ = out_pin->to_isr();
}

bool OpenTherm::initialize() {
#ifdef ESP8266
  OpenTherm::instance = this;
#endif
  this->in_pin_->pin_mode(gpio::FLAG_INPUT);
  this->in_pin_->setup();
  this->out_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->out_pin_->setup();
  this->out_pin_->digital_write(true);

#ifdef USE_ESP32
  // Edge-decoder extension: timestamp every edge on the input (for the edge decoder and pulse statistics)
  if (this->rmt_capture_) {
    if (!this->init_rmt_())
      return false;
  } else if (this->edge_decoder_ || this->edge_stats_) {
    this->in_pin_->attach_interrupt(OpenTherm::edge_isr, this, gpio::INTERRUPT_ANY_EDGE);
  }
  return this->init_esp32_timer_();
#else
  return true;
#endif
}

void OpenTherm::listen() {
  this->stop_timer_();
  this->timeout_counter_ = this->device_timeout_ * 5;  // timer_ ticks at 5 ticks/ms

  this->mode_ = OperationMode::LISTEN;
  this->data_ = 0;
  this->bit_pos_ = 0;
  this->edge_n_ = 0;
  this->read_ticks_ = 0;
  this->capture_on_ = true;
  if (this->rmt_capture_)
    this->arm_rmt_();

  this->start_read_timer_();
}

void OpenTherm::send(OpenthermData &data) {
  this->stop_timer_();
  this->capture_on_ = false;
  this->data_ = data.type;
  this->data_ = (this->data_ << 12) | data.id;
  this->data_ = (this->data_ << 8) | data.valueHB;
  this->data_ = (this->data_ << 8) | data.valueLB;
  if (!check_parity_(this->data_)) {
    this->data_ = this->data_ | 0x80000000;
  }

  this->clock_ = 1;     // clock starts at HIGH
  this->bit_pos_ = 33;  // count down (33 == start bit, 32-1 data, 0 == stop bit)
  this->mode_ = OperationMode::WRITE;

  this->start_write_timer_();
}

bool OpenTherm::get_message(OpenthermData &data) {
  if (this->mode_ == OperationMode::RECEIVED) {
    data.type = (this->data_ >> 28) & 0x7;
    data.id = (this->data_ >> 16) & 0xFF;
    data.valueHB = (this->data_ >> 8) & 0xFF;
    data.valueLB = this->data_ & 0xFF;
    return true;
  }
  return false;
}

bool OpenTherm::get_protocol_error(OpenThermError &error) {
  if (this->mode_ != OperationMode::ERROR_PROTOCOL) {
    return false;
  }

  error.error_type = this->error_type_;
  error.bit_pos = this->bit_pos_;
  error.capture = this->capture_;
  error.clock = this->clock_;
  error.data = this->data_;

  return true;
}

void OpenTherm::stop() {
  this->stop_timer_();
  this->mode_ = OperationMode::IDLE;
  this->out_pin_->digital_write(true);
}

void IRAM_ATTR OpenTherm::read_() {
  this->data_ = 0;
  this->bit_pos_ = 0;
  this->mode_ = OperationMode::READ;
  this->capture_ = 1;         // reset counter and add as if read start bit
  this->clock_ = 1;           // clock is high at the start of comm
  this->start_read_timer_();  // get us into 1/4 of manchester code. 5 timer ticks constitute 1 ms, which is 1 bit
                              // period in OpenTherm.
}

#ifdef USE_ESP32
bool IRAM_ATTR OpenTherm::timer_isr(gptimer_handle_t timer, const gptimer_alarm_event_data_t *edata, void *user_ctx) {
  auto *arg = static_cast<OpenTherm *>(user_ctx);
#else
bool IRAM_ATTR OpenTherm::timer_isr(OpenTherm *arg) {
#endif
  if (arg->mode_ == OperationMode::LISTEN) {
    if (arg->timeout_counter_ == 0) {
      arg->mode_ = OperationMode::ERROR_TIMEOUT;
      arg->stop_timer_();
      return false;
    }
    bool const value = arg->isr_in_pin_.digital_read();
    if (value) {  // incoming data (rising signal)
      arg->read_();
    }
    if (arg->timeout_counter_ > 0) {
      arg->timeout_counter_--;
    }
  } else if (arg->mode_ == OperationMode::READ && arg->edge_decoder_) {
    // Edge decoder: wait until the whole response (34 bits = 34 ms) is in, then decode it from the edges.
    ++arg->read_ticks_;
    // After 36 ms (180 x 0.2 ms) the response is complete. With RMT, wait until the peripheral closes the capture
    // (2 ms idle after the stop bit), at most 60 ms.
    bool const ready = arg->rmt_capture_ ? (arg->rmt_done_ || arg->read_ticks_ >= 300) : arg->read_ticks_ >= 180;
    if (ready && arg->read_ticks_ >= 180) {
      arg->decode_edges_();
    }
  } else if (arg->mode_ == OperationMode::READ) {
    bool const value = arg->isr_in_pin_.digital_read();
    uint8_t const last = (arg->capture_ & 1);
    if (value != last) {
      // transition of signal from last sampling
      if (arg->clock_ == 1 && arg->capture_ > 0xF) {
        // no transition in the middle of the bit
        arg->mode_ = OperationMode::ERROR_PROTOCOL;
        arg->error_type_ = ProtocolErrorType::NO_TRANSITION;
        arg->stop_timer_();
        return false;
      } else if (arg->clock_ == 1 || arg->capture_ > 0xF) {
        // transition in the middle of the bit OR no transition between two bit, both are valid data points
        if (arg->bit_pos_ == BitPositions::STOP_BIT) {
          // expecting stop bit
          auto stop_bit_error = arg->verify_stop_bit_(last);
          if (stop_bit_error == ProtocolErrorType::NO_ERROR) {
            arg->mode_ = OperationMode::RECEIVED;
            arg->stop_timer_();
            return false;
          } else {
            // end of data not verified, invalid data
            arg->mode_ = OperationMode::ERROR_PROTOCOL;
            arg->error_type_ = stop_bit_error;
            arg->stop_timer_();
            return false;
          }
        } else {
          // normal data point at clock high
          arg->bit_read_(last);
          arg->clock_ = 0;
        }
      } else {
        // clock low, not a data point, switch clock
        arg->clock_ = 1;
      }
      arg->capture_ = 1;  // reset counter
    } else if (arg->capture_ > 0xFF) {
      // no change for too long, invalid manchester encoding
      arg->mode_ = OperationMode::ERROR_PROTOCOL;
      arg->error_type_ = ProtocolErrorType::NO_CHANGE_TOO_LONG;
      arg->stop_timer_();
      return false;
    }
    arg->capture_ = (arg->capture_ << 1) | value;
  } else if (arg->mode_ == OperationMode::WRITE) {
    // write data to pin
    if (arg->bit_pos_ == 33 || arg->bit_pos_ == 0) {  // start bit
      arg->write_bit_(1, arg->clock_);
    } else {  // data bits
      arg->write_bit_(read_bit(arg->data_, arg->bit_pos_ - 1), arg->clock_);
    }
    if (arg->clock_ == 0) {
      if (arg->bit_pos_ <= 0) {            // check termination
        arg->mode_ = OperationMode::SENT;  // all data written
        arg->stop_timer_();
      }
      arg->bit_pos_--;
      arg->clock_ = 1;
    } else {
      arg->clock_ = 0;
    }
  }

  return false;
}

#ifdef ESP8266
void IRAM_ATTR OpenTherm::esp8266_timer_isr() { OpenTherm::timer_isr(OpenTherm::instance); }
#endif

void IRAM_ATTR OpenTherm::bit_read_(uint8_t value) {
  this->data_ = (this->data_ << 1) | value;
  this->bit_pos_++;
}

ProtocolErrorType IRAM_ATTR OpenTherm::verify_stop_bit_(uint8_t value) {
  if (value) {  // stop bit detected
    return check_parity_(this->data_) ? ProtocolErrorType::NO_ERROR : ProtocolErrorType::PARITY_ERROR;
  } else {  // no stop bit detected, error
    return ProtocolErrorType::INVALID_STOP_BIT;
  }
}

void IRAM_ATTR OpenTherm::write_bit_(uint8_t high, uint8_t clock) {
  if (clock == 1) {                           // left part of manchester encoding
    this->isr_out_pin_.digital_write(!high);  // low means logical 1 to protocol
  } else {                                    // right part of manchester encoding
    this->isr_out_pin_.digital_write(high);   // high means logical 0 to protocol
  }
}

#ifdef USE_ESP32

bool OpenTherm::init_esp32_timer_() {
  // 80MHz / 80 = 1MHz resolution (1µs per tick)
  gptimer_config_t config = {
      .clk_src = GPTIMER_CLK_SRC_DEFAULT,
      .direction = GPTIMER_COUNT_UP,
      .resolution_hz = 1000000,
  };

  esp_err_t result = gptimer_new_timer(&config, &this->timer_handle_);
  if (result != ESP_OK) {
    ESP_LOGE(TAG, "Failed to create timer: %s", esp_err_to_name(result));
    return false;
  }

  gptimer_event_callbacks_t cbs = {
      .on_alarm = OpenTherm::timer_isr,
  };
  result = gptimer_register_event_callbacks(this->timer_handle_, &cbs, this);
  if (result != ESP_OK) {
    ESP_LOGE(TAG, "Failed to register timer callback: %s", esp_err_to_name(result));
    gptimer_del_timer(this->timer_handle_);
    this->timer_handle_ = nullptr;
    return false;
  }

  result = gptimer_enable(this->timer_handle_);
  if (result != ESP_OK) {
    ESP_LOGE(TAG, "Failed to enable timer: %s", esp_err_to_name(result));
    gptimer_del_timer(this->timer_handle_);
    this->timer_handle_ = nullptr;
    return false;
  }

  return true;
}

void IRAM_ATTR OpenTherm::start_esp32_timer_(uint64_t alarm_value) {
  // We will report timer errors outside of interrupt handler
  this->timer_error_ = ESP_OK;
  this->timer_error_type_ = TimerErrorType::NO_TIMER_ERROR;

  this->alarm_config_.alarm_count = alarm_value;
  this->timer_error_ = gptimer_set_alarm_action(this->timer_handle_, &this->alarm_config_);
  if (this->timer_error_ != ESP_OK) {
    this->timer_error_type_ = TimerErrorType::SET_ALARM_VALUE_ERROR;
    return;
  }
  this->timer_error_ = gptimer_start(this->timer_handle_);
  if (this->timer_error_ != ESP_OK) {
    this->timer_error_type_ = TimerErrorType::TIMER_START_ERROR;
  }
}

void OpenTherm::report_and_reset_timer_error() {
  if (this->timer_error_ == ESP_OK) {
    return;
  }

  ESP_LOGE(TAG, "Error occured while manipulating timer (%s): %s", this->timer_error_to_str(this->timer_error_type_),
           esp_err_to_name(this->timer_error_));

  this->timer_error_ = ESP_OK;
  this->timer_error_type_ = NO_TIMER_ERROR;
}

// 5 kHz timer_
void IRAM_ATTR OpenTherm::start_read_timer_() {
  InterruptLock const lock;
  this->start_esp32_timer_(200);
}

// 2 kHz timer_
void IRAM_ATTR OpenTherm::start_write_timer_() {
  InterruptLock const lock;
  this->start_esp32_timer_(500);
}

void IRAM_ATTR OpenTherm::stop_timer_() {
  InterruptLock const lock;
  // We will report timer errors outside of interrupt handler
  this->timer_error_ = ESP_OK;
  this->timer_error_type_ = TimerErrorType::NO_TIMER_ERROR;

  this->timer_error_ = gptimer_stop(this->timer_handle_);
  if (this->timer_error_ != ESP_OK) {
    this->timer_error_type_ = TimerErrorType::TIMER_PAUSE_ERROR;
    return;
  }
  this->timer_error_ = gptimer_set_raw_count(this->timer_handle_, 0);
  if (this->timer_error_ != ESP_OK) {
    this->timer_error_type_ = TimerErrorType::SET_COUNTER_VALUE_ERROR;
  }
}

#endif  // USE_ESP32

#ifdef ESP8266
// 5 kHz timer_
void IRAM_ATTR OpenTherm::start_read_timer_() {
  InterruptLock const lock;
  timer1_attachInterrupt(OpenTherm::esp8266_timer_isr);
  timer1_enable(TIM_DIV16, TIM_EDGE, TIM_LOOP);  // 5MHz (5 ticks/us - 1677721.4 us max)
  timer1_write(1000);                            // 5kHz
}

// 2 kHz timer_
void IRAM_ATTR OpenTherm::start_write_timer_() {
  InterruptLock const lock;
  timer1_attachInterrupt(OpenTherm::esp8266_timer_isr);
  timer1_enable(TIM_DIV16, TIM_EDGE, TIM_LOOP);  // 5MHz (5 ticks/us - 1677721.4 us max)
  timer1_write(2500);                            // 2kHz
}

void IRAM_ATTR OpenTherm::stop_timer_() {
  InterruptLock const lock;
  timer1_disable();
  timer1_detachInterrupt();
}

// There is nothing to report on ESP8266
void OpenTherm::report_and_reset_timer_error() {}

#endif  // END ESP8266

// https://stackoverflow.com/questions/21617970/how-to-check-if-value-has-even-parity-of-bits-or-odd
bool IRAM_ATTR OpenTherm::check_parity_(uint32_t val) {
  val ^= val >> 16;
  val ^= val >> 8;
  val ^= val >> 4;
  val ^= val >> 2;
  val ^= val >> 1;
  return (~val) & 1;
}

#define TO_STRING_MEMBER(name) \
  case name: \
    return #name;

const char *OpenTherm::operation_mode_to_str(OperationMode mode) {
  switch (mode) {
    TO_STRING_MEMBER(IDLE)
    TO_STRING_MEMBER(LISTEN)
    TO_STRING_MEMBER(READ)
    TO_STRING_MEMBER(RECEIVED)
    TO_STRING_MEMBER(WRITE)
    TO_STRING_MEMBER(SENT)
    TO_STRING_MEMBER(ERROR_PROTOCOL)
    TO_STRING_MEMBER(ERROR_TIMEOUT)
    TO_STRING_MEMBER(ERROR_TIMER)
    default:
      return "<INVALID>";
  }
}
const char *OpenTherm::protocol_error_to_str(ProtocolErrorType error_type) {
  switch (error_type) {
    TO_STRING_MEMBER(NO_ERROR)
    TO_STRING_MEMBER(NO_TRANSITION)
    TO_STRING_MEMBER(INVALID_STOP_BIT)
    TO_STRING_MEMBER(PARITY_ERROR)
    TO_STRING_MEMBER(NO_CHANGE_TOO_LONG)
    default:
      return "<INVALID>";
  }
}
const char *OpenTherm::timer_error_to_str(TimerErrorType error_type) {
  switch (error_type) {
    TO_STRING_MEMBER(NO_TIMER_ERROR)
    TO_STRING_MEMBER(SET_ALARM_VALUE_ERROR)
    TO_STRING_MEMBER(TIMER_START_ERROR)
    TO_STRING_MEMBER(TIMER_PAUSE_ERROR)
    TO_STRING_MEMBER(SET_COUNTER_VALUE_ERROR)
    default:
      return "<INVALID>";
  }
}
const char *OpenTherm::message_type_to_str(MessageType message_type) {
  switch (message_type) {
    TO_STRING_MEMBER(READ_DATA)
    TO_STRING_MEMBER(READ_ACK)
    TO_STRING_MEMBER(WRITE_DATA)
    TO_STRING_MEMBER(WRITE_ACK)
    TO_STRING_MEMBER(INVALID_DATA)
    TO_STRING_MEMBER(DATA_INVALID)
    TO_STRING_MEMBER(UNKNOWN_DATAID)
    default:
      return "<INVALID>";
  }
}

const char *OpenTherm::message_id_to_str(MessageId id) {
  switch (id) {
    TO_STRING_MEMBER(STATUS)
    TO_STRING_MEMBER(CH_SETPOINT)
    TO_STRING_MEMBER(CONTROLLER_CONFIG)
    TO_STRING_MEMBER(DEVICE_CONFIG)
    TO_STRING_MEMBER(COMMAND_CODE)
    TO_STRING_MEMBER(FAULT_FLAGS)
    TO_STRING_MEMBER(REMOTE)
    TO_STRING_MEMBER(COOLING_CONTROL)
    TO_STRING_MEMBER(CH2_SETPOINT)
    TO_STRING_MEMBER(CH_SETPOINT_OVERRIDE)
    TO_STRING_MEMBER(TSP_COUNT)
    TO_STRING_MEMBER(TSP_COMMAND)
    TO_STRING_MEMBER(FHB_SIZE)
    TO_STRING_MEMBER(FHB_COMMAND)
    TO_STRING_MEMBER(MAX_MODULATION_LEVEL)
    TO_STRING_MEMBER(MAX_BOILER_CAPACITY)
    TO_STRING_MEMBER(ROOM_SETPOINT)
    TO_STRING_MEMBER(MODULATION_LEVEL)
    TO_STRING_MEMBER(CH_WATER_PRESSURE)
    TO_STRING_MEMBER(DHW_FLOW_RATE)
    TO_STRING_MEMBER(DAY_TIME)
    TO_STRING_MEMBER(DATE)
    TO_STRING_MEMBER(YEAR)
    TO_STRING_MEMBER(ROOM_SETPOINT_CH2)
    TO_STRING_MEMBER(ROOM_TEMP)
    TO_STRING_MEMBER(FEED_TEMP)
    TO_STRING_MEMBER(DHW_TEMP)
    TO_STRING_MEMBER(OUTSIDE_TEMP)
    TO_STRING_MEMBER(RETURN_WATER_TEMP)
    TO_STRING_MEMBER(SOLAR_STORE_TEMP)
    TO_STRING_MEMBER(SOLAR_COLLECT_TEMP)
    TO_STRING_MEMBER(FEED_TEMP_CH2)
    TO_STRING_MEMBER(DHW2_TEMP)
    TO_STRING_MEMBER(EXHAUST_TEMP)
    TO_STRING_MEMBER(FAN_SPEED)
    TO_STRING_MEMBER(FLAME_CURRENT)
    TO_STRING_MEMBER(ROOM_TEMP_CH2)
    TO_STRING_MEMBER(REL_HUMIDITY)
    TO_STRING_MEMBER(DHW_BOUNDS)
    TO_STRING_MEMBER(CH_BOUNDS)
    TO_STRING_MEMBER(OTC_CURVE_BOUNDS)
    TO_STRING_MEMBER(DHW_SETPOINT)
    TO_STRING_MEMBER(MAX_CH_SETPOINT)
    TO_STRING_MEMBER(OTC_CURVE_RATIO)
    TO_STRING_MEMBER(HVAC_STATUS)
    TO_STRING_MEMBER(REL_VENT_SETPOINT)
    TO_STRING_MEMBER(DEVICE_VENT)
    TO_STRING_MEMBER(HVAC_VER_ID)
    TO_STRING_MEMBER(REL_VENTILATION)
    TO_STRING_MEMBER(REL_HUMID_EXHAUST)
    TO_STRING_MEMBER(EXHAUST_CO2)
    TO_STRING_MEMBER(SUPPLY_INLET_TEMP)
    TO_STRING_MEMBER(SUPPLY_OUTLET_TEMP)
    TO_STRING_MEMBER(EXHAUST_INLET_TEMP)
    TO_STRING_MEMBER(EXHAUST_OUTLET_TEMP)
    TO_STRING_MEMBER(EXHAUST_FAN_SPEED)
    TO_STRING_MEMBER(SUPPLY_FAN_SPEED)
    TO_STRING_MEMBER(REMOTE_VENTILATION_PARAM)
    TO_STRING_MEMBER(NOM_REL_VENTILATION)
    TO_STRING_MEMBER(HVAC_NUM_TSP)
    TO_STRING_MEMBER(HVAC_IDX_TSP)
    TO_STRING_MEMBER(HVAC_FHB_SIZE)
    TO_STRING_MEMBER(HVAC_FHB_IDX)
    TO_STRING_MEMBER(RF_SIGNAL)
    TO_STRING_MEMBER(DHW_MODE)
    TO_STRING_MEMBER(OVERRIDE_FUNC)
    TO_STRING_MEMBER(SOLAR_MODE_FLAGS)
    TO_STRING_MEMBER(SOLAR_ASF)
    TO_STRING_MEMBER(SOLAR_VERSION_ID)
    TO_STRING_MEMBER(SOLAR_PRODUCT_ID)
    TO_STRING_MEMBER(SOLAR_NUM_TSP)
    TO_STRING_MEMBER(SOLAR_IDX_TSP)
    TO_STRING_MEMBER(SOLAR_FHB_SIZE)
    TO_STRING_MEMBER(SOLAR_FHB_IDX)
    TO_STRING_MEMBER(SOLAR_STARTS)
    TO_STRING_MEMBER(SOLAR_HOURS)
    TO_STRING_MEMBER(SOLAR_ENERGY)
    TO_STRING_MEMBER(SOLAR_TOTAL_ENERGY)
    TO_STRING_MEMBER(FAILED_BURNER_STARTS)
    TO_STRING_MEMBER(BURNER_FLAME_LOW)
    TO_STRING_MEMBER(OEM_DIAGNOSTIC)
    TO_STRING_MEMBER(BURNER_STARTS)
    TO_STRING_MEMBER(CH_PUMP_STARTS)
    TO_STRING_MEMBER(DHW_PUMP_STARTS)
    TO_STRING_MEMBER(DHW_BURNER_STARTS)
    TO_STRING_MEMBER(BURNER_HOURS)
    TO_STRING_MEMBER(CH_PUMP_HOURS)
    TO_STRING_MEMBER(DHW_PUMP_HOURS)
    TO_STRING_MEMBER(DHW_BURNER_HOURS)
    TO_STRING_MEMBER(OT_VERSION_CONTROLLER)
    TO_STRING_MEMBER(OT_VERSION_DEVICE)
    TO_STRING_MEMBER(VERSION_CONTROLLER)
    TO_STRING_MEMBER(VERSION_DEVICE)
    default:
      return "<INVALID>";
  }
}

void OpenTherm::debug_data(OpenthermData &data) {
  char type_buf[9], id_buf[9], hb_buf[9], lb_buf[9];
  ESP_LOGD(TAG, "%s %s %s %s", format_bin_to(type_buf, data.type), format_bin_to(id_buf, data.id),
           format_bin_to(hb_buf, data.valueHB), format_bin_to(lb_buf, data.valueLB));
  ESP_LOGD(TAG, "type: %s; id: %u; HB: %u; LB: %u; uint_16: %u; float: %f",
           this->message_type_to_str((MessageType) data.type), data.id, data.valueHB, data.valueLB, data.get_u16(),
           data.get_f88());
}
void OpenTherm::debug_error(OpenThermError &error) const {
  ESP_LOGD(TAG, "data: 0x%08" PRIx32 "; clock: %u; capture: 0x%08" PRIx32 "; bit_pos: %u", error.data, this->clock_,
           error.capture, error.bit_pos);
}

float OpenthermData::get_f88() { return ((float) this->get_s16()) / 256.0f; }

void OpenthermData::set_f88(float value) { this->set_s16((int16_t) (value * 256)); }

uint16_t OpenthermData::get_u16() {
  uint16_t const value = this->valueHB;
  return (value << 8) | this->valueLB;
}

void OpenthermData::set_u16(uint16_t value) {
  this->valueLB = value & 0xFF;
  this->valueHB = (value >> 8) & 0xFF;
}

int16_t OpenthermData::get_s16() {
  int16_t const value = this->valueHB;
  return (value << 8) | this->valueLB;
}

void OpenthermData::set_s16(int16_t value) {
  this->valueLB = value & 0xFF;
  this->valueHB = (value >> 8) & 0xFF;
}


// ------------------------------------------------------------------------------------------------------------------
// Edge-decoder extension: decode from edge timestamps.
//
// Why: the stock decoder samples at 5 kHz (every 200 µs) and tells a half bit (500 µs = 2-3 samples) from a full
// bit (1000 µs = 5 samples) with a threshold at 4 samples. An edge shifted by 100-200 µs (asymmetric opto-coupler
// response, late start detection, interrupt latency) then yields a false NO_TRANSITION. Measured on a THRM ONE v0.2
// with a Weheat P80: high half-bits 600 µs, low half-bits 400 µs, ±3 µs jitter, no glitches.
// This decoder looks for the mandatory mid-bit transition within ±330 µs of where it is expected and uses the edge
// it finds as the reference for the next bit. Glitches shorter than 100 µs are filtered out.

void IRAM_ATTR OpenTherm::edge_isr(OpenTherm *arg) {
  if (!arg->capture_on_)
    return;
  uint8_t const n = arg->edge_n_;
  if (n >= MAX_EDGES)
    return;
  arg->edge_t_[n] = (uint32_t) esp_timer_get_time();
  arg->edge_lvl_[n] = arg->isr_in_pin_.digital_read();
  arg->edge_n_ = n + 1;
}

// Filters glitches and returns the edge times from the first rising edge (start of the start bit).
static uint8_t IRAM_ATTR ot_filter_edges(const volatile uint32_t *t, const volatile uint8_t *lvl, uint8_t n,
                                         uint32_t *f, uint32_t *glitches) {
  uint8_t i = 0;
  while (i < n && lvl[i] == 0)  // first rising edge = start
    i++;
  uint8_t m = 0;
  while (i < n) {
    if (i + 1 < n && (t[i + 1] - t[i]) < 100) {  // pulse shorter than 100 µs: glitch, drop both edges
      if (glitches != nullptr)
        (*glitches)++;
      i += 2;
      continue;
    }
    f[m++] = t[i++];
  }
  return m;
}

// Decodes 34 bits (start, 32 data, stop). The level after edge k is high if k is even (k = 0: rising).
// Bit value = level in the first half = level before the mid-bit transition.
static ProtocolErrorType IRAM_ATTR ot_decode_times(const uint32_t *f, uint8_t m, uint32_t *data, uint8_t *bit_pos) {
  if (m < 2) {
    *bit_pos = 0;
    return ProtocolErrorType::NO_TRANSITION;
  }
  uint32_t ref = f[0];
  uint8_t k = 1;
  uint32_t d = 0;
  for (uint8_t bit = 0; bit < 34; bit++) {
    *bit_pos = bit;
    // Window ±330 µs around the expected mid-bit: wide enough for the measured skew (high 600 / low 400 µs) and
    // still ~170 µs away from the bit-boundary edges at ±500 µs.
    uint32_t const lo = ref + 170, hi = ref + 830;
    while (k < m && (int32_t) (f[k] - lo) < 0)
      k++;
    if (k >= m || (int32_t) (f[k] - hi) > 0)
      return ProtocolErrorType::NO_TRANSITION;
    uint8_t const value = (k % 2 == 0) ? 0 : 1;  // high after an even edge -> low before it
    if (bit == 0 && value != 1)
      return ProtocolErrorType::NO_TRANSITION;  // no valid start bit
    if (bit >= 1 && bit <= 32)
      d = (d << 1) | value;
    if (bit == 33 && value != 1)
      return ProtocolErrorType::INVALID_STOP_BIT;
    ref = f[k] + 500;
    k++;
  }
  *data = d;
  return ProtocolErrorType::NO_ERROR;
}

void IRAM_ATTR OpenTherm::decode_edges_() {
  this->capture_on_ = false;
  this->stop_timer_();
  if (this->rmt_capture_) {
    // Convert RMT symbols (level + duration) into timestamped edges; t = 0 at the first (rising) edge.
    uint8_t n = 0;
    uint32_t t = 0;
    int prev = -1;
    size_t const ns = this->rmt_done_ ? this->rmt_n_ : 0;
    for (size_t i = 0; i < ns && n < MAX_EDGES; i++) {
      for (uint8_t h = 0; h < 2 && n < MAX_EDGES; h++) {
        uint32_t const dur = h == 0 ? this->rmt_buf_[i].duration0 : this->rmt_buf_[i].duration1;
        uint8_t const lvl = h == 0 ? this->rmt_buf_[i].level0 : this->rmt_buf_[i].level1;
        if (dur == 0)
          break;  // end of capture
        if ((int) lvl != prev) {
          this->edge_t_[n] = t;
          this->edge_lvl_[n] = lvl;
          n++;
          prev = lvl;
        }
        t += dur;
      }
    }
    if (n < MAX_EDGES && prev == 1) {  // final edge back to low (end of stop bit)
      this->edge_t_[n] = t;
      this->edge_lvl_[n] = 0;
      n++;
    }
    this->edge_n_ = n;
  }
  uint32_t f[MAX_EDGES];
  uint8_t const m = ot_filter_edges(this->edge_t_, this->edge_lvl_, this->edge_n_, f, nullptr);
  uint32_t d = 0;
  uint8_t pos = 0;
  ProtocolErrorType const err = ot_decode_times(f, m, &d, &pos);
  this->bit_pos_ = pos;
  if (err == ProtocolErrorType::NO_ERROR) {
    this->data_ = d;
    this->mode_ = OperationMode::RECEIVED;
  } else {
    this->error_type_ = err;
    this->capture_ = 0;
    this->mode_ = OperationMode::ERROR_PROTOCOL;
  }
}

static const char *const TAG_EDGE = "otedge";

void OpenTherm::collect_stats(bool failed) {
  this->capture_on_ = false;
  if (!this->edge_stats_)
    return;
  uint8_t const n = this->edge_n_;
  uint32_t f[MAX_EDGES];
  uint8_t const m = ot_filter_edges(this->edge_t_, this->edge_lvl_, n, f, &this->st_glitches_);
  this->st_frames_++;
  if (failed)
    this->st_failed_++;
  uint32_t d = 0;
  uint8_t pos = 0;
  bool const dec_ok = ot_decode_times(f, m, &d, &pos) == ProtocolErrorType::NO_ERROR;
  if (!dec_ok)
    this->st_dec_fail_++;
  for (uint8_t k = 0; k + 1 < m; k++) {
    uint32_t const w = f[k + 1] - f[k];
    uint8_t const level = (k % 2 == 0) ? 1 : 0;
    uint8_t const cls = w < 750 ? 0 : 1;
    PulseStats &p = this->st_[level][cls];
    p.n++;
    p.sum += w;
    if (w < p.min)
      p.min = w;
    if (w > p.max)
      p.max = w;
    int32_t const base = cls == 0 ? 250 : 750;
    int32_t idx = ((int32_t) w - base) / 50;
    if (idx < 0)
      idx = 0;
    if (idx > 15)
      idx = 15;
    p.hist[idx]++;
  }
  if (failed || !dec_ok) {
    // Full edge list of a rejected response: H/L = high/low, in µs
    char buf[420];
    int len = snprintf(buf, sizeof(buf), "%s%s n=%u m=%u pos=%u:", failed ? "rejected" : "", dec_ok ? "" : " edge-decoder-fail",
                       n, m, pos);
    for (uint8_t k = 0; k + 1 < m && len < (int) sizeof(buf) - 8; k++)
      len += snprintf(buf + len, sizeof(buf) - len, " %c%u", (k % 2 == 0) ? 'H' : 'L', (unsigned) (f[k + 1] - f[k]));
    ESP_LOGI(TAG_EDGE, "%s", buf);
  }
}

void OpenTherm::log_stats() {
  ESP_LOGI(TAG_EDGE, "frames=%u rejected=%u edge-decoder-would-fail=%u glitches=%u", (unsigned) this->st_frames_,
           (unsigned) this->st_failed_, (unsigned) this->st_dec_fail_, (unsigned) this->st_glitches_);
  static const char *const names[2][2] = {{"L short", "L long"}, {"H short", "H long"}};
  for (uint8_t level = 0; level < 2; level++) {
    for (uint8_t cls = 0; cls < 2; cls++) {
      PulseStats &p = this->st_[level][cls];
      if (p.n == 0)
        continue;
      char hist[120];
      int len = 0;
      for (uint8_t i = 0; i < 16; i++)
        len += snprintf(hist + len, sizeof(hist) - len, "%s%u", i ? "," : "", p.hist[i]);
      ESP_LOGI(TAG_EDGE, "%s n=%u min=%u avg=%u max=%u bins(50us from %u)=%s", names[level][cls], (unsigned) p.n,
               (unsigned) p.min, (unsigned) (p.sum / p.n), (unsigned) p.max, cls == 0 ? 250 : 750, hist);
      p = PulseStats();
    }
  }
  this->st_frames_ = this->st_failed_ = this->st_glitches_ = this->st_dec_fail_ = 0;
}


bool IRAM_ATTR OpenTherm::rmt_done_cb(rmt_channel_handle_t chan, const rmt_rx_done_event_data_t *edata, void *ctx) {
  auto *arg = static_cast<OpenTherm *>(ctx);
  arg->rmt_n_ = edata->num_symbols;
  arg->rmt_done_ = true;
  arg->rmt_armed_ = false;
  return false;
}

bool OpenTherm::init_rmt_() {
  rmt_rx_channel_config_t cfg = {};
  cfg.gpio_num = (gpio_num_t) this->in_pin_->get_pin();
  cfg.clk_src = RMT_CLK_SRC_DEFAULT;
  cfg.resolution_hz = 1000000;  // 1 µs per tick
  cfg.mem_block_symbols = 48;
  cfg.flags.invert_in = this->in_pin_->is_inverted();
  esp_err_t err = rmt_new_rx_channel(&cfg, &this->rmt_rx_);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Failed to create RMT channel: %s", esp_err_to_name(err));
    return false;
  }
  rmt_rx_event_callbacks_t cbs = {};
  cbs.on_recv_done = OpenTherm::rmt_done_cb;
  rmt_rx_register_event_callbacks(this->rmt_rx_, &cbs, this);
  err = rmt_enable(this->rmt_rx_);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Failed to enable RMT channel: %s", esp_err_to_name(err));
    return false;
  }
  ESP_LOGI(TAG, "RMT capture active on GPIO%d", (int) cfg.gpio_num);
  return true;
}

void OpenTherm::arm_rmt_() {
  if (this->rmt_armed_) {  // previous capture not finished (e.g. no response): restart
    rmt_disable(this->rmt_rx_);
    rmt_enable(this->rmt_rx_);
    this->rmt_armed_ = false;
  }
  this->rmt_done_ = false;
  this->rmt_n_ = 0;
  rmt_receive_config_t rc = {};
  rc.signal_range_min_ns = 1000;     // pulses < 1 µs: glitch
  rc.signal_range_max_ns = 2000000;  // 2 ms without an edge: end of response (longest pulse ~1.1 ms)
  if (rmt_receive(this->rmt_rx_, this->rmt_buf_, sizeof(this->rmt_buf_), &rc) == ESP_OK)
    this->rmt_armed_ = true;
}

}  // namespace esphome::opentherm
