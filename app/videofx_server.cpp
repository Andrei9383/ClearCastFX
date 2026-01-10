/*
 * VideoFX Server - Real-time video effects with persistent model loading
 * Based on NVIDIA VideoFX SDK AigsEffectApp sample
 * 
 * Accepts commands via named pipe for UI integration
 */

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <poll.h>
#include <linux/videodev2.h>

#include <chrono>
#include <string>
#include <iostream>
#include <thread>
#include <atomic>
#include <mutex>

#include "nvCVOpenCV.h"
#include "nvVideoEffects.h"
#include "opencv2/opencv.hpp"

#define BAIL_IF_ERR(err) do { if (0 != (err)) { goto bail; } } while (0)
#define BAIL_IF_NULL(x, err, code) do { if ((void *)(x) == NULL) { err = code; goto bail; } } while (0)

// Command pipe path
const char* CMD_PIPE = "/tmp/videofx_cmd";
const char* VCAM_DEVICE = "/dev/video10";

// Global state (controlled by command pipe)
std::atomic<bool> g_running(true);
std::atomic<int> g_compMode(5);  // compBG by default
std::atomic<float> g_blurStrength(0.5f);
std::atomic<bool> g_vcamEnabled(false);
std::atomic<bool> g_showPreview(true);
std::atomic<bool> g_showOverlay(true);
std::mutex g_bgMutex;
std::string g_bgFile;
bool g_bgChanged = false;

// Composition modes
enum CompMode { compMatte, compLight, compGreen, compWhite, compNone, compBG, compBlur };

class VideoFXServer {
public:
    VideoFXServer() : _eff(nullptr), _bgblurEff(nullptr), _stream(nullptr), 
                      _inited(false), _showFPS(true), _framePeriod(0.f),
                      _batchOfStates(nullptr), _vcamFd(-1) {}
    
    ~VideoFXServer() { 
        destroyEffect(); 
        if (_vcamFd >= 0) close(_vcamFd);
    }

    NvCV_Status init(const std::string& modelDir, int mode) {
        NvCV_Status vfxErr = NVCV_SUCCESS;
        
        // Create Green Screen effect
        vfxErr = NvVFX_CreateEffect(NVVFX_FX_GREEN_SCREEN, &_eff);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error creating Green Screen effect: " << vfxErr << std::endl;
            return vfxErr;
        }
        
