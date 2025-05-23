import pyaudio
import wave

# 配置参数
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
FRAMES_PER_BUFFER = 1024
RECORD_SECONDS = 5
OUTPUT_FILENAME = "test_output.wav"

# 初始化 PyAudio
audio = pyaudio.PyAudio()

# 列出所有可用的输入设备
print("\n可用的输入设备：")
input_devices = []
for i in range(audio.get_device_count()):
    device_info = audio.get_device_info_by_index(i)
    if device_info.get('maxInputChannels') > 0:  # 只显示输入设备
        print(f"设备 {i}: {device_info.get('name')}")
        print(f"  输入通道数: {device_info.get('maxInputChannels')}")
        print(f"  默认采样率: {device_info.get('defaultSampleRate')}")
        print()
        input_devices.append(i)

# 列出所有可用的输入设备
print("\n可用的输出设备：")
output_devices = []
for i in range(audio.get_device_count()):
    device_info = audio.get_device_info_by_index(i)
    if device_info.get('maxOutputChannels') > 0:  # 只显示输出设备
        print(f"设备 {i}: {device_info.get('name')}")
        print(f"  输出通道数: {device_info.get('maxOutputChannels')}")
        print(f"  默认采样率: {device_info.get('defaultSampleRate')}")
        print()
        output_devices.append(i)        

if not input_devices:
    print("没有找到可用的输入设备！")
    audio.terminate()
    exit()

# 选择输入设备
device_index = int(input("请输入要使用的设备编号: "))
if device_index not in input_devices:
    print("无效的设备编号！")
    audio.terminate()
    exit()

try:
    # 打开输入流
    stream = audio.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        input_device_index=device_index,  # 使用选择的设备
                        frames_per_buffer=FRAMES_PER_BUFFER)

    print("正在录音...")

    frames = []
    for _ in range(0, int(RATE / FRAMES_PER_BUFFER * RECORD_SECONDS)):
        data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
        frames.append(data)

    print("录音结束，保存中...")

    # 停止并关闭流
    stream.stop_stream()
    stream.close()
    audio.terminate()

    # 保存为 WAV 文件
    wf = wave.open(OUTPUT_FILENAME, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(audio.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()

    print(f"音频已保存为：{OUTPUT_FILENAME}")

except Exception as e:
    print("发生错误：", e)
    audio.terminate()