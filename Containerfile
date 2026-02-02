# ClearCastFX - Containerfile
# Self-contained container with NVIDIA VideoFX SDK, TensorRT, and cuDNN

FROM docker.io/nvidia/cuda:11.8.0-cudnn8-devel-ubuntu20.04

LABEL maintainer="ClearCastFX"
LABEL description="AI-powered video effects with virtual camera output"
LABEL org.opencontainers.image.source="https://github.com/Andrei9383/ClearCastFX"
LABEL org.opencontainers.image.description="Real-time AI-powered video effects using NVIDIA Maxine VideoFX SDK"
LABEL org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libopencv-dev \
    python3 \
    python3-pip \
    python3-opencv \
    v4l-utils \
    libv4l-dev \
    ffmpeg \
    x11-apps \
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

# Install PySide6 for modern Qt6 UI
RUN pip3 install --no-cache-dir \
    numpy \
    Pillow \
    PySide6

# Copy SDK files from build context
COPY sdk/TensorRT-8.5.1.7 /usr/local/TensorRT-8.5.1.7
COPY sdk/VideoFX /usr/local/VideoFX
COPY sdk/cudnn /usr/local/cuda/

# Create symlinks for library compatibility
RUN ln -sf /usr/local/VideoFX/lib/libVideoFX.so /usr/local/VideoFX/lib/libNVVideoEffects.so

# Set up library paths
ENV LD_LIBRARY_PATH=/usr/local/TensorRT-8.5.1.7/lib:/usr/local/VideoFX/lib:/usr/local/cuda/lib64:$LD_LIBRARY_PATH
ENV PATH=/usr/local/TensorRT-8.5.1.7/bin:$PATH

WORKDIR /build

# Create FindTensorRT.cmake for the build
RUN echo 'set(TensorRT_ROOT /usr/local/TensorRT-8.5.1.7)\n\
    set(TensorRT_INCLUDE_DIRS ${TensorRT_ROOT}/include)\n\
    set(TensorRT_LIBRARIES ${TensorRT_ROOT}/lib/libnvinfer.so ${TensorRT_ROOT}/lib/libnvinfer_plugin.so)\n\
    set(TensorRT_FOUND TRUE)\n\
    set(TensorRT_VERSION 8.5.1)' > /build/FindTensorRT.cmake

# Create app directory and copy source
WORKDIR /app
COPY app/ /app/
COPY assets/ /app/assets/

# Build the ClearCastFX server
RUN mkdir -p /build/clearcastfx && cd /build/clearcastfx && \
    cmake /app \
    -DCMAKE_MODULE_PATH=/build \
    -DCMAKE_CXX_FLAGS='-I/usr/local/VideoFX/include -I/usr/local/VideoFX/share/samples/utils' \
    -DCMAKE_EXE_LINKER_FLAGS='-L/usr/local/VideoFX/lib -Wl,-rpath,/usr/local/VideoFX/lib:/usr/local/TensorRT-8.5.1.7/lib' && \
    make -j4 && \
    cp clearcastfx_server /app/

# Create output directory
RUN mkdir -p /output /tmp/clearcastfx

# Create startup script
RUN echo '#!/bin/bash\n\
    echo "Starting ClearCastFX..."\n\
    /app/clearcastfx_server --model_dir=/usr/local/VideoFX/lib/models &\n\
    SERVER_PID=$!\n\
    sleep 2\n\
    python3 /app/control_panel.py\n\
    kill $SERVER_PID 2>/dev/null\n\
    ' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
