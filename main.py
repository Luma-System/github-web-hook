import os
import sys
import hashlib
import hmac
import json
import yaml
import subprocess
import asyncio
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import logging
import uvicorn

from core.services import WebhookProcessor

load_dotenv()

logging.basicConfig(
    filename='logs/app.log',               
    level=logging.DEBUG,              
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

host_port = os.getenv("PORT", 9798)
hook_secret = os.getenv("WEBHOOK_SECRET")
deploy_path = os.getenv("DEPLOY_SCRIPT_PATH")
allow_events = os.getenv("ALLOWED_EVENTS")
allow_branches = os.getenv("ALLOWED_BRANCHES")


def json_res(code, message):
    logger.debug(message)
    return JSONResponse(
        content={"message": message}, status_code=code
    )


def raise_err(code, message):
    logger.error(message)
    raise HTTPException(status_code=code, detail=message)


app = FastAPI(title="GitHub Webhook Deploy Handler", version="1.0.0")

# Initialize webhook processor
service = WebhookProcessor(deploy_path)

@app.middleware("http")
async def log_request_data(request: Request, call_next):
    client_host = request.client.host
    path = request.url.path
    headers = dict(request.headers)
    logging.info(f"[REQUEST] From {client_host}, Path: {path}, Headers: {headers}")
    response = await call_next(request)
    return response

@app.get("/")
async def root():
    return {"welcome": "Hi bro what are you doing here :D ???"}


@app.get("/status")
async def deployment_status_app():
    """Get current deployment status of app"""
    return {
        "status": service.status,
    }
    
async def run_deployment(payload: dict, event_type: str):
    try:
        logger.debug(f"Starting deployment for {event_type} event")

        # Log deployment context
        if event_type == "push":
            branch = payload.get("ref", "").replace("refs/heads/", "")
            commit = payload.get("after", "")[:7]
            logger.debug(f"Deploying push to {branch} (commit: {commit})")
        elif event_type == "release":
            tag = payload.get("release", {}).get("tag_name", "unknown")
            logger.debug(f"Deploying release {tag}")

        repo = payload.get("repository")
        
        if not os.path.exists("deploy.yaml"):
            await service.error(f"The deploy.yaml not found")
            sys.exit(1)
            
        with open("deploy.yaml") as f:
            config = yaml.safe_load(f)
        
        apps = config.get("apps", {})
        repo_name = repo.get('name')
        
        if repo_name in apps:
            app = apps[repo_name]
            path = app.get("path")
            commands = app.get("commands", [])
            await service.execute_script(repo_name, path, commands)
        else:
            await service.error(f"Unknown apps.{repo_name}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Deployment error: {str(e)}")
        service.error(f"Deployment error: {str(e)}")
 


@app.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitHub webhook requests"""
    try:
        payload_bytes = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        event_type = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        
        logger.info(f"Received {event_type} webhook (delivery: {delivery_id})")

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            background_tasks.add_task(run_deployment, payload, event_type)
        except json.JSONDecodeError:
            return raise_err(400, "Invalid JSON payload")

        # if not service.verify_signature(payload_bytes, signature):
        #     return raise_err(400, "Invalid signature")

        return json_res(202, f"Deployment triggered {event_type} successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return raise_err(500, "Internal server error")
    
    

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=host_port,
        reload=True,
    )
