#!/usr/bin/python3
# vim: ai ts=8 sw=4 et sts=4
from troposphere import (
    Base64,
    Condition,
    Equals,
    GetAtt,
    ImportValue,
    Join,
    Not,
    Output,
    Parameter,
    Ref,
    Select,
    Split,
    Sub,
    Tags,
    Template,
)
from troposphere.policies import (
    CreationPolicy,
    ResourceSignal,
    AutoScalingReplacingUpdate,
    AutoScalingRollingUpdate,
    UpdatePolicy
)
from troposphere.cloudformation import AWSCustomObject
from troposphere.rds import DBInstance, DBSubnetGroup
from troposphere.awslambda import Code, Function
from troposphere.ec2 import SecurityGroup, SecurityGroupRule, SecurityGroupIngress
from awacs.aws import Allow, Statement, Policy, Action, Principal
from pathlib import Path
import types
import sys, getopt
import os
import re

## BEGIN Input Parameter Definition ##
## These are parameters that will be configurable through CloudFormation at stack creation
parameters = {
    "ProvisionerStackName" : Parameter(
        "ProvisionerStackName",
        Description="Name of the stack that has the PostGis function. Leave empty for a normal Postgres instance",
        Type="String",
        Default="postgis-provisioner-lambda",
    ),
    "NetworkName" : Parameter(
        "NetworkName",
        Description="Common identifier for the network",
        Type="String",
        Default="default"
    ),
    "Username" : Parameter(
        "Username",
        Description="Database user name",
        Type="String",
        Default=""
    ),
    "Password" : Parameter(
        "Password",
        Description="Database password",
        NoEcho=True,
        Type="String",
        Default=""
    ),
    "DBName" : Parameter(
        "DBName",
        Description="Database name",
        Type="String",
        Default="rds_db",
        MinLength="1",
        MaxLength="64",
        ConstraintDescription=("must begin with a letter and contain only"
                               " alphanumeric characters.")
    ),
    "DBStorage" : Parameter(
        "DBStorage",
        Default="50",
        Description="The size of the database (Gb)",
        Type="Number",
        MinValue="5",
        MaxValue="6144",
        ConstraintDescription="must be between 5 and 6144Gb.",
    ),
    "DBStorageType" : Parameter(
        "DBStorageType",
        Default="gp2",
        Description="The storage type to use)",
        Type="String",
        AllowedValues=['standard', 'gp2', 'io1']
    ),
    "Iops" : Parameter(
        "Iops",
        Default="0",
        Description="Provisioned IOPS, if using io1 storage type",
        Type="Number",
    ),
    "DBClass" : Parameter(
        "DBClass",
        Default="db.m4.large",
        Description="Database instance class",
        Type="String",
        AllowedValues=[
            "db.m1.small",
            "db.m1.medium",
            "db.m1.large",
            "db.m1.xlarge",
            "db.m2.xlarge ",
            "db.m2.2xlarge",
            "db.m2.4xlarge",
            "db.m3.medium",
            "db.m3.large",
            "db.m3.xlarge",
            "db.m3.2xlarge",
            "db.m4.large",
            "db.m4.xlarge",
            "db.m4.2xlarge",
            "db.m4.4xlarge",
            "db.m4.10xlarge",
            "db.r3.large",
            "db.r3.xlarge",
            "db.r3.2xlarge",
            "db.r3.4xlarge",
            "db.r3.8xlarge",
            "db.t2.micro",
            "db.t2.small",
            "db.t2.medium",
            "db.t2.large"],
        ConstraintDescription="must select a valid database instance type.",
    ),
    "DBEngine" : Parameter(
        "DBEngine",
        Description="Database engine",
        Type="String",
        Default="postgres",
        AllowedValues=[
            "postgres",
        ],
    ),
    "DBEngineVersion" : Parameter(
        "DBEngineVersion",
        Description="Database engine version",
        Type="String",
        Default="9.6.2"
    ),
    "MultiAZ" : Parameter(
        "MultiAZ",
        Default="False",
        Description="Make database multi-az",
        Type="String",
        AllowedValues=['True', 'False']
    ),
    "PubliclyAccessible" : Parameter(
        "PubliclyAccessible",
        Default="False",
        Description="Make database publicly accessible",
        Type="String",
        AllowedValues=['True', 'False']
    ),
}

## BEGIN Python specific variable declaration ##

######### node_params usage ########
service_name = "RDS"

## END  Input Parameter Definition ##

## Class used for our lambda custom resource
class PostGisProvisioner(AWSCustomObject):
    resource_type = "Custom::PostGisProvisioner"
    props = {
        "DBName": (str, True),
        "Host": (str, True),
        "Password": (str, True),
        "ServiceToken": (str, True),
        "Username": (str, True),
    }

