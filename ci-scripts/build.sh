#!/bin/bash -x
python3 -m venv testing-venv
source testing-venv/bin/activate
pip3 install poetry amaranth git+https://github.com/CapableRobot/CapableRobot_USBHub_Driver --upgrade
poetry install
deactivate