#!/usr/bin/env python3
import aws_cdk as cdk

from cellar_stack import CellarStack

app = cdk.App()
CellarStack(
    app, "CellarIndex",
    env=cdk.Environment(account="699191579533", region="us-east-1"),
    alert_email=app.node.try_get_context("alert_email") or "kirbyrobins@gmail.com",
    # AWS-managed prefix list of CloudFront's origin-facing IPs in us-east-1.
    cloudfront_prefix_list=app.node.try_get_context("cloudfront_prefix_list") or "pl-3b927c52",
    description="Cellar Index - wine price tracker (EC2 + CloudFront)",
)
app.synth()