def gen_postgis_provisioner():
    postgis_provisioner = PostGisProvisioner(
        "PostGisProvisioner",
        Condition="InstallPostgis",
        DBName=Ref("DBName"),
        DependsOn="DB",
        Host=GetAtt("DB", "Endpoint.Address"),
        Password=Ref("Password"),
        ServiceToken=ImportValue(Sub("${ProvisionerStackName}-LambdaArn")),
        Username=Ref("Username"),
    )
    return [postgis_provisioner]

# Generates the tag parameter for everything except ASGs
def gen_tags(name):
    tags = Tags(
        Name=name,
        Environment="dev",
        POCName="Grant Soyka",
        POCEmail="grant.soyka@radiantsolutions.com",
        Project="rds",
    )
    return tags

# Generate the security group
def gen_sg():
    sg = SecurityGroup(
        "DBSecurityGroup",
        GroupDescription="Enable Postgres on the inbound port",
        VpcId=ImportValue(Sub("${NetworkName}-network-vpc-VpcId"))
    )
    self_sg_rule = SecurityGroupIngress(
        "IngressFromSelfRule",
        GroupId=Ref("DBSecurityGroup"),
        IpProtocol="tcp",
        FromPort="5432",
        ToPort="5432",
        SourceSecurityGroupId=Ref("DBSecurityGroup"),
    )

    lambda_sg_rule = SecurityGroupIngress(
        "IngressFromLambdaRule",
        Condition="InstallPostgis",
        GroupId=Ref("DBSecurityGroup"),
        IpProtocol="tcp",
        FromPort="5432",
        ToPort="5432",
        SourceSecurityGroupId=ImportValue(Sub("${ProvisionerStackName}-SecurityGroup")),
    )

    return [sg, self_sg_rule, lambda_sg_rule]

def gen_rds_db( service_name ):
    db_subnet_group = DBSubnetGroup(
        "DBSubnetGroup",
        DBSubnetGroupDescription="Subnets available for the RDS DB Instance",
        SubnetIds = [
            Select(0,Split(",", ImportValue(Sub("${NetworkName}-network-vpc-PrivateSubnets")))),
            Select(1, Split(",", ImportValue(Sub("${NetworkName}-network-vpc-PrivateSubnets"))))
        ],
    )
    db = DBInstance(
        "DB",
        DBName=Ref(parameters['DBName']),
        AllocatedStorage=Ref(parameters['DBStorage']),
        DBInstanceClass=Ref(parameters['DBClass']),
        DBInstanceIdentifier=service_name,
        VPCSecurityGroups=[Ref('DBSecurityGroup')],
        Engine=Ref(parameters['DBEngine']),
        EngineVersion=Ref(parameters['DBEngineVersion']),
        StorageType=Ref(parameters['DBStorageType']),
        Iops=Ref(parameters['Iops']),
        MasterUsername=Ref(parameters['Username']),
        MasterUserPassword=Ref(parameters['Password']),
        MultiAZ=Ref(parameters['MultiAZ']),
        PubliclyAccessible=Ref(parameters['PubliclyAccessible']),
        DBSubnetGroupName=Ref("DBSubnetGroup"),
        Tags=gen_tags( service_name )
    )
    return [db, db_subnet_group]

# Function to write template to specified file
def write_to_file( template ):

    # Define the directory to write to as located one level up from the current directory, in a folder named templates
    dir = os.path.abspath(os.path.join(os.path.dirname( __file__ )))

    # Create the directory if it does not exist
    if not os.path.exists(dir):
        os.makedirs(dir)

        # Define filename for template equal to name of current script
        filename = re.sub('\.py$','', sys.argv[0]).split("/")[-1]
        file = os.path.join(dir,filename)

        # Write the template to file
        target = open(file + '.json', 'w')
        target.truncate()
        target.write(template)
        target.close()

######################## MAIN BEGINS HERE ###############################
def main(argv):

    # Set up a blank template
    t = Template()

    # Add description
    t.add_description("RDS Database")

    # Add all defined input parameters to template
    for p in parameters.values():
        t.add_parameter(p)

    t.add_condition("InstallPostgis", Not(Equals(Ref("ProvisionStackName"), "")))
    t.add_resource(gen_postgis_provisioner())

    # Create instance and security group add to template
    t.add_resource(gen_sg())
    for resource in gen_rds_db(service_name):
        t.add_resource(resource)

    t.add_output(Output(
        "ConnectionString",
        Description="Connection string for database",
        Value=Join("", [
            GetAtt("DB", "Endpoint.Address"),
            Ref("DB")
        ])
    ))

    # Convert template to json
    template=(t.to_json())

    # Print template to console (for debugging) and write to file
    print(template)
    write_to_file(template)

if __name__ == "__main__":
    main(sys.argv[1:])
