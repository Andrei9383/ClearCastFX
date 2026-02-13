#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
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

#define BAIL_IF_ERR(err) do { if (0 != (err)) { goto bail; } } while (0)
#define BAIL_IF_NULL(x, err, code) do { if ((void *)(x) == NULL) { err = code; goto bail; } } while (0)

const char *CMD_PIPE = "/tmp/blucast/blucast_cmd";
const char *VCAM_DEVICE = "/dev/video10";
const char *PREVIEW_FRAME = "/tmp/blucast/preview_frame.raw";

std::atomic<bool> g_running(true);
std::atomic<int> g_compMode(5);
std::atomic<float> g_blurStrength(0.5f);
std::atomic<int> g_outputFps(30);
std::atomic<bool> g_vcamEnabled(true);
std::atomic<int> g_vcamConsumers(0);
std::atomic<bool> g_showPreview(false);
std::atomic<bool> g_showOverlay(false);
std::atomic<bool> g_embeddedPreview(true);  // Qt embedded preview
std::mutex g_bgMutex;
std::string g_bgFile;
bool g_bgChanged = false;

std::atomic<int> g_cameraWidth(1280);
std::atomic<int> g_cameraHeight(720);
std::atomic<int> g_cameraFps(30);
std::atomic<bool> g_cameraSettingsChanged(false);

std::mutex g_deviceMutex;
std::string g_inputDevice;
bool g_deviceChanged = false;

enum CompMode {
  compMatte,
  compLight,
  compGreen,
  compWhite,
  compNone,
  compBG,
  compBlur,
  compDenoise
};

class VideoFXServer {
public:
  VideoFXServer()
      : _eff(nullptr), _bgblurEff(nullptr), _artifactEff(nullptr),
        _stream(nullptr), _inited(false), _showFPS(true), _framePeriod(0.f),
        _batchOfStates(nullptr), _vcamFd(-1), _vcamWidth(0), _vcamHeight(0),
        _artifactInited(false) {}

  ~VideoFXServer() {
    destroyEffect();
    if (_vcamFd >= 0)
      close(_vcamFd);
  }

  NvCV_Status init(const std::string &modelDir, int mode) {
    NvCV_Status vfxErr = NVCV_SUCCESS;

    vfxErr = NvVFX_CreateEffect(NVVFX_FX_GREEN_SCREEN, &_eff);
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Error creating Green Screen effect: " << vfxErr << std::endl;
      return vfxErr;
    }

