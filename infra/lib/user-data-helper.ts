import * as fs from "fs";
import * as path from "path";

export interface UserDataParams {
  nodeToken: string;
  backendUrl: string;
  region: string;
  nodeName: string;
  diodeVersion: string;
}

/**
 * Load the user-data.sh template and substitute placeholders.
 * Shared by both the Lightsail and EC2 stacks.
 */
export function generateUserData(params: UserDataParams): string {
  const userDataTemplate = fs.readFileSync(
    path.join(__dirname, "user-data.sh"),
    "utf-8"
  );

  const agentPyPath = path.join(__dirname, "..", "..", "agent", "agent.py");
  const agentPyContent = fs.readFileSync(agentPyPath, "utf-8");

  return userDataTemplate
    .replace(/\{\{NODE_TOKEN\}\}/g, params.nodeToken)
    .replace(/\{\{BACKEND_URL\}\}/g, params.backendUrl)
    .replace(/\{\{REGION\}\}/g, params.region)
    .replace(/\{\{NODE_NAME\}\}/g, params.nodeName)
    .replace(/\{\{DIODE_VERSION\}\}/g, params.diodeVersion)
    .replace(/\{\{AGENT_PY_CONTENT\}\}/g, agentPyContent);
}
