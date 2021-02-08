import os
import sys

from setuptools import setup, find_packages


# Provide our default install requirements.
install_requirements = [
    'pyusb',
    'apollo @ git+https://github.com/apollo/apollo.git',
    'nmigen @ git+https://github.com/nmigen/nmigen.git',
    'nmigen_boards @ git+https://github.com/nmigen/nmigen-boards.git',
    'pyvcd',
    'usb_protocol @ git+https://github.com/usb-tools/python-usb-protocol.git',
    'libusb1',
]

# On ReadTheDocs don't enforce requirements; we'll use requirements.txt
# to provision the documentation builder.
if os.environ.get('READTHEDOCS') == 'True':
    install_requirements = []


setup(

    # Vitals
    name='luna',
    license='BSD',
    url='https://github.com/greatscottgadgets/luna',
    author='Katherine J. Temkin',
    author_email='ktemkin@greatscottgadgets.com',
    description='framework for FPGA-based USB multitools',
    use_scm_version= {
        "root": '..',
        "relative_to": __file__,
        "version_scheme": "guess-next-dev",
        "local_scheme": lambda version : version.format_choice("+{node}", "+{node}.dirty"),
        "fallback_version": "r0.0"
    },

    # Imports / exports / requirements.
    platforms='any',
    packages=find_packages(),
    include_package_data=True,
    python_requires="~=3.7",
    install_requires=install_requirements,
    setup_requires=['setuptools', 'setuptools_scm'],

    extras_require = {
        'console_tests': ["prompt_toolkit"],
        'serial_examples': ["pyserial~=3.4"]
    },

    # Metadata
    classifiers = [
        'Programming Language :: Python',
        'Development Status :: 1 - Planning',
        'Natural Language :: English',
        'Environment :: Console',
        'Environment :: Plugins',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Topic :: Scientific/Engineering',
        'Topic :: Security',
        ],
)
