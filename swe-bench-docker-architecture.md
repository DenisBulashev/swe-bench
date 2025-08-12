# SWE-bench Docker Architecture

This document provides a comprehensive overview of the Docker-based evaluation harness used in SWE-bench. The harness is designed to ensure consistent, reproducible, and isolated environments for evaluating software engineering tasks.

## 1. Core Philosophy: Reproducibility and Isolation

The primary goal of the SWE-bench evaluation harness is to create a sandboxed environment for each task. This is crucial for several reasons:

- **Dependency Management**: Software projects often have complex and conflicting dependencies. Docker containers provide a way to isolate these dependencies for each project and task, preventing interference.
- **Reproducibility**: By encapsulating the entire environment, from the operating system to the specific versions of libraries, Docker ensures that an evaluation can be reproduced precisely at any time, on any machine.
- **Security**: Running untrusted code (e.g., patches from models) can be risky. The Docker sandbox provides a layer of security, isolating the execution from the host system.

## 2. The 3-Layer Docker Architecture

To achieve these goals efficiently, SWE-bench employs a 3-layer Docker image architecture. This layered approach is designed to maximize caching and minimize redundant builds.

### Layer 1: Base Images (`sweb.base:TAG`)

- **Purpose**: To provide the foundational, language-specific runtime environment.
- **Contents**:
    - A specific version of a programming language (e.g., Python 3.8, Java 11).
    - Common system-level dependencies and tools (e.g., `build-essential`, `git`, `curl`).
    - A non-root user (`docker`) to enhance security.
- **Naming Convention**: `sweb.base:<language>-<version>` (e.g., `sweb.base:python-3.8`).
- **Build Trigger**: Built once per unique language/version combination required by the dataset. These are typically pre-built or built on the first run.

### Layer 2: Environment Images (`sweb.env:TAG`)

- **Purpose**: To install the specific set of dependencies for a given software project at a particular version.
- **Contents**:
    - Everything from the corresponding base image.
    - Project-specific dependencies, as defined by files like `requirements.txt` (for Python), `package.json` (for JavaScript), or `pom.xml` (for Java).
- **Naming Convention**: `sweb.env:<repo_owner>__<repo_name>-<version_hash>` (e.g., `sweb.env:django__django-1.22.1`).
- **Build Trigger**: Built if it doesn't already exist for a specific project version. This is where the bulk of the caching benefits are realized, as a single environment image can be used for many different evaluation instances on the same project version.

### Layer 3: Instance Images (`sweb.eval:TAG`)

- **Purpose**: To create a ready-to-run evaluation environment containing the project's source code.
- **Contents**:
    - Everything from the corresponding environment image.
    - A clone of the project's Git repository.
    - The repository is checked out to the specific commit (`base_commit`) associated with the task instance.
- **Naming Convention**: `sweb.eval:<instance_id>`.
- **Build Trigger**: Built for each unique task instance being evaluated. These images are the most numerous and are often cleaned up after an evaluation run to save space.

## 3. The Image Building Workflow

The image building process is orchestrated by the `swebench.harness.docker_build` module. The workflow is lazy, meaning images are only built if they are not found locally.

1.  **`build_base_images`**:
    - Iterates through all tasks in the dataset.
    - Identifies the unique `base_image_key` for each task from its `TestSpec`.
    - Checks if the image exists locally using `client.images.get()`.
    - If not found, it calls the generic `build_image` function with the appropriate Dockerfile and platform.

2.  **`build_env_images`**:
    - First, ensures all necessary base images are built by calling `build_base_images`.
    - Identifies unique `env_image_key`s from the dataset.
    - For each key, it checks if the environment image exists.
    - If not, it calls `build_image`, providing the `setup_env.sh` script which contains the commands to install project dependencies. This script is generated from the `TestSpec`.

3.  **`build_instance_images`**:
    - Ensures the corresponding environment images are built first.
    - For each task instance, it checks if the instance image exists.
    - If not, it calls `build_image`, providing the `setup_repo.sh` script. This script handles cloning the repository and checking out the correct commit.

### The `TestSpec` Object

The `TestSpec` is a crucial data class that holds all the metadata required to build the images and run the evaluation for a single task instance. Key fields include:
- `instance_id`: A unique identifier for the task.
- `base_image_key`, `env_image_key`, `instance_image_key`: The names for the three image layers.
- `base_dockerfile`, `env_dockerfile`, `instance_dockerfile`: The string contents of the Dockerfiles for each layer.
- `setup_env_script`, `install_repo_script`: The shell scripts for setting up the environment and repository.
- `test_cmd`: The command used to run the test suite.

## 4. The Test Execution Flow

Once the instance image is ready, the evaluation for a single task proceeds as follows, managed primarily by `swebench.harness.run_evaluation`.

1.  **Container Creation**:
    - A new Docker container is created from the `sweb.eval` image using `client.containers.create()`.
    - The container is started in detached mode (`-d`) and runs a `tail -f /dev/null` command to keep it alive.

2.  **Patch Application**:
    - The model-generated patch (a `.patch` file) is copied from the host into the container's `/tmp` directory using `docker_utils.copy_to_container`.
    - The patch is applied to the repository using a command like `git apply /tmp/model.patch`. This is executed inside the container via `container.exec_run()`.

3.  **Test Command Execution**:
    - The core of the evaluation happens here. The `test_cmd` from the `TestSpec` is executed inside the container.
    - To prevent hangs, this is done using `docker_utils.exec_run_with_timeout`, which runs the command in a separate thread and joins it with a specified timeout (e.g., 600 seconds).
    - If the command thread is still alive after the timeout, it's terminated using `kill -TERM`.

4.  **Output and Result Parsing**:
    - The `stdout` and `stderr` from the test command are captured.
    - A language-specific log parser (e.g., `swebench.harness.log_parsers.python`) analyzes the output to determine the outcome. It looks for specific patterns that indicate success (e.g., "OK", "PASSED") or failure.
    - The result is categorized as `PASSED`, `FAILED`, `ERROR` (if the test command itself failed to run), or `TIMEOUT`.

5.  **Container Cleanup**:
    - Regardless of the outcome, the `cleanup_container` function is called to stop and remove the container, ensuring a clean state for the next evaluation.

## 5. Caching and Resource Management

Given the large number of Docker images that can be generated, SWE-bench includes mechanisms for managing disk space.

- **Cache Levels**: The `--cache_level` argument in `run_evaluation` controls which image layers are preserved between runs:
    - `none`: All images are removed after the run.
    - `base`: Only `sweb.base` images are kept.
    - `env`: (Default) `sweb.base` and `sweb.env` images are kept. This provides a good balance of speed and storage.
    - `instance`: All images, including `sweb.eval` images, are kept. Fastest for re-runs, but uses the most disk space.
- **Cleanup**: The `docker_utils.clean_images` function implements the logic for removing images based on the cache level and whether they existed before the current run.

This sophisticated Docker architecture is the backbone of SWE-bench, providing the reliability and consistency required for a robust benchmark of software engineering AI models.