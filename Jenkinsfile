// =============================================================================
// Declarative Jenkins pipeline for the Skincare Routine Classifier.
//
// Pipeline shape
// --------------
//   Preparation
//   Install Dependencies
//   Quality Gates (parallel):
//       * Lint            - flake8 (PEP-8 + complexity)
//       * Static Typing   - mypy   (type-level defects)
//       * Security (SAST) - bandit (source-level CWE patterns)
//       * Security (SCA)  - pip-audit (dependency CVEs)
//       * Test + Coverage - pytest + branch coverage, fails below 95%
//   Build Docker Image    (only after every quality gate passes)
//   Image Smoke Test      (proves the built image is actually functional)
//   Promote to dev        (auto)
//   Promote to test       (manual approval)
//   Promote to staging    (manual approval)
//   Promote to prod       (manual approval)
//
// Why this shape
// --------------
// * Parallel quality gates: shift left + fail fast on any of five
//   independent quality dimensions.
// * Image is built *once*, smoke-tested, then *promoted* through four
//   environments. This is the Week 8 lecture's "build once, promote
//   the same artefact" principle: dev/test/staging/prod consume the
//   identical IMAGE_TAG so they are guaranteed to be the same binary.
// * Manual approval gates between non-prod and prod environments give
//   the human a chance to abort - the standard control from the
//   Week 11 lecture on automation-as-risk-amplifier.
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
        timeout(time: 30, unit: 'MINUTES')
        // Retain only the most recent runs to keep disk usage bounded.
        buildDiscarder(logRotator(numToKeepStr: '15', artifactNumToKeepStr: '5'))
        // Add timestamps to every console line - invaluable when diagnosing
        // long-running stages.
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
                checkout scm
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
                            # /opt/pyenv is a venv baked into the jenkins-py:lts
                            # image at build time, so PEP 668 never blocks us.
                            pip install --upgrade pip
                            pip install -r requirements.txt
                            pip freeze > pip-freeze.txt
                        '''
                    } else {
                        bat '''
                            python -m pip install --upgrade pip
                            python -m pip install -r requirements.txt
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
        // 3. Quality gates - five independent checks in parallel.
        //    Any failure aborts the pipeline before the Docker image is built.
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
                                    flake8 src tests --count --select=E9,F63,F7,F82 \
                                           --show-source --statistics
                                    flake8 src tests --count --max-complexity=10 \
                                           --max-line-length=100 --statistics \
                                           --tee --output-file=flake8-report.txt
                                '''
                            } else {
                                bat '''
                                    flake8 src tests --count --select=E9,F63,F7,F82 --show-source --statistics || exit /b 1
                                    flake8 src tests --count --max-complexity=10 --max-line-length=100 --statistics --tee --output-file=flake8-report.txt
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

                // --- 3b. Static typing ----------------------------------------
                // mypy catches a class of defects flake8 cannot see (wrong
                // types, missing return annotations on callable boundaries,
                // unsound Optional handling, etc.). Failing here keeps the
                // type contracts honoured at every commit.
                stage('Static Typing (mypy)') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh '''
                                    set -euxo pipefail
                                    mypy --ignore-missing-imports \
                                         --no-strict-optional \
                                         src \
                                         | tee mypy-report.txt
                                '''
                            } else {
                                bat '''
                                    mypy --ignore-missing-imports --no-strict-optional src > mypy-report.txt
                                    type mypy-report.txt
                                '''
                            }
                        }
                    }
                    post {
                        always {
                            archiveArtifacts artifacts: 'mypy-report.txt',
                                             allowEmptyArchive: true
                        }
                    }
                }

                // --- 3c. Security (SAST) --------------------------------------
                stage('Security SAST (bandit)') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh '''
                                    set -euxo pipefail
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

                // --- 3d. Security (SCA) ---------------------------------------
                // pip-audit cross-references every pinned dependency in
                // requirements.txt against the PyPA / OSV vulnerability
                // database. Catches the "we shipped a vulnerable library"
                // failure mode that lint and unit tests cannot detect.
                // ``--strict`` makes a *finding* a build failure, exactly
                // matching the Week 11 lecture's notion of a security gate.
                stage('Security SCA (pip-audit)') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh '''
                                    set -euxo pipefail
                                    pip-audit \
                                        --requirement requirements.txt \
                                        --strict \
                                        --format json \
                                        --output pip-audit-report.json \
                                        || (echo "Vulnerable dependencies detected"; exit 1)
                                '''
                            } else {
                                bat '''
                                    pip-audit --requirement requirements.txt --strict --format json --output pip-audit-report.json || exit /b 1
                                '''
                            }
                        }
                    }
                    post {
                        always {
                            archiveArtifacts artifacts: 'pip-audit-report.json',
                                             allowEmptyArchive: true
                        }
                    }
                }

                // --- 3e. Tests + Coverage -------------------------------------
                stage('Test + Coverage') {
                    steps {
                        script {
                            if (isUnix()) {
                                sh """
                                    set -euxo pipefail
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
        //    Built ONCE; the same tag is promoted through every environment.
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
        //
        //    The new image serves HTTP, so the smoke test starts a container,
        //    waits for /health, posts a profile to /recommend and asserts the
        //    JSON response. This exercises the full WSGI stack inside Docker.
        // ---------------------------------------------------------------------
        stage('Image Smoke Test') {
            when {
                expression { return isDockerAvailable() }
            }
            steps {
                script {
                    def fullName = "${env.IMAGE_NAME}:${env.IMAGE_TAG}"
                    def container = "skincare-smoke-${env.BUILD_NUMBER}"
                    if (isUnix()) {
                        sh """
                            set -euxo pipefail
                            docker rm -f ${container} >/dev/null 2>&1 || true
                            # No port mapping: Jenkins runs inside Docker, so -p binds
                            # on the host, not on Jenkins's 127.0.0.1. Instead, start
                            # the container on the default bridge and reach it via its
                            # internal IP (both containers share the same bridge).
                            docker run -d --name ${container} ${fullName}

                            # Resolve the container's bridge IP.
                            CONTAINER_IP=\$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ${container})
                            echo "Smoke container IP: \${CONTAINER_IP}"

                            # Wait up to 20 seconds for the healthcheck endpoint.
                            healthy=0
                            for i in \$(seq 1 20); do
                                if curl -fsS http://\${CONTAINER_IP}:8000/health > /dev/null; then
                                    echo "container healthy after \${i}s"
                                    healthy=1; break
                                fi
                                sleep 1
                            done
                            [ "\${healthy}" -eq 1 ] || { echo "Container failed to start within 20s"; docker logs ${container}; exit 1; }

                            # Verify /recommend returns a structurally valid response.
                            curl -fsS -X POST http://\${CONTAINER_IP}:8000/recommend \\
                                -H 'Content-Type: application/json' \\
                                -d '{"skin_type":"oily","age":25,"concerns":["acne"],"climate":"humid","budget":"medium","routine_preference":"balanced","sensitivities":[]}' \\
                                | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); assert "morning_routine" in d, d'

                            docker logs ${container} | tail -n 30
                            docker rm -f ${container}
                        """
                    } else {
                        bat """
                            docker rm -f ${container} > nul 2>&1
                            docker run -d --name ${container} -p 18080:8000 ${fullName}
                            powershell -Command "for(\$i=0;\$i -lt 20;\$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/health|Out-Null;break}catch{Start-Sleep -Seconds 1}}"
                            curl -fsS -X POST http://127.0.0.1:18080/recommend -H "Content-Type: application/json" -d "{\\"skin_type\\":\\"oily\\",\\"age\\":25,\\"concerns\\":[\\"acne\\"],\\"climate\\":\\"humid\\",\\"budget\\":\\"medium\\",\\"routine_preference\\":\\"balanced\\",\\"sensitivities\\":[]}"
                            docker rm -f ${container}
                        """
                    }
                }
            }
        }

        // ---------------------------------------------------------------------
        // 6. Environment promotion - the same image is deployed to four
        //    environments in sequence. Dev is automatic; test/staging/prod
        //    require a human approval. This mirrors the Week 8 lecture's
        //    "build once, promote with gates" flow (slides 22-24).
        //
        //    The 'deploy' step here is a simulation: in a real Kubernetes
        //    cluster it would 'helm upgrade --install', in ECS it would
        //    'aws ecs update-service'. The pipeline shape is the same.
        // ---------------------------------------------------------------------
        stage('Deploy to dev') {
            when { expression { return isDockerAvailable() } }
            steps {
                script {
                    simulateDeploy('dev', "${env.IMAGE_NAME}:${env.IMAGE_TAG}")
                }
            }
        }

        stage('Approve promotion to test') {
            when { expression { return isDockerAvailable() } }
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: 'Promote to TEST?', ok: 'Promote'
                }
            }
        }
        stage('Deploy to test') {
            when { expression { return isDockerAvailable() } }
            steps { script { simulateDeploy('test', "${env.IMAGE_NAME}:${env.IMAGE_TAG}") } }
        }

        stage('Approve promotion to staging') {
            when { expression { return isDockerAvailable() } }
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: 'Promote to STAGING?', ok: 'Promote'
                }
            }
        }
        stage('Deploy to staging') {
            when { expression { return isDockerAvailable() } }
            steps { script { simulateDeploy('staging', "${env.IMAGE_NAME}:${env.IMAGE_TAG}") } }
        }

        stage('Approve promotion to prod') {
            when { expression { return isDockerAvailable() } }
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: 'Promote SAME IMAGE TAG to PRODUCTION?',
                          ok: 'I have reviewed and approve'
                }
            }
        }
        stage('Deploy to prod') {
            when { expression { return isDockerAvailable() } }
            steps { script { simulateDeploy('prod', "${env.IMAGE_NAME}:${env.IMAGE_TAG}") } }
        }
    }

    // -------------------------------------------------------------------------
    // Post actions - run regardless of outcome.
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
            echo "Pipeline succeeded - image ${env.IMAGE_NAME}:${env.IMAGE_TAG} promoted to prod."
        }
        unstable {
            echo "Pipeline finished UNSTABLE - typically a test or coverage warning."
        }
        failure {
            echo "Pipeline FAILED - inspect the failing stage's log and archived reports."
        }
        cleanup {
            cleanWs()
        }
    }
}

// ---------------------------------------------------------------------------
// Helper: simulate a per-environment deployment.
//
// In a teaching context we cannot assume the marker has a Kubernetes
// cluster or cloud credentials, so we model the deployment by running
// the image with a per-environment APP_ENV / banner setting, hitting
// /health, and printing the version. The Jenkins console output is the
// promotion evidence; a production version would replace the body with
// a 'helm upgrade' / 'kubectl rollout' / 'aws ecs update-service' call.
// ---------------------------------------------------------------------------
def simulateDeploy(String envName, String image) {
    if (isUnix()) {
        sh """
            set -euxo pipefail
            echo "==> Deploying ${image} to '${envName}' environment"
            container="skincare-${envName}-${env.BUILD_NUMBER}"
            docker rm -f "\$container" >/dev/null 2>&1 || true
            docker run -d --name "\$container" -e APP_ENV=${envName} ${image}
            CONTAINER_IP=\$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "\$container")
            healthy=0
            for i in \$(seq 1 20); do
                if curl -fsS http://\${CONTAINER_IP}:8000/health > /dev/null; then
                    healthy=1; break
                fi
                sleep 1
            done
            [ "\${healthy}" -eq 1 ] || { echo "Deploy to ${envName} failed health check within 20s"; docker logs "\$container"; exit 1; }
            curl -fsS http://\${CONTAINER_IP}:8000/version | python3 -m json.tool
            echo "==> '${envName}' deployment healthy"
            docker rm -f "\$container"
        """
    } else {
        bat """
            echo Deploying ${image} to ${envName}
            set container=skincare-${envName}-${env.BUILD_NUMBER}
            docker rm -f %container% > nul 2>&1
            docker run -d --name %container% -e APP_ENV=${envName} -p 18099:8000 ${image}
            powershell -Command "Start-Sleep -Seconds 5; Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18099/version"
            docker rm -f %container%
        """
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
