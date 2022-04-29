# Use the official image as a parent image
FROM ubuntu:20.04
CMD ["/bin/bash"]

# add user with uid:gid 1000:1000 to match host system
RUN groupadd -g 1000 jenkins
RUN useradd -r -u 1000 -g 1000 -d /var/jenkins_home jenkins

# Override interactive installations and install dependencies
ENV DEBIAN_FRONTEND=noninteractive 
RUN apt-get update && apt-get install -y \
    bison \
    build-essential \
    clang \
    cmake \
    curl \
    dfu-util \
    flex \
    gawk \
    gcc-arm-none-eabi \
    git \
    jq \
    libboost-all-dev \
    libeigen3-dev \
    libreadline-dev \
    openocd \
    pkg-config \
    python3 \
    python3-pip \
    python3-venv \
    python-is-python3 \
    tcl \
    tcl-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install poetry amaranth git+https://github.com/CapableRobot/CapableRobot_USBHub_Driver --upgrade

ARG CACHEBUST=1
RUN curl -L $(curl -s "https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest" \
    | jq --raw-output '.assets[].browser_download_url' | grep "linux-x64") --output oss-cad-suite-linux-x64.tgz \
    && tar zxvf oss-cad-suite-linux-x64.tgz

# add to PATH for pip/source package installations
ENV PATH="/root/.local/bin:/oss-cad-suite/bin:$PATH"

# Inform Docker that the container is listening on port 8080 at runtime
EXPOSE 8080
