import os
import sys
import signal
import logging
from pathlib import Path
import time
import yaml
import nacos
from daemonize import Daemonize
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('./log/nacos_config_daemon.log')] 
)
logger = logging.getLogger(__name__)

class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, daemon):
        self.daemon = daemon
    
    def on_modified(self, event):
        if event.src_path == self.daemon.config_file:
            logger.info(f"Detected config file modification: {event.src_path}")
            try:
                self.daemon.reload_config()
            except Exception as e:
                logger.error(f"Failed to reload config: {str(e)}")

class NacosConfigDaemon:
    def __init__(self, config_file):
        self.config_file = config_file
        self.config = None
        self.client = None
        self.running = True
        self.watchers = {}  # Track active watchers
        self.observer = None  # For config file monitoring
        self.load_config()
        
    def load_config(self):
        with open(self.config_file, 'r') as f:
            new_config = yaml.safe_load(f)
        
        # If this is the first load or if config changed significantly
        if not self.config or self.config.get('nacos') != new_config.get('nacos'):
            self.config = new_config
            self.init_nacos_client()
        else:
            # Only update config mapping if nacos settings didn't change
            self.config['config_mapping'] = new_config['config_mapping']
        logger.info("Configuration reloaded successfully")
    
    def reload_config(self):
        """Reload configuration and update watchers as needed"""
        old_mapping = self.config['config_mapping'].copy() if self.config else {}
        self.load_config()
        
        # Remove watchers for configs that no longer exist
        for data_id in list(self.watchers.keys()):
            if data_id not in self.config['config_mapping']:
                logger.info(f"Removing watcher for {data_id} as it's no longer in config")
                del self.watchers[data_id]
        
        # Add/update watchers for current configs
        for data_id, mapping in self.config['config_mapping'].items():
            group = mapping.get('group', 'DEFAULT_GROUP')
            
            # If new config or changed group
            if data_id not in old_mapping or old_mapping[data_id].get('group') != group:
                if data_id in self.watchers:
                    # Remove old watcher if group changed
                    del self.watchers[data_id]
                
                # Add new watcher
                logger.info(f"Adding watcher for {data_id} (group: {group})")
                self.watchers[data_id] = {
                    'group': group,
                    'callback': lambda *args, **kwargs: self.config_change_callback(*args, **kwargs)
                }
                self.client.add_config_watcher(data_id, group, self.watchers[data_id]['callback'])
                
                # Fetch and write initial config
                try:
                    config = self.client.get_config(data_id, group)
                    if config:
                        self.write_config_to_file(data_id, group, config)
                except Exception as e:
                    logger.error(f"Failed to get initial config for {data_id}: {str(e)}")
    
    def init_nacos_client(self):
        if self.client:
            # Clean up old client if it exists
            pass
            
        server_addresses = self.config['nacos']['server_addresses']
        namespace = self.config['nacos'].get('namespace')
        username = self.config['nacos'].get('username')
        password = self.config['nacos'].get('password')
        
        self.client = nacos.NacosClient(
            server_addresses=server_addresses,
            namespace=namespace,
            username=username,
            password=password
        )
    
    def write_config_to_file(self, data_id, group, content):
        logger.info(f"Processing config update for: {data_id}")
        config_mapping = self.config['config_mapping']
        if data_id not in config_mapping:
            logger.warning(f"Received unregistered config: {data_id}")
            return
            
        file_path = config_mapping[data_id]['file_path']
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w') as f:
                f.write(content)
            os.chmod(file_path, config_mapping[data_id].get('file_mode', 0o644))
            logger.info(f"Successfully wrote config {data_id} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to write config {data_id} to {file_path}: {str(e)}")
    
    def config_change_callback(self, *args, **kwargs):
        data_id = args[0]["data_id"]
        group = args[0]["group"]
        content = args[0]["content"]
        logger.info(f"Config update received for {data_id}")
        self.write_config_to_file(data_id, group, content)

    def setup_config_watcher(self):
        """Set up watchers for all configured configs"""
        for data_id, mapping in self.config['config_mapping'].items():
            group = mapping.get('group', 'DEFAULT_GROUP')
            logger.info(f"Registering config watcher for {data_id} (group: {group})")
            # Store watcher reference
            self.watchers[data_id] = {
                'group': group,
                'callback': lambda *args, **kwargs: self.config_change_callback(*args, **kwargs)
            }
            try:
                # Get initial config
                config = self.client.get_config(data_id, group)
                logger.debug(f"Initial config for {data_id}: {config}")
                if config:
                    self.write_config_to_file(data_id, group, config)
                
                # Add watcher
                self.client.add_config_watcher(data_id, group, self.watchers[data_id]['callback'])
            except Exception as e:
                logger.error(f"Failed to initialize config for {data_id}: {str(e)}")
    
    def start_config_file_monitor(self):
        """Start monitoring the config file for changes"""
        self.observer = Observer()
        event_handler = ConfigFileHandler(self)
        self.observer.schedule(event_handler, path=str(Path(self.config_file).parent), recursive=False)
        self.observer.start()
        logger.info(f"Started monitoring config file: {self.config_file}")
    
    def run(self):
        self.init_nacos_client()
        self.setup_config_watcher()
        self.start_config_file_monitor()
        
        logger.info("Nacos Config Daemon started successfully")
        try:
            while self.running:
                time.sleep(1)
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        if self.observer:
            self.observer.stop()
            self.observer.join()
        logger.info("Cleanup complete")
    
    def stop(self, signum, frame):
        logger.info("Received signal to stop")
        self.running = False

def main():
    if len(sys.argv) != 2:
        print("Usage: nacos_config_daemon.py <config_file>")
        sys.exit(1)
    
    config_file = os.path.abspath(sys.argv[1])
    daemon = NacosConfigDaemon(config_file)
    # for test
    daemon.run()
    # Set up signal handlers
    signal.signal(signal.SIGTERM, daemon.stop)
    signal.signal(signal.SIGINT, daemon.stop)
    
    # Set up logging file descriptors for daemonization
    keep_fds = [
        logging.root.handlers[0].stream.fileno(),
        logging.root.handlers[1].stream.fileno()
    ]
    
    # Daemonize
    # daemonize = Daemonize(
    #     app="nacos_config_daemon",
    #     pid="/tmp/nacos_config_daemon.pid",
    #     action=daemon.run,
    #     keep_fds=keep_fds,
    #     chdir=os.path.dirname(os.path.abspath(__file__)))
    # daemonize.start()

if __name__ == "__main__":
    main()