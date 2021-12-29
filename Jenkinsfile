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
        stage('Build (Firmware)') {
            steps {
                sh '''#!/bin/bash
                git clone --recursive https://github.com/greatscottgadgets/apollo
                cd apollo/firmware/
                make APOLLO_BOARD=luna dfu
                cd ../..'''
            }
        }
        stage('Build') {
            steps {
                sh 'poetry install'
            }
        }
        stage('Test') {
            steps {
                sh './ci-scripts/test-hub.sh'
                retry(3) {
                    sh 'poetry run applets/interactive-test.py'
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
