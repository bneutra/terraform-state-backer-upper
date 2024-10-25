""" main.py
This script receives notifications from Terraform Cloud workspaces
and automatically saves the latest state file from that workspace
to a corresponding S3 bucket. 
"""

import base64
import hashlib
import hmac
import json
import os
import boto3
import requests


DRY_RUN = os.getenv("DRY_RUN", False)
REGION = os.getenv("REGION", None)
S3_BUCKET = os.getenv("S3_BUCKET", None)
SALT_PATH = os.getenv("SALT_PATH", None)
TFC_TOKEN_PATH = os.getenv("TFC_TOKEN_PATH", None)
# run task requires this response body
OK_RESPONSE = "200 OK"
NOTIFICATION_APPLY_STATE = "applied"
RUN_TASK_APPLY_STATE = "post_apply"


# Initialize boto3 client at global scope for connection reuse
session = boto3.Session(region_name=REGION)
ssm = session.client("ssm")
s3 = boto3.resource("s3")


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


def run_task_post(event: dict) -> dict:
    """Handle a POST request for run tasks."""

    payload = json.loads(event["body"])

    if payload["stage"] is None:
        ("Run stage set to null in payload. Test event?")
    elif payload["stage"] == RUN_TASK_APPLY_STATE:
        workspace_id = payload["workspace_id"]
        workspace_name = payload["workspace_name"]
        callback_url = payload["task_result_callback_url"]
        access_token = payload["access_token"]
        if any([not workspace_id, not workspace_name, not callback_url, not access_token]):
            raise Exception(
                "Missing workspace_id, workspace_name, callback_url, or access_token"
            )
        try:
            if DRY_RUN:
                print("DRY RUN: Not saving state file.")
            else:
                task_callback(callback_url, access_token, "Saving tfstate", "running")
                save_state(workspace_id, workspace_name, get_tfc_token())
                task_callback(callback_url, access_token, "State saved", "passed")
        except Exception as e:
            task_callback(callback_url, access_token, f"Exception saving state: {e}", "failed")
            raise e
    else:
        raise Exception("Unsupported run stage: ", payload["stage"])
    return {"statusCode": 200, "body": OK_RESPONSE}


def notification_post(event: dict) -> dict:
    """Handle a POST request for notifications."""
    payload = json.loads(event["body"])

    if payload and "run_status" in payload["notifications"][0]:
        body = payload["notifications"][0]
        if body["run_status"] is None:
            print("WARNING: run_status set to null in payload. Test event?")
        elif body["run_status"] == NOTIFICATION_APPLY_STATE:
            print("run_status indicates save the state file.")
            workspace_id = payload["workspace_id"]
            workspace_name = payload["workspace_name"]
            if any([not workspace_id, not workspace_name]):
                raise Exception("Missing workspace_id or workspace_name")
            if DRY_RUN:
                print("DRY RUN: Not saving state file.")
            else:
                save_state(workspace_id, workspace_name, get_tfc_token())
        else:
            print("WARNING: Unsupported run status: ", body["run_status"])
    return {"statusCode": 200, "body": OK_RESPONSE}


def get_tfc_token() -> str:
    """Get the TFC token from the SSM parameter store."""
    tfc_api_token = bytes(
        ssm.get_parameter(Name=TFC_TOKEN_PATH, WithDecryption=True)["Parameter"][
            "Value"
        ],
        "utf-8",
    )
    return tfc_api_token.decode("utf-8")


def task_callback(callback_url: str, access_token: str, message: str, status: str) -> None:
    """Send a PATCH request to the callback URL."""
    payload = {
        "data": {
            "type": "task-result",
            "attributes": {
                "status": status,
                "message": message,
            },
        }
    }
    tfc_headers = get_headers(access_token)
    response = requests.patch(callback_url, headers=tfc_headers, json=payload)
    if response.status_code > 399:
        raise Exception("Error sending task callback: ", response.text)
    print("Task callback sent successfully: ", response.status_code)


def get_headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/vnd.api+json",
    }


def save_state(workspace_id: str, workspace_name: str, tfc_api_token: str) -> None:
    """Save the state file to the S3 bucket."""

    state_api_url = (
        "https://app.terraform.io/api/v2/workspaces/"
        + workspace_id
        + "/current-state-version"
    )

    tfc_headers = get_headers(tfc_api_token)
    state_api_response = requests.get(state_api_url, headers=tfc_headers)

    state_response_payload = json.loads(state_api_response.text)
    if state_api_response.status_code > 399:
        raise Exception("Error retrieving workspace info: ", state_response_payload)

    archivist_url = state_response_payload["data"]["attributes"][
        "hosted-state-download-url"
    ]

    archivist_response = requests.get(archivist_url, headers=tfc_headers)
    if archivist_response.status_code > 399:
        raise Exception("Error retrieving state file: ", archivist_response.text)

    encoded_state = archivist_response.text.encode("utf-8")

    state_md5 = base64.b64encode(hashlib.md5(encoded_state).digest()).decode("utf-8")

    s3_response = s3.Bucket(S3_BUCKET).put_object(
        Key=workspace_name, Body=encoded_state, ContentMD5=state_md5
    )
    print("State file saved: ", s3_response)
