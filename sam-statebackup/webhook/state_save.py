""" state_save.py
This script receives notifications from our TFC webhook
and automatically saves the latest state file from the workspace
to an S3 bucket. 
"""

import base64
import hashlib
import json
import os
import boto3
import requests


DRY_RUN = os.getenv("DRY_RUN", False)
REGION = os.getenv("REGION", None)
S3_BUCKET = os.getenv("S3_BUCKET", None)
TFC_TOKEN_PATH = os.getenv("TFC_TOKEN_PATH", None)
# run task requires this response body
OK_RESPONSE = "200 OK"


# Initialize boto3 client at global scope for connection reuse
session = boto3.Session(region_name=REGION)
ssm = session.client("ssm")
s3 = boto3.resource("s3")


def lambda_handler(event: dict, context) -> dict:
    """Handle the incoming requests"""
    print(event)
    save_state(
        event["workspace_id"],
        event["workspace_name"],
    )


def get_tfc_token() -> str:
    """Get the TFC token from the SSM parameter store."""
    tfc_api_token = bytes(
        ssm.get_parameter(Name=TFC_TOKEN_PATH, WithDecryption=True)["Parameter"][
            "Value"
        ],
        "utf-8",
    )
    return tfc_api_token.decode("utf-8")



def get_headers(token: str) -> dict:
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/vnd.api+json",
    }


def save_state(workspace_id: str, workspace_name: str) -> None:
    """Save the state file to the S3 bucket."""

    # TODO: in the event of an error, we could retry but I anticipiate
    # throttling issues with the TFC API. One possible approach:
    # record a marker object in S3 with the run ID and workspace name
    # an hourly lambda could check for these markers and retry the save

    state_api_url = (
        "https://app.terraform.io/api/v2/workspaces/"
        + workspace_id
        + "/current-state-version"
    )

    tfc_headers = get_headers(get_tfc_token())
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

    if DRY_RUN:
        print(f"DRY RUN: Not saving state file to {S3_BUCKET}/{workspace_name}")
        return
    s3_response = s3.Bucket(S3_BUCKET).put_object(
        Key=workspace_name, Body=encoded_state, ContentMD5=state_md5
    )
    print("State file saved: ", s3_response)

