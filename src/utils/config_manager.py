import json
import logging
import time
from pathlib import Path
from typing import Dict, Any
import threading
import requests
import socket
import uuid
import sys

from src.utils.logging_config import get_logger
logger = get_logger(__name__)


class ConfigManager:
    """配置管理器 - 单例模式"""

    _instance = None
    _lock = threading.Lock()

    # 配置文件路径
    CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    # 记录配置文件路径
    logger.info(f"配置目录: {CONFIG_DIR.absolute()}")
    logger.info(f"配置文件: {CONFIG_FILE.absolute()}")

    # 默认配置
    DEFAULT_CONFIG = {
        "SYSTEM_OPTIONS": {
            "CLIENT_ID": None,
            "DEVICE_ID": None,
            "NETWORK": {
                "OTA_VERSION_URL": "https://api.tenclass.net/xiaozhi/ota/",
                "WEBSOCKET_URL": None,
                "WEBSOCKET_ACCESS_TOKEN": None,
                "MQTT_INFO": None,
                "ACTIVATION_VERSION": "v2",  # 可选值: v1, v2
                "AUTHORIZATION_URL": "https://xiaozhi.me/"
            },
        },
        "WAKE_WORD_OPTIONS": {
            "USE_WAKE_WORD": False,
            "MODEL_PATH": "models/vosk-model-small-cn-0.22",
            "WAKE_WORDS": [
                "小牛",
                "小美"
            ]
        },
        "TEMPERATURE_SENSOR_MQTT_INFO": {
            "endpoint": "你的Mqtt连接地址",
            "port": 1883,
            "username": "admin",
            "password": "123456",
            "publish_topic": "sensors/temperature/command",
            "subscribe_topic": "sensors/temperature/device_001/state"
        },
        "CAMERA": {
            "camera_index": 0,
            "frame_width": 640,
            "frame_height": 480,
            "fps": 30,
            "Loacl_VL_url": "https://open.bigmodel.cn/api/paas/v4/",
            "VLapi_key": "你自己的key",
            "models": "glm-4v-plus"
        }
    }

    def __new__(cls):
        """确保单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化配置管理器"""
        self.logger = logger
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        # 加载配置
        self._config = self._load_config()
        self._initialize_client_id()
        self._initialize_device_id()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件，如果不存在则创建"""
        try:
            # 先尝试从当前工作目录加载
            config_file = Path("config/config.json")
            if config_file.exists():
                config = json.loads(config_file.read_text(encoding='utf-8'))
                return self._merge_configs(self.DEFAULT_CONFIG, config)

            # 再尝试从打包目录加载
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                config_file = Path(sys._MEIPASS) / "config" / "config.json"
                if config_file.exists():
                    config = json.loads(
                        config_file.read_text(encoding='utf-8')
                    )
                    return self._merge_configs(self.DEFAULT_CONFIG, config)

            # 最后尝试从开发环境目录加载
            if self.CONFIG_FILE.exists():
                config = json.loads(
                    self.CONFIG_FILE.read_text(encoding='utf-8')
                )
                return self._merge_configs(self.DEFAULT_CONFIG, config)
            else:
                # 创建默认配置
                self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                self._save_config(self.DEFAULT_CONFIG)
                return self.DEFAULT_CONFIG.copy()
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return self.DEFAULT_CONFIG.copy()

    def _save_config(self, config: dict) -> bool:
        """保存配置到文件"""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self.CONFIG_FILE.write_text(
                json.dumps(config, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            return True
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False

    @staticmethod
    def _merge_configs(default: dict, custom: dict) -> dict:
        """递归合并配置字典"""
        result = default.copy()
        for key, value in custom.items():
            if (key in result and isinstance(result[key], dict)
                    and isinstance(value, dict)):
                result[key] = ConfigManager._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def get_config(self, path: str, default: Any = None) -> Any:
        """
        通过路径获取配置值
        path: 点分隔的配置路径，如 "network.mqtt.host"
        """
        try:
            value = self._config
            for key in path.split('.'):
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def update_config(self, path: str, value: Any) -> bool:
        """
        更新特定配置项
        path: 点分隔的配置路径，如 "network.mqtt.host"
        """
        try:
            current = self._config
            *parts, last = path.split('.')
            for part in parts:
                current = current.setdefault(part, {})
            current[last] = value
            return self._save_config(self._config)
        except Exception as e:
            logger.error(f"Error updating config {path}: {e}")
            return False

    @classmethod
    def get_instance(cls):
        """获取配置管理器实例（线程安全）"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def generate_uuid(self) -> str:
        """
        生成 UUID v4
        """
        return str(uuid.uuid4())

    def get_local_ip(self):
        try:
            # 创建一个临时 socket 连接来获取本机 IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            logger.error(f"获取本地IP失败: {e}")
            return "127.0.0.1"

    def _initialize_client_id(self):
        """初始化客户端ID"""
        client_id = self.get_config("SYSTEM_OPTIONS.CLIENT_ID")
        if not client_id:
            client_id = self.generate_uuid()
            self.update_config("SYSTEM_OPTIONS.CLIENT_ID", client_id)
            logger.info(f"已生成新的客户端ID: {client_id}")

    def _initialize_device_id(self):
        """初始化设备ID"""
        device_id = self.get_config("SYSTEM_OPTIONS.DEVICE_ID")
        if not device_id:
            device_id = self.generate_uuid()
            self.update_config("SYSTEM_OPTIONS.DEVICE_ID", device_id)
            logger.info(f"已生成新的设备ID: {device_id}")

    def get_app_path(self) -> Path:
        """获取应用程序路径"""
        if getattr(sys, 'frozen', False):
            return Path(sys.executable).parent
            return Path(__file__).parent.parent.parent