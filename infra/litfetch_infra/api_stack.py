"""The API stack: who can sign in (Cognito) and what the website calls (HTTP API + Lambda).

    litfetch-users       Cognito user pool. Email + password, email verified with a code, sign-up
                         only with an invite code (pre sign-up trigger), group "admins".
                         Lite plan (free up to 10,000 monthly active users). Kept if the stack is deleted.
    litfetch-web         App client for the website: no client secret (a browser can't keep one).
    litfetch-api         HTTP API. Every route except /health needs a valid ID token from the pool;
                         API Gateway checks it before the Lambda runs. 10 requests/s, bursts of 20.
    litfetch-api-fn      Lambda behind every route (api/http.py).
    litfetch-presignup   Lambda Cognito calls before a sign-up (api/presignup.py).
The API Lambda may send email through SES (test messages; litfetch_infra/ses.py).
"""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from litfetch_infra import ses
from litfetch_infra.data_stack import TABLE_NAME

SSM_PREFIX = "/litfetch/"
API_NAME = "litfetch-api"
API_FN_NAME = "litfetch-api-fn"
PRESIGNUP_NAME = "litfetch-presignup"
POOL_NAME = "litfetch-users"
CLIENT_NAME = "litfetch-web"
ADMIN_GROUP = "admins"
M = apigw.HttpMethod
# Must match api/http.py ROUTES (tests/test_infra.py checks it).
PUBLIC_ROUTES = {"/health": [M.GET]}
LOGIN_ROUTES = {
    "/me": [M.GET, M.DELETE],
    "/me/preferences": [M.PUT],
    "/me/webhook": [M.PUT, M.DELETE],
    "/me/preview": [M.POST],
    "/me/test-delivery": [M.POST],
    "/me/digests": [M.GET],
    "/admin/invites": [M.GET, M.POST],
}


class ApiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, code: lambda_.Code | None = None,
                 web_origins=("http://localhost:5173",), **kwargs) -> None:
        """code: the Lambda zip (default: bundling.py; tests pass a stub).
        web_origins: sites allowed to call the API from a browser (CORS): the local dev server now,
        the real site's URL from M7."""
        super().__init__(scope, construct_id, **kwargs)
        if code is None:
            from litfetch_infra.bundling import worker_code
            code = worker_code()
        table = dynamodb.Table.from_table_name(self, "Table", TABLE_NAME)

        def function(id_, name, handler, memory, timeout, environment, description):
            log_group = logs.LogGroup(self, f"{id_}Logs", log_group_name=f"/aws/lambda/{name}",
                                      retention=logs.RetentionDays.TWO_WEEKS,
                                      removal_policy=RemovalPolicy.DESTROY)
            return lambda_.Function(
                self, id_, function_name=name, description=description,
                runtime=lambda_.Runtime.PYTHON_3_12, architecture=lambda_.Architecture.ARM_64,
                handler=handler, code=code, memory_size=memory, timeout=timeout,
                log_group=log_group, environment=environment)

        # ---- Sign-up gate ----
        self.presignup = function("PreSignUp", PRESIGNUP_NAME, "api.presignup.handler", 256,
                                  Duration.seconds(10), {"LITFETCH_TABLE": TABLE_NAME},
                                  "Literature Fetch: allow sign-up only with an invite code")
        table.grant(self.presignup, "dynamodb:UpdateItem")       # mark the invite used, nothing else

        # ---- Users ----
        self.pool = cognito.UserPool(
            self, "Users",
            user_pool_name=POOL_NAME,
            self_sign_up_enabled=True,                       # still needs an invite (trigger above)
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)),
            password_policy=cognito.PasswordPolicy(min_length=10, require_lowercase=True,
                                                   require_uppercase=False, require_digits=True,
                                                   require_symbols=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            feature_plan=cognito.FeaturePlan.LITE,
            lambda_triggers=cognito.UserPoolTriggers(pre_sign_up=self.presignup),
            removal_policy=RemovalPolicy.RETAIN,             # accounts survive stack deletion
            deletion_protection=True,
        )
        cognito.CfnUserPoolGroup(self, "Admins", user_pool_id=self.pool.user_pool_id,
                                 group_name=ADMIN_GROUP, description="Can make invite codes")
        self.client = self.pool.add_client(
            "Web",
            user_pool_client_name=CLIENT_NAME,
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True,          # the website (Amplify)
                                        user_password=True),    # curl / CLI testing
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            prevent_user_existence_errors=True,                 # don't reveal which emails have accounts
        )

        # ---- API function ----
        self.api_fn = function("ApiFn", API_FN_NAME, "api.http.handler", 512, Duration.seconds(29), {
            "LITFETCH_TABLE": TABLE_NAME,
            "LITFETCH_SSM_PREFIX": SSM_PREFIX,
            "LITFETCH_USER_POOL_ID": self.pool.user_pool_id,
        }, "Literature Fetch: the website's API")
        table.grant_read_write_data(self.api_fn)
        param = f"arn:aws:ssm:{self.region}:{self.account}:parameter"
        path = SSM_PREFIX.rstrip("/")
        self.api_fn.add_to_role_policy(iam.PolicyStatement(      # API keys for preview / test messages
            actions=["ssm:GetParametersByPath"], resources=[f"{param}{path}", f"{param}{path}/*"]))
        self.api_fn.add_to_role_policy(iam.PolicyStatement(      # users' own webhooks only
            actions=["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"],
            resources=[f"{param}{path}/SLACK_WEBHOOK_*"]))
        self.api_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["kms:Decrypt", "kms:Encrypt"], resources=["*"],
            conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}}))
        self.api_fn.add_to_role_policy(iam.PolicyStatement(      # DELETE /me removes the login too
            actions=["cognito-idp:AdminDeleteUser"], resources=[self.pool.user_pool_arn]))
        ses.allow_sending(self.api_fn)                # "Send test" by email, via SES

        # ---- HTTP API ----
        self.api = apigw.HttpApi(
            self, "Api",
            api_name=API_NAME,
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=list(web_origins),
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.PUT,
                               apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.DELETE],
                allow_headers=["authorization", "content-type"],
                max_age=Duration.hours(1)),
        )
        integration = integrations.HttpLambdaIntegration("ApiFnIntegration", self.api_fn)
        authorizer = authorizers.HttpUserPoolAuthorizer("Cognito", self.pool, user_pool_clients=[self.client])
        for route, methods in PUBLIC_ROUTES.items():
            self.api.add_routes(path=route, methods=methods, integration=integration)
        for route, methods in LOGIN_ROUTES.items():
            self.api.add_routes(path=route, methods=methods, integration=integration, authorizer=authorizer)
        stage = self.api.default_stage.node.default_child         # throttle every route
        stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_rate_limit=10, throttling_burst_limit=20)

        CfnOutput(self, "ApiUrl", value=self.api.api_endpoint)
        CfnOutput(self, "UserPoolId", value=self.pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.client.user_pool_client_id)
