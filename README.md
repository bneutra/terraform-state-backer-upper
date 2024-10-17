# Terraform Cloud/Enterprise State Saver

```
This is a fork of https://github.com/bneutra/terraform-state-backer-upper:
- fix bugs
- support run tasks (which is a better solution at this point)
- use the community lambda to streamline things a bit
- TODO: the rest of this README is un-altered, so out of date re: using notifications
```

This is an AWS Lambda function that receives notifications from Terraform Cloud workspaces, and saves that workspace's latest state file into a corresponding S3 bucket.

This workspace will require AWS access/credentials to provision.

## Usage

First, provision with Terraform.

### Variables
Please provide values for the following [variables](https://www.terraform.io/docs/language/values/variables.html#assigning-values-to-root-module-variables):
* `notification_token`: used to generate the HMAC on the notification request. Read more in the [documentation](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings/notifications#notification-authenticity).
* `prefix`: a name prefix to add to the resources
* `region`: the AWS region where the resources will be created
* `tfc_token`: The [Terraform Cloud API token](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/api-tokens) you would like to use. This should be a team token with the "[Read state versions](https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/permissions#general-workspace-permissions)" permission on all workspaces. NOTE: This is a secret and should be marked as sensitive in Terraform Cloud. 

In addition, I recommend that you review all other variables and configure their values according to your specifications. `ttl` and `common_tags` are used only for tagging and are completely optional.

### Enabling the Webhook on Workspaces

Once the resources have been created, we need to enable the webhook on Terraform Cloud workspaces by adding a [workspace notification configuration](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings/notifications). This can be done manually, with Terraform, or via API calls. [This documentation](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/settings/notifications#creating-a-notification-configuration) covers how to do this manually.

Here's an example usage with the [TFE provider](https://registry.terraform.io/providers/hashicorp/tfe/latest/docs):
```
resource "tfe_notification_configuration" "state_saver_webhook" {
 name                      = "state-saver"
 enabled                   = true
 destination_type          = "generic"
 triggers                  = ["run:completed"]
 url                       = data.tfe_outputs.state-saver.values.webhook_url
 workspace_external_id     = tfe_workspace.my-workspace.id
}
```

If you have many workspaces, [`for_each`](https://developer.hashicorp.com/terraform/language/meta-arguments/for_each) will be useful.

Lastly, [here](./files/add_notification_to_workspaces.sh) is a simple shell script that will add the notification configuration to one or more workspaces in the organization specified. You must provide:
1. a Terraform Cloud organization or admin user token as the environment variable `TOKEN`.
2. the notification token you've configured (Terraform variable `notification_token`) as the environment variable `HMAC_SALT`.
3. the workspace(s) to which you'd like to add the notification configuration.
4. the webhook URL output from Terraform.

Example usage:
```
→ ./files/add_notification_to_workspaces.sh hashidemos workspace-1 https://h8alki27g6.execute-api.us-west-2.amazonaws.com/state-saver
```
