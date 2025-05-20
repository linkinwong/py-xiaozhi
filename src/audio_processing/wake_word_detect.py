import json
import threading
import time
import os
import sys
from pathlib import Path
from vosk import Model, KaldiRecognizer, SetLogLevel
from pypinyin import lazy_pinyin
import pyaudio

from src.constants.constants import AudioConfig
from src.utils.config_manager import ConfigManager
from src.utils.logging_config import get_logger

logger = get_logger(__name__)



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
            import rclpy
            from rclpy.node import Node
            from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
            from bridge.msg import WakeUp
            logger.info("ROS2 Python库导入成功")
            
            global rclpy, Node, QoSProfile, ReliabilityPolicy, HistoryPolicy, Bool, WakeUp
            
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

    def start(self, audio_codec_or_stream=None):
        """启动检测"""
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
                        logger.info("ROS2上下文已关闭")
                    except Exception as e:
                        logger.warning(f"关闭ROS2上下文时出错: {e}")
            except Exception as e:
                logger.warning(f"清理ROS2资源时出错: {e}")
            
            logger.info("ROS2唤醒词检测已停止")
        except Exception as e:
            logger.error(f"停止检测时出错: {e}")

    def pause(self):
        """暂停检测器但不停止ROS2监听"""
        if self._running:
            self._paused = True

    def resume(self):
        """恢复检测器并重置状态记忆，确保可以立即响应新事件"""
        if self._running:
            self._paused = False
            # 主动重置状态以确保能够响应新的唤醒事件
            self._last_wake_status = False

    def on_detected(self, callback):
        """注册唤醒词检测回调"""
        self.on_detected_callbacks.append(callback)
        logger.info(f"已注册唤醒词检测回调，当前回调数量: {len(self.on_detected_callbacks)}")

    def is_running(self):
        """检查唤醒词检测是否正在运行"""
        with self._state_lock:
            # 同时更新兼容性属性
            self.running = self._running and not self._paused
            return self._running and not self._paused

    def _reinitialize_ros(self):
        """重新初始化ROS2节点和订阅"""
        try:
            # 先检查是否正在运行，如果不在运行则不尝试重新初始化
            if not self._running:
                logger.debug("检测器已停止，不再重新初始化ROS2")
                return
                
            # 先关闭现有资源
            if hasattr(self, 'node') and self.node:
                if hasattr(self, 'wake_status_sub'):
                    try:
                        self.node.destroy_subscription(self.wake_status_sub)
                    except Exception as e:
                        logger.warning(f"销毁订阅失败: {e}")
                try:
                    self.node.destroy_node()
                except Exception as e:
                    logger.warning(f"销毁节点失败: {e}")
                self.node = None
            
            # 确保ROS2上下文关闭，但仅在尚未关闭时
            if 'rclpy' in globals() and hasattr(rclpy, 'ok') and rclpy.ok():
                try:
                    rclpy.shutdown()
                    logger.debug("ROS2上下文已关闭，准备重新初始化")
                except Exception as e:
                    logger.warning(f"关闭ROS2上下文失败: {e}")
            
            # 添加短暂延迟以确保资源正确释放
            time.sleep(0.5)
            
            # 如果已停止，不再重新初始化
            if not self._running:
                logger.debug("检测器已停止，取消重新初始化")
                return
                
            # 重新初始化
            try:
                rclpy.init()
                self.node = rclpy.create_node('wake_word_detector')
                
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
                if self.on_error and self._running:
                    self.on_error(e)
        except Exception as e:
            logger.error(f"重新初始化ROS2节点失败: {e}")
            if self.on_error and self._running:
                self.on_error(e)

    def __del__(self):
        """析构函数"""
        logger.info("销毁ROS2唤醒词检测器...")
        self.stop()

    def is_paused(self):
        """检查唤醒词检测是否暂停"""
        with self._state_lock:
            # 同时更新兼容性属性
            self.paused = self._paused
            return self._paused


