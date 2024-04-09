#!/bin/bash
set -e
python3 -m venv testing-venv
source testing-venv/bin/activate
pip install .[dev]
pip install "cynthion @ git+https://github.com/greatscottgadgets/cynthion/#subdirectory=cynthion/python/"
pip install "amaranth-stdio @ git+https://github.com/amaranth-lang/amaranth-stdio@4a14bb17"
deactivate
