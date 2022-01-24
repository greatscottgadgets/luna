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
        stage('Build') {
            steps {
                sh './ci-scripts/build.sh'
            }
        }
        stage('Test') {
            steps {
                retry(3) {
                    sh './ci-scripts/test.sh'
                }
            }
        }
    }
    post {
        always {
            sh 'usbhub --hub D9D1 power state --port 3 --reset'
            sh 'rm -rf testing-venv/'
            cleanWs(cleanWhenNotBuilt: false,
                    deleteDirs: true,
                    disableDeferredWipeout: true,
                    notFailBuild: true)
        }
    }
}