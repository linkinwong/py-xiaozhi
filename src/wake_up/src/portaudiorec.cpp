/*
 * @file
 * @brief record implementation using PortAudio
 *
 * This file provides the same interface as linuxrec.c but uses PortAudio
 * for cross-platform audio capture on macOS, Windows, and Linux
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <portaudio.h>
#include <pthread.h>
#include <unistd.h>
#include <assert.h>
#include <atomic>
#include "formats.h"
#include "portaudiorec.h"

#define DBG_ON 1

#if DBG_ON
#define dbg  printf
#else
#define dbg(...)
#endif

/* recorder states - same as in linuxrec.c */
enum {
    RECORD_STATE_CREATED,   /* Init     */
    RECORD_STATE_CLOSING,
    RECORD_STATE_READY,     /* Opened   */
    RECORD_STATE_STOPPING,  /* During Stop  */
    RECORD_STATE_RECORDING, /* Started  */
};

#define SAMPLE_RATE  16000
#define SAMPLE_BIT_SIZE 16
#define FRAME_CNT   10

/* A structure to store buffer information */
struct bufinfo {
    char *data;
    unsigned int bufsize;
};

/* Structure to pass to callback */
typedef struct {
    struct recorder *rec;
    std::atomic<bool> *isRunning;
} CallbackData;

/* PortAudio callback function */
static int paCallback(const void *inputBuffer, void *outputBuffer,
                     unsigned long framesPerBuffer,
                     const PaStreamCallbackTimeInfo* timeInfo,
                     PaStreamCallbackFlags statusFlags,
                     void *userData)
{
    CallbackData *data = (CallbackData*)userData;
    struct recorder *rec = data->rec;
    
    if (!rec || !inputBuffer || !(*data->isRunning)) {
        return paAbort;
    }
    
    // Calculate size in bytes
    unsigned long bytes = framesPerBuffer * (rec->bits_per_frame / 8);
    
    // Call the user callback with the data
    if (rec->on_data_ind) {
        rec->on_data_ind((char*)inputBuffer, bytes, rec->user_cb_para);
    }
    
    return paContinue;
}

/* Thread for audio recording */
static void* record_thread_proc(void *para)
{
    struct recorder *rec = (struct recorder*)para;
    CallbackData *data = (CallbackData*)rec->user_cb_para;
    
    // The main thread loop is handled by PortAudio internally
    // We just need to wait until recording is stopped
    while (*data->isRunning) {
        Pa_Sleep(100); // Sleep to avoid busy waiting
    }
    
    return NULL;
}

/* Get default input device */
record_dev_id get_default_input_dev()
{
    record_dev_id id;
    id.u.index = Pa_GetDefaultInputDevice();
    return id;
}

/* Get number of available input devices */
int get_input_dev_num()
{
    PaError err = Pa_Initialize();
    if (err != paNoError) {
        fprintf(stderr, "PortAudio initialization error: %s\n", Pa_GetErrorText(err));
        return 0;
    }
    
    int numDevices = Pa_GetDeviceCount();
    int inputDevices = 0;
    
    for (int i = 0; i < numDevices; i++) {
        const PaDeviceInfo *deviceInfo = Pa_GetDeviceInfo(i);
        if (deviceInfo->maxInputChannels > 0) {
            inputDevices++;
        }
    }
    
    Pa_Terminate();
    return inputDevices;
}

