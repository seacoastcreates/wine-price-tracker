#!/usr/bin/env python3
import aws_cdk as cdk

from cellar_stack import CellarStack
from cert_stack import CellarCertStack

app = cdk.App()
env = cdk.Environment(account="699191579533", region="us-east-1")
SITE_DOMAIN = "www.thepriceofwine.com"
CellarCertStack(app, "CellarCert", env=env, domain_name=SITE_DOMAIN,
                description="Cellar Index - TLS certificate for the custom domain")
CellarStack(
    app, "CellarIndex",
    env=env,
    alert_email=app.node.try_get_context("alert_email") or "kirbyrobins@gmail.com",
    # AWS-managed prefix list of CloudFront's origin-facing IPs in us-east-1.
    cloudfront_prefix_list=app.node.try_get_context("cloudfront_prefix_list") or "pl-3b927c52",
    # Custom domain: attached once the CellarCert certificate has been validated (pass its ARN).
    site_domain=SITE_DOMAIN,
    site_cert_arn=app.node.try_get_context("site_cert_arn"),
    description="Cellar Index - wine price tracker (EC2 + CloudFront)",
)
app.synth()
