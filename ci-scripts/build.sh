#!/bin/bash
set -e
python3 -m venv testing-venv
source testing-venv/bin/activate
pip install .
pip install "cynthion~=0.1"
deactivate