        // Set model directory
        vfxErr = NvVFX_SetString(_eff, NVVFX_MODEL_DIRECTORY, modelDir.c_str());
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error setting model directory: " << vfxErr << std::endl;
            return vfxErr;
        }
        
        // Set mode (0=quality, 1=performance)
        vfxErr = NvVFX_SetU32(_eff, NVVFX_MODE, mode);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error setting mode: " << vfxErr << std::endl;
            return vfxErr;
        }
        
        // Create CUDA stream
        vfxErr = NvVFX_CudaStreamCreate(&_stream);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error creating CUDA stream: " << vfxErr << std::endl;
            return vfxErr;
        }
        
        vfxErr = NvVFX_SetCudaStream(_eff, NVVFX_CUDA_STREAM, _stream);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error setting CUDA stream: " << vfxErr << std::endl;
            return vfxErr;
        }
        
        // Set max dimensions for dynamic resolution
        vfxErr = NvVFX_SetU32(_eff, NVVFX_MAX_INPUT_WIDTH, 1920);
        BAIL_IF_ERR(vfxErr);
        vfxErr = NvVFX_SetU32(_eff, NVVFX_MAX_INPUT_HEIGHT, 1080);
        BAIL_IF_ERR(vfxErr);
        vfxErr = NvVFX_SetU32(_eff, NVVFX_MAX_NUMBER_STREAMS, 1);
        BAIL_IF_ERR(vfxErr);
        
        // Load the model (this is the expensive part - done once!)
        std::cout << "Loading AI model (this takes a few seconds)..." << std::endl;
        vfxErr = NvVFX_Load(_eff);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error loading model: " << vfxErr << std::endl;
            return vfxErr;
        }
        std::cout << "Model loaded successfully!" << std::endl;
        
        // Allocate state for temporal consistency
        NvVFX_StateObjectHandle state;
        vfxErr = NvVFX_AllocateState(_eff, &state);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Error allocating state: " << vfxErr << std::endl;
            return vfxErr;
        }
        _stateArray.push_back(state);
        
        // Create background blur effect
        vfxErr = NvVFX_CreateEffect(NVVFX_FX_BGBLUR, &_bgblurEff);
        if (NVCV_SUCCESS != vfxErr) {
            std::cerr << "Warning: Could not create blur effect (code " << vfxErr << ")" << std::endl;
            _bgblurEff = nullptr;
        } else {
            NvVFX_SetCudaStream(_bgblurEff, NVVFX_CUDA_STREAM, _stream);
        }
        
        _inited = true;
        return NVCV_SUCCESS;
        
    bail:
        return vfxErr;
    }
    
    void destroyEffect() {
        for (auto& state : _stateArray) {
            if (_eff && state) NvVFX_DeallocateState(_eff, state);
        }
        _stateArray.clear();
        
        if (_batchOfStates) {
            free(_batchOfStates);
            _batchOfStates = nullptr;
        }
        
        if (_eff) {
            NvVFX_DestroyEffect(_eff);
            _eff = nullptr;
        }
        if (_bgblurEff) {
            NvVFX_DestroyEffect(_bgblurEff);
            _bgblurEff = nullptr;
        }
        if (_stream) {
            NvVFX_CudaStreamDestroy(_stream);
            _stream = nullptr;
        }
        
        NvCVImage_Dealloc(&_srcGPU);
        NvCVImage_Dealloc(&_dstGPU);
        NvCVImage_Dealloc(&_blurGPU);
    }
    
    bool initVirtualCamera(int width, int height) {
        _vcamFd = open(VCAM_DEVICE, O_WRONLY);
        if (_vcamFd < 0) {
            std::cerr << "Warning: Could not open virtual camera " << VCAM_DEVICE << std::endl;
            std::cerr << "Virtual camera disabled. Make sure v4l2loopback is loaded." << std::endl;
            return false;
        }
        
        struct v4l2_format fmt;
        memset(&fmt, 0, sizeof(fmt));
        fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
        fmt.fmt.pix.width = width;
        fmt.fmt.pix.height = height;
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_BGR24;
        fmt.fmt.pix.sizeimage = width * height * 3;
        fmt.fmt.pix.field = V4L2_FIELD_NONE;
        
        if (ioctl(_vcamFd, VIDIOC_S_FMT, &fmt) < 0) {
            std::cerr << "Warning: Could not set virtual camera format" << std::endl;
            close(_vcamFd);
            _vcamFd = -1;
            return false;
        }
        
        std::cout << "Virtual camera initialized: " << VCAM_DEVICE << std::endl;
        return true;
    }
    
    void writeToVirtualCamera(const cv::Mat& frame) {
        if (_vcamFd < 0 || !g_vcamEnabled) return;
        
        cv::Mat bgr;
        if (frame.channels() == 3) {
            bgr = frame;
        } else {
            cv::cvtColor(frame, bgr, cv::COLOR_GRAY2BGR);
        }
        
        size_t written = write(_vcamFd, bgr.data, bgr.total() * bgr.elemSize());
        (void)written;  // Ignore return value
    }
    
    int run(int cameraId) {
        cv::VideoCapture cap(cameraId);
        if (!cap.isOpened()) {
            std::cerr << "Error: Cannot open camera " << cameraId << std::endl;
            return 1;
        }
        
        cap.set(cv::CAP_PROP_FRAME_WIDTH, 1280);
        cap.set(cv::CAP_PROP_FRAME_HEIGHT, 720);
        cap.set(cv::CAP_PROP_FPS, 30);
        
        int width = (int)cap.get(cv::CAP_PROP_FRAME_WIDTH);
        int height = (int)cap.get(cv::CAP_PROP_FRAME_HEIGHT);
        std::cout << "Camera opened: " << width << "x" << height << std::endl;
        
        // Try to initialize virtual camera
        initVirtualCamera(width, height);
        
        // Allocate GPU buffers
        NvCV_Status vfxErr;
        vfxErr = NvCVImage_Alloc(&_srcGPU, width, height, NVCV_BGR, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
        if (vfxErr != NVCV_SUCCESS) {
            std::cerr << "Error allocating source GPU buffer: " << vfxErr << std::endl;
            return 1;
        }
        vfxErr = NvCVImage_Alloc(&_dstGPU, width, height, NVCV_A, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
        if (vfxErr != NVCV_SUCCESS) {
            std::cerr << "Error allocating dest GPU buffer: " << vfxErr << std::endl;
            return 1;
        }
        vfxErr = NvCVImage_Alloc(&_blurGPU, width, height, NVCV_BGR, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
        if (vfxErr != NVCV_SUCCESS) {
            std::cerr << "Error allocating blur GPU buffer: " << vfxErr << std::endl;
            return 1;
        }
        
        // Allocate batch states
        unsigned modelBatch;
        NvVFX_GetU32(_eff, NVVFX_MODEL_BATCH, &modelBatch);
        _batchOfStates = (NvVFX_StateObjectHandle*)malloc(sizeof(NvVFX_StateObjectHandle) * modelBatch);
        _batchOfStates[0] = _stateArray[0];
        
        cv::Mat frame, result, matte;
        cv::namedWindow("VideoFX Studio", cv::WINDOW_AUTOSIZE);
        
        std::cout << "\n=== VideoFX Studio Ready ===" << std::endl;
        std::cout << "Press 'Q' or ESC to quit" << std::endl;
        std::cout << "Press 'F' to toggle FPS display" << std::endl;
        std::cout << "Listening for commands on " << CMD_PIPE << std::endl;
        
        while (g_running) {
            cap >> frame;
            if (frame.empty()) continue;
            
            // Check for background change
            {
                std::lock_guard<std::mutex> lock(g_bgMutex);
                if (g_bgChanged && !g_bgFile.empty()) {
                    _bgImg = cv::imread(g_bgFile);
                    if (!_bgImg.empty()) {
                        cv::resize(_bgImg, _bgImg, cv::Size(width, height));
                        std::cout << "Background loaded: " << g_bgFile << std::endl;
                    } else {
                        std::cerr << "Failed to load background: " << g_bgFile << std::endl;
                    }
                    g_bgChanged = false;
                }
            }
            
            int mode = g_compMode.load();
            
            // Only run AI effect if needed
            if (mode != compNone && _inited) {
                processFrame(frame, result, matte, mode);
            } else {
                result = frame.clone();
            }
            
            // Create a display copy for overlay (keep result clean for vcam)
            cv::Mat display = result.clone();
            
            // Draw overlays only if enabled
            if (g_showOverlay) {
                // Draw FPS
                if (_showFPS) {
                    drawFPS(display);
                }
                
                // Draw mode indicator
                const char* modeNames[] = {"Matte", "Light", "Green", "White", "Original", "Background", "Blur"};
                if (mode >= 0 && mode < 7) {
                    cv::putText(display, modeNames[mode], cv::Point(10, 60), 
                               cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(255, 255, 0), 2);
                }
                
                // Virtual camera indicator
                if (g_vcamEnabled && _vcamFd >= 0) {
                    cv::putText(display, "VCAM", cv::Point(width - 80, 30), 
                               cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(0, 255, 0), 2);
                }
            }
            
            // Show preview window if enabled
            if (g_showPreview) {
                cv::imshow("VideoFX Studio", display);
            }
            
            // Write to virtual camera if enabled
            writeToVirtualCamera(result);
            
            // Handle keyboard
            int key = cv::waitKey(1);
            if (key == 'q' || key == 'Q' || key == 27) {  // 27 = ESC
                g_running = false;
                break;
            } else if (key == 'f' || key == 'F') {
                _showFPS = !_showFPS;
            }
        }
        
        cv::destroyAllWindows();
        cap.release();
        return 0;
    }
    
private:
    void processFrame(const cv::Mat& src, cv::Mat& result, cv::Mat& matte, int mode) {
        NvCV_Status vfxErr;
        
        matte = cv::Mat::zeros(src.size(), CV_8UC1);
        result.create(src.rows, src.cols, CV_8UC3);
        
        NvCVImage srcWrapper, dstWrapper;
        NVWrapperForCVMat(&src, &srcWrapper);
        NVWrapperForCVMat(&matte, &dstWrapper);
        
        // Transfer to GPU
        vfxErr = NvVFX_SetImage(_eff, NVVFX_INPUT_IMAGE, &_srcGPU);
        vfxErr = NvVFX_SetImage(_eff, NVVFX_OUTPUT_IMAGE, &_dstGPU);
        vfxErr = NvCVImage_Transfer(&srcWrapper, &_srcGPU, 1.0f, _stream, NULL);
        
        // Set state
        vfxErr = NvVFX_SetStateObjectHandleArray(_eff, NVVFX_STATE, _batchOfStates);
        
        // Run inference
        vfxErr = NvVFX_Run(_eff, 0);
        if (vfxErr != NVCV_SUCCESS) {
            src.copyTo(result);
            return;
        }
        
        // Transfer matte back
        vfxErr = NvCVImage_Transfer(&_dstGPU, &dstWrapper, 1.0f, _stream, NULL);
        
        // Composite based on mode
        NvCVImage resultWrapper;
        NVWrapperForCVMat(&result, &resultWrapper);
        
        switch (mode) {
            case compNone:
                src.copyTo(result);
                break;
                
            case compMatte:
                cv::cvtColor(matte, result, cv::COLOR_GRAY2BGR);
                break;
                
            case compGreen: {
                const unsigned char bgColor[3] = {0, 255, 0};
                NvCVImage_CompositeOverConstant(&srcWrapper, &dstWrapper, bgColor, &resultWrapper, _stream);
            } break;
            
            case compWhite: {
                const unsigned char bgColor[3] = {255, 255, 255};
                NvCVImage_CompositeOverConstant(&srcWrapper, &dstWrapper, bgColor, &resultWrapper, _stream);
            } break;
            
            case compLight:
                // Overlay the matte on the original
                for (int y = 0; y < src.rows; y++) {
                    for (int x = 0; x < src.cols; x++) {
                        float alpha = matte.at<uchar>(y, x) / 255.0f;
                        cv::Vec3b srcPix = src.at<cv::Vec3b>(y, x);
                        result.at<cv::Vec3b>(y, x) = cv::Vec3b(
                            srcPix[0] * (0.5f + 0.5f * alpha),
                            srcPix[1] * (0.5f + 0.5f * alpha),
                            srcPix[2] * (0.5f + 0.5f * alpha)
                        );
                    }
                }
                break;
                
            case compBG:
                if (!_bgImg.empty()) {
                    NvCVImage bgWrapper;
                    NVWrapperForCVMat(&_bgImg, &bgWrapper);
                    NvCVImage_Composite(&srcWrapper, &bgWrapper, &dstWrapper, &resultWrapper, _stream);
                } else {
                    // No background - show green with text
                    const unsigned char bgColor[3] = {0, 200, 0};
                    NvCVImage_CompositeOverConstant(&srcWrapper, &dstWrapper, bgColor, &resultWrapper, _stream);
                    cv::putText(result, "Select background in control panel", 
                               cv::Point(20, result.rows/2), cv::FONT_HERSHEY_SIMPLEX, 
                               0.8, cv::Scalar(255, 255, 255), 2);
                }
                break;
                
            case compBlur:
                if (_bgblurEff) {
                    float strength = g_blurStrength.load();
                    NvVFX_SetF32(_bgblurEff, NVVFX_STRENGTH, strength);
                    NvVFX_SetImage(_bgblurEff, NVVFX_INPUT_IMAGE_0, &_srcGPU);
                    NvVFX_SetImage(_bgblurEff, NVVFX_INPUT_IMAGE_1, &_dstGPU);
                    NvVFX_SetImage(_bgblurEff, NVVFX_OUTPUT_IMAGE, &_blurGPU);
                    NvVFX_Load(_bgblurEff);
                    vfxErr = NvVFX_Run(_bgblurEff, 0);
                    if (vfxErr == NVCV_SUCCESS) {
                        NvCVImage_Transfer(&_blurGPU, &resultWrapper, 1.0f, _stream, NULL);
                    } else {
                        src.copyTo(result);
                    }
                } else {
                    // Fallback: simple CPU blur
                    cv::Mat blurred;
                    cv::GaussianBlur(src, blurred, cv::Size(51, 51), 0);
                    for (int y = 0; y < src.rows; y++) {
                        for (int x = 0; x < src.cols; x++) {
                            float alpha = matte.at<uchar>(y, x) / 255.0f;
                            result.at<cv::Vec3b>(y, x) = 
                                src.at<cv::Vec3b>(y, x) * alpha + 
                                blurred.at<cv::Vec3b>(y, x) * (1.0f - alpha);
                        }
                    }
                }
                break;
        }
    }
    
    void drawFPS(cv::Mat& img) {
        auto now = std::chrono::high_resolution_clock::now();
        std::chrono::duration<float> dur = now - _lastTime;
        float t = dur.count();
        
        if (t > 0.f && t < 100.f) {
            if (_framePeriod > 0)
                _framePeriod += (t - _framePeriod) * 0.0625f;
            else
                _framePeriod = t;
            
            char buf[32];
            snprintf(buf, sizeof(buf), "%.1f FPS", 1.0f / _framePeriod);
            cv::putText(img, buf, cv::Point(10, 30), cv::FONT_HERSHEY_SIMPLEX, 
                       1, cv::Scalar(0, 255, 0), 2);
        }
        _lastTime = now;
    }
    
    NvVFX_Handle _eff;
    NvVFX_Handle _bgblurEff;
    CUstream _stream;
    bool _inited;
    bool _showFPS;
    float _framePeriod;
    std::chrono::high_resolution_clock::time_point _lastTime;
    
    NvCVImage _srcGPU;
    NvCVImage _dstGPU;
    NvCVImage _blurGPU;
    
    cv::Mat _bgImg;
    
    std::vector<NvVFX_StateObjectHandle> _stateArray;
    NvVFX_StateObjectHandle* _batchOfStates;
    
    int _vcamFd;
};

// Command listener thread
void commandListener() {
    // Create named pipe
    unlink(CMD_PIPE);
    mkfifo(CMD_PIPE, 0666);
    
    while (g_running) {
        int fd = open(CMD_PIPE, O_RDONLY | O_NONBLOCK);
        if (fd < 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }
        
        struct pollfd pfd = {fd, POLLIN, 0};
        while (g_running) {
            int ret = poll(&pfd, 1, 100);  // 100ms timeout
            if (ret > 0 && (pfd.revents & POLLIN)) {
                char buf[512];
                ssize_t n = read(fd, buf, sizeof(buf) - 1);
                if (n > 0) {
                    buf[n] = '\0';
                    // Remove newline
                    if (n > 0 && buf[n-1] == '\n') buf[n-1] = '\0';
                    
                    std::string cmd(buf);
                    
                    if (cmd == "QUIT") {
                        std::cout << "Received QUIT command" << std::endl;
                        g_running = false;
                    } else if (cmd.substr(0, 5) == "MODE:") {
                        int newMode = std::stoi(cmd.substr(5));
                        g_compMode.store(newMode);
                        std::cout << "Mode changed to: " << newMode << std::endl;
                    } else if (cmd.substr(0, 3) == "BG:") {
                        std::lock_guard<std::mutex> lock(g_bgMutex);
                        g_bgFile = cmd.substr(3);
                        g_bgChanged = true;
                        std::cout << "Background set to: " << g_bgFile << std::endl;
                    } else if (cmd.substr(0, 5) == "BLUR:") {
                        float val = std::stof(cmd.substr(5));
                        g_blurStrength.store(val);
                        std::cout << "Blur strength: " << val << std::endl;
                    } else if (cmd == "VCAM:on") {
                        g_vcamEnabled.store(true);
                        std::cout << "Virtual camera enabled" << std::endl;
                    } else if (cmd == "VCAM:off") {
                        g_vcamEnabled.store(false);
                        std::cout << "Virtual camera disabled" << std::endl;
                    } else if (cmd == "PREVIEW:on") {
                        g_showPreview.store(true);
                        std::cout << "Preview window shown" << std::endl;
                    } else if (cmd == "PREVIEW:off") {
                        g_showPreview.store(false);
                        cv::destroyWindow("VideoFX Studio");
                        std::cout << "Preview window hidden" << std::endl;
                    } else if (cmd == "OVERLAY:on") {
                        g_showOverlay.store(true);
                        std::cout << "Overlay enabled" << std::endl;
                    } else if (cmd == "OVERLAY:off") {
                        g_showOverlay.store(false);
                        std::cout << "Overlay disabled" << std::endl;
                    }
                }
            }
        }
        close(fd);
    }
    
    unlink(CMD_PIPE);
}

int main(int argc, char** argv) {
    std::string modelDir = "/usr/local/VideoFX/lib/models";
    int cameraId = 0;
    int mode = 0;  // 0=quality, 1=performance
    
    // Parse arguments
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg.substr(0, 12) == "--model_dir=") {
            modelDir = arg.substr(12);
        } else if (arg.substr(0, 9) == "--camera=") {
            cameraId = std::stoi(arg.substr(9));
        } else if (arg.substr(0, 7) == "--mode=") {
            mode = std::stoi(arg.substr(7));
        } else if (arg == "--performance" || arg == "-p") {
            mode = 1;
        }
    }
    
    std::cout << "========================================" << std::endl;
    std::cout << "     VideoFX Studio - AI Video Effects" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Model directory: " << modelDir << std::endl;
    std::cout << "Camera ID: " << cameraId << std::endl;
    std::cout << "Mode: " << (mode == 0 ? "Quality" : "Performance") << std::endl;
    std::cout << std::endl;
    
    // Start command listener
    std::thread cmdThread(commandListener);
    
    VideoFXServer server;
    NvCV_Status err = server.init(modelDir, mode);
    if (err != NVCV_SUCCESS) {
        std::cerr << "Failed to initialize VideoFX: " << err << std::endl;
        g_running = false;
        cmdThread.join();
        return 1;
    }
    
    int result = server.run(cameraId);
    
    g_running = false;
    cmdThread.join();
    
    std::cout << "VideoFX Studio closed." << std::endl;
    return result;
}
