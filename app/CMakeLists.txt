cmake_minimum_required(VERSION 3.10)
project(VideoFXServer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find OpenCV
find_package(OpenCV REQUIRED)

# Find CUDA
find_package(CUDA REQUIRED)

# VideoFX SDK paths
set(VFX_SDK "/usr/local/VideoFX")
set(VFX_INCLUDE "${VFX_SDK}/include")
set(VFX_LIB "${VFX_SDK}/lib")
set(VFX_SAMPLES "${VFX_SDK}/share/samples")

# TensorRT paths  
set(TRT_ROOT "/usr/local/TensorRT-8.5.1.7")

# Include directories
include_directories(
    ${VFX_INCLUDE}
    ${VFX_SAMPLES}/utils
    ${OpenCV_INCLUDE_DIRS}
    ${TRT_ROOT}/include
    ${CUDA_INCLUDE_DIRS}
)

# Link directories
link_directories(
    ${VFX_LIB}
    ${TRT_ROOT}/lib
)

# Source files - just our server code, link directly to SDK libs
set(SOURCE_FILES
    videofx_server.cpp
)

# Build the server
add_executable(videofx_server ${SOURCE_FILES})

# Link directly to the VideoFX shared libraries (Linux)
target_link_libraries(videofx_server
    ${OpenCV_LIBS}
    ${VFX_LIB}/libVideoFX.so
    ${VFX_LIB}/libNVCVImage.so
    ${CUDA_LIBRARIES}
    cuda
    pthread
    dl
)

# Set rpath for runtime library loading
set_target_properties(videofx_server PROPERTIES
    BUILD_RPATH "${VFX_LIB};${TRT_ROOT}/lib"
    INSTALL_RPATH "${VFX_LIB};${TRT_ROOT}/lib"
)
