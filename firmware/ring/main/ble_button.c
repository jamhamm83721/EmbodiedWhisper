#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_err.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_hs_mbuf.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "host/ble_store.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "ble_button.h"

static const char *TAG = "ble_button";

static const ble_uuid128_t s_service_uuid =
    BLE_UUID128_INIT(0xf0, 0xde, 0xbc, 0x9a, 0x78, 0x56, 0x34, 0x12,
                     0x78, 0x56, 0x34, 0x12, 0x78, 0x56, 0x34, 0x12);
static const ble_uuid128_t s_char_uuid =
    BLE_UUID128_INIT(0xf1, 0xde, 0xbc, 0x9a, 0x78, 0x56, 0x34, 0x12,
                     0x78, 0x56, 0x34, 0x12, 0x78, 0x56, 0x34, 0x12);

static uint8_t s_own_addr_type;
static uint16_t s_char_val_handle;
static uint16_t s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static bool s_notify_enabled = false;
static button_event_t s_last_event = BUTTON_EVENT_RELEASED;
static uint8_t s_adv_event_code = 0;
static uint16_t s_adv_event_counter = 0;
static QueueHandle_t s_event_queue = NULL;

static const char *ble_addr_type_to_string(uint8_t addr_type)
{
    switch (addr_type) {
        case BLE_ADDR_PUBLIC:
            return "public";
        case BLE_ADDR_RANDOM:
            return "random";
        case BLE_ADDR_PUBLIC_ID:
            return "public_id";
        case BLE_ADDR_RANDOM_ID:
            return "random_id";
        default:
            return "unknown";
    }
}

static const char *ble_disconnect_reason_to_string(int reason)
{
    switch (reason) {
        case 0x05:
            return "authentication failed";
        case 0x08:
            return "connection timeout";
        case 0x13:
            return "remote user terminated connection";
        case 0x16:
            return "local host terminated connection";
        case 0x1A:
            return "unsupported remote feature";
        case 0x3E:
            return "connection establishment failed";
        default:
            return "unknown";
    }
}

void ble_store_config_init(void);

static const char *ble_button_event_to_string(button_event_t event)
{
    switch (event) {
        case BUTTON_EVENT_PRESSED:
            return "pressed";
        case BUTTON_EVENT_RELEASED:
            return "released";
        case BUTTON_EVENT_CLICKED:
            return "clicked";
        case BUTTON_EVENT_LONG_PRESSED:
            return "long_pressed";
        default:
            return "unknown";
    }
}

static uint8_t ble_button_event_to_code(button_event_t event)
{
    switch (event) {
        case BUTTON_EVENT_CLICKED:
            return 1;
        case BUTTON_EVENT_LONG_PRESSED:
            return 2;
        case BUTTON_EVENT_PRESSED:
            return 3;
        case BUTTON_EVENT_RELEASED:
        default:
            return 0;
    }
}

static int ble_button_char_access(uint16_t conn_handle, uint16_t attr_handle,
                                  struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    button_event_t event = s_last_event;
    const char *event_str = ble_button_event_to_string(s_last_event);
    int rc;

    (void)conn_handle;
    (void)arg;

    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR || attr_handle != s_char_val_handle) {
        return BLE_ATT_ERR_UNLIKELY;
    }

    rc = os_mbuf_append(ctxt->om, event_str, strlen(event_str));
    if (rc != 0) {
        return BLE_ATT_ERR_INSUFFICIENT_RES;
    }

    /* Read polling fallback: consume actionable events once. */
    if (event == BUTTON_EVENT_CLICKED || event == BUTTON_EVENT_LONG_PRESSED) {
        s_last_event = BUTTON_EVENT_RELEASED;
    }

    return 0;
}

static const struct ble_gatt_svc_def s_gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &s_service_uuid.u,
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                .uuid = &s_char_uuid.u,
                .access_cb = ble_button_char_access,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &s_char_val_handle,
            },
            {0}
        },
    },
    {0},
};

static void ble_button_advertise(void);

