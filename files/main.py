""" This script receives notifications from Terraform Cloud workspaces
    and automatically saves the latest state file from that workspace
    to a corresponding S3 bucket. """

import base64
import hashlib
import hmac
import json
import os
import boto3
from botocore.exceptions import ClientError
import requests


REGION = os.getenv("REGION", None)
S3_BUCKET = os.getenv("S3_BUCKET", None)
SALT_PATH = os.getenv("SALT_PATH", None)
TFC_TOKEN_PATH = os.getenv("TFC_TOKEN_PATH", None)
# run task requires this response body
OK_RESPONSE = "200 OK"
SAVE_STATES = {'applied'}


# Initialize boto3 client at global scope for connection reuse
session = boto3.Session(region_name=REGION)
ssm = session.client('ssm')
s3 = boto3.resource('s3')


def lambda_handler(event, context):
    """ Handle the incoming requests """
    print(event)
    # first we need to authenticate the message by verifying the hash
    message = bytes(event['body'], 'utf-8')
    salt = bytes(ssm.get_parameter(Name=SALT_PATH, WithDecryption=True)[
        'Parameter']['Value'], 'utf-8')
    hash = hmac.new(salt, message, hashlib.sha512)
    if hash.hexdigest() == event['headers'].get('X-Tfe-Notification-Signature'):
        # NOTE: I think run tasks are a better solution for this use case.
        # but I'm leaving this here for now.
        if event['httpMethod'] == "POST":
            return notification_post(event)
        return get()
    elif hash.hexdigest() == event['headers'].get('X-Tfc-Task-Signature'):
        if event['httpMethod'] == "POST":
            return run_task_post(event)
        return get()

    print('Invalid HMAC')
    return 'Invalid HMAC'


def get():
    """ Handle a GET request """
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": OK_RESPONSE
    }


def run_task_post(event):
    """Handle a POST request for run tasks."""
    payload = json.loads(event['body'])

    if payload and 'workspace_id' in payload:
        if payload['stage'] is None:
            print("Run status set to null in payload.")
        if payload['stage'] != 'post_apply':
            print(f"Run status is {payload['stage']}. We expect post_apply.")
        else:
            workspace_id = payload['workspace_id']
            workspace_name = payload['workspace_name']
            save_state(workspace_id, workspace_name)
    return {
        "statusCode": 200,
        "body": OK_RESPONSE
    }

def notification_post(event):
    """Handle a POST request for notifications."""

    payload = json.loads(event['body'])

    if payload and 'run_status' in payload['notifications'][0]:
        body = payload['notifications'][0]
        if not body['run_status']:
            print("Run status set to null in payload.")

        if body['run_status'] in SAVE_STATES:
            print("Run status indicates save the state file.")
            workspace_id = payload['workspace_id']
            workspace_name = payload['workspace_name']
            save_state(workspace_id, workspace_name)
    return {
        "statusCode": 200,
        "body": OK_RESPONSE
    }

def save_state(workspace_id, workspace_name):
            tfc_api_token = bytes(ssm.get_parameter(
                Name=TFC_TOKEN_PATH, WithDecryption=True)['Parameter']['Value'], 'utf-8')
            tfc_api_token = tfc_api_token.decode("utf-8")

            state_api_url = 'https://app.terraform.io/api/v2/workspaces/' + \
                workspace_id + '/current-state-version'

            tfc_headers = {'Authorization': 'Bearer ' + tfc_api_token,
                            'Content-Type': 'application/vnd.api+json'}

            state_api_response = requests.get(
                state_api_url, headers=tfc_headers)

            state_response_payload = json.loads(state_api_response.text)
            if "error"

            archivist_url = state_response_payload['data']['attributes'][
                'hosted-state-download-url']

            archivist_response = requests.get(
                archivist_url, headers=tfc_headers)
            if "error" in archivist_response.text:
                raise Exception("Error retrieving state file: ", archivist_response.text)

            encoded_state = archivist_response.text.encode('utf-8')

            state_md5 = base64.b64encode(hashlib.md5(
                encoded_state).digest()).decode('utf-8')

            try:
                s3_response = s3.Bucket(S3_BUCKET).put_object(
                    Key=workspace_name, Body=encoded_state, ContentMD5=state_md5)
                print("State file saved: ", s3_response)
            except ClientError as error:
                print(error)