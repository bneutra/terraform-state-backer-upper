variable "prefix" {
  description = "Name prefix to add to the resources"
  default     = "brendan-test"
}

variable "region" {
  description = "The region where the resources are created."
  default     = "us-west-2"
}

// OPTIONAL Tags
locals {
  common_tags = {
    owner              = "your-name-here"
    se-region          = "your-region-here"
    purpose            = "Back up state files"
    terraform          = "true"  # true/false
    hc-internet-facing = "false" # true/false
  }
}