    vfxErr = NvVFX_SetString(_eff, NVVFX_MODEL_DIRECTORY, modelDir.c_str());
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Error setting model directory: " << vfxErr << std::endl;
      return vfxErr;
    }

    vfxErr = NvVFX_SetU32(_eff, NVVFX_MODE, mode);
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Error setting mode: " << vfxErr << std::endl;
      return vfxErr;
    }

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

    vfxErr = NvVFX_SetU32(_eff, NVVFX_MAX_INPUT_WIDTH, 1920);
    BAIL_IF_ERR(vfxErr);
    vfxErr = NvVFX_SetU32(_eff, NVVFX_MAX_INPUT_HEIGHT, 1080);
    BAIL_IF_ERR(vfxErr);
    vfxErr = NvVFX_SetU32(_eff, NVVFX_MAX_NUMBER_STREAMS, 1);
    BAIL_IF_ERR(vfxErr);

    std::cout << "Loading AI model..." << std::endl;
    vfxErr = NvVFX_Load(_eff);
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Error loading model: " << vfxErr << std::endl;
      return vfxErr;
    }
    std::cout << "Model loaded successfully!" << std::endl;

    NvVFX_StateObjectHandle state;
    vfxErr = NvVFX_AllocateState(_eff, &state);
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Error allocating state: " << vfxErr << std::endl;
      return vfxErr;
    }
    _stateArray.push_back(state);

    vfxErr = NvVFX_CreateEffect(NVVFX_FX_BGBLUR, &_bgblurEff);
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Warning: Could not create blur effect" << std::endl;
      _bgblurEff = nullptr;
    } else {
      NvVFX_SetCudaStream(_bgblurEff, NVVFX_CUDA_STREAM, _stream);
    }

    vfxErr = NvVFX_CreateEffect(NVVFX_FX_ARTIFACT_REDUCTION, &_artifactEff);
    if (NVCV_SUCCESS != vfxErr) {
      std::cerr << "Warning: Could not create artifact reduction effect" << std::endl;
      _artifactEff = nullptr;
    } else {
      NvVFX_SetCudaStream(_artifactEff, NVVFX_CUDA_STREAM, _stream);
      NvVFX_SetString(_artifactEff, NVVFX_MODEL_DIRECTORY, modelDir.c_str());
      std::cout << "Denoise effect created" << std::endl;
    }

    _inited = true;
    return NVCV_SUCCESS;

  bail:
    return vfxErr;
  }

  void destroyEffect() {
    for (auto &state : _stateArray) {
      if (_eff && state)
        NvVFX_DeallocateState(_eff, state);
    }
    _stateArray.clear();

    if (_batchOfStates) {
      free(_batchOfStates);
      _batchOfStates = nullptr;
    }

    if (_eff) { NvVFX_DestroyEffect(_eff); _eff = nullptr; }
    if (_bgblurEff) { NvVFX_DestroyEffect(_bgblurEff); _bgblurEff = nullptr; }
    if (_artifactEff) { NvVFX_DestroyEffect(_artifactEff); _artifactEff = nullptr; }
    if (_stream) { NvVFX_CudaStreamDestroy(_stream); _stream = nullptr; }

    NvCVImage_Dealloc(&_srcGPU);
    NvCVImage_Dealloc(&_dstGPU);
    NvCVImage_Dealloc(&_blurGPU);
    NvCVImage_Dealloc(&_artifactInGPU);
    NvCVImage_Dealloc(&_artifactGPU);
  }

  bool initVirtualCamera(int width, int height) {
    if (_vcamFd >= 0 && (_vcamWidth != width || _vcamHeight != height)) {
      close(_vcamFd);
      _vcamFd = -1;
    }

    if (_vcamFd >= 0)
      return true;

    _vcamFd = open(VCAM_DEVICE, O_WRONLY);
    if (_vcamFd < 0) {
      std::cerr << "Warning: Could not open virtual camera " << VCAM_DEVICE << std::endl;
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
      return true;
    }

    // Set frame rate on the virtual camera device
    int fps = g_outputFps.load();
    if (fps <= 0) fps = 30;
    struct v4l2_streamparm parm;
    memset(&parm, 0, sizeof(parm));
    parm.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
    parm.parm.output.timeperframe.numerator = 1;
    parm.parm.output.timeperframe.denominator = fps;
    if (ioctl(_vcamFd, VIDIOC_S_PARM, &parm) < 0) {
      std::cerr << "Warning: Could not set virtual camera frame rate" << std::endl;
    }

    _vcamWidth = width;
    _vcamHeight = height;
    std::cout << "Virtual camera: " << VCAM_DEVICE << " @ " << width << "x" << height << " " << fps << "fps" << std::endl;
    return true;
  }

  void writeToVirtualCamera(const cv::Mat &frame) {
    if (_vcamFd < 0 || !g_vcamEnabled)
      return;

    cv::Mat bgr;
    if (frame.channels() == 3) {
      bgr = frame;
    } else {
      cv::cvtColor(frame, bgr, cv::COLOR_GRAY2BGR);
    }

    if (bgr.cols != _vcamWidth || bgr.rows != _vcamHeight) {
      struct v4l2_format fmt;
      memset(&fmt, 0, sizeof(fmt));
      fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
      fmt.fmt.pix.width = bgr.cols;
      fmt.fmt.pix.height = bgr.rows;
      fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_BGR24;
      fmt.fmt.pix.sizeimage = bgr.cols * bgr.rows * 3;
      fmt.fmt.pix.field = V4L2_FIELD_NONE;

      if (ioctl(_vcamFd, VIDIOC_S_FMT, &fmt) >= 0) {
        _vcamWidth = bgr.cols;
        _vcamHeight = bgr.rows;

        // Also update frame rate
        int fps = g_outputFps.load();
        if (fps <= 0) fps = 30;
        struct v4l2_streamparm parm;
        memset(&parm, 0, sizeof(parm));
        parm.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
        parm.parm.output.timeperframe.numerator = 1;
        parm.parm.output.timeperframe.denominator = fps;
        ioctl(_vcamFd, VIDIOC_S_PARM, &parm);
      }
    }

    write(_vcamFd, bgr.data, bgr.total() * bgr.elemSize());
  }

  void writeIdleFrame() {
    if (_vcamFd < 0)
      return;

    static cv::Mat idleFrame;
    if (idleFrame.empty()) {
      idleFrame = cv::Mat::zeros(720, 1280, CV_8UC3);
      cv::putText(idleFrame, "Camera Off", cv::Point(520, 360),
                  cv::FONT_HERSHEY_SIMPLEX, 1.5, cv::Scalar(100, 100, 100), 2);
    }

    write(_vcamFd, idleFrame.data, idleFrame.total() * idleFrame.elemSize());
  }

  void writePreviewFrame(const cv::Mat &frame) {
    static int previewFd = -1;
    static int lastWidth = 0;
    static int lastHeight = 0;
    
    // Convert BGR to RGB for Qt
    cv::Mat rgb;
    cv::cvtColor(frame, rgb, cv::COLOR_BGR2RGB);
    
    // Reopen file if dimensions changed or first time
    if (previewFd < 0 || rgb.cols != lastWidth || rgb.rows != lastHeight) {
      if (previewFd >= 0) close(previewFd);
      previewFd = open(PREVIEW_FRAME, O_WRONLY | O_CREAT | O_TRUNC, 0666);
      lastWidth = rgb.cols;
      lastHeight = rgb.rows;
    }
    
    if (previewFd >= 0) {
      lseek(previewFd, 0, SEEK_SET);
      write(previewFd, rgb.data, rgb.total() * rgb.elemSize());
    }
  }

  int run(int cameraId) {
    cv::VideoCapture cap;
    bool cameraActive = false;
    bool buffersAllocated = false;
    bool previewCreated = false;
    int width = 0;
    int height = 0;
    std::string currentDevice;

    cv::Mat frame, result, matte;

    std::cout << "\n=== BluCast Ready ===" << std::endl;
    std::cout << "Press 'Q' or ESC to quit" << std::endl;
    std::cout << "Listening for commands on " << CMD_PIPE << std::endl;

    bool lastNeedCamera = false;

    while (g_running) {
      bool vcamEnabled = g_vcamEnabled.load();
      bool previewWanted = g_showPreview.load();
      bool embeddedPreview = g_embeddedPreview.load();
      int consumers = g_vcamConsumers.load();

      if (vcamEnabled && _vcamFd < 0)
        initVirtualCamera(1280, 720);

      bool needCamera = previewWanted || embeddedPreview || (vcamEnabled && consumers > 0);

      if (needCamera != lastNeedCamera) {
        std::cout << (needCamera ? "Capture active" : "Idle") << std::endl;
        lastNeedCamera = needCamera;
      }

      if (!needCamera) {
        if (cameraActive) {
          cap.release();
          cameraActive = false;
          std::cout << "Camera released" << std::endl;
        }
        if (previewCreated) {
          cv::destroyWindow("VideoFX Studio");
          previewCreated = false;
        }
        static bool wroteIdleFrame = false;
        if (vcamEnabled && _vcamFd >= 0 && !wroteIdleFrame) {
          writeIdleFrame();
          wroteIdleFrame = true;
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
        wroteIdleFrame = false;
        continue;
      }

      if (!cameraActive) {
        // Check if a device path was set via command
        {
          std::lock_guard<std::mutex> lock(g_deviceMutex);
          if (!g_inputDevice.empty()) {
            currentDevice = g_inputDevice;
          }
          g_deviceChanged = false;
        }

        if (!currentDevice.empty()) {
          cap.open(currentDevice, cv::CAP_V4L2);
        } else {
          cap.open(cameraId, cv::CAP_V4L2);
        }
        if (!cap.isOpened()) {
          std::cerr << "Error: Cannot open camera " << (currentDevice.empty() ? std::to_string(cameraId) : currentDevice) << std::endl;
          std::this_thread::sleep_for(std::chrono::milliseconds(500));
          continue;
        }

        int reqWidth = g_cameraWidth.load();
        int reqHeight = g_cameraHeight.load();
        int reqFps = g_cameraFps.load();
        cap.set(cv::CAP_PROP_FRAME_WIDTH, reqWidth);
        cap.set(cv::CAP_PROP_FRAME_HEIGHT, reqHeight);
        cap.set(cv::CAP_PROP_FPS, reqFps);

        width = (int)cap.get(cv::CAP_PROP_FRAME_WIDTH);
        height = (int)cap.get(cv::CAP_PROP_FRAME_HEIGHT);
        std::cout << "Camera: " << width << "x" << height << std::endl;

        if (vcamEnabled)
          initVirtualCamera(width, height);

        if (!buffersAllocated) {
          NvCV_Status vfxErr;
          vfxErr = NvCVImage_Alloc(&_srcGPU, width, height, NVCV_BGR, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
          if (vfxErr != NVCV_SUCCESS) return 1;
          vfxErr = NvCVImage_Alloc(&_dstGPU, width, height, NVCV_A, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
          if (vfxErr != NVCV_SUCCESS) return 1;
          vfxErr = NvCVImage_Alloc(&_blurGPU, width, height, NVCV_BGR, NVCV_U8, NVCV_CHUNKY, NVCV_GPU, 1);
          if (vfxErr != NVCV_SUCCESS) return 1;

          vfxErr = NvCVImage_Alloc(&_artifactInGPU, width, height, NVCV_BGR, NVCV_F32, NVCV_PLANAR, NVCV_GPU, 1);
          if (vfxErr == NVCV_SUCCESS) {
            vfxErr = NvCVImage_Alloc(&_artifactGPU, width, height, NVCV_BGR, NVCV_F32, NVCV_PLANAR, NVCV_GPU, 1);
          }

          unsigned modelBatch;
          NvVFX_GetU32(_eff, NVVFX_MODEL_BATCH, &modelBatch);
          _batchOfStates = (NvVFX_StateObjectHandle *)malloc(sizeof(NvVFX_StateObjectHandle) * modelBatch);
          _batchOfStates[0] = _stateArray[0];

          if (_artifactEff && !_artifactInited && _artifactInGPU.pixels && _artifactGPU.pixels) {
            NvVFX_SetImage(_artifactEff, NVVFX_INPUT_IMAGE, &_artifactInGPU);
            NvVFX_SetImage(_artifactEff, NVVFX_OUTPUT_IMAGE, &_artifactGPU);
            vfxErr = NvVFX_Load(_artifactEff);
            if (vfxErr == NVCV_SUCCESS) {
              _artifactInited = true;
              std::cout << "Denoise model loaded" << std::endl;
            }
          }

          buffersAllocated = true;
        }

        if (g_showPreview && !previewCreated) {
          cv::namedWindow("BluCast", cv::WINDOW_AUTOSIZE);
          previewCreated = true;
        }

        cameraActive = true;
      }

      // Check for device change or camera settings change
      {
        std::lock_guard<std::mutex> lock(g_deviceMutex);
        if (g_deviceChanged) {
          g_deviceChanged = false;
          if (cameraActive) {
            cap.release();
            cameraActive = false;
            // Deallocate GPU buffers so they are reallocated for new resolution
            NvCVImage_Dealloc(&_srcGPU);
            NvCVImage_Dealloc(&_dstGPU);
            NvCVImage_Dealloc(&_blurGPU);
            NvCVImage_Dealloc(&_artifactInGPU);
            NvCVImage_Dealloc(&_artifactGPU);
            buffersAllocated = false;
          }
          continue;
        }
      }
      if (g_cameraSettingsChanged.exchange(false)) {
        if (cameraActive) {
          cap.release();
          cameraActive = false;
        }
        continue;
      }

      cap >> frame;
      if (frame.empty())
        continue;

      {
        std::lock_guard<std::mutex> lock(g_bgMutex);
        if (g_bgChanged && !g_bgFile.empty()) {
          _bgImg = cv::imread(g_bgFile);
          if (!_bgImg.empty()) {
            cv::resize(_bgImg, _bgImg, cv::Size(width, height));
            std::cout << "Background: " << g_bgFile << std::endl;
          }
          g_bgChanged = false;
        }
      }

      int mode = g_compMode.load();

      if (mode != compNone && _inited) {
        processFrame(frame, result, matte, mode);
      } else {
        result = frame.clone();
      }

      cv::Mat display = result.clone();

      if (g_showOverlay) {
        if (_showFPS)
          drawFPS(display);

        const char *modeNames[] = {"Matte", "Light", "Green", "White", "Original", "Background", "Blur", "Denoise"};
        if (mode >= 0 && mode < 8) {
          cv::putText(display, modeNames[mode], cv::Point(10, 60),
                      cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(255, 255, 0), 2);
        }

        if (g_vcamEnabled && _vcamFd >= 0) {
          cv::putText(display, "VCAM", cv::Point(width - 80, 30),
                      cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(0, 255, 0), 2);
        }
      }

      if (g_showPreview) {
        if (!previewCreated) {
          cv::namedWindow("BluCast", cv::WINDOW_AUTOSIZE);
          previewCreated = true;
        }
        cv::imshow("BluCast", display);
      } else if (previewCreated) {
        cv::destroyWindow("BluCast");
        previewCreated = false;
      }

      writeToVirtualCamera(result);
      
      // Write frame for Qt preview
      writePreviewFrame(result);

      if (previewCreated) {
        int key = cv::waitKey(1);
        if (key == 'q' || key == 'Q' || key == 27) {
          g_running = false;
          break;
        } else if (key == 'f' || key == 'F') {
          _showFPS = !_showFPS;
        }
      }
    }

    cv::destroyAllWindows();
    cap.release();
    return 0;
  }

private:
  void processFrame(const cv::Mat &src, cv::Mat &result, cv::Mat &matte, int mode) {
    NvCV_Status vfxErr;

    matte = cv::Mat::zeros(src.size(), CV_8UC1);
    result.create(src.rows, src.cols, CV_8UC3);

    NvCVImage srcWrapper, dstWrapper;
    NVWrapperForCVMat(&src, &srcWrapper);
    NVWrapperForCVMat(&matte, &dstWrapper);

    vfxErr = NvVFX_SetImage(_eff, NVVFX_INPUT_IMAGE, &_srcGPU);
    vfxErr = NvVFX_SetImage(_eff, NVVFX_OUTPUT_IMAGE, &_dstGPU);
    vfxErr = NvCVImage_Transfer(&srcWrapper, &_srcGPU, 1.0f, _stream, NULL);
    vfxErr = NvVFX_SetStateObjectHandleArray(_eff, NVVFX_STATE, _batchOfStates);

    vfxErr = NvVFX_Run(_eff, 0);
    if (vfxErr != NVCV_SUCCESS) {
      src.copyTo(result);
      return;
    }

    vfxErr = NvCVImage_Transfer(&_dstGPU, &dstWrapper, 1.0f, _stream, NULL);

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
      for (int y = 0; y < src.rows; y++) {
        for (int x = 0; x < src.cols; x++) {
          float alpha = matte.at<uchar>(y, x) / 255.0f;
          cv::Vec3b srcPix = src.at<cv::Vec3b>(y, x);
          result.at<cv::Vec3b>(y, x) = cv::Vec3b(
              srcPix[0] * (0.5f + 0.5f * alpha),
              srcPix[1] * (0.5f + 0.5f * alpha),
              srcPix[2] * (0.5f + 0.5f * alpha));
        }
      }
      break;

    case compBG:
      if (!_bgImg.empty()) {
        NvCVImage bgWrapper;
        NVWrapperForCVMat(&_bgImg, &bgWrapper);
        NvCVImage_Composite(&srcWrapper, &bgWrapper, &dstWrapper, &resultWrapper, _stream);
      } else {
        const unsigned char bgColor[3] = {0, 200, 0};
        NvCVImage_CompositeOverConstant(&srcWrapper, &dstWrapper, bgColor, &resultWrapper, _stream);
        cv::putText(result, "Select background in control panel",
                    cv::Point(20, result.rows / 2), cv::FONT_HERSHEY_SIMPLEX, 0.8, cv::Scalar(255, 255, 255), 2);
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
        cv::Mat blurred;
        cv::GaussianBlur(src, blurred, cv::Size(51, 51), 0);
        for (int y = 0; y < src.rows; y++) {
          for (int x = 0; x < src.cols; x++) {
            float alpha = matte.at<uchar>(y, x) / 255.0f;
            result.at<cv::Vec3b>(y, x) = src.at<cv::Vec3b>(y, x) * alpha + blurred.at<cv::Vec3b>(y, x) * (1.0f - alpha);
          }
        }
      }
      break;

    case compDenoise:
      if (_artifactEff && _artifactInited) {
        vfxErr = NvCVImage_Transfer(&srcWrapper, &_artifactInGPU, 1.0f / 255.0f, _stream, NULL);
        if (vfxErr != NVCV_SUCCESS) {
          src.copyTo(result);
          break;
        }
        vfxErr = NvVFX_Run(_artifactEff, 0);
        if (vfxErr == NVCV_SUCCESS) {
          vfxErr = NvCVImage_Transfer(&_artifactGPU, &resultWrapper, 255.0f, _stream, NULL);
          if (vfxErr != NVCV_SUCCESS)
            src.copyTo(result);
        } else {
          src.copyTo(result);
        }
      } else {
        src.copyTo(result);
        cv::putText(result, "Denoise not available",
                    cv::Point(20, result.rows / 2), cv::FONT_HERSHEY_SIMPLEX, 0.8, cv::Scalar(0, 0, 255), 2);
      }
      break;
    }
  }

  void drawFPS(cv::Mat &img) {
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
      cv::putText(img, buf, cv::Point(10, 30), cv::FONT_HERSHEY_SIMPLEX, 1, cv::Scalar(0, 255, 0), 2);
    }
    _lastTime = now;
  }

  NvVFX_Handle _eff;
  NvVFX_Handle _bgblurEff;
  NvVFX_Handle _artifactEff;
  CUstream _stream;
  bool _inited;
  bool _artifactInited;
  bool _showFPS;
  float _framePeriod;
  std::chrono::high_resolution_clock::time_point _lastTime;

  NvCVImage _srcGPU;
  NvCVImage _dstGPU;
  NvCVImage _blurGPU;
  NvCVImage _artifactInGPU;
  NvCVImage _artifactGPU;

  cv::Mat _bgImg;

  std::vector<NvVFX_StateObjectHandle> _stateArray;
  NvVFX_StateObjectHandle *_batchOfStates;

  int _vcamFd;
  int _vcamWidth;
  int _vcamHeight;
};