/* Create a recorder object */
int create_recorder(struct recorder **out_rec, 
                   void (*on_data_ind)(char *data, unsigned long len, void *user_para), 
                   void *user_cb_para)
{
    if (!out_rec) {
        return RECORD_ERR_INVAL;
    }
    
    // Initialize PortAudio
    PaError err = Pa_Initialize();
    if (err != paNoError) {
        fprintf(stderr, "PortAudio initialization error: %s\n", Pa_GetErrorText(err));
        return RECORD_ERR_GENERAL;
    }
    
    // Allocate recorder structure
    struct recorder *rec = (struct recorder *)malloc(sizeof(struct recorder));
    if (!rec) {
        Pa_Terminate();
        return RECORD_ERR_MEMFAIL;
    }
    
    // Clear memory
    memset(rec, 0, sizeof(struct recorder));
    
    // Set callback and user data
    rec->on_data_ind = on_data_ind;
    rec->user_cb_para = user_cb_para;
    rec->state = RECORD_STATE_CREATED;
    
    *out_rec = rec;
    return 0;
}

/* Destroy a recorder object */
void destroy_recorder(struct recorder *rec)
{
    if (!rec) {
        return;
    }
    
    // Make sure recorder is closed
    close_recorder(rec);
    
    // Free memory
    free(rec);
    
    // Terminate PortAudio
    Pa_Terminate();
}

/* Open the audio device */
int open_recorder(struct recorder *rec, record_dev_id dev, WAVEFORMATEX *fmt)
{
    if (!rec) {
        return RECORD_ERR_INVAL;
    }
    
    if (rec->state >= RECORD_STATE_READY) {
        return RECORD_ERR_ALREADY;
    }
    
    // Default format if none provided
    WAVEFORMATEX default_fmt = {
        WAVE_FORMAT_PCM,
        1,                  // Mono
        16000,              // 16kHz
        32000,              // Bytes per second
        2,                  // Block align
        16,                 // Bits per sample
        sizeof(WAVEFORMATEX)
    };
    
    if (!fmt) {
        fmt = &default_fmt;
    }
    
    // Set recorder parameters
    rec->bits_per_frame = fmt->wBitsPerSample;
    rec->period_frames = 1024; // Reasonable default for PortAudio
    rec->buffer_frames = 4096; // 4 periods
    
    // Create PortAudio stream
    PaStreamParameters inputParameters;
    inputParameters.device = dev.u.index;
    if (inputParameters.device == paNoDevice) {
        inputParameters.device = Pa_GetDefaultInputDevice();
    }
    
    const PaDeviceInfo *deviceInfo = Pa_GetDeviceInfo(inputParameters.device);
    if (!deviceInfo) {
        return RECORD_ERR_INVAL;
    }
    
    inputParameters.channelCount = fmt->nChannels;
    inputParameters.sampleFormat = paInt16; // Assuming 16-bit samples
    inputParameters.suggestedLatency = deviceInfo->defaultLowInputLatency;
    inputParameters.hostApiSpecificStreamInfo = NULL;
    
    // Create stream
    PaStream *stream;
    PaError err = Pa_OpenStream(
        &stream,
        &inputParameters,
        NULL, // No output
        fmt->nSamplesPerSec,
        rec->period_frames,
        paClipOff,
        NULL, // No callback yet
        NULL  // No user data yet
    );
    
    if (err != paNoError) {
        fprintf(stderr, "PortAudio error: %s\n", Pa_GetErrorText(err));
        return RECORD_ERR_GENERAL;
    }
    
    // Store the stream
    rec->wavein_hdl = stream;
    rec->state = RECORD_STATE_READY;
    
    return 0;
}

/* Close the recorder */
void close_recorder(struct recorder *rec)
{
    if (!rec || rec->state < RECORD_STATE_READY) {
        return;
    }
    
    // Stop recording if it's active
    if (rec->state == RECORD_STATE_RECORDING) {
        stop_record(rec);
    }
    
    // Close stream
    PaStream *stream = (PaStream*)rec->wavein_hdl;
    if (stream) {
        Pa_CloseStream(stream);
        rec->wavein_hdl = NULL;
    }
    
    rec->state = RECORD_STATE_CREATED;
}

