#!/usr/bin/python3
import json
import requests
import copy
import random
import string
import os
import boto3
import botocore
import time
import sys

class CloudFormationTemplateCreator:

    inputs_dir = 'templates/'
    outputs_dir = 'outputs/'

    def get_security_group_resource(self):
        security_group_ingress = json.load(open(self.inputs_dir + 'security_group_resource.json'))
        ip_addr = self.get_public_ip() + '/32'
        for rule in security_group_ingress['Properties']['SecurityGroupIngress']:
            if 'CidrIp' in rule:
                rule['CidrIp'] = ip_addr
        return security_group_ingress

    def get_ec2_resources(self, num_instances):
        ec2_resources = {}
        ec2_resource = json.load(open(self.inputs_dir + 'ec2_resource.json'))
        key_pair_name = self.get_keypair()
        for instance in range(1,num_instances+1):
            temp = copy.deepcopy(ec2_resource)
            temp['Properties']['KeyName'] = key_pair_name
            temp['Properties']['Tags'][0]['Value'] = str(instance)
            ec2_resources['EC2Instance' + str(instance)] = temp
        return ec2_resources

    def write_cf_json(self, json_data):
        fn = self.outputs_dir + 'cf_json_{0}.json'.format(''.join(random.choice(string.ascii_letters) for i in range(8)))
        fp = open(fn,'w')
        json.dump(json_data,fp, indent=2,sort_keys=True)
        return os.path.realpath(fp.name)

    def create_proxy_file(self, num_instances):
        cf_json = json.load(open(self.inputs_dir + 'cloud_formation_base_proxies.json'))
        cf_json['Mappings']['RegionMap'] = self.get_latest_ami_for_regions()
        cf_json['Resources'] = self.get_ec2_resources(num_instances)
        cf_json['Resources']['SecurityGroup'] = self.get_security_group_resource()
        cf_json['Resources']['SecurityGroupIngress'] = json.load(open(self.inputs_dir + 'security_group_ingress.json'))
        cf_json['Resources']['ProxyMaster'] = json.load(open(self.inputs_dir + 'ec2_proxy_pool.json'))
        cf_json['Resources']['ProxyMaster'] = json.load(open(self.inputs_dir + 'ec2_proxy_pool.json'))
        cf_json['Resources']['ProxyInstanceRole'] = json.load(open(self.inputs_dir + 'instance_role.json'))
        cf_json['Resources']['ProxyInstancePolicy'] = json.load(open(self.inputs_dir + 'instance_policy.json'))
        cf_json['Resources']['ProxyInstanceProfile'] = json.load(open(self.inputs_dir + 'instance_profile.json'))
        cf_json['Parameters'] = json.load(open(self.inputs_dir + 'cf_parameters.json'))
        return self.write_cf_json(cf_json)

    def get_public_ip(self):
        return requests.get("https://ipinfo.io/json").json()['ip']

    def get_latest_ami_for_regions(self):
        region_map = {}
        regions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
        for region in regions:
            client = boto3.client('ssm', region_name=region)
            region_map[region] = {'AMI':client.get_parameters(Names=['/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2'])['Parameters'][0]['Value']}
        return region_map

    def cf_stack_exists(self, stack_name='ScannerStack', region_name='us-east-1' ):
        client = boto3.client('cloudformation', region_name=region_name)
        stack_exists = True
        try:
            exists = client.describe_stacks(StackName=stack_name)
        except botocore.exceptions.ClientError as e:
            if 'does not exist' in str(e):
                stack_exists = False

        return stack_exists

    def get_cloud_formation_stack_success(self, stack_name='ScannerStack', region_name='us-east-1'):
        client = boto3.client('cloudformation', region_name=region_name)

        status = client.describe_stacks(StackName=stack_name)['Stacks'][0]['StackStatus']
        while status == 'CREATE_IN_PROGRESS':
            time.sleep(15)
            status = client.describe_stacks(StackName=stack_name)['Stacks'][0]['StackStatus']

        return status == 'CREATE_COMPLETE'

    def launch_cloud_formation_stack(self,cf_json_name,stack_name='ScannerStack', region_name='us-east-1'):
        if self.cf_stack_exists(stack_name=stack_name) == True:
            print ('CloudFormation stack exists.')
            return False

        client = boto3.client('cloudformation', region_name=region_name)
        client.create_stack(StackName=stack_name, TemplateBody=open(cf_json_name).read(),Capabilities=['CAPABILITY_IAM'])

        return self.get_cloud_formation_stack_success(stack_name=stack_name)

    def stop_cloud_formation_stack(self,stack_name='ScannerStack', region_name='us-east-1'):
        boto3.client('cloudformation',region_name=region_name).delete_stack(StackName=stack_name)

    def get_ec2_ips(self, region_name='us-east-1'):
        client = boto3.client('ec2', region_name=region_name)
        proxy_file = open(self.outputs_dir + 'secondary_proxies.txt','w')
        instance_data = client.describe_instances(MaxResults=50, Filters=[{'Name': 'instance-state-name', 'Values': ['running']},{'Name':'tag:secondary_proxy','Values':['*']}])
        for instance in instance_data['Reservations']:
            proxy_file.write(instance['Instances'][0]['NetworkInterfaces'][0]['Association']['PublicIp'] + '\n')

    def get_keypair_exists(self, region_name='us-east-1', key_pair_name='ScannerStackKeypair'):
        return len(boto3.client('ec2', region_name=region_name).describe_key_pairs(Filters=[{"Name":"key-name","Values":[key_pair_name]}])['KeyPairs']) == 1

    def get_keypair(self, region_name='us-east-1', key_pair_name='ScannerStackKeypair', delete_old_keypair=True):
        client = boto3.client('ec2', region_name=region_name)
        key_pair_exists = self.get_keypair_exists(region_name=region_name, key_pair_name=key_pair_name)

        if delete_old_keypair is False and key_pair_exists is True:
            return key_pair_name

        if delete_old_keypair is True and key_pair_exists is True:
            client.delete_key_pair(KeyName=key_pair_name)

        key_pair = client.create_key_pair(KeyName=key_pair_name)
        open(self.outputs_dir + 'ssh_private_key.pem','w').write(key_pair['KeyMaterial'])

        return key_pair_name

    def get_primary_proxy(self,region_name='us-east-1'):
        client = boto3.client('ec2', region_name=region_name)
        instance_data = client.describe_instances(MaxResults=50,
                                                 Filters=[{'Name': 'instance-state-name', 'Values': ['running']},
                                                          {'Name': 'tag:primary_proxy', 'Values': ['*']}])
        proxy_file = open(self.outputs_dir + 'primary_proxy.txt', 'w')
        for instance in instance_data['Reservations']:
            proxy_file.write(instance['Instances'][0]['NetworkInterfaces'][0]['Association']['PublicIp'])
            print (instance['Instances'][0]['NetworkInterfaces'][0]['Association']['PublicIp'])

    def start_cloud_formation(self,num_instances):
        stack_file = self.create_proxy_file(num_instances)
        print(self.launch_cloud_formation_stack(stack_file))
        self.get_ec2_ips()
        self.get_primary_proxy()


if __name__ == "__main__":

    if sys.argv[1] == 'start':
        print ('Starting')
        CloudFormationTemplateCreator().start_cloud_formation(3)
    if sys.argv[1] == 'stop':
        print ('Stoping')
        CloudFormationTemplateCreator().stop_cloud_formation_stack()