static void ble_button_update_advertising_event(button_event_t event)
{
    if (event != BUTTON_EVENT_CLICKED && event != BUTTON_EVENT_LONG_PRESSED) {
        return;
    }

    s_adv_event_code = ble_button_event_to_code(event);
    s_adv_event_counter++;

    /*
     * Connection-free Raspberry Pi path:
     * restart advertising so scanners can see the latest short/long press
     * without pairing, connecting, reading, or subscribing.
     */
    if (s_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        (void)ble_gap_adv_stop();
        ble_button_advertise();
    }
}

static int ble_button_gap_event(struct ble_gap_event *event, void *arg)
{
    (void)arg;

    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status == 0) {
                s_conn_handle = event->connect.conn_handle;
                s_notify_enabled = false;
                ESP_LOGI(TAG, "BLE connected, conn_handle=%d", s_conn_handle);
            } else {
                ESP_LOGW(TAG, "BLE connect failed, status=%d", event->connect.status);
                ble_button_advertise();
            }
            return 0;

        case BLE_GAP_EVENT_DISCONNECT:
            ESP_LOGI(TAG,
                     "BLE disconnected, reason=%d (%s)",
                     event->disconnect.reason,
                     ble_disconnect_reason_to_string(event->disconnect.reason));
            s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            s_notify_enabled = false;
            ble_button_advertise();
            return 0;

        case BLE_GAP_EVENT_SUBSCRIBE:
            ESP_LOGI(TAG,
                     "BLE subscribe event: conn_handle=%d attr_handle=%d reason=%d prev_notify=%d cur_notify=%d",
                     event->subscribe.conn_handle,
                     event->subscribe.attr_handle,
                     event->subscribe.reason,
                     event->subscribe.prev_notify,
                     event->subscribe.cur_notify);
            if (event->subscribe.attr_handle == s_char_val_handle) {
                s_conn_handle = event->subscribe.conn_handle;
                s_notify_enabled = event->subscribe.cur_notify;
                ESP_LOGI(TAG, "BLE subscribe changed, notify=%d", s_notify_enabled);
            }
            return 0;

        case BLE_GAP_EVENT_ADV_COMPLETE:
            ESP_LOGI(TAG, "BLE advertising completed, restarting");
            ble_button_advertise();
            return 0;

        case BLE_GAP_EVENT_MTU:
            ESP_LOGI(TAG, "BLE mtu updated to %d", event->mtu.value);
            return 0;

        case BLE_GAP_EVENT_NOTIFY_TX:
            if (event->notify_tx.status != 0 && event->notify_tx.status != BLE_HS_EDONE) {
                ESP_LOGW(TAG, "BLE notify status=%d", event->notify_tx.status);
            }
            return 0;

        default:
            return 0;
    }
}

static void ble_button_advertise(void)
{
    struct ble_hs_adv_fields fields = {0};
    struct ble_hs_adv_fields rsp_fields = {0};
    const char *name = ble_svc_gap_device_name();
    struct ble_gap_adv_params adv_params = {0};
    uint8_t mfg_data[8] = {
        0xff, 0xff, 'R', 'N', 'G',
        s_adv_event_code,
        (uint8_t)(s_adv_event_counter & 0xff),
        (uint8_t)((s_adv_event_counter >> 8) & 0xff),
    };
    int rc;

    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = (ble_uuid128_t *)&s_service_uuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    fields.mfg_data = mfg_data;
    fields.mfg_data_len = sizeof(mfg_data);

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gap_adv_set_fields failed, rc=%d", rc);
        return;
    }

    rsp_fields.name = (uint8_t *)name;
    rsp_fields.name_len = strlen(name);
    rsp_fields.name_is_complete = 1;

    rc = ble_gap_adv_rsp_set_fields(&rsp_fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gap_adv_rsp_set_fields failed, rc=%d", rc);
        return;
    }

    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    adv_params.itvl_min = BLE_GAP_ADV_ITVL_MS(100);
    adv_params.itvl_max = BLE_GAP_ADV_ITVL_MS(120);

    rc = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER, &adv_params,
                           ble_button_gap_event, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gap_adv_start failed, rc=%d", rc);
        return;
    }

    ESP_LOGI(TAG, "BLE advertising as %s", BLE_BUTTON_DEVICE_NAME);
}

