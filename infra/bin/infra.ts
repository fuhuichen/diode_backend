#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { DiodeNodeStack } from "../lib/diode-node-stack";
import { DiodeNodeEc2Stack } from "../lib/diode-node-ec2-stack";

const app = new cdk.App();

// Read context parameters
const region = app.node.tryGetContext("region") || "ap-southeast-1";
const instanceCount = parseInt(app.node.tryGetContext("instanceCount") || "1", 10);
const nodeTokens: string = app.node.tryGetContext("nodeTokens") || "";
const bundleId = app.node.tryGetContext("bundleId") || "nano_3_0";
const blueprintId = app.node.tryGetContext("blueprintId") || "amazon_linux_2023";
const diodeVersion = app.node.tryGetContext("diodeVersion") || "v1.17.2";
const backendUrl = app.node.tryGetContext("backendUrl") || "https://api.diode.dev";
const keyPairName = app.node.tryGetContext("keyPairName") || "";
const provider = app.node.tryGetContext("provider") || "lightsail";
const instanceType = app.node.tryGetContext("instanceType") || "t3a.nano";

// Parse node tokens — use placeholders during bootstrap/synth-only if not provided
const tokens = nodeTokens
  ? nodeTokens.split(",")
  : Array.from({ length: instanceCount }, () => "placeholder");

if (provider === "ec2") {
  new DiodeNodeEc2Stack(app, `DiodeNodesEc2-${region}`, {
    env: { account: process.env.CDK_DEFAULT_ACCOUNT, region },
    region,
    instanceCount,
    nodeTokens: tokens,
    instanceType,
    diodeVersion,
    backendUrl,
    keyPairName: keyPairName || undefined,
  });
} else {
  new DiodeNodeStack(app, `DiodeNodes-${region}`, {
    env: { region },
    region,
    instanceCount,
    nodeTokens: tokens,
    bundleId,
    blueprintId,
    diodeVersion,
    backendUrl,
    keyPairName: keyPairName || undefined,
  });
}

app.synth();
