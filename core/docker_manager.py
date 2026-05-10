import subprocess
import logging
import time
import os

logger = logging.getLogger("antigravity.docker_manager")

class DockerManager:
    """
    Manages a sandboxed Docker container for secure code execution.
    """
    
    def __init__(self, image_name="antigravity-sandbox", container_name="antigravity-worker"):
        self.image_name = image_name
        self.container_name = container_name
        self.is_active = False

    def build_image(self, dockerfile_path="Dockerfile.sandbox"):
        """Build the sandbox image if it doesn't exist."""
        logger.info(f"Building Docker image: {self.image_name}...")
        try:
            subprocess.run(
                ["docker", "build", "-t", self.image_name, "-f", dockerfile_path, "."],
                check=True,
                capture_output=True
            )
            logger.info("Docker image built successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to build Docker image: {e.stderr.decode()}")
            return False

    def start_container(self, workspace_path=None):
        """Start the sandbox container."""
        # Check if container already exists
        result = subprocess.run(["docker", "ps", "-a", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"], capture_output=True, text=True)
        
        if self.container_name in result.stdout:
            logger.info(f"Container {self.container_name} already exists. Removing to refresh mounts...")
            subprocess.run(["docker", "stop", self.container_name], capture_output=True)
            subprocess.run(["docker", "rm", self.container_name], capture_output=True)
        
        logger.info(f"Starting new container {self.container_name}...")
        # Mount workspace if provided
        mount_args = []
        if workspace_path and os.path.exists(workspace_path):
            mount_args = ["-v", f"{os.path.abspath(workspace_path)}:/workspace"]
        
        subprocess.run(
            ["docker", "run", "-d", "--name", self.container_name] + mount_args + [self.image_name],
            check=True,
            capture_output=True
        )
        
        self.is_active = True
        return True

    def execute(self, command: str, cwd: str = "/workspace") -> tuple:
        """Execute a command inside the container."""
        if not self.is_active:
            self.start_container()
            
        logger.debug(f"Docker Exec: {command}")
        
        # We use 'bash -c' to support piping and complex commands
        exec_cmd = ["docker", "exec", "-w", cwd, self.container_name, "bash", "-c", command]
        
        try:
            result = subprocess.run(exec_cmd, capture_output=True, text=True, timeout=60)
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out in Docker sandbox."
        except Exception as e:
            return -1, "", f"Docker execution error: {str(e)}"

    def stop_container(self):
        """Stop and remove the container."""
        logger.info(f"Stopping container {self.container_name}...")
        subprocess.run(["docker", "stop", self.container_name], capture_output=True)
        subprocess.run(["docker", "rm", self.container_name], capture_output=True)
        self.is_active = False

# Singleton
_docker_instance = None

def get_docker_manager() -> DockerManager:
    global _docker_instance
    if _docker_instance is None:
        _docker_instance = DockerManager()
    return _docker_instance
