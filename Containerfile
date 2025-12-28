# VideoFX Portable App - Containerfile
# Self-contained container with NVIDIA VideoFX SDK, TensorRT, and cuDNN

FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu20.04

LABEL maintainer="VideoFX Portable App"
LABEL description="NVIDIA VideoFX SDK with webcam UI and virtual camera output"

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    build-essential \
    libopencv-dev \
    python3 \
    python3-pip \
    python3-opencv \
    python3-pyqt5 \
    v4l-utils \
    libv4l-dev \
    ffmpeg \
    x11-apps \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for the UI
RUN pip3 install --no-cache-dir \
    numpy \
    pyfakewebcam \
    Pillow

# Copy SDK files from build context
COPY sdk/TensorRT-8.5.1.7 /usr/local/TensorRT-8.5.1.7
COPY sdk/VideoFX /usr/local/VideoFX
COPY sdk/cudnn /usr/local/cuda/

# Create symlinks for library compatibility
RUN ln -sf /usr/local/VideoFX/lib/libVideoFX.so /usr/local/VideoFX/lib/libNVVideoEffects.so

# Set up library paths
ENV LD_LIBRARY_PATH=/usr/local/TensorRT-8.5.1.7/lib:/usr/local/VideoFX/lib:/usr/local/cuda/lib64:$LD_LIBRARY_PATH
ENV PATH=/usr/local/TensorRT-8.5.1.7/bin:$PATH

# Build VideoFX sample apps
WORKDIR /build

# Create FindTensorRT.cmake for the build
RUN echo 'set(TensorRT_ROOT /usr/local/TensorRT-8.5.1.7)\n\
set(TensorRT_INCLUDE_DIRS ${TensorRT_ROOT}/include)\n\
set(TensorRT_LIBRARIES ${TensorRT_ROOT}/lib/libnvinfer.so ${TensorRT_ROOT}/lib/libnvinfer_plugin.so)\n\
set(TensorRT_FOUND TRUE)\n\
set(TensorRT_VERSION 8.5.1)' > /build/FindTensorRT.cmake

# Build the sample apps
RUN mkdir -p /build/samples && cd /build/samples && \
    cmake /usr/local/VideoFX/share/samples \
        -DCMAKE_MODULE_PATH=/build \
        -DCMAKE_CXX_FLAGS='-I/usr/local/VideoFX/include' \
        -DCMAKE_EXE_LINKER_FLAGS='-L/usr/local/VideoFX/lib -Wl,-rpath,/usr/local/VideoFX/lib:/usr/local/TensorRT-8.5.1.7/lib' \
        -Wno-dev && \
    make -j4

# Create app directory
WORKDIR /app

# Copy the UI application
COPY app/ /app/

# Create output directory for samples
RUN mkdir -p /output /tmp/videofx_frames

# Default command - run the UI
CMD ["python3", "/app/videofx_ui.py"]

