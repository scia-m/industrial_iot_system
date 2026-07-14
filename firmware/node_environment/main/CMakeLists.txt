idf_component_register(SRCS "node_environment.c"
                    INCLUDE_DIRS "."
                    REQUIRES mqtt esp_wifi esp_netif nvs_flash)
