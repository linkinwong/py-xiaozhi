import json
import threading
import time
import os
import sys
from pathlib import Path
import pyaudio

from src.constants.constants import AudioConfig
from src.utils.config_manager import ConfigManager
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# 全局变量声明
rclpy = None
Node = None
QoSProfile = None
ReliabilityPolicy = None
HistoryPolicy = None
WakeUp = None

class RosWakeWordDetector:
    """ROS2唤醒词检测器"""
    
    def __init__(self):
        """初始化ROS2唤醒词检测器"""
        logger.info("初始化ROS2唤醒词检测器...")
        
        # 初始化状态变量
        self._running = False  # ROS检测器内部使用的私有变量
        self._paused = False
        self._detection_thread = None
        self.on_detected_callbacks = []  # 回调列表
        self.on_error = None
        self._last_wake_time = 0  # 上次唤醒时间
        self._wake_cooldown = 0.1  # 唤醒冷却时间（秒）
        self._callback_lock = threading.Lock()  # 回调锁
        self._last_wake_status = False  # 上次唤醒状态
        self._state_lock = threading.Lock()  # 状态锁
        
        # 设置唤醒词
        config = ConfigManager.get_instance()
        self.wake_words = config.get_config('WAKE_WORD_OPTIONS.WAKE_WORDS', ["哈利", "小牛"])
        self._wake_word_phrase = self.wake_words[0] if self.wake_words else "小牛"

        # 兼容性属性 - 让RosWakeWordDetector看起来像WakeWordDetector
        self.enabled = True 
        self.running = False    # 映射到_running公开的兼容性属性，让application.py能够与ROS检测器交互
        self.paused = False     # 映射到_paused
        self.stream = None      # 音频流引用
        self.external_stream = False  # 是否使用外部流

        # 设置环境变量
        system_lib_path = "/usr/lib/aarch64-linux-gnu"
        ros2_lib_path = "/opt/ros/humble/lib"
        current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
        os.environ['LD_LIBRARY_PATH'] = f"{system_lib_path}:{ros2_lib_path}:{current_ld_path}"
        logger.info(f"已设置 LD_LIBRARY_PATH: {os.environ['LD_LIBRARY_PATH']}")

        # 添加ROS2 Python路径
        ros2_python_path = "/opt/ros/humble/lib/python3.10/site-packages"
        if ros2_python_path not in sys.path:
            sys.path.append(ros2_python_path)
        logger.info("已添加 ROS2 Python 路径")

        # 初始化ROS2节点
        try:
            global rclpy, Node, QoSProfile, ReliabilityPolicy, HistoryPolicy, WakeUp
            import rclpy
            from rclpy.node import Node
            from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
            from bridge.msg import WakeUp
            logger.info("ROS2 Python库导入成功")
            
            rclpy.init()
            self.node = Node('wake_word_detector')
            logger.info("ROS2节点初始化成功")
            
            # 创建订阅
            self.wake_status_sub = self.node.create_subscription(
                WakeUp,
                '/audio/wake',
                self._wake_status_callback,
                QoSProfile(
                    reliability=ReliabilityPolicy.RELIABLE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10
                )
            )
            logger.info("唤醒状态消息订阅者创建成功")
            
        except ImportError as ie:
            logger.error(f"ROS2依赖导入失败: {ie}")
            self._running = False
            raise
        except Exception as e:
            logger.error(f"ROS2节点初始化失败: {e}")
            self._running = False
            raise

        logger.info("ROS2唤醒词检测器初始化完成")

    def _wake_status_callback(self, msg):
        """处理唤醒状态消息的回调函数"""
        if not self._running:
            logger.debug("检测器未运行，忽略消息")
            return
            
        # 任何msg.status=True的消息都触发回调，不再检查_last_wake_status
        if msg.status:
            # 可选：添加短暂去抖动逻辑，避免过于频繁触发
            current_time = time.time()
            if current_time - self._last_wake_time > 1.0:  # 1秒去抖动
                self._last_wake_time = current_time
                logger.info(f"触发唤醒回调，间隔={current_time - self._last_wake_time:.2f}秒")
                # 使用_trigger_callbacks代替直接调用_on_detected
                self._trigger_callbacks(self._wake_word_phrase, "")
        else:
            logger.debug("收到status=False的消息")

    def _trigger_callbacks(self, wake_word, wake_word_id):
        """触发所有注册的回调函数"""
        if not self.on_detected_callbacks:
            logger.warning("没有注册的回调函数")
            return

        logger.info(f"触发唤醒词回调: {wake_word}")
        for callback in self.on_detected_callbacks:
            try:
                callback(wake_word, wake_word_id)
            except Exception as e:
                logger.error(f"执行回调时出错: {e}")

    def start(self, audio_codec_or_stream=None, shared_stream=None):
        """启动检测
        
        Args:
            audio_codec_or_stream: 音频编解码器或音频流（向后兼容）
            shared_stream: 共享的音频流（新参数）
        """
        if not self.on_detected_callbacks:
            logger.warning("未注册回调函数，唤醒词检测将无效")
        
        try:
            logger.info("启动ROS2唤醒词检测...")
            self._running = True
            self._paused = False
            self._last_wake_time = 0
            self._last_wake_status = False
            
            # 更新兼容性属性
            self.running = True
            self.paused = False
            
            # 如果提供了共享流，使用它
            if shared_stream:
                self.stream = shared_stream
                self.external_stream = True
                logger.info("使用共享音频流")
            
            # 启动ROS2消息处理线程
            self._detection_thread = threading.Thread(
                target=self._ros_spin_loop,
                daemon=True,
                name="ROS2-Spin-Thread"
            )
            self._detection_thread.start()
            logger.info("ROS2唤醒词检测已启动")
            return True
        except Exception as e:
            logger.error(f"启动ROS2唤醒词检测失败: {e}")
            self._running = False
            self.running = False  # 兼容性属性
            if self.on_error:
                self.on_error(e)
            return False

    def _ros_spin_loop(self):
        """ROS2消息处理循环"""
        logger.info("启动ROS2消息处理循环")
        
        while self._running:
            try:
                # 不管是否暂停都处理消息，暂停状态下只是不触发回调
                if not rclpy.ok():
                    # 检查是否仍在运行，避免关闭时的重新初始化
                    if not self._running:
                        logger.debug("检测器已停止，退出消息循环")
                        break
                        
                    logger.warning("ROS2上下文已失效，尝试重新初始化...")
                    self._reinitialize_ros()
                    # 如果重新初始化后仍无效，添加较长延迟避免频繁尝试
                    if not rclpy.ok():
                        time.sleep(1.0)
                    continue
                
                # 减少超时时间，更频繁检查消息
                try:
                    rclpy.spin_once(self.node, timeout_sec=0.001)
                except Exception as e:
                    # 如果已停止，不记录错误
                    if not self._running:
                        break
                    logger.error(f"ROS2消息处理出错: {e}")
                    time.sleep(0.01)
                
                # 减少循环间隔，提高响应速度
                time.sleep(0.01)
            except Exception as e:
                if not self._running:  # 正常停止不记录错误
                    break
                logger.error(f"ROS2消息处理循环错误: {e}")
                time.sleep(0.1)
                if self.on_error and self._running:
                    self.on_error(e)
        
        logger.info("ROS2消息处理循环已停止")

    def stop(self):
        """停止检测"""
        try:
            if not self._running:
                return
            
            logger.info("停止ROS2唤醒词检测...")
            # 先设置停止标志，避免重新初始化
            self._running = False
            # 更新兼容性属性
            self.running = False
            self.paused = False
            
            # 等待线程结束
            if self._detection_thread and self._detection_thread.is_alive():
                try:
                    # 增加超时时间
                    self._detection_thread.join(timeout=3.0)
                    if self._detection_thread.is_alive():
                        logger.warning("检测线程未能在超时时间内结束")
                except Exception as e:
                    logger.error(f"等待检测线程结束时出错: {e}")
            
            # 清理ROS2资源
            try:
                if hasattr(self, 'node') and self.node:
                    if hasattr(self, 'wake_status_sub'):
                        try:
                            self.node.destroy_subscription(self.wake_status_sub)
                            self.wake_status_sub = None
                        except Exception as e:
                            logger.warning(f"销毁订阅失败: {e}")
                    try:
                        self.node.destroy_node()
                    except Exception as e:
                        logger.warning(f"销毁节点失败: {e}")
                    self.node = None
                
                # 关闭ROS2上下文
                if 'rclpy' in globals() and hasattr(rclpy, 'ok') and rclpy.ok():
                    try:
                        rclpy.shutdown()
                    except Exception as e:
                        logger.warning(f"关闭ROS2上下文失败: {e}")
            except Exception as e:
                logger.error(f"清理ROS2资源时出错: {e}")
            
            logger.info("ROS2唤醒词检测已停止")
        except Exception as e:
            logger.error(f"停止ROS2唤醒词检测时出错: {e}")

    def pause(self):
        """暂停检测"""
        with self._state_lock:
            self._paused = True
            self.paused = True  # 兼容性属性
            logger.info("ROS2唤醒词检测已暂停")

    def resume(self):
        """恢复检测"""
        with self._state_lock:
            self._paused = False
            self.paused = False  # 兼容性属性
            logger.info("ROS2唤醒词检测已恢复")

    def on_detected(self, callback):
        """注册唤醒词检测回调"""
        with self._callback_lock:
            self.on_detected_callbacks.append(callback)
            logger.info("已注册唤醒词检测回调")

    def is_running(self):
        """检查是否正在运行"""
        with self._state_lock:
            return self._running

    def _reinitialize_ros(self):
        """重新初始化ROS2节点"""
        logger.info("尝试重新初始化ROS2节点...")
        try:
            # 清理现有资源
            if hasattr(self, 'node') and self.node:
                if hasattr(self, 'wake_status_sub'):
                    try:
                        self.node.destroy_subscription(self.wake_status_sub)
                        self.wake_status_sub = None
                    except Exception as e:
                        logger.warning(f"销毁订阅失败: {e}")
                try:
                    self.node.destroy_node()
                except Exception as e:
                    logger.warning(f"销毁节点失败: {e}")
                self.node = None

            # 重新初始化ROS2
            if 'rclpy' in globals():
                try:
                    rclpy.shutdown()
                except Exception as e:
                    logger.warning(f"关闭ROS2上下文失败: {e}")

            # 重新初始化
            rclpy.init()
            self.node = Node('wake_word_detector')
            
            # 重新创建订阅
            self.wake_status_sub = self.node.create_subscription(
                WakeUp,
                '/audio/wake',
                self._wake_status_callback,
                QoSProfile(
                    reliability=ReliabilityPolicy.RELIABLE,
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10
                )
            )
            logger.info("ROS2节点重新初始化成功")
        except Exception as e:
            logger.error(f"重新初始化ROS2节点失败: {e}")
            raise

    def __del__(self):
        """析构函数"""
        self.stop()

    def is_paused(self):
        """检查是否已暂停"""
        with self._state_lock:
            return self._paused