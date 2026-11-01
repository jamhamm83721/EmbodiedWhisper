#include "sdkconfig.h"


#ifndef __WIFI_H_
#define __WIFI_H_

#include "driver/gpio.h"
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_event.h"
#include "esp_log.h"
#include "freertos/event_groups.h"


#include "string.h"
/*wifi*/


#define DEFAULT_SSID CONFIG_EW_WIFI_SSID
#define DEFAULT_PWD CONFIG_EW_WIFI_PASSWORD
#define WIFI_CONNECTED_BIT  BIT0
#define WIFI_FAIL_BIT       BIT1
#define DEFAULT_SCAN_LIST_SIZE 12


#define WIFICONFIG() {.sta = {.ssid = DEFAULT_SSID,\
    .password = DEFAULT_PWD, \
    .threshold.authmode = WIFI_AUTH_WPA2_PSK,}, \
}


void wifi_scan(void);
void wifi_sta_init(void);

#endif
