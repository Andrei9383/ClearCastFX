#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "nvCVOpenCV.h"
#include "nvVideoEffects.h"
#include "opencv2/opencv.hpp"

//  Paths ───────────────────────────────────────────────────────────────
static const char *SHARED_DIR      = "/tmp/blucast";
static const char *CMD_PIPE_PATH   = "/tmp/blucast/cmd.pipe";
static const char *CONSUMERS_FILE  = "/tmp/blucast/consumers";
static const char *PREVIEW_FILE    = "/tmp/blucast/preview.jpg";
static const char *PREVIEW_TMP     = "/tmp/blucast/preview.jpg.tmp";
static const char *PID_FILE        = "/tmp/blucast/server.pid";
static const char *VCAM_DEVICE     = "/dev/video10";

//  Global state
static std::atomic<bool>  g_running{true};
static std::atomic<bool>  g_windowVisible{true};
static std::atomic<int>   g_effectMode{6};
static std::atomic<float> g_blurStrength{0.5f};
static std::atomic<int>   g_cameraWidth{1280};
static std::atomic<int>   g_cameraHeight{720};
static std::atomic<int>   g_cameraFps{30};
static std::atomic<bool>  g_cameraSettingsChanged{false};

static std::mutex  g_deviceMutex;
static std::string g_inputDevice;
static bool        g_deviceChanged = false;

static std::mutex  g_bgMutex;
static std::string g_bgFile;
static bool        g_bgChanged = false;

//  Effect modes ────────────────────────────────────────────────────────
enum EffectMode {
    MODE_MATTE    = 0,
    MODE_LIGHT    = 1,
    MODE_GREEN    = 2,
    MODE_WHITE    = 3,
    MODE_NONE     = 4,
    MODE_BG       = 5,
    MODE_BLUR     = 6,
    MODE_DENOISE  = 7,
};

//  Utility: read consumer count from file ──────────────────────────────
static int readConsumerCount() {
    FILE *f = fopen(CONSUMERS_FILE, "r");
    if (!f) return 0;
    int n = 0;
    if (fscanf(f, "%d", &n) != 1) n = 0;
    fclose(f);
    return n < 0 ? 0 : n;
}

//  Utility: write PID file ─────────────────────────────────────────────
static void writePidFile() {
    FILE *f = fopen(PID_FILE, "w");
    if (f) {
        fprintf(f, "%d\n", getpid());
        fclose(f);
    }
}

// ══════════════════════════════════════════════════════════════════════════
// Virtual Camera
// ══════════════════════════════════════════════════════════════════════════
class VirtualCamera {
public:
    VirtualCamera() : fd_(-1), width_(0), height_(0) {}

    ~VirtualCamera() {
        if (fd_ >= 0) {
            int type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
            ioctl(fd_, VIDIOC_STREAMOFF, &type);
            close(fd_);
        }
    }

    bool open(int width, int height, int fps) {
        // reopen if resolution changed
        if (fd_ >= 0 && (width_ != width || height_ != height)) {
            int type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
            ioctl(fd_, VIDIOC_STREAMOFF, &type);
            close(fd_);
            fd_ = -1;
        }
        if (fd_ >= 0) return true;

        fd_ = ::open(VCAM_DEVICE, O_WRONLY);
        if (fd_ < 0) {
            std::cerr << "Cannot open virtual camera " << VCAM_DEVICE << std::endl;
            return false;
        }

        struct v4l2_format fmt{};
        fmt.type                 = V4L2_BUF_TYPE_VIDEO_OUTPUT;
        fmt.fmt.pix.width        = width;
        fmt.fmt.pix.height       = height;
        fmt.fmt.pix.pixelformat  = V4L2_PIX_FMT_YUV420;
        fmt.fmt.pix.sizeimage    = width * height * 3 / 2;
        fmt.fmt.pix.field        = V4L2_FIELD_NONE;
        if (ioctl(fd_, VIDIOC_S_FMT, &fmt) < 0) {
            std::cerr << "Warning: VIDIOC_S_FMT failed (device may be locked)" << std::endl;
        }

        struct v4l2_streamparm parm{};
        parm.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
        parm.parm.output.timeperframe.numerator   = 1;
        parm.parm.output.timeperframe.denominator = fps > 0 ? fps : 30;
        ioctl(fd_, VIDIOC_S_PARM, &parm);

        width_  = width;
        height_ = height;
        std::cout << "Virtual camera: " << VCAM_DEVICE
                  << " @ " << width << "x" << height
                  << " " << fps << "fps" << std::endl;
        return true;
    }

