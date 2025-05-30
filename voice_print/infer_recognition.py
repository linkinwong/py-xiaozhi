import argparse
import functools
import sys
from scipy.io import wavfile

from mvector.predict import MVectorPredictor
from mvector.utils.record import RecordAudio
from mvector.utils.utils import add_arguments, print_arguments
from scipy.io import wavfile

parser = argparse.ArgumentParser(description=__doc__)
add_arg = functools.partial(add_arguments, argparser=parser)
add_arg('configs',          str,    'configs/cam++.yml',        '配置文件')
add_arg('use_gpu',          bool,   False,                       '是否使用GPU预测')
add_arg('audio_db_path',    str,    'audio_db/',                '音频库的路径')
add_arg('record_seconds',   int,    3,                          '录音长度')
add_arg('threshold',        float,  0.1,                        '判断是否为同一个人的阈值')
add_arg('model_path',       str,    'models/CAMPPlus_Fbank/best_model/', '导出的预测模型文件路径')
args = parser.parse_args()
print_arguments(args=args)

# 获取识别器
predictor = MVectorPredictor(configs=args.configs,
                             threshold=args.threshold,
                             audio_db_path=args.audio_db_path,
                             model_path=args.model_path,
                             use_gpu=args.use_gpu)

print("初始化录音设备...")
sys.stdout.flush()
record_audio = RecordAudio()
print("录音设备初始化完成！")
sys.stdout.flush()

while True:
    print("\n===== 声纹识别系统 =====")
    print("0: 注册音频到声纹库")
    print("1: 执行声纹识别")
    print("2: 删除用户")
    print("3: 退出程序")
    sys.stdout.flush()
    
    try:
        select_fun = int(input("请选择功能 (0-3): "))
        print(f"您选择了功能: {select_fun}")
        sys.stdout.flush()
        
        if select_fun == 0:
            print(f"按下回车键开始录音，录音{args.record_seconds}秒中...")
            sys.stdout.flush()
            input("请按回车继续: ")
            audio_data = record_audio.record(record_seconds=args.record_seconds)
            name = input("请输入该音频用户的名称: ")
            sys.stdout.flush()
            if name == '': continue
            predictor.register(user_name=name, audio_data=audio_data, sample_rate=record_audio.sample_rate)
        elif select_fun == 1:
            print(f"按下回车键开始录音，录音{args.record_seconds}秒中...")
            sys.stdout.flush()
            input("请按回车继续: ")
            audio_data = record_audio.record(record_seconds=args.record_seconds)
            # 打印audio_data的shape
            print(f"录音数据形状: {audio_data.shape}")
            print(f"录音数据样本: {audio_data[:10]}")
            sys.stdout.flush()
            # 把audio_data存储为wav格式的文件
            wavfile.write("audio_data_infer.wav", record_audio.sample_rate, audio_data)
            print("录音已保存为 audio_data_infer.wav")
            sys.stdout.flush()

            name, score = predictor.recognition(audio_data, sample_rate=record_audio.sample_rate)
            if name:
                print(f"识别说话的为：{name}，得分：{score}")
            else:
                print(f"没有识别到说话人，可能是没注册。")
            sys.stdout.flush()
        elif select_fun == 2:
            name = input("请输入要删除的用户名称: ")
            sys.stdout.flush()
            if name == '': continue
            result = predictor.remove_user(user_name=name)
            print(f"删除结果: {'成功' if result else '失败'}")
            sys.stdout.flush()
        elif select_fun == 3:
            print("退出程序")
            sys.stdout.flush()
            break
        else:
            print('请选择有效的功能编号 (0-3)')
            sys.stdout.flush()
    except ValueError:
        print("请输入有效的数字!")
        sys.stdout.flush()
    except Exception as e:
        print(f"发生错误: {e}")
        sys.stdout.flush()
