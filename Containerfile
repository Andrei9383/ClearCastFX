# ClearCastFX - Containerfile

FROM docker.io/nvidia/cuda:11.8.0-cudnn8-devel-ubuntu20.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libopencv-dev \
    libv4l-dev \
    && rm -rf /var/lib/apt/lists/*

COPY sdk/TensorRT-8.5.1.7 /usr/local/TensorRT-8.5.1.7
COPY sdk/VideoFX /usr/local/VideoFX
COPY sdk/cudnn /usr/local/cuda/

ENV LD_LIBRARY_PATH=/usr/local/TensorRT-8.5.1.7/lib:/usr/local/VideoFX/lib:/usr/local/cuda/lib64:$LD_LIBRARY_PATH

WORKDIR /build

RUN echo 'set(TensorRT_ROOT /usr/local/TensorRT-8.5.1.7)\n\
    set(TensorRT_INCLUDE_DIRS ${TensorRT_ROOT}/include)\n\
    set(TensorRT_LIBRARIES ${TensorRT_ROOT}/lib/libnvinfer.so ${TensorRT_ROOT}/lib/libnvinfer_plugin.so)\n\
    set(TensorRT_FOUND TRUE)\n\
    set(TensorRT_VERSION 8.5.1)' > /build/FindTensorRT.cmake

COPY app/ /app/
RUN mkdir -p /build/clearcastfx && cd /build/clearcastfx && \
    cmake /app \
    -DCMAKE_MODULE_PATH=/build \
    -DCMAKE_CXX_FLAGS='-I/usr/local/VideoFX/include -I/usr/local/VideoFX/share/samples/utils' \
    -DCMAKE_EXE_LINKER_FLAGS='-L/usr/local/VideoFX/lib -Wl,-rpath,/usr/local/VideoFX/lib:/usr/local/TensorRT-8.5.1.7/lib' && \
    make -j$(nproc)

FROM docker.io/nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu20.04

LABEL maintainer="ClearCastFX"
LABEL description="AI-powered video effects with virtual camera output"
LABEL org.opencontainers.image.source="https://github.com/Andrei9383/ClearCastFX"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    libopencv-videoio4.2 \
    libopencv-imgproc4.2 \
    libopencv-highgui4.2 \
    python3 \
    python3-pip \
    v4l-utils \
    ffmpeg \
    libxcb-cursor0 \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-keysyms1 \
    libxcb-shape0 \
    libegl1 \
    libgl1-mesa-glx \
    libxkbcommon0 \
    libxkbcommon-x11-0 \
    libdbus-1-3 \
    fonts-ubuntu \
    fontconfig \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    numpy \
    Pillow \
    PySide6

RUN mkdir -p /usr/local/lib/clearcastfx

COPY --from=builder /build/clearcastfx/clearcastfx_server /app/clearcastfx_server

COPY --from=builder /usr/local/TensorRT-8.5.1.7/lib/libnvinfer.so.8* /usr/local/lib/clearcastfx/
COPY --from=builder /usr/local/TensorRT-8.5.1.7/lib/libnvinfer_plugin.so.8* /usr/local/lib/clearcastfx/
COPY --from=builder /usr/local/VideoFX/lib/libVideoFX.so* /usr/local/lib/clearcastfx/
COPY --from=builder /usr/local/VideoFX/lib/libNVCVImage.so* /usr/local/lib/clearcastfx/
COPY --from=builder /usr/local/VideoFX/lib/libNVTRTLogger.so* /usr/local/lib/clearcastfx/

COPY --from=builder /usr/local/VideoFX/lib/models /usr/local/VideoFX/lib/models

RUN ln -sf /usr/local/lib/clearcastfx/libVideoFX.so /usr/local/lib/clearcastfx/libNVVideoEffects.so

COPY app/control_panel.py /app/
COPY assets/ /app/assets/

ENV LD_LIBRARY_PATH=/usr/local/lib/clearcastfx:$LD_LIBRARY_PATH
WORKDIR /app

RUN mkdir -p /output /tmp/clearcastfx

RUN echo '#!/bin/bash\n\
    echo "Starting ClearCastFX..."\n\
    /app/clearcastfx_server --model_dir=/usr/local/VideoFX/lib/models &\n\
    SERVER_PID=$!\n\
    sleep 2\n\
    python3 /app/control_panel.py\n\
    kill $SERVER_PID 2>/dev/null\n\
    ' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
