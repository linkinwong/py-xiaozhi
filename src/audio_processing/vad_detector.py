import threading
import time
import numpy as np
import pyaudio
import webrtcvad
import logging
import collections
from src.utils.logging_config import get_logger
from src.constants.constants import AbortReason, DeviceState
from voice_print.voiceprint_manager import VoiceprintManager

logger = get_logger(__name__)
# logger.setLevel(logging.DEBUG)  # 不需要在这里设置，已经在logging_config中配置
logger.debug("VAD检测器模块初始化")

class VADDetector:
    """VAD检测器类，用于检测用户语音活动并触发打断"""
    
    def __init__(self, audio_codec, protocol, app_instance, loop, shared_stream=None, voiceprint_enabled=True, allowed_speakers=None, voiceprint_threshold=0.18, voice_print_len=1.3):
        """初始化VAD检测器
        
        参数:
            audio_codec: 音频编解码器实例
            protocol: 通信协议实例
            app_instance: 应用程序实例
            loop: 事件循环
            shared_stream: 可选的共享音频流
            voiceprint_enabled: 是否启用声纹验证
            allowed_speakers: 允许打断的说话者列表
            voiceprint_threshold: 声纹识别阈值
            voice_print_len: 声纹识别所需的最小音频长度(秒)
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
        
        # 添加定时器引用，避免创建过多线程
        self.resume_timer = None
        
        # 声纹识别相关设置
        self.voiceprint_enabled = voiceprint_enabled
        self.voiceprint_manager = None
        
        # 初始化声纹管理器
        if self.voiceprint_enabled:
            try:
                self.voiceprint_manager = VoiceprintManager(
                    threshold=voiceprint_threshold,
                    voice_print_len=voice_print_len
                )
                if allowed_speakers:
                    self.voiceprint_manager.set_allowed_speakers(allowed_speakers)
                self.voiceprint_manager.enable(True)
                logger.info(f"声纹管理器初始化成功，阈值={voiceprint_threshold}，允许打断的说话者：{allowed_speakers}")
            except Exception as e:
                logger.error(f"声纹管理器初始化失败: {e}")
                self.voiceprint_enabled = False
        
        # 音频缓冲区，用于保存近期的语音
        self.audio_buffer = collections.deque(maxlen=int(3.0 * 1000 / self.frame_duration))  # 保存最近3秒的音频
        self.last_recognition_time = 0  # 上次声纹识别的时间
        self.min_recognition_interval = 0.3  # 最小识别间隔（秒）
        
        # 语音活动检测状态
        self.is_speech_active = False  # 是否检测到语音活动
        self.active_speech_time = 0  # 语音活动开始时间
        
        logger.debug(f"VAD检测器初始化完成 [能量阈值={self.energy_threshold}] [触发窗口={self.speech_window}帧] [VAD模式=1] [声纹识别={self.voiceprint_enabled}]")
        
    def start(self):
        """启动VAD检测器"""
        if self.running:
            logger.warning("VAD检测器已在运行")
            return
            
        logger.debug("启动VAD检测器")
        self.running = True
        self.paused = False
        self.speech_count = 0
        self.silence_count = 0
        self.triggered = False
        self.energy_history = []
        self.audio_buffer.clear()
        self.is_speech_active = False
        
        # 添加调试信息
        logger.debug("VAD检测器开始初始化音频流")
        
        # 优先使用初始化时提供的共享流
        if self.shared_stream:
            try:
                logger.debug("尝试使用初始化时提供的共享音频流")
                self.stream = self.shared_stream
                # 测试流是否可用
                test_data = self.stream.read(self.frame_size, exception_on_overflow=False)
                if test_data and len(test_data) > 0:
                    logger.info("成功使用初始化时提供的共享音频流")
                    # 启动检测线程
                    logger.debug("准备启动VAD检测线程")
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
                    logger.debug("准备启动VAD检测线程")
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
        logger.debug("开始初始化独立音频流")
        if not self._initialize_audio_stream():
            logger.error("初始化音频流失败，VAD检测器启动失败")
            self.running = False
            return False
            
        # 启动检测线程
        logger.debug("准备启动VAD检测线程")
        self.thread = threading.Thread(
            target=self._detection_loop,
            daemon=True,
            name="VAD-Detection-Thread"
        )
        self.thread.start()
        logger.info("VAD检测器已启动")
        logger.debug("VAD检测器启动，running=%s, paused=%s", self.running, self.paused)
        return True
        
    def stop(self):
        """停止VAD检测器"""
        if not self.running:
            return
            
        logger.debug("停止VAD检测器")
        self.running = False
        
        # 取消定时器（如果存在）
        if self.resume_timer and self.resume_timer.is_alive():
            self.resume_timer.cancel()
            self.resume_timer = None
        
        # 等待线程结束
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            
        # 关闭音频流
        self._close_audio_stream()
        
        # 关闭声纹管理器
        if self.voiceprint_manager:
            self.voiceprint_manager.shutdown()
            
        logger.debug("VAD检测器已停止")
        
    def pause(self):
        """暂停VAD检测"""
        if self.running and not self.paused:
            self.paused = True
            logger.debug("VAD检测已暂停")
            
    def resume(self):
        """恢复VAD检测"""
        if self.running and self.paused:
            self.paused = False
            # 重置状态
            self.speech_count = 0
            self.silence_count = 0
            self.triggered = False
            self.is_speech_active = False
            logger.debug("VAD检测已恢复")
            
    def _initialize_audio_stream(self):
        """初始化独立的音频流"""
        try:
            # 创建PyAudio实例
            logger.debug("正在创建PyAudio实例")
            self.pa = pyaudio.PyAudio()
            
            # 获取默认输入设备
            logger.debug(f"获取音频输入设备信息，共有 {self.pa.get_device_count()} 个设备")
            device_index = None
            for i in range(self.pa.get_device_count()):
                device_info = self.pa.get_device_info_by_index(i)
                logger.debug(f"设备 {i}: {device_info['name']} - 输入通道: {device_info['maxInputChannels']}")
                if device_info['maxInputChannels'] > 0:
                    device_index = i
                    break
            
            if device_index is None:
                logger.error("找不到可用的输入设备")
                return False
                
            # 输出设备信息
            logger.debug(f"VAD将使用音频输入设备: {self.pa.get_device_info_by_index(device_index)['name']} (索引: {device_index})")
                
            # 创建输入流
            logger.debug("开始打开音频流")
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
            logger.debug("测试音频流是否正常工作")
            test_data = self.stream.read(self.frame_size, exception_on_overflow=False)
            if test_data and len(test_data) == self.frame_size * 2:
                audio_data = np.frombuffer(test_data, dtype=np.int16)
                energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                logger.debug(f"VAD音频流测试成功: 读取到{len(test_data)}字节数据，能量值={energy:.2f}")
            else:
                logger.warning(f"VAD音频流测试异常: 读取到{len(test_data) if test_data else 0}字节")
                pass
            
            logger.debug(f"VAD检测器音频流初始化成功")
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
                logger.debug("使用的是共享音频流，仅清除引用而不关闭")
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
                
            logger.debug("VAD音频流已关闭")
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
        
        logger.debug("VAD检测循环开始，设备状态: %s", self.app.device_state)
        
        while self.running:
            # 如果暂停或者音频流未初始化，则跳过
            if self.paused or not self.stream:
                time.sleep(0.1)
                continue
                
            try:
                current_time = time.time()
                if current_time - last_status_time > 5.0:
                    last_status_time = current_time
                    logger.debug(f"VAD检测循环状态: 运行中={self.running}, 暂停={self.paused}, 设备状态={self.app.device_state}")

                # 只在说话状态下进行检测
                if self.app.device_state == DeviceState.SPEAKING:
                    # 读取音频帧
                    frame = self._read_audio_frame()
                    if not frame:
                        logger.debug("读取音频帧失败，等待下一次尝试")
                        time.sleep(0.01)
                        continue

                    frame_counter += 1

                    # 将帧添加到缓冲区
                    self.audio_buffer.append(frame)

                    # 检测是否是语音
                    is_speech, energy = self._detect_speech(frame)


                    # 处理语音/静音帧
                    if is_speech:
                        self._handle_speech_frame(energy)
                    else:
                        self._handle_silence_frame()
                        
                    # 处理声纹识别结果
                    if self.voiceprint_enabled and self.voiceprint_manager:
                        self._check_voiceprint_result()
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
                    logger.debug(f"每 100 个音频帧（包括语音和静音）状态汇报: VAD状态: 运行中={self.running}, 暂停={self.paused}, 检测到语音={self.is_speech_active}, 语音计数={self.speech_count}")
                    status_report_counter = 0

            except Exception as e:
                logger.error(f"VAD检测循环出错: {e}", exc_info=True)

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
                # 添加调试信息
                logger.debug("正在读取音频帧...")
                data = self.stream.read(self.frame_size, exception_on_overflow=False)
                logger.debug(f"音频帧读取完成，数据大小: {len(data) if data else 0}字节")
                if not data or len(data) != self.frame_size * 2:
                    logger.warning(f"读取到异常音频数据: {len(data) if data else 0}字节，预期{self.frame_size * 2}字节")
                return data
            except OSError as e:
                # 处理特定的音频流错误
                logger.error(f"音频流读取OSError: {e}")
                return None
        except Exception as e:
            logger.error(f"读取音频帧失败: {e}", exc_info=True)
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
            energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            
            # 保存能量历史
            self.energy_history.append(energy)
            if len(self.energy_history) > self.history_size:
                self.energy_history = self.energy_history[-self.history_size:]
                
            # 计算平均能量和最大能量
            if len(self.energy_history) > 10:
                avg_energy = np.mean(self.energy_history)
                max_energy = np.max(self.energy_history)
            
            # 动态阈值
            if self.app.device_state == DeviceState.SPEAKING:
                dynamic_threshold = self.energy_threshold + 500  # 或更高
            else:
                dynamic_threshold = self.energy_threshold
            is_valid_speech = is_speech and energy > dynamic_threshold
                
            return is_valid_speech, energy
        except Exception as e:
            logger.error(f"检测语音失败: {e}")
            return False, 0
            
    def _handle_speech_frame(self, energy):
        """处理语音帧"""
        self.speech_count += 1
        self.silence_count = 0
        
        # 如果之前不是语音活动状态，标记开始新的语音段
        if not self.is_speech_active:
            self.is_speech_active = True
            self.active_speech_time = time.time()
            logger.debug(f"检测到语音从非活动状态变为活动状态 [能量: {energy:.2f}, speech_count: {self.speech_count}]")
        
        # 检测到足够的连续语音帧, 触发检测到声音事件
        if self.speech_count >= self.speech_window and not self.triggered:
            # logger.debug(f"打破vad 阈值，当前 [speech_count: {self.speech_count}]")
            # 只有声纹验证功能启用时才进行额外处理
            if self.voiceprint_enabled and self.voiceprint_manager:
                # 检查是否有足够长的音频进行声纹识别
                current_time = time.time()
                speech_duration = current_time - self.active_speech_time
                # logger.debug(f"在唤醒区间检测到新的语音段 [持续时间: {speech_duration:.2f}秒]")
                
                # 检查是否达到最小识别间隔，距离上次成功提交识别的时间间隔
                # 和最小音频长度, 这是用于声纹识别所需要的最小音频长度 默认值是 2 秒
                if (speech_duration >= self.voiceprint_manager.voice_print_len and 
                    current_time - self.last_recognition_time >= self.min_recognition_interval and
                    not self.voiceprint_manager.is_recognizing):
                    logger.debug(f"提交了 1 次声纹识别任务")
                    
                    # 从缓冲区提取音频数据
                    self._submit_audio_for_recognition()
            else:
                # 未启用声纹识别，直接触发打断
                self.triggered = True
                logger.debug(f"检测到持续语音，触发打断！[连续语音帧={self.speech_count}] [能量={energy:.2f}]")
                self._trigger_interrupt()
                self._reset_after_interrupt()
            
    def _handle_silence_frame(self):
        """处理静音帧"""
        self.speech_count = max(0, self.speech_count - 0.2)  # 逐渐减少语音计数
        self.silence_count += 1
        
        # 如果静音时间足够长，结束当前语音段
        if self.silence_count >= 100 and self.is_speech_active:  # 约2s的静音
            self.is_speech_active = False
            logger.debug(f"语音段结束，持续时间: {time.time() - self.active_speech_time:.2f}秒")
            
    def _submit_audio_for_recognition(self):
        """从缓冲区提取音频数据并提交给声纹识别器"""
        try:
            # 确保缓冲区中有足够的数据
            if len(self.audio_buffer) < 10:  # 至少需要10帧
                return
                
            # 计算所需的帧数
            required_frames = int(self.voiceprint_manager.voice_print_len * 1000 / self.frame_duration)
            frames_to_use = min(required_frames, len(self.audio_buffer))
            
            # 从缓冲区提取最近的帧
            recent_frames = list(self.audio_buffer)[-frames_to_use:]
            
            # 合并帧数据
            audio_data = b''.join(recent_frames)
            
            # 转换为NumPy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # 提交给声纹识别器
            if self.voiceprint_manager.submit_recognition_task(audio_array, self.sample_rate):
                # 成功提交识别任务的时间点，若上一个任务正在识别，则不会更新，因为不会进入 if
                self.last_recognition_time = time.time()
                logger.info(f"试图提交声纹识别任务，音频长度: {len(audio_array) / self.sample_rate:.2f}秒")
                
        except Exception as e:
            logger.error(f"提交音频进行声纹识别失败: {e}")
            
    def _check_voiceprint_result(self):
        """检查声纹识别结果并处理"""
        if not self.voiceprint_manager or not self.voiceprint_enabled:
            return
            
        # 检查是否有新的识别结果
        is_allowed, speaker_name = self.voiceprint_manager.is_allowed_speaker()
        
        if is_allowed and not self.triggered:
            # 识别到允许的说话者，触发打断
            self.triggered = True
            logger.info(f"声纹识别到允许的说话者({speaker_name})，触发打断")
            self._trigger_interrupt()
            self._reset_after_interrupt()
            
            # 添加：重置声纹识别结果
            if hasattr(self.voiceprint_manager, 'reset_recognition_result'):
                self.voiceprint_manager.reset_recognition_result()
            
    def _reset_state(self):
        """重置状态"""
        self.speech_count = 0
        self.silence_count = 0
        self.triggered = False
        self.is_speech_active = False
        
    def _reset_after_interrupt(self):
        """中断后重置状态"""
        self.speech_count = 0
        self.silence_count = 0
        self.is_speech_active = False
        
        # 暂时暂停以防止重复触发
        self.paused = True
        logger.debug("VAD检测器暂时暂停以防止重复触发")
        
        # 3秒后重新启用检测
        def resume_detector():
            if self.running and self.paused:
                self.paused = False
                self.triggered = False
                logger.info("VAD检测器恢复检测")
        
        # 取消已有的定时器（如果存在）
        if self.resume_timer and self.resume_timer.is_alive():
            self.resume_timer.cancel()
            
        # 启动定时器，2秒后恢复检测
        self.resume_timer = threading.Timer(2.0, resume_detector)
        self.resume_timer.name = "VAD-Resume-Timer"
        self.resume_timer.daemon = True
        self.resume_timer.start()
        
    def _trigger_interrupt(self):
        """触发打断"""
        # 通知应用程序中止当前语音输出
        logger.debug("VAD检测到用户打断，正在触发中断...")
        
        try:
            # 记录当前状态
            logger.info(f"打断前状态: 设备状态={self.app.device_state}, TTS播放={self.app.get_is_tts_playing()}, self.aborted: {self.app.aborted}")
            
            # 直接调用而不是通过schedule，减少延迟
            self.app.abort_speaking(AbortReason.USER_INTERRUPTION)
            
            # 记录打断后状态
            logger.info(f"打断后状态: 设备状态={self.app.device_state}, TTS播放={self.app.get_is_tts_playing()}, self.aborted: {self.app.aborted}")
        except Exception as e:
            logger.error(f"触发打断失败: {e}", exc_info=True)
            # 如果直接调用失败，回退到使用schedule
            self.app.schedule(lambda: self.app.abort_speaking(AbortReason.USER_INTERRUPTION))

    def is_active_and_hearing(self):
        """返回VAD是否在运行且最近检测到声音"""
        return self.running and self.is_speech_active

    def calibrate_threshold(self, seconds=2):
        """校准能量阈值"""
        energies = []
        for _ in range(int(self.sample_rate / self.frame_size * seconds)):
            frame = self._read_audio_frame()
            if frame:
                audio_data = np.frombuffer(frame, dtype=np.int16)
                energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                energies.append(energy)
        self.energy_threshold = np.mean(energies) + 3 * np.std(energies)
        logger.debug(f'自适应VAD阈值设为: {self.energy_threshold:.1f}')
        
    def set_allowed_speakers(self, speakers_list):
        """设置允许打断的说话者列表"""
        if self.voiceprint_manager:
            self.voiceprint_manager.set_allowed_speakers(speakers_list)
            logger.info(f"更新允许打断的说话者列表: {speakers_list}")
            
    def enable_voiceprint(self, enable=True):
        """启用或禁用声纹验证"""
        self.voiceprint_enabled = enable
        
        if self.voiceprint_manager:
            self.voiceprint_manager.enable(enable)
            logger.info(f"声纹验证功能已{'启用' if enable else '禁用'}")
        elif enable:
            # 如果启用但没有声纹管理器，尝试初始化
            try:
                self.voiceprint_manager = VoiceprintManager()
                self.voiceprint_manager.enable(True)
                logger.info("声纹验证功能已启用，声纹管理器已初始化")
            except Exception as e:
                logger.error(f"启用声纹验证失败: {e}")
                self.voiceprint_enabled = False
