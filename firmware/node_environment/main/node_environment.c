#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdlib.h>
#include <assert.h>
#include <stdint.h>
#include <time.h>
#include <sys/time.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "mqtt_client.h"
#include "esp_system.h"
#include "esp_sntp.h"
#include "esp_task_wdt.h"
#include "cJSON.h"

#define FIRMWARE_VERSION "v1.0.0"
#define WIFI_SSID "ARAZ_TR"
#define WIFI_PASSWORD "7462008+"
#define MQTT_BROKER_URI "mqtt://rpi3.lan"
#define MQTT_TELEMETRY_TOPIC "factory/node_environment/telemetry"
#define MQTT_HEARTBEAT_TOPIC "factory/node_environment/heartbeat"
#define MQTT_STATUS_TOPIC "factory/node_environment/status"
#define MQTT_COMMAND_TOPIC "factory/node_environment/command"
#define SENSOR_READ_INTERVAL_MS 5000
#define HEARTBEAT_INTERVAL_MS 30000
#define MQTT_QUEUE_LENGTH 10
#define MQTT_PAYLOAD_MAX_SIZE 256
#define WATCHDOG_TIMEOUT_MS 60000

static const char *TAG = "node_environment";
static volatile bool s_wifi_connected = false;
static volatile bool s_mqtt_connected = false;
static esp_mqtt_client_handle_t s_mqtt_client = NULL;
static QueueHandle_t mqtt_queue = NULL;
char mqtt_payload[MQTT_PAYLOAD_MAX_SIZE] = {0};
static volatile uint32_t s_sensor_read_interval_ms = SENSOR_READ_INTERVAL_MS;

typedef enum {
    MQTT_MSG_HEARTBEAT,
    MQTT_MSG_TELEMETRY,
} mqtt_msg_type_t;

typedef struct {
    char node_id[32];
    uint32_t uptime;
    uint32_t free_heap;
    int8_t wifi_rssi;
    char firmware[16];
} mqtt_heartbeat_t;

typedef struct {
    char node_id[32];
    uint32_t timestamp;
    float temperature_c;
    float humidity_pct;
} mqtt_telemetry_t;

typedef struct {
    mqtt_msg_type_t type;
    union {
        mqtt_heartbeat_t heartbeat;
        mqtt_telemetry_t telemetry;
    } data;
} mqtt_queue_msg_t;

static void handle_mqtt_command(const char *data, int len);

static uint32_t get_uptime_seconds(void){
    return (uint32_t)(xTaskGetTickCount() / configTICK_RATE_HZ);
}

static void delay_ms(uint32_t ms){
    if (ms > 0U) {
        vTaskDelay(pdMS_TO_TICKS(ms));
    }
}

static void initialize_sntp(void){
    if (esp_sntp_enabled()) {
        return;
    }

    ESP_LOGI(TAG, "Initializing SNTP");
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, "pool.ntp.org");
    esp_sntp_init();
    esp_sntp_set_sync_interval(60000);
    setenv("TZ", "GMT+3", 1);
    tzset();
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data){
    if (event_base == WIFI_EVENT) {
        switch (event_id) {
        case WIFI_EVENT_STA_START:
            ESP_LOGI(TAG, "Wi-Fi station started");
            esp_wifi_connect();
            break;
        case WIFI_EVENT_STA_DISCONNECTED:
            s_wifi_connected = false;
            ESP_LOGW(TAG, "Wi-Fi disconnected, reconnecting");
            esp_wifi_connect();
            break;
        default:
            break;
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        s_wifi_connected = true;
        ESP_LOGI(TAG, "Wi-Fi connected, IP: " IPSTR, IP2STR(&event->ip_info.ip));
        initialize_sntp();
    }
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data){
    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        s_mqtt_connected = true;
        esp_mqtt_client_publish(s_mqtt_client, MQTT_STATUS_TOPIC, "{\"status\": \"online\"}", 0, 1, 1);
        esp_mqtt_client_subscribe(s_mqtt_client, MQTT_COMMAND_TOPIC, 1);
        ESP_LOGI(TAG, "MQTT connected");
        break;
    case MQTT_EVENT_DATA: {
        esp_mqtt_event_handle_t evt = event_data;
        ESP_LOGI(TAG, "MQTT_EVENT_DATA topic=%.*s data=%.*s", evt->topic_len, evt->topic, evt->data_len, evt->data);
        handle_mqtt_command(evt->data, evt->data_len);
        break;
    }
    case MQTT_EVENT_DISCONNECTED:
        s_mqtt_connected = false;
        ESP_LOGW(TAG, "MQTT disconnected");
        break;
    case MQTT_EVENT_ERROR:
        s_mqtt_connected = false;
        ESP_LOGE(TAG, "MQTT event error");
        break;
    default:
        break;
    }
}