    void writeFrame(const cv::Mat &bgr) {
        if (fd_ < 0) return;
        cv::Mat yuv;
        if (bgr.cols != width_ || bgr.rows != height_) {
            cv::Mat resized;
            cv::resize(bgr, resized, cv::Size(width_, height_));
            cv::cvtColor(resized, yuv, cv::COLOR_BGR2YUV_I420);
        } else {
            cv::cvtColor(bgr, yuv, cv::COLOR_BGR2YUV_I420);
        }
        ::write(fd_, yuv.data, yuv.total() * yuv.elemSize());
    }

    void writeIdleFrame() {
        if (fd_ < 0) return;
        if (idleYuv_.empty() || idleW_ != width_ || idleH_ != height_) {
            int w = width_  > 0 ? width_  : 1280;
            int h = height_ > 0 ? height_ : 720;
            cv::Mat black = cv::Mat::zeros(h, w, CV_8UC3);
            cv::putText(black, "Camera Off",
                        cv::Point(w / 2 - 120, h / 2),
                        cv::FONT_HERSHEY_SIMPLEX, 1.5,
                        cv::Scalar(80, 80, 80), 2);
            cv::cvtColor(black, idleYuv_, cv::COLOR_BGR2YUV_I420);
            idleW_ = w;
            idleH_ = h;
        }
        ::write(fd_, idleYuv_.data, idleYuv_.total() * idleYuv_.elemSize());
    }

    bool isOpen() const { return fd_ >= 0; }
    int width()  const { return width_; }
    int height() const { return height_; }

private:
    int fd_, width_, height_;
    cv::Mat idleYuv_;
    int idleW_ = 0, idleH_ = 0;
};

// ══════════════════════════════════════════════════════════════════════════
// Preview writer
// ══════════════════════════════════════════════════════════════════════════
static void writePreviewJpeg(const cv::Mat &bgr) {
    static std::vector<int> params = {cv::IMWRITE_JPEG_QUALITY, 80};
    std::vector<uchar> buf;
    cv::imencode(".jpg", bgr, buf, params);

    FILE *f = fopen(PREVIEW_TMP, "wb");
    if (f) {
        fwrite(buf.data(), 1, buf.size(), f);
        fclose(f);
        rename(PREVIEW_TMP, PREVIEW_FILE);
    }
}

// ══════════════════════════════════════════════════════════════════════════
// VideoFX Processor
// ══════════════════════════════════════════════════════════════════════════
class VideoFXProcessor {
public:
    VideoFXProcessor()
        : eff_(nullptr), bgblurEff_(nullptr), artifactEff_(nullptr),
          stream_(nullptr), inited_(false), artifactInited_(false),
          batchOfStates_(nullptr) {}

    ~VideoFXProcessor() { destroy(); }