/* Start recording */
int start_record(struct recorder *rec)
{
    if (!rec || rec->state != RECORD_STATE_READY) {
        return RECORD_ERR_NOT_READY;
    }
    
    // Create atomic flag for thread communication
    std::atomic<bool> *isRunning = new std::atomic<bool>(true);
    
    // Create callback data
    CallbackData *data = new CallbackData;
    data->rec = rec;
    data->isRunning = isRunning;
    
    // Set callback for the stream
    PaStream *stream = (PaStream*)rec->wavein_hdl;
    
    // Reset stream before starting
    PaError err = Pa_CloseStream(stream);
    if (err != paNoError) {
        fprintf(stderr, "Error closing stream: %s\n", Pa_GetErrorText(err));
        delete isRunning;
        delete data;
        return RECORD_ERR_GENERAL;
    }
    
    // Get format information
    WAVEFORMATEX default_fmt = {
        WAVE_FORMAT_PCM,
        1,                  // Mono
        16000,              // 16kHz
        32000,              // Bytes per second
        2,                  // Block align
        16,                 // Bits per sample
        sizeof(WAVEFORMATEX)
    };
    
    // Reopen stream with callback
    PaStreamParameters inputParameters;
    inputParameters.device = Pa_GetDefaultInputDevice();
    const PaDeviceInfo *deviceInfo = Pa_GetDeviceInfo(inputParameters.device);
    inputParameters.channelCount = 1; // Mono
    inputParameters.sampleFormat = paInt16;
    inputParameters.suggestedLatency = deviceInfo->defaultLowInputLatency;
    inputParameters.hostApiSpecificStreamInfo = NULL;
    
    err = Pa_OpenStream(
        &stream,
        &inputParameters,
        NULL, // No output
        SAMPLE_RATE,
        rec->period_frames,
        paClipOff,
        paCallback,
        data
    );
    
    if (err != paNoError) {
        fprintf(stderr, "Error opening stream: %s\n", Pa_GetErrorText(err));
        delete isRunning;
        delete data;
        return RECORD_ERR_GENERAL;
    }
    
    rec->wavein_hdl = stream;
    
    // Start the stream
    err = Pa_StartStream(stream);
    if (err != paNoError) {
        fprintf(stderr, "Error starting stream: %s\n", Pa_GetErrorText(err));
        delete isRunning;
        delete data;
        return RECORD_ERR_GENERAL;
    }
    
    // Create recording thread
    if (pthread_create(&rec->rec_thread, NULL, record_thread_proc, rec) != 0) {
        Pa_StopStream(stream);
        delete isRunning;
        delete data;
        return RECORD_ERR_GENERAL;
    }
    
    rec->state = RECORD_STATE_RECORDING;
    rec->user_cb_para = data; // Store for cleanup
    
    return 0;
}

/* Stop recording */
int stop_record(struct recorder *rec)
{
    if (!rec || rec->state != RECORD_STATE_RECORDING) {
        return RECORD_ERR_NOT_READY;
    }
    
    // Set state to stopping
    rec->state = RECORD_STATE_STOPPING;
    
    // Stop PortAudio stream
    PaStream *stream = (PaStream*)rec->wavein_hdl;
    PaError err = Pa_StopStream(stream);
    if (err != paNoError) {
        fprintf(stderr, "Error stopping stream: %s\n", Pa_GetErrorText(err));
    }
    
    // Signal thread to stop
    CallbackData *data = (CallbackData*)rec->user_cb_para;
    if (data && data->isRunning) {
        *data->isRunning = false;
    }
    
    // Wait for thread to complete
    pthread_join(rec->rec_thread, NULL);
    
    // Clean up
    if (data) {
        delete data->isRunning;
        delete data;
        rec->user_cb_para = NULL;
    }
    
    rec->state = RECORD_STATE_READY;
    return 0;
}

/* Check if recording is stopped */
int is_record_stopped(struct recorder *rec)
{
    if (!rec) {
        return 1; // Treat as stopped if no recorder
    }
    
    return (rec->state != RECORD_STATE_RECORDING);
} 