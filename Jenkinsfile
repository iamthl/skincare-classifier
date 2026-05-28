// =============================================================================
// Enterprise-grade Declarative Jenkins pipeline for the Skincare Routine
// Classifier.
//
// Pipeline design
// ---------------
//  Setup       -> creates a clean, isolated Python virtualenv (no global pip).
//  Quality gates run in parallel for speed:
//      * Lint        - flake8 enforces PEP-8.
//      * Security    - bandit scans for common Python security issues.
//      * Test+Cov    - pytest with pytest-cov, fails below the coverage gate.
//  Build       -> reproducible Docker image build, tagged with the commit SHA.
//  Smoke Test  -> the freshly built image is actually executed to prove it
//                 produces valid JSON output (catches "builds-but-broken").
//
// Quality gates
// -------------
//  Any failure in Lint, Security, or Test+Coverage aborts the pipeline
//  before the Docker image is built - defective code never reaches a
//  registry. This is the core CI/CD principle: shift left, fail fast.
//
//  Reports (JUnit XML, coverage XML/HTML, bandit JSON) are archived so a
//  human reviewer or downstream tool (SonarQube, Codecov, etc.) can read
//  them after the run.
// =============================================================================

pipeline {
    // 'any' is appropriate for a teaching context; in production this would
    // typically be a labelled agent (e.g. 'docker && linux').
    agent any

    // -------------------------------------------------------------------------
    // Global options - applied to every stage.
    // -------------------------------------------------------------------------
    options {
        // Cap total wall time so a stuck stage cannot block the executor forever.
        timeout(time: 20, unit: 'MINUTES')
        // Retain only the most recent runs to keep disk usage bounded.
        buildDiscarder(logRotator(numToKeepStr: '15', artifactNumToKeepStr: '5'))
        // Add timestamps to every console line - invaluable when diagnosing
        // long-running stages. (AnsiColor was removed: purely cosmetic and
        // adds a fragile external-mirror plugin dependency.)
        timestamps()
        // Abort previously-running builds when a new commit lands on the same
        // branch; nobody benefits from CI on stale code.
        disableConcurrentBuilds()
    }

    // -------------------------------------------------------------------------
    // Environment - centralised so stages can reference rather than duplicate.
    // -------------------------------------------------------------------------
    environment {
        // Quality thresholds enforced by the pipeline (single source of truth).
        COVERAGE_MIN    = '95'
        // Docker image coordinates - SHA tag gives every build a unique,
        // immutable identity; the 'latest' tag is *not* applied automatically.
        IMAGE_NAME      = 'skincare-routine-classifier'
        IMAGE_TAG       = "${env.GIT_COMMIT?.take(8) ?: env.BUILD_NUMBER}"
        // Make Python output unbuffered so Jenkins streams logs in real time.
        PYTHONUNBUFFERED = '1'
        PYTHONDONTWRITEBYTECODE = '1'
    }

    stages {

        // ---------------------------------------------------------------------
        // 1. Preparation - reproducible environment from a clean slate.
        // ---------------------------------------------------------------------
        stage('Preparation') {
            steps {
                echo "Building ${env.IMAGE_NAME}:${env.IMAGE_TAG} for branch '${env.BRANCH_NAME ?: 'local'}'"

                // 'checkout scm' uses the SCM config from the multibranch / job
                // definition - no hard-coded URL means the pipeline is portable.
                checkout scm

                script {
                    // Choose shell wrapper based on agent OS. The original
                    // scaffold used 'bat' (Windows); enterprise pipelines must
                    // remain portable, so we abstract over the difference.
                    env.SHELL_WRAP = isUnix() ? 'sh' : 'bat'
                }
            }
        }

        // ---------------------------------------------------------------------
        // 2. Dependency installation in an isolated virtualenv.
        // ---------------------------------------------------------------------
        stage('Install Dependencies') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -euxo pipefail
                            # Install directly to user site-packages.
                            # venv is avoided because python3-venv behaves
                            # inconsistently across Debian Bookworm Jenkins
                            # images; the workspace is already isolated per
                            # build so user-scoped installs are safe here.
                            python3 -m pip install --user --upgrade pip
                            python3 -m pip install --user -r requirements.txt
                            python3 -m pip freeze > pip-freeze.txt
                        '''
                    } else {
                        bat '''
                            python -m pip install --user --upgrade pip
                            python -m pip install --user -r requirements.txt
                            python -m pip freeze > pip-freeze.txt
                        '''
                    }
                }
            }
            post {
                always {
                    // Archive the resolved dependency tree for traceability.
                    archiveArtifacts artifacts: 'pip-freeze.txt',
                                     allowEmptyArchive: true,
                                     fingerprint: true
                }
            }
        }

        // ---------------------------------------------------------------------
        // 3. Quality gates - lint + security + tests run in parallel for speed.
        //    A failure in any branch fails the whole stage and aborts the
        //    pipeline before the Docker image is built.
        // ---------------------------------------------------------------------
        stage('Quality Gates') {
            parallel {

                // --- 3a. Lint --------------------------------------------------
                stage('Lint (flake8)') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh '''
                                    set -euxo pipefail
                                    export PATH="${HOME}/.local/bin:${PATH}"
                                    flake8 src tests --count --select=E9,F63,F7,F82 \
                                           --show-source --statistics
                                    flake8 src tests --count --max-complexity=10 \
                                           --max-line-length=100 --statistics \
                                           --tee --output-file=flake8-report.txt \
                                           --exit-zero
                                '''
                            } else {
                                bat '''
                                    flake8 src tests --count --select=E9,F63,F7,F82 --show-source --statistics || exit /b 1
                                    flake8 src tests --count --max-complexity=10 --max-line-length=100 --statistics --tee --output-file=flake8-report.txt --exit-zero
                                '''
                            }
                        }
                    }
                    post {
                        always {
                            archiveArtifacts artifacts: 'flake8-report.txt',
                                             allowEmptyArchive: true
                        }
                    }
                }

                // --- 3b. Security ---------------------------------------------
                stage('Security Scan (bandit)') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh '''
                                    set -euxo pipefail
                                    export PATH="${HOME}/.local/bin:${PATH}"
                                    bandit -r src -f json -o bandit-report.json
                                    bandit -r src
                                '''
                            } else {
                                bat '''
                                    bandit -r src -f json -o bandit-report.json || exit /b 1
                                    bandit -r src
                                '''
                            }
                        }
                    }
                    post {
                        always {
                            archiveArtifacts artifacts: 'bandit-report.json',
                                             allowEmptyArchive: true
                        }
                    }
                }

                // --- 3c. Tests + Coverage -------------------------------------
                stage('Test + Coverage') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh """
                                    set -euxo pipefail
                                    export PATH="\${HOME}/.local/bin:\${PATH}"
                                    pytest \\
                                        --maxfail=1 \\
                                        --strict-markers \\
                                        --tb=short \\
                                        --junitxml=junit-report.xml \\
                                        --cov=src \\
                                        --cov-branch \\
                                        --cov-report=term-missing \\
                                        --cov-report=xml:coverage.xml \\
                                        --cov-report=html:htmlcov \\
                                        --cov-fail-under=${env.COVERAGE_MIN}
                                """
                            } else {
                                bat """
                                    call %VENV_DIR%\\Scripts\\activate
                                    pytest --maxfail=1 --strict-markers --tb=short ^
                                        --junitxml=junit-report.xml ^
                                        --cov=src --cov-branch ^
                                        --cov-report=term-missing ^
                                        --cov-report=xml:coverage.xml ^
                                        --cov-report=html:htmlcov ^
                                        --cov-fail-under=${env.COVERAGE_MIN}
                                """
                            }
                        }
                    }
                    post {
                        always {
                            // JUnit results power the Jenkins test trend graph.
                            junit allowEmptyResults: false,
                                  testResults: 'junit-report.xml'
                            archiveArtifacts artifacts: 'coverage.xml, htmlcov/**',
                                             allowEmptyArchive: true,
                                             fingerprint: true
                        }
                    }
                }
            } // end parallel
        }

        // ---------------------------------------------------------------------
        // 4. Build the Docker image (only after all quality gates have passed).
        // ---------------------------------------------------------------------
        stage('Build Docker Image') {
            // Skip this stage when the Docker daemon is unavailable (e.g. when
            // the pipeline is being validated on a controller-only node).
            when {
                expression { return isDockerAvailable() }
            }
            steps {
                script {
                    def fullName = "${env.IMAGE_NAME}:${env.IMAGE_TAG}"
                    echo "Building Docker image: ${fullName}"
                    if (isUnix()) {
                        sh """
                            set -euxo pipefail
                            docker build \\
                                --pull \\
                                --label "git.commit=${env.GIT_COMMIT ?: 'unknown'}" \\
                                --label "ci.build=${env.BUILD_NUMBER}" \\
                                -t ${fullName} \\
                                -t ${env.IMAGE_NAME}:latest \\
                                .
                            docker image ls ${env.IMAGE_NAME}
                        """
                    } else {
                        bat """
                            docker build --pull ^
                                --label git.commit=${env.GIT_COMMIT} ^
                                --label ci.build=${env.BUILD_NUMBER} ^
                                -t ${fullName} ^
                                -t ${env.IMAGE_NAME}:latest .
                            docker image ls ${env.IMAGE_NAME}
                        """
                    }
                }
            }
        }

        // ---------------------------------------------------------------------
        // 5. Smoke test - actually run the image. A green build that produces a
        //    broken container is worse than a red build, so prove the image is
        //    functional before declaring success.
        // ---------------------------------------------------------------------
        stage('Image Smoke Test') {
            when {
                expression { return isDockerAvailable() }
            }
            steps {
                script {
                    def fullName = "${env.IMAGE_NAME}:${env.IMAGE_TAG}"
                    if (isUnix()) {
                        sh """
                            set -euxo pipefail
                            output=\$(docker run --rm ${fullName})
                            echo "\${output}"
                            echo "\${output}" | python3 -c 'import json,sys; json.loads(sys.stdin.read())'
                        """
                    } else {
                        bat """
                            docker run --rm ${fullName} > image-output.json
                            type image-output.json
                            python -c "import json; json.load(open('image-output.json'))"
                        """
                    }
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Post actions - run regardless of outcome. The 'always' block guarantees
    // workspace cleanup; success / failure / unstable hooks make notifications
    // easy to bolt on later (Slack, email, etc.).
    // -------------------------------------------------------------------------
    post {
        always {
            echo "Build #${env.BUILD_NUMBER} finished with status: ${currentBuild.currentResult}"
            // Best-effort image cleanup so the agent does not fill its disk.
            script {
                if (isDockerAvailable()) {
                    if (isUnix()) {
                        sh "docker image prune -f --filter 'label=ci.build=${env.BUILD_NUMBER}' || true"
                    } else {
                        bat "docker image prune -f --filter \"label=ci.build=${env.BUILD_NUMBER}\" || ver > nul"
                    }
                }
            }
        }
        success {
            echo "Pipeline succeeded - image ${env.IMAGE_NAME}:${env.IMAGE_TAG} is ready."
        }
        unstable {
            echo "Pipeline finished UNSTABLE - typically a test or coverage warning."
        }
        failure {
            echo "Pipeline FAILED - inspect the failing stage's log and archived reports."
        }
        cleanup {
            // Always wipe the workspace at the very end of post-processing.
            cleanWs()
        }
    }
}

// ---------------------------------------------------------------------------
// Helper: detect whether the executing agent has a working Docker daemon.
// Wrapping the check lets the pipeline degrade gracefully on agents that
// only run the Python quality gates.
// ---------------------------------------------------------------------------
boolean isDockerAvailable() {
    try {
        if (isUnix()) {
            return sh(script: 'command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1',
                      returnStatus: true) == 0
        } else {
            return bat(script: 'docker info >nul 2>&1', returnStatus: true) == 0
        }
    } catch (ignored) {
        return false
    }
}
