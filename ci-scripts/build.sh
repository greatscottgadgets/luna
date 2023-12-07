#!/bin/bash
set -e
python3 -m venv testing-venv
source testing-venv/bin/activate
pip install .[dev]
deactivate
