#include "sample_common.h"
#include "speech_recognizer.h"
#include "audio_buffer.h"
#include "config.h"
// 音频回调函数，用于缓存音频数据
void AudioCallback(const int16_t *samples, size_t count)
{
    g_audioBuffer.addSamples(samples, count);
}

void ivwIns(const char *audio_path, int keywordfiles_count)
{
    AIKIT_ParamBuilder *paramBuilder = nullptr;
    AIKIT_DataBuilder *dataBuilder = nullptr;
    AIKIT_HANDLE *handle = nullptr;
    AiAudio *aiAudio_raw = nullptr;
    int fileSize = 0;
    int readLen = 0;
    FILE *file = nullptr;
    char data[320] = {0};
    int *index = NULL;
    int writetimes = 0;
    int ret = 0;

    paramBuilder = AIKIT_ParamBuilder::create();
    index = (int *)malloc(keywordfiles_count * sizeof(int));
    for (int i = 0; i < keywordfiles_count; ++i)
        index[i] = i;
    ret = AIKIT_SpecifyDataSet(IVW_ABILITY, "key_word", index, keywordfiles_count);
    printf("AIKIT_SpecifyDataSet:%d\n", ret);
    if (ret != 0)
    {
        goto exit;
    }
    paramBuilder->param("wdec_param_nCmThreshold", "0 0:1000", strlen("0 0:1000"));
    paramBuilder->param("gramLoad", true);

    ret = AIKIT_Start(IVW_ABILITY, AIKIT_Builder::build(paramBuilder), nullptr, &handle);
    printf("AIKIT_Start:%d\n", ret);
    if (ret != 0)
    {
        goto exit;
    }

    file = fopen(audio_path, "rb");
    if (file == nullptr)
    {
        printf("fopen failed\n");
        goto exit;
    }
    fseek(file, 0, SEEK_END);
    fileSize = ftell(file);
    fseek(file, 0, SEEK_SET);

    dataBuilder = AIKIT_DataBuilder::create();
    while (fileSize > 0)
    {
        readLen = fread(data, 1, sizeof(data), file);
        dataBuilder->clear();

        aiAudio_raw = AiAudio::get("wav")->data(data, 320)->valid();
        dataBuilder->payload(aiAudio_raw);
        ret = AIKIT_Write(handle, AIKIT_Builder::build(dataBuilder));
        writetimes++;
        if (ret != 0)
        {
            printf("AIKIT_Write:%d\n", ret);
            goto exit;
        }
        fileSize -= readLen;
    }
    ret = AIKIT_End(handle);

exit:
    if (index != NULL)
        free(index);
    if (file != nullptr)
    {
        fclose(file);
        file = nullptr;
    }
    if (handle != nullptr)
        AIKIT_End(handle);

    if (paramBuilder != nullptr)
    {
        delete paramBuilder;
        paramBuilder = nullptr;
    }

    if (dataBuilder != nullptr)
    {
        delete dataBuilder;
        dataBuilder = nullptr;
    }
}

/* demo recognize the audio from microphone */
static void demo_mic(int keywordfiles_count)
{
    printf("record start!\n");
    int errcode;

    struct speech_rec ivw;

    errcode = sr_init(&ivw, keywordfiles_count, IVW_ABILITY, SR_MIC);
    if (errcode)
    {
        printf("speech recognizer init failed\n");
        return;
    }
    else
    {
        // 设置音频回调
        sr_set_audio_callback(&ivw, AudioCallback);

        errcode = sr_start_listening(&ivw);
        if (errcode)
        {
            printf("start listen failed %d\n", errcode);
        }
    }

    char end_command;
    system("stty -icanon");
    while (1)
    {
        end_command = getchar();
        if (end_command == 's')
            break;
        sleep(1);
    }
    errcode = sr_stop_listening(&ivw);
    if (errcode)
    {
        printf("stop listening failed %d\n", errcode);
    }

    sr_uninit(&ivw);
}

void TestIvw70(const AIKIT_Callbacks &cbs)
{
    int ret = 0;
    int count = 1;
    int aud_src = 1;
    int times = 1;
    int loop = 1;

    printf("======================= IVW Start ===========================\n");
    AIKIT_RegisterAbilityCallback(IVW_ABILITY, cbs);

    ret = AIKIT_EngineInit(IVW_ABILITY, nullptr);
    if (ret != 0)
    {
        printf("AIKIT_EngineInit failed:%d\n", ret);
        goto exit;
    }

    if (times == 1)
    {
        AIKIT_CustomData customData;
        customData.key = "key_word";
        customData.index = 0;
        customData.from = AIKIT_DATA_PTR_PATH;
        customData.value = (void *)(RESOURCE_PATH "/ivw70/many-keywords.txt");
        customData.len = strlen(RESOURCE_PATH "/ivw70/many-keywords.txt");
        customData.next = nullptr;
        customData.reserved = nullptr;
        printf("AIKIT_LoadData start!\n");
        ret = AIKIT_LoadData(IVW_ABILITY, &customData);
        printf("AIKIT_LoadData end!\n");
        printf("AIKIT_LoadData:%d\n", ret);
        if (ret != 0)
        {
            goto exit;
        }

        times++;
    }

    // printf("=================================\n");
    // printf("  Where the audio comes from?\n"
    //        "  0: From a audio file.\n  1: From microphone.\n");
    // printf("=================================\n");
    // scanf("%d", &aud_src);

    if (aud_src != 0)
    {
        printf("Demo recognizing the speech from microphone\n");
        printf("\n\
=================================\n\
    press s to end recording\n\
==================================\n");

        // char start_command;
        // scanf("%s",&start_command);
        // if(start_command == 'r')
        demo_mic(count);
        // else
        // {
        //     printf("please press r to start recording, if not, it will quit!\n");
        //     scanf("%s",&start_command);
        //     if(start_command == 'r')
        //         demo_mic(count);
        // }
        printf("\n");
        printf("record end\n");
    }
    else
    {
        // 批量读取文件
        //  FILE *wav_scp = NULL;
        //  char wav_file[100];

        // wav_scp = fopen("wav.scp", "r");
        // if (wav_scp == NULL)
        //     goto exit;

        // while (fgets(wav_file, 100, wav_scp))
        // {
        //     wav_file[strcspn(wav_file, "\n")] = '\0';
        //     FILE *fin = fopen("ivw_result.txt", "ab");
        //     if (fin == nullptr)
        //     {
        //         printf("文件打开失败！");
        //         return;
        //     }
        //     fwrite(wav_file, sizeof(char), strlen(wav_file), fin);
        //     fwrite("\n", sizeof(char), strlen("\n"), fin);
        //     fclose(fin);
        //     ivwIns(wav_file, count);
        //     sleep(0.5);
        // }

        // if (wav_scp != NULL)
        // {
        //     fclose(wav_scp);
        //     wav_scp = NULL;
        // }

        // 读取单个音频
        while (loop--)
            ivwIns("./resource/ivw70/audio/xbxb.wav", 1);
    }
exit:
    AIKIT_UnLoadData(IVW_ABILITY, "key_word", 0);
    AIKIT_EngineUnInit(IVW_ABILITY);
    printf("======================= IVW End ===========================\n");
}