static float read_temperature_c(void){
    return (float)(int)((20.0f + ((float)(esp_random() % 100) / 10.0f)) * 100.0f) / 100.0f;
}

static float read_humidity_pct(void){
    return (float)(int)((40.0f + ((float)(esp_random() % 200) / 10.0f)) * 100.0f) / 100.0f;
}

static void heartbeat_task(void *arg){
    const char *task_name = pcTaskGetName(NULL);
    mqtt_queue_msg_t heartbeat_msg = {0};
    wifi_ap_record_t ap_info = {0};
    heartbeat_msg.type = MQTT_MSG_HEARTBEAT;

    while (1) {
        /* Feed task watchdog for this task */
        esp_task_wdt_reset();
        heartbeat_msg.data.heartbeat.uptime = get_uptime_seconds();
        heartbeat_msg.data.heartbeat.free_heap = esp_get_free_heap_size();
        esp_wifi_sta_get_ap_info(&ap_info);
        heartbeat_msg.data.heartbeat.wifi_rssi = ap_info.rssi;
        strncpy(heartbeat_msg.data.heartbeat.firmware, FIRMWARE_VERSION, sizeof(heartbeat_msg.data.heartbeat.firmware) - 1);

        if (xQueueSend(mqtt_queue, &heartbeat_msg, pdMS_TO_TICKS(1000)) != pdTRUE) {
            ESP_LOGW(task_name, "Failed to queue heartbeat message");
        } else {
            ESP_LOGI(task_name, "Queued heartbeat message");
        }

        delay_ms(HEARTBEAT_INTERVAL_MS);
    }
}

static void sensor_read_task(void *arg){
    const char *task_name = pcTaskGetName(NULL);

    mqtt_telemetry_t sensor_data = {0};
    mqtt_queue_msg_t sample = {0};
    sample.type = MQTT_MSG_TELEMETRY;

    time_t now = 0;
    struct tm timeinfo = {0};

    while (1) {
        /* Feed task watchdog for this task */
        esp_task_wdt_reset();
        sensor_data.temperature_c = read_temperature_c();
        sensor_data.humidity_pct = read_humidity_pct();
        
        time(&now);
        localtime_r(&now, &timeinfo);
        if (timeinfo.tm_year >= (2024 - 1900)) {
            sensor_data.timestamp = now;
        } else {
            sensor_data.timestamp = 0;
        }
        ESP_LOGI(task_name, "Read sensor sample: temp=%.2fC hum=%.2f%% timestamp=%ld",
                 sensor_data.temperature_c, sensor_data.humidity_pct, sensor_data.timestamp);
        sample.data.telemetry = sensor_data;
        if (xQueueSend(mqtt_queue, &sample, pdMS_TO_TICKS(1000)) != pdTRUE) {
            ESP_LOGW(task_name, "Failed to queue sensor sample");
        } else {
            ESP_LOGI(task_name, "Queued sensor sample");
        }

        delay_ms(s_sensor_read_interval_ms);
    }
}

