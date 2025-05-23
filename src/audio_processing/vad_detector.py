import threading
import time
import numpy as np
import pyaudio
import webrtcvad
from src.utils.logging_config import get_logger
from src.constants.constants import AbortReason, DeviceState

logger = get_logger(__name__)

class VADDetector:
    """VAD检测器类，用于检测用户语音活动并触发打断"""
    
    def __init__(self, audio_codec, protocol, app_instance, loop, shared_stream=None):
        """初始化VAD检测器
        
        参数:
            audio_codec: 音频编解码器实例
            protocol: 通信协议实例
            app_instance: 应用程序实例
            loop: 事件循环
            shared_stream: 可选的共享音频流
        """
        self.audio_codec = audio_codec
        self.protocol = protocol
        self.app = app_instance
        self.loop = loop
        self.shared_stream = shared_stream  # 保存共享流引用
        
        # VAD设置
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(1)  # 改为1，提高灵敏度（0最灵敏，3最严格）
        
        # 参数设置
        self.sample_rate = 16000
        self.frame_duration = 20  # 毫秒
        self.frame_size = int(self.sample_rate * self.frame_duration / 1000)
        self.speech_window = 8  # 改为2，更快触发
        self.energy_threshold = 1200  # 降低阈值，更容易检测到语音
        
        # 状态变量
        self.running = False
        self.paused = False
        self.thread = None
        self.speech_count = 0
        self.silence_count = 0
        self.triggered = False
        
        # 调试变量
        self.debug_mode = True
        self.energy_history = []
        self.history_size = 100
        
        # 创建独立的PyAudio实例和流
        self.pa = None
        self.stream = None
        
        # logger.info(f"VAD检测器初始化完成 [能量阈值={self.energy_threshold}] [触发窗口={self.speech_window}帧] [VAD模式=1]")
        
    def start(self):
        """启动VAD检测器"""
        if self.running:
            logger.warning("VAD检测器已在运行")
            return
            
        # logger.info("启动VAD检测器")
        self.running = True
        self.paused = False
        self.speech_count = 0
        self.silence_count = 0
        self.triggered = False
        self.energy_history = []
        
        # 优先使用初始化时提供的共享流
        if self.shared_stream:
            try:
                logger.info("使用初始化时提供的共享音频流")
                self.stream = self.shared_stream
                # 测试流是否可用
                test_data = self.stream.read(self.frame_size, exception_on_overflow=False)
                if test_data and len(test_data) > 0:
                    logger.info("成功使用初始化时提供的共享音频流")
                    # 启动检测线程
                    self.thread = threading.Thread(
                        target=self._detection_loop,
                        daemon=True,
                        name="VAD-Detection-Thread"
                    )
                    self.thread.start()
                    logger.info("VAD检测器已启动")
                    return True
                else:
                    logger.warning("初始化时提供的共享音频流不可用，将创建独立流")
            except Exception as e:
                logger.warning(f"使用初始化时提供的共享音频流失败: {e}")
                # 如果共享流不可用，继续尝试创建独立流
        
        # 再尝试使用音频编解码器的流
        if self.audio_codec and hasattr(self.audio_codec, 'input_stream') and self.audio_codec.input_stream:
            try:
                logger.info("尝试使用应用程序共享的音频流")
                self.stream = self.audio_codec.input_stream
                # 测试流是否可用
                test_data = self.stream.read(self.frame_size, exception_on_overflow=False)
                if test_data and len(test_data) > 0:
                    logger.info("成功使用应用程序共享的音频流")
                    # 启动检测线程
                    self.thread = threading.Thread(
                        target=self._detection_loop,
                        daemon=True,
                        name="VAD-Detection-Thread"
                    )
                    self.thread.start()
                    logger.info("VAD检测器已启动")
                    return True
                else:
                    logger.warning("应用程序共享的音频流不可用，将创建独立流")
            except Exception as e:
                logger.warning(f"使用共享音频流失败: {e}")
                # 如果共享流不可用，继续尝试创建独立流
        
        # 初始化独立音频流
        if not self._initialize_audio_stream():
            logger.error("初始化音频流失败，VAD检测器启动失败")
            self.running = False
            return False
            
        # 启动检测线程
        self.thread = threading.Thread(
            target=self._detection_loop,
            daemon=True,
            name="VAD-Detection-Thread"
        )
        self.thread.start()
        logger.info("VAD检测器已启动")
        # logger.info("VAD检测器启动，running=%s, paused=%s", self.running, self.paused)
        # if self.stream:
        #     logger.info("VAD检测器音频流已分配，stream=%s", self.stream)
        # else:
        #     logger.warning("VAD检测器音频流未分配")
        return True
        
    def stop(self):
        """停止VAD检测器"""
        if not self.running:
            return
            
        # logger.info("停止VAD检测器")
        self.running = False
        
        # 等待线程结束
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            
        # 关闭音频流
        self._close_audio_stream()
        # logger.info("VAD检测器已停止")
        
    def pause(self):
        """暂停VAD检测"""
        if self.running and not self.paused:
            self.paused = True
            # logger.info("VAD检测已暂停")
            
    def resume(self):
        """恢复VAD检测"""
        if self.running and self.paused:
            self.paused = False
            # 重置状态
            self.speech_count = 0
            self.silence_count = 0
            self.triggered = False
            # logger.info("VAD检测已恢复")
            
    def _initialize_audio_stream(self):
        """初始化独立的音频流"""
        try:
            # 创建PyAudio实例
            self.pa = pyaudio.PyAudio()
            
            # 列出所有设备以便诊断
            # logger.info(f"发现 {device_count} 个音频设备:")
            # for i in range(device_count):
            #     device_info = self.pa.get_device_info_by_index(i)
            #     logger.info(f"设备 {i}: {device_info['name']} (输入通道: {device_info.get('maxInputChannels', 0)})")
            
            # 获取默认输入设备
            device_index = None
            for i in range(self.pa.get_device_count()):
                device_info = self.pa.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    device_index = i
                    break
            
            if device_index is None:
                logger.error("找不到可用的输入设备")
                return False
                
            # 输出设备信息
            # logger.info(f"VAD将使用音频输入设备: {self.pa.get_device_info_by_index(device_index)['name']} (索引: {device_index})")
                
            # 创建输入流
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.frame_size,
                start=True
            )
            
            # 测试流是否正常工作
            test_data = self.stream.read(self.frame_size, exception_on_overflow=False)
            if test_data and len(test_data) == self.frame_size * 2:
                audio_data = np.frombuffer(test_data, dtype=np.int16)
                # logger.info(f"音频帧前10个采样值: {audio_data[:10]}")
                energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                # logger.info(f"VAD音频流测试成功: 读取到{len(test_data)}字节数据，能量值={energy:.2f}")
            else:
                # logger.warning(f"VAD音频流测试异常: 读取到{len(test_data) if test_data else 0}字节")
                pass
            
            # logger.info(f"VAD检测器音频流初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"初始化VAD音频流失败: {e}", exc_info=True)
            return False
            
    def _close_audio_stream(self):
        """关闭音频流"""
        try:
            # 检查是否使用的是共享流
            is_shared_stream = (
                self.audio_codec and 
                hasattr(self.audio_codec, 'input_stream') and 
                self.stream == self.audio_codec.input_stream
            )
            
            # 如果是共享流，只置空引用而不关闭
            if is_shared_stream:
                logger.info("使用的是共享音频流，仅清除引用而不关闭")
                self.stream = None
            # 否则完全关闭独立流
            elif self.stream:
                logger.info("关闭独立音频流")
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
                
            # 只在使用独立PyAudio实例时关闭
            if not is_shared_stream and self.pa:
                self.pa.terminate()
                self.pa = None
                
            # logger.info("VAD音频流已关闭")
        except Exception as e:
            logger.error(f"关闭VAD音频流失败: {e}")
            # 确保变量被重置
            self.stream = None
            self.pa = None
            
    def _detection_loop(self):
        """VAD检测主循环"""
        logger.info("VAD检测循环已启动")
        
        # 添加计数器以定期报告状态
        frame_counter = 0
        last_status_time = time.time()
        
        # 添加状态报告计数器
        status_report_counter = 0
        
        while self.running:
            # 如果暂停或者音频流未初始化，则跳过
            if self.paused or not self.stream:
                time.sleep(0.1)
                continue
            try:
                # 每5秒输出一次状态信息，无论是否在说话状态
                current_time = time.time()
                if current_time - last_status_time > 5.0:
                    # logger.info(f"VAD状态: 运行={self.running}, 暂停={self.paused}, 设备状态={self.app.device_state}")
                    last_status_time = current_time

                energy = 0  # 确保energy有初值
                is_speech = False

                # 只在说话状态下进行检测
                if self.app.device_state == DeviceState.SPEAKING:
                    # 读取音频帧
                    frame = self._read_audio_frame()
                    if not frame:
                        time.sleep(0.01)
                        continue

                    frame_counter += 1

                    # 检测是否是语音
                    is_speech, energy = self._detect_speech(frame)

                    # 每50帧输出一次当前状态（约1秒）
                    if frame_counter % 50 == 0:
                        # logger.info(f"VAD状态: 运行中 [语音计数={self.speech_count}] [能量={energy:.2f}] [阈值={self.energy_threshold}] [TTS播放={self.app.get_is_tts_playing()}]")
                        pass

                    # 如果检测到语音并且达到触发条件，处理打断
                    if is_speech:
                        self._handle_speech_frame(frame, energy)
                    else:
                        self._handle_silence_frame(frame)
                else:
                    # 不在说话状态，重置状态
                    if frame_counter > 0:
                        logger.debug(f"设备当前状态: {self.app.device_state}，不是SPEAKING状态，VAD检测暂停")
                        frame_counter = 0
                    self._reset_state()
                    time.sleep(0.1)  # 非说话状态下降低检查频率

                # 每100帧输出一次状态信息
                status_report_counter += 1
                if status_report_counter >= 100:
                    # logger.debug(f"VAD状态: 运行中={self.running}, 暂停={self.paused}, 检测到语音={is_speech}, 能量={energy:.1f}, 平均能量={np.mean(self.energy_history[-100:]) if self.energy_history else 0:.1f}")
                    status_report_counter = 0

                if self.triggered and self.app.device_state == DeviceState.SPEAKING:
                    logger.info(f"VAD检测到用户语音中断，能量={energy:.1f}, 帧数={frame_counter}")

                    # 直接调用中断（替代使用asyncio.create_task）
                    self.app.abort_speaking(AbortReason.USER_INTERRUPTION)

                    # 重置状态
                    self.triggered = False 
                    self.speech_count = 0

                if energy > self.energy_threshold:
                    # logger.info(f"VAD检测到声音，能量={energy:.1f}")
                    pass

            except Exception as e:
                logger.error(f"VAD检测循环出错: {e}")

            time.sleep(0.01)  # 小延迟，减少CPU使用
            
        logger.info("VAD检测循环已结束")
        
    def _read_audio_frame(self):
        """读取音频帧"""
        try:
            if not self.stream:
                logger.warning("VAD音频流不存在，无法读取音频帧")
                return None
                
            if not self.stream.is_active():
                logger.warning("VAD音频流未激活，尝试重新启动")
                try:
                    self.stream.start_stream()
                    logger.info("VAD音频流已重新启动")
                except Exception as e:
                    logger.error(f"启动VAD音频流失败: {e}")
                    return None
                
            # 读取音频数据
            try:
                data = self.stream.read(self.frame_size, exception_on_overflow=False)
                if not data or len(data) != self.frame_size * 2:
                    logger.warning(f"读取到异常音频数据: {len(data) if data else 0}字节，预期{self.frame_size * 2}字节")
                return data
            except OSError as e:
                # 处理特定的音频流错误
                logger.error(f"音频流读取OSError: {e}")
                return None
        except Exception as e:
            logger.error(f"读取音频帧失败: {e}")
            return None
            
    def _detect_speech(self, frame):
        """检测是否是语音"""
        try:
            # 确保帧长度正确
            if len(frame) != self.frame_size * 2:  # 16位音频，每个样本2字节
                return False, 0
                
            # 使用VAD检测
            is_speech = self.vad.is_speech(frame, self.sample_rate)
            
            # 计算音频能量
            audio_data = np.frombuffer(frame, dtype=np.int16)
            # logger.info(f"音频帧前10个采样值: {audio_data[:10]}")
            energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            
            # 保存能量历史
            self.energy_history.append(energy)
            if len(self.energy_history) > self.history_size:
                self.energy_history = self.energy_history[-self.history_size:]
                
            # 计算平均能量和最大能量
            if len(self.energy_history) > 10:
                avg_energy = np.mean(self.energy_history)
                max_energy = np.max(self.energy_history)
                # 每50帧输出一次能量统计
                if len(self.energy_history) % 50 == 0:
                    # logger.info(f"能量统计: 当前={energy:.1f}, 平均={avg_energy:.1f}, 最大={max_energy:.1f}, 阈值={self.energy_threshold}")
                    pass
            
            # 动态阈值
            if self.app.device_state == DeviceState.SPEAKING:
                dynamic_threshold = self.energy_threshold + 500  # 或更高
            else:
                dynamic_threshold = self.energy_threshold
            is_valid_speech = is_speech and energy > dynamic_threshold
            
            # 输出详细的调试日志
            if self.debug_mode and (is_speech or energy > self.energy_threshold * 0.5):
                # logger.debug(f'VAD检测结果: {"语音" if is_valid_speech else "非语音"} [VAD={is_speech}] [能量={energy:.2f}] [阈值={self.energy_threshold}]')
                pass
                
            return is_valid_speech, energy
        except Exception as e:
            logger.error(f"检测语音失败: {e}")
            return False, 0
            
    def _handle_speech_frame(self, frame, energy):
        """处理语音帧"""
        self.speech_count += 1
        self.silence_count = 0
        
        # 详细记录连续语音状态
        logger.debug(f'检测到语音 [能量: {energy:.2f}] [连续语音帧: {self.speech_count}/{self.speech_window}]')
        
        # 检测到足够的连续语音帧，触发打断
        if self.speech_count >= self.speech_window and not self.triggered:
            self.triggered = True
            logger.info(f"检测到持续语音，触发打断！[连续语音帧={self.speech_count}] [能量={energy:.2f}]")
            self._trigger_interrupt()
            
            # 使用短暂暂停而不是永久暂停，防止频繁触发
            self.paused = True
            logger.info("VAD检测器暂时暂停以防止重复触发")
            
            # 重置状态
            self.speech_count = 0
            self.silence_count = 0
            
            # 3秒后重新启用检测
            def resume_detector():
                if self.running and self.paused:
                    self.paused = False
                    self.triggered = False
                    logger.info("VAD检测器恢复检测")
                    
            # 启动定时器，3秒后恢复检测
            threading.Timer(3.0, resume_detector).start()
            
    def _handle_silence_frame(self, frame):
        """处理静音帧"""
        self.speech_count = max(0, self.speech_count - 0.2)  # 逐渐减少语音计数
        self.silence_count += 1
        
    def _reset_state(self):
        """重置状态"""
        self.speech_count = 0
        self.silence_count = 0
        self.triggered = False
        
    def _trigger_interrupt(self):
        """触发打断"""
        # 通知应用程序中止当前语音输出
        logger.info("VAD检测到用户打断，正在触发中断...")
        
        try:
            # 记录当前状态
            logger.info(f"打断前状态: 设备状态={self.app.device_state}, TTS播放={self.app.get_is_tts_playing()}")
            
            # 直接调用而不是通过schedule，减少延迟
            self.app.abort_speaking(AbortReason.USER_INTERRUPTION)
            
            # 记录打断后状态
            logger.info(f"打断后状态: 设备状态={self.app.device_state}, TTS播放={self.app.get_is_tts_playing()}")
        except Exception as e:
            logger.error(f"触发打断失败: {e}", exc_info=True)
            # 如果直接调用失败，回退到使用schedule
            self.app.schedule(lambda: self.app.abort_speaking(AbortReason.USER_INTERRUPTION))

    def is_active_and_hearing(self):
        """返回VAD是否在运行且最近检测到声音"""
        return self.running and self.last_energy > self.energy_threshold

    def calibrate_threshold(self, seconds=2):
        energies = []
        for _ in range(int(self.sample_rate / self.frame_size * seconds)):
            frame = self._read_audio_frame()
            if frame:
                audio_data = np.frombuffer(frame, dtype=np.int16)
                energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                energies.append(energy)
        self.energy_threshold = np.mean(energies) + 3 * np.std(energies)
        logger.info(f'自适应VAD阈值设为: {self.energy_threshold:.1f}')
