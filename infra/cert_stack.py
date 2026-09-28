"""TLS certificate for the custom domain (CloudFront requires it in us-east-1).

DNS is hosted at Netlify, so validation is manual: the validation CNAME is shown in the deploy's
events and must be added in Netlify DNS; the stack finishes once ACM sees it.
"""

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_certificatemanager as acm
from constructs import Construct


class CellarCertStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, domain_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        Tags.of(self).add("project", "cellar-index")
        cert = acm.Certificate(self, "SiteCert", domain_name=domain_name,
                               validation=acm.CertificateValidation.from_dns())
        CfnOutput(self, "CertificateArn", value=cert.certificate_arn)
