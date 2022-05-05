#!/bin/bash -x
export PIP_CACHE_DIR=${WORKSPACE}/.cache
env
python3 -m venv testing-venv
source testing-venv/bin/activate
env
pip3 install wheel amaranth poetry git+https://github.com/CapableRobot/CapableRobot_USBHub_Driver --upgrade
poetry install
deactivate