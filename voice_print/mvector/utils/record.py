import os
import time
import numpy as np
import subprocess
from yeaudio.audio import AudioSegment  # 正确导入 AudioSegment 类
import soundfile


class RecordAudio:
    def __init__(self, channels=1, sample_rate=16000):
        # 录音参数
        self.channels = channels
        self.sample_rate = sample_rate
        print(f"RecordAudio初始化: 通道数={channels}, 采样率={sample_rate}")
        
    def record(self, record_seconds=3, save_path=None):
        """录音

        :param record_seconds: 录音时间，默认3秒
        :param save_path: 录音保存的路径，后缀名为wav
        :return: 音频的numpy数据
        """
        print(f"开始录音，持续{record_seconds}秒...")
        # 使用 arecord 命令录制音频到临时文件
        temp_file = "/tmp/temp_recording.wav"
        
        # 构建 arecord 命令
        cmd = f"arecord -d {record_seconds} -f S16_LE -c {self.channels} -r {self.sample_rate} {temp_file}"
        print(f"执行命令: {cmd}")
        
        # 使用subprocess执行命令，并捕获输出
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            print(f"录音命令执行结果: 返回码={result.returncode}")
            if result.stderr:
                print(f"录音命令错误输出: {result.stderr}")
        except Exception as e:
            print(f"录音命令执行异常: {str(e)}")
            raise
        
        # 检查临时文件是否存在
        if not os.path.exists(temp_file):
            print(f"错误: 临时录音文件未创建: {temp_file}")
            raise FileNotFoundError(f"录音文件未创建: {temp_file}")
        
        print(f"临时录音文件已创建: {temp_file}, 大小: {os.path.getsize(temp_file)} 字节")
        
        # 使用 AudioSegment 加载录制的音频
        try:
            print("开始加载音频文件...")
            audio_segment = AudioSegment.from_file(temp_file)
            print(f"音频加载成功: 采样率={audio_segment.sample_rate}, 时长={audio_segment.duration}秒")
        except Exception as e:
            print(f"加载音频文件失败: {str(e)}")
            raise
        
        # 获取音频数据
        audio_data = audio_segment.samples
        print(f"获取音频数据: shape={audio_data.shape}, dtype={audio_data.dtype}")
            
        print("录音处理完成!")
        
        # 保存录音文件（如果需要）
        if save_path is not None:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            try:
                soundfile.write(save_path, data=audio_data, samplerate=self.sample_rate)
                print(f"录音已保存到: {save_path}")
            except Exception as e:
                print(f"保存录音文件失败: {str(e)}")
        
        # 删除临时文件
        try:
            os.remove(temp_file)
            print(f"临时文件已删除: {temp_file}")
        except Exception as e:
            print(f"删除临时文件失败: {str(e)}")
        
        return audio_data