static void handle_mqtt_command(const char *data, int len)
{
    if (data == NULL || len <= 0) {
        ESP_LOGW(TAG, "Empty MQTT command payload");
        return;
    }

    /* Parse JSON payload (not necessarily null-terminated) */
    char *buf = malloc(len + 1);
    if (!buf) {
        ESP_LOGE(TAG, "OOM allocating buffer for MQTT command");
        return;
    }
    memcpy(buf, data, len);
    buf[len] = '\0';

    cJSON *root = cJSON_Parse(buf);
    free(buf);
    if (root == NULL) {
        ESP_LOGW(TAG, "Invalid JSON command payload");
        return;
    }

    cJSON *cmd = cJSON_GetObjectItem(root, "command");
    if (!cJSON_IsString(cmd)) {
        ESP_LOGW(TAG, "Command missing or not a string");
        cJSON_Delete(root);
        return;
    }

    const char *command = cmd->valuestring;
    ESP_LOGI(TAG, "Received command: %s", command);

    if (strcmp(command, "restart") == 0) {
        esp_mqtt_client_publish(s_mqtt_client, MQTT_STATUS_TOPIC, "{\"status\": \"restarting\"}", 0, 1, 0);
        cJSON_Delete(root);
        ESP_LOGI(TAG, "Restarting system as requested by MQTT command");
        delay_ms(1000); // Allow time for the message to be sent
        esp_restart();
        return;
    }

    if (strcmp(command, "set_interval") == 0) {
        cJSON *val = cJSON_GetObjectItem(root, "value");
        if (cJSON_IsNumber(val) && val->valuedouble > 0) {
            uint32_t new_interval = (uint32_t)val->valuedouble;
            if (new_interval < 100) {
                ESP_LOGW(TAG, "Requested interval too small: %lu ms, ignoring", new_interval);
            } else {
                s_sensor_read_interval_ms = new_interval;
                ESP_LOGI(TAG, "Sensor read interval set to %lu ms", s_sensor_read_interval_ms);
                char ack[128];
                int n = snprintf(ack, sizeof(ack), "{\"status\": \"ok\", \"sensor_interval_ms\": %lu}", s_sensor_read_interval_ms);
                esp_mqtt_client_publish(s_mqtt_client, MQTT_STATUS_TOPIC, ack, n, 1, 0);
            }
        } else {
            ESP_LOGW(TAG, "set_interval missing valid numeric value");
        }
        cJSON_Delete(root);
        return;
    }

    if (strcmp(command, "sample_now") == 0) {
        mqtt_queue_msg_t sample_msg = {0};
        sample_msg.type = MQTT_MSG_TELEMETRY;
        mqtt_telemetry_t telemetry = {0};
        telemetry.temperature_c = read_temperature_c();
        telemetry.humidity_pct = read_humidity_pct();
        time_t now = 0;
        struct tm timeinfo = {0};
        time(&now);
        localtime_r(&now, &timeinfo);
        telemetry.timestamp = (timeinfo.tm_year >= (2024 - 1900)) ? now : 0;
        sample_msg.data.telemetry = telemetry;
        if (xQueueSend(mqtt_queue, &sample_msg, pdMS_TO_TICKS(1000)) != pdTRUE) {
            ESP_LOGW(TAG, "Failed to queue immediate sample");
        } else {
            ESP_LOGI(TAG, "Queued immediate sample as requested");
        }
        cJSON_Delete(root);
        return;
    }

    ESP_LOGW(TAG, "Unknown command: %s", command);
    cJSON_Delete(root);
}

static void publish_telemetry(mqtt_telemetry_t *telemetry){
    if (telemetry == NULL) {
        ESP_LOGE(TAG, "Telemetry data is NULL");
        return;
    }

    snprintf(mqtt_payload, MQTT_PAYLOAD_MAX_SIZE, "{\"schema\":\"1.0\", \"node_id\": \"%s\", \"timestamp\": %lu,\"type\": \"telemetry\",\"payload\": {\"temperature_c\": %.2f, \"humidity_pct\": %.2f}}",
             TAG, telemetry->timestamp, telemetry->temperature_c, telemetry->humidity_pct);

    int msg_id = esp_mqtt_client_publish(s_mqtt_client, MQTT_TELEMETRY_TOPIC, mqtt_payload, 0, 1, 0);
    ESP_LOGI(TAG, "Publishing telemetry message %d with payload: %s", msg_id, mqtt_payload);
    if (msg_id >= 0) {
        ESP_LOGI(TAG, "Published telemetry message with ID: %d", msg_id);
    } else {
        ESP_LOGE(TAG, "Failed to publish telemetry message");
    }
}

static void publish_heartbeat(mqtt_heartbeat_t *heartbeat){
    if (heartbeat == NULL) {
        ESP_LOGE(TAG, "Heartbeat data is NULL");
        return;
    }

    snprintf(mqtt_payload, MQTT_PAYLOAD_MAX_SIZE, "{\"node_id\": \"%s\", \"uptime\": %lu, \"free_heap\": %lu, \"wifi_rssi\": %d, \"firmware\": \"%s\"}",
             TAG, heartbeat->uptime, heartbeat->free_heap, heartbeat->wifi_rssi, heartbeat->firmware);

    int msg_id = esp_mqtt_client_publish(s_mqtt_client, MQTT_HEARTBEAT_TOPIC, mqtt_payload, 0, 1, 0);
    ESP_LOGI(TAG, "Publishing heartbeat message %d with payload: %s", msg_id, mqtt_payload);
    if (msg_id >= 0) {
        ESP_LOGI(TAG, "Published heartbeat message with ID: %d", msg_id);
    } else {
        ESP_LOGE(TAG, "Failed to publish heartbeat message");
    }
}

