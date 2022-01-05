pipeline {
    agent { 
        dockerfile {
            args '--group-add=46 --privileged -v /dev/bus/usb:/dev/bus/usb'
        }
    }
    options {
        throttleJobProperty(
            categories: ['single-build-throttle'],
            throttleEnabled: true,
            throttleOption: 'category'
        )
    }
    environment {
        GIT_COMMITER_NAME = 'CI Person'
        GIT_COMMITER_EMAIL = 'ci@greatscottgadgets.com'
    }
    stages {
        // stage('Build (Firmware)') {
        //     steps {
        //         sh '''#!/bin/bash
        //             git clone --recursive https://github.com/greatscottgadgets/apollo
        //             cd apollo/firmware/
        //             make APOLLO_BOARD=luna dfu
        //             cd ../..'''
        //     }
        // }
        stage('Build') {
            steps {
                sh '''#!/bin/bash
                    python3 -m venv testing-venv
                    source testing-venv/bin/activate
                    pip3 install capablerobot_usbhub poetry amaranth
                    poetry install
                    deactivate'''
            }
        }
        stage('Test') {
            steps {
                retry(3) {
                    sh '''#!/bin/bash
                        source testing-venv/bin/activate
                        poetry run applets/interactive-test.py
                        deactivate'''
                }
            }
        }
    }
    post {
        always {
            echo 'One way or another, I have finished'
            sh 'rm -rf testing-venv/'
            // Clean after build
            cleanWs(cleanWhenNotBuilt: false,
                    deleteDirs: true,
                    disableDeferredWipeout: true,
                    notFailBuild: true)
        }
    }
}
