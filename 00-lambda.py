#!/usr/bin/python3
# vim: ai ts=8 sw=4 et sts=4
from troposphere import(
    GetAtt,
    ImportValue,
    Export,
    Output,
    Parameter,
    Ref,
    Select,
    Split,
    Sub,
    Template
)
from troposphere.ec2 import (
    SecurityGroup,
    SecurityGroupRule,
    SecurityGroupEgress,
)
from troposphere.awslambda import Code, Function, VPCConfig
from troposphere.iam import Policy, Role
from awacs.aws import (
    Action,
    PolicyDocument,
    Principal,
    Statement,
)
import sys


t = Template()
t.add_description("Lambda function/SG/IAM Role to install PostGIS on existing RDS")
BucketName = t.add_parameter(Parameter(
    "BucketName",
    Type="String",
))

BucketKey = t.add_parameter(Parameter(
    "BucketKey",
    Type="String",
))
Networkname = t.add_parameter(Parameter(
    "NetworkName",
    Default="default",
    Type="String",
))

def gen_iam_role():
    ExecutionRole = Role(
        "PostgisProvisionerExecutionRole",
        Path="/",
        ManagedPolicyArns=[
            "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        ],
        AssumeRolePolicyDocument=PolicyDocument(
            Version="2012-10-17",
            Statement=[
                Statement(
                    Action=[ Action("sts", "AssumeRole") ],
                    Effect="Allow",
                    Principal=Principal("Service", ["lambda.amazonaws.com"]),
                )
            ]
        )
    )
    return ExecutionRole

def gen_sg():
    sg = SecurityGroup(
        "PostGisProvisionerSg",
        GroupDescription="Allow PostGis Provisioner access to Postgres",
        VpcId=ImportValue(Sub("${NetworkName}-network-vpc-VpcId"))
    )
    sg_rule = SecurityGroupEgress(
        "EgressToPrivateSubnets",
        GroupId=Ref("PostGisProvisionerSg"),
        IpProtocol="tcp",
        FromPort="5432",
        ToPort="5432",
        CidrIp=ImportValue(Sub("${NetworkName}-network-vpc-PrivateCIDR")),
    )
    return [sg, sg_rule]


def gen_postgis_function():
    PostGisFunction = Function(
        "PostGisProvisionerFunction",
        Code=Code(
            S3Bucket=Ref("BucketName"),
            S3Key=Ref("BucketKey"),
        ),
        FunctionName=Sub("${AWS::StackName}-PostGisProvisioner"),
        Handler="postgis_provisioner.lambda_handler",
        Role=GetAtt("PostgisProvisionerExecutionRole", "Arn"),
        Timeout="60",
        Runtime="python3.6",
        VpcConfig=VPCConfig(
            SecurityGroupIds=[Ref("PostGisProvisionerSg")],
            SubnetIds=[
                Select(0,Split(",", ImportValue(Sub("${NetworkName}-network-vpc-PrivateSubnets")))),
                Select(1, Split(",", ImportValue(Sub("${NetworkName}-network-vpc-PrivateSubnets"))))
            ]
        )
    )
    return PostGisFunction

######################## MAIN BEGINS HERE ###############################
def main(argv):
    t.add_resource(gen_sg())
    t.add_resource(gen_iam_role())
    t.add_resource(gen_postgis_function())

    t.add_output(Output(
        "LambdaArn",
        Description="Arn of the Lambda function",
        Value=GetAtt("PostGisProvisionerFunction", "Arn"),
        Export=Export(Sub("${AWS::StackName}-LambdaArn")),
    ))

    t.add_output(Output(
        "SecurityGroup",
        Description="SecurityGroup that the Lambda function resides in",
        Value=GetAtt("PostGisProvisionerSg", "GroupId"),
        Export=Export(Sub("${AWS::StackName}-SecurityGroup")),
    ))

    print(t.to_json())

if __name__ == "__main__":
    main(sys.argv[1:])
