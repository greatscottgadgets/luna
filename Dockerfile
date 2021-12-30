# Use the official image as a parent image
FROM ubuntu:20.04

# Add Jenkins as a user with sufficient permissions
RUN mkdir /home/jenkins
RUN groupadd -g 136 jenkins
RUN useradd -r -u 126 -g jenkins -G plugdev -d /home/jenkins jenkins
RUN chown jenkins:jenkins /home/jenkins

WORKDIR /home/jenkins

CMD ["/bin/bash"]

# override interactive installations
ENV DEBIAN_FRONTEND=noninteractive 

# Install prerequisites
RUN apt-get update && apt-get install -y \
    bison \
    build-essential \
    clang \
    cmake \
    dfu-util \
    flex \
    gawk \
    gcc-arm-none-eabi \
    git \
    libboost-all-dev \
    libeigen3-dev \
    libreadline-dev \
    openocd \
    pkg-config \
    python3 \
    python3-pip \
    python-is-python3 \
    tcl \
    tcl-dev \
    wget \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --user --upgrade capablerobot_usbhub poetry amaranth

RUN wget https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2021-12-29/oss-cad-suite-linux-x64-20211229.tgz

RUN tar zxvf oss-cad-suite-linux-x64-20211229.tgz

RUN export PATH="/root/.local/bin:$PATH"

RUN poetry --help

RUN export PATH="$HOME/jenkins/oss-cad-suite/bin:$PATH"

RUN export

RUN poetry --help

USER jenkins

# Inform Docker that the container is listening on the specified port at runtime.
EXPOSE 8080

# Copy the rest of your app's source code from your host to your image filesystem.
COPY . .