class WakeWordDetector:
    """唤醒词检测类（集成AudioCodec优化版）"""

    def __init__(self, 
                 sample_rate=AudioConfig.INPUT_SAMPLE_RATE,
                 buffer_size=AudioConfig.INPUT_FRAME_SIZE,
                 audio_codec=None):
        """
        初始化唤醒词检测器
        
        参数:
            audio_codec: AudioCodec实例（新增）
            sample_rate: 音频采样率
            buffer_size: 音频缓冲区大小
        """
        # 初始化音频编解码器引用
        self.audio_codec = audio_codec
        
        # 初始化基本属性
        self.on_detected_callbacks = []
        self.running = False
        self.detection_thread = None
        self.paused = False
        self.audio = None
        self.stream = None
        self.external_stream = False
        self.stream_lock = threading.Lock()
        self.on_error = None

        # 配置检查
        config = ConfigManager.get_instance()
        if not config.get_config('WAKE_WORD_OPTIONS.USE_WAKE_WORD', False):
            logger.info("唤醒词功能已禁用")
            self.enabled = False
            return

        # 基本参数初始化
        self.enabled = True
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.sensitivity = config.get_config("WAKE_WORD_OPTIONS.SENSITIVITY", 0.5)

        # 唤醒词配置
        self.wake_words = config.get_config('WAKE_WORD_OPTIONS.WAKE_WORDS', [
            "哈利", "小牛"
        ])
        self.wake_words_pinyin = [''.join(lazy_pinyin(word)) for word in self.wake_words]

        # 模型初始化
        try:
            model_path = self._get_model_path(config)
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"模型路径不存在: {model_path}")

            logger.info(f"加载语音识别模型: {model_path}")
            SetLogLevel(-1)
            self.model = Model(model_path=model_path)
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
            logger.info("模型加载完成")

            # 调试日志
            logger.info(f"已配置 {len(self.wake_words)} 个唤醒词")
            for idx, (word, pinyin) in enumerate(zip(self.wake_words, self.wake_words_pinyin)):
                logger.debug(f"唤醒词 {idx+1}: {word.ljust(8)} => {pinyin}")
                
        except Exception as e:
            logger.error(f"初始化失败: {e}", exc_info=True)
            self.enabled = False

    def _get_model_path(self, config):
        """获取模型路径（更智能的路径查找）"""
        # 直接从配置中获取模型名称或路径
        model_name = config.get_config(
            'WAKE_WORD_OPTIONS.MODEL_PATH', 
            'vosk-model-small-cn-0.22'
        )
        
        # 转换为Path对象
        model_path = Path(model_name)
        
        # 如果只有模型名称（没有父目录），则标准化为models子目录下的路径
        if len(model_path.parts) == 1:
            model_path = Path('models') / model_path
        
        # 可能的基准路径
        possible_base_dirs = [
            Path(__file__).parent.parent.parent,  # 项目根目录
            Path.cwd(),  # 当前工作目录
        ]
        
        # 如果是打包后的环境，增加更多可能的基准路径
        if getattr(sys, 'frozen', False):
            # 可执行文件所在目录
            exe_dir = Path(sys.executable).parent
            possible_base_dirs.append(exe_dir)
            
            # PyInstaller的_MEIPASS路径(如果存在)
            if hasattr(sys, '_MEIPASS'):
                meipass_dir = Path(sys._MEIPASS)
                possible_base_dirs.append(meipass_dir)
                # 增加_MEIPASS的父目录(可能是应用根目录)
                possible_base_dirs.append(meipass_dir.parent)
                
            # 增加可执行文件父目录(处理某些安装情况)
            possible_base_dirs.append(exe_dir.parent)
            
            logger.debug(f"可执行文件目录: {exe_dir}")
            if hasattr(sys, '_MEIPASS'):
                logger.debug(f"PyInstaller临时目录: {meipass_dir}")
        
        # 查找模型文件
        model_file_path = None
        
        # 遍历所有可能的基准路径
        for base_dir in filter(None, possible_base_dirs):
            # 1. 尝试标准的models目录下的模型
            path_to_check = base_dir / model_path
            if path_to_check.exists():
                model_file_path = path_to_check
                logger.info(f"找到模型文件: {model_file_path}")
                break
                
            # 2. 尝试直接使用模型名称(不包含models前缀)
            if len(model_path.parts) > 1 and model_path.parts[0] == 'models':
                # 去掉models前缀
                alt_path = base_dir / Path(*model_path.parts[1:])
                if alt_path.exists():
                    model_file_path = alt_path
                    logger.info(f"在替代位置找到模型: {model_file_path}")
                    break
        
        # 如果仍未找到，尝试一些特殊位置
        if model_file_path is None and getattr(sys, 'frozen', False):
            # 1. 检查与可执行文件同级的特定目录
            special_paths = [
                # PyInstaller 6.0.0+ 的_internal目录
                Path(sys.executable).parent / "_internal" / model_path,
                # 与可执行文件同级的models目录
                Path(sys.executable).parent / "models" / model_path.name,
                # 可执行文件同级直接放置模型
                Path(sys.executable).parent / model_path.name
            ]
            
            for path in special_paths:
                if path.exists():
                    model_file_path = path
                    logger.info(f"在特殊位置找到模型: {model_file_path}")
                    break
        
        # 如果找不到任何位置，使用配置的原始路径
        if model_file_path is None:
            # 如果是绝对路径直接使用
            if model_path.is_absolute():
                model_file_path = model_path
            else:
                # 否则使用项目根目录+相对路径
                model_file_path = Path(__file__).parent.parent.parent / model_path
                
            logger.warning(f"未找到模型，将使用默认路径: {model_file_path}")
        
        # 转换为字符串返回
        model_path_str = str(model_file_path)
        logger.debug(f"最终模型路径: {model_path_str}")
        return model_path_str

    def start(self, audio_codec_or_stream=None):
        logger.info("启动唤醒词检测")
        """启动检测（支持音频编解码器或直接流传入）"""
        if not self.enabled:
            logger.warning("唤醒词功能未启用")
            return False

        logger.info("唤醒词功能已启用")
        # 检查参数类型，区分音频编解码器和流对象
        if audio_codec_or_stream:
            # 检查是否是流对象
            if hasattr(audio_codec_or_stream, 'read') and hasattr(audio_codec_or_stream, 'is_active'):
                # 是流对象，使用直接流模式
                self.stream = audio_codec_or_stream
                self.external_stream = True
                return self._start_with_external_stream()
            else:
                # 是AudioCodec对象，使用AudioCodec模式
                self.audio_codec = audio_codec_or_stream

        # 优先使用audio_codec的流
        if self.audio_codec:
            return self._start_with_audio_codec()
        else:
            return self._start_standalone()

    def _start_with_audio_codec(self):
        """使用AudioCodec的输入流（直接访问）"""
        try:
            # 直接访问input_stream属性
            if not self.audio_codec or not self.audio_codec.input_stream:
                logger.error("音频编解码器无效或输入流不可用")
                return False

            # 直接使用AudioCodec的输入流
            self.stream = self.audio_codec.input_stream
            self.external_stream = True  # 标记为外部流，避免错误关闭

            # 配置流参数
            self.sample_rate = AudioConfig.INPUT_SAMPLE_RATE
            self.buffer_size = AudioConfig.INPUT_FRAME_SIZE

            # 启动检测线程
            self.running = True
            self.paused = False
            self.detection_thread = threading.Thread(
                target=self._audio_codec_detection_loop,
                daemon=True,
                name="WakeWordDetector-AudioCodec"
            )
            self.detection_thread.start()

            logger.info("唤醒词检测已启动（直接使用AudioCodec输入流）")
            return True
        except Exception as e:
            logger.error(f"通过AudioCodec启动失败: {e}")
            return False

    def _start_standalone(self):
        """独立音频模式"""
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=AudioConfig.CHANNELS,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.buffer_size
            )

            self.running = True
            self.paused = False
            self.detection_thread = threading.Thread(
                target=self._detection_loop,
                daemon=True,
                name="WakeWordDetector-Standalone"
            )
            self.detection_thread.start()

            logger.info("唤醒词检测已启动（独立音频模式）")
            return True
        except Exception as e:
            logger.error(f"独立模式启动失败: {e}")
            return False

    def _start_with_external_stream(self):
        """使用外部提供的音频流"""
        try:
            # 设置参数
            self.sample_rate = AudioConfig.INPUT_SAMPLE_RATE
            self.buffer_size = AudioConfig.INPUT_FRAME_SIZE
            
            # 启动检测线程
            self.running = True
            self.paused = False
            self.detection_thread = threading.Thread(
                target=self._detection_loop,
                daemon=True,
                name="WakeWordDetector-ExternalStream"
            )
            self.detection_thread.start()
            
            logger.info("唤醒词检测已启动（使用外部音频流）")
            return True
        except Exception as e:
            logger.error(f"使用外部流启动失败: {e}")
            return False

    def _audio_codec_detection_loop(self):
        """AudioCodec专用检测循环（优化直接访问）"""
        logger.info("进入AudioCodec检测循环")
        error_count = 0
        MAX_ERRORS = 5
        STREAM_TIMEOUT = 3.0  # 流等待超时时间

        while self.running:
            try:
                if self.paused:
                    time.sleep(0.1)
                    continue

                # 直接访问AudioCodec的输入流
                if not self.audio_codec or not hasattr(self.audio_codec, 'input_stream'):
                    logger.warning("AudioCodec不可用，等待中...")
                    time.sleep(STREAM_TIMEOUT)
                    continue
                    
                # 直接使用当前流引用
                stream = self.audio_codec.input_stream
                if not stream or not stream.is_active():
                    logger.debug("AudioCodec输入流不活跃，等待恢复...")
                    try:
                        # 尝试重新激活或等待AudioCodec恢复流
                        if stream and hasattr(stream, 'start_stream'):
                            stream.start_stream()
                        else:
                            time.sleep(0.5)
                            continue
                    except Exception as e:
                        logger.warning(f"激活流失败: {e}")
                        time.sleep(0.5)
                        continue

                # 读取音频数据
                data = self._read_audio_data_direct(stream)
                if not data:
                    continue

                # 处理数据
                self._process_audio_data(data)
                error_count = 0  # 重置错误计数

            except Exception as e:
                error_count += 1
                logger.error(f"检测循环错误({error_count}/{MAX_ERRORS}): {str(e)}")
                
                if error_count >= MAX_ERRORS:
                    logger.critical("达到最大错误次数，停止检测")
                    self.stop()
                time.sleep(0.5)

    def _read_audio_data_direct(self, stream):
        """直接从流读取数据（简化版）"""
        try:
            with self.stream_lock:
                # 检查可用数据
                if hasattr(stream, 'get_read_available'):
                    available = stream.get_read_available()
                    if available < self.buffer_size:
                        return None

                # 精确读取
                return stream.read(self.buffer_size, exception_on_overflow=False)
        except OSError as e:
            error_msg = str(e)
            logger.warning(f"音频流错误: {error_msg}")
            
            # 关键错误处理
            critical_errors = ["Input overflowed", "Device unavailable"]
            if any(msg in error_msg for msg in critical_errors) and self.audio_codec:
                logger.info("触发音频流重置...")
                try:
                    # 直接调用AudioCodec的重置方法
                    self.audio_codec._reinitialize_input_stream()
                except Exception as re:
                    logger.error(f"流重置失败: {re}")
                    
            time.sleep(0.5)
            return None
        except Exception as e:
            logger.error(f"读取音频数据异常: {e}")
            return None

    def _detection_loop(self):
        """标准检测循环（用于外部流或独立模式）"""
        logger.info("进入标准检测循环")
        error_count = 0
        MAX_ERRORS = 5

        while self.running:
            try:
                if self.paused:
                    time.sleep(0.1)
                    continue

                # 读取音频数据（带锁保护）
                try:
                    with self.stream_lock:
                        if not self.stream:
                            logger.warning("音频流不可用")
                            time.sleep(0.5)
                            continue
                            
                        # 确保流是活跃的
                        if not self.stream.is_active():
                            logger.warning("音频流不活跃，尝试重新启动")
                            try:
                                self.stream.start_stream()
                                logger.info("音频流重新启动成功")
                            except Exception as e:
                                logger.error(f"启动音频流失败: {e}")
                                time.sleep(0.5)
                                continue
                        
                        # 读取数据
                        data = self.stream.read(
                            self.buffer_size, 
                            exception_on_overflow=False
                        )
                        logger.debug(f"读取到音频数据: {len(data) if data else 0} 字节")
                except Exception as e:
                    logger.error(f"读取音频数据失败: {e}")
                    time.sleep(0.5)
                    continue

                # 处理音频数据
                if data and len(data) > 0:
                    self._process_audio_data(data)
                    error_count = 0  # 重置错误计数
                else:
                    logger.warning("读取到空音频数据")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"检测循环错误({error_count}/{MAX_ERRORS}): {e}")
                
                if error_count >= MAX_ERRORS:
                    logger.critical("达到最大错误次数，停止检测")
                    self.stop()
                time.sleep(0.5)
                
    def stop(self):
        """停止检测（优化资源释放）"""
        if self.running:
            logger.info("正在停止唤醒词检测...")
            self.running = False

            if self.detection_thread and self.detection_thread.is_alive():
                self.detection_thread.join(timeout=1.0)

            # 仅清理自有资源，不清理外部传入的流
            if not self.external_stream and not self.audio_codec and self.stream:
                try:
                    if self.stream.is_active():
                        self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    logger.error(f"关闭音频流失败: {e}")
                    
            # 清理PyAudio实例
            if self.audio:
                try:
                    self.audio.terminate()
                except Exception as e:
                    logger.error(f"终止音频设备失败: {e}")

            # 重置状态
            self.stream = None
            self.audio = None
            self.external_stream = False
            logger.info("唤醒词检测已停止")
            
    def is_running(self):
        """检查唤醒词检测是否正在运行"""
        return self.running and not self.paused
        
    def update_stream(self, new_stream):
        """更新唤醒词检测器使用的音频流"""
        if not self.running:
            logger.warning("唤醒词检测器未运行，无法更新流")
            return False

        with self.stream_lock:
            # 如果当前不是使用外部流或AudioCodec，先清理现有资源
            if not self.external_stream and not self.audio_codec and self.stream:
                try:
                    if self.stream.is_active():
                        self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    logger.warning(f"关闭旧流时出错: {e}")

            # 更新为新的流
            self.stream = new_stream
            self.external_stream = True
            logger.info("已更新唤醒词检测器的音频流")
        return True

    def _process_audio_data(self, data):
        """处理音频数据（优化日志）"""
        try:
            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                if text := result.get('text', ''):
                    logger.info(f"完整识别结果: {text}")
                    self._check_wake_word(text)
                else:
                    logger.debug("完整识别结果为空")

            partial = json.loads(self.recognizer.PartialResult()).get('partial', '')
            if partial:
                # logger.info(f"部分识别结果: {partial}")
                self._check_wake_word(partial, is_partial=True)
            else:
                logger.debug("部分识别结果为空")
        except Exception as e:
            logger.error(f"处理音频数据时出错: {e}")

    def _check_wake_word(self, text, is_partial=False):
        """唤醒词检查（优化拼音匹配）"""
        try:
            text_pinyin = ''.join(lazy_pinyin(text)).replace(' ', '')
            logger.debug(f"当前文本拼音: {text_pinyin}")
            logger.debug(f"当前配置的唤醒词拼音: {self.wake_words_pinyin}")
            
            for word, pinyin in zip(self.wake_words, self.wake_words_pinyin):
                if pinyin in text_pinyin:
                    logger.info(f"检测到唤醒词 '{word}' (匹配拼音: {pinyin})")
                    self._trigger_callbacks(word, text)
                    self.recognizer.Reset()
                    return
                else:
                    logger.debug(f"未匹配到唤醒词 '{word}' (拼音: {pinyin})")
        except Exception as e:
            logger.error(f"检查唤醒词时出错: {e}")

    def pause(self):
        """暂停检测"""
        if self.running and not self.paused:
            self.paused = True
            logger.info("检测已暂停")

    def resume(self):
        """恢复检测"""
        if self.running and self.paused:
            self.paused = False
            logger.info("检测已恢复")

    def on_detected(self, callback):
        """注册回调"""
        self.on_detected_callbacks.append(callback)

    def _trigger_callbacks(self, wake_word, text):
        """触发回调（带异常处理）"""
        for cb in self.on_detected_callbacks:
            try:
                cb(wake_word, text)
            except Exception as e:
                logger.error(f"回调执行失败: {e}", exc_info=True)

    def __del__(self):
        self.stop()