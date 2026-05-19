import org.jenkinsci.plugins.workflow.steps.FlowInterruptedException

pipeline {
    options {
        skipDefaultCheckout true
        throttleJobProperty(
            categories: ['cynthion-named-container'],
            throttleEnabled: true,
            throttleOption: 'category',
        )
    }
    agent any
    stages {
        stage('Build Docker Image') {
            options {
                timeout(time: 20, unit: 'MINUTES')
            }
            steps {
                sh 'docker build -t cynthion-test https://github.com/greatscottgadgets/cynthion-test.git'
            }
        }
        stage('Checkout as submodule') {
            options {
                timeout(time: 2, unit: 'MINUTES')
            }
            steps {
                dir('cynthion-test') {
                    git url: 'https://github.com/greatscottgadgets/cynthion-test.git', branch: 'main'
                    sh 'make submodule-checkout'
                    sh 'rm -rf dependencies/luna'
                    dir('dependencies/luna') {
                        checkout scm // override pinned submodule version with current version
                    }
                }
            }
        }
        stage('Build') {
            agent{
                docker {
                    image 'cynthion-test'
                    reuseNode true
                    args '--name cynthion-test_container'
                }
            }
            options {
                timeout(time: 6, unit: 'MINUTES')
            }
            steps {
                dir('cynthion-test') {
                    sh 'cp /tmp/calibration.dat calibration.dat'
                    sh 'make analyzer.bit'
                }
            }
        }
        stage('HIL Test') {
            agent {
                docker {
                    image 'cynthion-test'
                    reuseNode true
                    // Named pipes /tmp/req_pipe and /tmp/res_pipe for use with Jenkins HIL CI USB port power server
                    args '''
                            --name cynthion-test_container
                            --group-add=20
                            --group-add=46
                            --device-cgroup-rule="c 166:* rmw"
                            --device-cgroup-rule="c 189:* rmw"
                            --device /dev/bus/usb
                            --volume /run/udev/control:/run/udev/control
                            --net=host
                            -v /tmp/req_pipe:/tmp/req_pipe
                            -v /tmp/res_pipe:/tmp/res_pipe
                        '''
                }
            }
            steps {
                dir('cynthion-test') {
                    lock('HIL_hubs') {
                        script {
                            allOff()
                            retry(3) {
                                // reset() retains it's own internal retries
                                reset('cyntest_tycho cyntest_greatfet cyntest_bmp')
                                // run the test with 0 internal retries and 3 external retries to ensure resets between test runs
                                runCommand("HIL Test", 'make unattended', 0, 5, 'MINUTES')
                            }
                        }
                    }
                }
            }
        }
    }
    post {
        always {
            cleanWs(cleanWhenNotBuilt: false,
                    deleteDirs: true,
                    disableDeferredWipeout: true,
                    notFailBuild: true)
        }
    }
}

def allOff() {
    // Allow 20 seconds for the USB hub port power server to respond
    runCommand('USB hub port power server command', "hubs all off", 3, 20, 'SECONDS', )
}

def reset(devices) {
    // Allow 20 seconds for the USB hub port power server to respond
    runCommand('USB hub port power server command', "hubs ${devices} reset", 3, 20, 'SECONDS')
}

def runCommand(title, cmd, retries, time, unit) {
    retry(retries) {
        try {
            timeout(time: time, unit: unit) {
                sh "${cmd}"
            }
        } catch (FlowInterruptedException err) {
            // Check if the cause was specifically an exceeded timeout
            def cause = err.getCauses().get(0)
            if (cause instanceof org.jenkinsci.plugins.workflow.steps.TimeoutStepExecution.ExceededTimeout) {
                echo "${title} timeout reached."
                throw err // Re-throw the exception to fail the build
            } else {
                echo "Build interrupted for another reason."
                throw err // Re-throw the exception to fail the build
            }
        } catch (Exception err) {
            echo "An unrelated error occurred: ${err.getMessage()}"
            throw err
        }
    }
}
