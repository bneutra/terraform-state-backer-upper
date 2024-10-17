# Terraform Cloud/Enterprise State Saver

```
This is a fork of https://github.com/bneutra/terraform-state-backer-upper:
- fix bugs
- support run tasks (which is a better solution at this point)
- use the community lambda to streamline things a bit
```

This is an AWS Lambda function that receives notifications from Terraform Cloud workspaces, and saves that workspace's latest state file into a corresponding S3 bucket.

This workspace will require AWS access/credentials to provision.

## Usage

First, provision with Terraform.

### Variables
Provide values for the following [variables](https://www.terraform.io/docs/language/values/variables.html#assigning-values-to-root-module-variables):
* `prefix`: a name prefix to add to the resources
* `region`: the AWS region where the resources will be created

### Secrets
The Lambda acquires two secrets from SSM. After Terraform applying (creating the SSM params), update them in the AWS console (persisting secrets in terraform state is a bad practice):
- HMAC, set to anything secure, save it so you can input it when creating the run task in TFC
- TFC Token. Provision in TFC (individual or team token with workspace and state read permission)


### Enabling the Webhook on Workspaces
https://developer.hashicorp.com/terraform/enterprise/api-docs/run-tasks/run-tasks