static void ble_button_on_sync(void)
{
    uint8_t addr_val[6] = {0};
    int nrpa = 0;
    int rc = ble_hs_util_ensure_addr(0);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_hs_util_ensure_addr failed, rc=%d", rc);
        return;
    }

    rc = ble_hs_id_infer_auto(0, &s_own_addr_type);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_hs_id_infer_auto failed, rc=%d", rc);
        return;
    }

    rc = ble_hs_id_copy_addr(s_own_addr_type, addr_val, &nrpa);
    if (rc == 0) {
        ESP_LOGI(TAG,
                 "BLE advertising address: %02X:%02X:%02X:%02X:%02X:%02X, type=%s, nrpa=%d",
                 addr_val[5], addr_val[4], addr_val[3],
                 addr_val[2], addr_val[1], addr_val[0],
                 ble_addr_type_to_string(s_own_addr_type), nrpa);
    } else {
        ESP_LOGW(TAG, "ble_hs_id_copy_addr failed, rc=%d", rc);
    }

    ble_button_advertise();
}

static void ble_button_on_reset(int reason)
{
    ESP_LOGW(TAG, "BLE stack reset, reason=%d", reason);
}

static void ble_button_host_task(void *param)
{
    (void)param;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static void ble_button_notify_task(void *param)
{
    button_event_t event;

    (void)param;

    while (1) {
        if (xQueueReceive(s_event_queue, &event, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        s_last_event = event;
        ble_button_update_advertising_event(event);

        ESP_LOGI(TAG,
                 "button event queued: %s, conn_handle=%d, notify_enabled=%d",
                 ble_button_event_to_string(event),
                 s_conn_handle,
                 s_notify_enabled);

        if (s_conn_handle == BLE_HS_CONN_HANDLE_NONE || !s_notify_enabled) {
            continue;
        }

        {
            struct os_mbuf *om;
            const char *event_str = ble_button_event_to_string(event);
            int rc;

            om = ble_hs_mbuf_from_flat(event_str, strlen(event_str));
            if (om == NULL) {
                ESP_LOGW(TAG, "failed to allocate notification buffer");
                continue;
            }

            rc = ble_gatts_notify_custom(s_conn_handle, s_char_val_handle, om);
            if (rc != 0) {
                ESP_LOGW(TAG, "ble_gatts_notify_custom failed, rc=%d", rc);
            } else {
                ESP_LOGI(TAG, "BLE notification sent: %s", event_str);
            }
        }
    }
}

esp_err_t ble_button_init(void)
{
    esp_err_t ret;
    int rc;

    ret = nimble_port_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ble_hs_cfg.reset_cb = ble_button_on_reset;
    ble_hs_cfg.sync_cb = ble_button_on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_hs_cfg.sm_bonding = 0;
    ble_hs_cfg.sm_mitm = 0;
    ble_hs_cfg.sm_sc = 0;
    ble_hs_cfg.sm_our_key_dist = 0;
    ble_hs_cfg.sm_their_key_dist = 0;

    ble_store_config_init();
    ble_svc_gap_init();
    ble_svc_gatt_init();

    rc = ble_svc_gap_device_name_set(BLE_BUTTON_DEVICE_NAME);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_svc_gap_device_name_set failed, rc=%d", rc);
        return ESP_FAIL;
    }

    rc = ble_gatts_count_cfg(s_gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gatts_count_cfg failed, rc=%d", rc);
        return ESP_FAIL;
    }

    rc = ble_gatts_add_svcs(s_gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gatts_add_svcs failed, rc=%d", rc);
        return ESP_FAIL;
    }

    s_event_queue = xQueueCreate(8, sizeof(button_event_t));
    if (s_event_queue == NULL) {
        ESP_LOGE(TAG, "failed to create event queue");
        return ESP_FAIL;
    }

    nimble_port_freertos_init(ble_button_host_task);
    xTaskCreate(ble_button_notify_task, "ble_btn_ntf", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "BLE button service initialized");
    return ESP_OK;
}

void ble_button_publish_event(button_event_t event)
{
    if (s_event_queue == NULL) {
        return;
    }

    if (xQueueSend(s_event_queue, &event, 0) != pdTRUE) {
        ESP_LOGW(TAG, "button event queue full");
    }
}
