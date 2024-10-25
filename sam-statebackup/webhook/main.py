""" main.py
This script receives notifications from Terraform Cloud workspaces
and run tasks and invokes the appropriate handler function based on the
notification type or run task stage.
"""

import hashlib
import hmac
import json
import os
import boto3
import lib


DRY_RUN = os.getenv("DRY_RUN", False)
REGION = os.getenv("REGION", None)
SALT_PATH = os.getenv("SALT_PATH", None)
# run task requires this response body
OK_RESPONSE = "200 OK"
# map of what function to call based on the notification type
NOTIFICATIONS_MAP = {
    "applied": os.environ["STATE_SAVE_FUNCTION"],
}
# map of what function to call based on the run task stage (TBD)
RUN_TASK_MAP = {
    "post_apply": None,
}

# Initialize boto3 client at global scope for connection reuse
session = boto3.Session(region_name=REGION)
ssm = session.client("ssm")


def lambda_handler(event: dict, context) -> dict:
    """Handle the incoming requests"""
    print(event)
    # first we need to authenticate the message by verifying the hash
    message = bytes(event["body"], "utf-8")
    salt = bytes(
        ssm.get_parameter(Name=SALT_PATH, WithDecryption=True)["Parameter"]["Value"],
        "utf-8",
    )
    hash = hmac.new(salt, message, hashlib.sha512)
    # support either notification or run task post-apply events: you choose
    if hash.hexdigest() == event["headers"].get("X-Tfe-Notification-Signature"):
        if event["httpMethod"] == "POST":
            return notification_post(event)
        if event["httpMethod"] == "GET":
            return get()
    elif hash.hexdigest() == event["headers"].get("X-Tfc-Task-Signature"):
        if event["httpMethod"] == "POST":
            return run_task_post(event)
        if event["httpMethod"] == "GET":
            return get()
    print("Invalid HMAC signature")
    return {"statusCode": 400, "body": "Invalid HMAC signature"}


def get() -> dict:
    """Handle a GET request"""
    return {"statusCode": 200, "body": OK_RESPONSE}


def notification_post(event: dict) -> dict:
    """Handle a POST request for notifications."""
    payload = json.loads(event["body"])

    if payload and "run_status" in payload["notifications"][0]:
        body = payload["notifications"][0]
        if body["run_status"] is None:
            print("WARNING: run_status set to null in payload. Test event?")
        elif body["run_status"] in NOTIFICATIONS_MAP:
            print("run_status indicates save the state file.")
            workspace_id = payload["workspace_id"]
            workspace_name = payload["workspace_name"]
            if any([not workspace_id, not workspace_name]):
                raise Exception("Missing workspace_id or workspace_name")
            function_name = NOTIFICATIONS_MAP[body["run_status"]]
            if DRY_RUN:
                print(f"DRY RUN: Not invoking {function_name}")
            else:
                invoke(function_name, payload)
        else:
            print("WARNING: Unsupported run status: ", body["run_status"])
    return {"statusCode": 200, "body": OK_RESPONSE}


def run_task_post(event: dict) -> dict:
    """Handle a POST request for run tasks."""

    payload = json.loads(event["body"])

    if payload["stage"] is None:
        ("Run stage set to null in payload. Test event?")
    elif payload["stage"] in RUN_TASK_MAP:
        workspace_id = payload["workspace_id"]
        workspace_name = payload["workspace_name"]
        callback_url = payload["task_result_callback_url"]
        access_token = payload["access_token"]
        if any([not workspace_id, not workspace_name, not callback_url, not access_token]):
            raise Exception(
                "Missing workspace_id, workspace_name, callback_url, or access_token"
            )
        if DRY_RUN:
            print("DRY RUN: Not saving state file.")
        else:
            lib.task_callback(callback_url, access_token, "Saving tfstate", "running")
            invoke(RUN_TASK_MAP[payload["stage"]], payload)
            # called function should call task_callback with "passed" or "failed"
    else:
        raise Exception("Unsupported run stage: ", payload["stage"])
    return {"statusCode": 200, "body": OK_RESPONSE}



def invoke(function_name: str, tfc_payload: dict) -> None:
    """Invoke the TFC handler function."""

    lambda_client = boto3.client('lambda')
    # TODO: does this raise?
    print(f"Invoking {function_name} with payload: {tfc_payload}")
    lambda_client.invoke(
        FunctionName=function_name,
        InvocationType='Event',  # 'Event' for asynchronous execution
        Payload=json.dumps(tfc_payload)
    )
    
    return {
        "statusCode": 200,
        "body": f"Invoked {function_name} successfully"
    }
