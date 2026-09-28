"""Cellar Index on AWS: one EC2 instance (Next.js + FastAPI model service + PostgreSQL behind nginx),
CloudFront in front for HTTPS and caching, an S3 bucket for nightly database backups, and a monthly
budget with email alerts. Quarterly retraining runs as a SageMaker Processing job (started from the
server by an EventBridge Scheduler -> SSM Run Command schedule) and publishes to an S3 model registry;
the API explains wines with Amazon Nova on Amazon Bedrock.

The instance is built from scratch on first boot from two CDK assets: the source tree and a data
bundle (database dump + active model), see deploy/bootstrap.sh. Any change to either replaces the
instance, so every deploy is a clean, reproducible build.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, IgnoreMode, RemovalPolicy, Stack, Tags
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as assets
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
# Amazon Nova Lite (first-party, no Marketplace subscription needed) via its US cross-region profile.
BEDROCK_PROFILE = "us.amazon.nova-lite-v1:0"
BEDROCK_MODEL = "amazon.nova-lite-v1:0"
# PLCB publishes each quarter's list on the 1st of Jan/Apr/Jul/Oct; refresh a week later.
REFRESH_SCHEDULE = "cron(0 6 8 1,4,7,10 ? *)"
UBUNTU_ARM64 = "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id"
SOURCE_EXCLUDES = [
    ".git", "**/node_modules", "**/.next", "**/.venv", "**/__pycache__", "**/*.egg-info", "**/.DS_Store",
    "data", "ml/data", "ml/artifacts", "ml/registry", "deploy/bundle", "infra",
    "**/.env*",
]


class CellarStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, alert_email: str, cloudfront_prefix_list: str,
                 monthly_budget_usd: int = 20, site_domain: str | None = None, site_cert_arn: str | None = None,
                 **kwargs) -> None:
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

        # ---- quarterly retraining on SageMaker ------------------------------------------------------
        artifacts = s3.Bucket(
            self, "Artifacts",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # Training inputs/outputs per run expire; the model registry (registry/) is kept.
            lifecycle_rules=[s3.LifecycleRule(prefix="runs/", expiration=Duration.days(180))],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        train_image = ecr_assets.DockerImageAsset(
            self, "TrainImage",
            directory=str(REPO / "ml"),
            platform=ecr_assets.Platform.LINUX_AMD64,
            exclude=["data", "artifacts", "registry", "**/__pycache__", "*.egg-info"],
        )
        sm_role = iam.Role(
            self, "SageMakerRole",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            description="Cellar Index training - read inputs, write outputs, pull the training image, write logs",
        )
        artifacts.grant_read_write(sm_role)
        train_image.repository.grant_pull(sm_role)
        sm_role.add_to_policy(iam.PolicyStatement(
            actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
            resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/sagemaker/ProcessingJobs*"],
        ))
        sm_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"], resources=["*"],
            conditions={"StringLike": {"cloudwatch:namespace": "/aws/sagemaker/*"}},
        ))

        # ---- instance ---------------------------------------------------------------------------
        role = iam.Role(
            self, "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
            description="Cellar Index server - SSM access, read deploy assets, write DB backups",
        )
        source.grant_read(role)
        bundle.grant_read(role)
        backups.grant_read_write(role, "backups/*")
        artifacts.grant_read_write(role)
        role.add_to_policy(iam.PolicyStatement(
            sid="RunTrainingJobs",
            actions=["sagemaker:CreateProcessingJob", "sagemaker:DescribeProcessingJob",
                     "sagemaker:StopProcessingJob", "sagemaker:AddTags"],
            resources=[f"arn:aws:sagemaker:{self.region}:{self.account}:processing-job/cellar-train-*"],
        ))
        role.add_to_policy(iam.PolicyStatement(
            sid="PassOnlyTheTrainingRole",
            actions=["iam:PassRole"], resources=[sm_role.role_arn],
            conditions={"StringEquals": {"iam:PassedToService": "sagemaker.amazonaws.com"}},
        ))
        role.add_to_policy(iam.PolicyStatement(
            sid="ExplainWithAmazonNova",
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{BEDROCK_PROFILE}",
                # The US cross-region profile routes to these regions.
                *[f"arn:aws:bedrock:{r}::foundation-model/{BEDROCK_MODEL}" for r in ("us-east-1", "us-east-2", "us-west-2")],
            ],
        ))

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
            f"{backups.bucket_name} {self.region} {artifacts.bucket_name} {sm_role.role_arn} {train_image.image_uri}",
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

        # ---- quarterly refresh: EventBridge Scheduler -> SSM Run Command on the server ---------------
        schedule_role = iam.Role(self, "RefreshScheduleRole",
                                 assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
                                 description="Cellar Index - start the quarterly refresh on the server")
        schedule_role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:SendCommand"],
            resources=[f"arn:aws:ec2:{self.region}:{self.account}:instance/{instance.instance_id}",
                       f"arn:aws:ssm:{self.region}::document/AWS-RunShellScript"],
        ))
        scheduler.CfnSchedule(
            self, "QuarterlyRefresh",
            description="Ingest the new PLCB price list, retrain on SageMaker, activate the new model",
            schedule_expression=REFRESH_SCHEDULE,
            schedule_expression_timezone="UTC",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn="arn:aws:scheduler:::aws-sdk:ssm:sendCommand",
                role_arn=schedule_role.role_arn,
                input=Stack.of(self).to_json_string({
                    "DocumentName": "AWS-RunShellScript",
                    "InstanceIds": [instance.instance_id],
                    "Parameters": {
                        "commands": ["/opt/cellar/src/deploy/refresh-aws.sh >> /var/log/cellar-refresh.log 2>&1"],
                        "executionTimeout": ["14400"],
                    },
                }),
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(maximum_retry_attempts=0),
            ),
        )

        # ---- CloudFront: HTTPS, and caching for Next.js static assets -----------------------------
        origin = origins.HttpOrigin(instance.instance_public_dns_name,
                                    protocol_policy=cf.OriginProtocolPolicy.HTTP_ONLY)
        custom_domain = {}
        if site_domain and site_cert_arn:
            custom_domain = {
                "domain_names": [site_domain],
                "certificate": acm.Certificate.from_certificate_arn(self, "SiteCert", site_cert_arn),
            }
        dist = cf.Distribution(
            self, "Cdn",
            comment="Cellar Index",
            **custom_domain,
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

        CfnOutput(self, "SiteUrl", value=f"https://{site_domain}" if custom_domain
                  else f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "CloudFrontDomain", value=dist.distribution_domain_name)
        CfnOutput(self, "ApiDocsUrl", value=f"https://{dist.distribution_domain_name}/api/v1/docs")
        CfnOutput(self, "InstanceId", value=instance.instance_id)
        CfnOutput(self, "BackupBucket", value=backups.bucket_name)
        CfnOutput(self, "ArtifactBucket", value=artifacts.bucket_name)
        CfnOutput(self, "TrainImageUri", value=train_image.image_uri)
