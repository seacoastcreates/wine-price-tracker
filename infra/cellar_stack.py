"""Cellar Index on AWS: one EC2 instance (Next.js + FastAPI model service + PostgreSQL behind nginx),
CloudFront in front for HTTPS and caching, an S3 bucket for nightly database backups, and a monthly
budget with email alerts.

The instance is built from scratch on first boot from two CDK assets: the source tree and a data
bundle (database dump + active model), see deploy/bootstrap.sh. Any change to either replaces the
instance, so every deploy is a clean, reproducible build.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, IgnoreMode, RemovalPolicy, Stack, Tags
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as assets
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
UBUNTU_ARM64 = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
SOURCE_EXCLUDES = [
    ".git", "**/node_modules", "**/.next", "**/.venv", "**/__pycache__", "**/*.egg-info", "**/.DS_Store",
    "data", "ml/data", "ml/artifacts", "ml/registry", "deploy/bundle", "infra/cdk.out", "infra/.venv",
    "**/.env*",
]


class CellarStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, alert_email: str, cloudfront_prefix_list: str,
                 monthly_budget_usd: int = 20, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        Tags.of(self).add("project", "cellar-index")

        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # ---- code and data, uploaded as CDK assets ------------------------------------------------
        source = assets.Asset(self, "Source", path=str(REPO), exclude=SOURCE_EXCLUDES, ignore_mode=IgnoreMode.GLOB)
        bundle = assets.Asset(self, "DataBundle", path=str(REPO / "deploy" / "bundle"))

        backups = s3.Bucket(
            self, "Backups",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ---- instance ---------------------------------------------------------------------------
        role = iam.Role(
            self, "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
            description="Cellar Index server - SSM access, read deploy assets, write DB backups",
        )
        source.grant_read(role)
        bundle.grant_read(role)
        backups.grant_put(role, "backups/*")

        sg = ec2.SecurityGroup(self, "WebSg", vpc=vpc, allow_all_outbound=True,
                               description="Cellar Index - HTTP from CloudFront only, no SSH")
        sg.add_ingress_rule(ec2.Peer.prefix_list(cloudfront_prefix_list), ec2.Port.tcp(80),
                            "HTTP from CloudFront origin-facing servers only")

        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -euxo pipefail",
            "exec > >(tee -a /var/log/cellar-bootstrap.log) 2>&1",
            f"export AWS_DEFAULT_REGION={self.region}",
            "apt-get update && apt-get install -y unzip curl",
            "curl -sSL https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip -o /tmp/awscli.zip",
            "unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install --update",
            "mkdir -p /tmp/cellar/src /tmp/cellar/bundle",
            f"/usr/local/bin/aws s3 cp s3://{source.s3_bucket_name}/{source.s3_object_key} /tmp/cellar/src.zip",
            f"/usr/local/bin/aws s3 cp s3://{bundle.s3_bucket_name}/{bundle.s3_object_key} /tmp/cellar/bundle.zip",
            "unzip -q /tmp/cellar/src.zip -d /tmp/cellar/src",
            "unzip -q /tmp/cellar/bundle.zip -d /tmp/cellar/bundle",
            f"bash /tmp/cellar/src/deploy/bootstrap.sh /tmp/cellar/src /tmp/cellar/bundle "
            f"{backups.bucket_name} {self.region}",
        )

        instance = ec2.Instance(
            self, "Server",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType("t4g.small"),
            machine_image=ec2.MachineImage.from_ssm_parameter(UBUNTU_ARM64, cached_in_context=True),
            security_group=sg,
            role=role,
            user_data=user_data,
            user_data_causes_replacement=True,
            require_imdsv2=True,
            associate_public_ip_address=True,
            block_devices=[ec2.BlockDevice(
                device_name="/dev/sda1",
                volume=ec2.BlockDeviceVolume.ebs(16, volume_type=ec2.EbsDeviceVolumeType.GP3, encrypted=True),
            )],
        )

        # ---- CloudFront: HTTPS, and caching for Next.js static assets -----------------------------
        origin = origins.HttpOrigin(instance.instance_public_dns_name,
                                    protocol_policy=cf.OriginProtocolPolicy.HTTP_ONLY)
        dist = cf.Distribution(
            self, "Cdn",
            comment="Cellar Index",
            price_class=cf.PriceClass.PRICE_CLASS_100,
            http_version=cf.HttpVersion.HTTP2_AND_3,
            default_behavior=cf.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cf.AllowedMethods.ALLOW_ALL,
                cache_policy=cf.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER,
            ),
            additional_behaviors={
                "/_next/static/*": cf.BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=cf.CachePolicy.CACHING_OPTIMIZED,
                ),
            },
        )

        # ---- cost guardrail ------------------------------------------------------------------------
        def alert(threshold: float, kind: str) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    notification_type=kind, comparison_operator="GREATER_THAN",
                    threshold=threshold, threshold_type="ABSOLUTE_VALUE"),
                subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=alert_email)],
            )

        budgets.CfnBudget(
            self, "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="cellar-index-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=monthly_budget_usd, unit="USD"),
            ),
            notifications_with_subscribers=[
                alert(5, "ACTUAL"),
                alert(monthly_budget_usd, "ACTUAL"),
                alert(monthly_budget_usd, "FORECASTED"),
            ],
        )

        CfnOutput(self, "SiteUrl", value=f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "ApiDocsUrl", value=f"https://{dist.distribution_domain_name}/api/v1/docs")
        CfnOutput(self, "InstanceId", value=instance.instance_id)
        CfnOutput(self, "BackupBucket", value=backups.bucket_name)
