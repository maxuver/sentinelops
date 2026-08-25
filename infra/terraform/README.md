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

## Cost control

- `single_nat_gateway = true` (one NAT, not one per AZ)
- `capacity_type = "SPOT"` on small `t3.small` nodes
- Everything tagged `Lifecycle = ephemeral`

Destroy the cluster when the demo is over. This is not meant to run 24/7.
