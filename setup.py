import os
import sys

from setuptools import setup, find_packages

# Provide our default install requirements.
install_requirements = [
    'pyusb',
    'apollo-fpga==0.*,>=0.0.1',
    'nmigen @ git+https://github.com/nmigen/nmigen.git#egg=nmigen',
    'nmigen-boards @ git+https://github.com/nmigen/nmigen-boards.git#egg=nmigen-boards',
    'nmigen-stdio @ git+https://github.com/nmigen/nmigen-stdio.git#egg=nmigen-stdio',
    'nmigen-soc @ git+https://github.com/nmigen/nmigen-soc.git#egg=nmigen-soc',
    'pyvcd~=0.1.4',
    'usb-protocol @git+https://github.com/usb-tools/python-usb-protocol#egg=usb-protocol',
    'libusb1',
    'pyserial',

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
    dependency_links=[
    ],

    extras_require = {
        'console_tests': [
            "prompt_toolkit",
        ],
        'soc': [
            'lambdasoc @ git+https://github.com/ktemkin/lambdasoc.git#egg=lambdasoc',
            'minerva @ git+https://github.com/lambdaconcept/minerva.git#egg=minerva',
        ]
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
