[CmdletBinding()]
param(
    [string]$ApiKeyEnvironmentVariable = "QWEN_API_KEY",
    [string]$Model = "qwen3.7-plus",
    [string]$BaseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    [string[]]$Containers = @(
        "hiclaw-manager",
        "hiclaw-worker-agentloom-investigator",
        "hiclaw-worker-agentloom-implementer",
        "hiclaw-worker-agentloom-verifier"
    ),
    [switch]$SkipConnectionTest
)

$ErrorActionPreference = "Stop"

function Get-SecretFromEnvironment {
    param([Parameter(Mandatory)][string]$Name)

    foreach ($scope in @("Process", "User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }
    throw "Environment variable $Name is missing"
}

function Get-CoPawBaseUri {
    param([Parameter(Mandatory)][string]$Container)

    $containerPort = if ($Container -eq "hiclaw-manager") { 18799 } else { 8088 }
    $binding = & docker port $Container "$containerPort/tcp" 2>&1 |
        Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($binding)) {
        throw "Cannot resolve CoPaw port for $Container"
    }
    if ($binding -notmatch ":(?<port>\d+)$") {
        throw "Unexpected docker port output for ${Container}: $binding"
    }
    return "http://127.0.0.1:$($Matches.port)"
}

function Invoke-CoPaw {
    param(
        [Parameter(Mandatory)][string]$BaseUri,
        [Parameter(Mandatory)][ValidateSet("Get", "Post", "Put")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body
    )

    $arguments = @{
        Method = $Method
        Uri = "$BaseUri$Path"
        TimeoutSec = 90
    }
    if ($null -ne $Body) {
        $arguments.ContentType = "application/json"
        $arguments.Body = $Body | ConvertTo-Json -Depth 10
    }
    return Invoke-RestMethod @arguments
}

function Wait-CoPawApiReady {
    param(
        [Parameter(Mandatory)][string]$BaseUri,
        [Parameter(Mandatory)][string]$Container,
        [int]$TimeoutSeconds = 120
    )

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $null = Invoke-CoPaw -BaseUri $BaseUri -Method Get `
                -Path "/api/models" -Body $null
            return
        }
        catch {
            Start-Sleep -Seconds 3
        }
    }
    throw "CoPaw API did not become ready in $Container within $TimeoutSeconds seconds"
}

$secretValue = Get-SecretFromEnvironment -Name $ApiKeyEnvironmentVariable
$results = foreach ($container in $Containers) {
    $baseUri = Get-CoPawBaseUri -Container $container
    Wait-CoPawApiReady -BaseUri $baseUri -Container $container
    $config = @{
        api_key = $secretValue
        base_url = $BaseUrl
        chat_model = "OpenAIChatModel"
        generate_kwargs = @{
            temperature = 0.1
            max_tokens = 4096
        }
    }
    $null = Invoke-CoPaw -BaseUri $baseUri -Method Put `
        -Path "/api/models/dashscope/config" -Body $config

    $providers = Invoke-CoPaw -BaseUri $baseUri -Method Get `
        -Path "/api/models" -Body $null
    $dashscope = $providers | Where-Object { $_.id -eq "dashscope" }
    if ($null -eq $dashscope) {
        throw "DashScope provider is unavailable in $container"
    }
    $modelIds = (@($dashscope.models) + @($dashscope.extra_models)) |
        ForEach-Object { $_.id }
    if ($Model -notin $modelIds) {
        $null = Invoke-CoPaw -BaseUri $baseUri -Method Post `
            -Path "/api/models/dashscope/models" `
            -Body @{ id = $Model; name = $Model }
    }

    $active = Invoke-CoPaw -BaseUri $baseUri -Method Put `
        -Path "/api/models/active" `
        -Body @{ provider_id = "dashscope"; model = $Model; scope = "global" }

    $connectionVerified = $false
    if (-not $SkipConnectionTest) {
        $probe = Invoke-CoPaw -BaseUri $baseUri -Method Post `
            -Path "/api/models/dashscope/models/test" `
            -Body @{ model_id = $Model }
        if (-not $probe.success) {
            throw "DashScope model probe failed in $container"
        }
        $connectionVerified = $true
    }

    [ordered]@{
        container = $container
        provider = $active.active_llm.provider_id
        model = $active.active_llm.model
        connectionVerified = $connectionVerified
    }
}

$results | ConvertTo-Json -Depth 5
