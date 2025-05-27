# voice_recognition_wrapper.py
import ctypes
import numpy as np
from mvector.predict import MVectorPredictor
import os
from scipy.io import wavfile


class VoiceRecognitionWrapper:
    def __init__(self, threshold=0.18):
        # 获取当前文件所在目录的绝对路径
        base_dir = os.path.dirname(os.path.abspath(__file__))

        self.predictor = MVectorPredictor(
            configs=os.path.join(base_dir, "configs/cam++.yml"),
            threshold=threshold,
            audio_db_path=os.path.join(base_dir, "audio_db/"),
            model_path=os.path.join(base_dir, "models/CAMPPlus_Fbank/best_model/"),
            use_gpu=False,  # 算力受限情况下建议用CPU
        )

    def recognize(self, audio_data, sample_rate):
        # print("audio_data前10个：", audio_data[:10])
        # # 把audio_data存储为wav格式的文件
        # wavfile.write("audio_data_mine.wav", sample_rate, audio_data)
        name, score = self.predictor.recognition(audio_data, sample_rate=sample_rate)
        return name, score

    def recognize_from_file(self, audio_path):
        """从音频文件中识别声纹
        Args:
            audio_path: 音频文件路径
        Returns:
            name: 识别到的用户名
            score: 相似度得分
        """
        name, score = self.predictor.recognition(audio_path)
        return name, score

    def register(self, name, audio_path, sample_rate):
        if name == "":
            print("请输入一个有效的名称")
            return False
        result = self.predictor.register(
            user_name=name, audio_data=audio_path, sample_rate=sample_rate
        )
        return result[0]

    def remove_user(self, name):
        if name == "":
            print("请输入一个有效的名称")
            return False
        return self.predictor.remove_user(name)

# C接口
recognizer = None


def init_recognizer(threshold=0.18):
    global recognizer
    recognizer = VoiceRecognitionWrapper(threshold=threshold)

def register(name, audio_path, sample_rate):
    # 实现异常处理。注册不成功，则返回特殊结果
    try:
        return recognizer.register(name, audio_path, sample_rate)
    except Exception as e:
        print(f"注册声纹失败: {e}")
        return False

def remove_user(name):
    try:
        return recognizer.remove_user(name)
    except Exception as e:
        print(f"删除用户声纹失败: {e}")
        return False

def recognize_voice(audio_data, audio_len, sample_rate):
    # 打印接收到的数据信息
    # print(f"数据步长: {audio_data.strides}")
    # print("Python端接收到的数据信息:")
    # print(f"数据形状: {audio_data.shape}")
    # print(f"数据前10个采样点:")
    # print(audio_data[:10])
    
    if recognizer is None:
        return "", -1.0
    # 打印audio_data的shape,
    # print(audio_data.shape)
    name, score = recognizer.recognize(audio_data, sample_rate)
    if name is None and score is None:
        return "unkown", 0.0
    return name, score


def recognize_voice_from_file(audio_path):
    if recognizer is None:
        return "", -1.0

    name, score = recognizer.recognize_from_file(audio_path)
    return name, score
