#!/usr/bin/env bash

set -euo pipefail

CONSOLE_URL="http://127.0.0.1:8001"
KUBE_API="https://localhost:18443"
KUBE_NAMESPACE="higress-system"
MCP_SERVER_NAME="mcp-agentloom-policy-broker"
GATEWAY_ASSERTION="__AGENTLOOM_GATEWAY_ASSERTION__"
MCP_URL="http://host.docker.internal:8765/mcp"
GATEWAY_URL="http://aigw-local.hiclaw.io:8080/mcp-servers/${MCP_SERVER_NAME}"
SERVICE_SOURCE_NAME="agentloom-policy-broker-proxy"
CONSUMER_MAX_ATTEMPTS=10
COOKIE_FILE="$(mktemp)"
RESPONSE_FILE="$(mktemp)"

cleanup() {
    rm -f "${COOKIE_FILE}" "${RESPONSE_FILE}"
}
trap cleanup EXIT

for command in curl jq; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Required command is unavailable: ${command}" >&2
        exit 1
    }
done

test -n "${HICLAW_ADMIN_PASSWORD:-}" || {
    echo "Higress Console credentials are unavailable" >&2
    exit 1
}

login_body="$(jq -cn \
    --arg username "${HICLAW_ADMIN_USER:-admin}" \
    --arg password "${HICLAW_ADMIN_PASSWORD}" \
    '{username: $username, password: $password}')"
curl --fail --silent --show-error \
    --request POST \
    --header "Content-Type: application/json" \
    --cookie-jar "${COOKIE_FILE}" \
    --data "${login_body}" \
    "${CONSOLE_URL}/session/login" >/dev/null

api_write() {
    local method="$1"
    local path="$2"
    local body="$3"
    local allow_conflict="${4:-false}"
    local quiet_rejection="${5:-false}"
    local status

    status="$(curl --silent --show-error \
        --output "${RESPONSE_FILE}" \
        --write-out "%{http_code}" \
        --request "${method}" \
        --header "Content-Type: application/json" \
        --cookie "${COOKIE_FILE}" \
        --data "${body}" \
        "${CONSOLE_URL}${path}")"

    if [ "${status}" = "409" ] && [ "${allow_conflict}" = "true" ]; then
        return
    fi
    case "${status}" in
        200|201|204) ;;
        *)
            echo "Higress API ${method} ${path} failed with HTTP ${status}" >&2
            return 1
            ;;
    esac
    if jq -e '.success == false' "${RESPONSE_FILE}" >/dev/null 2>&1; then
        error_message="$(jq -r '
            (.message // .msg // .error // "unspecified error")
            | if type == "string" then . else "unspecified error" end
        ' "${RESPONSE_FILE}")"
        if [ "${quiet_rejection}" != "true" ]; then
            echo "Higress API ${method} ${path} rejected the request: ${error_message}" >&2
        fi
        return 1
    fi
}

api_get() {
    local path="$1"
    curl --fail --silent --show-error \
        --cookie "${COOKIE_FILE}" \
        "${CONSOLE_URL}${path}"
}

service_body="$(jq -cn '{
    type: "dns",
    name: "agentloom-policy-broker-proxy",
    domain: "host.docker.internal",
    port: 8765,
    protocol: "http"
}')"
api_write POST "/v1/service-sources" "${service_body}" true

allowed_consumers="$(jq -cn '[
    "worker-agentloom-investigator",
    "worker-agentloom-implementer",
    "worker-agentloom-verifier"
]')"
for consumer in \
    worker-agentloom-investigator \
    worker-agentloom-implementer \
    worker-agentloom-verifier; do
    if ! consumer_record="$(api_get "/v1/consumers/${consumer}")"; then
        echo "Expected Higress consumer is unavailable: ${consumer}" >&2
        exit 1
    fi
    persisted_name="$(jq -r '.data.name // .name // empty' <<<"${consumer_record}")"
    test "${persisted_name}" = "${consumer}" || {
        echo "Expected Higress consumer is unavailable: ${consumer}" >&2
        exit 1
    }
done

services="$(jq -cn '[{
    name: "agentloom-policy-broker-proxy.dns",
    port: 8765,
    weight: 100
}]')"
mcp_body="$(jq -cn \
    --arg name "${MCP_SERVER_NAME}" \
    --argjson services "${services}" \
    '{
        name: $name,
        description: "AgentLoom Policy Broker MCP Direct Route (Streamable HTTP)",
        type: "DIRECT_ROUTE",
        domains: ["aigw-local.hiclaw.io"],
        services: $services,
        directRouteConfig: {
            path: "/mcp",
            transportType: "streamable"
        },
        consumerAuthInfo: {
            type: "key-auth",
            enable: true,
            allowedConsumers: []
        }
    }')"
api_write PUT "/v1/mcpServer" "${mcp_body}"

current_consumer_result="$(api_get \
    "/v1/mcpServer/consumers?mcpServerName=${MCP_SERVER_NAME}")"
current_consumers="$(jq -c '[.data[]?.consumerName]' <<<"${current_consumer_result}")"
if [ "$(jq 'length' <<<"${current_consumers}")" -gt 0 ]; then
    current_consumer_body="$(jq -cn \
        --arg name "${MCP_SERVER_NAME}" \
        --argjson consumers "${current_consumers}" \
        '{mcpServerName: $name, consumers: $consumers}')"
    api_write DELETE "/v1/mcpServer/consumers" "${current_consumer_body}"