static void mqtt_task(void *arg){
    const char *task_name = pcTaskGetName(NULL);
    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = MQTT_BROKER_URI,
        .session = {
            .last_will = {
                .topic = MQTT_STATUS_TOPIC,
                .msg = "{\"status\": \"offline\"}",
                .qos = 1,
                .retain = 1,
            },
            .keepalive = 60,
        }
    };

    s_mqtt_client = esp_mqtt_client_init(&mqtt_cfg);
    if (s_mqtt_client == NULL) {
        ESP_LOGE(task_name, "Failed to initialize MQTT client");
        vTaskDelete(NULL);
    }

    ESP_LOGI(task_name, "Wait for Wi-Fi connection...");
    while (!s_wifi_connected) {
        delay_ms(1000);
    }

    esp_mqtt_client_register_event(s_mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt_client));

    mqtt_queue_msg_t mqtt_msg = {0};

    while (1) {
        /* Feed task watchdog for this task */
        esp_task_wdt_reset();
        if (!s_wifi_connected) {
            ESP_LOGW(task_name, "Wi-Fi not connected; waiting before publishing");
            delay_ms(5000);
            continue;
        }

        if (!s_mqtt_connected) {
            ESP_LOGW(task_name, "MQTT not connected; attempting reconnect");
            esp_mqtt_client_reconnect(s_mqtt_client);
            delay_ms(2000);
            continue;
        }

        if (xQueueReceive(mqtt_queue, &mqtt_msg, pdMS_TO_TICKS(5000))) {
            switch (mqtt_msg.type) {
            case MQTT_MSG_TELEMETRY:
                publish_telemetry(&mqtt_msg.data.telemetry);
                break;
            case MQTT_MSG_HEARTBEAT:
                publish_heartbeat(&mqtt_msg.data.heartbeat);
                break;
            default:
                ESP_LOGW(task_name, "Unknown MQTT message type: %d", mqtt_msg.type);
                break;
            }
        }
    }
}

void app_main(void){
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_t *sta_netif = esp_netif_create_default_wifi_sta();
    assert(sta_netif != NULL);

    wifi_init_config_t wifi_init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_init_cfg));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, WIFI_EVENT_STA_START, wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASSWORD,
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    mqtt_queue = xQueueCreate(MQTT_QUEUE_LENGTH, sizeof(mqtt_queue_msg_t));
    assert(mqtt_queue != NULL);

    esp_task_wdt_config_t wdt_config = {
        .timeout_ms = WATCHDOG_TIMEOUT_MS,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };

    esp_err_t wdt_ret = esp_task_wdt_init(&wdt_config);
    if (wdt_ret == ESP_OK) {
        ESP_LOGI(TAG, "Task WDT initialized (timeout %u ms)", wdt_config.timeout_ms);
    } else if (wdt_ret == ESP_ERR_INVALID_STATE) {
        ESP_LOGW(TAG, "Task WDT already initialized, attempting reconfigure to %u ms", wdt_config.timeout_ms);
        esp_err_t rc = esp_task_wdt_reconfigure(&wdt_config);
        if (rc == ESP_OK) {
            ESP_LOGI(TAG, "Task WDT reconfigured (timeout %u ms)", wdt_config.timeout_ms);
        } else {
            ESP_LOGW(TAG, "Failed to reconfigure Task WDT: %d", rc);
        }
    } else {
        ESP_LOGE(TAG, "Failed to init Task WDT: %d", wdt_ret);
    }

    TaskHandle_t heartbeat_handle = NULL;
    TaskHandle_t sensor_handle = NULL;
    TaskHandle_t mqtt_handle = NULL;

    xTaskCreatePinnedToCore(heartbeat_task, "heartbeat_task", 4096, NULL, 5, &heartbeat_handle, 0);
    xTaskCreatePinnedToCore(sensor_read_task, "sensor_task", 4096, NULL, 5, &sensor_handle, 0);
    xTaskCreatePinnedToCore(mqtt_task, "mqtt_task", 4096, NULL, 5, &mqtt_handle, 0);

    /* Register tasks with the task watchdog */
    if (heartbeat_handle) { ESP_ERROR_CHECK(esp_task_wdt_add(heartbeat_handle)); }
    if (sensor_handle) { ESP_ERROR_CHECK(esp_task_wdt_add(sensor_handle)); }
    if (mqtt_handle) { ESP_ERROR_CHECK(esp_task_wdt_add(mqtt_handle)); }
}
