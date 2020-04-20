import os
import sys

from setuptools import setup, find_packages

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
    install_requires=['pyusb', 'nmigen', 'pyvcd', 'usb_protocol'],
    setup_requires=['setuptools', 'setuptools_scm'],
    entry_points= {
        'console_scripts': [
            'luna-dev = luna.commands.luna_dev:main',
        ],
    },

    extras_require = {
        'console_tests': ["prompt_toolkit"]
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
