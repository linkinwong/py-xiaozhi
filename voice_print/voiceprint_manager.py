# voiceprint_manager.py
import logging
import threading
import queue
import numpy as np
import time
from src.utils.logging_config import get_logger
from voice_print.voice_recognition_wrapper import VoiceRecognitionWrapper

logger = get_logger(__name__)

class VoiceprintManager:
    """声纹管理器，负责声纹识别相关功能"""
    
    def __init__(self, threshold=0.18, voice_print_len=1.3):
        """初始化声纹管理器
        
        参数:
            threshold: 声纹识别阈值，值越小越严格
            voice_print_len: 声纹识别所需的最小音频长度(秒)
        """
        self.threshold = threshold
        self.voice_print_len = voice_print_len  # 单位：秒
        self.voice_recognizer = None
        self.allowed_speakers = []
        self.enabled = False
        
        # 识别任务队列和结果
        self.recognition_queue = queue.Queue()
        self.recognition_result = None
        self.is_recognizing = False
        
        # 初始化声纹识别器
        self._initialize_voice_recognizer()
        
        # 启动识别线程
        self.running = True
        self.recognition_thread = threading.Thread(
            target=self._recognition_worker,
            daemon=True,
            name="Voiceprint-Recognition-Thread"
        )
        self.recognition_thread.start()
        
        logger.info(f"声纹管理器初始化完成 [阈值={threshold}] [最小音频长度={voice_print_len}秒]")
        
    def _initialize_voice_recognizer(self):
        """初始化声纹识别器"""
        try:
            self.voice_recognizer = VoiceRecognitionWrapper(threshold=self.threshold)
            logger.info("声纹识别器初始化成功")
        except Exception as e:
            logger.error(f"声纹识别器初始化失败: {e}")
            self.voice_recognizer = None
            
    def enable(self, enable=True):
        """启用或禁用声纹验证"""
        self.enabled = enable
        logger.info(f"声纹验证功能已{'启用' if enable else '禁用'}")
        return True
        
    def set_threshold(self, threshold):
        """设置声纹识别阈值"""
        # 确保阈值在有效范围内
        threshold = max(0.01, min(0.99, threshold))
        self.threshold = threshold
        
        # 重新初始化声纹识别器
        try:
            self.voice_recognizer = None  # 清除现有实例
            self.voice_recognizer = VoiceRecognitionWrapper(threshold=threshold)
            logger.info(f"声纹识别器已重新初始化，阈值={threshold}")
            return True
        except Exception as e:
            logger.error(f"重新初始化声纹识别器失败: {e}")
            return False
            
    def set_voice_print_length(self, length_seconds):
        """设置声纹识别所需的最小音频长度"""
        if length_seconds < 0.5:
            length_seconds = 0.5  # 至少0.5秒
        elif length_seconds > 5.0:
            length_seconds = 5.0  # 最多5秒
            
        self.voice_print_len = length_seconds
        logger.info(f"声纹识别所需的最小音频长度已设为{length_seconds}秒")
        return True
        
    def set_allowed_speakers(self, speakers_list):
        """设置允许打断的说话者列表"""
        self.allowed_speakers = speakers_list
        logger.info(f"已更新允许打断的说话者列表: {speakers_list}")
        return True
        
    def add_allowed_speaker(self, name):
        """添加允许打断的说话者"""
        if name not in self.allowed_speakers:
            self.allowed_speakers.append(name)
            logger.info(f"已添加允许打断的说话者: {name}")
        return True
        
    def remove_allowed_speaker(self, name):
        """移除允许打断的说话者"""
        if name in self.allowed_speakers:
            self.allowed_speakers.remove(name)
            logger.info(f"已移除允许打断的说话者: {name}")
        return True
        
    def register(self, name, audio_path=None, audio_data=None, sample_rate=16000):
        """注册声纹
        
        参数:
            name: 说话者名称
            audio_path: 音频文件路径（与audio_data二选一）
            audio_data: 音频数据（与audio_path二选一）
            sample_rate: 音频采样率
            
        返回:
            bool: 是否注册成功
        """
        if not self.voice_recognizer:
            logger.error("声纹识别器未初始化，无法注册")
            return False
            
        try:
            # 根据传入参数选择注册方式
            if audio_path:
                # 从文件注册
                result = self.voice_recognizer.register(name, audio_path, sample_rate)
            elif audio_data is not None:
                # 从音频数据注册
                result = self.voice_recognizer.register(name, audio_data, sample_rate)
            else:
                logger.error("未提供有效的音频数据，无法注册声纹")
                return False
                
            if result:
                # 注册成功后，将新的说话者添加到允许列表
                if name not in self.allowed_speakers:
                    self.allowed_speakers.append(name)
                    logger.info(f"已添加新注册的说话者到允许列表: {name}")
                    
            return result
        except Exception as e:
            logger.error(f"注册声纹失败: {e}")
            return False
            
    def remove_user(self, name):
        """删除声纹
        
        参数:
            name: 要删除的说话者名称
            
        返回:
            bool: 是否删除成功
        """
        if not self.voice_recognizer:
            logger.error("声纹识别器未初始化，无法删除声纹")
            return False
            
        try:
            result = self.voice_recognizer.remove_user(name)
            
            if result:
                # 从允许列表中移除
                if name in self.allowed_speakers:
                    self.allowed_speakers.remove(name)
                    logger.info(f"已从允许列表中移除说话者: {name}")
                    
            return result
        except Exception as e:
            logger.error(f"删除声纹失败: {e}")
            return False
            
    def submit_recognition_task(self, audio_data, sample_rate=16000):
        """提交声纹识别任务
        
        参数:
            audio_data: 音频数据
            sample_rate: 采样率
            
        返回:
            bool: 是否成功提交任务
        """
        if not self.enabled or not self.voice_recognizer:
            return False
            
        # 如果正在识别中，则不接受新任务
        if self.is_recognizing:
            logger.debug("声纹识别任务已在进行中，忽略新任务")
            return False
            
        # 提交新任务
        try:
            self.recognition_queue.put((audio_data, sample_rate))
            logger.debug(f"已提交声纹识别任务，队列长度: {self.recognition_queue.qsize()}")
            return True
        except Exception as e:
            logger.error(f"提交声纹识别任务失败: {e}")
            return False
            
    def is_allowed_speaker(self, timeout=0):
        """检查最近的识别结果是否为允许的说话者
        
        参数:
            timeout: 等待结果的超时时间(秒)，0表示不等待
            
        返回:
            (bool, str): (是否是允许的说话者, 说话者名称)
            如果识别失败或未完成，返回(False, None)
        """
        # 如果没有识别结果，直接返回False
        if not self.recognition_result:
            return False, None
            
        name, score = self.recognition_result
        
        # 检查识别结果是否为允许的说话者
        if name in self.allowed_speakers:
            logger.info(f"识别到允许的说话者: {name}, 得分: {score:.4f}")
            return True, name
        else:
            logger.info(f"识别到非允许的说话者: {name}, 得分: {score:.4f}")
            return False, name
            
    def wait_for_result(self, timeout=3.0):
        """等待识别结果
        
        参数:
            timeout: 等待超时时间(秒)
            
        返回:
            (bool, str, float): (是否成功识别, 说话者名称, 得分)
            如果超时，返回(False, None, 0)
        """
        start_time = time.time()
        while self.is_recognizing and time.time() - start_time < timeout:
            time.sleep(0.1)
            
        if self.is_recognizing:
            # 超时
            return False, None, 0
            
        if not self.recognition_result:
            return False, None, 0
            
        name, score = self.recognition_result
        return True, name, score
            
    def _recognition_worker(self):
        """声纹识别工作线程"""
        logger.info("声纹识别工作线程已启动")
        
        while self.running:
            try:
                # 从队列中获取任务
                try:
                    audio_data, sample_rate = self.recognition_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                    
                # 标记正在识别
                self.is_recognizing = True
                self.recognition_result = None
                
                # 执行声纹识别
                logger.debug("开始执行声纹识别...")
                start_time = time.time()
                
                try:
                    name, score = self.voice_recognizer.recognize(audio_data, sample_rate)
                    elapsed = time.time() - start_time
                    logger.info(f"声纹识别完成: 说话者={name}, 得分={score:.4f}, 耗时={elapsed:.3f}秒")
                    
                    # 保存识别结果
                    self.recognition_result = (name, score)
                except Exception as e:
                    logger.error(f"声纹识别失败: {e}")
                    self.recognition_result = (None, 0)
                    
                # 标记识别完成
                self.is_recognizing = False
                
                # 处理队列中的任务完成
                self.recognition_queue.task_done()
                
            except Exception as e:
                logger.error(f"声纹识别工作线程异常: {e}")
                self.is_recognizing = False
                
        logger.info("声纹识别工作线程已退出")
        
    def shutdown(self):
        """关闭声纹管理器"""
        self.running = False
        
        # 清空队列
        while not self.recognition_queue.empty():
            try:
                self.recognition_queue.get_nowait()
                self.recognition_queue.task_done()
            except queue.Empty:
                break
                
        # 等待线程结束
        if self.recognition_thread and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=2.0)
            
        logger.info("声纹管理器已关闭")

    def reset_recognition_result(self):
        """重置声纹识别结果"""
        self.recognition_result = None
        self.recognition_score = 0.0

    def abort_speaking(self):
        """在 abort_speaking 中添加
        self.tts_already_aborted = True
        """
        self.tts_already_aborted = True

    def _handle_tts_stop(self):
        """在 _handle_tts_stop 开头添加
        if hasattr(self, 'tts_already_aborted') and self.tts_already_aborted:
            logger.info("TTS停止事件被中断处理过，不再重复处理")
            self.tts_already_aborted = False  # 重置标志
            return
        """
        if hasattr(self, 'tts_already_aborted') and self.tts_already_aborted:
            logger.info("TTS停止事件被中断处理过，不再重复处理")
            self.tts_already_aborted = False  # 重置标志
            return

        # 处理TTS停止的逻辑
        # ...

        # 如果TTS停止处理完成，返回True
        return True 