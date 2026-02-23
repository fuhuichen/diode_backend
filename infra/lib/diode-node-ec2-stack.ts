import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";
import { generateUserData } from "./user-data-helper";

export interface DiodeNodeEc2StackProps extends cdk.StackProps {
  region: string;
  instanceCount: number;
  nodeTokens: string[];
  instanceType: string;
  diodeVersion: string;
  backendUrl: string;
  keyPairName?: string;
}

export class DiodeNodeEc2Stack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: DiodeNodeEc2StackProps) {
    super(scope, id, props);

    // Use the default VPC
    const vpc = ec2.Vpc.fromLookup(this, "DefaultVpc", { isDefault: true });

    // Security group with the same ports as Lightsail
    const sg = new ec2.SecurityGroup(this, "DiodeNodeSg", {
      vpc,
      description: "Diode node security group",
      allowAllOutbound: true,
    });

    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(22), "SSH");
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(3300), "Diode SOCKS TCP");
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.udp(3300), "Diode SOCKS UDP");
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(41046), "Diode TCP");
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.udp(41046), "Diode UDP");

    // Optional key pair
    const keyPair = props.keyPairName
      ? ec2.KeyPair.fromKeyPairName(this, "KeyPair", props.keyPairName)
      : undefined;

    for (let i = 0; i < props.instanceCount; i++) {
      const nodeName = `diode-node-${props.region}-${i}`;
      const nodeToken = props.nodeTokens[i];

      const rawScript = generateUserData({
        nodeToken,
        backendUrl: props.backendUrl,
        region: props.region,
        nodeName,
        diodeVersion: props.diodeVersion,
      });

      const instance = new ec2.Instance(this, `DiodeNode${i}`, {
        vpc,
        instanceType: new ec2.InstanceType(props.instanceType),
        machineImage: ec2.MachineImage.latestAmazonLinux2023(),
        securityGroup: sg,
        userData: ec2.UserData.custom(rawScript),
        keyPair,
        instanceName: nodeName,
      });

      cdk.Tags.of(instance).add("Project", "diode");
      cdk.Tags.of(instance).add("Region", props.region);
      cdk.Tags.of(instance).add("ManagedBy", "cdk");
      cdk.Tags.of(instance).add("NodeIndex", String(i));

      // Elastic IP for a stable public address
      const eip = new ec2.CfnEIP(this, `DiodeNodeEip${i}`, {
        domain: "vpc",
        tags: [
          { key: "Name", value: `${nodeName}-eip` },
          { key: "Project", value: "diode" },
        ],
      });

      new ec2.CfnEIPAssociation(this, `DiodeNodeEipAssoc${i}`, {
        allocationId: eip.attrAllocationId,
        instanceId: instance.instanceId,
      });

      new cdk.CfnOutput(this, `InstanceId${i}`, {
        value: instance.instanceId,
        description: `EC2 instance ID for node ${i}`,
      });

      new cdk.CfnOutput(this, `ElasticIp${i}`, {
        value: eip.ref,
        description: `Elastic IP for node ${i}`,
      });
    }
  }
}