void commandListener() {
  mkdir("/tmp/blucast", 0777);
  unlink(CMD_PIPE);
  mkfifo(CMD_PIPE, 0666);

  while (g_running) {
    int fd = open(CMD_PIPE, O_RDWR | O_NONBLOCK);
    if (fd < 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
      continue;
    }

    struct pollfd pfd = {fd, POLLIN, 0};
    while (g_running) {
      int ret = poll(&pfd, 1, 500);
      if (ret < 0) break;
      if (ret == 0) continue;
      if (pfd.revents & (POLLHUP | POLLERR)) break;
      if (pfd.revents & POLLIN) {
        char buf[512];
        ssize_t n = read(fd, buf, sizeof(buf) - 1);
        if (n <= 0) break;
        buf[n] = '\0';
        if (buf[n - 1] == '\n') buf[n - 1] = '\0';

        std::string cmd(buf);

        if (cmd == "QUIT") {
          g_running = false;
        } else if (cmd.rfind("VCAM_CONSUMERS:", 0) == 0) {
          int consumers = 0;
          try { consumers = std::stoi(cmd.substr(15)); } catch (...) {}
          if (consumers < 0) consumers = 0;
          int prev = g_vcamConsumers.exchange(consumers);
          if (prev != consumers) std::cout << "Vcam consumers: " << consumers << std::endl;
        } else if (cmd.rfind("VCAM_OPENERS:", 0) == 0) {
          int openers = 0;
          try { openers = std::stoi(cmd.substr(13)); } catch (...) {}
          int consumers = openers - 1;
          if (consumers < 0) consumers = 0;
          int prev = g_vcamConsumers.exchange(consumers);
          if (prev != consumers) std::cout << "Vcam consumers: " << consumers << std::endl;
        } else if (cmd.substr(0, 5) == "MODE:") {
          int newMode = std::stoi(cmd.substr(5));
          g_compMode.store(newMode);
          std::cout << "Mode: " << newMode << std::endl;
        } else if (cmd.substr(0, 3) == "BG:") {
          std::lock_guard<std::mutex> lock(g_bgMutex);
          g_bgFile = cmd.substr(3);
          g_bgChanged = true;
        } else if (cmd.substr(0, 5) == "BLUR:") {
          float val = std::stof(cmd.substr(5));
          g_blurStrength.store(val);
        } else if (cmd == "VCAM:on") {
          g_vcamEnabled.store(true);
        } else if (cmd == "VCAM:off") {
          g_vcamEnabled.store(false);
        } else if (cmd == "PREVIEW:on") {
          g_showPreview.store(true);
        } else if (cmd == "PREVIEW:off") {
          g_showPreview.store(false);
        } else if (cmd == "OVERLAY:on") {
          g_showOverlay.store(true);
        } else if (cmd == "OVERLAY:off") {
          g_showOverlay.store(false);
        } else if (cmd == "EMBEDDED:on") {
          g_embeddedPreview.store(true);
        } else if (cmd == "EMBEDDED:off") {
          g_embeddedPreview.store(false);
        } else if (cmd.rfind("DEVICE:", 0) == 0) {
          std::string devPath = cmd.substr(7);
          if (!devPath.empty()) {
            std::lock_guard<std::mutex> lock(g_deviceMutex);
            if (devPath != g_inputDevice) {
              g_inputDevice = devPath;
              g_deviceChanged = true;
              std::cout << "Input device: " << devPath << std::endl;
            }
          }
        } else if (cmd.rfind("RESOLUTION:", 0) == 0) {
          std::string res = cmd.substr(11);
          size_t xpos = res.find('x');
          if (xpos != std::string::npos) {
            try {
              int w = std::stoi(res.substr(0, xpos));
              int h = std::stoi(res.substr(xpos + 1));
              if (w > 0 && h > 0 && w <= 4096 && h <= 2160) {
                g_cameraWidth.store(w);
                g_cameraHeight.store(h);
                g_cameraSettingsChanged.store(true);
              }
            } catch (...) {}
          }
        } else if (cmd.rfind("FPS:", 0) == 0) {
          try {
            int fps = std::stoi(cmd.substr(4));
            if (fps > 0 && fps <= 120) {
              g_cameraFps.store(fps);
              g_outputFps.store(fps);
              g_cameraSettingsChanged.store(true);
            }
          } catch (...) {}
        } else if (cmd.rfind("OUTPUT_FPS:", 0) == 0) {
          try {
            int fps = std::stoi(cmd.substr(11));
            if (fps > 0 && fps <= 120)
              g_outputFps.store(fps);
          } catch (...) {}
        }
      }
    }
    close(fd);
  }

  unlink(CMD_PIPE);
}

int main(int argc, char **argv) {
  setenv("LIBGL_ALWAYS_SOFTWARE", "0", 0);
  setenv("MESA_GL_VERSION_OVERRIDE", "3.3", 0);

  setenv("OPENCV_VIDEOIO_PRIORITY_V4L2", "990", 0);
  setenv("OPENCV_VIDEOIO_PRIORITY_GSTREAMER", "0", 0);

  std::string modelDir = "/usr/local/VideoFX/lib/models";
  int cameraId = 0;
  int mode = 0;

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
  std::cout << "           BluCast" << std::endl;
  std::cout << "========================================" << std::endl;
  std::cout << "Model directory: " << modelDir << std::endl;
  std::cout << "Camera ID: " << cameraId << std::endl;
  std::cout << "Mode: " << (mode == 0 ? "Quality" : "Performance") << std::endl;

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

  std::cout << "BluCast closed." << std::endl;
  return result;
}
