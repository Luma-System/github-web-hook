import os
import json
import asyncio
import logging
from pathlib import Path


class WebhookProcessor:
    def __init__(self, script_path: str):
        self.script_path = Path(script_path)
        self.is_deploying = False
        self.status = {}
        
    def error(self, error):
        self.status['error'] = error
        
    def message(self, message):
        self.status['message'] = message

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature"""
        if not signature.startswith("sha256="):
            return False

        expected_signature = hmac.new(
            hook_secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()

        provided_signature = signature[7:]  # Remove 'sha256=' prefix
        return hmac.compare_digest(expected_signature, provided_signature)

    def should_deploy(self, event_type: str, payload: dict) -> tuple[bool, str]:
        """Determine if deployment should be triggered"""
        if event_type not in allow_events:
            return False, f"Event type '{event_type}' not in allowed events"

        if event_type == "push":
            ref = payload.get("ref", "")
            branch = ref.replace("refs/heads/", "")

            if branch not in allow_branches:
                return False, f"Branch '{branch}' not in allowed branches"

            # Skip if no commits (e.g., branch deletion)
            if not payload.get("commits"):
                return False, "No commits in push event"
            
            repo = payload.get("repository")
            # new_env = os.environ.copy()
            new_env = {}
            new_env['REPO_BRANCH'] = branch
            new_env['REPO_NAME'] = repo.get('name')
            new_env['REPO_LINK'] = repo.get("git_url")
            new_env['REPO_FULL'] = repo.get("full_name")
            new_env['REPO_DATE'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if not os.path.exists(deploy_path):
                print(f"Deploy script not found at {deploy_path}")
                return False, f"Deploy script not found at {deploy_path}"
            
            result = subprocess.run(
                ["sh", deploy_path],
                env=new_env,
                text=True,
                check=True,
                capture_output=True
            )
            print(result.stdout, result.stderr)

        elif event_type == "release":
            # Only deploy on published releases
            action = payload.get("action", "")
            if action != "published":
                return False, f"Release action '{action}' does not trigger deployment"

        return True, "Deployment conditions met"

    async def execute_deploy_script(self, new_env) -> tuple[bool, str, str]:
        """Execute the deployment script asynchronously"""
        if not self.script_path.exists():
            return False, "", f"Deploy script not found at {self.script_path}"

        if not self.script_path.is_file():
            return False, "", f"Deploy script path is not a file: {self.script_path}"

        try:
            # Make script executable
            self.script_path.chmod(0o755)
            
            # Execute script
            process = await asyncio.create_subprocess_exec(
                self.script_path.resolve(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # cwd=os.getcwd(),
                env=new_env
            )

            stdout, stderr = await process.communicate()

            success = process.returncode == 0
            return success, stdout.decode("utf-8"), stderr.decode("utf-8")

        except Exception as e:
            return False, "", f"Failed to execute deploy script: {str(e)}"
    
    async def execute_script(self, app, path, commands) -> tuple[bool, str, str]:
        self.status[app] = {}
        
        cmd = ' && '.join(commands)
        self.error('')
        self.status[app]['cmd'] = cmd
        
        if not os.path.exists(path):
            self.status[app]['path'] = f"Deploy [{path}] not found"
            return False, "", f"Deploy [{path}] not found"
        
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path
            )

            out, err = await process.communicate()
            stdout = out.decode().strip()
            stderr = err.decode().strip()
            
            # self.status[app]['stdout'] = json.dumps(stdout, indent=2)
            # self.status[app]['stderr'] = json.dumps(stderr, indent=2)
            self.status[app]['stdout'] = stdout.splitlines()
            self.status[app]['stderr'] = stderr.splitlines()
            self.status[app]['returncode'] = process.returncode

            success = process.returncode == 0
            return success, stdout, stderr

        except Exception as e:
            self.status[app]['error'] = str(e)
            return False, "", f"Failed to execute deploy script: {str(e)}"
