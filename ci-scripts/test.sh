#!/bin/bash -x
usbhub --disable-i2c --hub D9D1 power state --port 3 --reset
source testing-venv/bin/activate
poetry run applets/interactive-test.py
deactivate