import queue
import numpy as np
import pyaudio
import opuslib
import time
import threading
import logging
import os

from src.constants.constants import AudioConfig
from src.utils.logging_config import get_logger

logger = get_logger(__name__)
logger.setLevel(logging.DEBUG)

# 检查是否启用模拟模式
SIMULATION_MODE = os.environ.get('DISABLE_AUDIO', 'False').lower() in ('true', '1', 'yes')
if SIMULATION_MODE:
    logger.warning("音频编解码器运行在模拟模式，不会实际访问音频设备")


class AudioCodec:
    """音频编解码器类，处理音频的录制和播放（严格兼容版）"""

    def __init__(self):
        self.audio = None
        self.input_stream = None
        self.output_stream = None
        self.opus_encoder = None
        self.opus_decoder = None
        self.audio_decode_queue = queue.Queue()

        # 状态管理（保留原始变量名）
        self._is_closing = False
        self._is_input_paused = False
        self._input_paused_lock = threading.Lock()
        self._stream_lock = threading.Lock()

        # 新增设备索引缓存
        self._cached_input_device = -1
        self._cached_output_device = -1

        self._initialize_audio()
        
    def _initialize_audio(self):
        try:
            # 在模拟模式下，不实际初始化音频设备
            if SIMULATION_MODE:
                logger.info("音频编解码器在模拟模式下运行，使用虚拟音频设备")
                self._initialize_simulated_audio()
                return
                
            self.audio = pyaudio.PyAudio()

            # 缓存设备索引
            self._cached_input_device = self._get_default_or_first_available_device(True)
            self._cached_output_device = self._get_default_or_first_available_device(False)

            # 初始化流（优化实现）
            self.input_stream = self._create_stream(is_input=True)
            self.output_stream = self._create_stream(is_input=False)

            # 打印当前音频配置
            logger.debug(f"初始化音频配置: 输入采样率={AudioConfig.INPUT_SAMPLE_RATE}, 输出采样率={AudioConfig.OUTPUT_SAMPLE_RATE}")
            logger.debug(f"帧长度: {AudioConfig.FRAME_DURATION}ms, 输入帧大小={AudioConfig.INPUT_FRAME_SIZE}, 输出帧大小={AudioConfig.OUTPUT_FRAME_SIZE}")
            
            # 编解码器初始化（保持原始参数）
            self.opus_encoder = opuslib.Encoder(
                AudioConfig.INPUT_SAMPLE_RATE,
                AudioConfig.CHANNELS,
                AudioConfig.OPUS_APPLICATION
            )
            
            # 打印当前音频配置
            logger.debug(f"初始化音频配置: 输入采样率={AudioConfig.INPUT_SAMPLE_RATE}, 输出采样率={AudioConfig.OUTPUT_SAMPLE_RATE}")
            logger.debug(f"帧长度: {AudioConfig.FRAME_DURATION}ms, 输入帧大小={AudioConfig.INPUT_FRAME_SIZE}, 输出帧大小={AudioConfig.OUTPUT_FRAME_SIZE}")
            
            self.opus_decoder = opuslib.Decoder(
                AudioConfig.OUTPUT_SAMPLE_RATE,
                AudioConfig.CHANNELS
            )

            logger.info("音频设备和编解码器初始化成功")
        except Exception as e:
            logger.error(f"初始化音频设备失败: {e}")
            self.close()
            raise
            
    def _initialize_simulated_audio(self):
        """初始化模拟音频环境"""
        logger.info("初始化模拟音频环境")
        
        # 仍然初始化编解码器，因为它们不依赖于实际的音频设备
        self.opus_encoder = opuslib.Encoder(
            AudioConfig.INPUT_SAMPLE_RATE,
            AudioConfig.CHANNELS,
            AudioConfig.OPUS_APPLICATION
        )
        
        self.opus_decoder = opuslib.Decoder(
            AudioConfig.OUTPUT_SAMPLE_RATE,
            AudioConfig.CHANNELS
        )
        
        # 创建一个模拟的音频流类
        class SimulatedAudioStream:
            def __init__(self, is_input=True):
                self.is_input = is_input
                self._active = True
                self.frame_size = AudioConfig.INPUT_FRAME_SIZE if is_input else AudioConfig.OUTPUT_FRAME_SIZE
                
            def read(self, frame_size, exception_on_overflow=False):
                """返回静音数据"""
                time.sleep(0.01)  # 模拟处理延迟
                return b'\x00' * (frame_size * 2)  # 16位静音
                
            def write(self, data):
                """模拟写入"""
                time.sleep(0.01)  # 模拟处理延迟
                return len(data)
                
            def is_active(self):
                return self._active
                
            def stop_stream(self):
                self._active = False
                
            def start_stream(self):
                self._active = True
                
            def close(self):
                self._active = False
                
            def get_read_available(self):
                """模拟可读取的帧数"""
                return self.frame_size
        
        # 创建模拟的流
        self.input_stream = SimulatedAudioStream(is_input=True)
        self.output_stream = SimulatedAudioStream(is_input=False)
        
        logger.info("模拟音频环境初始化成功")

    def _get_default_or_first_available_device(self, is_input=True):
        """设备选择逻辑（优化异常处理）"""
        if is_input:
            logger.info("选择输入设备")
            return 1
        else:
            logger.info("选择输出设备")
            # return 3

        try:
            device = self.audio.get_default_input_device_info() if is_input else \
                self.audio.get_default_output_device_info()
            logger.info(f"使用默认设备: {device['name']} (Index: {device['index']})")
            return device["index"]
        except OSError:
            logger.warning("默认设备不可用，查找替代设备...")
            for i in range(self.audio.get_device_count()):
                dev = self.audio.get_device_info_by_index(i)
                if is_input and dev["maxInputChannels"] > 0:
                    logger.info(f"使用替代输入设备: {dev['name']} (Index: {i})")
                    return i
                if not is_input and dev["maxOutputChannels"] > 0:
                    logger.info(f"使用替代输出设备: {dev['name']} (Index: {i})")
                    return i
            raise RuntimeError("没有可用的音频设备")

    def _create_stream(self, is_input=True):
        """流创建逻辑（新增设备缓存）"""
        # 如果在模拟模式下，返回已经创建的模拟流
        if SIMULATION_MODE:
            return self.input_stream if is_input else self.output_stream
            
        params = {
            "format": pyaudio.paInt16,
            "channels": AudioConfig.CHANNELS,
            "rate": AudioConfig.INPUT_SAMPLE_RATE if is_input else AudioConfig.OUTPUT_SAMPLE_RATE,
            "input" if is_input else "output": True,
            "frames_per_buffer": AudioConfig.INPUT_FRAME_SIZE if is_input else AudioConfig.OUTPUT_FRAME_SIZE,
            "start": False
        }

        # 使用缓存设备索引
        if is_input:
            params["input_device_index"] = self._cached_input_device
        else:
            params["output_device_index"] = self._cached_output_device

        return self.audio.open(**params)

    def _reinitialize_input_stream(self):
        """输入流重建（优化设备缓存）"""
        if self._is_closing:
            return
            
        # 如果在模拟模式下，不需要重新初始化
        if SIMULATION_MODE:
            logger.info("模拟模式下无需重新初始化输入流")
            return

        try:
            # 刷新设备缓存
            self._cached_input_device = self._get_default_or_first_available_device(True)

            if self.input_stream:
                try:
                    self.input_stream.stop_stream()
                    self.input_stream.close()
                except Exception:
                    pass

            self.input_stream = self._create_stream(is_input=True)
            self.input_stream.start_stream()
            logger.info("音频输入流重新初始化成功")
        except Exception as e:
            logger.error(f"输入流重建失败: {e}")
            raise

    def _reinitialize_output_stream(self):
        """输出流重建（优化设备缓存）"""
        if self._is_closing:
            return
            
        # 如果在模拟模式下，不需要重新初始化
        if SIMULATION_MODE:
            logger.info("模拟模式下无需重新初始化输出流")
            return

        try:
            # 刷新设备缓存
            self._cached_output_device = self._get_default_or_first_available_device(False)

            if self.output_stream:
                try:
                    self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception:
                    pass

            self.output_stream = self._create_stream(is_input=False)
            self.output_stream.start_stream()
            logger.info("音频输出流重新初始化成功")
        except Exception as e:
            logger.error(f"输出流重建失败: {e}")
            raise

    def pause_input(self):
        with self._input_paused_lock:
            self._is_input_paused = True
        logger.info("音频输入已暂停")

    def resume_input(self):
        with self._input_paused_lock:
            self._is_input_paused = False
        logger.info("音频输入已恢复")

    def is_input_paused(self):
        with self._input_paused_lock:
            return self._is_input_paused

    def read_audio(self):
        """（优化缓冲区管理）"""
        if self.is_input_paused():
            return None

        try:
            with self._stream_lock:
                # 流状态检查优化
                if not self.input_stream or not self.input_stream.is_active():
                    self._reinitialize_input_stream()
                    if not self.input_stream.is_active():
                        return None

                # 动态缓冲区调整 - 实时性能优化
                available = self.input_stream.get_read_available()
                if available > AudioConfig.INPUT_FRAME_SIZE * 2:  # 降低阈值从3倍到2倍
                    skip_samples = available - (AudioConfig.INPUT_FRAME_SIZE * 1.5)  # 减少保留量
                    if skip_samples > 0:  # 增加安全检查
                        self.input_stream.read(
                            int(skip_samples),  # 确保整数
                            exception_on_overflow=False
                        )
                        logger.debug(f"跳过{skip_samples}个样本减少延迟")

                # 读取数据
                data = self.input_stream.read(
                    AudioConfig.INPUT_FRAME_SIZE,
                    exception_on_overflow=False
                )

                # 数据验证
                if len(data) != AudioConfig.INPUT_FRAME_SIZE * 2:
                    logger.warning("音频数据长度异常，重置输入流")
                    self._reinitialize_input_stream()
                    return None

                return self.opus_encoder.encode(data, AudioConfig.INPUT_FRAME_SIZE)

        except Exception as e:
            logger.error(f"音频读取失败: {e}")
            self._reinitialize_input_stream()
            return None

    def play_audio(self):
        """处理和播放音频数据"""
        try:
            # 检查队列是否为空，为空则直接返回
            if self.audio_decode_queue.empty():
                return

            # 批量解码优化
            batch_size = min(10, self.audio_decode_queue.qsize())
            logger.debug(f"准备处理音频帧批次，数量: {batch_size}")
            buffer = bytearray()
            
            # 服务器采样率为24000，但客户端配置使用48000或16000
            # 尝试多种解码帧大小以应对不同采样率的音频数据
            possible_frame_sizes = [
                # 960,  # 48000Hz, 20ms
                # 480,  # 24000Hz, 20ms
                # 320,  # 16000Hz, 20ms
                # 1440, # 48000Hz, 30ms
                # 720,  # 24000Hz, 30ms
                2880, # 48000Hz, 60ms
                # 1440, # 24000Hz, 60ms
            ]
            
            # 逐帧处理队列中的音频数据
            for i in range(batch_size):
                try:
                    # 从队列获取Opus编码数据
                    opus_data = self.audio_decode_queue.get_nowait()
                    data_size = len(opus_data)
                    
                    # 记录当前处理的帧信息
                    logger.debug(f"正在解码第{i+1}/{batch_size}帧，数据大小: {data_size}字节")
                    
                    # 尝试使用不同的帧大小进行解码
                    decoded = False
                    for frame_size in possible_frame_sizes:
                        try:
                            # 使用足够大的帧大小解码
                            pcm = self.opus_decoder.decode(opus_data, frame_size)
                            buffer.extend(pcm)
                            logger.debug(f"使用帧大小 {frame_size} 成功解码")
                            decoded = True
                            break
                        except opuslib.OpusError as e:
                            # 尝试下一个帧大小
                            logger.debug(f"使用帧大小 {frame_size} 解码失败: {e}")
                            continue
                    
                    if not decoded:
                        # 如果所有帧大小都失败，尝试重置解码器
                        logger.warning(f"所有帧大小都解码失败，异常： {e}, 数据大小: {data_size}字节")
                    
                except queue.Empty:
                    # 队列为空，提前结束循环
                    logger.debug("队列已处理完毕，提前结束批处理")
                    break
                except opuslib.OpusError as e:
                    # 记录详细的解码错误信息
                    logger.error(f"解码失败: {e}, 数据大小: {data_size if 'data_size' in locals() else '未知'}字节")
                    # 继续处理下一帧，不中断整个批次

            # 检查是否有数据需要播放
            if buffer:
                logger.debug(f"准备播放缓冲区数据，大小: {len(buffer)}字节")
                # 使用锁保证线程安全
                with self._stream_lock:
                    # 验证输出流状态
                    if self.output_stream and self.output_stream.is_active():
                        try:
                            # 将缓冲区数据转换为numpy数组再转为字节流写入输出流
                            self.output_stream.write(np.frombuffer(buffer, dtype=np.int16).tobytes())
                        except OSError as e:
                            # 处理流关闭的特殊情况
                            if "Stream closed" in str(e):
                                logger.warning(f"输出流已关闭，尝试重新初始化: {e}")
                                self._reinitialize_output_stream()
                                self.output_stream.write(buffer)
        except Exception as e:
            # 捕获并记录所有其他异常
            logger.error(f"播放失败: {e}", exc_info=True)
            # 尝试重新初始化输出流以恢复
            self._reinitialize_output_stream()

    def close(self):
        """（优化资源释放顺序和线程安全性）"""
        if self._is_closing:
            return

        self._is_closing = True
        logger.info("开始关闭音频编解码器...")

        try:
            # 清空队列先行处理
            self.clear_audio_queue()
            
            # 安全停止和关闭流
            with self._stream_lock:
                # 先关闭输入流
                if self.input_stream:
                    try:
                        if hasattr(self.input_stream, 'is_active') and self.input_stream.is_active():
                            self.input_stream.stop_stream()
                        self.input_stream.close()
                    except Exception as e:
                        logger.warning(f"关闭输入流失败: {e}")
                    finally:
                        self.input_stream = None
                        
                # 再关闭输出流        
                if self.output_stream:
                    try:
                        if hasattr(self.output_stream, 'is_active') and self.output_stream.is_active():
                            self.output_stream.stop_stream()
                        self.output_stream.close()
                    except Exception as e:
                        logger.warning(f"关闭输出流失败: {e}")
                    finally:
                        self.output_stream = None
                
                # 最后释放PyAudio
                if self.audio:
                    try:
                        self.audio.terminate()
                    except Exception as e:
                        logger.warning(f"释放PyAudio失败: {e}")
                    finally:
                        self.audio = None

            # 清理编解码器
            self.opus_encoder = None
            self.opus_decoder = None
            
            logger.info("音频资源已完全释放")
        except Exception as e:
            logger.error(f"关闭音频编解码器过程中发生错误: {e}")
        finally:
            self._is_closing = False

    def write_audio(self, opus_data):
        self.audio_decode_queue.put(opus_data)

    def has_pending_audio(self):
        return not self.audio_decode_queue.empty()

    def wait_for_audio_complete(self, timeout=5.0):
        start = time.time()
        while self.has_pending_audio() and time.time() - start < timeout:
            time.sleep(0.1)

    def clear_audio_queue(self):
        with self._stream_lock:
            while not self.audio_decode_queue.empty():
                try:
                    self.audio_decode_queue.get_nowait()
                except queue.Empty:
                    break

    def start_streams(self):
        for stream in [self.input_stream, self.output_stream]:
            if stream and not stream.is_active():
                try:
                    stream.start_stream()
                except OSError as e:
                    logger.error(f"启动失败: {e}")

    def stop_streams(self):
        """安全停止流（优化错误处理）"""
        with self._stream_lock:
            for name, stream in [("输入", self.input_stream), ("输出", self.output_stream)]:
                if stream:
                    try:
                        # 使用hasattr避免在流已关闭情况下调用is_active
                        if hasattr(stream, 'is_active') and stream.is_active():
                            stream.stop_stream()
                    except Exception as e:
                        # 使用warning级别，因为这不是严重错误
                        logger.warning(f"停止{name}流失败: {e}")

    def __del__(self):
        self.close()

# 在AudioCodec类中创建一个集中的音频管理器
class AudioManager:
    def __init__(self):
        self.input_stream = None
        self.listeners = []
        self._buffer = []  # 用于缓存最近的音频数据
        
    def add_listener(self, listener):
        self.listeners.append(listener)
        
    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
            
    def push_audio_data(self, data):
        # 将音频数据保存到缓冲区
        self._buffer.append(data)
        if len(self._buffer) > 10:  # 保持缓冲区大小
            self._buffer.pop(0)
        # 分发给所有监听器
        for listener in self.listeners:
            listener.process_audio(data)