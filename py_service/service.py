import nacos
import time

SERVER_ADDRESSES = "127.0.0.1:8848"
NAMESPACE = ""
SERVICE_NAME = "python-service"
IP = "127.0.0.1"
PORT = 4000

client = nacos.NacosClient(SERVER_ADDRESSES, namespace=NAMESPACE)

client.add_naming_instance(
    service_name=SERVICE_NAME,
    ip=IP,
    port=PORT,
    metadata={"version": "1.0"},
    heartbeat_interval=5,
    healthy=True,
    ephemeral=True
)

print(f"Service {SERVICE_NAME} Redistered Success at {IP}:{PORT}")

try:
    while True:
        time.sleep(10)
except KeyboardInterrupt:
    client.remove_naming_instance(SERVICE_NAME, IP, PORT)
    print(f"Service {SERVICE_NAME} Destroy")
