import os
import hashlib
import hmac
import json
import subprocess
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional
import logging

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
# WEBHOOK_SECRET = "your-webhook-secret-here"  # Set this to your GitHub webhook secret
# DEPLOY_SCRIPT_PATH = "./deploy.sh"  # Path to your deploy script
# ALLOWED_BRANCHES = ["main", "master"]  # Branches that trigger deployment
# ALLOWED_EVENTS = ["push", "release"]  # GitHub events that trigger deployment

hook_secret = os.getenv("WEBHOOK_SECRET")
deploy_path = os.getenv("DEPLOY_SCRIPT_PATH")
allow_events = os.getenv("ALLOWED_EVENTS")
allow_branches = os.getenv("ALLOWED_BRANCHES")

app = FastAPI(title="GitHub Webhook Deploy Handler", version="1.0.0")


class WebhookProcessor:
    def __init__(self, script_path: str):
        self.script_path = Path(script_path)
        self.is_deploying = False

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

        elif event_type == "release":
            # Only deploy on published releases
            action = payload.get("action", "")
            if action != "published":
                return False, f"Release action '{action}' does not trigger deployment"

        return True, "Deployment conditions met"

    async def execute_deploy_script(self) -> tuple[bool, str, str]:
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
                str(self.script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.script_path.parent,
            )

            stdout, stderr = await process.communicate()

            success = process.returncode == 0
            return success, stdout.decode("utf-8"), stderr.decode("utf-8")

        except Exception as e:
            return False, "", f"Failed to execute deploy script: {str(e)}"


# Initialize webhook processor
webhook_processor = WebhookProcessor(deploy_path)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "GitHub Webhook Deploy Handler is running"}


@app.get("/status")
async def deployment_status():
    """Get current deployment status"""
    return {
        "is_deploying": webhook_processor.is_deploying,
        "deploy_script_exists": webhook_processor.script_path.exists(),
        "deploy_script_path": str(webhook_processor.script_path),
    }


async def run_deployment(payload: dict, event_type: str):
    """Background task to run deployment"""
    if webhook_processor.is_deploying:
        logger.warning("Deployment already in progress, skipping")
        return

    webhook_processor.is_deploying = True

    try:
        logger.info(f"Starting deployment for {event_type} event")

        # Log deployment context
        if event_type == "push":
            branch = payload.get("ref", "").replace("refs/heads/", "")
            commit = payload.get("after", "")[:7]
            logger.info(f"Deploying push to {branch} (commit: {commit})")
        elif event_type == "release":
            tag = payload.get("release", {}).get("tag_name", "unknown")
            logger.info(f"Deploying release {tag}")

        # Execute deployment script
        success, stdout, stderr = await webhook_processor.execute_deploy_script()

        if success:
            logger.info("Deployment completed successfully")
            if stdout:
                logger.info(f"Deploy script output:\n{stdout}")
        else:
            logger.error("Deployment failed")
            if stderr:
                logger.error(f"Deploy script error:\n{stderr}")
            if stdout:
                logger.info(f"Deploy script output:\n{stdout}")

    except Exception as e:
        logger.error(f"Deployment error: {str(e)}")
    finally:
        webhook_processor.is_deploying = False


@app.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitHub webhook requests"""
    try:
        # Get request body and headers
        payload_bytes = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        event_type = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")

        logger.info(f"Received {event_type} webhook (delivery: {delivery_id})")

        # Verify webhook signature
        if not webhook_processor.verify_signature(payload_bytes, signature):
            logger.warning(f"Invalid webhook signature for delivery {delivery_id}")
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Parse JSON payload
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            logger.error("Failed to parse webhook payload as JSON")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Check if deployment should be triggered
        should_deploy, reason = webhook_processor.should_deploy(event_type, payload)

        if not should_deploy:
            logger.info(f"Skipping deployment: {reason}")
            return JSONResponse(
                content={
                    "message": f"Webhook received but deployment skipped: {reason}"
                },
                status_code=200,
            )

        # Check if already deploying
        if webhook_processor.is_deploying:
            logger.warning("Deployment already in progress")
            return JSONResponse(
                content={"message": "Deployment already in progress"}, status_code=202
            )

        # Trigger deployment in background
        background_tasks.add_task(run_deployment, payload, event_type)

        logger.info(f"Deployment triggered for {event_type} event")
        return JSONResponse(
            content={"message": "Deployment triggered successfully"}, status_code=202
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/deploy")
async def manual_deploy(background_tasks: BackgroundTasks):
    """Manually trigger deployment (for testing)"""
    if webhook_processor.is_deploying:
        return JSONResponse(
            content={"message": "Deployment already in progress"}, status_code=202
        )

    # Create a fake payload for manual deployment
    fake_payload = {"ref": "refs/heads/main", "commits": [{"id": "manual"}]}

    background_tasks.add_task(run_deployment, fake_payload, "push")

    return JSONResponse(
        content={"message": "Manual deployment triggered"}, status_code=202
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
