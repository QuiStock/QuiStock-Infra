#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?Defina AWS_REGION}"
: "${CLUSTER_NAME:?Defina CLUSTER_NAME}"
: "${K8S_VERSION:?Defina K8S_VERSION}"
: "${CLUSTER_ROLE_ARN:?Defina CLUSTER_ROLE_ARN}"
: "${NODE_ROLE_ARN:?Defina NODE_ROLE_ARN}"
: "${SUBNET_IDS_JSON:?Defina SUBNET_IDS_JSON como array JSON}"

command -v jq >/dev/null || { echo "jq é obrigatório" >&2; exit 1; }
command -v aws >/dev/null || { echo "AWS CLI é obrigatória" >&2; exit 1; }

if aws eks describe-cluster --region "$AWS_REGION" --name "$CLUSTER_NAME" >/dev/null 2>&1; then
  echo "O cluster $CLUSTER_NAME já existe em $AWS_REGION" >&2
  exit 1
fi

jq -e 'type == "array" and length >= 2 and all(.[]; type == "string" and startswith("subnet-"))' \
  <<<"$SUBNET_IDS_JSON" >/dev/null

cluster_spec="$(mktemp)"
trap 'rm -f "$cluster_spec"' EXIT

jq -n \
  --arg name "$CLUSTER_NAME" \
  --arg version "$K8S_VERSION" \
  --arg cluster_role "$CLUSTER_ROLE_ARN" \
  --arg node_role "$NODE_ROLE_ARN" \
  --argjson subnets "$SUBNET_IDS_JSON" \
  '{
    name: $name,
    version: $version,
    roleArn: $cluster_role,
    resourcesVpcConfig: {
      subnetIds: $subnets,
      endpointPublicAccess: true,
      endpointPrivateAccess: true
    },
    computeConfig: {
      enabled: true,
      nodeRoleArn: $node_role,
      nodePools: ["general-purpose", "system"]
    },
    kubernetesNetworkConfig: {
      elasticLoadBalancing: {enabled: true}
    },
    storageConfig: {
      blockStorage: {enabled: true}
    },
    accessConfig: {
      authenticationMode: "API",
      bootstrapClusterCreatorAdminPermissions: true
    }
  }' >"$cluster_spec"

aws eks create-cluster \
  --region "$AWS_REGION" \
  --cli-input-json "file://$cluster_spec"

aws eks wait cluster-active --region "$AWS_REGION" --name "$CLUSTER_NAME"
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"
kubectl get nodepools
