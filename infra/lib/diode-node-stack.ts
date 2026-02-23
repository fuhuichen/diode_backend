import * as cdk from "aws-cdk-lib";
import * as lightsail from "aws-cdk-lib/aws-lightsail";
import { Construct } from "constructs";
import * as fs from "fs";
import * as path from "path";

export interface DiodeNodeStackProps extends cdk.StackProps {
  region: string;
  instanceCount: number;
  nodeTokens: string[];
  bundleId: string;
  blueprintId: string;
  diodeVersion: string;
  backendUrl: string;
  keyPairName?: string;
}

export class DiodeNodeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: DiodeNodeStackProps) {
    super(scope, id, props);

    // Read user-data template
    const userDataTemplate = fs.readFileSync(
      path.join(__dirname, "user-data.sh"),
      "utf-8"
    );

    // Read agent.py content to embed in user-data
    const agentPyPath = path.join(__dirname, "..", "..", "agent", "agent.py");
    const agentPyContent = fs.readFileSync(agentPyPath, "utf-8");

    for (let i = 0; i < props.instanceCount; i++) {
      const nodeName = `diode-node-${props.region}-${i}`;
      const nodeToken = props.nodeTokens[i];

      // Replace placeholders in user-data
      const userData = userDataTemplate
        .replace(/\{\{NODE_TOKEN\}\}/g, nodeToken)
        .replace(/\{\{BACKEND_URL\}\}/g, props.backendUrl)
        .replace(/\{\{REGION\}\}/g, props.region)
        .replace(/\{\{NODE_NAME\}\}/g, nodeName)
        .replace(/\{\{DIODE_VERSION\}\}/g, props.diodeVersion)
        .replace(/\{\{AGENT_PY_CONTENT\}\}/g, agentPyContent);

      const instance = new lightsail.CfnInstance(this, `DiodeNode${i}`, {
        instanceName: nodeName,
        blueprintId: props.blueprintId,
        bundleId: props.bundleId,
        availabilityZone: `${props.region}a`,
        userData: userData,
        keyPairName: props.keyPairName || undefined,
        tags: [
          { key: "Project", value: "diode" },
          { key: "Region", value: props.region },
          { key: "ManagedBy", value: "cdk" },
          { key: "NodeIndex", value: String(i) },
        ],
        networking: {
          ports: [
            {
              protocol: "tcp",
              fromPort: 22,
              toPort: 22,
              accessFrom: "0.0.0.0/0",
              accessType: "public",
            },
            {
              protocol: "tcp",
              fromPort: 41046,
              toPort: 41046,
              accessFrom: "0.0.0.0/0",
              accessType: "public",
            },
            {
              protocol: "udp",
              fromPort: 41046,
              toPort: 41046,
              accessFrom: "0.0.0.0/0",
              accessType: "public",
            },
          ],
        },
      });

      new cdk.CfnOutput(this, `InstanceName${i}`, {
        value: instance.instanceName,
        description: `Lightsail instance name for node ${i}`,
      });
    }
  }
}
