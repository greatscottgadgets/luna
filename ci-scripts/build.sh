#!/bin/bash
python3 -m venv testing-venv
source testing-venv/bin/activate
pip3 install capablerobot_usbhub poetry amaranth
poetry install
deactivate