    bool init(const std::string &modelDir, int mode) {
        NvCV_Status err;

        err = NvVFX_CreateEffect(NVVFX_FX_GREEN_SCREEN, &eff_);
        if (err != NVCV_SUCCESS) {
            std::cerr << "Error creating Green Screen effect: " << err << std::endl;
            return false;
        }

        NvVFX_SetString(eff_, NVVFX_MODEL_DIRECTORY, modelDir.c_str());
        NvVFX_SetU32(eff_, NVVFX_MODE, mode);
        NvVFX_CudaStreamCreate(&stream_);
        NvVFX_SetCudaStream(eff_, NVVFX_CUDA_STREAM, stream_);
        NvVFX_SetU32(eff_, NVVFX_MAX_INPUT_WIDTH, 1920);
        NvVFX_SetU32(eff_, NVVFX_MAX_INPUT_HEIGHT, 1080);
        NvVFX_SetU32(eff_, NVVFX_MAX_NUMBER_STREAMS, 1);

        std::cout << "Loading AI model..." << std::endl;
        err = NvVFX_Load(eff_);
        if (err != NVCV_SUCCESS) {
            std::cerr << "Error loading model: " << err << std::endl;
            return false;
        }
        std::cout << "Model loaded." << std::endl;

        NvVFX_StateObjectHandle state;
        NvVFX_AllocateState(eff_, &state);
        stateArray_.push_back(state);

        // Background blur
        if (NvVFX_CreateEffect(NVVFX_FX_BGBLUR, &bgblurEff_) == NVCV_SUCCESS) {
            NvVFX_SetCudaStream(bgblurEff_, NVVFX_CUDA_STREAM, stream_);
        } else {
            bgblurEff_ = nullptr;
        }

        // Artifact reduction (denoise)
        if (NvVFX_CreateEffect(NVVFX_FX_ARTIFACT_REDUCTION, &artifactEff_) == NVCV_SUCCESS) {
            NvVFX_SetCudaStream(artifactEff_, NVVFX_CUDA_STREAM, stream_);
            NvVFX_SetString(artifactEff_, NVVFX_MODEL_DIRECTORY, modelDir.c_str());
        } else {
            artifactEff_ = nullptr;
        }

        inited_ = true;
        return true;
    }

