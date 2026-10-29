"""The website stack: the built React app (web/dist) in a private S3 bucket, served by CloudFront.

    litfetch-site bucket   Private: Block Public Access on, HTTPS only. Only this CloudFront
                           distribution may read it (Origin Access Control + bucket policy).
    Distribution           https://<id>.cloudfront.net. HTTPS only, gzip/brotli, security headers,
                           edge locations in North America and Europe (price class 100, cheapest).
                           Paths that aren't files (/settings, /digests, ...) get index.html, so
                           React Router can show the page (SPA routing).
    Deployments            Copy web/dist into the bucket on `cdk deploy`. Hashed files under
                           assets/ are cached for a year (a new build makes new names); index.html is
                           never cached and is invalidated in CloudFront on every deploy.

Build the site first: `cd web && npm run build`. Without web/dist the stack deploys an empty site
(cdk synth prints a warning).
"""
import os

from aws_cdk import Annotations, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIST = os.path.join(ROOT, "web", "dist")
LONG_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


class WebStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, dist_dir: str = WEB_DIST, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = s3.Bucket(
            self, "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # Only built files live here, so deleting the stack may delete them too.
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # A missing page has to come back as index.html with 200, so React Router can draw it.
        # With OAC and no ListBucket permission, S3 answers 403 (not 404) for a missing key.
        spa = [cloudfront.ErrorResponse(http_status=status, response_http_status=200,
                                        response_page_path="/index.html", ttl=Duration.seconds(0))
               for status in (403, 404)]

        self.distribution = cloudfront.Distribution(
            self, "Cdn",
            comment="Literature Fetch website",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                compress=True,
            ),
            error_responses=spa,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
        )
        self.url = f"https://{self.distribution.distribution_domain_name}"

        if os.path.isfile(os.path.join(dist_dir, "index.html")):
            # Old hashed files are kept (prune=False), so a tab opened before a deploy still works.
            assets = s3deploy.BucketDeployment(
                self, "DeployAssets",
                sources=[s3deploy.Source.asset(dist_dir, exclude=["index.html"])],
                destination_bucket=self.bucket,
                cache_control=[s3deploy.CacheControl.from_string(LONG_CACHE)],
                prune=False,
            )
            index = s3deploy.BucketDeployment(
                self, "DeployIndex",
                sources=[s3deploy.Source.asset(dist_dir, exclude=["*", "!index.html"])],
                destination_bucket=self.bucket,
                cache_control=[s3deploy.CacheControl.from_string(NO_CACHE)],
                prune=False,
                distribution=self.distribution,          # then clear CloudFront's copy of index.html
                distribution_paths=["/index.html"],
            )
            index.node.add_dependency(assets)            # new index.html only after its files exist
        else:
            Annotations.of(self).add_warning(
                f"{dist_dir} has no index.html: run `npm run build` in web/ first, or the site is empty")

        CfnOutput(self, "WebUrl", value=self.url)
        CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
