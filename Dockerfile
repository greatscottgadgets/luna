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
    git \
    libboost-all-dev \
    libeigen3-dev \
    openocd \
    pkg-config \
    python3 \
    python3-pip \
    python-is-python3 \
    tcl \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --user --upgrade capablerobot_usbhub poetry amaranth

RUN git clone --recursive https://github.com/YosysHQ/prjtrellis \
    && cd prjtrellis/libtrellis/ \
    && cmake -DCMAKE_INSTALL_PREFIX=/usr/local . \
    && make \
    && make install \
    && cd ../..

RUN git clone --recursive https://github.com/YosysHQ/yosys.git \
    && cd yosys/ \
    && make config-clang \
    && make \
    && make install \
    && cd ..

RUN git clone --recursive https://github.com/YosysHQ/nextpnr.git \
    && cd nextpnr/ \
    && cmake . -DARCH=ecp5 -DTRELLIS_INSTALL_PREFIX=/usr/local \
    && make -j$(nproc) \
    && make install \
    && cd ..

RUN git clone --recursive https://github.com/greatscottgadgets/apollo \
    && cd apollo/firmware/ \
    && make APOLLO_BOARD=luna dfu \
    && cd ../..

RUN export

USER jenkins

# Inform Docker that the container is listening on the specified port at runtime.
EXPOSE 8080

# Copy the rest of your app's source code from your host to your image filesystem.
COPY . .