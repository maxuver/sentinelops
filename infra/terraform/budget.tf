# A spend alarm, because the expensive failure mode here is not the demo — it is
# forgetting to destroy afterwards. The EKS control plane and the NAT gateway
# bill by the hour whether or not anything is running, so an idle cluster costs
# roughly $100/month while producing nothing.
#
# Created only when budget_alert_email is set, so the module still applies for
# someone who would rather manage budgets outside Terraform.

resource "aws_budgets_budget" "monthly" {
  count = var.budget_alert_email == "" ? 0 : 1

  name         = "${var.cluster_name}-monthly"
  budget_type  = "COST"
  limit_amount = var.budget_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Fires while there is still time to react, not after the bill arrives.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}
