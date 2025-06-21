import nacos
import time
import json
import logging
import os
import uuid
from typing import Dict, List, Optional, Any

# 配置常量
SERVER_ADDRESSES = "127.0.0.1:8848"
NAMESPACE = ""
SERVICE_NAME = "python-service"
LOG_FILE = "log/nacos_monitor.log"    # 日志文件
IP_INFO_DIR = "service_ips"       # 存储IP信息的目录
MAX_RETRY = 3                     # 最大重试次数
RETRY_DELAY = 5                   # 重试延迟(秒)

def ensure_ip_dir_exists():
    """确保IP信息目录存在"""
    if not os.path.exists(IP_INFO_DIR):
        try:
            os.makedirs(IP_INFO_DIR)
            logging.info(f"Created IP info directory: {IP_INFO_DIR}")
        except OSError as e:
            logging.error(f"Failed to create directory {IP_INFO_DIR}: {e}")
            raise

def get_service_filename(service_name: str) -> str:
    """获取服务对应的文件名"""
    safe_name = "".join(c if c.isalnum() else "_" for c in service_name)
    return os.path.join(IP_INFO_DIR, f"{safe_name}_ips.json")

def write_ips_to_file(service_name: str, instances: List[Dict]) -> None:
    """将健康的实例IP信息写入服务对应的文件"""
    healthy_instances = [
        {
            "ip": instance["ip"],
            "port": instance["port"],
            "weight": instance.get("weight", 1.0),
            "metadata": instance.get("metadata", {}),
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        for instance in instances if instance.get("healthy", False)
    ]
    
    filename = get_service_filename(service_name)
    
    try:
        # 原子写入模式，先写入临时文件再重命名
        temp_filename = f"{filename}.tmp"
        with open(temp_filename, 'w') as f:
            json.dump(healthy_instances, f, indent=2)
        
        # 替换原文件
        if os.path.exists(filename):
            os.remove(filename)
        os.rename(temp_filename, filename)
        
        logging.info(f"Successfully updated IP info for {service_name} to {filename}")
    except IOError as e:
        logging.error(f"Failed to write IP info for {service_name} to file {filename}: {e}")
        # 清理临时文件
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except:
                pass

def get_initial_instances(client: nacos.NacosClient, service_name: str) -> Optional[Dict]:
    try:
        instances = client.list_naming_instance(service_name)
        if not isinstance(instances, dict) or 'hosts' not in instances:
            logging.warning(f"Invalid initial instances data: {instances}")
            return None
        logging.info(f"Initial Service {service_name} Instances:")
        for instance in instances['hosts']:
            logging.info(
                f"IP: {instance['ip']}, "
                f"Port: {instance['port']}, "
                f"Weight: {instance.get('weight', 1.0)}, "
                f"Healthy: {instance['healthy']}"
            )
        write_ips_to_file(service_name, instances['hosts'])
        return instances
    except Exception as e:
        logging.error(f"Failed to get initial instances for {service_name}: {e}")
        return None

class NacosServiceMonitor:
    def __init__(self):
        self.client = None
        self.current_listener = None
        self.initialize_logging()
        ensure_ip_dir_exists()
    
    def initialize_logging(self):
        """初始化日志配置"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(LOG_FILE),
                logging.StreamHandler()
            ]
        )
    
    def connect_to_nacos(self) -> bool:
        """连接到Nacos服务器"""
        for attempt in range(MAX_RETRY):
            try:
                self.client = nacos.NacosClient(SERVER_ADDRESSES, namespace=NAMESPACE)
                logging.info("Successfully connected to Nacos server")
                return True
            except Exception as e:
                if attempt < MAX_RETRY - 1:
                    logging.warning(f"Connection attempt {attempt + 1} failed, retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logging.error(f"Failed to connect to Nacos after {MAX_RETRY} attempts: {e}")
                    return False
        return False
    
    def monitor_service(self, service_name: str):
        """监控指定服务"""
        if not self.connect_to_nacos():
            return

        while True:
             # 获取初始实例
            try:
                initial_instances = get_initial_instances(self.client, service_name)
                if initial_instances is None:
                    logging.error(f"Failed to get initial instances for {service_name}")
            except Exception as e:
                logging.error(f"Error getting initial instances: {e}")
            time.sleep(10)
def main():
    """主程序"""
    monitor = NacosServiceMonitor()
    monitor.monitor_service(SERVICE_NAME)

if __name__ == "__main__":
    main()