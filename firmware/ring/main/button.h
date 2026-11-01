#ifndef __BUTTON_H__
#define __BUTTON_H__

#include <stdbool.h>
#include "driver/gpio.h"
#include "esp_err.h"

#define BUTTON_GPIO              GPIO_NUM_36
#define BUTTON_ACTIVE_LEVEL      0
#define BUTTON_DEBOUNCE_MS       30
#define BUTTON_LONG_PRESS_MS     1500
#define BUTTON_SCAN_PERIOD_MS    10

typedef enum {
    BUTTON_EVENT_PRESSED = 0,
    BUTTON_EVENT_RELEASED,
    BUTTON_EVENT_CLICKED,
    BUTTON_EVENT_LONG_PRESSED,
} button_event_t;

typedef void (*button_callback_t)(button_event_t event);

esp_err_t button_init(void);
void button_start_task(button_callback_t callback);
bool button_is_pressed(void);

#endif