fi

consumer_body="$(jq -cn \
    --arg name "${MCP_SERVER_NAME}" \
    --argjson consumers "${allowed_consumers}" \
    '{mcpServerName: $name, consumers: $consumers}')"

consumer_allowlist_matches() {
    local consumer_state
    consumer_state="$(api_get \
        "/v1/mcpServer/consumers?mcpServerName=${MCP_SERVER_NAME}")" || return 1
    jq -e --argjson expected "${allowed_consumers}" \
        '([.data[]?.consumerName] | sort) == ($expected | sort)' \
        <<<"${consumer_state}" >/dev/null
}

consumer_attempt=1
consumer_authorized=false
while [ "${consumer_attempt}" -le "${CONSUMER_MAX_ATTEMPTS}" ]; do
    if api_write PUT "/v1/mcpServer/consumers" "${consumer_body}" false true; then
        :
    fi
    if consumer_allowlist_matches; then
        consumer_authorized=true
        break
    fi
    if [ "${consumer_attempt}" -ge "${CONSUMER_MAX_ATTEMPTS}" ]; then
        break
    fi
    consumer_attempt=$((consumer_attempt + 1))
    sleep 2
done
test "${consumer_authorized}" = "true" || {
    echo "Higress consumer authorization did not converge" >&2
    exit 1
}

for consumer in \
    worker-agentloom-investigator \
    worker-agentloom-implementer \
    worker-agentloom-verifier; do
    consumer_result="$(api_get "/v1/mcpServer/consumers?mcpServerName=${MCP_SERVER_NAME}&consumerName=${consumer}")"
    test "$(jq -r '.total // 0' <<<"${consumer_result}")" = "1" || {
        echo "Expected consumer authorization was not persisted: ${consumer}" >&2
        exit 1
    }
done

manager_result="$(api_get "/v1/mcpServer/consumers?mcpServerName=${MCP_SERVER_NAME}&consumerName=manager")"
test "$(jq -r '.total // 0' <<<"${manager_result}")" = "0" || {
    echo "Manager must not be authorized for the Policy Broker" >&2
    exit 1
}

route_name="mcp-server-${MCP_SERVER_NAME}.internal"
route_result="$(api_get "/v1/routes/${route_name}")"
upstream_host="$(jq -r '.data.rewrite.host // .rewrite.host // empty' <<<"${route_result}")"
test "${upstream_host}" = "host.docker.internal" || {
    echo "Higress Policy Broker route resolved to an unexpected upstream host" >&2
    exit 1
}
assertion_header="X-AgentLoom-Gateway-Assertion ${GATEWAY_ASSERTION}"
kube_ingress_url="${KUBE_API}/apis/networking.k8s.io/v1/namespaces/${KUBE_NAMESPACE}/ingresses/${route_name}"
current_ingress="$(curl --insecure --fail --silent --show-error "${kube_ingress_url}")"
updated_ingress="$(ASSERTION_HEADER="${assertion_header}" jq -c \
    '.metadata.annotations["higress.io/enable-header-control"] = "true"
     | .metadata.annotations["higress.io/request-header-control-update"]
       = env.ASSERTION_HEADER' <<<"${current_ingress}")"
kube_status="$(curl --insecure --silent --show-error \
    --output /dev/null \
    --write-out "%{http_code}" \
    --request PUT \
    --header "Content-Type: application/json" \
    --data-binary @- \
    "${kube_ingress_url}" <<<"${updated_ingress}")"
test "${kube_status}" = "200" || {
    echo "Higress ingress assertion patch failed with HTTP ${kube_status}" >&2
    exit 1
}
persisted_ingress="$(curl --insecure --fail --silent --show-error "${kube_ingress_url}")"
ASSERTION_HEADER="${assertion_header}" jq -e \
    '.metadata.annotations["higress.io/enable-header-control"] == "true"
     and .metadata.annotations["higress.io/request-header-control-update"]
       == env.ASSERTION_HEADER' \
    <<<"${persisted_ingress}" >/dev/null || {
        echo "Higress gateway assertion annotations were not persisted" >&2
        exit 1
    }

jq -cn \
    --arg configuredAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg serverName "${MCP_SERVER_NAME}" \
    --arg gatewayUrl "${GATEWAY_URL}" \
    --arg upstreamUrl "${MCP_URL}" \
    --arg upstreamHost "${upstream_host}" \
    --arg serviceSource "${SERVICE_SOURCE_NAME}" \
    --argjson consumers "${allowed_consumers}" \
    '{
        schemaVersion: "agentloom.higress-policy-broker/v1alpha1",
        configuredAt: $configuredAt,
        serverName: $serverName,
        gatewayUrl: $gatewayUrl,
        upstreamUrl: $upstreamUrl,
        upstreamHost: $upstreamHost,
        serviceSource: $serviceSource,
        transport: "http",
        authentication: "key-auth",
        gatewayAssertionConfigured: true,
        allowedConsumers: $consumers,
        managerAuthorized: false
    }'
