# SentinelOps on AWS EKS (Terraform)

Production-shaped infrastructure as code for an **ephemeral** EKS cluster:
a VPC (three AZs, single NAT gateway for cost) plus an EKS cluster with a managed
node group, built on the community `terraform-aws-modules` (the same modules
behind EKS blueprints).

## Status (honest)

`terraform init` and `terraform validate` pass. **Applying requires AWS
credentials** and is intentionally ephemeral: apply, deploy the Helm chart, demo,
then `destroy`, to keep the bill to a few dollars. The same
[`deploy/sentinelops`](../../deploy/sentinelops) Helm chart runs unchanged on
this cluster and on local kind, so nothing about the application layer is
AWS-specific.

## Validate (no AWS account needed)

```bash
cd infra/terraform
terraform init
terraform validate
```

## Provision, demo, destroy (needs AWS credentials)

```bash
export AWS_ACCESS_KEY_ID=...        # or an SSO / profile
export AWS_SECRET_ACCESS_KEY=...

terraform init
terraform plan
terraform apply

aws eks update-kubeconfig --region eu-central-1 --name sentinelops
helm upgrade --install so ../../deploy/sentinelops -n sentinelops --create-namespace

# ... demo ...

terraform destroy   # important: tear it down when finished
```

## What it costs

The expensive mistake is not running the demo — it is forgetting to destroy it
afterwards. The EKS control plane and the NAT gateway bill hourly whether or not
anything is running.

| Line item | Rate | 3-hour demo | Left running a month |
|---|---|---|---|
| EKS control plane | $0.10/hour | $0.30 | **$73** |
| 2× t3.small (SPOT) | ~$0.007/hour each | $0.04 | ~$10 |
| NAT gateway | $0.045/hour + traffic | $0.14 | **$33** |
| EBS volumes | — | ~$0.01 | ~$3 |
| **Total** | | **≈ $0.50** | **≈ $120** |

Rates are list prices for a typical EU/US region and move over time; check the
[AWS pricing calculator](https://calculator.aws) for your own region before a
long-running deployment. The shape of the answer does not change: a demo is
cents, a forgotten cluster is real money.

### The spend alarm

Set `budget_alert_email` and Terraform creates a monthly AWS Budget that warns at
50% of actual spend and again when the forecast crosses the limit:

```bash
terraform apply -var budget_alert_email=you@example.com -var budget_limit_usd=10
```

Leave it empty and no budget is created, for teams that manage budgets centrally.

## Cost control

- `single_nat_gateway = true` (one NAT, not one per AZ)
- `capacity_type = "SPOT"` on small `t3.small` nodes
- Everything tagged `Lifecycle = ephemeral`

Destroy the cluster when the demo is over. This is not meant to run 24/7.