    // Allocate GPU buffers for a given resolution. Must be called when resolution changes.
    bool allocate(int width, int height) {
        deallocateBuffers();
        NvCV_Status err;
        err = NvCVImage_Alloc(&srcGPU_,  width, height, NVCV_BGR, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
        if (err != NVCV_SUCCESS) return false;
        err = NvCVImage_Alloc(&dstGPU_,  width, height, NVCV_A,   NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
        if (err != NVCV_SUCCESS) return false;
        err = NvCVImage_Alloc(&blurGPU_, width, height, NVCV_BGR, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
        if (err != NVCV_SUCCESS) return false;

        NvCVImage_Alloc(&artifactInGPU_,  width, height, NVCV_BGR, NVCV_F32, NVCV_PLANAR, NVCV_GPU, 1);
        NvCVImage_Alloc(&artifactOutGPU_, width, height, NVCV_BGR, NVCV_F32, NVCV_PLANAR, NVCV_GPU, 1);

        unsigned modelBatch = 1;
        NvVFX_GetU32(eff_, NVVFX_MODEL_BATCH, &modelBatch);
        batchOfStates_ = (NvVFX_StateObjectHandle *)malloc(
            sizeof(NvVFX_StateObjectHandle) * modelBatch);
        batchOfStates_[0] = stateArray_[0];

        if (artifactEff_ && !artifactInited_ && artifactInGPU_.pixels && artifactOutGPU_.pixels) {
            NvVFX_SetImage(artifactEff_, NVVFX_INPUT_IMAGE,  &artifactInGPU_);
            NvVFX_SetImage(artifactEff_, NVVFX_OUTPUT_IMAGE, &artifactOutGPU_);
            if (NvVFX_Load(artifactEff_) == NVCV_SUCCESS) {
                artifactInited_ = true;
            }
        }

        bufWidth_  = width;
        bufHeight_ = height;
        return true;
    }

    cv::Mat process(const cv::Mat &frame, int mode) {
        if (!inited_ || mode == MODE_NONE) return frame.clone();
        if (frame.cols != bufWidth_ || frame.rows != bufHeight_) return frame.clone();

        cv::Mat matte = cv::Mat::zeros(frame.size(), CV_8UC1);
        cv::Mat result(frame.rows, frame.cols, CV_8UC3);

        NvCVImage srcW, matteW, resultW;
        NVWrapperForCVMat(&frame,  &srcW);
        NVWrapperForCVMat(&matte,  &matteW);
        NVWrapperForCVMat(&result, &resultW);

        NvVFX_SetImage(eff_, NVVFX_INPUT_IMAGE,  &srcGPU_);
        NvVFX_SetImage(eff_, NVVFX_OUTPUT_IMAGE, &dstGPU_);
        NvCVImage_Transfer(&srcW, &srcGPU_, 1.0f, stream_, NULL);
        NvVFX_SetStateObjectHandleArray(eff_, NVVFX_STATE, batchOfStates_);

        if (NvVFX_Run(eff_, 0) != NVCV_SUCCESS) return frame.clone();
        NvCVImage_Transfer(&dstGPU_, &matteW, 1.0f, stream_, NULL);

        switch (mode) {
        case MODE_MATTE:
            cv::cvtColor(matte, result, cv::COLOR_GRAY2BGR);
            break;

        case MODE_GREEN: {
            const unsigned char bg[3] = {0, 255, 0};
            NvCVImage_CompositeOverConstant(&srcW, &matteW, bg, &resultW, stream_);
            break;
        }
        case MODE_WHITE: {
            const unsigned char bg[3] = {255, 255, 255};
            NvCVImage_CompositeOverConstant(&srcW, &matteW, bg, &resultW, stream_);
            break;
        }
        case MODE_LIGHT:
            for (int y = 0; y < frame.rows; y++) {
                for (int x = 0; x < frame.cols; x++) {
                    float a = matte.at<uchar>(y, x) / 255.0f;
                    auto p = frame.at<cv::Vec3b>(y, x);
                    result.at<cv::Vec3b>(y, x) = cv::Vec3b(
                        p[0] * (0.5f + 0.5f * a),
                        p[1] * (0.5f + 0.5f * a),
                        p[2] * (0.5f + 0.5f * a));
                }
            }
            break;

        case MODE_BG:
            if (!bgImg_.empty()) {
                NvCVImage bgW;
                NVWrapperForCVMat(&bgImg_, &bgW);
                NvCVImage_Composite(&srcW, &bgW, &matteW, &resultW, stream_);
            } else {
                const unsigned char bg[3] = {0, 200, 0};
                NvCVImage_CompositeOverConstant(&srcW, &matteW, bg, &resultW, stream_);
            }
            break;

        case MODE_BLUR:
            if (bgblurEff_) {
                NvVFX_SetF32(bgblurEff_, NVVFX_STRENGTH, g_blurStrength.load());
                NvVFX_SetImage(bgblurEff_, NVVFX_INPUT_IMAGE_0, &srcGPU_);
                NvVFX_SetImage(bgblurEff_, NVVFX_INPUT_IMAGE_1, &dstGPU_);
                NvVFX_SetImage(bgblurEff_, NVVFX_OUTPUT_IMAGE,  &blurGPU_);
                NvVFX_Load(bgblurEff_);
                if (NvVFX_Run(bgblurEff_, 0) == NVCV_SUCCESS) {
                    NvCVImage_Transfer(&blurGPU_, &resultW, 1.0f, stream_, NULL);
                } else {
                    frame.copyTo(result);
                }
            }
            break;

        case MODE_DENOISE:
            if (artifactEff_ && artifactInited_) {
                NvCV_Status err;
                err = NvCVImage_Transfer(&srcW, &artifactInGPU_, 1.0f / 255.0f, stream_, NULL);
                if (err == NVCV_SUCCESS) err = NvVFX_Run(artifactEff_, 0);
                if (err == NVCV_SUCCESS) {
                    NvCVImage_Transfer(&artifactOutGPU_, &resultW, 255.0f, stream_, NULL);
                } else {
                    frame.copyTo(result);
                }
            } else {
                frame.copyTo(result);
            }
            break;

        default:
            frame.copyTo(result);
        }

        return result;
    }

    void setBackground(const std::string &path, int width, int height) {
        bgImg_ = cv::imread(path);
        if (!bgImg_.empty()) {
            cv::resize(bgImg_, bgImg_, cv::Size(width, height));
            std::cout << "Background: " << path << std::endl;
        }
    }

private:
    void deallocateBuffers() {
        NvCVImage_Dealloc(&srcGPU_);
        NvCVImage_Dealloc(&dstGPU_);
        NvCVImage_Dealloc(&blurGPU_);
        NvCVImage_Dealloc(&artifactInGPU_);
        NvCVImage_Dealloc(&artifactOutGPU_);
        if (batchOfStates_) { free(batchOfStates_); batchOfStates_ = nullptr; }
        bufWidth_ = bufHeight_ = 0;
    }

    void destroy() {
        for (auto &s : stateArray_) {
            if (eff_ && s) NvVFX_DeallocateState(eff_, s);
        }
        stateArray_.clear();
        deallocateBuffers();
        if (eff_)         { NvVFX_DestroyEffect(eff_);         eff_ = nullptr; }
        if (bgblurEff_)   { NvVFX_DestroyEffect(bgblurEff_);   bgblurEff_ = nullptr; }
        if (artifactEff_) { NvVFX_DestroyEffect(artifactEff_); artifactEff_ = nullptr; }
        if (stream_)      { NvVFX_CudaStreamDestroy(stream_);  stream_ = nullptr; }
    }

    NvVFX_Handle eff_, bgblurEff_, artifactEff_;
    CUstream stream_;
    bool inited_, artifactInited_;
    int bufWidth_ = 0, bufHeight_ = 0;

    NvCVImage srcGPU_{}, dstGPU_{}, blurGPU_{};
    NvCVImage artifactInGPU_{}, artifactOutGPU_{};
    std::vector<NvVFX_StateObjectHandle> stateArray_;
    NvVFX_StateObjectHandle *batchOfStates_;
    cv::Mat bgImg_;
};

// ══════════════════════════════════════════════════════════════════════════
// Command Listener
// ══════════════════════════════════════════════════════════════════════════
static void commandListener() {
    mkdir(SHARED_DIR, 0777);
    unlink(CMD_PIPE_PATH);
    mkfifo(CMD_PIPE_PATH, 0666);

    while (g_running) {
        // Open read-write to avoid blocking on open when no writer
        int fd = ::open(CMD_PIPE_PATH, O_RDWR | O_NONBLOCK);
        if (fd < 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            continue;
        }

        struct pollfd pfd = {fd, POLLIN, 0};
        while (g_running) {
            int ret = poll(&pfd, 1, 500);
            if (ret < 0) break;
            if (ret == 0) continue;
            if (pfd.revents & (POLLHUP | POLLERR)) break;
            if (!(pfd.revents & POLLIN)) continue;

            char buf[1024];
            ssize_t n = ::read(fd, buf, sizeof(buf) - 1);
            if (n <= 0) break;
            buf[n] = '\0';

            char *line = strtok(buf, "\n");
            while (line) {
                std::string cmd(line);

                if (cmd == "QUIT") {
                    g_running = false;
                } else if (cmd == "WINDOW:visible") {
                    g_windowVisible = true;
                } else if (cmd == "WINDOW:hidden") {
                    g_windowVisible = false;
                } else if (cmd.rfind("MODE:", 0) == 0) {
                    g_effectMode = std::stoi(cmd.substr(5));
                } else if (cmd.rfind("BLUR:", 0) == 0) {
                    g_blurStrength = std::stof(cmd.substr(5));
                } else if (cmd.rfind("BG:", 0) == 0) {
                    std::lock_guard<std::mutex> lock(g_bgMutex);
                    g_bgFile = cmd.substr(3);
                    g_bgChanged = true;
                } else if (cmd.rfind("DEVICE:", 0) == 0) {
                    std::lock_guard<std::mutex> lock(g_deviceMutex);
                    std::string dev = cmd.substr(7);
                    if (dev != g_inputDevice) {
                        g_inputDevice = dev;
                        g_deviceChanged = true;
                    }
                } else if (cmd.rfind("RESOLUTION:", 0) == 0) {
                    std::string res = cmd.substr(11);
                    auto x = res.find('x');
                    if (x != std::string::npos) {
                        int w = std::stoi(res.substr(0, x));
                        int h = std::stoi(res.substr(x + 1));
                        if (w > 0 && h > 0) {
                            g_cameraWidth  = w;
                            g_cameraHeight = h;
                            g_cameraSettingsChanged = true;
                        }
                    }
                } else if (cmd.rfind("FPS:", 0) == 0) {
                    int fps = std::stoi(cmd.substr(4));
                    if (fps > 0 && fps <= 120) {
                        g_cameraFps = fps;
                        g_cameraSettingsChanged = true;
                    }
                }

                line = strtok(nullptr, "\n");
            }
        }
        close(fd);
    }
    unlink(CMD_PIPE_PATH);
}

// ══════════════════════════════════════════════════════════════════════════
// Camera auto-detection
// ══════════════════════════════════════════════════════════════════════════
static std::string autoDetectCamera() {
    for (int i = 0; i <= 9; i++) {
        std::string path = "/dev/video" + std::to_string(i);
        if (path == VCAM_DEVICE) continue;
        struct stat st;
        if (stat(path.c_str(), &st) != 0) continue;
        cv::VideoCapture test;
        test.open(path, cv::CAP_V4L2);
        if (test.isOpened()) {
            test.release();
            return path;
        }
    }
    return "";
}

// ══════════════════════════════════════════════════════════════════════════
// Main loop
// ══════════════════════════════════════════════════════════════════════════
static void signalHandler(int) { g_running = false; }

int main(int argc, char **argv) {
    signal(SIGINT,  signalHandler);
    signal(SIGTERM, signalHandler);

    setenv("OPENCV_VIDEOIO_PRIORITY_V4L2",     "990", 0);
    setenv("OPENCV_VIDEOIO_PRIORITY_GSTREAMER", "0",   0);

    std::string modelDir = "/usr/local/VideoFX/lib/models";
    int aiMode = 0;
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg.rfind("--model_dir=", 0) == 0)  modelDir = arg.substr(12);
        else if (arg.rfind("--mode=", 0) == 0)   aiMode = std::stoi(arg.substr(7));
        else if (arg == "--performance" || arg == "-p") aiMode = 1;
    }

    std::cout << "════════════════════════════════════" << std::endl;
    std::cout << "           BluCast Server" << std::endl;
    std::cout << "════════════════════════════════════" << std::endl;
    std::cout << "Model dir: " << modelDir << std::endl;
    std::cout << "AI mode:   " << (aiMode == 0 ? "Quality" : "Performance") << std::endl;

    writePidFile();

    std::thread cmdThread(commandListener);

    VideoFXProcessor vfx;
    if (!vfx.init(modelDir, aiMode)) {
        std::cerr << "Failed to initialize VideoFX" << std::endl;
        g_running = false;
        cmdThread.join();
        return 1;
    }

    VirtualCamera vcam;
    int vcamW = g_cameraWidth.load();
    int vcamH = g_cameraHeight.load();
    int vcamFps = g_cameraFps.load();
    vcam.open(vcamW, vcamH, vcamFps);
    vcam.writeIdleFrame();

    cv::VideoCapture cap;
    bool cameraActive = false;
    bool buffersReady = false;
    int curWidth = 0, curHeight = 0;
    std::string currentDevice;
    bool lastNeedCamera = false;

    std::cout << "Ready. Listening on " << CMD_PIPE_PATH << std::endl;

    while (g_running) {
        int consumers = readConsumerCount();
        bool windowVis = g_windowVisible.load();
        bool needCamera = windowVis || (consumers > 0);

        if (needCamera != lastNeedCamera) {
            std::cout << (needCamera ? "Camera: activating" : "Camera: going idle") << std::endl;
            lastNeedCamera = needCamera;
        }

        if (!needCamera) {
            if (cameraActive) {
                cap.release();
                cameraActive = false;
                std::cout << "Camera released" << std::endl;
            }
            if (vcam.isOpen()) {
                vcam.writeIdleFrame();
            }
            unlink(PREVIEW_FILE);
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            continue;
        }

        if (!cameraActive) {
            {
                std::lock_guard<std::mutex> lock(g_deviceMutex);
                if (!g_inputDevice.empty()) currentDevice = g_inputDevice;
                g_deviceChanged = false;
            }

            if (currentDevice.empty()) {
                currentDevice = autoDetectCamera();
                if (!currentDevice.empty()) {
                    std::cout << "Auto-detected camera: " << currentDevice << std::endl;
                }
            }

            if (!currentDevice.empty()) {
                cap.open(currentDevice, cv::CAP_V4L2);
            } else {
                cap.open(0, cv::CAP_V4L2);
            }

            if (!cap.isOpened()) {
                std::cerr << "Cannot open camera" << std::endl;
                std::this_thread::sleep_for(std::chrono::seconds(1));
                continue;
            }

            int reqW   = g_cameraWidth.load();
            int reqH   = g_cameraHeight.load();
            int reqFps = g_cameraFps.load();
            cap.set(cv::CAP_PROP_FRAME_WIDTH,  reqW);
            cap.set(cv::CAP_PROP_FRAME_HEIGHT, reqH);
            cap.set(cv::CAP_PROP_FPS,          reqFps);

            curWidth  = (int)cap.get(cv::CAP_PROP_FRAME_WIDTH);
            curHeight = (int)cap.get(cv::CAP_PROP_FRAME_HEIGHT);
            std::cout << "Camera: " << curWidth << "x" << curHeight << std::endl;

            // Reallocate GPU buffers if resolution changed
            if (!buffersReady || curWidth != vcamW || curHeight != vcamH) {
                vfx.allocate(curWidth, curHeight);
                buffersReady = true;
            }

            vcam.open(curWidth, curHeight, reqFps);
            vcamW = curWidth;
            vcamH = curHeight;
            vcamFps = reqFps;

            cameraActive = true;
        }

        {
            std::lock_guard<std::mutex> lock(g_deviceMutex);
            if (g_deviceChanged) {
                g_deviceChanged = false;
                cap.release();
                cameraActive = false;
                buffersReady = false;
                continue;
            }
        }
        if (g_cameraSettingsChanged.exchange(false)) {
            cap.release();
            cameraActive = false;
            buffersReady = false;
            continue;
        }

        {
            std::lock_guard<std::mutex> lock(g_bgMutex);
            if (g_bgChanged && !g_bgFile.empty()) {
                vfx.setBackground(g_bgFile, curWidth, curHeight);
                g_bgChanged = false;
            }
        }

        cv::Mat frame;
        cap >> frame;
        if (frame.empty()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
        }

        int mode = g_effectMode.load();
        cv::Mat result = vfx.process(frame, mode);

        vcam.writeFrame(result);

        if (windowVis) {
            writePreviewJpeg(result);
        }
    }

    if (cameraActive) cap.release();
    unlink(PID_FILE);
    unlink(PREVIEW_FILE);
    unlink(PREVIEW_TMP);

    g_running = false;
    cmdThread.join();
    std::cout << "BluCast closed." << std::endl;
    return 0;
}
