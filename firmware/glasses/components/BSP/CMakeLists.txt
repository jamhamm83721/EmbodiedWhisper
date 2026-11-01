set(src_dirs
            LED
            USART
            KEY
            IIC
            WIFI
            Camera)

set(include_dirs
            LED
            USART
            KEY
            IIC
            WIFI
            Camera)

set(requires
            driver
            esp_wifi
            esp_event
            esp_netif
            esp32-camera)

idf_component_register(SRC_DIRS ${src_dirs} INCLUDE_DIRS ${include_dirs} REQUIRES ${requires})

component_compile_options(-ffast-math -O3 -Wno-error=format=-Wno-format)
